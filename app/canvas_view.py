"""Vista do canvas: zoom (Ctrl + roda, pinça do touchpad), rolagem, caneta com pressão (Windows
Ink), mouse para desenhar, borracha, laço, formas arrastadas e conexões."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QInputDevice, QPainter, QPainterPath, QPen, QPointingDevice
from PySide6.QtWidgets import QFrame, QGraphicsItem, QGraphicsView

import theme
from ink import INK_Z

INK_TOOLS = ("pen", "marker", "pencil")


class LiveInk(QGraphicsItem):
    """Traço enquanto é desenhado (o contorno com pressão é feito ao soltar)."""

    def __init__(self, color: str, width: float, tool: str):
        super().__init__()
        self.color = QColor(color)
        if tool == "marker":
            self.color.setAlpha(110)
        self.width = width
        self.tool = tool
        self.points: list[tuple[float, float, float]] = []
        self.path = QPainterPath()
        self.setZValue(INK_Z + 1)

    def add(self, p: QPointF, pressure: float) -> None:
        self.prepareGeometryChange()
        if not self.points:
            self.path.moveTo(p)
        else:
            self.path.lineTo(p)
        self.points.append((p.x(), p.y(), pressure))

    def boundingRect(self):
        return self.path.boundingRect().adjusted(-self.width * 2, -self.width * 2, self.width * 2, self.width * 2)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width if self.tool == "marker" else self.width * 0.85
        cap = Qt.PenCapStyle.FlatCap if self.tool == "marker" else Qt.PenCapStyle.RoundCap
        painter.setPen(QPen(self.color, w, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(self.path)


class RubberShape(QGraphicsItem):
    """Contorno enquanto se arrasta para criar uma forma ou uma conexão."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.a = self.b = QPointF()
        self.setZValue(INK_Z + 2)

    def set(self, a, b):
        self.prepareGeometryChange()
        self.a, self.b = a, b

    def boundingRect(self):
        return QRectF(self.a, self.b).normalized().adjusted(-20, -20, 20, 20)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme.ACCENT), 1.5, Qt.PenStyle.DashLine))
        r = QRectF(self.a, self.b).normalized()
        if self.kind in ("line", "arrow", "connector"):
            painter.drawLine(self.a, self.b)
        elif self.kind == "ellipse":
            painter.drawEllipse(r)
        else:
            painter.drawRect(r)


