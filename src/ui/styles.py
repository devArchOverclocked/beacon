from __future__ import annotations

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

WINDOW_BG = "#1e1e2e"
ACCENT = "#89b4fa"      # catppuccin blue
TEXT = "#cdd6f4"
SUBTEXT = "#6c7086"
HOVER_BG = "#313244"
RESULT_BG = "#181825"

# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

_QSS = f"""
/* ── Main window ─────────────────────────────────────────────────────────── */
BeaconWindow {{
    background: transparent;
}}

QWidget#beacon_inner {{
    background-color: {WINDOW_BG};
    border-radius: 12px;
    border: 1px solid #313244;
}}

/* ── Search input ────────────────────────────────────────────────────────── */
QLineEdit#search_input {{
    background-color: {WINDOW_BG};
    color: {TEXT};
    font-size: 20px;
    font-weight: 400;
    border: none;
    border-radius: 12px;
    padding: 14px 18px;
    selection-background-color: {ACCENT};
    selection-color: {WINDOW_BG};
}}

QLineEdit#search_input::placeholder {{
    color: {SUBTEXT};
}}

/* ── Divider line between input and results ──────────────────────────────── */
QFrame#divider {{
    color: #313244;
    background-color: #313244;
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ── Results list ────────────────────────────────────────────────────────── */
QListWidget#results_list {{
    background-color: {RESULT_BG};
    border: none;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
    outline: none;
    padding: 4px 0px;
}}

QListWidget#results_list::item {{
    background-color: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
}}

QListWidget#results_list::item:selected {{
    background-color: {HOVER_BG};
    border-radius: 6px;
}}

QListWidget#results_list::item:hover {{
    background-color: {HOVER_BG};
    border-radius: 6px;
}}

/* Hide scrollbar decorations */
QScrollBar:vertical {{
    width: 4px;
    background: transparent;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: #45475a;
    border-radius: 2px;
    min-height: 20px;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
    border: none;
    height: 0px;
}}

QScrollBar:horizontal {{
    height: 0px;
}}

/* ── Status bar ──────────────────────────────────────────────────────────── */
QLabel#status_bar {{
    background-color: transparent;
    color: {SUBTEXT};
    font-size: 11px;
    padding: 4px 18px 8px 18px;
}}

/* ── Settings dialog ─────────────────────────────────────────────────────── */
QDialog {{
    background-color: {WINDOW_BG};
    color: {TEXT};
}}

QLabel {{
    color: {TEXT};
}}

QLineEdit {{
    background-color: {RESULT_BG};
    color: {TEXT};
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: {ACCENT};
}}

QLineEdit:focus {{
    border-color: {ACCENT};
}}

QPushButton {{
    background-color: {ACCENT};
    color: {WINDOW_BG};
    border: none;
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: #b4d0fb;
}}

QPushButton:pressed {{
    background-color: #6ea3f7;
}}

QPushButton:disabled {{
    background-color: #45475a;
    color: {SUBTEXT};
}}

QSpinBox {{
    background-color: {RESULT_BG};
    color: {TEXT};
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}

QSpinBox:focus {{
    border-color: {ACCENT};
}}

QCheckBox {{
    color: {TEXT};
    font-size: 13px;
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #45475a;
    background-color: {RESULT_BG};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QGroupBox {{
    color: {SUBTEXT};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    border: 1px solid #313244;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
}}
"""


def get_stylesheet() -> str:
    """Return the complete QSS stylesheet for the Beacon application."""
    return _QSS
