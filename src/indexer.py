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
# JavaScript executed inside the page context to call the Search REST API.
# Using fetch from the page avoids CORS issues because the request originates
# from the same origin as the SharePoint tenant.
# ---------------------------------------------------------------------------
_FETCH_JS = """
async (apiUrl) => {
    try {
        const r = await fetch(apiUrl, {
            headers: { 'Accept': 'application/json;odata=verbose' }
        });
        if (!r.ok) return { __error: r.status };
        return await r.json();
    } catch(e) {
        return { __error: e.message };
    }
}
"""

# Maximum number of results returned per Search API call.
_ROW_LIMIT = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _site_base(sharepoint_root_url: str) -> str:
    """Extract the site-base URL (scheme + host + first two path segments).

    Example:
        https://contoso.sharepoint.com/sites/MyTeam/Shared%20Documents
        → https://contoso.sharepoint.com/sites/MyTeam
    """
    parsed = urllib.parse.urlparse(sharepoint_root_url)
    segments = [s for s in parsed.path.split("/") if s]
    # Keep up to 2 segments: ["sites", "<site-name>"]
    base_path = "/" + "/".join(segments[:2]) if len(segments) >= 2 else parsed.path
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, base_path, "", "", "")
    )


def _build_api_url(site_base: str, root_url: str, row_limit: int = _ROW_LIMIT) -> str:
    """Build the SharePoint Search REST API URL."""
    query_text = (
        f'Path:"{root_url}*" AND '
        "(FileType:docx OR FileType:xlsx OR FileType:pptx OR FileType:pdf)"
    )
    params = urllib.parse.urlencode(
        {
            "querytext": f"'{query_text}'",
            "selectproperties": "'Title,Path,FileType,Filename,ParentLink'",
            "rowlimit": str(row_limit),
            "trimduplicates": "false",
        }
    )
    return f"{site_base}/_api/search/query?{params}"


def _parse_rows(data: dict, root_url: str) -> list[dict]:
    """Parse the odata=verbose search response into a list of file dicts."""
    try:
        rows = (
            data["d"]["query"]["PrimaryQueryResult"]["RelevantResults"]["Table"][
                "Rows"
            ]["results"]
        )
    except (KeyError, TypeError):
        return []

    files: list[dict] = []
    # Normalise the root URL for relative-path stripping (no trailing slash).
    root_normalised = root_url.rstrip("/")

    for row in rows:
        cells = {c["Key"]: c["Value"] for c in row["Cells"]["results"]}
        name = cells.get("Filename") or cells.get("Title") or ""
        url = cells.get("Path", "")
        file_type = (cells.get("FileType") or "").lower()
        parent = cells.get("ParentLink", "")

        # Build a short human-readable relative path for display in the UI.
        if parent.startswith(root_normalised):
            rel = parent[len(root_normalised):].strip("/")
        else:
            # Fall back to the full parent link when the root prefix is absent.
            rel = parent

        if not name or not url:
            continue

        files.append(
            {
                "name": name,
                "path": rel,
                "url": url,
                "file_type": file_type,
            }
        )
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
        root_url = self._config.sharepoint_root_url

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
                page.goto(root_url, wait_until="domcontentloaded", timeout=30_000)

                # --------------------------------------------------------
                # Step 3 – login check
                # --------------------------------------------------------
                if _is_login_page(page.url):
                    duration = time.monotonic() - start
                    return IndexResult(
                        count=0,
                        duration_seconds=duration,
                        error="Session expired — please log in again.",
                    )

                # --------------------------------------------------------
                # Step 4 – call Search REST API
                # --------------------------------------------------------
                site_base = _site_base(root_url)
                api_url = _build_api_url(site_base, root_url, row_limit)
                _notify("Querying SharePoint Search API…")

                data = page.evaluate(_FETCH_JS, api_url)

                if not isinstance(data, dict):
                    duration = time.monotonic() - start
                    return IndexResult(
                        count=0,
                        duration_seconds=duration,
                        error=f"Unexpected API response type: {type(data).__name__}",
                    )

                if "__error" in data:
                    duration = time.monotonic() - start
                    return IndexResult(
                        count=0,
                        duration_seconds=duration,
                        error=f"Search API error: {data['__error']}",
                    )

                # --------------------------------------------------------
                # Step 5 – parse results
                # --------------------------------------------------------
                _notify("Parsing search results…")
                files = _parse_rows(data, root_url)

                # --------------------------------------------------------
                # Step 6 – refresh database
                # --------------------------------------------------------
                _notify(f"Writing {len(files)} file(s) to database…")
                self._db.clear_files()
                if files:
                    self._db.upsert_files(files)

            finally:
                browser.close()

        duration = time.monotonic() - start
        _notify(f"Indexing complete — {len(files)} file(s) in {duration:.1f}s.")
        return IndexResult(count=len(files), duration_seconds=duration)

    def is_session_valid(self) -> bool:
        """Headless check: navigate to the SharePoint root and verify we are
        *not* redirected to a Microsoft login page."""
        if not self._auth.has_session():
            return False

        root_url = self._config.sharepoint_root_url
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            try:
                context = browser.new_context(
                    storage_state=str(self._auth._session_path)
                )
                page = context.new_page()
                page.goto(root_url, wait_until="domcontentloaded", timeout=30_000)
                return not _is_login_page(page.url)
            except Exception:
                return False
            finally:
                browser.close()
