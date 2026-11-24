"""Objetos da página: caixa de texto, formas (com texto dentro), linhas e setas, post-it,
calendário, stickers, imagens, PDF, áudio, vídeo, tabela, transcrição e cartão de nota da Teia.

Cada objeto guarda o próprio estado no formato do JSON da nota (``state()``) e sabe se
atualizar no lugar (``set_state``), o que permite desfazer e refazer sem recriar a página."""

from __future__ import annotations

import copy
import math
from datetime import date

from PySide6.QtCore import QLineF, QPointF, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF, QTextCursor, QTextOption, QTextTableFormat,
                           QTextLength, QTextFrameFormat, QTextCharFormat)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsPathItem

import icons
import model
import theme
from textitem import EditableText

HANDLE = 6.0          # meia largura da alça, em pixels da tela
ROT_GAP = 22.0        # distância do botão de girar acima do objeto
ACCENT = QColor(theme.ACCENT)
MONTHS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def qcolor(value, default="#000000") -> QColor:
    c = QColor(value or default)
    if isinstance(value, str) and len(value) == 9 and value.startswith("#"):   # #RRGGBBAA do iPhone
        c = QColor(value[:7])
        c.setAlpha(int(value[7:9], 16))
    return c


def hex_color(c: QColor) -> str:
    return c.name() if c.alpha() == 255 else c.name() + f"{c.alpha():02x}"


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds + 0.5))
    return f"{seconds // 60}:{seconds % 60:02d}"


class BlockItem(QGraphicsObject):
    kind = "block"
    resizable = True
    rotatable = True
    keep_aspect = False
    min_w, min_h = 24.0, 18.0
    text_capable = False
    _moving = False

    def __init__(self, scene, state: dict):
        super().__init__()
        self.canvas = scene
        self.block_id = state["id"]
        self.data_state = copy.deepcopy(state)
        frame = state.get("frame") or {}
        self.w = float(frame.get("width") or 160)
        self.h = float(frame.get("height") or 80)
        self._drag = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setTransformOriginPoint(self.w / 2, self.h / 2)
        self._place(state)

    # ------------------------------------------------------------------ estado
    def _place(self, state: dict) -> None:
        frame = state.get("frame") or {}
        idx = self.canvas.page_index_of(state.get("pageID"))
        self.prepareGeometryChange()
        self.w = max(self.min_w, float(frame.get("width") or self.w))
        self.h = max(self.min_h if not self.kind == "line" else 0, float(frame.get("height") or self.h))
        self.setTransformOriginPoint(self.w / 2, self.h / 2)
        self.setRotation(float(state.get("rotation") or 0))
        self.setPos(float(frame.get("x") or 0), idx * self.canvas.page_h + float(frame.get("y") or 0))
        self.setZValue(10 + float(state.get("z") or 0))

    def state(self) -> dict:
        s = copy.deepcopy(self.data_state)
        center = self.mapToScene(QPointF(self.w / 2, self.h / 2))
        idx = self.canvas.page_at_y(center.y())
        s["pageID"] = self.canvas.page_id_at(idx)
        s["frame"] = {"x": round(self.pos().x(), 2), "y": round(self.pos().y() - idx * self.canvas.page_h, 2),
                      "width": round(self.w, 2), "height": round(self.h, 2)}
        s["rotation"] = round(self.rotation(), 2)
        s["z"] = int(round(self.zValue() - 10))
        self.write_state(s)
        return s

    def write_state(self, s: dict) -> None:
        """Subclasses acrescentam o próprio conteúdo (texto, cores...)."""

    def set_state(self, state: dict) -> None:
        self.data_state = copy.deepcopy(state)
        self._place(state)
        self.read_state(state)
        self.update()

    def read_state(self, state: dict) -> None:
        pass

    def resize_to(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self.w, self.h = max(self.min_w, w), max(self.min_h, h)
        self.setTransformOriginPoint(self.w / 2, self.h / 2)
        self.on_resized()
        self.update()

    def on_resized(self) -> None:
        pass

    # ------------------------------------------------------------------ desenho
    def rect(self) -> QRectF:
        return QRectF(0, 0, self.w, self.h)

    def _ui_scale(self) -> float:
        views = self.scene().views() if self.scene() else []
        z = views[0].transform().m11() if views else 1.0
        return 1.0 / max(0.05, z)

    def boundingRect(self) -> QRectF:
        m = (HANDLE + 2) * 4 + ROT_GAP * 3
        return QRectF(-m, -m, self.w + 2 * m, self.h + 2 * m)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.content_shape_rect())
        if self.isSelected():
            s = self._ui_scale()
            for p in self.handle_points():
                path.addEllipse(p, (HANDLE + 3) * s, (HANDLE + 3) * s)
        return path

    def content_shape_rect(self) -> QRectF:
        return self.rect()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.save()
        self.paint_content(painter)
        painter.restore()
        if self.isSelected() and not getattr(self.canvas, "exporting", False):
            self.paint_selection(painter)

    def paint_content(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#94A3B8"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(self.rect())

    def paint_selection(self, painter: QPainter) -> None:
        s = self._ui_scale()
        painter.setPen(QPen(ACCENT, 1.4 * s))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())
        if not self.resizable:
            return
        painter.setBrush(QColor("white"))
        painter.setPen(QPen(ACCENT, 1.4 * s))
        for p in self.handle_points():
            painter.drawEllipse(p, HANDLE * s, HANDLE * s)
        if self.rotatable:
            top = QPointF(self.w / 2, 0)
            knob = QPointF(self.w / 2, -ROT_GAP * s)
            painter.drawLine(top, knob)
            painter.setBrush(ACCENT)
            painter.drawEllipse(knob, HANDLE * s, HANDLE * s)

    def handle_points(self) -> list[QPointF]:
        if not self.resizable:
            return []
        w, h = self.w, self.h
        pts = [QPointF(0, 0), QPointF(w, 0), QPointF(w, h), QPointF(0, h)]
        if not self.keep_aspect:
            pts += [QPointF(w / 2, 0), QPointF(w, h / 2), QPointF(w / 2, h), QPointF(0, h / 2)]
        return pts

    def _hit_handle(self, pos: QPointF):
        if not self.isSelected():
            return None
        s = self._ui_scale()
        r = (HANDLE + 3) * s
        if self.rotatable and self.resizable and QLineF(pos, QPointF(self.w / 2, -ROT_GAP * s)).length() <= r:
            return "rotate"
        for i, p in enumerate(self.handle_points()):
            if QLineF(pos, p).length() <= r:
                return i
        return None

    # ------------------------------------------------------------------ mouse
    def hoverMoveEvent(self, event) -> None:
        h = self._hit_handle(event.pos())
        if h == "rotate":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif h is not None:
            cursors = [Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeFDiagCursor,
                       Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeVerCursor, Qt.CursorShape.SizeHorCursor,
                       Qt.CursorShape.SizeVerCursor, Qt.CursorShape.SizeHorCursor]
            self.setCursor(cursors[h])
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor if self.isSelected() else Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._hit_handle(event.pos())
            self.canvas.begin_change()
            if handle is not None:
                self._drag = {"handle": handle, "rect": QRectF(self.rect()), "anchor": self.mapToScene(QPointF(0, 0)),
                              "start": event.scenePos(), "rotation": self.rotation()}
                event.accept()
                return
            self.canvas.raise_on_drag(self)
            self._moving = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag:
            handle = self._drag["handle"]
            if handle == "rotate":
                c = self.mapToScene(QPointF(self.w / 2, self.h / 2))
                v = event.scenePos() - c
                angle = math.degrees(math.atan2(v.y(), v.x())) + 90
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier or abs(angle % 90) < 4 or abs(angle % 90) > 86:
                    step = 15 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 90
                    if step == 15 or abs(angle % 90) < 4 or abs(angle % 90) > 86:
                        angle = round(angle / step) * step
                self.setRotation(angle % 360)
                self.canvas.item_moved(self)
                return
            self._resize_drag(handle, event)
            return
        super().mouseMoveEvent(event)

    def _resize_drag(self, handle: int, event) -> None:
        r0: QRectF = self._drag["rect"]
        # posição do mouse nas coordenadas do objeto como era no começo do gesto
        p = self.mapFromScene(event.scenePos())
        left, top, right, bottom = r0.left(), r0.top(), r0.right(), r0.bottom()
        hx = {0: "l", 1: "r", 2: "r", 3: "l", 4: None, 5: "r", 6: None, 7: "l"}[handle]
        vy = {0: "t", 1: "t", 2: "b", 3: "b", 4: "t", 5: None, 6: "b", 7: None}[handle]
        if hx == "l":
            left = min(p.x(), right - self.min_w)
        elif hx == "r":
            right = max(p.x(), left + self.min_w)
        if vy == "t":
            top = min(p.y(), bottom - self.min_h)
        elif vy == "b":
            bottom = max(p.y(), top + self.min_h)
        new = QRectF(QPointF(left, top), QPointF(right, bottom))
        if (self.keep_aspect or event.modifiers() & Qt.KeyboardModifier.ShiftModifier) and hx and vy and r0.height() > 0:
            ratio = r0.width() / r0.height()
            if new.width() / max(1e-6, new.height()) > ratio:
                new.setWidth(new.height() * ratio) if hx == "r" else new.setLeft(new.right() - new.height() * ratio)
            else:
                new.setHeight(new.width() / ratio) if vy == "b" else new.setTop(new.bottom() - new.width() / ratio)
        target = self.mapToScene(new.topLeft())
        self.resize_to(new.width(), new.height())
        offset = self.mapToScene(QPointF(0, 0)) - self.pos()
        self.setPos(target - offset)
        self._drag["rect"] = QRectF(0, 0, self.w, self.h)
        self.canvas.item_moved(self)

    def mouseReleaseEvent(self, event) -> None:
        was = self._drag
        self._drag = None
        self._moving = False
        super().mouseReleaseEvent(event)
        self.canvas.clear_guides()
        self.canvas.end_change("Girar" if was and was["handle"] == "rotate" else "Redimensionar" if was else "Mover")

    def mouseDoubleClickEvent(self, event) -> None:
        self.activate(event.pos())

    def activate(self, pos: QPointF | None = None) -> None:
        """Duplo clique: editar o texto, abrir o vídeo, escolher a data..."""

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self._drag is None and self.scene():
            # alinhamento só enquanto o mouse arrasta (desfazer e as setas do teclado não grudam)
            if self._moving and self.canvas.snapping and self.isSelected() and len(self.scene().selectedItems()) == 1:
                return self.canvas.snap(self, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.canvas.item_moved(self)
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.on_selected(bool(value))
        return super().itemChange(change, value)

    def on_selected(self, selected: bool) -> None:
        pass

    def contextMenuEvent(self, event) -> None:
        ed = self.canvas.editor
        if ed is None:
            return
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)
        ed.object_menu(self, event.screenPos())
        event.accept()

    def menu_actions(self, menu, editor) -> None:
        """Ações próprias do objeto no menu do botão direito."""

    def search_text(self) -> str:
        return ""


