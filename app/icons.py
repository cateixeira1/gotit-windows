"""Ícones do Got It! (desenhados para este app, traço de 1,8 px numa grade de 24 × 24)."""

from __future__ import annotations

import re
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

S = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
F = 'fill="currentColor" stroke="none"'

PATHS: dict[str, str] = {
    "sidebar": f'<rect x="3" y="4" width="18" height="16" rx="3" {S}/><path d="M9 4v16" {S}/>',
    "plus": f'<path d="M12 5v14M5 12h14" {S}/>',
    "note": f'<path d="M6 3h8l4 4v14H6z" {S}/><path d="M14 3v4h4M9 12h6M9 16h6" {S}/>',
    "simple": f'<rect x="5" y="3" width="14" height="18" rx="2" {S}/><path d="M5 7h14M8 11h8M8 14h8M8 17h5" {S}/>',
    "teia": f'<rect x="3" y="4" width="6" height="6" rx="1" {S}/><rect x="15" y="4" width="6" height="6" rx="1" {S}/>'
            f'<rect x="9" y="15" width="6" height="6" rx="1" {S}/><path d="M9 7h6M7 10l4 5M17 10l-4 5" {S}/>',
    "search": f'<circle cx="10.5" cy="10.5" r="6" {S}/><path d="M15 15l5 5" {S}/>',
    "folder": f'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" {S}/>',
    "folder-plus": f'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" {S}/><path d="M12 10v6M9 13h6" {S}/>',
    "trash": f'<path d="M4 7h16M10 3h4M6 7l1 13h10l1-13M10 11v6M14 11v6" {S}/>',
    "gear": f'<circle cx="12" cy="12" r="3" {S}/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" {S}/>',
    "back": f'<path d="M15 5l-7 7 7 7" {S}/>',
    "chevron": f'<path d="M9 5l7 7-7 7" {S}/>',
    "down": f'<path d="M6 9l6 6 6-6" {S}/>',
    "undo": f'<path d="M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3" {S}/>',
    "redo": f'<path d="M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h3" {S}/>',
    "bold": f'<path d="M7 5h6a3.5 3.5 0 0 1 0 7H7zM7 12h7a3.5 3.5 0 0 1 0 7H7z" {S} stroke-width="2.4"/>',
    "italic": f'<path d="M10 5h8M6 19h8M14 5l-4 14" {S}/>',
    "underline": f'<path d="M7 4v7a5 5 0 0 0 10 0V4M5 20h14" {S}/>',
    "strike": f'<path d="M16 6.5C15 5 13.6 4.5 12 4.5c-2.5 0-4.5 1.3-4.5 3.4 0 1.5 1 2.4 2.5 3.1M4 12h16M8 17c1 1.6 2.4 2.5 4.3 2.5 2.6 0 4.5-1.4 4.5-3.5 0-.6-.2-1.2-.5-1.6" {S}/>',
    "align-left": f'<path d="M4 6h16M4 10h10M4 14h16M4 18h10" {S}/>',
    "align-center": f'<path d="M4 6h16M7 10h10M4 14h16M7 18h10" {S}/>',
    "align-right": f'<path d="M4 6h16M10 10h10M4 14h16M10 18h10" {S}/>',
    "align-justify": f'<path d="M4 6h16M4 10h16M4 14h16M4 18h16" {S}/>',
    "list": f'<circle cx="5" cy="7" r="1.3" {F}/><circle cx="5" cy="12" r="1.3" {F}/><circle cx="5" cy="17" r="1.3" {F}/><path d="M9 7h11M9 12h11M9 17h11" {S}/>',
    "list-num": f'<path d="M4 5h1.5v4M4 9h3M4 14.5c0-1 .8-1.5 1.5-1.5S7 13.5 7 14.3c0 1-3 2-3 3.7h3" {S} stroke-width="1.4"/><path d="M10 7h10M10 12h10M10 17h10" {S}/>',
    "indent": f'<path d="M4 5h16M10 10h10M10 14h10M4 19h16M4 9l3 3-3 3" {S}/>',
    "outdent": f'<path d="M4 5h16M10 10h10M10 14h10M4 19h16M7 9l-3 3 3 3" {S}/>',
    "text-color": f'<path d="M6 16L11 4h2l5 12M8 12h8" {S}/><rect x="4" y="18.5" width="16" height="2.5" rx="1" {F}/>',
    "highlight": f'<path d="M14.5 4.5l5 5-8 8H6.5v-5z" {S}/><path d="M4 21h16" {S}/>',
    "link": f'<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" {S}/>',
    "find": f'<circle cx="10" cy="10" r="5.5" {S}/><path d="M14 14l2.5 2.5M14 20.5h7M17.5 17v7" {S} stroke-width="1.5"/>',
    "pages": f'<rect x="7" y="3" width="12" height="15" rx="1.5" {S}/><path d="M5 6v13a2 2 0 0 0 2 2h9" {S}/>',
    "zoom-in": f'<circle cx="10.5" cy="10.5" r="6" {S}/><path d="M15 15l5 5M8 10.5h5M10.5 8v5" {S}/>',
    "zoom-out": f'<circle cx="10.5" cy="10.5" r="6" {S}/><path d="M15 15l5 5M8 10.5h5" {S}/>',
    "fit": f'<path d="M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4M8 12h8" {S}/>',
    "select": f'<path d="M6 3l12 9-5.5 1L15 19l-2.5 1.2-2.6-6L6 17z" {S}/>',
    "pen": f'<path d="M15 4l5 5L9 20H4v-5z" {S}/><path d="M13 6l5 5" {S}/>',
    "marker": f'<path d="M9 14l-3 3v3h3l3-3M9 14l7-9 3 3-7 9zM9 14l3 3" {S}/>',
    "pencil": f'<path d="M5 19l1.5-5L16 4.5 19.5 8 10 17.5z" {S}/><path d="M14 6.5L17.5 10M5 19l4-1" {S}/>',
    "eraser": f'<path d="M8 20h12M4.5 15.5l9-9a2 2 0 0 1 2.8 0l2.2 2.2a2 2 0 0 1 0 2.8L12 18H7z" {S}/><path d="M9 11l5 5" {S}/>',
    "textbox": f'<rect x="3" y="4" width="18" height="16" rx="2" {S}/><path d="M8 9h8M12 9v7" {S}/>',
    "table": f'<rect x="3" y="4" width="18" height="16" rx="2" {S}/><path d="M3 9.5h18M3 15h18M9 4v16M15 4v16" {S}/>',
    "image": f'<rect x="3" y="4" width="18" height="16" rx="2" {S}/><circle cx="9" cy="9.5" r="1.8" {S}/><path d="M4 18l5-5 4 4 3-3 4 4" {S}/>',
    "pdf": f'<path d="M6 3h8l4 4v14H6z" {S}/><path d="M14 3v4h4" {S}/><text x="12" y="17" font-size="5.6" font-family="Segoe UI, Arial" font-weight="700" text-anchor="middle" {F}>PDF</text>',
    "pdf-annotate": f'<path d="M5 3h8l4 4v6M5 3v18h7" {S}/><path d="M13 3v4h4M15 21l1-3 4.5-4.5 2 2L18 20z" {S}/>',
    "video": f'<rect x="3" y="6" width="13" height="12" rx="2" {S}/><path d="M16 10l5-3v10l-5-3" {S}/>',
    "mic": f'<rect x="9" y="3" width="6" height="11" rx="3" {S}/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" {S}/>',
    "wave": f'<path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 7v10M21 12h0" {S}/>',
    "sticker": f'<path d="M20 12a8 8 0 1 1-8-8h3l5 5z" {S}/><path d="M15 4v5h5M9 10h0M14 10h0" {S}/><path d="M8.5 14.5c1.5 2 5.5 2 7 0" {S}/>',
    "sticky": f'<path d="M4 4h16v11l-5 5H4z" {S}/><path d="M15 20v-5h5M8 9h8M8 13h5" {S}/>',
    "calendar": f'<rect x="3.5" y="5" width="17" height="15" rx="2" {S}/><path d="M3.5 10h17M8 3v4M16 3v4" {S}/><text x="12" y="18.2" font-size="6.5" font-family="Segoe UI, Arial" font-weight="700" text-anchor="middle" {F}>23</text>',
    "rectangle": f'<rect x="4" y="6" width="16" height="12" rx="1" {S}/>',
    "ellipse": f'<ellipse cx="12" cy="12" rx="8.5" ry="6.5" {S}/>',
    "diamond": f'<path d="M12 3l9 9-9 9-9-9z" {S}/>',
    "triangle": f'<path d="M12 4l9 16H3z" {S}/>',
    "line": f'<path d="M5 19L19 5" {S}/>',
    "arrow": f'<path d="M5 19L19 5M10 5h9v9" {S}/>',
    "header": f'<rect x="4" y="3" width="16" height="18" rx="2" {S}/><path d="M4 7.5h16M4 16.5h16" {S}/><rect x="6.5" y="4.6" width="11" height="1.6" rx=".8" {F}/>',
    "number": f'<path d="M9 4L7 20M17 4l-2 16M4 9h16M3 15h16" {S}/>',
    "paper": f'<rect x="4" y="3" width="16" height="18" rx="2" {S}/><path d="M4 8h16M4 12h16M4 16h16M9 3v18" {S} stroke-width="1.2"/>',
    "page-size": f'<rect x="5" y="3" width="14" height="18" rx="1.5" {S}/><path d="M9 8h6M9 8v3M15 16H9M15 16v-3" {S}/>',
    "export": f'<path d="M12 15V3M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" {S}/>',
    "print": f'<path d="M7 9V3h10v6M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2M7 14h10v7H7z" {S}/>',
    "sparkle": f'<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" {S}/><path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" {S} stroke-width="1.3"/>',
    "play": f'<path d="M8 5v14l11-7z" {F}/>',
    "pause": f'<rect x="6.5" y="5" width="4" height="14" rx="1" {F}/><rect x="13.5" y="5" width="4" height="14" rx="1" {F}/>',
    "stop": f'<rect x="6" y="6" width="12" height="12" rx="2" {F}/>',
    "record": f'<circle cx="12" cy="12" r="7" {F}/>',
    "more": f'<circle cx="5" cy="12" r="1.7" {F}/><circle cx="12" cy="12" r="1.7" {F}/><circle cx="19" cy="12" r="1.7" {F}/>',
    "close": f'<path d="M6 6l12 12M18 6L6 18" {S}/>',
    "check": f'<path d="M5 12.5l4.5 4.5L19 7" {S}/>',
    "transcript": f'<path d="M4 6h10M4 10h16M4 14h16M4 18h9" {S}/><path d="M18 3v5M16 5.5h4" {S} stroke-width="1.4"/>',
    "restore": f'<path d="M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4" {S}/>',
    "handwriting": f'<path d="M3 17c2-6 4-9 5.5-9S9 13 10 13s2-5 3.5-5 1 6 2.5 6 2-3 3-3" {S}/><path d="M3 21h18" {S}/>',
    "shapes": f'<rect x="3" y="12" width="9" height="9" rx="1" {S}/><circle cx="16.5" cy="7.5" r="4.5" {S}/>',
    "connector": f'<circle cx="5.5" cy="18.5" r="2.5" {S}/><circle cx="18.5" cy="5.5" r="2.5" {S}/><path d="M7.5 16.5l9-9" {S}/>',
    "crop": f'<path d="M6 2v16h16M2 6h16v16" {S}/>',
    "rotate": f'<path d="M20 12a8 8 0 1 1-2.5-5.8M20 4v4h-4" {S}/>',
    "bring-front": f'<rect x="8" y="8" width="12" height="12" rx="1.5" {F}/><path d="M4 16V5a1 1 0 0 1 1-1h11" {S}/>',
    "send-back": f'<rect x="4" y="4" width="12" height="12" rx="1.5" {S}/><path d="M20 8v11a1 1 0 0 1-1 1H8" {S}/>',
    "copy": f'<rect x="8" y="8" width="12" height="12" rx="2" {S}/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" {S}/>',
    "lock": f'<rect x="5" y="11" width="14" height="10" rx="2" {S}/><path d="M8 11V7a4 4 0 0 1 8 0v4" {S}/>',
    "cutout": f'<path d="M12 3c3 0 5 2.5 5 5.5 0 2-1 3.5-2.5 4.5l1 3.5H8.5l1-3.5C8 12 7 10.5 7 8.5 7 5.5 9 3 12 3z" {S}/><path d="M4 20h16" {S} stroke-dasharray="2 2"/>',
    "keyboard": f'<rect x="2.5" y="6" width="19" height="12" rx="2" {S}/><path d="M6 10h0M9 10h0M12 10h0M15 10h0M18 10h0M7 14h10" {S}/>',
    "drag": f'<circle cx="9" cy="6" r="1.4" {F}/><circle cx="15" cy="6" r="1.4" {F}/><circle cx="9" cy="12" r="1.4" {F}/><circle cx="15" cy="12" r="1.4" {F}/><circle cx="9" cy="18" r="1.4" {F}/><circle cx="15" cy="18" r="1.4" {F}/>',
    "equation": f'<path d="M4 8h6M7 5v6M4 17h6M14 7l6 6M20 7l-6 6M14 18h6" {S}/>',
    "eye": f'<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" {S}/><circle cx="12" cy="12" r="3" {S}/>',
    "download": f'<path d="M12 3v12M7 10l5 5 5-5M5 21h14" {S}/>',
}


