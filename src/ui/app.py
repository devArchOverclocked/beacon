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
            settings_saved_cb=self._reschedule_refresh,
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
        # Interval may have changed — restart the timer with correct delay.
        self._reschedule_refresh()

    # ------------------------------------------------------------------
    # Global hotkey
    # ------------------------------------------------------------------

    def _start_hotkey_listener(self) -> None:
        """Start a pynput Listener that fires only when the full combo is satisfied."""
        try:
            hotkey_str = self._config.hotkey

            def on_hotkey() -> None:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._window.show_and_focus)

            self._hotkey_listener = _build_hotkey_listener(hotkey_str, on_hotkey)

            self._hotkey_thread = threading.Thread(
                target=self._hotkey_listener.run,
                daemon=True,
                name="beacon-hotkey",
            )
            self._hotkey_thread.start()
        except Exception as exc:
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
        """Schedule the next background index refresh.

        Accounts for elapsed time since the last index so the app catches up
        after a long shutdown instead of waiting a full interval from startup.
        """
        interval_seconds = self._config.refresh_interval_hours * 3600

        last = self._db.get_last_indexed()
        if last is None:
            # Never indexed — refresh soon after startup.
            delay = 10.0
        else:
            elapsed = (time.time() - last.replace(tzinfo=None).timestamp())
            remaining = interval_seconds - elapsed
            # At least 10 s so we don't hammer the indexer immediately.
            delay = max(10.0, remaining)

        def _run() -> None:
            self._do_background_refresh()
            self._schedule_refresh()

        self._refresh_timer = threading.Timer(delay, _run)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _reschedule_refresh(self) -> None:
        """Cancel any pending timer and reschedule — call after settings save."""
        self._cancel_refresh_timer()
        self._schedule_refresh()

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
# Custom hotkey listener (avoids phantom-key false triggers)
# ---------------------------------------------------------------------------

def _build_hotkey_listener(hotkey_str: str, callback):
    """Return a pynput Listener that fires *callback* only when the complete
    hotkey combo is pressed.

    Modifier keys are tracked explicitly; the callback fires only on the
    keydown of the non-modifier trigger key while the exact modifiers are
    held.  This prevents phantom-key false triggers (e.g. Ctrl alone
    firing Ctrl+Space when a previous Space key-up was missed).
    """
    from pynput import keyboard as _kb

    _MOD_VARIANTS: dict[str, tuple] = {
        "ctrl":  (_kb.Key.ctrl,  _kb.Key.ctrl_l,  _kb.Key.ctrl_r),
        "alt":   (_kb.Key.alt,   _kb.Key.alt_l,   _kb.Key.alt_r),
        "shift": (_kb.Key.shift, _kb.Key.shift_l, _kb.Key.shift_r),
        "cmd":   (_kb.Key.cmd,   _kb.Key.cmd_l,   _kb.Key.cmd_r),
    }
    _SPECIAL_TRIGGER: dict[str, _kb.Key] = {
        "space": _kb.Key.space,
        "enter": _kb.Key.enter,
        "tab":   _kb.Key.tab,
        "esc":   _kb.Key.esc,
        **{f"f{i}": getattr(_kb.Key, f"f{i}") for i in range(1, 13)},
    }

    required_mods: set[str] = set()
    trigger_key = None
    for part in hotkey_str.lower().split("+"):
        part = part.strip()
        if part in _MOD_VARIANTS:
            required_mods.add(part)
        elif part in _SPECIAL_TRIGGER:
            trigger_key = _SPECIAL_TRIGGER[part]
        else:
            trigger_key = _kb.KeyCode.from_char(part)

    pressed_mods: set[str] = set()

    def _mod_name(key) -> str | None:
        for name, variants in _MOD_VARIANTS.items():
            if key in variants:
                return name
        return None

    def on_press(key) -> None:
        mod = _mod_name(key)
        if mod is not None:
            pressed_mods.add(mod)
        elif key == trigger_key and pressed_mods == required_mods:
            callback()

    def on_release(key) -> None:
        mod = _mod_name(key)
        if mod is not None:
            pressed_mods.discard(mod)

    listener = _kb.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    return listener