# ====================================================================== texto
class TextBlock(BlockItem):
    """Objeto com texto editável dentro (caixa de texto, post-it, forma, tabela, transcrição)."""
    text_capable = True
    padding = 8.0
    auto_height = False
    default_font_size = 18.0
    text = None

    def __init__(self, scene, state):
        super().__init__(scene, state)
        self.text = EditableText(self, owner=self)
        self.text.set_editing(False)
        self.text.document().setDocumentMargin(2)
        self._setup_text(state)
        self.text.document().contentsChanged.connect(self._contents_changed)
        self.on_resized()

    def _setup_text(self, state: dict) -> None:
        f = QFont(state.get("fontName") or self.default_family())
        f.setPointSizeF(float(state.get("fontSize") or self.default_font_size))
        self.text.document().setDefaultFont(f)
        self.text.setDefaultTextColor(qcolor(state.get("foreground"), "#1F2933"))
        html = state.get("html")
        if html:
            self.text.document().setHtml(html)
        else:
            self.text.document().setPlainText(state.get("text") or "")
        align = state.get("alignment")
        if align:
            opt = self.text.document().defaultTextOption()
            opt.setAlignment({"center": Qt.AlignmentFlag.AlignHCenter, "trailing": Qt.AlignmentFlag.AlignRight,
                              "justified": Qt.AlignmentFlag.AlignJustify}.get(align, Qt.AlignmentFlag.AlignLeft))
            self.text.document().setDefaultTextOption(opt)
        self.text.document().clearUndoRedoStacks()

    def default_family(self) -> str:
        return self.canvas.default_family

    def text_rect(self) -> QRectF:
        p = self.padding
        return QRectF(p, p, max(10, self.w - 2 * p), max(10, self.h - 2 * p))

    def on_resized(self) -> None:
        if self.text is None:
            return
        r = self.text_rect()
        self.text.setTextWidth(r.width())
        self.text.setPos(r.topLeft() + QPointF(0, self.vertical_offset(r)))

    def vertical_offset(self, r: QRectF) -> float:
        return 0.0

    def _contents_changed(self) -> None:
        if self.auto_height:
            need = self.text.document().size().height() + 2 * self.padding
            if abs(need - self.h) > 0.5 and need > self.min_h:
                self.prepareGeometryChange()
                self.h = max(self.min_h, need)
                self.setTransformOriginPoint(self.w / 2, self.h / 2)
                self.canvas.item_moved(self)
        self.on_resized()
        self.update()
        if self.canvas.editor is not None:
            self.canvas.editor.content_changed()

    def write_state(self, s: dict) -> None:
        doc = self.text.document()
        plain = doc.toPlainText()
        s["text"] = plain
        s["html"] = doc.toHtml() if plain.strip() or self._has_objects(doc) else ""

    @staticmethod
    def _has_objects(doc) -> bool:
        return len(doc.rootFrame().childFrames()) > 0

    def read_state(self, state: dict) -> None:
        want_html = state.get("html") or ""
        doc = self.text.document()
        cur_plain = doc.toPlainText()
        cur_html = doc.toHtml() if (cur_plain.strip() or self._has_objects(doc)) else ""
        if want_html != cur_html or (not want_html and (state.get("text") or "") != cur_plain):
            self._setup_text(state)
        self.text.setDefaultTextColor(qcolor(state.get("foreground"), "#1F2933"))
        self.on_resized()

    def start_editing(self, pos: QPointF | None = None) -> None:
        self.text.set_editing(True)
        self.text.setFocus(Qt.FocusReason.MouseFocusReason)
        c = self.text.textCursor()
        if pos is not None:
            local = self.text.mapFromParent(pos)
            hit = self.text.document().documentLayout().hitTest(local, Qt.HitTestAccuracy.FuzzyHit)
            if hit >= 0:
                c.setPosition(hit)
            else:
                c.movePosition(QTextCursor.MoveOperation.End)
        else:
            c.movePosition(QTextCursor.MoveOperation.End)
        self.text.setTextCursor(c)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)

    def stop_editing(self) -> None:
        self.text.set_editing(False)
        c = self.text.textCursor()
        c.clearSelection()
        self.text.setTextCursor(c)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        if self.data_state.get("autoBox"):
            ed = getattr(self.canvas, "editor", None)
            if ed is not None:
                QTimer.singleShot(0, lambda bid=self.block_id: ed.drop_empty_box(bid))

    @property
    def editing(self) -> bool:
        return bool(self.text.textInteractionFlags() & Qt.TextInteractionFlag.TextEditable)

    def activate(self, pos=None) -> None:
        self.start_editing(pos)

    def search_text(self) -> str:
        return self.text.document().toPlainText()


