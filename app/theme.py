"""Cores, fontes e estilo das janelas (Fluent do Windows 11, com as cores do ícone do Got It!)."""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

import core

TEAL = "#2E6474"          # fundo do ícone
TEAL_DARK = "#234E5B"
YELLOW = "#F1BE5D"        # post-it do ícone
NAVY = "#2A3570"          # check do ícone
ACCENT = "#2F6FB5"        # botões e seleção
INK = "#1F2933"
MUTED = "#6B7682"
LINE = "#DDE2E7"
WINDOW = "#F3F4F6"
SIDEBAR = "#EDF0F2"
CARD = "#FFFFFF"
DANGER = "#C93A3A"
DESK = "#E4E7EA"          # mesa atrás das páginas

BRAND_DOTS = ["#5a2c4e", "#0f7d72", "#1c1c1e", "#b9b9be"]   # Color Software (colorsoftware.com.br)

HANDWRITING_FONTS = ["Caveat", "Patrick Hand", "Kalam", "Indie Flower"]
UI_FONT = "Segoe UI"          # trocada pela Segoe UI Variable (Windows 11) em apply(), se existir

TEXT_COLORS = [("Preto", "#1F2933"), ("Azul", "#2563EB"), ("Vermelho", "#DC2626"), ("Verde", "#16A34A"),
               ("Laranja", "#EA580C"), ("Roxo", "#7C3AED"), ("Cinza", "#6B7280"), ("Branco", "#FFFFFF")]
HIGHLIGHTS = [("Amarelo", "#FFF07A"), ("Verde", "#B8F0A8"), ("Rosa", "#FFC2DD"), ("Azul", "#BFE3FF"), ("Laranja", "#FFD3A1")]
INK_COLORS = ["#1F2933", "#2563EB", "#DC2626", "#16A34A", "#EA580C", "#7C3AED", "#F1BE5D", "#FFFFFF"]
SHAPE_FILLS = [None, "#FFFFFF", "#FFF27A", "#FFB8D2", "#A9DDF7", "#C6EBA1", "#FFC98A", "#E5E7EB", "#1F2933"]

_registered: list[str] = []


def register_fonts() -> list[str]:
    """Fontes de escrita à mão (OFL) que vêm com o app."""
    if _registered:
        return _registered
    folder = core.asset_path("fonts")
    for path in sorted(folder.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0:
            _registered.extend(QFontDatabase.applicationFontFamilies(fid))
    return _registered


def ui_font(size: float = 9.5, bold: bool = False) -> QFont:
    f = QFont(UI_FONT)
    f.setPointSizeF(size)
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


def default_text_family() -> str:
    """Fonte padrão do texto das notas (a do sistema, como a San Francisco no iPhone)."""
    families = set(QFontDatabase.families())
    for name in ("Segoe UI", "Aptos", "Calibri", "Arial", "DejaVu Sans"):
        if name in families:
            return name
    return QGuiApplication.font().family()


def sticky_family() -> str:
    families = set(QFontDatabase.families())
    for name in ("Segoe Print", "Patrick Hand", "Caveat"):
        if name in families:
            return name
    return default_text_family()


def text_families() -> list[str]:
    families = set(QFontDatabase.families())
    preferred = ["Segoe UI", "Aptos", "Calibri", "Arial", "Times New Roman", "Georgia", "Cambria", "Garamond",
                 "Verdana", "Tahoma", "Trebuchet MS", "Consolas", "Courier New", "Comic Sans MS", "Segoe Print",
                 "Segoe Script", "Ink Free"]
    out = [f for f in preferred if f in families]
    base = default_text_family()
    if base not in out:
        out.insert(0, base)
    out += [f for f in HANDWRITING_FONTS if f in families and f not in out]
    return out


def apply(app) -> None:
    global UI_FONT
    families = set(QFontDatabase.families())
    for name in ("Segoe UI Variable Text", "Segoe UI"):
        if name in families:
            UI_FONT = name
            break
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(WINDOW))
    pal.setColor(QPalette.ColorRole.Base, QColor(CARD))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F7F8FA"))
    pal.setColor(QPalette.ColorRole.Text, QColor(INK))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(INK))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(INK))
    pal.setColor(QPalette.ColorRole.Button, QColor(CARD))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9AA5B1"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(INK))
    pal.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    app.setPalette(pal)
    app.setFont(ui_font(9.5))
    app.setStyleSheet(STYLE)


STYLE = f"""
QWidget {{ color: {INK}; }}
QToolTip {{ background: white; color: {INK}; border: 1px solid {LINE}; padding: 4px 6px; border-radius: 6px; }}
QMenu {{ background: white; border: 1px solid {LINE}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: #E8EEF6; color: {INK}; }}
QMenu::item:disabled {{ color: #A0A8B0; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{
    background: white; border: 1px solid #CDD3D9; border-radius: 6px; padding: 4px 8px; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QPushButton {{
    background: white; border: 1px solid #CDD3D9; border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ background: #F2F5F8; }}
QPushButton:pressed {{ background: #E6EBF0; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; }}
QPushButton[primary="true"]:hover {{ background: #2A64A4; }}
QPushButton[danger="true"] {{ color: {DANGER}; }}
QPushButton:disabled {{ color: #A0A8B0; background: #F3F4F6; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 4px; background: transparent; }}
QToolButton:hover {{ background: rgba(31, 41, 51, 0.07); }}
QToolButton:pressed, QToolButton:checked {{ background: rgba(47, 111, 181, 0.16); border: 1px solid rgba(47, 111, 181, 0.35); }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(31,41,51,0.25); border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(31,41,51,0.4); }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(31,41,51,0.25); border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QSlider::groove:horizontal {{ height: 4px; background: #D3D9DF; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: white; border: 1px solid #AAB4BE; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QTabBar::tab {{ padding: 6px 12px; }}
QDialog {{ background: {WINDOW}; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 8px; margin-top: 26px; padding: 12px 8px 8px 8px; background: white; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 4px; top: 2px; padding: 0 2px; color: {MUTED}; font-weight: 600; }}
QProgressBar {{ border: none; background: #E3E7EB; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""
