"""Colours, fonts and the Qt style sheet of the studio."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from utils.config import ASSETS_DIR

BG = "#0b1020"
PANEL = "#111830"
CARD = "#161f3a"
CARD_HI = "#1d2850"
BORDER = "#26335c"
TEXT = "#e8edf8"
MUTED = "#8c9abb"
ACCENT = "#4f8cff"
ACCENT_2 = "#8b5cf6"
OK = "#34d399"
WARN = "#fbbf24"
DANGER = "#f87171"

URDU_FAMILY = "Noto Nastaliq Urdu"
NASKH_FAMILY = "Noto Naskh Arabic"
UI_FAMILY = "Noto Sans"

QSS = f"""
* {{ font-family: "{UI_FAMILY}", "Segoe UI", "{NASKH_FAMILY}"; color: {TEXT}; }}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QWidget#Page {{ background: transparent; }}
QToolTip {{ background: {CARD_HI}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; border-radius: 6px; }}

QFrame#Sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QToolButton#NavButton {{ background: transparent; border: none; border-radius: 12px; padding: 10px 4px;
    color: {MUTED}; font-size: 11px; }}
QToolButton#NavButton:hover {{ background: {CARD}; color: {TEXT}; }}
QToolButton#NavButton:checked {{ background: {CARD_HI}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}
QLabel#Logo {{ font-size: 15px; font-weight: 800; color: {TEXT}; }}

QFrame#TopBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QLabel#ProjectName {{ font-size: 17px; font-weight: 700; }}
QLabel#Muted, QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel#PageTitle {{ font-size: 26px; font-weight: 800; }}
QLabel#PageSubtitle {{ color: {MUTED}; font-size: 14px; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 700; }}
QLabel#BigNumber {{ font-size: 30px; font-weight: 800; }}

QFrame#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#ThumbCard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#ThumbCard:hover {{ border: 1px solid {ACCENT}; background: {CARD_HI}; }}
QFrame#ThumbCard[selected="true"] {{ border: 2px solid {ACCENT}; background: {CARD_HI}; }}
QFrame#Hero {{ border-radius: 20px; border: 1px solid {BORDER};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1b2a5c, stop:0.55 #1a2048, stop:1 #2a1d55); }}

QPushButton {{ background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px;
    font-weight: 600; }}
QPushButton:hover {{ background: #263466; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #1a2550; }}
QPushButton:disabled {{ color: #56607e; background: #121a33; border-color: #1c2547; }}
QPushButton#Primary {{ border: none; color: white; font-size: 15px; padding: 10px 22px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6a9dff, stop:1 #9d74fa); }}
QPushButton#Primary:disabled {{ background: #2a3358; color: #8090b8; }}
QPushButton#Big {{ font-size: 19px; padding: 14px 34px; border-radius: 14px; }}
QPushButton#Danger {{ background: #3a1f2a; border-color: #5c2a3a; }}
QPushButton#Danger:hover {{ background: #5c2a3a; border-color: {DANGER}; }}
QPushButton#Chip {{ background: #1a2448; border-radius: 14px; padding: 5px 12px; font-weight: 500; color: #c9d4f0; }}
QPushButton#Chip:hover {{ border-color: {ACCENT}; color: white; }}
QPushButton#Chip:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#Swatch {{ border-radius: 8px; border: 2px solid {BORDER}; padding: 0; min-height: 26px; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{ background: #0d1430; border: 1px solid {BORDER};
    border-radius: 10px; padding: 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER}; selection-background-color: {ACCENT}; }}

QProgressBar {{ background: #0d1430; border: 1px solid {BORDER}; border-radius: 9px; height: 18px;
    text-align: center; font-weight: 700; }}
QProgressBar::chunk {{ border-radius: 8px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); }}

QSlider::groove:horizontal {{ height: 6px; background: #22305a; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: white; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER};
    background: #0d1430; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a3766; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a3766; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

QDialog {{ background: {PANEL}; }}
QMessageBox {{ background: {PANEL}; }}
QLabel#Toast {{ background: {CARD_HI}; border: 1px solid {ACCENT}; border-radius: 12px; padding: 10px 18px;
    font-weight: 600; }}
"""


def load_fonts() -> None:
    for f in (ASSETS_DIR / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))


def apply(app: QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    pal = QPalette()
    for role, colour in ((QPalette.Window, BG), (QPalette.Base, "#0d1430"), (QPalette.Text, TEXT),
                         (QPalette.WindowText, TEXT), (QPalette.Button, CARD_HI), (QPalette.ButtonText, TEXT),
                         (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
                         (QPalette.ToolTipBase, CARD_HI), (QPalette.ToolTipText, TEXT),
                         (QPalette.PlaceholderText, "#6b7799"), (QPalette.Link, "#7cb2ff"),
                         (QPalette.LinkVisited, "#b49cff")):
        pal.setColor(role, QColor(colour))
    app.setPalette(pal)
    f = QFont(UI_FAMILY, 10)
    f.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(f)
    app.setStyleSheet(QSS)


def urdu_font(size: int = 16) -> QFont:
    return QFont(NASKH_FAMILY, size)


def auto_direction(edit) -> None:
    """Each paragraph of a QTextEdit runs right-to-left (right-aligned) when it starts with Urdu."""
    from PySide6.QtCore import Qt

    doc = edit.document()
    opt = doc.defaultTextOption()
    opt.setTextDirection(Qt.LayoutDirectionAuto)
    opt.setAlignment(Qt.AlignLeading)
    doc.setDefaultTextOption(opt)