class TextBoxItem(TextBlock):
    kind = "text"
    auto_height = True
    min_h = 30.0
    rotatable = True

    def paint_content(self, painter: QPainter) -> None:
        fill = self.data_state.get("fill")
        border = self.data_state.get("stroke")
        if fill:
            painter.setBrush(qcolor(fill))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        if border:
            painter.setPen(QPen(qcolor(border), float(self.data_state.get("lineWidth") or 1)))
        elif not fill and (self.isSelected() or self.editing or not self.text.document().toPlainText()) \
                and not getattr(self.canvas, "exporting", False):
            painter.setPen(QPen(QColor("#B8C2CC"), 1 * self._ui_scale(), Qt.PenStyle.DashLine))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 4, 4)

    def write_state(self, s):
        super().write_state(s)
        s["kind"] = "text"


class TableItem(TextBlock):
    """Tabela simples: células de texto, linhas e colunas, linha de cabeçalho, bordas."""
    kind = "table"
    auto_height = True
    padding = 2.0
    min_h = 30.0
    rotatable = False

    def _setup_text(self, state):
        super()._setup_text(state)
        doc = self.text.document()
        if not self.table() and not state.get("html"):
            rows, cols = int(state.get("rows") or 3), int(state.get("columns") or 3)
            c = QTextCursor(doc)
            fmt = self.table_format(state)
            table = c.insertTable(rows, cols, fmt)
            if state.get("header", True):
                for col in range(cols):
                    cell = table.cellAt(0, col)
                    cf = cell.format()
                    cf.setBackground(QColor("#EEF2F6"))
                    cell.setFormat(cf)
            doc.clearUndoRedoStacks()

    @staticmethod
    def table_format(state) -> QTextTableFormat:
        fmt = QTextTableFormat()
        fmt.setBorder(float(state.get("lineWidth") or 1))
        fmt.setBorderBrush(QBrush(qcolor(state.get("stroke"), "#94A3B8")))
        fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        fmt.setBorderCollapse(True)
        fmt.setCellPadding(5)
        fmt.setCellSpacing(0)
        fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        return fmt

    def table(self):
        c = QTextCursor(self.text.document())
        c.movePosition(QTextCursor.MoveOperation.Start)
        while True:
            t = c.currentTable()
            if t is not None:
                return t
            if not c.movePosition(QTextCursor.MoveOperation.NextBlock):
                return None

    def paint_content(self, painter):
        if self.isSelected() and not self.editing:
            painter.setPen(QPen(QColor("#B8C2CC"), self._ui_scale(), Qt.PenStyle.DashLine))
            painter.drawRect(self.rect())

    def write_state(self, s):
        super().write_state(s)
        s["kind"] = "table"
        t = self.table()
        if t:
            s["rows"], s["columns"] = t.rows(), t.columns()
            cells = []
            for r in range(t.rows()):
                row = []
                for c in range(t.columns()):
                    cell = t.cellAt(r, c)
                    cur = cell.firstCursorPosition()
                    cur.setPosition(cell.lastCursorPosition().position(), QTextCursor.MoveMode.KeepAnchor)
                    row.append(cur.selectedText())
                cells.append(row)
            s["cells"] = cells
            s["text"] = "\n".join(" | ".join(r) for r in cells)


