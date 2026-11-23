"""Tinta: traços com pressão da caneta (Windows Ink), marcador, lápis e borracha (traço inteiro
ou só a parte tocada). Os pontos ficam em coordenadas da página."""

from __future__ import annotations

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem

import model

TOOLS = [("pen", "Caneta", "pen"), ("marker", "Marcador", "marker"), ("pencil", "Lápis", "pencil")]
INK_Z = 5000.0


def smooth(points: list[tuple[float, float, float]], passes: int = 1) -> list[tuple[float, float, float]]:
    """Chaikin: arredonda os cantos dos segmentos sem afastar o traço do lugar."""
    pts = points
    for _ in range(passes):
        if len(pts) < 3:
            return pts
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1], 0.75 * a[2] + 0.25 * b[2]))
            out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1], 0.25 * a[2] + 0.75 * b[2]))
        out.append(pts[-1])
        pts = out
    return pts


def simplify(points: list, min_dist: float = 0.6) -> list:
    if len(points) < 3:
        return points
    out = [points[0]]
    for p in points[1:-1]:
        q = out[-1]
        if math.hypot(p[0] - q[0], p[1] - q[1]) >= min_dist:
            out.append(p)
    out.append(points[-1])
    return out


def width_at(base: float, pressure: float, tool: str) -> float:
    if tool == "pen":
        return base * (0.35 + 0.95 * max(0.05, min(1.0, pressure)))
    if tool == "pencil":
        return base * (0.5 + 0.6 * max(0.05, min(1.0, pressure)))
    return base


def outline(points: list, base: float, tool: str) -> QPainterPath:
    """Contorno de largura variável (pressão), com pontas redondas."""
    path = QPainterPath()
    if not points:
        return path
    if tool == "marker":
        pen_path = QPainterPath(QPointF(points[0][0], points[0][1]))
        for p in points[1:]:
            pen_path.lineTo(p[0], p[1])
        if len(points) == 1:
            pen_path.lineTo(points[0][0] + 0.1, points[0][1])
        st = QPainterPathStroker()
        st.setWidth(base)
        st.setCapStyle(Qt.PenCapStyle.FlatCap)
        st.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return st.createStroke(pen_path)
    pts = smooth(points, 2 if len(points) > 4 else 0)
    if len(pts) == 1:
        r = width_at(base, pts[0][2], tool) / 2
        path.addEllipse(QPointF(pts[0][0], pts[0][1]), r, r)
        return path
    left, right = [], []
    n = len(pts)
    for i, p in enumerate(pts):
        a = pts[max(0, i - 1)]
        b = pts[min(n - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        r = width_at(base, p[2], tool) / 2
        left.append(QPointF(p[0] + nx * r, p[1] + ny * r))
        right.append(QPointF(p[0] - nx * r, p[1] - ny * r))
    poly = QPolygonF(left + right[::-1])
    path.addPolygon(poly)
    path.closeSubpath()
    r0 = width_at(base, pts[0][2], tool) / 2
    r1 = width_at(base, pts[-1][2], tool) / 2
    path.addEllipse(QPointF(pts[0][0], pts[0][1]), r0, r0)
    path.addEllipse(QPointF(pts[-1][0], pts[-1][1]), r1, r1)
    path.setFillRule(Qt.FillRule.WindingFill)
    return path


class StrokeItem(QGraphicsItem):
    def __init__(self, canvas, state: dict):
        super().__init__()
        self.canvas = canvas
        self.stroke_id = state["id"]
        self.data_state = copy.deepcopy(state)
        self._path = QPainterPath()
        self.setZValue(INK_Z)
        self.set_state(state)

    @property
    def tool(self) -> str:
        return self.data_state.get("tool") or "pen"

    @property
    def points(self) -> list:
        return self.data_state.get("points") or []

    def set_state(self, state: dict) -> None:
        self.data_state = copy.deepcopy(state)
        idx = self.canvas.page_index_of(state.get("pageID"))
        self.setPos(0, idx * self.canvas.page_h)
        self.rebuild()

    def state(self) -> dict:
        s = copy.deepcopy(self.data_state)
        if self.pos().x() != 0 or abs(self.pos().y() - self.canvas.page_index_of(s.get("pageID")) * self.canvas.page_h) > 0.01:
            # o traço foi movido (laço): grava os pontos já deslocados, na página onde está agora
            dy0 = self.canvas.page_index_of(s.get("pageID")) * self.canvas.page_h
            dx, dy = self.pos().x(), self.pos().y() - dy0
            pts = [[round(p[0] + dx, 2), round(p[1] + dy, 2), p[2]] for p in s["points"]]
            ys = [p[1] for p in pts]
            mid = (min(ys) + max(ys)) / 2 + dy0
            idx = self.canvas.page_at_y(mid)
            shift = (idx * self.canvas.page_h) - dy0
            s["points"] = [[p[0], round(p[1] - shift, 2), p[2]] for p in pts]
            s["pageID"] = self.canvas.page_id_at(idx)
        return s

    def rebuild(self) -> None:
        self.prepareGeometryChange()
        self._path = outline([tuple(p) for p in self.points], float(self.data_state.get("width") or 2), self.tool)

    def boundingRect(self) -> QRectF:
        return self._path.boundingRect().adjusted(-3, -3, 3, 3)

    def shape(self) -> QPainterPath:
        if self.tool == "marker":
            return self._path
        st = QPainterPathStroker()
        st.setWidth(6)
        return self._path.united(st.createStroke(self._path)) if len(self.points) < 400 else self._path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.data_state.get("color") or "#1F2933")
        if self.tool == "marker":
            color.setAlpha(110)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        elif self.tool == "pencil":
            color.setAlpha(205)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(self._path)
        if self.isSelected():
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(47, 111, 181, 160), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self._path.boundingRect())

    def scene_points(self) -> list[tuple[float, float]]:
        o = self.pos()
        return [(p[0] + o.x(), p[1] + o.y()) for p in self.points]

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.canvas.begin_change()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.canvas.end_change("Mover")

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self.canvas.editor is not None:
            self.canvas.editor.content_changed()
        return super().itemChange(change, value)