def svg(name: str, color: str = "#1f2933", size: int = 24) -> bytes:
    body = PATHS.get(name, PATHS["more"]).replace("currentColor", color)
    # um atributo repetido invalida o SVG: a espessura própria do ícone vale
    body = re.sub(r'stroke-width="1\.8"([^>]*?)stroke-width=', r'\1stroke-width=', body)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24">'
            f'{body}</svg>').encode()


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str = "#1f2933", px: int = 24, ratio: float = 2.0) -> QPixmap:
    side = int(px * ratio)
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, color)))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, side, side))
    painter.end()
    pm = QPixmap.fromImage(image)
    pm.setDevicePixelRatio(ratio)
    return pm


@lru_cache(maxsize=512)
def icon(name: str, color: str = "#1f2933", active: str | None = None) -> QIcon:
    ic = QIcon()
    for px in (16, 20, 24, 32):
        ic.addPixmap(pixmap(name, color, px), QIcon.Mode.Normal, QIcon.State.Off)
        ic.addPixmap(pixmap(name, "#9aa5b1", px), QIcon.Mode.Disabled, QIcon.State.Off)
        ic.addPixmap(pixmap(name, active or color, px), QIcon.Mode.Normal, QIcon.State.On)
    return ic


def size(px: int = 20) -> QSize:
    return QSize(px, px)