class ShapeItem(TextBlock):
    """Retângulo, elipse, losango e triângulo, com cor de contorno e de preenchimento e texto dentro."""
    kind = "shape"
    padding = 10.0
    default_font_size = 14.0

    def _setup_text(self, state):
        state = dict(state)
        state.setdefault("alignment", "center")
        super()._setup_text(state)
        opt = self.text.document().defaultTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WordWrap)
        self.text.document().setDefaultTextOption(opt)

    def outline(self) -> QPainterPath:
        kind = self.data_state.get("shape", "rectangle")
        r = self.rect()
        path = QPainterPath()
        if kind == "ellipse":
            path.addEllipse(r)
        elif kind == "diamond":
            path.addPolygon(QPolygonF([QPointF(r.center().x(), r.top()), QPointF(r.right(), r.center().y()),
                                       QPointF(r.center().x(), r.bottom()), QPointF(r.left(), r.center().y())]))
            path.closeSubpath()
        elif kind == "triangle":
            verts = self.data_state.get("vertices") or [[0.5, 0], [1, 1], [0, 1]]
            path.addPolygon(QPolygonF([QPointF(r.left() + v[0] * r.width(), r.top() + v[1] * r.height()) for v in verts]))
            path.closeSubpath()
        else:
            path.addRoundedRect(r, float(self.data_state.get("radius") or 2), float(self.data_state.get("radius") or 2))
        return path

    def text_rect(self) -> QRectF:
        kind = self.data_state.get("shape", "rectangle")
        r = QRectF(self.rect())
        if kind in ("ellipse", "diamond"):
            k = 0.13 if kind == "ellipse" else 0.2
            r.adjust(r.width() * k, r.height() * k, -r.width() * k, -r.height() * k)
        elif kind == "triangle":
            r.adjust(r.width() * 0.22, r.height() * 0.45, -r.width() * 0.22, -r.height() * 0.05)
        return r.adjusted(4, 4, -4, -4)

    def vertical_offset(self, r: QRectF) -> float:
        h = self.text.document().size().height()
        return max(0.0, (r.height() - h) / 2)

    def _contents_changed(self):
        super()._contents_changed()
        self.on_resized()

    def paint_content(self, painter):
        fill = self.data_state.get("fill")
        painter.setBrush(qcolor(fill) if fill else Qt.BrushStyle.NoBrush)
        width = float(self.data_state.get("lineWidth") or 2)
        stroke = self.data_state.get("stroke") or "#1F2933"
        painter.setPen(QPen(qcolor(stroke), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                       if width > 0 else Qt.PenStyle.NoPen)
        painter.drawPath(self.outline())

    def content_shape_rect(self):
        return self.rect()

    def write_state(self, s):
        super().write_state(s)
        s["kind"] = "shape"


class StickyItem(TextBlock):
    """Post-it com campo de texto e 5 cores (amarelo padrão), com cara de colado na página."""
    kind = "sticky"
    padding = 14.0
    default_font_size = 20.0
    keep_aspect = False
    rotatable = True

    def default_family(self):
        return theme.sticky_family()

    def _setup_text(self, state):
        if not state.get("fontSize"):
            # tamanho que cabe num post-it de 200 pt em cada fonte de escrita à mão
            self.default_font_size = {"Segoe Print": 15.0, "Patrick Hand": 20.0, "Caveat": 22.0}.get(self.default_family(), 18.0)
        super()._setup_text(state)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)

    def shape(self):
        path = QPainterPath()
        path.addRect(self.rect())
        if self.isSelected():
            s = self._ui_scale()
            for p in self.handle_points():
                path.addEllipse(p, (HANDLE + 3) * s, (HANDLE + 3) * s)
        return path

    def text_rect(self):
        return QRectF(14, 30, max(10, self.w - 28), max(10, self.h - 44))

    def paint_content(self, painter):
        r = self.rect()
        fill = qcolor(self.data_state.get("fill") or model.STICKY_COLORS[0][1])
        # sombra discreta embaixo, como papel colado
        shadow = QPainterPath()
        shadow.moveTo(r.left() + 6, r.bottom() - 2)
        shadow.lineTo(r.right() - 2, r.bottom() - 2)
        shadow.lineTo(r.right() - 4, r.bottom() + 4)
        shadow.quadTo(r.center().x(), r.bottom() + 1, r.left() + 8, r.bottom() + 5)
        painter.fillPath(shadow, QColor(0, 0, 0, 38))
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, fill.lighter(104))
        g.setColorAt(1, fill.darker(104))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(g)
        painter.drawRect(r)
        strip = QRectF(r.left(), r.top(), r.width(), 20)
        painter.fillRect(strip, QColor(0, 0, 0, 14))
        painter.setPen(QPen(QColor(0, 0, 0, 22), 1))
        painter.drawLine(QPointF(r.left(), strip.bottom()), QPointF(r.right(), strip.bottom()))

    def write_state(self, s):
        super().write_state(s)
        s["kind"] = "sticky"