def new_stroke_state(page_id: str, tool: str, color: str, width: float, points: list) -> dict:
    return {"id": model.new_id(), "pageID": page_id, "tool": tool, "color": color, "width": round(width, 2),
            "points": [[round(p[0], 2), round(p[1], 2), round(p[2], 3)] for p in points]}


def erase(state: dict, cx: float, cy: float, radius: float, whole: bool) -> list[dict] | None:
    """Borracha num traço (coordenadas da página). Devolve None se o traço não foi tocado,
    [] se sumiu, ou os pedaços que sobraram."""
    pts = state.get("points") or []
    width = float(state.get("width") or 2)
    reach = radius + width / 2
    hit = [math.hypot(p[0] - cx, p[1] - cy) <= reach for p in pts]
    if not any(hit):
        # segmento passando entre dois pontos distantes
        for a, b in zip(pts, pts[1:]):
            if _seg_dist(cx, cy, a, b) <= reach:
                hit = None
                break
        else:
            return None
    if whole:
        return []
    if hit is None:
        hit = [False] * len(pts)
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            if _seg_dist(cx, cy, a, b) <= reach:
                hit[i] = hit[i + 1] = True
    pieces, cur = [], []
    for p, h in zip(pts, hit):
        if h:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = []
        else:
            cur.append(p)
    if len(cur) >= 2:
        pieces.append(cur)
    out = []
    for piece in pieces:
        s = copy.deepcopy(state)
        s["id"] = model.new_id()
        s["points"] = piece
        out.append(s)
    return out


def _seg_dist(px, py, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    ln = dx * dx + dy * dy
    t = 0.0 if ln == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ln))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)
