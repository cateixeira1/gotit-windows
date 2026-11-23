"""Editor de uma nota ou Teia: canvas, barra de formatação, ferramentas, páginas, desfazer
único, gravação automática, inserção de mídias, exportar PDF e imprimir."""

from __future__ import annotations

import copy
import json
import re
import time
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF, QMimeData, QPointF, QRectF, QSizeF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QGuiApplication, QImage, QKeySequence, QPageLayout,
                           QPageSize, QPainter, QPdfWriter, QShortcut, QTextCharFormat, QTextCursor, QTextListFormat)
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QGraphicsItem, QHBoxLayout, QInputDialog, QLabel,
                               QMenu, QMessageBox, QVBoxLayout, QWidget)

import assets as assets_mod
import dialogs
import icons
import ink
import items as items_mod
import model
import shapes
import textfmt
import theme
from canvas import CanvasScene, StoryItem
from canvas_view import INK_TOOLS, CanvasView
from editor_ui import FormatBar, PagesPanel, RoundButton, ToolsPanel, swatch_icon
from media import AudioController, FrameGrabber, RecorderDialog, VideoDialog
from textitem import EditableText
from undo import History

OBJ_MIME = "application/x-gotit-objects"
IMAGE_FILTER = "Imagens (*.png *.jpg *.jpeg *.heic *.heif *.webp *.gif *.bmp *.tif *.tiff)"
VIDEO_FILTER = "Vídeos (*.mp4 *.mov *.m4v *.avi *.wmv *.mkv *.webm)"
AUDIO_FILTER = "Áudio (*.m4a *.mp3 *.wav *.aac *.wma *.ogg *.flac *.opus)"


