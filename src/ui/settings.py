from __future__ import annotations

import threading
from typing import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.auth import AuthManager
from src.config import Config
from src.db import Database
from src.ui.styles import ACCENT, SUBTEXT, TEXT, get_stylesheet


# ---------------------------------------------------------------------------
# Thread-safe signal bridge
# ---------------------------------------------------------------------------

class _WorkerSignals(QObject):
    login_done = pyqtSignal(bool)       # success
    index_progress = pyqtSignal(str)    # progress message
    index_done = pyqtSignal(object)     # IndexResult | None


# ---------------------------------------------------------------------------
# Hotkey capture field
# ---------------------------------------------------------------------------

class _HotkeyEdit(QLineEdit):
    """Read-only field that captures key combinations and formats them."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click and press a key combination…")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        mods = event.modifiers()

        # Ignore bare modifier keys
        if key in (
            Qt.Key.Key_Control, Qt.Key.Key_Shift,
            Qt.Key.Key_Alt, Qt.Key.Key_Meta,
            Qt.Key.Key_unknown,
        ):
            return

        parts: list[str] = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")

        key_name = event.text().lower().strip()
        if not key_name or key == Qt.Key.Key_Space:
            key_name = "space"
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            key_name = "enter"
        elif key == Qt.Key.Key_Tab:
            key_name = "tab"

        parts.append(key_name)
        self.setText("+".join(parts))


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Configuration dialog for Beacon."""

    def __init__(
        self,
        config: Config,
        auth: AuthManager,
        indexer,       # Indexer
        db: Database,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._auth = auth
        self._indexer = indexer
        self._db = db
        self._signals = _WorkerSignals()

        self.setWindowTitle("Beacon Settings")
        self.setMinimumWidth(480)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet(get_stylesheet())

        self._build_ui()
        self._load_values()
        self._connect_signals()
        self._update_index_info()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(20, 20, 20, 20)

        # ── SharePoint section ──────────────────────────────────────────
        sp_group = QGroupBox("SharePoint")
        sp_layout = QVBoxLayout(sp_group)
        sp_layout.setSpacing(8)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://yourcompany.sharepoint.com/sites/…")
        url_row.addWidget(QLabel("Root URL:"))
        url_row.addWidget(self._url_edit, 1)
        sp_layout.addLayout(url_row)

        login_row = QHBoxLayout()
        login_row.setSpacing(8)
        self._login_btn = QPushButton("Login to SharePoint")
        self._login_status = QLabel("")
        self._login_status.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        login_row.addWidget(self._login_btn)
        login_row.addWidget(self._login_status, 1)
        sp_layout.addLayout(login_row)

        root.addWidget(sp_group)

        # ── Index section ───────────────────────────────────────────────
        idx_group = QGroupBox("Index")
        idx_layout = QVBoxLayout(idx_group)
        idx_layout.setSpacing(8)

        fetch_row = QHBoxLayout()
        fetch_row.setSpacing(8)
        self._fetch_btn = QPushButton("Fetch Index Now")
        self._clear_btn = QPushButton("Clear Index")
        self._fetch_status = QLabel("")
        self._fetch_status.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        self._fetch_status.setWordWrap(True)
        fetch_row.addWidget(self._fetch_btn)
        fetch_row.addWidget(self._clear_btn)
        fetch_row.addWidget(self._fetch_status, 1)
        idx_layout.addLayout(fetch_row)

        self._index_info = QLabel("")
        self._index_info.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        idx_layout.addWidget(self._index_info)

        root.addWidget(idx_group)

        # ── Preferences section ─────────────────────────────────────────
        pref_group = QGroupBox("Preferences")
        pref_layout = QFormLayout(pref_group)
        pref_layout.setSpacing(10)
        pref_layout.setContentsMargins(12, 16, 12, 12)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 24)
        self._interval_spin.setSuffix(" hours")
        pref_layout.addRow("Refresh interval:", self._interval_spin)

        self._browser_check = QCheckBox("Open files in browser by default")
        pref_layout.addRow("", self._browser_check)

        self._hotkey_edit = _HotkeyEdit()
        pref_layout.addRow("Hotkey:", self._hotkey_edit)

        root.addWidget(pref_group)

        # ── Save button ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedWidth(100)
        btn_row.addWidget(self._save_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Populate / persist values
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        self._url_edit.setText(self._config.sharepoint_root_url)
        self._interval_spin.setValue(self._config.refresh_interval_hours)
        self._browser_check.setChecked(self._config.open_in_browser)
        self._hotkey_edit.setText(self._config.hotkey)

        if self._auth.has_session():
            self._login_status.setText("✓ Session active")
            self._login_status.setStyleSheet(f"color: #a6e3a1; font-size: 12px;")

    def _save_values(self) -> None:
        self._config.sharepoint_root_url = self._url_edit.text().strip()
        self._config.refresh_interval_hours = self._interval_spin.value()
        self._config.open_in_browser = self._browser_check.isChecked()
        hotkey = self._hotkey_edit.text().strip()
        if hotkey:
            self._config.hotkey = hotkey
        self._config.save()

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._login_btn.clicked.connect(self._on_login_clicked)
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        self._save_btn.clicked.connect(self._on_save_clicked)

        self._signals.login_done.connect(self._on_login_done)
        self._signals.index_progress.connect(self._on_index_progress)
        self._signals.index_done.connect(self._on_index_done)
        self._clear_btn.clicked.connect(self._on_clear_clicked)

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    def _on_login_clicked(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            self._login_status.setText("Enter a SharePoint URL first.")
            self._login_status.setStyleSheet(f"color: #f38ba8; font-size: 12px;")
            return

        self._login_btn.setEnabled(False)
        self._login_status.setText("Opening browser…")
        self._login_status.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")

        thread = threading.Thread(
            target=self._run_login, args=(url,), daemon=True
        )
        thread.start()

    def _run_login(self, url: str) -> None:
        try:
            success = self._auth.login_interactive(url)
        except Exception:
            success = False
        self._signals.login_done.emit(success)

    def _on_login_done(self, success: bool) -> None:
        self._login_btn.setEnabled(True)
        if success:
            self._login_status.setText("✓ Logged in")
            self._login_status.setStyleSheet("color: #a6e3a1; font-size: 12px;")
        else:
            self._login_status.setText("✗ Login failed")
            self._login_status.setStyleSheet("color: #f38ba8; font-size: 12px;")

    # ------------------------------------------------------------------
    # Index flow
    # ------------------------------------------------------------------

    def _on_fetch_clicked(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            self._fetch_status.setText("Enter a SharePoint URL first.")
            self._fetch_status.setStyleSheet("color: #f38ba8; font-size: 12px;")
            return
        self._config.sharepoint_root_url = url
        self._fetch_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)
        self._fetch_status.setText("Starting…")
        thread = threading.Thread(target=self._run_index, daemon=True)
        thread.start()

    def _on_clear_clicked(self) -> None:
        self._db.clear_files()
        self._fetch_status.setText("Index cleared.")
        self._fetch_status.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        self._update_index_info()

    def _run_index(self) -> None:
        def on_progress(msg: str) -> None:
            self._signals.index_progress.emit(msg)

        try:
            result = self._indexer.run(on_progress=on_progress)
        except Exception:
            self._signals.index_done.emit(None)
            return

        self._signals.index_done.emit(result)

    def _on_index_progress(self, msg: str) -> None:
        self._fetch_status.setText(msg)

    def _on_index_done(self, result) -> None:
        self._fetch_btn.setEnabled(True)
        self._clear_btn.setEnabled(True)
        if result is None or result.error:
            err = result.error if result else "Unknown error"
            self._fetch_status.setText(f"✗ {err}")
            self._fetch_status.setStyleSheet("color: #f38ba8; font-size: 12px;")
        else:
            self._fetch_status.setText(
                f"✓ {result.count:,} files indexed in {result.duration_seconds:.1f}s"
            )
            self._fetch_status.setStyleSheet("color: #a6e3a1; font-size: 12px;")
        self._update_index_info()

    def _update_index_info(self) -> None:
        count = self._db.get_file_count()
        last = self._db.get_last_indexed()

        if last is None:
            info = f"{count:,} files · never indexed"
        else:
            from src.ui.tray import _format_relative
            info = f"{count:,} files · last indexed {_format_relative(last)}"
        self._index_info.setText(info)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        self._save_values()
        self.accept()