class CanvasView(QGraphicsView):
    zoomChanged = Signal(float)
    visiblePageChanged = Signal(int)

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.tool = "select"
        self.live: LiveInk | None = None
        self.live_page = 0
        self.erasing = False
        self.eraser_from_pen = False
        self.rubber: RubberShape | None = None
        self.connect_from = None
        self._pan = None
        self._tablet_down = False
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor(theme.DESK))
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)

    # ------------------------------------------------------------------ zoom
    def zoom(self) -> float:
        return self.transform().m11()

    def set_zoom(self, z: float, anchor_mouse: bool = False) -> None:
        z = max(0.25, min(4.0, z))
        if not anchor_mouse:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        f = z / self.zoom()
        self.scale(f, f)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.zoomChanged.emit(z)
        if self.scene() is not None:
            self.scene().update()

    def fit_width(self) -> None:
        sc = self.scene()
        if sc is None:
            return
        avail = max(200, self.viewport().width() - 56)
        self.set_zoom(min(2.0, avail / sc.page_w))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            self.set_zoom(self.zoom() * (1.12 ** steps), anchor_mouse=True)
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, e):
        if e.type() == QEvent.Type.NativeGesture:
            from PySide6.QtCore import Qt as _Qt
            if e.gestureType() == _Qt.NativeGestureType.ZoomNativeGesture:
                self.set_zoom(self.zoom() * (1 + e.value()), anchor_mouse=True)
                return True
        return super().event(e)

    def _scrolled(self, *_):
        sc = self.scene()
        if sc is None:
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.visiblePageChanged.emit(sc.page_at_y(center.y()))

    def current_page(self) -> int:
        sc = self.scene()
        if sc is None:
            return 0
        top = self.mapToScene(0, int(self.viewport().height() * 0.35))
        return sc.page_at_y(top.y())

    # ------------------------------------------------------------------ ferramentas
    def set_tool(self, tool: str) -> None:
        self.tool = tool
        drawing = tool in INK_TOOLS or tool == "eraser"
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag if tool == "lasso" else QGraphicsView.DragMode.NoDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        sc = self.scene()
        if sc is not None:
            for st in sc.strokes_by_id.values():
                st.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, tool == "lasso")
                st.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, tool == "lasso")
            if drawing:
                sc.clearSelection()
                sc.setFocusItem(None)
        if drawing:
            self.viewport().setCursor(self._pen_cursor() if tool != "eraser" else Qt.CursorShape.CrossCursor)
        elif tool.startswith("shape:") or tool == "connector":
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().unsetCursor()

    def _pen_cursor(self):
        return Qt.CursorShape.CrossCursor

    def _from_stylus(self, event) -> bool:
        dev = event.device() if hasattr(event, "device") else None
        try:
            return dev is not None and dev.type() == QInputDevice.DeviceType.Stylus
        except Exception:
            return False

    # ------------------------------------------------------------------ caneta (Windows Ink)
    def viewportEvent(self, event):
        t = event.type()
        if t in (QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease):
            eraser_end = event.pointerType() == QPointingDevice.PointerType.Eraser
            tool = "eraser" if eraser_end else self.tool
            if tool in INK_TOOLS or tool == "eraser":
                pos = self._map(event.position())
                pressure = float(event.pressure()) if event.pressure() > 0 else 0.5
                if t == QEvent.Type.TabletPress:
                    self._tablet_down = True
                    self.eraser_from_pen = eraser_end
                    self._begin(tool, pos, pressure)
                elif t == QEvent.Type.TabletMove and self._tablet_down:
                    self._move(tool, pos, pressure)
                elif t == QEvent.Type.TabletRelease and self._tablet_down:
                    self._tablet_down = False
                    self._end(tool, pos)
                event.accept()
                return True
        return super().viewportEvent(event)

    def _map(self, posf) -> QPointF:
        """Posição da caneta na cena, sem arredondar para o pixel (traço mais liso)."""
        inverse, ok = self.viewportTransform().inverted()
        return inverse.map(QPointF(posf)) if ok else QPointF(self.mapToScene(posf.toPoint()))

    def _begin(self, tool, pos: QPointF, pressure: float) -> None:
        sc = self.scene()
        if tool == "eraser":
            self.erasing = True
            sc.begin_change()
            self.editor.erase_at(pos)
            return
        self.live_page = sc.page_at_y(pos.y())
        color, width = self.editor.ink_style(tool)
        self.live = LiveInk(color, width, tool)
        sc.addItem(self.live)
        self.live.add(pos, pressure)

    def _move(self, tool, pos: QPointF, pressure: float) -> None:
        if tool == "eraser":
            if self.erasing:
                self.editor.erase_at(pos)
            return
        if self.live is not None:
            last = self.live.points[-1]
            if math.hypot(pos.x() - last[0], pos.y() - last[1]) * self.zoom() >= 0.8:
                self.live.add(pos, pressure)

    def _end(self, tool, pos: QPointF) -> None:
        sc = self.scene()
        if tool == "eraser":
            if self.erasing:
                self.erasing = False
                sc.end_change("Apagar traço")
            return
        live, self.live = self.live, None
        if live is None:
            return
        sc.removeItem(live)
        if len(live.points) == 1:
            x, y, p = live.points[0]
            live.points.append((x + 0.3, y + 0.3, p))
        self.editor.finish_stroke(self.live_page, live.tool, live.points)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self._tablet_down or (self._from_stylus(event) and (self.tool in INK_TOOLS or self.tool == "eraser")):
            event.accept()
            return
        pos = self._map(event.position())
        if event.button() == Qt.MouseButton.LeftButton:
            if self.tool in INK_TOOLS or self.tool == "eraser":
                self._mouse_ink = True
                self._begin(self.tool, pos, 0.5)
                event.accept()
                return
            if self.tool.startswith("shape:"):
                self.rubber = RubberShape(self.tool.split(":", 1)[1])
                self.rubber.set(pos, pos)
                self.scene().addItem(self.rubber)
                event.accept()
                return
            if self.tool == "connector":
                src = self.editor.block_at(pos)
                if src is not None:
                    self.connect_from = src
                    self.rubber = RubberShape("connector")
                    self.rubber.set(pos, pos)
                    self.scene().addItem(self.rubber)
                event.accept()
                return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.tool == "select":
            self.editor.after_canvas_press(pos)

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            d = event.position() - self._pan
            self._pan = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        if self._tablet_down:
            return
        pos = self._map(event.position())
        if getattr(self, "_mouse_ink", False):
            self._move(self.tool, pos, 0.5)
            return
        if self.rubber is not None:
            a = self.rubber.a
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.rubber.kind not in ("line", "arrow", "connector"):
                side = max(abs(pos.x() - a.x()), abs(pos.y() - a.y()))
                pos = QPointF(a.x() + math.copysign(side, pos.x() - a.x()), a.y() + math.copysign(side, pos.y() - a.y()))
            self.rubber.set(a, pos)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan is not None and event.button() == Qt.MouseButton.MiddleButton:
            self._pan = None
            self.set_tool(self.tool)
            return
        if self._tablet_down:
            return
        pos = self._map(event.position())
        if getattr(self, "_mouse_ink", False):
            self._mouse_ink = False
            self._end(self.tool, pos)
            return
        if self.rubber is not None:
            rubber, self.rubber = self.rubber, None
            self.scene().removeItem(rubber)
            if rubber.kind == "connector":
                target = self.editor.block_at(pos)
                if self.connect_from is not None and target is not None and target is not self.connect_from:
                    self.editor.connect_blocks(self.connect_from, target)
                self.connect_from = None
                return
            self.editor.finish_shape_drag(rubber.kind, rubber.a, rubber.b)
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.editor.handle_view_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ arrastar arquivos
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        md = event.mimeData()
        pos = self._map(event.position())
        if md.hasUrls():
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if paths:
                self.editor.insert_files(paths, at=pos)
                event.acceptProposedAction()
                return
        if md.hasImage():
            self.editor.insert_qimage(md.imageData(), at=pos)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.editor.view_resized()
