"""Menu do Got It! (como no iPad): pasta mostrada, nova nota, nova nota simples, nova Teia,
nova pasta, as 9 notas e as 9 Teias mais recentes com "Todas as…", busca, Lixeira, Ajustes e a
marca da Color Software. Arrastar uma nota sobre outra cria uma pasta com as duas."""

from __future__ import annotations

import html
import re

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

import icons
import model
import theme

NOTE_MIME = "application/x-gotit-note"
RECENT_LIMIT = 9


class Row(QFrame):
    """Linha clicável do menu (ícone, título, detalhe à direita); pode receber notas soltas."""
    clicked = Signal()
    dropped = Signal(str)

    def __init__(self, icon: str, title: str, detail: str = "", accept_drop: bool = False, color: str = theme.INK):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(accept_drop)
        self.setObjectName("row")
        self._style(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon, color if color != theme.INK else theme.ACCENT, 18))
        lab = QLabel(title)
        lab.setFont(theme.ui_font(10))
        lay.addWidget(ic)
        lay.addWidget(lab, 1)
        if detail:
            d = QLabel(detail)
            d.setStyleSheet(f"color: {theme.MUTED};")
            lay.addWidget(d)
        self.setAccessibleName(title)

    def _style(self, hot: bool):
        self.setStyleSheet("#row { border-radius: 8px; background: %s; }" % ("#DCE8F7" if hot else "transparent")
                           + "#row:hover { background: rgba(31,41,51,0.06); }")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(NOTE_MIME):
            self._style(True)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._style(False)

    def dropEvent(self, e):
        self._style(False)
        doc_id = bytes(e.mimeData().data(NOTE_MIME)).decode()
        self.dropped.emit(doc_id)
        e.acceptProposedAction()


class Group(QFrame):
    """Cartão branco com linhas, como os grupos do menu do iPhone."""

    def __init__(self, card: bool = True):
        super().__init__()
        self.setObjectName("group")
        if card:
            self.setStyleSheet(f"#group {{ background: {theme.CARD}; border-radius: 12px; border: 1px solid {theme.LINE}; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(4, 4, 4, 4) if card else self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)

    def add(self, w):
        self.lay.addWidget(w)
        return w


class NoteCard(QWidget):
    """Cartão de nota ou Teia com a prévia da primeira página; arrastável."""
    clicked = Signal(str)
    dropped_on = Signal(str, str)        # arrastada, alvo
    menu = Signal(str, QPoint)

    def __init__(self, info, image: QImage | None, active: bool):
        super().__init__()
        self.info = info
        self.image = image
        self.active = active
        self.hot = False
        self._press = None
        self.setFixedSize(92, 158)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(info.title)
        self.setAccessibleName(info.title)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        thumb = QRectF(4, 4, 84, 116)
        if self.hot:
            p.setPen(QPen(QColor(theme.ACCENT), 2.5))
            p.setBrush(QColor("#DCE8F7"))
            p.drawRoundedRect(thumb.adjusted(-3, -3, 3, 3), 9, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 22))
        p.drawRoundedRect(thumb.translated(0, 2), 6, 6)
        path = QPainterPath()
        path.addRoundedRect(thumb, 6, 6)
        p.setClipPath(path)
        if self.info.kind == "web" and self.image is None:
            art = icons_teia_art()
            p.drawImage(thumb, art) if art is not None else p.fillRect(thumb, QColor(theme.TEAL))
        elif self.image is not None:
            p.fillRect(thumb, QColor("white"))
            img = self.image
            scale = max(thumb.width() / img.width(), thumb.height() / img.height())
            src = QRectF(0, 0, thumb.width() / scale, thumb.height() / scale)
            p.drawImage(thumb, img, src)
        else:
            p.fillRect(thumb, QColor("white"))
        p.setClipping(False)
        p.setPen(QPen(QColor(theme.ACCENT) if self.active else QColor("#D3D9DF"), 2 if self.active else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(thumb, 6, 6)
        if self.info.kind == "web":
            badge = QRectF(thumb.right() - 24, thumb.top() + 4, 20, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.TEAL))
            p.drawEllipse(badge)
            p.drawPixmap(badge.adjusted(3, 3, -3, -3).toRect(), icons.pixmap("teia", "#FFFFFF", 14))
        p.setPen(QColor(theme.INK))
        f = theme.ui_font(8.5, True)
        p.setFont(f)
        fm = QFontMetricsF(f)
        title = self.info.title or "Sem título"
        lines = _wrap(title, fm, 88, 2)
        y = 124
        for ln in lines:
            p.drawText(QRectF(2, y, 88, 15), Qt.AlignmentFlag.AlignHCenter, ln)
            y += 14

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() > 8:
            drag = QDrag(self)
            md = QMimeData()
            md.setData(NOTE_MIME, self.info.id.encode())
            drag.setMimeData(md)
            pm = self.grab()
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            drag.setPixmap(pm)
            drag.setHotSpot(self._press)
            self._press = None
            drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if self._press is not None and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.info.id)
        self._press = None

    def contextMenuEvent(self, e):
        self.menu.emit(self.info.id, e.globalPos())

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(NOTE_MIME) and bytes(e.mimeData().data(NOTE_MIME)).decode() != self.info.id:
            self.hot = True
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.hot = False
        self.update()

    def dropEvent(self, e):
        self.hot = False
        self.update()
        dragged = bytes(e.mimeData().data(NOTE_MIME)).decode()
        if dragged != self.info.id:
            self.dropped_on.emit(dragged, self.info.id)
            e.acceptProposedAction()