class TranscriptItem(TextBlock):
    """Cartão com a transcrição de um áudio; recolhe a um quadrado ao tocar no cabeçalho."""
    kind = "transcript"
    default_font_size = 14.0
    header = 34.0

    def text_rect(self):
        return QRectF(12, self.header, max(10, self.w - 24), max(10, self.h - self.header - 12))

    @property
    def folded(self) -> bool:
        return bool(self.data_state.get("folded"))

    def paint_content(self, painter):
        r = self.rect()
        painter.setPen(QPen(QColor("#C7CFDB"), 1))
        painter.setBrush(QColor("#F5F7FB"))
        painter.drawRoundedRect(r, 10, 10)
        pm = icons.pixmap("transcript", "#3B5B8C", 18)
        if self.folded:
            painter.drawPixmap(QRectF(r.center().x() - 11, r.center().y() - 11, 22, 22), pm, QRectF(pm.rect()))
            return
        painter.drawPixmap(QRectF(12, 8, 18, 18), pm, QRectF(pm.rect()))
        painter.setPen(QColor("#3B5B8C"))
        painter.setFont(theme.ui_font(9.5, True))
        painter.drawText(QRectF(36, 6, self.w - 48, 22), Qt.AlignmentFlag.AlignVCenter, "Transcrição")
        painter.setPen(QPen(QColor("#DDE3EC"), 1))
        painter.drawLine(QPointF(10, self.header - 4), QPointF(self.w - 10, self.header - 4))

    def read_state(self, state):
        super().read_state(state)
        self.text.setVisible(not self.folded)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._hit_handle(event.pos()) \
                and (self.folded or event.pos().y() < self.header) and self.canvas.editor is not None \
                and event.modifiers() == Qt.KeyboardModifier.NoModifier and self.isSelected():
            self.canvas.editor.toggle_fold(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def activate(self, pos=None):
        if self.folded and self.canvas.editor is not None:
            self.canvas.editor.toggle_fold(self)
            return
        super().activate(pos)

    def write_state(self, s):
        super().write_state(s)
        s["kind"] = "transcript"


# ====================================================================== linhas
class LineItem(BlockItem):
    """Linha ou seta; as pontas ficam em ``points`` (relativas ao quadro)."""
    kind = "line"
    rotatable = False
    min_w = min_h = 1.0

    def __init__(self, scene, state):
        super().__init__(scene, state)
        self.read_state(state)

    def read_state(self, state):
        pts = state.get("points") or [[0, 0], [self.w, self.h]]
        self.p1, self.p2 = QPointF(*pts[0]), QPointF(*pts[1])

    def handle_points(self):
        return [self.p1, self.p2]

    def boundingRect(self):
        m = 30.0
        return QRectF(self.p1, self.p2).normalized().adjusted(-m, -m, m, m)

    def shape(self):
        path = QPainterPath(self.p1)
        path.lineTo(self.p2)
        st = QPainterPathStroker()
        st.setWidth(max(10.0, float(self.data_state.get("lineWidth") or 2) + 8))
        out = st.createStroke(path)
        if self.isSelected():
            s = self._ui_scale()
            for p in self.handle_points():
                out.addEllipse(p, (HANDLE + 3) * s, (HANDLE + 3) * s)
        return out

    def paint_content(self, painter):
        width = float(self.data_state.get("lineWidth") or 2)
        color = qcolor(self.data_state.get("stroke") or "#1F2933")
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(self.p1, self.p2)
        if self.data_state.get("shape") == "arrow":
            draw_arrow_head(painter, self.p1, self.p2, width, color)

    def paint_selection(self, painter):
        s = self._ui_scale()
        painter.setBrush(QColor("white"))
        painter.setPen(QPen(ACCENT, 1.4 * s))
        for p in self.handle_points():
            painter.drawEllipse(p, HANDLE * s, HANDLE * s)

    def _resize_drag(self, handle, event):
        p = event.pos()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            other = self.p2 if handle == 0 else self.p1
            d = p - other
            ang = round(math.atan2(d.y(), d.x()) / (math.pi / 4)) * (math.pi / 4)
            ln = math.hypot(d.x(), d.y())
            p = other + QPointF(math.cos(ang) * ln, math.sin(ang) * ln)
        self.prepareGeometryChange()
        if handle == 0:
            self.p1 = p
        else:
            self.p2 = p
        self._normalize()
        self.canvas.item_moved(self)

    def _normalize(self) -> None:
        """Mantém a origem do objeto no canto superior esquerdo das duas pontas."""
        top_left = QPointF(min(self.p1.x(), self.p2.x()), min(self.p1.y(), self.p2.y()))
        self.prepareGeometryChange()
        self.p1 -= top_left
        self.p2 -= top_left
        self.setPos(self.pos() + top_left)
        self.w = max(1.0, abs(self.p2.x() - self.p1.x()))
        self.h = max(1.0, abs(self.p2.y() - self.p1.y()))
        self.update()

    def write_state(self, s):
        s["kind"] = "line"
        s["points"] = [[round(self.p1.x(), 2), round(self.p1.y(), 2)], [round(self.p2.x(), 2), round(self.p2.y(), 2)]]


def draw_arrow_head(painter, p1: QPointF, p2: QPointF, width: float, color: QColor) -> None:
    angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
    size = 8 + width * 2.2
    a = QPointF(p2.x() - size * math.cos(angle - 0.45), p2.y() - size * math.sin(angle - 0.45))
    b = QPointF(p2.x() - size * math.cos(angle + 0.45), p2.y() - size * math.sin(angle + 0.45))
    painter.setBrush(color)
    painter.setPen(QPen(color, max(1.0, width * 0.6), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPolygon(QPolygonF([p2, a, b]))


# ====================================================================== stickers
class CalendarItem(BlockItem):
    """Calendário de mesa com o dia (editável): duplo clique escolhe outra data."""
    kind = "calendar"
    keep_aspect = True

    def day(self) -> date:
        try:
            return date.fromisoformat(self.data_state.get("date") or "")
        except ValueError:
            return date.today()

    def paint_content(self, painter):
        r = self.rect()
        d = self.day()
        s = self.w / model.CALENDAR_SIZE[0]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.drawRoundedRect(r.adjusted(2 * s, 4 * s, 2 * s, 4 * s), 16 * s, 16 * s)
        painter.setBrush(QColor("white"))
        painter.setPen(QPen(QColor("#D9DDE3"), 1))
        painter.drawRoundedRect(r, 16 * s, 16 * s)
        head = QPainterPath()
        top = QRectF(r.left(), r.top(), r.width(), 36 * s)
        head.addRoundedRect(top, 16 * s, 16 * s)
        rect_bottom = QPainterPath()
        rect_bottom.addRect(QRectF(r.left(), r.top() + 18 * s, r.width(), 18 * s))
        head = head.united(rect_bottom)
        painter.fillPath(head, QColor("#E5484D"))
        f = QFont(theme.UI_FONT)
        f.setPixelSize(max(6, int(17 * s)))
        f.setWeight(QFont.Weight.Bold)
        painter.setFont(f)
        painter.setPen(QColor("white"))
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, MONTHS[d.month - 1])
        f.setPixelSize(max(8, int(64 * s)))
        f.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f)
        painter.setPen(QColor("#1F2933"))
        painter.drawText(QRectF(r.left(), top.bottom() - 2 * s, r.width(), 76 * s), Qt.AlignmentFlag.AlignCenter, str(d.day))
        f.setPixelSize(max(6, int(14 * s)))
        f.setWeight(QFont.Weight.Normal)
        painter.setFont(f)
        painter.setPen(QColor("#6B7682"))
        painter.drawText(QRectF(r.left(), r.bottom() - 32 * s, r.width(), 24 * s), Qt.AlignmentFlag.AlignCenter,
                         WEEKDAYS[d.weekday()])

    def activate(self, pos=None):
        if self.canvas.editor is not None:
            self.canvas.editor.pick_calendar_date(self)

    def search_text(self):
        return self.day().strftime("%d/%m/%Y")


class StickerItem(BlockItem):
    """Sticker: emoji desenhado pela fonte de emoji do Windows, ou uma imagem."""
    kind = "sticker"
    keep_aspect = True

    def paint_content(self, painter):
        r = self.rect()
        emoji = self.data_state.get("emoji")
        if emoji:
            f = QFont("Segoe UI Emoji")
            f.setPixelSize(max(6, int(min(r.width(), r.height()) * 0.82)))
            painter.setFont(f)
            painter.setPen(QColor("#1F2933"))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, emoji)
            return
        img = self.canvas.assets.image(self.data_state.get("asset"), int(max(self.w, self.h) * 2))
        if img is not None:
            painter.drawImage(r, img)


