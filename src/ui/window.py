from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.config import Config
from src.opener import open_file
from src.search import Searcher
from src.ui.styles import ACCENT, SUBTEXT, TEXT, WINDOW_BG, get_stylesheet

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Badge colours per file type
# ---------------------------------------------------------------------------

_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "docx": ("#2b5ce6", "#ffffff"),   # Word blue
    "xlsx": ("#197049", "#ffffff"),   # Excel green
    "pptx": ("#c43b1f", "#ffffff"),   # PowerPoint orange-red
    "pdf":  ("#f40f02", "#ffffff"),   # PDF red
}
_BADGE_LABELS: dict[str, str] = {
    "docx": "W",
    "xlsx": "X",
    "pptx": "P",
    "pdf":  "PDF",
}
_BADGE_DEFAULT = ("#45475a", "#cdd6f4")


# ---------------------------------------------------------------------------
# Result row widget
# ---------------------------------------------------------------------------

class _ResultRow(QWidget):
    """A single result row: [badge] [bold name] / [dim path]."""

    def __init__(self, file: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file = file

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        # Badge
        badge = _BadgeLabel(file.get("file_type", "").lower())
        layout.addWidget(badge, 0)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel(file.get("name", ""))
        name_lbl.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 600; background: transparent;")
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        path_lbl = QLabel(file.get("path", ""))
        path_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; background: transparent;")
        path_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        text_col.addWidget(name_lbl)
        text_col.addWidget(path_lbl)
        layout.addLayout(text_col, 1)

        self.setAutoFillBackground(False)

    def file_data(self) -> dict:
        return self._file


class _BadgeLabel(QWidget):
    """Coloured pill showing the file type abbreviation."""

    def __init__(self, file_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = _BADGE_LABELS.get(file_type, file_type.upper()[:3] or "?")
        colors = _BADGE_COLORS.get(file_type, _BADGE_DEFAULT)
        self._bg = QColor(colors[0])
        self._fg = QColor(colors[1])

        is_pdf = file_type == "pdf"
        self._width = 36 if is_pdf else 24
        self.setFixedSize(self._width, 20)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self._width, 20, 4, 4)
        painter.fillPath(path, self._bg)

        painter.setPen(self._fg)
        font = QFont()
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(0, 0, self._width, 20, Qt.AlignmentFlag.AlignCenter, self._label)
        painter.end()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class BeaconWindow(QWidget):
    """Frameless floating search window."""

    file_opened = pyqtSignal()

    def __init__(self, searcher: Searcher, config: Config) -> None:
        super().__init__()
        self._searcher = searcher
        self._config = config
        self._results: list[dict] = []

        self._build_ui()
        self._apply_window_flags()
        self.setStyleSheet(get_stylesheet())

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Outer layout sits directly on the transparent QWidget
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Inner container carries the visible rounded background
        self._inner = QWidget(self)
        self._inner.setObjectName("beacon_inner")
        outer.addWidget(self._inner)

        inner_layout = QVBoxLayout(self._inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)

        # Search input
        self._input = QLineEdit()
        self._input.setObjectName("search_input")
        self._input.setPlaceholderText("Search files...")
        self._input.textChanged.connect(self._on_text_changed)
        self._input.installEventFilter(self)
        inner_layout.addWidget(self._input)

        # Divider
        self._divider = QFrame()
        self._divider.setObjectName("divider")
        self._divider.setFrameShape(QFrame.Shape.HLine)
        self._divider.hide()
        inner_layout.addWidget(self._divider)

        # Results list
        self._list = QListWidget()
        self._list.setObjectName("results_list")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.hide()
        self._list.itemActivated.connect(self._on_item_activated)
        inner_layout.addWidget(self._list)

        # Status bar
        self._status = QLabel()
        self._status.setObjectName("status_bar")
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        inner_layout.addWidget(self._status)

        self._update_status()

    def _apply_window_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(640)
        self.setMinimumHeight(60)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_and_focus(self) -> None:
        """Show, raise to front, center on primary screen, clear input."""
        from PyQt6.QtCore import QTimer
        self._searcher.reload()
        self._input.clear()
        self._clear_results()
        self._update_status()
        self._center_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        # Defer setFocus to the next event loop iteration so the window is
        # fully mapped before we request focus — fixes intermittent miss.
        QTimer.singleShot(0, self._input.setFocus)

    def hide_window(self) -> None:
        self.hide()

    def update_status(self) -> None:
        """Refresh the status bar — call after re-indexing."""
        self._update_status()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.left() + (geo.width() - self.width()) // 2
        y = geo.top() + int(geo.height() * 0.28)
        self.move(x, y)

    def _on_text_changed(self, text: str) -> None:
        results = self._searcher.search(text)
        self._populate_results(results)

    def _populate_results(self, files: list[dict]) -> None:
        self._results = files
        self._list.clear()

        if not files:
            self._list.hide()
            self._divider.hide()
            self._adjust_height()
            return

        for file in files:
            row_widget = _ResultRow(file)
            item = QListWidgetItem()
            item.setSizeHint(QSize(640, 52))
            self._list.addItem(item)
            self._list.setItemWidget(item, row_widget)

        self._list.setCurrentRow(0)
        self._divider.show()
        self._list.show()
        self._adjust_height()

    def _clear_results(self) -> None:
        self._results = []
        self._list.clear()
        self._list.hide()
        self._divider.hide()
        self._adjust_height()

    def _adjust_height(self) -> None:
        """Resize window to fit content without exceeding 500 px."""
        list_height = self._list.count() * 52 if self._list.isVisible() else 0
        list_height = min(list_height, 380)  # cap list portion

        input_height = self._input.sizeHint().height()
        status_height = self._status.sizeHint().height()
        divider_height = 1 if self._divider.isVisible() else 0

        total = input_height + divider_height + list_height + status_height
        total = max(total, 60)
        total = min(total, 500)
        self.setFixedHeight(total)
        if self._list.isVisible():
            self._list.setFixedHeight(list_height)

    def _update_status(self) -> None:
        """Update the status bar with file count and last indexed time."""
        from src.config import Config as _Config  # local import to avoid cycle

        try:
            # We don't hold a db reference directly — use searcher's loaded data
            count = len(self._searcher._files)
            self._status.setText(f"{count:,} files in index")
        except Exception:
            self._status.setText("No index yet")

    def _open_selected(self, force_browser: bool = False) -> None:
        current = self._list.currentItem()
        if current is None:
            return
        widget = self._list.itemWidget(current)
        if widget is None or not isinstance(widget, _ResultRow):
            return
        file = widget.file_data()
        use_browser = force_browser or self._config.open_in_browser
        open_file(file, use_browser=use_browser)
        self.file_opened.emit()
        self.hide_window()

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        widget = self._list.itemWidget(item)
        if widget is not None and isinstance(widget, _ResultRow):
            file = widget.file_data()
            open_file(file, use_browser=self._config.open_in_browser)
            self.file_opened.emit()
            self.hide_window()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        from PyQt6.QtCore import QEvent
        if obj is self._input and isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()

            if key == Qt.Key.Key_Escape:
                self.hide_window()
                return True

            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                force_browser = bool(mods & Qt.KeyboardModifier.ControlModifier)
                self._open_selected(force_browser=force_browser)
                return True

            if key == Qt.Key.Key_Down:
                count = self._list.count()
                if count > 0:
                    current = self._list.currentRow()
                    self._list.setCurrentRow(min(current + 1, count - 1))
                return True

            if key == Qt.Key.Key_Up:
                count = self._list.count()
                if count > 0:
                    current = self._list.currentRow()
                    self._list.setCurrentRow(max(current - 1, 0))
                return True

        return super().eventFilter(obj, event)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        # Hide when the window itself loses focus (e.g. user clicks elsewhere)
        # but only if no child widget is taking focus.
        super().focusOutEvent(event)

    def event(self, event) -> bool:  # type: ignore[override]
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowDeactivate:
            self.hide_window()
        return super().event(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        # The window itself is transparent; the inner widget draws the bg.
        pass