_TEIA_ART = None


def icons_teia_art():
    global _TEIA_ART
    if _TEIA_ART is None:
        import core
        img = QImage(str(core.asset_path("teia-art.png")))
        _TEIA_ART = img if not img.isNull() else False
    return _TEIA_ART or None


def _wrap(text: str, fm: QFontMetricsF, width: float, max_lines: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if fm.horizontalAdvance(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fm.elidedText(lines[-1] + " …", Qt.TextElideMode.ElideRight, width)
    return [fm.elidedText(ln, Qt.TextElideMode.ElideRight, width) for ln in lines]


class BrandMark(QWidget):
    """Marca da Color Software: quatro pontos 2 × 2 (ameixa, verde, grafite, cinza)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(20, 20)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i, c in enumerate(theme.BRAND_DOTS):
            p.setBrush(QColor(c))
            p.drawEllipse(QRectF(2 + (i % 2) * 9, 2 + (i // 2) * 9, 7, 7))


class Sidebar(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.store = window.store
        self.folder_id = window.settings.value("currentFolder", None) or None
        if self.folder_id and not self.store.folder(self.folder_id):
            self.folder_id = None
        self.browsing: str | None = None      # "note" ou "web": "Todas as…"
        self.active_id: str | None = None
        self.setFixedWidth(330)
        self.setObjectName("sidebar")
        self.setStyleSheet(f"#sidebar {{ background: {theme.SIDEBAR}; border-right: 1px solid {theme.LINE}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 12, 10, 4)
        logo = QLabel()
        import core
        pm = QPixmap(str(core.asset_path("logo-rounded.png")))
        if not pm.isNull():
            dpr = max(1.0, self.devicePixelRatioF())
            pm = pm.scaled(int(30 * dpr), int(30 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            logo.setPixmap(pm)
        self.title = QLabel("Got It!")
        self.title.setFont(theme.ui_font(15, True))
        gear = QToolButton()
        gear.setIcon(icons.icon("gear"))
        gear.setIconSize(QSize(20, 20))
        gear.setToolTip("Ajustes")
        gear.clicked.connect(window.open_settings)
        head.addWidget(logo)
        head.addSpacing(10)
        head.addWidget(self.title, 1)
        head.addWidget(gear)
        outer.addLayout(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar nas notas")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setStyleSheet("QLineEdit { background: white; border-radius: 9px; padding: 6px 8px; }")
        sw = QHBoxLayout()
        sw.setContentsMargins(14, 6, 14, 8)
        sw.addWidget(self.search)
        outer.addLayout(sw)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        outer.addWidget(self.scroll, 1)
        self.search_timer = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)
        self.search.textChanged.connect(lambda *_: self.search_timer.start())
        self.refresh()

    # ------------------------------------------------------------------ montar
    def refresh(self) -> None:
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(14, 4, 14, 24)
        lay.setSpacing(10)
        query = self.search.text().strip()
        if query:
            self._results(lay, query)
        elif self.browsing:
            self._all(lay, self.browsing)
        else:
            self._home(lay)
        lay.addStretch(1)
        brand = QHBoxLayout()
        brand.addStretch()
        brand.addWidget(BrandMark())
        name = QLabel("Color Software")
        name.setFont(theme.ui_font(8.5, True))
        name.setStyleSheet(f"color: {theme.MUTED};")
        brand.addWidget(name)
        brand.addStretch()
        lay.addLayout(brand)
        old = self.scroll.takeWidget()
        pos = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(host)
        if old is not None:
            old.deleteLater()
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))
        self.window.settings.setValue("currentFolder", self.folder_id or "")

    def _header(self, lay, text: str):
        lab = QLabel(text)
        lab.setFont(theme.ui_font(9, True))
        lab.setStyleSheet(f"color: {theme.MUTED}; padding: 6px 4px 0 4px;")
        lay.addWidget(lab)

    def _home(self, lay) -> None:
        current = self.store.folder(self.folder_id)
        self._header(lay, current.name if current else "Notas e Teias")
        g = Group()
        if current:
            parent = self.store.folder(current.parent_id)
            back = g.add(Row("back", f"Voltar para {parent.name if parent else 'o início'}", accept_drop=True))
            back.clicked.connect(lambda: self.open_folder(current.parent_id))
            back.dropped.connect(lambda doc_id: self._move(doc_id, current.parent_id))
        for icon, title, fn in (("plus", "Nova nota", self.window.new_note),
                                ("simple", "Nova nota simples", self.window.new_simple_note),
                                ("teia", "Nova Teia", lambda: self.window.new_teia([])),
                                ("folder-plus", "Nova pasta", self.new_folder)):
            r = g.add(Row(icon, title))
            r.clicked.connect(fn)
        for f in self.store.folders(self.folder_id):
            r = g.add(Row("folder", f.name, str(self.store.folder_count(f.id)), accept_drop=True))
            r.clicked.connect(lambda fid=f.id: self.open_folder(fid))
            r.dropped.connect(lambda doc_id, fid=f.id: self._move(doc_id, fid))
            r.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            r.customContextMenuRequested.connect(lambda pos, fid=f.id, w=r: self._folder_menu(fid, w.mapToGlobal(pos)))
        lay.addWidget(g)
        for kind, title in (("note", "Notas"), ("web", "Teias")):
            recent = self.store.notes(kind=kind, folder_id=self.folder_id, limit=RECENT_LIMIT)
            if not recent:
                continue
            self._header(lay, title)
            lay.addWidget(self._grid(recent))
            total = len(self.store.notes(kind=kind, folder_id=self.folder_id))
            all_row = Row("chevron", "Todas as Notas" if kind == "note" else "Todas as Teias", str(total))
            all_row.setStyleSheet(all_row.styleSheet() + f"#row {{ background: {theme.CARD}; border: 1px solid {theme.LINE}; }}")
            all_row.clicked.connect(lambda k=kind: self.browse(k))
            lay.addWidget(all_row)
        g = Group()
        trash = len(self.store.notes(trashed=True))
        t = g.add(Row("trash", "Lixeira", str(trash) if trash else "", accept_drop=True))
        t.clicked.connect(self.window.open_trash)
        t.dropped.connect(self.window.trash_note)
        s = g.add(Row("gear", "Ajustes"))
        s.clicked.connect(self.window.open_settings)
        lay.addWidget(g)

    def _all(self, lay, kind: str) -> None:
        g = Group()
        back = g.add(Row("back", f"Voltar para {self._folder_name(self.folder_id)}"))
        back.clicked.connect(lambda: self.browse(None))
        lay.addWidget(g)
        notes = self.store.notes(kind=kind, folder_id=self.folder_id)
        word = ("Teia" if len(notes) == 1 else "Teias") if kind == "web" else ("nota" if len(notes) == 1 else "notas")
        self._header(lay, f"{len(notes)} {word}")
        if notes:
            lay.addWidget(self._grid(notes))
        else:
            empty = QLabel("Nenhuma Teia aqui." if kind == "web" else "Nenhuma nota aqui.")
            empty.setStyleSheet(f"color: {theme.MUTED}; padding: 8px;")
            lay.addWidget(empty)

    def _results(self, lay, query: str) -> None:
        hits = self.store.search(query)
        self._header(lay, f"{len(hits)} resultado(s)" if hits else "Nada encontrado")
        g = Group()
        for h in hits:
            g.add(ResultRow(h, self._folder_name(h.folder_id) if h.folder_id else "", lambda hit=h: self.window.open_hit(hit, query)))
        if hits:
            lay.addWidget(g)
        meaning = self.window.search_by_meaning(query, {h.doc_id for h in hits})
        if meaning:
            self._header(lay, "Por significado")
            g2 = Group()
            for h in meaning:
                g2.add(ResultRow(h, "", lambda hit=h: self.window.open_hit(hit, query)))
            lay.addWidget(g2)

    def _grid(self, notes) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(6)
        for i, n in enumerate(notes):
            card = NoteCard(n, self.window.thumbs.get(n.id, n.revision), n.id == self.active_id)
            card.clicked.connect(self.window.open_note)
            card.dropped_on.connect(self._merge)
            card.menu.connect(self._note_menu)
            grid.addWidget(card, i // 3, i % 3, Qt.AlignmentFlag.AlignHCenter)
        return w

    # ------------------------------------------------------------------ ações
    def _folder_name(self, folder_id) -> str:
        f = self.store.folder(folder_id)
        return f.name if f else "o início"

    def open_folder(self, folder_id) -> None:
        self.folder_id = folder_id
        self.browsing = None
        self.refresh()

    def browse(self, kind) -> None:
        self.browsing = kind
        self.refresh()
        self.scroll.verticalScrollBar().setValue(0)

    def set_active(self, doc_id: str | None) -> None:
        self.active_id = doc_id
        self.refresh()

    def new_folder(self) -> None:
        name = ask_folder_name(self, self.store.generic_folder_name())
        if name is None:
            return
        self.store.create_folder(name, self.folder_id)
        self.refresh()

    def _merge(self, dragged: str, target: str) -> None:
        """Nota solta sobre outra: pasta nova com as duas (numa transação), e o nome em seguida."""
        generic = self.store.generic_folder_name()
        folder = self.store.create_folder(generic, self.folder_id, containing=[target, dragged])
        self.refresh()
        name = ask_folder_name(self, generic)
        if name:
            self.store.rename_folder(folder.id, name)
            self.refresh()

    def _move(self, doc_id: str, folder_id) -> None:
        self.store.move_note(doc_id, folder_id)
        self.refresh()

    def _note_menu(self, doc_id: str, pos) -> None:
        info = self.store.info(doc_id)
        if not info:
            return
        m = QMenu(self)
        m.addAction(icons.icon("note"), "Abrir").triggered.connect(lambda: self.window.open_note(doc_id))
        m.addAction("Renomear…").triggered.connect(lambda: self._rename(doc_id))
        move = m.addMenu(icons.icon("folder"), "Mover para")
        self.window.fill_move_menu(move, [doc_id])
        if info.kind == "note":
            m.addAction(icons.icon("teia"), "Criar Teia com esta nota").triggered.connect(lambda: self.window.new_teia([doc_id]))
        m.addSeparator()
        m.addAction(icons.icon("trash", theme.DANGER), "Apagar (vai para a Lixeira)").triggered.connect(lambda: self.window.trash_note(doc_id))
        m.exec(pos)

    def _rename(self, doc_id: str) -> None:
        from PySide6.QtWidgets import QInputDialog
        info = self.store.info(doc_id)
        text, ok = QInputDialog.getText(self, "Renomear", "Nome:", text=info.title if info else "")
        if ok and text.strip():
            self.window.rename_note(doc_id, text.strip())

    def _folder_menu(self, folder_id: str, pos) -> None:
        f = self.store.folder(folder_id)
        if not f:
            return
        m = QMenu(self)
        m.addAction("Renomear…").triggered.connect(lambda: self._rename_folder(f))
        move = m.addMenu(icons.icon("folder"), "Mover para")
        self.window.fill_folder_move_menu(move, folder_id)
        m.addSeparator()
        m.addAction(icons.icon("trash", theme.DANGER), "Apagar a pasta (as notas sobem para a pasta de cima)").triggered.connect(
            lambda: (self.store.delete_folder(folder_id), self.refresh()))
        m.exec(pos)

    def _rename_folder(self, f) -> None:
        name = ask_folder_name(self, f.name, current=f.name, title="Renomear pasta")
        if name:
            self.store.rename_folder(f.id, name)
            self.refresh()


class ResultRow(QFrame):
    def __init__(self, hit, folder: str, on_click):
        super().__init__()
        self.on_click = on_click
        self.setObjectName("res")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("#res { border-radius: 8px; } #res:hover { background: rgba(31,41,51,0.06); }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(2)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("teia" if hit.kind == "web" else "note", theme.ACCENT, 16))
        title = QLabel(hit.title or "Sem título")
        title.setFont(theme.ui_font(10, True))
        top.addWidget(ic)
        top.addWidget(title, 1)
        if hit.count > 1:
            c = QLabel(f"{hit.count} lugares")
            c.setStyleSheet(f"color: {theme.MUTED};")
            top.addWidget(c)
        lay.addLayout(top)
        snippet = html.escape(hit.snippet or "").replace("[[", "<b style='background:#FFF07A'>").replace("]]", "</b>")
        s = QLabel(snippet)
        s.setTextFormat(Qt.TextFormat.RichText)
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {theme.INK};")
        lay.addWidget(s)
        if folder:
            f = QLabel(f"Pasta: {folder}")
            f.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
            lay.addWidget(f)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.on_click()


def ask_folder_name(parent, generic: str, current: str = "", title: str = "Nome da pasta") -> str | None:
    """Campo do nome com "Pasta N" em cinza claro; sem digitar, fica "Pasta N"."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    edit = QLineEdit(current)
    edit.setPlaceholderText(generic)
    edit.setMinimumWidth(280)
    lay.addWidget(edit)
    import dialogs
    lay.addWidget(dialogs.buttons(dlg, "OK"))
    edit.setFocus()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None if current else generic
    return edit.text().strip() or generic