# ====================================================================== mídias
class ImageItem(BlockItem):
    kind = "image"
    keep_aspect = True

    def image_rect_source(self, img: QImage) -> QRectF:
        crop = self.data_state.get("crop")
        if crop:
            return QRectF(crop["x"] * img.width(), crop["y"] * img.height(), crop["width"] * img.width(), crop["height"] * img.height())
        return QRectF(0, 0, img.width(), img.height())

    def paint_content(self, painter):
        r = self.rect()
        views = self.scene().views() if self.scene() else []
        zoom = views[0].transform().m11() if views else 1.0
        img = self.canvas.assets.image(self.data_state.get("asset"), int(max(self.w, self.h) * max(1.0, zoom) * 1.5))
        mask = self.data_state.get("mask")
        if mask:
            painter.setClipPath(shape_path(mask, r))
        if img is None:
            painter.fillRect(r, QColor("#EEF1F4"))
            painter.setPen(QColor("#9AA5B1"))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "Imagem")
            return
        painter.drawImage(r, img, self.image_rect_source(img))

    def menu_actions(self, menu, editor):
        editor.image_menu(self, menu)

    def search_text(self):
        return self.data_state.get("caption") or ""


def shape_path(kind: str, r: QRectF) -> QPainterPath:
    path = QPainterPath()
    if kind == "ellipse":
        path.addEllipse(r)
    elif kind == "diamond":
        path.addPolygon(QPolygonF([QPointF(r.center().x(), r.top()), QPointF(r.right(), r.center().y()),
                                   QPointF(r.center().x(), r.bottom()), QPointF(r.left(), r.center().y())]))
    elif kind == "triangle":
        path.addPolygon(QPolygonF([QPointF(r.center().x(), r.top()), r.bottomRight(), r.bottomLeft()]))
    else:
        path.addRoundedRect(r, 10, 10)
    path.closeSubpath()
    return path


class PdfItem(BlockItem):
    """PDF na nota: mostra a primeira página; duplo clique abre o leitor."""
    kind = "pdf"
    keep_aspect = True

    def paint_content(self, painter):
        r = self.rect()
        digest = self.data_state.get("asset")
        views = self.scene().views() if self.scene() else []
        zoom = views[0].transform().m11() if views else 1.0
        img = self.canvas.assets.pdf_page(digest, int(self.data_state.get("page") or 0), int(self.w * max(1.0, zoom) * 1.5))
        painter.setPen(QPen(QColor("#CBD2D9"), 1))
        painter.setBrush(QColor("white"))
        painter.drawRect(r)
        if img is not None:
            painter.drawImage(r.adjusted(1, 1, -1, -1), img)
        badge = QRectF(r.left() + 6, r.bottom() - 26, min(r.width() - 12, 190), 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(31, 41, 51, 200))
        painter.drawRoundedRect(badge, 6, 6)
        painter.setPen(QColor("white"))
        painter.setFont(theme.ui_font(8))
        n = self.canvas.assets.pdf_page_count(digest) if digest else 0
        name = self.data_state.get("caption") or "PDF"
        label = f"{name} · {n} pág." if n else name
        painter.drawText(badge.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter,
                         QFontMetricsF(theme.ui_font(8)).elidedText(label, Qt.TextElideMode.ElideMiddle, badge.width() - 12))

    def activate(self, pos=None):
        if self.canvas.editor is not None:
            self.canvas.editor.open_pdf(self)

    def search_text(self):
        return self.data_state.get("caption") or ""


class AudioItem(BlockItem):
    """Áudio gravado ou importado: tocar e pausar no próprio bloco."""
    kind = "audio"
    min_w, min_h = 180.0, 44.0
    rotatable = False

    def playing(self) -> bool:
        ed = self.canvas.editor
        return bool(ed and ed.media.is_playing(self.block_id))

    def progress(self) -> tuple[float, float]:
        ed = self.canvas.editor
        dur = float(self.data_state.get("duration") or 0)
        if ed:
            pos, d = ed.media.position(self.block_id)
            if d:
                dur = d
            return pos, dur
        return 0.0, dur

    def paint_content(self, painter):
        r = self.rect()
        painter.setPen(QPen(QColor("#D5DBE3"), 1))
        painter.setBrush(QColor("#F7F9FC"))
        painter.drawRoundedRect(r, r.height() / 2.4, r.height() / 2.4)
        d = min(r.height() - 16, 40)
        btn = QRectF(10, (r.height() - d) / 2, d, d)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT)
        painter.drawEllipse(btn)
        pm = icons.pixmap("pause" if self.playing() else "play", "#FFFFFF", 18)
        painter.drawPixmap(btn.adjusted(d * 0.27, d * 0.27, -d * 0.27, -d * 0.27), pm, QRectF(pm.rect()))
        pos, dur = self.progress()
        x0 = btn.right() + 12
        bar = QRectF(x0, r.height() / 2 + 4, max(20, r.width() - x0 - 16), 4)
        painter.setBrush(QColor("#D9E0E8"))
        painter.drawRoundedRect(bar, 2, 2)
        if dur > 0:
            done = QRectF(bar.left(), bar.top(), bar.width() * min(1.0, pos / dur), bar.height())
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(done, 2, 2)
        painter.setPen(QColor("#1F2933"))
        painter.setFont(theme.ui_font(9, True))
        title = self.data_state.get("caption") or "Áudio"
        fm = QFontMetricsF(theme.ui_font(9, True))
        painter.drawText(QRectF(x0, 6, bar.width() - 60, r.height() / 2 - 4), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                         fm.elidedText(title, Qt.TextElideMode.ElideRight, bar.width() - 64))
        painter.setFont(theme.ui_font(8.5))
        painter.setPen(QColor("#6B7682"))
        t = f"{fmt_time(pos)} / {fmt_time(dur)}" if dur else fmt_time(pos)
        painter.drawText(QRectF(bar.right() - 90, 6, 90, r.height() / 2 - 4), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, t)

    def mousePressEvent(self, event):
        r = self.rect()
        d = min(r.height() - 16, 40)
        btn = QRectF(10, (r.height() - d) / 2, d, d)
        if event.button() == Qt.MouseButton.LeftButton and btn.adjusted(-4, -4, 4, 4).contains(event.pos()) and self.canvas.editor:
            self.canvas.editor.media.toggle(self)
            event.accept()
            return
        x0 = btn.right() + 12
        bar = QRectF(x0, r.height() / 2 - 4, max(20, r.width() - x0 - 16), 18)
        if event.button() == Qt.MouseButton.LeftButton and self.isSelected() and bar.contains(event.pos()) and self.canvas.editor:
            frac = (event.pos().x() - bar.left()) / bar.width()
            self.canvas.editor.media.seek(self, frac)
            event.accept()
            return
        super().mousePressEvent(event)

    def menu_actions(self, menu, editor):
        editor.audio_menu(self, menu)

    def search_text(self):
        return self.data_state.get("caption") or ""


