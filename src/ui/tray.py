from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from src.config import Config
from src.db import Database
from src.ui.styles import ACCENT


# ---------------------------------------------------------------------------
# Helper: build a simple "B" icon from scratch
# ---------------------------------------------------------------------------

def _make_tray_icon() -> QIcon:
    """Create a 16×16 blue square with white 'B' letter as the tray icon."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(0, 0, 0, 0))  # transparent base

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Blue background
    painter.setBrush(QColor(ACCENT))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawRoundedRect(0, 0, 16, 16, 3, 3)

    # White "B"
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setPixelSize(11)
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(0, 0, 16, 16, 0x84, "B")  # 0x84 = AlignHCenter | AlignVCenter
    painter.end()

    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Signal bridge — lets background threads emit Qt signals safely
# ---------------------------------------------------------------------------

class _Signals(QObject):
    indexing_done = pyqtSignal(object)   # IndexResult
    indexing_error = pyqtSignal(str)


# ---------------------------------------------------------------------------
# Tray
# ---------------------------------------------------------------------------

class BeaconTray(QSystemTrayIcon):
    """System tray icon with context menu for Beacon."""

    def __init__(
        self,
        config: Config,
        db: Database,
        indexer,          # Indexer — avoid circular import with string type
        show_window_cb: Callable[[], None],
        settings_saved_cb: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(_make_tray_icon())
        self._config = config
        self._db = db
        self._indexer = indexer
        self._show_window_cb = show_window_cb
        self._settings_saved_cb = settings_saved_cb
        self._signals = _Signals()
        self._signals.indexing_done.connect(self._on_indexing_done)

        self._build_menu()
        self.setToolTip("Beacon — SharePoint file finder")
        self.update_index_status()

    # ------------------------------------------------------------------
    # Menu construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()

        # Title (disabled)
        title_action = menu.addAction("Beacon")
        title_action.setEnabled(False)

        menu.addSeparator()

        # Dynamic status items
        self._last_indexed_action = menu.addAction("Last indexed: never")
        self._last_indexed_action.setEnabled(False)

        self._file_count_action = menu.addAction("0 files in index")
        self._file_count_action.setEnabled(False)

        menu.addSeparator()

        # Open window
        open_action = menu.addAction("Open Beacon")
        open_action.triggered.connect(self._show_window_cb)

        # Refresh index
        self._refresh_action = menu.addAction("Refresh Index Now")
        self._refresh_action.triggered.connect(self._on_refresh_triggered)

        menu.addSeparator()

        # Settings
        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self._open_settings)

        # Quit
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)

        self.setContextMenu(menu)
        self._menu = menu

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_index_status(self) -> None:
        """Refresh 'last indexed' and file count labels from the database."""
        count = self._db.get_file_count()
        self._file_count_action.setText(f"{count:,} files in index")

        last = self._db.get_last_indexed()
        if last is None:
            self._last_indexed_action.setText("Last indexed: never")
        else:
            self._last_indexed_action.setText(
                f"Last indexed: {_format_relative(last)}"
            )

    def set_indexing(self, running: bool) -> None:
        """Grey out the refresh action while indexing is in progress."""
        self._refresh_action.setEnabled(not running)
        if running:
            self._refresh_action.setText("Indexing…")
        else:
            self._refresh_action.setText("Refresh Index Now")

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_refresh_triggered(self) -> None:
        self.set_indexing(True)
        self.showMessage("Beacon", "Indexing SharePoint files…", QSystemTrayIcon.MessageIcon.Information, 3000)
        thread = threading.Thread(target=self._run_indexer, daemon=True)
        thread.start()

    def _run_indexer(self) -> None:
        """Run in a background thread; emit signal when done."""
        try:
            result = self._indexer.run()
            self._signals.indexing_done.emit(result)
        except Exception as exc:
            self._signals.indexing_done.emit(None)

    def _on_indexing_done(self, result) -> None:
        self.set_indexing(False)
        self.update_index_status()

        if result is None or result.error:
            msg = result.error if result else "Unknown error"
            self.showMessage(
                "Beacon — Index Error",
                msg,
                QSystemTrayIcon.MessageIcon.Critical,
                5000,
            )
        else:
            self.showMessage(
                "Beacon",
                f"Done — {result.count:,} files indexed",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    def _open_settings(self) -> None:
        from src.auth import AuthManager
        from src.ui.settings import SettingsDialog

        # Reconstruct auth — it holds no state beyond the path
        auth = AuthManager(self._config.session_path)
        dlg = SettingsDialog(self._config, auth, self._indexer, self._db)
        dlg.exec()
        self.update_index_status()
        if self._settings_saved_cb is not None:
            self._settings_saved_cb()

    def _quit(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_relative(dt: datetime) -> str:
    """Return a human-readable relative time string."""
    now = datetime.utcnow()
    delta = now - dt.replace(tzinfo=None)
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"
