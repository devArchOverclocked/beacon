from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

from playwright.sync_api import sync_playwright

from src.auth import AuthManager, _is_login_page
from src.config import Config
from src.db import Database

# ---------------------------------------------------------------------------
# JavaScript executed inside the page context to call the Lists REST API.
# Handles pagination via the __next link SharePoint includes when there
# are more items than $top allows.
# ---------------------------------------------------------------------------
_FETCH_JS = """
async (startUrl) => {
    try {
        let results = [];
        let nextUrl = startUrl;
        while (nextUrl) {
            const r = await fetch(nextUrl, {
                headers: { 'Accept': 'application/json;odata=verbose' }
            });
            if (!r.ok) return { __error: r.status };
            const data = await r.json();
            if (data.d && data.d.results) {
                results = results.concat(data.d.results);
            }
            nextUrl = (data.d && data.d.__next) ? data.d.__next : null;
        }
        return { results: results };
    } catch(e) {
        return { __error: e.message };
    }
}
"""

# Items per page — SharePoint hard-caps at 5000; well above our expected count.
_ROW_LIMIT = 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_root_url(url: str) -> str:
    """Strip SharePoint view suffixes so we get the plain folder URL.

    SharePoint library URLs often look like:
        .../Deliverables/Forms/AllItems.aspx?RootFolder=...
    The actual folder path is everything before /Forms/.

    Examples:
        .../Deliverables/Forms/AllItems.aspx → .../Deliverables
        .../Deliverables/                    → .../Deliverables  (unchanged)
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    forms_idx = path.lower().find("/forms/")
    if forms_idx != -1:
        path = path[:forms_idx]
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", "")
    )


def _site_base(folder_url: str) -> str:
    """Extract the SharePoint site base URL — one level up from the library folder.

    Works for any URL depth, including custom domains:
        https://goto.netcompany.com/cases/GTO547/ATPBOS/Deliverables
        → https://goto.netcompany.com/cases/GTO547/ATPBOS

        https://contoso.sharepoint.com/sites/MyTeam/Documents
        → https://contoso.sharepoint.com/sites/MyTeam
    """
    parsed = urllib.parse.urlparse(folder_url)
    segments = [s for s in parsed.path.split("/") if s]
    base_path = "/" + "/".join(segments[:-1]) if len(segments) > 1 else "/"
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, base_path, "", "", "")
    )


_SUPPORTED_TYPES = {"docx", "xlsx", "pptx", "pdf"}


def _build_api_url(site_base: str, folder_url: str, row_limit: int = _ROW_LIMIT) -> str:
    """Build the SharePoint Lists REST API URL for the library at folder_url."""
    server_rel_path = urllib.parse.urlparse(folder_url).path
    type_clauses = " or ".join(
        f"File_x0020_Type eq '{t}'" for t in sorted(_SUPPORTED_TYPES)
    )
    odata_filter = f"FSObjType eq 0 and ({type_clauses})"
    params = urllib.parse.urlencode(
        {
            "$select": "FileLeafRef,FileRef,File_x0020_Type",
            "$filter": odata_filter,
            "$top": str(row_limit),
        }
    )
    return f"{site_base}/_api/web/GetList('{server_rel_path}')/items?{params}"


def _parse_items(data: dict, folder_url: str) -> list[dict]:
    """Parse the Lists REST API response into file dicts."""
    parsed = urllib.parse.urlparse(folder_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    lib_path = parsed.path.rstrip("/")

    files: list[dict] = []
    for item in data.get("results", []):
        file_ref = item.get("FileRef", "")
        name = item.get("FileLeafRef", "")
        file_type = (item.get("File_x0020_Type") or "").lower()

        if not name or not file_ref:
            continue

        url = base_url + file_ref

        # Relative folder path: strip library root and filename
        rel = file_ref[len(lib_path):].strip("/")
        rel = rel.rsplit("/", 1)[0] if "/" in rel else ""

        files.append({"name": name, "path": rel, "url": url, "file_type": file_type})
    return files


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


@dataclass
class IndexResult:
    count: int
    duration_seconds: float
    error: str | None = None


class Indexer:
    """Crawls a SharePoint document library using the Search REST API and
    stores the results in the local SQLite database."""

    def __init__(self, config: Config, auth: AuthManager, db: Database) -> None:
        self._config = config
        self._auth = auth
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        on_progress: Callable[[str], None] | None = None,
        row_limit: int = _ROW_LIMIT,
    ) -> IndexResult:
        """Index all matching files and refresh the database.

        Steps:
        1. Open headless Edge with the saved Playwright session state.
        2. Navigate to the SharePoint root URL to refresh auth cookies.
        3. Detect redirect to login → return an error IndexResult.
        4. Call the SharePoint Search REST API via page.evaluate().
        5. Parse the results.
        6. Clear the DB and write fresh records.
        7. Return an IndexResult.
        """

        def _notify(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        start = time.monotonic()
        # Strip SharePoint view suffixes (/Forms/AllItems.aspx etc.)
        folder_url = _clean_root_url(self._config.sharepoint_root_url)

        files: list[dict] = []
        result_error: str | None = None

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            try:
                ctx_kwargs: dict = {}
                if self._auth.has_session():
                    ctx_kwargs["storage_state"] = str(self._auth._session_path)

                context = browser.new_context(**ctx_kwargs)
                page = context.new_page()

                # --------------------------------------------------------
                # Step 2 – navigate to root to hydrate auth cookies
                # --------------------------------------------------------
                _notify("Navigating to SharePoint…")
                page.goto(folder_url, wait_until="domcontentloaded", timeout=30_000)

                # --------------------------------------------------------
                # Step 3 – login check
                # --------------------------------------------------------
                if _is_login_page(page.url):
                    result_error = "Session expired — please log in again."
                else:
                    # --------------------------------------------------------
                    # Step 4 – call Search REST API
                    # --------------------------------------------------------
                    site_base = _site_base(folder_url)
                    api_url = _build_api_url(site_base, folder_url, row_limit)
                    _notify("Querying SharePoint library…")

                    data = page.evaluate(_FETCH_JS, api_url)

                    if not isinstance(data, dict):
                        result_error = f"Unexpected API response: {type(data).__name__}"
                    elif "__error" in data:
                        result_error = f"Lists API error {data['__error']} — check the root URL in Settings"
                    else:
                        # --------------------------------------------------------
                        # Step 5 – parse + write
                        # --------------------------------------------------------
                        _notify("Parsing results…")
                        files = _parse_items(data, folder_url)
                        _notify(f"Writing {len(files)} file(s) to database…")
                        self._db.clear_files()
                        if files:
                            self._db.upsert_files(files)

            except Exception as exc:
                result_error = f"{type(exc).__name__}: {exc}"
            finally:
                browser.close()

        duration = time.monotonic() - start
        if result_error:
            return IndexResult(count=0, duration_seconds=duration, error=result_error)
        _notify(f"Done — {len(files)} file(s) in {duration:.1f}s.")
        return IndexResult(count=len(files), duration_seconds=duration)

    def is_session_valid(self) -> bool:
        """Headless check: navigate to the SharePoint root and verify we are
        *not* redirected to a Microsoft login page."""
        if not self._auth.has_session():
            return False

        folder_url = _clean_root_url(self._config.sharepoint_root_url)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            try:
                context = browser.new_context(
                    storage_state=str(self._auth._session_path)
                )
                page = context.new_page()
                page.goto(folder_url, wait_until="domcontentloaded", timeout=30_000)
                return not _is_login_page(page.url)
            except Exception:
                return False
            finally:
                browser.close()