class VideoItem(BlockItem):
    kind = "video"
    keep_aspect = True

    def paint_content(self, painter):
        r = self.rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        painter.drawRoundedRect(r, 8, 8)
        poster = self.canvas.assets.image(self.data_state.get("poster"), int(max(self.w, self.h) * 1.5))
        if poster is not None:
            path = QPainterPath()
            path.addRoundedRect(r, 8, 8)
            painter.setClipPath(path)
            painter.drawImage(r, poster)
            painter.setClipping(False)
        d = min(56.0, min(r.width(), r.height()) * 0.4)
        c = r.center()
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawEllipse(c, d / 2, d / 2)
        pm = icons.pixmap("play", "#FFFFFF", 24)
        painter.drawPixmap(QRectF(c.x() - d * 0.22, c.y() - d * 0.25, d * 0.5, d * 0.5), pm, QRectF(pm.rect()))
        dur = float(self.data_state.get("duration") or 0)
        if dur:
            painter.setFont(theme.ui_font(8.5, True))
            painter.setPen(QColor("white"))
            painter.drawText(r.adjusted(8, 6, -10, -6), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, fmt_time(dur))

    def activate(self, pos=None):
        if self.canvas.editor is not None:
            self.canvas.editor.open_video(self)

    def search_text(self):
        return self.data_state.get("caption") or ""


