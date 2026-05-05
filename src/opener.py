from __future__ import annotations

import subprocess
import webbrowser


# Maps file_type values to their Office URI scheme prefixes.
_OFFICE_SCHEMES: dict[str, str] = {
    "docx": "ms-word:ofe|u|",
    "xlsx": "ms-excel:ofe|u|",
    "pptx": "ms-powerpoint:ofe|u|",
}


def open_file(file: dict, use_browser: bool = False) -> None:
    """Open a SharePoint file using the best available method.

    Parameters
    ----------
    file:
        Dict with keys ``name``, ``path``, ``url``, ``file_type``.
    use_browser:
        When *True* always open the URL in the default web browser.
        When *False* (default) Office files are opened via their
        ``ms-word/ms-excel/ms-powerpoint`` URI schemes so they open in
        the local desktop application.  PDFs have no ``ms-pdf`` protocol
        on Windows so they always fall back to the browser.
    """
    url: str = file["url"]
    file_type: str = file.get("file_type", "").lower()

    if use_browser:
        webbrowser.open(url)
        return

    scheme_prefix = _OFFICE_SCHEMES.get(file_type)
    if scheme_prefix:
        office_uri = f"{scheme_prefix}{url}"
        # Use cmd /c start "" <uri> so Windows resolves the protocol handler.
        subprocess.Popen(
            ["cmd", "/c", "start", "", office_uri],
            shell=False,
            # Suppress the console window that would briefly flash.
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    else:
        # pdf and any unknown type → browser
        webbrowser.open(url)
