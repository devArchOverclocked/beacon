from __future__ import annotations

import sys
import threading
import time
from typing import Callable


def _build_indexer(config, auth, db):
    """Lazy import to avoid loading playwright at module level."""
    from src.indexer import Indexer
    return Indexer(config=config, auth=auth, db=db)


class BeaconApp:
    """Top-level orchestrator for the Beacon application."""

    def __init__(self) -> None:
        # QApplication must be created before any other Qt objects.
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt

        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setApplicationName("Beacon")
        self._app.setQuitOnLastWindowClosed(False)

        # Load subsystems
        from src.config import Config
        from src.db import Database
        from src.auth import AuthManager
        from src.search import Searcher
        from src.ui.styles import get_stylesheet

        self._config = Config.load()
        self._db = Database(self._config.db_path)
        self._auth = AuthManager(self._config.session_path)
        self._indexer = _build_indexer(self._config, self._auth, self._db)
        self._searcher = Searcher(self._db)

        # Apply global stylesheet
        self._app.setStyleSheet(get_stylesheet())

        # Build UI components
        from src.ui.window import BeaconWindow
        from src.ui.tray import BeaconTray

        self._window = BeaconWindow(self._searcher, self._config)
        self._tray = BeaconTray(
            config=self._config,
            db=self._db,
            indexer=self._indexer,
            show_window_cb=self._window.show_and_focus,
        )
        self._tray.show()

        # Background refresh state
        self._refresh_timer: threading.Timer | None = None
        self._refresh_lock = threading.Lock()

        # Hotkey listener thread handle
        self._hotkey_thread: threading.Thread | None = None
        self._hotkey_listener = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> int:
        from PyQt6.QtWidgets import QApplication

        # First-run: open settings dialog
        if not self._config.is_configured():
            self._open_settings()

        # Start global hotkey listener
        self._start_hotkey_listener()

        # Start background auto-refresh
        self._schedule_refresh()

        exit_code = self._app.exec()

        # Cleanup
        self._stop_hotkey_listener()
        self._cancel_refresh_timer()

        return exit_code

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        from src.ui.settings import SettingsDialog
        dlg = SettingsDialog(
            config=self._config,
            auth=self._auth,
            indexer=self._indexer,
            db=self._db,
        )
        dlg.exec()
        # Reload searcher after potential index run in settings
        self._searcher.reload()
        self._tray.update_index_status()

    # ------------------------------------------------------------------
    # Global hotkey
    # ------------------------------------------------------------------

    def _start_hotkey_listener(self) -> None:
        """Start pynput GlobalHotKeys in a daemon thread."""
        try:
            from pynput import keyboard as _kb

            hotkey_str = self._config.hotkey  # e.g. "ctrl+space"
            # pynput expects e.g. "<ctrl>+<space>" or "<ctrl>+a"
            pynput_combo = _to_pynput_hotkey(hotkey_str)

            def on_hotkey() -> None:
                # Must dispatch to main thread
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._window.show_and_focus)

            hotkeys = {pynput_combo: on_hotkey}
            self._hotkey_listener = _kb.GlobalHotKeys(hotkeys)
            self._hotkey_listener.daemon = True

            self._hotkey_thread = threading.Thread(
                target=self._hotkey_listener.run,
                daemon=True,
                name="beacon-hotkey",
            )
            self._hotkey_thread.start()
        except Exception as exc:
            # Non-fatal: hotkey simply won't work (e.g. no display on CI)
            print(f"[Beacon] Could not register hotkey: {exc}", file=sys.stderr)

    def _stop_hotkey_listener(self) -> None:
        try:
            if self._hotkey_listener is not None:
                self._hotkey_listener.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Background refresh
    # ------------------------------------------------------------------

    def _schedule_refresh(self) -> None:
        """Schedule the next background index refresh."""
        interval_seconds = self._config.refresh_interval_hours * 3600

        def _run() -> None:
            self._do_background_refresh()
            # Re-schedule for the next cycle
            self._schedule_refresh()

        self._refresh_timer = threading.Timer(interval_seconds, _run)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _cancel_refresh_timer(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
            self._refresh_timer = None

    def _do_background_refresh(self) -> None:
        with self._refresh_lock:
            try:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._tray.set_indexing(True))

                result = self._indexer.run()

                # Reload searcher on the main thread is not strictly necessary
                # since Searcher._files is replaced atomically, but we call
                # reload() here from the background thread for simplicity.
                self._searcher.reload()

                QTimer.singleShot(0, self._tray.update_index_status)
                QTimer.singleShot(0, lambda: self._tray.set_indexing(False))

                if result and not result.error:
                    QTimer.singleShot(
                        0,
                        lambda: self._window.update_status()
                    )
            except Exception as exc:
                print(f"[Beacon] Background refresh failed: {exc}", file=sys.stderr)
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._tray.set_indexing(False))


# ---------------------------------------------------------------------------
# pynput hotkey string conversion
# ---------------------------------------------------------------------------

def _to_pynput_hotkey(hotkey: str) -> str:
    """Convert e.g. 'ctrl+space' → '<ctrl>+<space>', 'ctrl+a' → '<ctrl>+a'."""
    _SPECIAL = {
        "ctrl": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "cmd": "<cmd>",
        "win": "<cmd>",
        "space": "<space>",
        "enter": "<enter>",
        "tab": "<tab>",
        "esc": "<esc>",
        "escape": "<esc>",
        "up": "<up>",
        "down": "<down>",
        "left": "<left>",
        "right": "<right>",
        "f1": "<f1>", "f2": "<f2>", "f3": "<f3>", "f4": "<f4>",
        "f5": "<f5>", "f6": "<f6>", "f7": "<f7>", "f8": "<f8>",
        "f9": "<f9>", "f10": "<f10>", "f11": "<f11>", "f12": "<f12>",
    }
    parts = hotkey.lower().split("+")
    converted = []
    for part in parts:
        part = part.strip()
        converted.append(_SPECIAL.get(part, part))
    return "+".join(converted)
