"""Régua (como a do Word), em cima da página: mostra as margens e os recuos do parágrafo onde está
o cursor e deixa travar o texto num ponto exato.

- Triângulo de cima: recuo da primeira linha.
- Triângulo de baixo: recuo do parágrafo (a primeira linha fica onde está — recuo deslocado).
- Retângulo embaixo: move os dois juntos.
- Triângulo da direita: recuo à direita.
- Clique na régua: parada de tabulação ali (a tecla Tab leva o texto até ela). Arraste para mover;
  arraste para fora da régua para tirar. Duplo clique numa parada também tira.

Vale para os parágrafos selecionados (ou o do cursor), num passo só de desfazer. Os valores andam
de 0,25 cm em 0,25 cm; com Alt, livremente. Números em centímetros a partir da margem esquerda."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QTextCursor, QTextOption
from PySide6.QtWidgets import QToolTip, QWidget

import theme

CM = 72 / 2.54           # unidades do texto (pontos) por centímetro
SNAP = CM / 4
H = 26
DEFAULT_TAB = 1.25 * CM  # tabulação padrão do Word


class Ruler(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setFixedHeight(H)
        self.setMouseTracking(True)
        self.setToolTip("")
        self.item = None
        self.geo = None            # dict com a geometria atual (cena)
        self.drag = None           # (o que, valor inicial)
        self.preview = None        # valores durante o arraste
        self._last_key = None

    # ------------------------------------------------------------------ dados do parágrafo
    def refresh(self, item) -> None:
        """Chamado pelo editor a cada mudança de cursor: só repinta se algo mudou."""
        geo = self._geometry(item) if item is not None else None
        key = None if geo is None else tuple(round(v, 2) if isinstance(v, float) else v for k, v in sorted(geo.items())
                                             if k not in ("tabs",)) + tuple(geo["tabs"])
        view_key = (self.editor.view.horizontalScrollBar().value(), round(self.editor.view.zoom(), 4), self.width())
        if (key, view_key) != self._last_key:
            self._last_key = (key, view_key)
            self.item, self.geo = item, geo
            self.update()

    def _geometry(self, item) -> dict | None:
        try:
            doc = item.document()
        except RuntimeError:
            return None
        if item.scene() is None or abs(item.sceneTransform().m12()) > 1e-6:
            return None              # sem régua em texto girado
        rf = doc.rootFrame().frameFormat()
        width = doc.textWidth() if doc.textWidth() > 0 else doc.pageSize().width()
        if width <= 0:
            width = doc.size().width()
        dm = doc.documentMargin()
        left = dm + rf.leftMargin() + rf.padding() + rf.border()
        right = width - dm - rf.rightMargin() - rf.padding() - rf.border()
        c = item.textCursor()
        bf = c.blockFormat()
        lst = c.currentList()
        list_indent = (lst.format().indent() if lst is not None else bf.indent()) * doc.indentWidth()
        p0 = item.mapToScene(QPointF(0, 0)).x()
        return {"origin": p0 + left, "width": right - left, "left": bf.leftMargin() + list_indent, "base": list_indent,
                "first": bf.textIndent(), "right": bf.rightMargin(), "page_left": item.mapToScene(QPointF(0, 0)).x(),
                "page_right": item.mapToScene(QPointF(width, 0)).x(),
                "tabs": [round(t.position + bf.leftMargin() + bf.textIndent(), 2) for t in bf.tabPositions()]}

    # ------------------------------------------------------------------ conversões
    def _px(self, scene_x: float) -> float:
        v = self.editor.view
        return v.mapFromScene(QPointF(scene_x, v.mapToScene(0, 0).y())).x() + v.x() - self.x()

    def _scene(self, px: float) -> float:
        v = self.editor.view
        inv, ok = v.viewportTransform().inverted()
        return inv.map(QPointF(px - v.x() + self.x(), 0)).x()

    def _units(self, px: float, free: bool) -> float:
        """Posição do mouse em pontos a partir da margem esquerda (arredondada a 0,25 cm)."""
        u = self._scene(px) - self.geo["origin"]
        return u if free else round(u / SNAP) * SNAP

    # ------------------------------------------------------------------ desenho
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#F5F6F8"))
        p.setPen(QColor("#E3E6EA"))
        p.drawLine(0, H - 1, self.width(), H - 1)
        g = self.geo
        if g is None:
            p.setPen(QColor(theme.MUTED))
            p.setFont(theme.ui_font(8))
            p.drawText(self.rect().adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter,
                       "Clique no texto para ver a régua do parágrafo")
            return
        vals = dict(g)
        if self.preview:
            vals.update(self.preview)
        o, w = g["origin"], g["width"]
        x0, x1 = self._px(g["page_left"]), self._px(g["page_right"])
        a, b = self._px(o), self._px(o + w)
        band = QRectF(x0, 4, x1 - x0, H - 9)
        p.fillRect(band, QColor("#E4E7EB"))                        # margens
        p.fillRect(QRectF(a, 4, b - a, H - 9), QColor("white"))    # área do texto
        # marcas: 0,25 cm curtas, 0,5 cm médias, números a cada centímetro
        scale = abs(self._px(o + CM) - a)
        p.setFont(QFont(theme.ui_font(7)))
        step = 1 if scale > 26 else 2 if scale > 14 else 5
        n_min = int(-(o - g["page_left"]) // CM) - 1
        n_max = int((g["page_right"] - o) // CM) + 1
        for n in range(n_min * 4, n_max * 4 + 1):
            ux = o + n * CM / 4
            if ux < g["page_left"] - 0.1 or ux > g["page_right"] + 0.1:
                continue
            x = self._px(ux)
            if n % 4 == 0:
                cm = abs(n // 4)
                if cm and cm % step == 0:
                    p.setPen(QColor("#6B7280"))
                    p.drawText(QRectF(x - 12, 5, 24, H - 11), Qt.AlignmentFlag.AlignCenter, str(cm))
            elif n % 2 == 0 and scale > 10:
                p.setPen(QPen(QColor("#9AA3AD"), 1))
                p.drawLine(QPointF(x, 12), QPointF(x, 16))
            elif scale > 22:
                p.setPen(QPen(QColor("#B8C0C8"), 1))
                p.drawLine(QPointF(x, 13), QPointF(x, 15))
        # paradas de tabulação
        for t in vals["tabs"]:
            self._tab_mark(p, self._px(o + t))
        # recuos
        first = self._px(o + vals["left"] + vals["first"])
        left = self._px(o + vals["left"])
        right = self._px(o + w - vals["right"])
        self._marker(p, first, down=True)
        self._marker(p, left, down=False)
        p.setBrush(QColor("white"))
        p.setPen(QPen(QColor("#8A94A0"), 1))
        p.drawRect(QRectF(left - 4.5, H - 7, 9, 4.5))
        self._marker(p, right, down=False)
        if self.drag and self.preview:
            kind = self.drag[0]
            val = {"first": vals["left"] + vals["first"], "left": vals["left"], "both": vals["left"],
                   "right": vals["right"], "tab": self.preview.get("tab_at", 0)}.get(kind, 0)
            p.setPen(QColor(theme.ACCENT))
            p.setFont(theme.ui_font(7, True))
            text = f"{val / CM:.2f} cm".replace(".", ",")
            x = {"first": first, "left": left, "both": left, "right": right}.get(kind, self._px(o + val))
            p.drawText(QRectF(x + 8, 0, 70, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _marker(self, p, x: float, down: bool) -> None:
        s = 5.0
        if down:
            poly = QPolygonF([QPointF(x - s, 2), QPointF(x + s, 2), QPointF(x, 2 + s * 1.3)])
        else:
            y = H - 8
            poly = QPolygonF([QPointF(x - s, y), QPointF(x + s, y), QPointF(x, y - s * 1.3)])
        p.setBrush(QColor("white"))
        p.setPen(QPen(QColor("#6B7280"), 1))
        p.drawPolygon(poly)

    def _tab_mark(self, p, x: float) -> None:
        p.setPen(QPen(QColor("#1F2933"), 1.6))
        path = QPainterPath(QPointF(x, H - 13))
        path.lineTo(x, H - 7)
        path.lineTo(x + 5, H - 7)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    # ------------------------------------------------------------------ mouse
    def _hit(self, pos: QPointF):
        g = self.geo
        o = g["origin"]
        first = self._px(o + g["left"] + g["first"])
        left = self._px(o + g["left"])
        right = self._px(o + g["width"] - g["right"])
        x, y = pos.x(), pos.y()
        if abs(x - first) <= 6 and y <= 10:
            return "first"
        if abs(x - left) <= 6 and y >= H - 8:
            return "both"
        if abs(x - left) <= 6 and y > 9:
            return "left"
        if abs(x - right) <= 6 and y > 9:
            return "right"
        for i, t in enumerate(g["tabs"]):
            if abs(x - self._px(o + t)) <= 5 and y > 9:
                return ("tab", i)
        return None

    def mouseMoveEvent(self, e):
        if self.geo is None:
            return
        pos = e.position()
        if self.drag is None:
            hit = self._hit(pos)
            tips = {"first": "Recuo da primeira linha", "left": "Recuo deslocado (as outras linhas)",
                    "both": "Recuo esquerdo (move os dois)", "right": "Recuo direito"}
            name = hit[0] if isinstance(hit, tuple) else hit
            self.setCursor(Qt.CursorShape.SizeHorCursor if hit else Qt.CursorShape.ArrowCursor)
            self.setToolTip("Parada de tabulação (arraste para fora para tirar)" if name == "tab" else tips.get(name, "")
                            or "Clique para pôr uma parada de tabulação")
            return
        free = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
        u = self._units(pos.x(), free)
        g = self.geo
        kind = self.drag[0]
        pv = {}
        if kind == "first":
            pv["first"] = max(-g["left"], min(g["width"] - g["right"] - 20, u) - g["left"])
        elif kind == "left":
            new_left = max(0.0, min(u, g["width"] - g["right"] - 20))
            pv["left"] = new_left
            pv["first"] = g["left"] + g["first"] - new_left       # a primeira linha fica onde estava
        elif kind == "both":
            new_left = max(0.0, min(u, g["width"] - g["right"] - 20))
            pv["left"] = new_left
            pv["first"] = max(-new_left, g["first"])
        elif kind == "right":
            pv["right"] = max(0.0, min(g["width"] - u, g["width"] - g["left"] - 20))
        elif kind == "tab":
            tabs = list(g["tabs"])
            out = pos.y() < -12 or pos.y() > H + 14
            if self.drag[1] is not None and self.drag[1] < len(tabs):
                tabs.pop(self.drag[1])
            if not out and 0 <= u <= g["width"]:
                tabs.append(u)
                pv["tab_at"] = u
            pv["tabs"] = sorted(tabs)
            self.setCursor(Qt.CursorShape.ForbiddenCursor if out else Qt.CursorShape.SizeHorCursor)
        self.preview = pv
        self.update()

    def mousePressEvent(self, e):
        if self.geo is None or e.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(e.position())
        if hit is None:
            u = self._units(e.position().x(), bool(e.modifiers() & Qt.KeyboardModifier.AltModifier))
            if 0 < u < self.geo["width"]:
                self.drag = ("tab", None)
                self.mouseMoveEvent(e)
            return
        self.drag = hit if isinstance(hit, tuple) else (hit, None)
        self.preview = {}

    def mouseReleaseEvent(self, e):
        if self.drag is None:
            return
        pv, self.preview, self.drag = self.preview or {}, None, None
        if pv:
            self.apply(pv)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.geo is None:
            return
        hit = self._hit(e.position())
        if isinstance(hit, tuple) and hit[0] == "tab":
            tabs = list(self.geo["tabs"])
            tabs.pop(hit[1])
            self.apply({"tabs": tabs})

    # ------------------------------------------------------------------ aplicar
    def apply(self, values: dict) -> None:
        """Grava os recuos e as tabulações nos parágrafos selecionados (um passo de desfazer)."""
        item, g = self.item, self.geo
        if item is None or g is None:
            return
        ed = self.editor
        doc = item.document()
        c = item.textCursor()
        start, end = c.selectionStart(), c.selectionEnd()
        block = doc.findBlock(start)
        ed.history.break_group()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        while block.isValid() and (block.position() <= end or block == doc.findBlock(start)):
            bc = QTextCursor(block)
            bf = block.blockFormat()
            lst = block.textList()
            base = (lst.format().indent() if lst is not None else bf.indent()) * doc.indentWidth()
            # o Qt conta as tabulações a partir do começo da primeira linha (recuo + primeira linha)
            old_start = bf.leftMargin() + bf.textIndent()
            if "left" in values:
                if lst is None:
                    bf.setIndent(0)
                    base = 0.0
                bf.setLeftMargin(max(0.0, values["left"] - base))
            if "first" in values:
                bf.setTextIndent(values["first"])
            if "right" in values:
                bf.setRightMargin(values["right"])
            new_start = bf.leftMargin() + bf.textIndent()
            # as tabulações ficam no mesmo lugar da régua, mesmo que o recuo mude
            tabs = values.get("tabs", [t.position + old_start for t in bf.tabPositions()])
            bf.setTabPositions([QTextOption.Tab(max(1.0, t - new_start), QTextOption.TabType.LeftTab)
                                for t in tabs if t - new_start > 0.5])
            bc.setBlockFormat(bf)
            if block.position() + block.length() > end:
                break
            block = block.next()
        cur.endEditBlock()
        ed.history.break_group()
        ed.content_changed()
        self._last_key = None
        self.refresh(item)
        ed._refocus(item)
