from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

# Hostnames that indicate the browser has been redirected to a Microsoft
# login page rather than staying on the SharePoint tenant.
_LOGIN_HOSTNAMES = ("login.microsoftonline.com", "login.live.com")


def _is_login_page(url: str) -> bool:
    return any(h in url for h in _LOGIN_HOSTNAMES)


class AuthManager:
    """Manages Playwright browser sessions for SharePoint authentication."""

    def __init__(self, session_path: Path) -> None:
        self._session_path = session_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_session(self) -> bool:
        """Return True when a saved Playwright storage-state file exists."""
        return self._session_path.exists()

    def login_interactive(self, sharepoint_url: str) -> bool:
        """Open a *visible* Edge browser so the user can sign in interactively.

        After the user completes the login flow the Playwright storage state
        (cookies + local storage) is saved to ``session_path``.

        Returns True when the browser lands on a SharePoint page (i.e. the
        user successfully authenticated) and False when the final URL still
        looks like a Microsoft login page.
        """
        self._session_path.parent.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=False)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto(sharepoint_url, wait_until="domcontentloaded", timeout=60_000)

                # Wait until the user is no longer on a login page.  Poll
                # every 500 ms; give the user up to 5 minutes to complete MFA.
                page.wait_for_function(
                    """() => !window.location.href.includes('login.microsoftonline.com')
                            && !window.location.href.includes('login.live.com')""",
                    timeout=300_000,
                    polling=500,
                )

                final_url = page.url
                if _is_login_page(final_url):
                    return False

                # Persist cookies / storage so headless runs can reuse the session.
                context.storage_state(path=str(self._session_path))
                return True
            finally:
                browser.close()

    def clear_session(self) -> None:
        """Delete the saved session file (forces re-authentication)."""
        if self._session_path.exists():
            self._session_path.unlink()