class ChronologyItem(QGraphicsItem):
    """Setas discretas da cronologia da Teia (pela data de criação das notas). É derivada:
    não é gravada e mover um cartão não muda a cronologia."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setZValue(8)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        sc = self.scene()
        return sc.sceneRect() if sc else QRectF()

    def paint(self, painter, option, widget=None):
        sc = self.scene()
        if sc is None or not self.editor.show_chronology:
            return
        cards = []
        for it in sc.items_by_id.values():
            if isinstance(it, items_mod.NoteRefItem):
                info = sc.resolve_note(it.data_state.get("documentID"))
                if info:
                    cards.append((info.get("createdRaw") or "", it))
        cards.sort(key=lambda c: c[0])
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.MUTED)
        color.setAlpha(150)
        from PySide6.QtGui import QPen
        for (_, a), (_, b) in zip(cards, cards[1:]):
            ca = a.mapToScene(QPointF(a.w / 2, a.h / 2))
            cb = b.mapToScene(QPointF(b.w / 2, b.h / 2))
            pa = items_mod._edge_point(a, ca, cb)
            pb = items_mod._edge_point(b, cb, ca)
            painter.setPen(QPen(color, 1.4, Qt.PenStyle.DashLine))
            painter.drawLine(pa, pb)
            items_mod.draw_arrow_head(painter, pa, pb, 1.2, color)


class Editor(QWidget):
    saved = Signal(str)
    openRequested = Signal(str)
    sidebarToggle = Signal()
    assistantRequested = Signal()
    trashed = Signal(str)
    teiaRequested = Signal(list)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.store = window.store
        self.assets = window.assets
        self.settings = window.settings
        self.scene: CanvasScene | None = None
        self.doc: dict | None = None
        self.history = History(self)
        self.media = AudioController(self)
        self.active_text = None
        self.dirty = False
        self.tool = "select"
        self.last_ink = "pen"
        self.ink = {"pen": {"color": "#1F2933", "width": 2.0}, "marker": {"color": "#F1BE5D", "width": 14.0},
                    "pencil": {"color": "#374151", "width": 1.6}}
        self.eraser_whole = False
        self.eraser_radius = 9.0
        self.show_chronology = True
        self._grabbers = []
        self._find_dialog = None
        self._last_state = None
        self._hw_pending: list = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.bar = FormatBar(self)
        lay.addWidget(self.bar)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.pages_panel = PagesPanel(self)
        self.pages_panel.hide()
        self.view = CanvasView(self)
        self.tools = ToolsPanel(self)
        body.addWidget(self.pages_panel)
        body.addWidget(self.view, 1)
        body.addWidget(self.tools)
        lay.addLayout(body, 1)
        self.toast_label = QLabel(self.view)
        self.toast_label.setStyleSheet("background: rgba(31,41,51,0.92); color: white; padding: 8px 14px; border-radius: 10px;")
        self.toast_label.hide()
        self.pen_button = RoundButton("pen", "Desenhar com a caneta (ou voltar à seleção)")
        self.pen_button.setParent(self.view)
        self.pen_button.clicked.connect(self.toggle_pen)
        self.ai_button = RoundButton("sparkle", "Assistente", theme.TEAL)
        self.ai_button.setCheckable(False)
        self.ai_button.setParent(self.view)
        self.ai_button.clicked.connect(self.assistantRequested.emit)

        self.bar.sidebar.clicked.connect(self.sidebarToggle.emit)
        self.bar.undo.clicked.connect(self.undo)
        self.bar.redo.clicked.connect(self.redo)
        self.bar.bold.clicked.connect(lambda: self.fmt("bold"))
        self.bar.italic.clicked.connect(lambda: self.fmt("italic"))
        self.bar.underline.clicked.connect(lambda: self.fmt("underline"))
        self.bar.strike.clicked.connect(lambda: self.fmt("strike"))
        self.bar.font_combo.activated.connect(lambda i: self.fmt("family", self.bar.font_combo.itemText(i)))
        self.bar.size_combo.activated.connect(lambda i: self._size_from_combo())
        self.bar.size_combo.lineEdit().returnPressed.connect(self._size_from_combo)
        self.bar.style_combo.activated.connect(lambda i: self.fmt("named", self.bar.style_combo.itemData(i)))
        self.bar.title.editingFinished.connect(self._title_edited)
        self.bar.pages.toggled.connect(self._toggle_pages)
        self.bar.tools.setChecked(True)
        self.bar.tools.toggled.connect(self.tools.setVisible)
        self.bar.set_fonts(theme.text_families())
        self.view.zoomChanged.connect(lambda z: self.bar.zoom.setText(f"{round(z * 100)}%"))
        self.view.visiblePageChanged.connect(self._visible_page)
        self.pages_panel.page_clicked.connect(self.scroll_to_page)
        self.history.changed.connect(self._history_changed)

        self.save_timer = QTimer(self, singleShot=True, interval=800, timeout=self.save_now)
        self.thumb_timer = QTimer(self, singleShot=True, interval=2500, timeout=self._update_thumbs)
        self.state_timer = QTimer(self, interval=180, timeout=self._refresh_state)
        self.state_timer.start()
        self.hw_timer = QTimer(self, singleShot=True, interval=1300, timeout=self._recognize_handwriting)
        self._shortcuts()
        self.tools.show_ink(self.ink["pen"]["color"], self.ink["pen"]["width"])
        self.tools.whole.setChecked(False)
        self._history_changed()

    # ================================================================== abrir e gravar
    def open_document(self, doc: dict, find: str | None = None, part: str | None = None) -> None:
        self.save_now()
        self.media.stop()
        old = self.scene
        self.doc = doc
        family = self.settings.value("defaultFont", theme.default_text_family())
        size = float(self.settings.value("defaultFontSize", 12))
        self.scene = CanvasScene(doc, self.assets, editor=self, resolver=self.window.resolve_note,
                                 default_font=(family, size))
        self.scene.pagesChanged.connect(lambda: self.thumb_timer.start())
        self.chrono = ChronologyItem(self)
        if doc.get("kind") == "web":
            self.scene.addItem(self.chrono)
        self.view.setScene(self.scene)
        self.history.clear()
        self.active_text = self.scene.story
        self.bar.title.setText(doc.get("title") or "")
        self.bar.title.setCursorPosition(0)
        simple = bool(doc["canvas"].get("simpleNote"))
        self.tools.setVisible(not simple and self.bar.tools.isChecked())
        self.bar.tools.setEnabled(not simple)
        self.pen_button.setVisible(not simple)
        canvas = doc["canvas"]
        for w, key in ((self.tools.recognize, "recognizeDiagrams"), (self.tools.handwriting, "handwritingToText"),
                       (self.tools.equations, "solveEquations")):
            w.blockSignals(True)
            w.setChecked(bool(canvas.get(key)))
            w.blockSignals(False)
        self.tools.hw_font.blockSignals(True)
        self.tools.hw_font.setCurrentText(canvas.get("handwritingFont") or "Caveat")
        self.tools.hw_font.blockSignals(False)
        self.set_tool("select")
        self.dirty = False
        self.view.resetTransform()
        QTimer.singleShot(0, self._after_open(find, part))
        if old is not None:
            old.editor = None
            old.deleteLater()
        self.store.mark_opened(doc["id"])
        self._update_bar_for_kind()
        self.thumb_timer.start()

    def _after_open(self, find, part):
        def run():
            if self.scene is None:
                return
            self.view.fit_width()
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().minimum())
            if find:
                if self.find_text(find, part):
                    return
            if self.doc.get("kind") != "web":
                # cursor no fim do texto, pronto para escrever
                self.scene.setFocusItem(self.scene.story)
                self.view.setFocus()
                self.scene.story.cursor_to_end()
                self.ensure_cursor_visible(self.scene.story)
        return run

    def _update_bar_for_kind(self) -> None:
        web = self.doc and self.doc.get("kind") == "web"
        self.ai_button.setVisible(bool(self.window.assistant_available()))
        self.position_floating()

    def close_document(self) -> None:
        self.save_now()
        self.media.stop()
        if self.scene is not None:
            self.scene.editor = None
        self.view.setScene(None)
        self.scene = None
        self.doc = None
        self.history.clear()

    def content_changed(self) -> None:
        if self.scene is None:
            return
        self.dirty = True
        self.save_timer.start()
        self.thumb_timer.start()

    def save_now(self) -> None:
        if self.scene is None or not self.dirty:
            return
        doc = self.scene.serialize()
        doc["title"] = doc.get("title") or "Nota sem título"
        saved = self.store.save(doc)
        doc["revision"] = saved["revision"]
        doc["updatedAt"] = saved["updatedAt"]
        self.dirty = False
        self.saved.emit(doc["id"])

    def _update_thumbs(self) -> None:
        if self.scene is None:
            return
        self.save_now()
        img = self.scene.render_page(0, 300)
        self.window.thumbs.put_live(self.doc["id"], self.doc.get("revision", 0), img)
        if self.pages_panel.isVisible():
            self.pages_panel.set_pages([self.scene.render_page(i, 104) for i in range(self.scene.page_count())])
        self.window.thumbnail_updated(self.doc["id"])

    def _toggle_pages(self, on: bool) -> None:
        self.pages_panel.setVisible(on)
        if on and self.scene is not None:
            self.pages_panel.set_pages([self.scene.render_page(i, 104) for i in range(self.scene.page_count())])
            self.pages_panel.setCurrentRow(self.view.current_page())

    def _visible_page(self, idx: int) -> None:
        if self.pages_panel.isVisible() and idx < self.pages_panel.count():
            self.pages_panel.blockSignals(True)
            self.pages_panel.setCurrentRow(idx)
            self.pages_panel.blockSignals(False)

    def scroll_to_page(self, idx: int) -> None:
        if self.scene is None:
            return
        r = self.scene.page_rect(idx)
        self.view.centerOn(r.center().x(), r.top() + self.view.viewport().height() / 2 / self.view.zoom() - 10)

    def _title_edited(self) -> None:
        if self.scene is None:
            return
        title = self.bar.title.text().strip() or self.doc.get("title")
        if title != self.doc.get("title"):
            with self.scene.change("Renomear"):
                self.doc["title"] = title
            self.save_now()

    def title_changed_externally(self) -> None:
        self.bar.title.setText(self.doc.get("title") or "")
        self.bar.title.setCursorPosition(0)

    # ================================================================== interface
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.position_floating()

    def view_resized(self) -> None:
        self.position_floating()

    def position_floating(self) -> None:
        vp = self.view.viewport()
        x = vp.width() - 52 - 22
        y = vp.height() - 52 - 22
        self.pen_button.move(x, y)
        self.ai_button.move(x, y - 52 - 14)
        self.pen_button.raise_()
        self.ai_button.raise_()

    def toast(self, text: str, ms: int = 3200) -> None:
        self.toast_label.setText(text)
        self.toast_label.adjustSize()
        vp = self.view.viewport()
        self.toast_label.move((vp.width() - self.toast_label.width()) // 2, vp.height() - self.toast_label.height() - 28)
        self.toast_label.show()
        self.toast_label.raise_()
        QTimer.singleShot(ms, self.toast_label.hide)

    def _history_changed(self) -> None:
        self.bar.undo.setEnabled(self.history.can_undo())
        self.bar.redo.setEnabled(self.history.can_redo())
        self.bar.undo.setToolTip(f"Desfazer {self.history.undo_label().lower()} (Ctrl+Z)" if self.history.can_undo() else "Desfazer (Ctrl+Z)")
        self.bar.redo.setToolTip(f"Refazer {self.history.redo_label().lower()} (Ctrl+Y)" if self.history.can_redo() else "Refazer (Ctrl+Y)")

    def _shortcuts(self) -> None:
        def sc(keys, fn):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            s.activated.connect(fn)
            return s
        sc("Ctrl+B", lambda: self.fmt("bold"))
        sc("Ctrl+I", lambda: self.fmt("italic"))
        sc("Ctrl+U", lambda: self.fmt("underline"))
        sc("Ctrl+K", self.insert_link)
        sc("Ctrl+H", self.find_replace)
        sc("Ctrl+F", self.find_replace)
        sc("Ctrl+]", lambda: self.fmt("grow", 1))
        sc("Ctrl+[", lambda: self.fmt("grow", -1))
        sc("Ctrl+L", lambda: self.fmt("align", "left"))
        sc("Ctrl+E", lambda: self.fmt("align", "center"))
        sc("Ctrl+R", lambda: self.fmt("align", "right"))
        sc("Ctrl+J", lambda: self.fmt("align", "justify"))
        sc("Ctrl+Z", self.undo)
        sc("Ctrl+Y", self.redo)
        sc("Ctrl+Shift+Z", self.redo)
        sc("Ctrl+=", lambda: self.view.set_zoom(self.view.zoom() * 1.25))
        sc("Ctrl++", lambda: self.view.set_zoom(self.view.zoom() * 1.25))
        sc("Ctrl+-", lambda: self.view.set_zoom(self.view.zoom() * 0.8))
        sc("Ctrl+0", lambda: self.view.set_zoom(1.0))
        sc("Ctrl+P", self.print_note)
        sc("Ctrl+Shift+E", self.export_pdf)
        sc("Ctrl+D", self.duplicate_selection)
        sc("Ctrl+Alt+P", self.toggle_pen)

    # ================================================================== ferramentas
    def set_tool(self, tool: str) -> None:
        if self.scene is None:
            return
        if tool == self.tool and tool in ("connector",) or (tool.startswith("shape:") and tool == self.tool):
            tool = "select"
        self.tool = tool
        if tool in INK_TOOLS:
            self.last_ink = tool
            self.tools.show_ink(self.ink[tool]["color"], self.ink[tool]["width"])
        self.view.set_tool(tool)
        self.tools.show_tool(tool)
        self.pen_button.blockSignals(True)
        self.pen_button.setChecked(tool in INK_TOOLS or tool == "eraser")
        self.pen_button.restyle()
        self.pen_button.blockSignals(False)
        if tool != "select":
            self.stop_all_editing()

    def toggle_pen(self) -> None:
        self.set_tool("select" if self.tool in INK_TOOLS or self.tool == "eraser" else self.last_ink)

    def ink_style(self, tool: str) -> tuple[str, float]:
        s = self.ink.get(tool, self.ink["pen"])
        return s["color"], s["width"]

    def set_ink_color(self, color: str) -> None:
        tool = self.tool if self.tool in INK_TOOLS else self.last_ink
        self.ink[tool]["color"] = color
        self.tools.show_ink(color, self.ink[tool]["width"])
        if self.tool not in INK_TOOLS:
            self.set_tool(tool)

    def set_ink_width(self, width: float) -> None:
        tool = self.tool if self.tool in INK_TOOLS else self.last_ink
        self.ink[tool]["width"] = max(0.5, width)
        if self.tool == "eraser":
            self.eraser_radius = max(3.0, width * 2)

    def set_eraser_whole(self, on: bool) -> None:
        self.eraser_whole = on

    def _canvas_flag(self, key: str, value) -> None:
        if self.scene is None or self.doc["canvas"].get(key) == value:
            return
        with self.scene.change("Ajustes da nota"):
            self.doc["canvas"][key] = value

    def set_recognize(self, on: bool) -> None:
        self._canvas_flag("recognizeDiagrams", on)

    def set_handwriting(self, on: bool) -> None:
        if on and not self.window.handwriting_available():
            self.tools.handwriting.blockSignals(True)
            self.tools.handwriting.setChecked(False)
            self.tools.handwriting.blockSignals(False)
            self.window.explain_handwriting()
            return
        self._canvas_flag("handwritingToText", on)

    def set_handwriting_font(self, family: str) -> None:
        self._canvas_flag("handwritingFont", family)

    def set_solve_equations(self, on: bool) -> None:
        self._canvas_flag("solveEquations", on)

    # ================================================================== tinta
    def finish_stroke(self, page: int, tool: str, scene_points: list) -> None:
        sc = self.scene
        top = page * sc.page_h
        pts = ink.simplify([(x, y - top, p) for x, y, p in scene_points])
        color, width = self.ink_style(tool)
        page_id = sc.page_id_at(page)
        canvas = self.doc["canvas"]
        if tool == "pen" and canvas.get("recognizeDiagrams") and len(pts) >= 6:
            found = shapes.recognize([(p[0], p[1]) for p in pts])
            if found is not None:
                self._insert_recognized(found, page, color, width)
                return
        state = ink.new_stroke_state(page_id, tool, color, width, pts)
        with sc.change("Desenho"):
            item = sc.add_stroke(state)
        if self.view.tool == "lasso":
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        if tool == "pen" and (canvas.get("handwritingToText") or canvas.get("solveEquations")):
            self._hw_pending.append(state["id"])
            self.hw_timer.start()

    def _insert_recognized(self, found: shapes.Recognized, page: int, color: str, width: float) -> None:
        sc = self.scene
        page_id = sc.page_id_at(page)
        x, y, w, h = found.frame
        if found.kind in ("line", "arrow"):
            (x1, y1), (x2, y2) = found.points
            # linha ligando duas formas vira conexão (acompanha as formas)
            a = self.block_at(QPointF(x1, y1 + page * sc.page_h), shapes_only=True)
            b = self.block_at(QPointF(x2, y2 + page * sc.page_h), shapes_only=True)
            if a is not None and b is not None and a is not b:
                self.connect_blocks(a, b, color=color, width=max(1.5, width), arrow=found.kind == "arrow")
                return
            x0, y0 = min(x1, x2), min(y1, y2)
            state = {"id": model.new_id(), "kind": "line", "shape": found.kind, "pageID": page_id,
                     "frame": {"x": x0, "y": y0, "width": max(1, abs(x2 - x1)), "height": max(1, abs(y2 - y1))},
                     "points": [[x1 - x0, y1 - y0], [x2 - x0, y2 - y0]], "stroke": color,
                     "lineWidth": max(1.5, width), "z": sc.next_z()}
        else:
            state = {"id": model.new_id(), "kind": "shape", "shape": found.kind, "pageID": page_id,
                     "frame": {"x": x, "y": y, "width": max(20, w), "height": max(20, h)}, "rotation": found.rotation,
                     "stroke": color, "fill": None, "lineWidth": max(1.5, width), "z": sc.next_z(), "text": "", "html": ""}
            if found.vertices:
                state["vertices"] = found.vertices
        with sc.change("Forma"):
            sc.add_block(state)

    def erase_at(self, pos: QPointF) -> None:
        sc = self.scene
        r = self.eraser_radius / max(0.3, self.view.zoom()) * 1.0
        box = QRectF(pos.x() - r, pos.y() - r, 2 * r, 2 * r)
        for sid, st in list(sc.strokes_by_id.items()):
            if not st.sceneBoundingRect().intersects(box):
                continue
            local = pos - st.pos()
            state = st.state()
            result = ink.erase(state, local.x(), local.y() - (sc.page_index_of(state.get("pageID")) * sc.page_h - st.pos().y()),
                               r, self.eraser_whole)
            if result is None:
                continue
            sc.remove_stroke(sid)
            for piece in result:
                sc.add_stroke(piece)

    def _recognize_handwriting(self) -> None:
        pending, self._hw_pending = self._hw_pending, []
        if self.scene is None or not pending:
            return
        strokes = [self.scene.strokes_by_id[s] for s in pending if s in self.scene.strokes_by_id]
        if strokes:
            self.window.recognize_handwriting(self, strokes)

    # ================================================================== objetos: criar
    def _occupied(self, page: int) -> list[tuple]:
        sc = self.scene
        top = page * sc.page_h
        rects = []
        for it in sc.items_by_id.values():
            r = it.sceneBoundingRect() if abs(it.rotation()) > 0.1 else QRectF(it.pos(), QSizeF(it.w, it.h))
            if sc.page_at_y(r.center().y()) == page:
                rects.append((r.x(), r.y() - top, r.width(), r.height()))
        # o texto já escrito também ocupa lugar (texto vazio não)
        doc = sc.story.document()
        lay = doc.documentLayout()
        block = doc.begin()
        m = sc._text_margins
        while block.isValid():
            if block.text().strip():
                layout = block.layout()
                br = lay.blockBoundingRect(block)
                for i in range(layout.lineCount()):
                    line = layout.lineAt(i)
                    y = br.y() + line.y()
                    if int(y // sc.page_h) == page:
                        rects.append((m["left"], y - top, sc.page_w - m["left"] - m["right"], line.height()))
            block = block.next()
        for st in sc.strokes_by_id.values():
            r = st.sceneBoundingRect()
            if sc.page_at_y(r.center().y()) == page:
                rects.append((r.x(), r.y() - top, r.width(), r.height()))
        return rects

    def _place(self, w: float, h: float, at: QPointF | None = None, page: int | None = None) -> tuple[str, float, float, int]:
        sc = self.scene
        if at is not None:
            page = sc.page_at_y(at.y())
            return sc.page_id_at(page), at.x() - w / 2, at.y() - page * sc.page_h - h / 2, page
        page = self.view.current_page() if page is None else page
        x, y = model.first_free_spot({**self.doc, "blocks": []}, sc.page_id_at(page), w, h, self._occupied(page))
        return sc.page_id_at(page), x, y, page

    def _add(self, kind: str, w: float, h: float, label: str, at=None, page=None, select=True, **fields):
        sc = self.scene
        page_id, x, y, _ = self._place(w, h, at, page)
        state = {"id": model.new_id(), "kind": kind, "pageID": page_id,
                 "frame": {"x": round(x, 2), "y": round(y, 2), "width": w, "height": h}, "z": sc.next_z(), **fields}
        self.stop_all_editing()
        with sc.change(label):
            item = sc.add_block(state)
        if select:
            sc.clearSelection()
            item.setSelected(True)
            self.view.ensureVisible(item, 40, 60)
        return item

    def text_width(self) -> float:
        m = self.scene._text_margins
        return self.scene.page_w - m["left"] - m["right"]

    def insert_text_box(self, at=None) -> None:
        item = self._add("text", 240, 40, "Caixa de texto", at=at, text="", html="", fontSize=self.scene.default_size)
        item.start_editing()

    def insert_sticky(self, color: str, at=None) -> None:
        item = self._add("sticky", model.STICKY_SIDE, model.STICKY_SIDE, "Post-it", at=at, fill=color, text="", html="",
                         foreground="#2B2B2B")
        item.start_editing()

    def insert_calendar(self, at=None) -> None:
        w, h = model.CALENDAR_SIZE
        self._add("calendar", w, h, "Calendário", at=at, date=date.today().isoformat())

    def insert_table(self) -> None:
        dlg = dialogs.TableDialog(self)
        if self.active_text is None or self.active_text is not self.scene.story:
            dlg.where.setCurrentIndex(1)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rows, cols = dlg.rows.value(), dlg.cols.value()
        if dlg.where.currentData() == "story":
            story = self.scene.story
            self.scene.setFocusItem(story)
            textfmt.insert_table(story, rows, cols)
            return
        w = min(self.text_width(), 120 * cols)
        self._add("table", w, rows * 30 + 4, "Tabela", rows=rows, columns=cols, header=True, text="", html="",
                  fontSize=max(10.0, self.scene.default_size - 1))

    def finish_shape_drag(self, kind: str, a: QPointF, b: QPointF) -> None:
        sc = self.scene
        r = QRectF(a, b).normalized()
        if kind in ("line", "arrow"):
            if (b - a).manhattanLength() < 8:
                b = a + QPointF(140, 0)
            page = sc.page_at_y(a.y())
            top = page * sc.page_h
            x0, y0 = min(a.x(), b.x()), min(a.y(), b.y())
            state = {"id": model.new_id(), "kind": "line", "shape": kind, "pageID": sc.page_id_at(page),
                     "frame": {"x": x0, "y": y0 - top, "width": max(1, abs(b.x() - a.x())), "height": max(1, abs(b.y() - a.y()))},
                     "points": [[a.x() - x0, a.y() - y0], [b.x() - x0, b.y() - y0]], "stroke": "#1F2933", "lineWidth": 2,
                     "z": sc.next_z()}
            with sc.change(model.SHAPE_TITLES[kind]):
                item = sc.add_block(state)
        else:
            if r.width() < 8 or r.height() < 8:
                r = QRectF(a.x() - 70, a.y() - 45, 140, 90)
            page = sc.page_at_y(r.center().y())
            top = page * sc.page_h
            state = {"id": model.new_id(), "kind": "shape", "shape": kind, "pageID": sc.page_id_at(page),
                     "frame": {"x": r.x(), "y": r.y() - top, "width": r.width(), "height": r.height()},
                     "stroke": "#1F2933", "fill": None, "lineWidth": 2, "z": sc.next_z(), "text": "", "html": ""}
            with sc.change(model.SHAPE_TITLES[kind]):
                item = sc.add_block(state)
        self.set_tool("select")
        sc.clearSelection()
        item.setSelected(True)

    def connect_blocks(self, a, b, color="#334155", width=2.0, arrow=True) -> None:
        state = {"id": model.new_id(), "sourceID": a.block_id, "targetID": b.block_id, "kind": "connector",
                 "style": {"color": color, "width": width, "arrowAtEnd": arrow, "routing": "straight"}}
        with self.scene.change("Conexão"):
            self.scene.add_connector(state)
        if self.tool == "connector":
            self.set_tool("select")

    def block_at(self, pos: QPointF, shapes_only: bool = False):
        for it in self.scene.items(pos):
            if isinstance(it, items_mod.BlockItem) and not isinstance(it, items_mod.LineItem):
                if shapes_only and not isinstance(it, (items_mod.ShapeItem, items_mod.StickyItem, items_mod.NoteRefItem,
                                                       items_mod.TextBoxItem, items_mod.ImageItem)):
                    continue
                return it
            if isinstance(it, EditableText) and it.owner is not None:
                return it.owner
        return None

    # ------------------------------------------------------------------ mídias
    def _import_image(self, path: Path) -> str | None:
        converted = assets_mod.import_image_bytes_safe(path)
        if converted:
            data, ext = converted
            return self.store.import_bytes(data, ext)
        return self.store.import_asset(path)

    def choose_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Inserir imagens", self._last_dir(), IMAGE_FILTER)
        if paths:
            self._remember_dir(paths[0])
            self.insert_files(paths)

    def choose_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Inserir PDF", self._last_dir(), "PDF (*.pdf)")
        if path:
            self._remember_dir(path)
            self.insert_pdf(Path(path))

    def choose_pdf_annotate(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "PDF para anotar", self._last_dir(), "PDF (*.pdf)")
        if path:
            self._remember_dir(path)
            self.annotate_pdf(self.store.import_asset(Path(path)), Path(path).stem)

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Inserir vídeo", self._last_dir(), VIDEO_FILTER)
        if path:
            self._remember_dir(path)
            self.insert_video(Path(path))

    def choose_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Inserir áudio", self._last_dir(), AUDIO_FILTER)
        if path:
            self._remember_dir(path)
            self.insert_audio(Path(path))

    def _last_dir(self) -> str:
        return self.settings.value("lastDir", str(Path.home()))

    def _remember_dir(self, path: str) -> None:
        self.settings.setValue("lastDir", str(Path(path).parent))

    def insert_files(self, paths: list[str], at: QPointF | None = None) -> None:
        for i, p in enumerate(paths):
            path = Path(p)
            ext = path.suffix.lower()
            pos = at + QPointF(i * 24, i * 24) if at is not None else None
            if ext in assets_mod.IMAGE_EXT:
                self.insert_image(path, at=pos)
            elif ext == ".pdf":
                self.insert_pdf(path, at=pos)
            elif ext in assets_mod.VIDEO_EXT:
                self.insert_video(path, at=pos)
            elif ext in assets_mod.AUDIO_EXT:
                self.insert_audio(path, at=pos)
            elif ext in (".txt", ".md", ".csv"):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                c = self.scene.story.textCursor()
                c.insertText(text)

    def _fit(self, w: float, h: float, max_w: float | None = None, max_h: float = 420) -> tuple[float, float]:
        max_w = max_w or min(self.text_width(), 380)
        scale = min(1.0, max_w / max(1, w), max_h / max(1, h))
        return max(24, w * scale), max(24, h * scale)

    def insert_image(self, path: Path, at=None, sticker: bool = False) -> None:
        digest = self._import_image(path)
        if not digest:
            self.toast("Não foi possível ler esta imagem.")
            return
        iw, ih = self.assets.image_size(digest)
        if sticker:
            w, h = self._fit(iw, ih, 140, 140)
            self._add("sticker", w, h, "Sticker", at=at, asset=digest)
            return
        w, h = self._fit(iw / 1.33, ih / 1.33)
        self._add("image", w, h, "Imagem", at=at, asset=digest, caption=path.stem)

    def insert_qimage(self, image: QImage, at=None) -> None:
        if image is None or image.isNull():
            return
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buf, "PNG")
        digest = self.store.import_bytes(bytes(ba.data()), ".png")
        w, h = self._fit(image.width() / 1.33, image.height() / 1.33)
        self._add("image", w, h, "Imagem", at=at, asset=digest, caption="Imagem colada")

    def insert_pdf(self, path: Path, at=None) -> None:
        digest = self.store.import_asset(path)
        if not self.assets.pdf_page_count(digest):
            self.toast("Não foi possível abrir este PDF.")
            return
        pw, ph = self.assets.pdf_page_size(digest, 0)
        w = 190.0
        self._add("pdf", w, w * ph / pw, "PDF", at=at, asset=digest, caption=path.stem, page=0)

    def annotate_pdf(self, digest: str, name: str) -> None:
        """Cada página do PDF vira uma página da nota, com o PDF por baixo, para escrever,
        desenhar e digitar por cima (até 100 por vez; um só desfazer)."""
        sc = self.scene
        n = self.assets.pdf_page_count(digest)
        if not n:
            self.toast("Não foi possível abrir este PDF.")
            return
        n = min(n, 100)
        with sc.change("PDF para anotar"):
            pages = sc.doc["pages"]
            start = len(pages)
            first_blank = (len(pages) == 1 and not sc.story.document().toPlainText().strip()
                           and not sc.items_by_id and not sc.strokes_by_id and not pages[0].get("background"))
            for i in range(n):
                bg = {"asset": digest, "page": i, "name": name}
                if i == 0 and first_blank:
                    pages[0]["background"] = bg
                    pages[0].pop("auto", None)
                    start = 0
                    continue
                page = model.new_page()
                page["background"] = bg
                pages.append(page)
            sc.update_pages()
        self.scroll_to_page(start)
        if n < self.assets.pdf_page_count(digest):
            self.toast(f"Entraram as primeiras {n} páginas.")

    def insert_video(self, path: Path, at=None) -> None:
        digest = self.store.import_asset(path)
        item = self._add("video", 320, 180, "Vídeo", at=at, asset=digest, caption=path.stem)
        grab = FrameGrabber(path, self)
        self._grabbers.append(grab)

        def done(image, duration, item=item, grab=grab):
            fields = {}
            if duration:
                fields["duration"] = round(duration, 2)
            if image is not None and not image.isNull():
                from PySide6.QtCore import QBuffer, QByteArray, QIODevice
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                image.scaled(960, 960, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(buf, "JPG", 85)
                fields["poster"] = self.store.import_bytes(bytes(ba.data()), ".jpg")
                h = 320 * image.height() / max(1, image.width())
                fields["frame_h"] = h
            self._patch_block(item, fields)
            if grab in self._grabbers:
                self._grabbers.remove(grab)
        grab.done.connect(done)

    def insert_audio(self, path: Path, at=None, caption: str | None = None) -> None:
        digest = self.store.import_asset(path, path.suffix or ".m4a")
        item = self._add("audio", 300, model.AUDIO_HEIGHT, "Áudio", at=at, asset=digest, caption=caption or path.stem)
        grab = FrameGrabber(path, self, want_frame=False)
        self._grabbers.append(grab)

        def done(_img, duration, item=item, grab=grab):
            if duration:
                self._patch_block(item, {"duration": round(duration, 2)})
            if grab in self._grabbers:
                self._grabbers.remove(grab)
        grab.done.connect(done)

    def _patch_block(self, item, fields: dict) -> None:
        """Metadados descobertos depois de inserir (capa, duração): valem também no desfazer."""
        if item.scene() is None:
            return
        frame_h = fields.pop("frame_h", None)
        item.data_state.update(fields)
        if frame_h:
            item.resize_to(item.w, frame_h)
        key = "b:" + item.block_id
        for entry in self.history.entries:
            diff = getattr(entry, "diff", None)
            if diff and key in diff:
                before, after = diff[key]
                if after is not None:
                    after.update(fields)
                    if frame_h:
                        after["frame"]["height"] = frame_h
                if before is not None:
                    before.update(fields)
        item.update()
        self.content_changed()

    def record_audio(self) -> None:
        dlg = RecorderDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.path and Path(dlg.path).exists():
            stamp = datetime.now().strftime("%d/%m %H:%M")
            self.insert_audio(Path(dlg.path), caption=f"Gravação {stamp}")
            try:
                Path(dlg.path).unlink()
            except OSError:
                pass

    def choose_sticker(self) -> None:
        dlg = dialogs.StickerDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
            return
        kind, value = dlg.choice
        if kind == "emoji":
            self._add("sticker", 96, 96, "Sticker", emoji=value)
        elif kind == "sticky":
            self.insert_sticky(model.STICKY_COLORS[0][1])
        elif kind == "calendar":
            self.insert_calendar()
        elif kind == "image":
            path, _ = QFileDialog.getOpenFileName(self, "Imagem do sticker", self._last_dir(), IMAGE_FILTER)
            if path:
                self.insert_image(Path(path), sticker=True)

    # ================================================================== objetos: editar
    def selected_blocks(self) -> list:
        if self.scene is None:
            return []
        return [it for it in self.scene.selectedItems() if isinstance(it, items_mod.BlockItem)]

    def selected_strokes(self) -> list:
        return [it for it in self.scene.selectedItems() if isinstance(it, ink.StrokeItem)] if self.scene else []

    def delete_selection(self) -> None:
        sc = self.scene
        blocks, strokes = self.selected_blocks(), self.selected_strokes()
        conns = [c for c in sc.selectedItems() if isinstance(c, items_mod.ConnectorItem)]
        if not (blocks or strokes or conns):
            return
        with sc.change("Apagar"):
            for it in blocks:
                sc.remove_block(it.block_id)
            for st in strokes:
                sc.remove_stroke(st.stroke_id)
            for c in conns:
                sc.remove_connector(c.rel_id)

    def block_removed(self, item) -> None:
        if self.media.item is item:
            self.media.stop()
        if self.active_text is getattr(item, "text", None):
            self.active_text = self.scene.story if self.scene else None

    def copy_selection(self, cut: bool = False) -> bool:
        blocks, strokes = self.selected_blocks(), self.selected_strokes()
        if not blocks and not strokes:
            return False
        payload = {"blocks": [b.state() for b in blocks], "strokes": [s.state() for s in strokes]}
        md = QMimeData()
        md.setData(OBJ_MIME, json.dumps(payload).encode())
        md.setText("\n".join(b.search_text() for b in blocks if b.search_text()))
        QGuiApplication.clipboard().setMimeData(md)
        if cut:
            self.delete_selection()
        return True

    def paste_objects(self) -> bool:
        md = QGuiApplication.clipboard().mimeData()
        if md.hasFormat(OBJ_MIME):
            payload = json.loads(bytes(md.data(OBJ_MIME)).decode())
            self._paste_payload(payload, offset=16)
            return True
        if md.hasImage():
            self.insert_qimage(md.imageData())
            return True
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            self.insert_files([u.toLocalFile() for u in md.urls() if u.isLocalFile()])
            return True
        return False

    def _paste_payload(self, payload: dict, offset: float) -> None:
        sc = self.scene
        page = self.view.current_page()
        page_id = sc.page_id_at(page)
        ids = {}
        sc.clearSelection()
        new_items = []
        with sc.change("Colar"):
            z = sc.next_z()
            for st in payload.get("blocks", []):
                st = copy.deepcopy(st)
                ids[st["id"]] = model.new_id()
                st["id"] = ids[st["id"]]
                st["frame"]["x"] += offset
                st["frame"]["y"] += offset
                st["z"] = z
                z += 1
                new_items.append(sc.add_block(st))
            for st in payload.get("strokes", []):
                st = copy.deepcopy(st)
                st["id"] = model.new_id()
                st["points"] = [[p[0] + offset, p[1] + offset, p[2]] for p in st["points"]]
                new_items.append(sc.add_stroke(st))
        for it in new_items:
            it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            it.setSelected(True)

    def duplicate_selection(self) -> None:
        blocks, strokes = self.selected_blocks(), self.selected_strokes()
        if blocks or strokes:
            self._paste_payload({"blocks": [b.state() for b in blocks], "strokes": [s.state() for s in strokes]}, 18)

    def bring_to_front(self, front: bool = True) -> None:
        sc = self.scene
        blocks = self.selected_blocks()
        if not blocks:
            return
        with sc.change("Trazer para a frente" if front else "Enviar para trás"):
            zs = [int(it.zValue() - 10) for it in sc.items_by_id.values()]
            if front:
                z = max(zs) + 1
                for it in sorted(blocks, key=lambda i: i.zValue()):
                    it.setZValue(10 + z)
                    z += 1
            else:
                z = min(zs) - len(blocks)
                for it in sorted(blocks, key=lambda i: i.zValue()):
                    it.setZValue(10 + z)
                    z += 1
            sc.refresh_connectors()

    def rotate_selection(self, degrees: float) -> None:
        blocks = [b for b in self.selected_blocks() if b.rotatable]
        if not blocks:
            return
        with self.scene.change("Girar"):
            for b in blocks:
                b.setRotation((b.rotation() + degrees) % 360)
            self.scene.refresh_connectors()

    def set_block_field(self, items, label: str, **fields) -> None:
        with self.scene.change(label):
            for it in items:
                st = it.state()
                st.update(fields)
                it.set_state(st)

    def pick_calendar_date(self, item) -> None:
        dlg = dialogs.CalendarDialog(item.day(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_block_field([item], "Data do calendário", date=dlg.value())

    def toggle_fold(self, item) -> None:
        """Recolhe a transcrição a um quadrado (o texto fica oculto, não é apagado) ou abre."""
        with self.scene.change("Recolher" if not item.folded else "Abrir"):
            st = item.state()
            if item.folded:
                fold = st.pop("folded")
                exp, small = fold["expanded"], fold["folded"]
                dx, dy = st["frame"]["x"] - small["x"], st["frame"]["y"] - small["y"]
                st["frame"] = {"x": exp["x"] + dx, "y": exp["y"] + dy, "width": exp["width"], "height": exp["height"]}
            else:
                side = model.AUDIO_HEIGHT + 8
                f = st["frame"]
                square = {"x": f["x"], "y": f["y"], "width": side, "height": side}
                st["folded"] = {"expanded": dict(f), "folded": dict(square)}
                st["frame"] = square
            item.set_state(st)
            item.min_w = item.min_h = 24.0

    def open_pdf(self, item) -> None:
        digest = item.data_state.get("asset")
        path = self.store.asset_path(digest)
        if not path:
            self.toast("O arquivo deste PDF não foi encontrado.")
            return
        dlg = dialogs.PdfViewer(self.assets, digest, item.data_state.get("caption") or "PDF", path, self)
        dlg.annotate.connect(lambda: self.annotate_pdf(digest, item.data_state.get("caption") or "PDF"))
        dlg.exec()

    def open_video(self, item) -> None:
        path = self.store.asset_path(item.data_state.get("asset"))
        if not path:
            self.toast("O arquivo deste vídeo não foi encontrado.")
            return
        self.media.stop()
        VideoDialog(path, item.data_state.get("caption") or "Vídeo", self).exec()

    def open_note(self, doc_id: str) -> None:
        self.save_now()
        self.openRequested.emit(doc_id)

    def save_asset_as(self, item, title: str, filt: str) -> None:
        path = self.store.asset_path(item.data_state.get("asset"))
        if not path:
            return
        name = (item.data_state.get("caption") or "arquivo") + path.suffix
        dest, _ = QFileDialog.getSaveFileName(self, title, str(Path(self._last_dir()) / name), filt)
        if dest:
            import shutil
            shutil.copyfile(path, dest)

    # ================================================================== menus
    def object_menu(self, item, screen_pos) -> None:
        m = QMenu(self)
        blocks = self.selected_blocks() or [item]
        if isinstance(item, items_mod.TextBlock):
            m.addAction(icons.icon("textbox"), "Editar o texto").triggered.connect(lambda: item.start_editing())
        item.menu_actions(m, self)
        if isinstance(item, items_mod.CalendarItem):
            m.addAction(icons.icon("calendar"), "Escolher a data…").triggered.connect(lambda: self.pick_calendar_date(item))
        if isinstance(item, items_mod.PdfItem):
            m.addAction(icons.icon("eye"), "Abrir o PDF").triggered.connect(lambda: self.open_pdf(item))
            m.addAction(icons.icon("pdf-annotate"), "Anotar este PDF na nota").triggered.connect(
                lambda: self.annotate_pdf(item.data_state["asset"], item.data_state.get("caption") or "PDF"))
            m.addAction(icons.icon("download"), "Salvar o PDF como…").triggered.connect(lambda: self.save_asset_as(item, "Salvar PDF", "PDF (*.pdf)"))
        if isinstance(item, items_mod.VideoItem):
            m.addAction(icons.icon("play"), "Abrir o vídeo").triggered.connect(lambda: self.open_video(item))
            m.addAction(icons.icon("download"), "Salvar o vídeo como…").triggered.connect(lambda: self.save_asset_as(item, "Salvar vídeo", VIDEO_FILTER))
        if isinstance(item, items_mod.TranscriptItem):
            m.addAction(icons.icon("transcript"), "Abrir" if item.folded else "Recolher").triggered.connect(lambda: self.toggle_fold(item))
        if isinstance(item, items_mod.NoteRefItem):
            m.addAction(icons.icon("note"), "Abrir a nota").triggered.connect(lambda: item.activate())
        if isinstance(item, items_mod.TableItem):
            self._table_menu(m, item.text, item)
        if isinstance(item, (items_mod.ShapeItem, items_mod.TextBoxItem, items_mod.LineItem, items_mod.StickyItem)):
            self._style_menus(m, blocks)
        if isinstance(item, items_mod.ShapeItem):
            sub = m.addMenu(icons.icon("shapes"), "Trocar a forma")
            for kind in ("rectangle", "ellipse", "diamond", "triangle"):
                sub.addAction(icons.icon(kind), model.SHAPE_TITLES[kind]).triggered.connect(
                    lambda _=False, k=kind: self.set_block_field(blocks, "Trocar a forma", shape=k, vertices=None))
        m.addSeparator()
        if not isinstance(item, items_mod.LineItem):
            m.addAction(icons.icon("connector"), "Conectar a outro objeto").triggered.connect(lambda: self.set_tool("connector"))
        m.addAction(icons.icon("bring-front"), "Trazer para a frente").triggered.connect(lambda: self.bring_to_front(True))
        m.addAction(icons.icon("send-back"), "Enviar para trás").triggered.connect(lambda: self.bring_to_front(False))
        if item.rotatable:
            m.addAction(icons.icon("rotate"), "Girar 90°").triggered.connect(lambda: self.rotate_selection(90))
        m.addSeparator()
        m.addAction("Recortar").triggered.connect(lambda: self.copy_selection(cut=True))
        m.addAction(icons.icon("copy"), "Copiar").triggered.connect(lambda: self.copy_selection())
        m.addAction("Duplicar (Ctrl+D)").triggered.connect(self.duplicate_selection)
        a = m.addAction(icons.icon("trash", theme.DANGER), "Apagar")
        a.triggered.connect(self.delete_selection)
        m.exec(screen_pos)

    def _style_menus(self, m: QMenu, blocks: list) -> None:
        sticky = [b for b in blocks if isinstance(b, items_mod.StickyItem)]
        others = [b for b in blocks if not isinstance(b, items_mod.StickyItem)]
        if sticky:
            sub = m.addMenu(icons.icon("sticky"), "Cor do post-it")
            for title, value in model.STICKY_COLORS:
                sub.addAction(swatch_icon(value), title).triggered.connect(
                    lambda _=False, v=value: self.set_block_field(sticky, "Cor do post-it", fill=v))
        if not others:
            return
        if any(not isinstance(b, items_mod.LineItem) for b in others):
            sub = m.addMenu("Preenchimento")
            for value in theme.SHAPE_FILLS:
                sub.addAction(swatch_icon(value), "Sem preenchimento" if value is None else value).triggered.connect(
                    lambda _=False, v=value: self.set_block_field(others, "Preenchimento", fill=v))
        sub = m.addMenu("Cor do contorno")
        none = sub.addAction(swatch_icon(None), "Sem contorno")
        none.triggered.connect(lambda: self.set_block_field(others, "Contorno", stroke=None if any(isinstance(b, items_mod.TextBoxItem) for b in others) else "#00000000", lineWidth=0))
        for value in theme.INK_COLORS:
            sub.addAction(swatch_icon(value), value).triggered.connect(
                lambda _=False, v=value: self.set_block_field(others, "Contorno", stroke=v,
                                                              lineWidth=max(1.0, float(others[0].data_state.get("lineWidth") or 2))))
        sub = m.addMenu("Espessura")
        for w in (1, 2, 3, 4, 6, 8):
            sub.addAction(f"{w} pt").triggered.connect(lambda _=False, v=w: self.set_block_field(others, "Espessura", lineWidth=v))
        if any(isinstance(b, items_mod.LineItem) for b in others):
            lines = [b for b in others if isinstance(b, items_mod.LineItem)]
            m.addAction(icons.icon("arrow"), "Seta na ponta").triggered.connect(
                lambda: self.set_block_field(lines, "Seta", shape="line" if lines[0].data_state.get("shape") == "arrow" else "arrow"))

    def image_menu(self, item, m: QMenu) -> None:
        m.addAction(icons.icon("crop"), "Recortar…").triggered.connect(lambda: self.crop_image(item))
        if item.data_state.get("crop"):
            m.addAction("Desfazer o recorte").triggered.connect(lambda: self.set_block_field([item], "Recorte", crop=None))
        sub = m.addMenu(icons.icon("ellipse"), "Formato da imagem")
        for kind, title in ((None, "Retangular"), ("ellipse", "Elipse"), ("rectangle", "Cantos arredondados"),
                            ("diamond", "Losango"), ("triangle", "Triângulo")):
            sub.addAction(title).triggered.connect(lambda _=False, k=kind: self.set_block_field([item], "Formato da imagem", mask=k))
        m.addAction(icons.icon("cutout"), "Remover o fundo…").triggered.connect(lambda: self.window.remove_background(self, item))
        m.addAction("Legenda…").triggered.connect(lambda: self._caption(item))
        m.addAction(icons.icon("download"), "Salvar a imagem como…").triggered.connect(lambda: self.save_asset_as(item, "Salvar imagem", IMAGE_FILTER))
        m.addAction("Copiar a imagem").triggered.connect(lambda: QGuiApplication.clipboard().setImage(
            self.assets.image(item.data_state.get("asset"), 4096) or QImage()))

    def audio_menu(self, item, m: QMenu) -> None:
        m.addAction(icons.icon("play"), "Tocar ou pausar").triggered.connect(lambda: self.media.toggle(item))
        t = m.addAction(icons.icon("transcript"), "Transcrever…")
        t.triggered.connect(lambda: self.window.transcribe(self, item))
        m.addAction("Renomear…").triggered.connect(lambda: self._caption(item, "Nome do áudio"))
        m.addAction(icons.icon("download"), "Salvar o áudio como…").triggered.connect(lambda: self.save_asset_as(item, "Salvar áudio", AUDIO_FILTER))

    def _caption(self, item, title: str = "Legenda") -> None:
        text, ok = QInputDialog.getText(self, title, title + ":", text=item.data_state.get("caption") or "")
        if ok:
            self.set_block_field([item], title, caption=text.strip())

    def crop_image(self, item) -> None:
        crop = item.data_state.get("crop") or {"x": 0, "y": 0, "width": 1, "height": 1}
        dlg = QDialog(self)
        dlg.setWindowTitle("Recortar a imagem (%)")
        from PySide6.QtWidgets import QFormLayout, QSpinBox
        form = QFormLayout(dlg)
        spins = {}
        for key, title, value in (("left", "Esquerda", crop["x"]), ("top", "Em cima", crop["y"]),
                                  ("right", "Direita", 1 - crop["x"] - crop["width"]), ("bottom", "Embaixo", 1 - crop["y"] - crop["height"])):
            s = QSpinBox()
            s.setRange(0, 95)
            s.setSuffix(" %")
            s.setValue(int(round(value * 100)))
            spins[key] = s
            form.addRow(f"Cortar à {title.lower()}" if key in ("left", "right") else f"Cortar {title.lower()}", s)
        form.addRow(dialogs.buttons(dlg, "Recortar"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        l, t, r, b = (spins[k].value() / 100 for k in ("left", "top", "right", "bottom"))
        if l + r >= 0.95 or t + b >= 0.95:
            return
        new = {"x": l, "y": t, "width": 1 - l - r, "height": 1 - t - b}
        # o que fica visível não muda de escala: a moldura acompanha o recorte
        ow, oh = item.w / crop["width"], item.h / crop["height"]
        st = item.state()
        st["crop"] = new
        st["frame"]["x"] += (new["x"] - crop["x"]) * ow
        st["frame"]["y"] += (new["y"] - crop["y"]) * oh
        st["frame"]["width"] = ow * new["width"]
        st["frame"]["height"] = oh * new["height"]
        with self.scene.change("Recortar"):
            item.set_state(st)

    def connector_menu(self, conn, screen_pos) -> None:
        m = QMenu(self)
        sub = m.addMenu("Cor da conexão")
        for value in theme.INK_COLORS[:7]:
            sub.addAction(swatch_icon(value), value).triggered.connect(lambda _=False, v=value: self._conn_style(conn, color=v))
        sub = m.addMenu("Espessura")
        for w in (1, 2, 3, 4, 6):
            sub.addAction(f"{w} pt").triggered.connect(lambda _=False, v=w: self._conn_style(conn, width=v))
        style = conn.data_state.get("style") or {}
        m.addAction("Seta na ponta").triggered.connect(lambda: self._conn_style(conn, arrowAtEnd=not style.get("arrowAtEnd", True)))
        m.addAction("Linha em ângulo reto" if style.get("routing") != "orthogonal" else "Linha reta").triggered.connect(
            lambda: self._conn_style(conn, routing="straight" if style.get("routing") == "orthogonal" else "orthogonal"))
        m.addSeparator()
        m.addAction(icons.icon("trash", theme.DANGER), "Apagar a conexão").triggered.connect(lambda: self._del_conn(conn))
        m.exec(screen_pos)

    def _conn_style(self, conn, **kw) -> None:
        with self.scene.change("Conexão"):
            st = conn.state()
            st.setdefault("style", {}).update(kw)
            conn.set_state(st)

    def _del_conn(self, conn) -> None:
        with self.scene.change("Apagar conexão"):
            self.scene.remove_connector(conn.rel_id)

    def text_context_menu(self, item, screen_pos, anchor: str = "") -> None:
        m = QMenu(self)
        c = item.textCursor()
        has_sel = c.hasSelection()
        m.addAction("Recortar").triggered.connect(lambda: self._text_action(item, "cut"))
        m.actions()[-1].setEnabled(has_sel)
        m.addAction(icons.icon("copy"), "Copiar").triggered.connect(lambda: self._text_action(item, "copy"))
        m.actions()[-1].setEnabled(has_sel)
        m.addAction("Colar").triggered.connect(lambda: self._text_action(item, "paste"))
        m.addAction("Colar sem formatação").triggered.connect(lambda: self._text_action(item, "paste_plain"))
        m.addSeparator()
        if anchor:
            title = anchor
            mm = re.match(r"gotit://nota/([0-9a-fA-F-]{36})", anchor)
            if mm:
                info = self.window.resolve_note(mm.group(1))
                title = info["title"] if info else "nota"
            m.addAction(icons.icon("link"), f"Abrir “{title}”").triggered.connect(lambda: self.open_link(anchor))
            m.addAction("Remover o link").triggered.connect(lambda: (textfmt.remove_link(item), self.content_changed()))
        m.addAction(icons.icon("link"), "Inserir link…").triggered.connect(self.insert_link)
        m.addAction(icons.icon("note"), "Ligar a outra nota…").triggered.connect(self.link_to_note)
        if c.currentTable() is not None:
            self._table_menu(m, item, None)
        elif item is self.scene.story:
            m.addAction(icons.icon("table"), "Inserir tabela…").triggered.connect(self.insert_table)
        m.addSeparator()
        sub = m.addMenu(icons.icon("highlight"), "Destacar")
        for title, value in theme.HIGHLIGHTS:
            sub.addAction(swatch_icon(value), title).triggered.connect(lambda _=False, v=value: self.fmt("highlight", v))
        sub.addAction(swatch_icon(None), "Tirar destaque").triggered.connect(lambda: self.fmt("highlight", None))
        if has_sel:
            m.addAction(icons.icon("sparkle"), "Perguntar ao assistente sobre o trecho").triggered.connect(
                lambda: self.window.ask_assistant_about(c.selectedText().replace(" ", "\n")))
        m.addAction("Selecionar tudo").triggered.connect(lambda: self._text_action(item, "all"))
        m.exec(screen_pos)

    def _text_action(self, item, action: str) -> None:
        c = item.textCursor()
        cb = QGuiApplication.clipboard()
        if action in ("cut", "copy") and c.hasSelection():
            frag = c.selection()
            md = QMimeData()
            md.setHtml(frag.toHtml())
            md.setText(frag.toPlainText())
            cb.setMimeData(md)
            if action == "cut":
                c.removeSelectedText()
        elif action == "paste":
            md = cb.mimeData()
            if md.hasHtml():
                c.insertHtml(md.html())
            elif md.hasText():
                c.insertText(md.text())
            elif md.hasImage():
                self.insert_qimage(md.imageData())
        elif action == "paste_plain":
            c.insertText(cb.text())
        elif action == "all":
            c.select(QTextCursor.SelectionType.Document)
        item.setTextCursor(c)
        self.history.break_group()

    def _table_menu(self, m: QMenu, text_item, block) -> None:
        sub = m.addMenu(icons.icon("table"), "Tabela")
        for title, act in (("Nova linha abaixo", "row_below"), ("Nova linha acima", "row_above"),
                           ("Nova coluna à direita", "col_right"), ("Nova coluna à esquerda", "col_left"), (None, None),
                           ("Duplicar a linha", "dup_row"), ("Apagar a linha", "del_row"), ("Apagar a coluna", "del_col"),
                           (None, None), ("Linha de cabeçalho", "header")):
            if title is None:
                sub.addSeparator()
                continue
            sub.addAction(title).triggered.connect(lambda _=False, a=act: self.table_action(text_item, a))
        colors = sub.addMenu("Cor da célula")
        for value in [None, "#EEF2F6", "#FFF27A", "#C6EBA1", "#A9DDF7", "#FFB8D2", "#FFC98A"]:
            colors.addAction(swatch_icon(value), "Sem cor" if value is None else value).triggered.connect(
                lambda _=False, v=value: self.table_action(text_item, "cell_color", v))
        border = sub.addMenu("Espessura da borda")
        for w in (0, 1, 2, 3):
            border.addAction(f"{w} pt").triggered.connect(lambda _=False, v=w: self.table_action(text_item, "border", v))

    def table_action(self, text_item, action: str, value=None) -> None:
        c = text_item.textCursor()
        table = c.currentTable()
        if table is None:
            if isinstance(getattr(text_item, "owner", None), items_mod.TableItem):
                table = text_item.owner.table()
                if table is None:
                    return
                c = table.cellAt(0, 0).firstCursorPosition()
            else:
                return
        cell = table.cellAt(c)
        row, col = (cell.row(), cell.column()) if cell.isValid() else (0, 0)
        c.beginEditBlock()
        if action == "row_below":
            table.insertRows(row + 1, 1)
        elif action == "row_above":
            table.insertRows(row, 1)
        elif action == "col_right":
            table.insertColumns(col + 1, 1)
        elif action == "col_left":
            table.insertColumns(col, 1)
        elif action == "dup_row":
            table.insertRows(row + 1, 1)
            for j in range(table.columns()):
                src = table.cellAt(row, j)
                cur = src.firstCursorPosition()
                cur.setPosition(src.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
                frag = cur.selection()
                table.cellAt(row + 1, j).firstCursorPosition().insertFragment(frag)
        elif action == "del_row" and table.rows() > 1:
            table.removeRows(row, 1)
        elif action == "del_col" and table.columns() > 1:
            table.removeColumns(col, 1)
        elif action == "header":
            first = table.cellAt(0, 0).format().background().color()
            on = first.alpha() == 0 or first.name().lower() != "#eef2f6"
            for j in range(table.columns()):
                cl = table.cellAt(0, j)
                f = cl.format()
                f.setBackground(QColor("#EEF2F6") if on else QColor(0, 0, 0, 0))
                f.setFontWeight(700 if on else 400)
                cl.setFormat(f)
        elif action == "cell_color":
            f = cell.format()
            f.setBackground(QColor(value) if value else QColor(0, 0, 0, 0))
            cell.setFormat(f)
        elif action == "border":
            fmt = table.format()
            fmt.setBorder(float(value))
            table.setFormat(fmt)
        c.endEditBlock()
        self.content_changed()

    # ================================================================== texto
    def set_active_text(self, item) -> None:
        self.active_text = item
        self.history.break_group()

    def text_focus_lost(self, item) -> None:
        def check():
            owner = getattr(item, "owner", None)
            if owner is None or not owner.scene():
                return
            fw = QApplication.focusWidget()
            if fw is not None and (self.bar.isAncestorOf(fw) or self.tools.isAncestorOf(fw)):
                return
            if self.scene is not None and self.scene.focusItem() is item:
                return
            if QApplication.activePopupWidget() is not None:
                return
            owner.stop_editing()
        QTimer.singleShot(0, check)

    def stop_all_editing(self) -> None:
        if self.scene is None:
            return
        for it in self.scene.items_by_id.values():
            if isinstance(it, items_mod.TextBlock) and it.editing:
                it.stop_editing()

    def story_pressed(self) -> None:
        if self.tool != "select":
            self.set_tool("select")
        self.stop_all_editing()

    def after_canvas_press(self, pos: QPointF) -> None:
        """Clique fora do texto e dos objetos: o cursor vai para o texto da nota."""
        sc = self.scene
        if sc is None or self.doc.get("kind") == "web":
            return
        if sc.focusItem() is None and not sc.selectedItems() and not sc.items(pos, Qt.ItemSelectionMode.IntersectsItemShape)[:1]:
            sc.setFocusItem(sc.story)

    def focus_text(self, item, cursor: QTextCursor) -> None:
        owner = getattr(item, "owner", None)
        if owner is not None:
            owner.start_editing()
        self.scene.setFocusItem(item)
        item.setTextCursor(cursor)
        self.ensure_cursor_visible(item)

    def ensure_cursor_visible(self, item) -> None:
        r = item.document().documentLayout().blockBoundingRect(item.textCursor().block())
        line_rect = item.mapRectToScene(r)
        self.view.ensureVisible(line_rect, 30, 80)

    def target_texts(self) -> list:
        if self.scene is None:
            return []
        focus = self.scene.focusItem()
        if isinstance(focus, EditableText):
            return [focus]
        blocks = [b.text for b in self.selected_blocks() if isinstance(b, items_mod.TextBlock)]
        if blocks:
            return blocks
        if self.active_text is not None and self.active_text.scene() is self.scene:
            return [self.active_text]
        return [self.scene.story]

    def fmt(self, action: str, value=None) -> None:
        targets = self.target_texts()
        if not targets:
            return
        self.history.break_group()
        for t in targets:
            if action == "bold":
                textfmt.toggle_bold(t)
            elif action == "italic":
                textfmt.toggle_italic(t)
            elif action == "underline":
                textfmt.toggle_underline(t)
            elif action == "strike":
                textfmt.toggle_strike(t)
            elif action == "family":
                textfmt.set_family(t, value)
            elif action == "size":
                textfmt.set_size(t, value)
            elif action == "grow":
                textfmt.grow(t, value)
            elif action == "color":
                textfmt.set_color(t, value)
            elif action == "highlight":
                textfmt.set_highlight(t, value)
            elif action == "align":
                textfmt.set_alignment(t, {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
                                          "right": Qt.AlignmentFlag.AlignRight, "justify": Qt.AlignmentFlag.AlignJustify}[value])
            elif action == "bullets":
                textfmt.toggle_list(t, QTextListFormat.Style.ListDisc)
            elif action == "numbers":
                textfmt.toggle_list(t, QTextListFormat.Style.ListDecimal)
            elif action == "nolist":
                textfmt.remove_list(t)
            elif action == "indent":
                textfmt.indent(t, value)
            elif action == "spacing":
                textfmt.set_line_spacing(t, value)
            elif action == "named":
                textfmt.apply_named_style(t, value, self.scene.default_size)
        self.history.break_group()
        self.content_changed()
        self._refocus(targets[0])

    def _refocus(self, item) -> None:
        if self.scene is None:
            return
        owner = getattr(item, "owner", None)
        if owner is None or owner.editing:
            self.view.setFocus()
            self.scene.setFocusItem(item)

    def _size_from_combo(self) -> None:
        try:
            size = float(self.bar.size_combo.currentText().replace(",", "."))
        except ValueError:
            return
        if 4 <= size <= 400:
            self.fmt("size", size)

    def update_named_style(self) -> None:
        self.toast("O estilo do parágrafo foi atualizado pela seleção.")

    def _refresh_state(self) -> None:
        if self.scene is None or not self.isVisible():
            return
        targets = self.target_texts()
        state = None
        if targets:
            t = targets[0]
            try:
                fmt = textfmt.current(t)
            except RuntimeError:
                return
            fam = fmt.fontFamilies() if hasattr(fmt, "fontFamilies") else None
            family = (fam[0] if isinstance(fam, list) and fam else None) or t.document().defaultFont().family()
            size = fmt.fontPointSize() or t.document().defaultFont().pointSizeF()
            align = t.textCursor().blockFormat().alignment()
            state = {"bold": fmt.fontWeight() >= 600, "italic": fmt.fontItalic(), "underline": fmt.fontUnderline(),
                     "strike": fmt.fontStrikeOut(), "family": family, "size": round(size, 1),
                     "align": "center" if align & Qt.AlignmentFlag.AlignHCenter else "right" if align & Qt.AlignmentFlag.AlignRight
                     else "justify" if align & Qt.AlignmentFlag.AlignJustify else "left",
                     "list": textfmt.list_style(t) is not None, "named": textfmt.named_style(t)}
        if state != self._last_state:
            self._last_state = state
            self.bar.show_state(state)

    def handle_text_key(self, item, event) -> bool:
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key.Key_Escape:
            if getattr(item, "owner", None) is not None:
                owner = item.owner
                owner.stop_editing()
                self.scene.setFocusItem(None)
                owner.setSelected(True)
                return True
            return False
        c = item.textCursor()
        if key == Qt.Key.Key_Tab and c.currentList() is not None:
            textfmt.indent(item, 1)
            return True
        if key == Qt.Key.Key_Backtab and c.currentList() is not None:
            textfmt.indent(item, -1)
            return True
        if key == Qt.Key.Key_Tab and c.currentTable() is not None:
            table = c.currentTable()
            cell = table.cellAt(c)
            r, col = cell.row(), cell.column() + 1
            if col >= table.columns():
                r, col = r + 1, 0
            if r >= table.rows():
                table.appendRows(1)
            item.setTextCursor(table.cellAt(r, col).firstCursorPosition())
            return True
        if event.matches(QKeySequence.StandardKey.Paste):
            md = QGuiApplication.clipboard().mimeData()
            if md.hasFormat(OBJ_MIME) or (md.hasImage() and not md.hasText()):
                self.paste_objects()
                return True
            self.history.break_group()
            return False
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and c.currentList() is not None and not c.block().text():
            textfmt.remove_list(item)
            return True
        return False

    def handle_view_key(self, event) -> bool:
        sc = self.scene
        if sc is None:
            return False
        focus = sc.focusItem()
        if isinstance(focus, EditableText):
            return False
        key = event.key()
        selected = self.selected_blocks() + self.selected_strokes()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and (selected or sc.selectedItems()):
            self.delete_selection()
            return True
        if key == Qt.Key.Key_Escape:
            if self.tool != "select":
                self.set_tool("select")
            else:
                sc.clearSelection()
            return True
        if event.matches(QKeySequence.StandardKey.Copy) and selected:
            return self.copy_selection()
        if event.matches(QKeySequence.StandardKey.Cut) and selected:
            return self.copy_selection(cut=True)
        if event.matches(QKeySequence.StandardKey.Paste):
            return self.paste_objects()
        if event.matches(QKeySequence.StandardKey.SelectAll):
            for it in list(sc.items_by_id.values()):
                it.setSelected(True)
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) and selected:
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            d = {Qt.Key.Key_Left: QPointF(-step, 0), Qt.Key.Key_Right: QPointF(step, 0),
                 Qt.Key.Key_Up: QPointF(0, -step), Qt.Key.Key_Down: QPointF(0, step)}[key]
            with sc.change("Mover"):
                for it in selected:
                    it.setPos(it.pos() + d)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2) and len(self.selected_blocks()) == 1:
            self.selected_blocks()[0].activate()
            return True
        return False

    def undo(self) -> None:
        self.history.undo()

    def redo(self) -> None:
        self.history.redo()

    # ------------------------------------------------------------------ links
    def open_link(self, href: str) -> None:
        mm = re.match(r"gotit://nota/([0-9a-fA-F-]{36})", href)
        if mm:
            self.open_note(mm.group(1))
            return
        if textfmt.is_allowed_link(href):
            QDesktopServices.openUrl(QUrl(href))

    def insert_link(self) -> None:
        targets = self.target_texts()
        if not targets:
            return
        t = targets[0]
        dlg = dialogs.LinkDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url, text = dlg.value()
        if not url:
            return
        if not textfmt.insert_link(t, url, text or None):
            QMessageBox.information(self, "Link", "Só endereços da web (http, https) e de e-mail (mailto) viram link.")
            return
        self.content_changed()

    def link_to_note(self) -> None:
        targets = self.target_texts()
        if not targets or self.doc is None:
            return
        t = targets[0]
        notes = [n for n in self.store.notes() if n.id != self.doc["id"]]
        if not notes:
            self.toast("Ainda não há outras notas para ligar.")
            return
        dlg = dialogs.NotePicker(notes, "Ligar a outra nota", previews=self.window.thumbs.small, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.chosen():
            return
        target = dlg.chosen()[0]
        info = self.store.info(target)
        textfmt.insert_link(t, f"gotit://nota/{target}", info.title if info else "nota")
        self.content_changed()

    def find_replace(self) -> None:
        if self._find_dialog is None:
            self._find_dialog = dialogs.FindReplaceDialog(self)
            self._find_dialog.find_next.connect(self._find_next)
            self._find_dialog.replace_one.connect(self._replace_one)
            self._find_dialog.replace_all.connect(self._replace_all)
        t = self.target_texts()
        if t and t[0].textCursor().hasSelection():
            self._find_dialog.needle.setText(t[0].textCursor().selectedText())
        self._find_dialog.show()
        self._find_dialog.raise_()
        self._find_dialog.needle.setFocus()
        self._find_dialog.needle.selectAll()

    def _all_texts(self) -> list:
        sc = self.scene
        out = [sc.story]
        for it in sorted(sc.items_by_id.values(), key=lambda i: (i.pos().y(), i.pos().x())):
            if isinstance(it, items_mod.TextBlock):
                out.append(it.text)
        return out

    def _find_next(self, needle: str, case: bool, whole: bool, back: bool) -> None:
        if not needle or self.scene is None:
            return
        texts = self._all_texts()
        hits = []
        for t in texts:
            for c in textfmt.find_all(t.document(), needle, case, whole):
                hits.append((t, c))
        self._find_dialog.info.setText(f"{len(hits)} ocorrência(s)" if hits else "Nada encontrado.")
        if not hits:
            return
        cur_item = self.scene.focusItem()
        cur_pos = cur_item.textCursor().selectionEnd() if isinstance(cur_item, EditableText) else -1
        order = [(texts.index(t), c.selectionStart()) for t, c in hits]
        here = (texts.index(cur_item), cur_pos) if cur_item in texts else (-1, -1)
        if back:
            here = (here[0], cur_item.textCursor().selectionStart() if cur_item in texts else 10 ** 9)
            cands = [i for i, o in enumerate(order) if o < here]
            idx = cands[-1] if cands else len(hits) - 1
        else:
            cands = [i for i, o in enumerate(order) if o >= here]
            idx = cands[0] if cands else 0
        t, c = hits[idx]
        self.focus_text(t, c)

    def _replace_one(self, needle, repl, case, whole) -> None:
        focus = self.scene.focusItem() if self.scene else None
        if isinstance(focus, EditableText):
            c = focus.textCursor()
            sel = c.selectedText()
            if sel and (sel == needle or (not case and sel.lower() == needle.lower())):
                c.insertText(repl)
        self._find_next(needle, case, whole, False)

    def _replace_all(self, needle, repl, case, whole) -> None:
        total = 0
        for t in self._all_texts():
            hits = textfmt.find_all(t.document(), needle, case, whole)
            if not hits:
                continue
            first = t.textCursor()
            first.beginEditBlock()
            for c in reversed(hits):
                c.insertText(repl)
            first.endEditBlock()
            total += len(hits)
        self._find_dialog.info.setText(f"{total} substituição(ões).")
        self.content_changed()

    def find_text(self, query: str, part: str | None = None) -> bool:
        """Abre a nota no trecho achado pela busca, com a palavra selecionada."""
        words = [w for w in re.findall(r"\w+", query, flags=re.UNICODE)]
        if not words:
            return False
        texts = self._all_texts()
        if part and part != "story" and part in self.scene.items_by_id:
            it = self.scene.items_by_id[part]
            if isinstance(it, items_mod.TextBlock):
                texts = [it.text] + [t for t in texts if t is not it.text]
            else:
                self.scene.clearSelection()
                it.setSelected(True)
                self.view.ensureVisible(it, 40, 80)
                return True
        import unicodedata

        def fold(s):
            return "".join(ch for ch in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(ch) != "Mn")
        w = fold(words[0])
        for t in texts:
            plain = t.document().toPlainText()
            folded = fold(plain)
            m = re.search(r"\b" + re.escape(w), folded)
            if m:
                # índices iguais: o texto sem acentos tem o mesmo número de caracteres
                c = QTextCursor(t.document())
                start = len(fold(plain[:0])) + m.start()
                c.setPosition(start)
                end = start
                while end < len(plain) and (plain[end].isalnum() or plain[end] == "_"):
                    end += 1
                c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                self.focus_text(t, c)
                return True
        return False

    # ================================================================== páginas
    def add_page(self, after: int | None = None) -> None:
        if self.scene is None:
            return
        with self.scene.change("Nova página"):
            idx = self.scene.add_page(after)
        self.scroll_to_page(idx)
        self.thumb_timer.start()

    def delete_page(self, index: int) -> None:
        if self.scene is None or self.scene.page_count() <= 1:
            return
        if QMessageBox.question(self, "Apagar página", f"Apagar a página {index + 1} com os objetos e desenhos dela? "
                                "O texto da nota continua (ele passa de uma página para a outra).") != QMessageBox.StandardButton.Yes:
            return
        with self.scene.change("Apagar página"):
            self.scene.delete_page(index)
        self.thumb_timer.start()

    def page_setup(self) -> None:
        dlg = dialogs.PageSetupDialog(self.doc["canvas"], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            with self.scene.change("Tamanho da página"):
                self.doc["canvas"] = dlg.result_canvas(self.doc["canvas"])
                self.scene.apply_page_format()
                self.scene.relayout_objects()
            self.view.fit_width()

    def _pick_band_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Imagem ou PDF do cabeçalho", self._last_dir(),
                                              "Imagens ou PDF (*.png *.jpg *.jpeg *.heic *.webp *.bmp *.pdf)")
        if not path:
            return None
        p = Path(path)
        if p.suffix.lower() == ".pdf":
            return "pdf", self.store.import_asset(p)
        return "image", self._import_image(p)

    def header_footer(self, tab: int = 0) -> None:
        dlg = dialogs.HeaderFooterDialog(self.doc["canvas"], self._pick_band_image, tab, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            with self.scene.change("Cabeçalho e rodapé"):
                self.doc["canvas"] = dlg.result_canvas(self.doc["canvas"])
                self.scene.apply_page_format()

    def paper(self, page: int | None = None) -> None:
        idx = self.view.current_page() if page is None else page
        current = (self.doc["pages"][idx].get("paper") if idx < len(self.doc["pages"]) else None) or self.doc["canvas"].get("paper")
        dlg = dialogs.PaperDialog(current, self)
        if page is not None:
            dlg.scope.setCurrentIndex(1)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        paper, scope = dlg.value()
        with self.scene.change("Papel"):
            if scope == "note":
                self.doc["canvas"]["paper"] = paper
                for p in self.doc["pages"]:
                    p.pop("paper", None)
            else:
                pg = self.doc["pages"][idx]
                if paper is None:
                    pg["paper"] = {"kind": "plain"} if self.doc["canvas"].get("paper") else None
                    if pg["paper"] is None:
                        pg.pop("paper")
                else:
                    pg["paper"] = paper
            self.scene.apply_page_format()

    # ================================================================== nota
    def build_note_menu(self, parent) -> QMenu:
        m = QMenu(parent)
        m.aboutToShow.connect(lambda: self._fill_note_menu(m))
        return m

    def _fill_note_menu(self, m: QMenu) -> None:
        m.clear()
        if self.doc is None:
            return
        web = self.doc.get("kind") == "web"
        if web:
            m.addAction(icons.icon("plus"), "Adicionar notas à Teia…").triggered.connect(self.add_notes_to_teia)
            a = m.addAction("Mostrar a cronologia (setas pela data de criação)")
            a.setCheckable(True)
            a.setChecked(self.show_chronology)
            a.triggered.connect(self._toggle_chrono)
            m.addSeparator()
        m.addAction(icons.icon("export"), "Exportar como PDF… (Ctrl+Shift+E)").triggered.connect(self.export_pdf)
        m.addAction(icons.icon("print"), "Imprimir… (Ctrl+P)").triggered.connect(self.print_note)
        m.addSeparator()
        m.addAction(icons.icon("link"), "Citada em…").triggered.connect(self.cited_by)
        if not web:
            m.addAction(icons.icon("teia"), "Criar Teia com esta nota").triggered.connect(lambda: self.teiaRequested.emit([self.doc["id"]]))
        move = m.addMenu(icons.icon("folder"), "Mover para")
        self.window.fill_move_menu(move, [self.doc["id"]])
        m.addAction(icons.icon("copy"), "Duplicar a nota").triggered.connect(self.duplicate_note)
        m.addSeparator()
        m.addAction(icons.icon("page-size"), "Tamanho da página e margens…").triggered.connect(self.page_setup)
        m.addSeparator()
        m.addAction(icons.icon("trash", theme.DANGER), "Apagar (vai para a Lixeira)").triggered.connect(self.trash_note)

    def _toggle_chrono(self, on: bool) -> None:
        self.show_chronology = on
        if self.scene:
            self.scene.update()

    def add_notes_to_teia(self) -> None:
        present = {it.data_state.get("documentID") for it in self.scene.items_by_id.values() if isinstance(it, items_mod.NoteRefItem)}
        notes = [n for n in self.store.notes(kind="note") if n.id not in present]
        if not notes:
            self.toast("Todas as notas já estão nesta Teia.")
            return
        dlg = dialogs.NotePicker(notes, "Adicionar notas à Teia", multi=True, previews=self.window.thumbs.small, parent=self,
                                 ok_text="Adicionar")
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen():
            self.add_note_cards(dlg.chosen())

    def add_note_cards(self, ids: list[str]) -> None:
        sc = self.scene
        w, h = 190.0, 240.0
        with sc.change("Adicionar notas"):
            for doc_id in ids:
                page_id, x, y, _ = self._place(w, h, page=0)
                state = {"id": model.new_id(), "kind": "noteRef", "documentID": doc_id, "pageID": page_id,
                         "frame": {"x": x, "y": y, "width": w, "height": h}, "z": sc.next_z()}
                sc.add_block(state)
        sc.update()

    def cited_by(self) -> None:
        self.save_now()
        notes = self.store.cited_by(self.doc["id"])
        if not notes:
            QMessageBox.information(self, "Citada em", "Nenhuma nota ou Teia aponta para esta nota.")
            return
        dlg = dialogs.NotePicker(notes, "Citada em", previews=self.window.thumbs.small, parent=self, ok_text="Abrir")
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen():
            self.open_note(dlg.chosen()[0])

    def duplicate_note(self) -> None:
        self.save_now()
        doc = copy.deepcopy(self.scene.serialize())
        new_id = model.new_id()
        old_first = doc["pages"][0]["id"]
        doc["id"] = new_id
        doc["pages"][0]["id"] = new_id
        for b in doc["blocks"]:
            if b.get("pageID") in (None, old_first):
                b["pageID"] = new_id
        for s in doc["strokes"]:
            if s.get("pageID") in (None, old_first):
                s["pageID"] = new_id
        doc["title"] = f"{doc['title']} (cópia)"
        doc["createdAt"] = doc["updatedAt"] = model.now_iso()
        doc["revision"] = 0
        info = self.store.info(self.doc["id"])
        self.store.create(doc, folder_id=info.folder_id if info else None)
        self.window.refresh()
        self.openRequested.emit(new_id)

    def trash_note(self) -> None:
        doc_id = self.doc["id"]
        self.save_now()
        self.close_document()
        self.store.trash(doc_id)
        self.trashed.emit(doc_id)

    # ------------------------------------------------------------------ exportar
    def _paint_pages(self, painter: QPainter, page_rect_px: QRectF, new_page) -> None:
        sc = self.scene
        selected = sc.selectedItems()
        for it in selected:
            it.setSelected(False)
        focus = sc.focusItem()
        sc.setFocusItem(None)
        sc.exporting = True
        try:
            for i in range(sc.page_count()):
                if i:
                    new_page()
                sc.render(painter, page_rect_px, sc.page_rect(i))
        finally:
            sc.exporting = False
            for it in selected:
                it.setSelected(True)
            if focus is not None:
                sc.setFocusItem(focus)

    def export_pdf(self) -> None:
        if self.scene is None:
            return
        name = re.sub(r'[\\/:*?"<>|]', "-", self.doc.get("title") or "Nota") + ".pdf"
        dest, _ = QFileDialog.getSaveFileName(self, "Exportar como PDF", str(Path(self._last_dir()) / name), "PDF (*.pdf)")
        if not dest:
            return
        self.export_pdf_to(dest)
        self.toast("PDF exportado.")

    def export_pdf_to(self, dest: str) -> None:
        sc = self.scene
        writer = QPdfWriter(dest)
        writer.setResolution(300)
        writer.setTitle(self.doc.get("title") or "Nota")
        writer.setCreator("Got It! para Windows")
        size = QPageSize(QSizeF(sc.page_w, sc.page_h), QPageSize.Unit.Point, "", QPageSize.SizeMatchPolicy.ExactMatch)
        writer.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
        painter = QPainter(writer)
        rect = QRectF(0, 0, writer.width(), writer.height())
        self._paint_pages(painter, rect, writer.newPage)
        painter.end()

    def print_note(self) -> None:
        if self.scene is None:
            return
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except ImportError:
            self.toast("A impressão não está disponível neste computador.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.doc.get("title") or "Nota")
        sc = self.scene
        printer.setPageSize(QPageSize(QSizeF(sc.page_w, sc.page_h), QPageSize.Unit.Point))
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        painter = QPainter(printer)
        rect = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
        rect.moveTo(0, 0)
        self._paint_pages(painter, rect, printer.newPage)
        painter.end()

    # ------------------------------------------------------------------ assistente
    def insert_plain_text(self, text: str, title: str | None = None) -> None:
        """Insere texto (resposta do assistente, transcrição) no fim do texto da nota."""
        story = self.scene.story
        c = QTextCursor(story.document())
        c.movePosition(QTextCursor.MoveOperation.End)
        c.beginEditBlock()
        if story.document().toPlainText().strip():
            c.insertBlock()
        if title:
            bold = QTextCharFormat()
            bold.setFontWeight(QFont.Weight.Bold)
            c.insertText(title, bold)
            c.insertBlock()
            c.setCharFormat(QTextCharFormat())
        c.insertText(text)
        c.endEditBlock()
        self.focus_text(story, c)
        self.content_changed()

    def insert_transcript(self, audio_item, text: str) -> None:
        """Transcrição num bloco próprio ao lado do áudio: direita, esquerda, abaixo ou acima."""
        sc = self.scene
        w, h = 300.0, 180.0
        a = QRectF(audio_item.pos(), QSizeF(audio_item.w, audio_item.h))
        page = sc.page_at_y(a.center().y())
        top = page * sc.page_h
        candidates = [QPointF(a.right() + 12, a.top()), QPointF(a.left() - 12 - w, a.top()),
                      QPointF(a.left(), a.bottom() + 12), QPointF(a.left(), a.top() - 12 - h)]
        occupied = [QRectF(x, y + top, ww, hh) for x, y, ww, hh in self._occupied(page)]
        spot = None
        for p in candidates:
            r = QRectF(p, QSizeF(w, h))
            if r.left() >= 0 and r.right() <= sc.page_w and r.top() >= top and r.bottom() <= top + sc.page_h \
                    and not any(r.intersects(o) for o in occupied if o != a):
                spot = p
                break
        spot = spot or candidates[2]
        state = {"id": model.new_id(), "kind": "transcript", "pageID": sc.page_id_at(page),
                 "frame": {"x": spot.x(), "y": spot.y() - top, "width": w, "height": h}, "z": sc.next_z(),
                 "text": text, "html": "", "fontSize": 11.0, "foreground": "#1F2933"}
        with sc.change("Transcrição"):
            item = sc.add_block(state)
        need = item.text.document().size().height() + item.header + 14
        if need > h:
            item.resize_to(w, min(need, 600))
        self.content_changed()