class NoteRefItem(BlockItem):
    """Cartão de uma nota na Teia: nome, data de criação e prévia da primeira página. A nota
    não é copiada; uma nota apagada vira um cartão indisponível."""
    kind = "noteRef"
    keep_aspect = False
    min_w, min_h = 120.0, 120.0

    def paint_content(self, painter):
        r = self.rect()
        info = self.canvas.resolve_note(self.data_state.get("documentID"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 28))
        painter.drawRoundedRect(r.translated(0, 3), 12, 12)
        painter.setBrush(QColor("#E6E9ED"))
        painter.setPen(QPen(QColor("#9AA5B1"), 1.2))
        painter.drawRoundedRect(r, 12, 12)
        title_h = 44.0
        preview = QRectF(10, 10, r.width() - 20, r.height() - title_h - 16)
        if info and info.get("preview") is not None:
            img: QImage = info["preview"]
            scale = min(preview.width() / img.width(), preview.height() / img.height())
            w, h = img.width() * scale, img.height() * scale
            target = QRectF(preview.center().x() - w / 2, preview.top(), w, h)
            painter.setPen(QPen(QColor("#C3CAD2"), 1))
            painter.setBrush(QColor("white"))
            painter.drawRect(target)
            painter.drawImage(target, img)
        else:
            painter.setBrush(QColor("white"))
            painter.setPen(QPen(QColor("#C3CAD2"), 1))
            painter.drawRect(preview)
        painter.setPen(QColor("#1F2933"))
        painter.setFont(theme.ui_font(10, True))
        title = info["title"] if info else "Nota indisponível"
        fm = QFontMetricsF(theme.ui_font(10, True))
        painter.drawText(QRectF(12, r.height() - title_h, r.width() - 24, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(title, Qt.TextElideMode.ElideRight, r.width() - 24))
        painter.setPen(QColor("#6B7682"))
        painter.setFont(theme.ui_font(8.5))
        painter.drawText(QRectF(12, r.height() - title_h + 18, r.width() - 24, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         info["created"] if info else "")

    def activate(self, pos=None):
        if self.canvas.editor is not None and self.data_state.get("documentID"):
            self.canvas.editor.open_note(self.data_state["documentID"])

    def search_text(self):
        info = self.canvas.resolve_note(self.data_state.get("documentID"))
        return info["title"] if info else ""


# ====================================================================== conexões
class ConnectorItem(QGraphicsPathItem):
    """Ligação entre dois objetos (cor própria; acompanha os objetos quando eles se mexem)."""

    def __init__(self, canvas, state: dict):
        super().__init__()
        self.canvas = canvas
        self.rel_id = state["id"]
        self.data_state = copy.deepcopy(state)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(9)
        self.refresh()

    def state(self) -> dict:
        return copy.deepcopy(self.data_state)

    def set_state(self, state: dict) -> None:
        self.data_state = copy.deepcopy(state)
        self.refresh()

    def endpoints(self):
        a = self.canvas.items_by_id.get(self.data_state.get("sourceID"))
        b = self.canvas.items_by_id.get(self.data_state.get("targetID"))
        if not a or not b:
            return None
        ca = a.mapToScene(QPointF(a.w / 2, a.h / 2))
        cb = b.mapToScene(QPointF(b.w / 2, b.h / 2))
        return _edge_point(a, ca, cb), _edge_point(b, cb, ca)

    def refresh(self) -> None:
        ends = self.endpoints()
        path = QPainterPath()
        if ends:
            p1, p2 = ends
            style = self.data_state.get("style") or {}
            if style.get("routing") == "orthogonal":
                mid = (p1.x() + p2.x()) / 2
                path.moveTo(p1)
                path.lineTo(mid, p1.y())
                path.lineTo(mid, p2.y())
                path.lineTo(p2)
            else:
                path.moveTo(p1)
                path.lineTo(p2)
            a = self.canvas.items_by_id.get(self.data_state.get("sourceID"))
            b = self.canvas.items_by_id.get(self.data_state.get("targetID"))
            self.setZValue(max(a.zValue(), b.zValue()) + 0.5 if a and b else 9)
        self.prepareGeometryChange()
        self.setPath(path)

    def boundingRect(self):
        return super().boundingRect().adjusted(-14, -14, 14, 14)

    def shape(self):
        st = QPainterPathStroker()
        st.setWidth(12)
        return st.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        style = self.data_state.get("style") or {}
        color = qcolor(style.get("color") or "#334155")
        width = float(style.get("width") or 2)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, width, Qt.PenStyle.DashLine if style.get("chronology") else Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        if self.isSelected():
            glow = QPen(QColor(47, 111, 181, 90), width + 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(glow)
            painter.drawPath(self.path())
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())
        if style.get("arrowAtEnd", True) and self.path().elementCount() >= 2:
            n = self.path().elementCount()
            e1, e2 = self.path().elementAt(n - 2), self.path().elementAt(n - 1)
            draw_arrow_head(painter, QPointF(e1.x, e1.y), QPointF(e2.x, e2.y), width, color)

    def contextMenuEvent(self, event):
        ed = self.canvas.editor
        if ed is not None:
            self.scene().clearSelection()
            self.setSelected(True)
            ed.connector_menu(self, event.screenPos())
            event.accept()


def _edge_point(item: BlockItem, center: QPointF, toward: QPointF) -> QPointF:
    """Onde a reta entre os centros sai do contorno do objeto."""
    line = QLineF(center, toward)
    local_outline = item.outline() if hasattr(item, "outline") else None
    if local_outline is None:
        local_outline = QPainterPath()
        local_outline.addRect(item.rect())
    poly = item.mapToScene(local_outline.toFillPolygon())
    best = None
    for i in range(poly.count()):
        a, b = poly.at(i), poly.at((i + 1) % poly.count())
        kind, p = line.intersects(QLineF(a, b))
        if kind == QLineF.IntersectionType.BoundedIntersection:
            d = QLineF(center, p).length()
            if best is None or d > best[0]:
                best = (d, p)
    return best[1] if best else center


class CellsItem(BlockItem):
    """Conta no papel quadriculado: um caractere por quadrado. O que a pessoa digita fica em
    preto; a resposta, em azul, ocupa os quadrados seguintes ao "=" (ou vem depois de um
    quadrado vazio, numa equação). Também guarda a resposta de uma conta escrita à mão."""
    kind = "cells"
    resizable = False
    rotatable = False
    min_w, min_h = 4.0, 4.0
    SHOW = {".": "·", "*": "×", "-": "−"}

    def __init__(self, scene, state):
        self.editing = False
        self.cursor = 0
        super().__init__(scene, state)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.fit()

    @property
    def cell(self) -> float:
        return float(self.data_state.get("cell") or 20)

    def chars(self) -> list[tuple[str, bool]]:
        out = [(c, False) for c in self.data_state.get("text") or ""]
        return out + [(c, True) for c in self.data_state.get("answer") or ""]

    def fit(self) -> None:
        n = max(1, len(self.chars()), self.cursor + 1 if self.editing else 0)
        self.prepareGeometryChange()
        self.w, self.h = self.cell * n, self.cell
        self.setTransformOriginPoint(self.w / 2, self.h / 2)
        self.update()

    def read_state(self, state):
        self.fit()

    def paint_content(self, painter):
        cell = self.cell
        if self.editing:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(37, 99, 235, 28))
            painter.drawRect(QRectF(0, 0, self.w, cell))
            painter.setPen(QPen(ACCENT, max(0.8, cell / 14)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(self.cursor * cell, 0, cell, cell))
        f = QFont(self.data_state.get("fontName") or self.canvas.default_family)
        f.setPixelSize(100)
        fm = QFontMetricsF(f)
        digit = fm.tightBoundingRect("0").height() or fm.capHeight()
        k = 0.6 * cell / max(1.0, digit)
        ink = qcolor(self.data_state.get("foreground"), "#1F2933")
        blue = qcolor(self.data_state.get("answerColor"), "#2563EB")
        for i, (c, answer) in enumerate(self.chars()):
            if c == " ":
                continue
            ch = self.SHOW.get(c, c)
            path = QPainterPath()
            path.addText(QPointF(0, 0), f, ch)
            adv = fm.horizontalAdvance(ch)
            painter.save()
            painter.translate(i * cell + cell / 2 - adv * k / 2, cell / 2 + digit * k / 2)
            painter.scale(k, k)
            painter.fillPath(path, blue if answer else ink)
            painter.restore()

    def paint_selection(self, painter):
        if not self.editing:
            super().paint_selection(painter)

    def search_text(self) -> str:
        return (self.data_state.get("text") or "") + " " + (self.data_state.get("answer") or "")

    # ------------------------------------------------------------------ digitação
    def column_at(self, scene_pos: QPointF) -> int:
        return max(0, int(self.mapFromScene(scene_pos).x() // self.cell))

    def mousePressEvent(self, event):
        ed = self.canvas.editor
        if event.button() == Qt.MouseButton.LeftButton and ed is not None and ed.tool == "select" \
                and not self.data_state.get("equationOf"):
            ed.start_cells(self, self.column_at(event.scenePos()))
            event.accept()
            return
        super().mousePressEvent(event)

    def start_editing(self, column: int = 0) -> None:
        self.editing = True
        self.cursor = max(0, min(column, len(self.data_state.get("text") or "")))
        self.fit()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def stop_editing(self) -> None:
        if not self.editing:
            return
        self.editing = False
        self.clearFocus()
        self.fit()
        ed = self.canvas.editor
        if ed is not None:
            ed.cells_done(self)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.editing and event.reason() != Qt.FocusReason.PopupFocusReason:
            self.stop_editing()

    def set_text(self, text: str) -> None:
        import mathsolve
        self.data_state["text"] = text
        self.data_state["answer"] = mathsolve.cells_answer(text)
        self.fit()
        self.canvas.item_moved(self)
        if self.canvas.editor is not None:
            self.canvas.editor.content_changed()

    def keyPressEvent(self, event):
        if not self.editing:
            return super().keyPressEvent(event)
        text = self.data_state.get("text") or ""
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            self.stop_editing()
        elif key == Qt.Key.Key_Backspace:
            if self.cursor > 0:
                self.cursor -= 1
                self.set_text(text[:self.cursor] + text[self.cursor + 1:])
        elif key == Qt.Key.Key_Delete:
            self.set_text(text[:self.cursor] + text[self.cursor + 1:])
        elif key == Qt.Key.Key_Left:
            self.cursor = max(0, self.cursor - 1)
            self.fit()
        elif key == Qt.Key.Key_Right:
            self.cursor = min(len(text), self.cursor + 1)
            self.fit()
        elif key == Qt.Key.Key_Home:
            self.cursor = 0
            self.fit()
        elif key == Qt.Key.Key_End:
            self.cursor = len(text)
            self.fit()
        elif event.text() and event.text().isprintable() and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            ch = event.text()[0]
            # cada tecla ocupa o quadrado do cursor (escreve por cima) e o cursor anda um
            new = text[:self.cursor] + ch + text[self.cursor + 1:]
            self.cursor += 1
            self.set_text(new)
        else:
            return super().keyPressEvent(event)
        event.accept()


ITEM_CLASSES = {
    "text": TextBoxItem, "table": TableItem, "shape": ShapeItem, "sticky": StickyItem, "transcript": TranscriptItem,
    "line": LineItem, "calendar": CalendarItem, "sticker": StickerItem, "image": ImageItem, "pdf": PdfItem,
    "audio": AudioItem, "video": VideoItem, "noteRef": NoteRefItem, "cells": CellsItem,
}


def make_item(canvas, state: dict) -> BlockItem:
    cls = ITEM_CLASSES.get(state.get("kind"), TextBoxItem)
    return cls(canvas, state)
