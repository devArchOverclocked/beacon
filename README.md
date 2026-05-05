# Beacon

A lightweight Windows desktop tool for fuzzy-finding and opening files in SharePoint — no browser tab hunting, no folder archaeology.

Press a hotkey anywhere, type part of a filename or path, hit Enter. Done.

---

## How it works

**Indexer** (runs on demand + background timer):
- Uses a headless browser (system Edge — no download required) to authenticate against SharePoint
- Calls the SharePoint Search REST API to enumerate all Word, Excel, PowerPoint, and PDF files under a configured root folder
- Writes results to a local SQLite database (~milliseconds to search)

**Search UI** (always running in system tray):
- Global hotkey (default `Ctrl+Space`) opens a floating search bar
- Fuzzy-matches file name + path on every keystroke via `rapidfuzz`
- Enter opens the file in the local Office app via the `ms-word:` / `ms-excel:` / `ms-powerpoint:` protocol
- Right-click any result to open in browser instead

The index is read-only local data — no VPN or network needed to search.

---

## First-time setup (each team member)

1. **Install Python 3.11+** from python.org (check "Add to PATH")
2. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```
3. **Run Beacon:**
   ```
   python beacon.py
   ```
4. A settings dialog opens. Enter the SharePoint folder URL (e.g. `https://yourcompany.sharepoint.com/sites/Designs/Shared%20Documents/Designs`).
5. Click **Login to SharePoint** — a browser window opens. Log in with your company account. Close when done.
6. Click **Fetch Index Now** — takes a few seconds for a few hundred files.
7. Beacon minimises to the system tray. Press `Ctrl+Space` to search.

---

## Distributing to the team

Build a standalone `.exe` on a Windows machine (no Python needed by recipients):

```bat
build.bat
```

Share `dist/Beacon.exe`. Each team member runs it once, completes the setup wizard above, and is done.

---

## Usage

| Action | How |
|---|---|
| Open Beacon | `Ctrl+Space` (configurable) |
| Navigate results | `↑` / `↓` arrow keys |
| Open in Office app | `Enter` |
| Open in browser | `Ctrl+Enter` or right-click → Open in browser |
| Dismiss | `Escape` |
| Refresh index | System tray → Refresh Now |
| Settings | System tray → Settings |

---

## Configuration

Settings are stored in `%APPDATA%\Beacon\config.json`:

| Key | Default | Description |
|---|---|---|
| `sharepoint_root_url` | _(required)_ | SharePoint folder URL to index |
| `refresh_interval_hours` | `4` | Background re-index interval |
| `hotkey` | `ctrl+space` | Global hotkey to open search |
| `open_in_browser` | `false` | Default open target |

---

## File types

| Type | Opens with |
|---|---|
| `.docx` | `ms-word:ofe\|u\|<url>` |
| `.xlsx` | `ms-excel:ofe\|u\|<url>` |
| `.pptx` | `ms-powerpoint:ofe\|u\|<url>` |
| `.pdf` | Default browser |

---

## Architecture

```
beacon.py               Entry point
src/
  config.py             JSON config in %APPDATA%/Beacon/
  db.py                 SQLite index
  auth.py               Playwright session management (system Edge)
  indexer.py            SharePoint Search REST API crawler
  search.py             rapidfuzz search against in-memory index
  opener.py             Office protocol handlers
  ui/
    app.py              QApplication, hotkey thread, background refresh
    window.py           Frameless spotlight-style search window
    tray.py             System tray icon + menu
    settings.py         First-run and settings dialog
    styles.py           QSS dark theme
```

---

## Requirements

- Windows 10 / 11
- Microsoft Edge (pre-installed on all modern Windows — no separate browser download)
- Microsoft 365 account with access to the SharePoint library
- VPN required only during index refresh
