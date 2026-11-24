"""Canvas paginado da nota: páginas A4 (ou do tamanho escolhido) uma embaixo da outra, o texto
principal com as margens do Word paginado pelo próprio Qt, objetos por cima do texto e a tinta
por cima de tudo.

As páginas ficam encostadas na cena (página i começa em ``i × altura``); uma faixa da cor da
mesa, desenhada por cima, faz o espaço entre elas. O texto nunca chega a essa faixa porque ela
cai dentro das margens de cima e de baixo."""

from __future__ import annotations

import copy
import math
from contextlib import contextmanager

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QTextBlockFormat,
                           QTextCursor, QTextOption)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

import items as items_mod
import model
import theme
from ink import INK_Z, StrokeItem
from textitem import EditableText

GAP = 16.0          # espaço visível entre as páginas (pontos)


class StoryItem(EditableText):
    """Texto principal da nota (a área do Word)."""

    def __init__(self, canvas):
        super().__init__(None, owner=None)
        self.canvas = canvas
        self.setZValue(1)

    def paint(self, painter, option, widget=None):
        # sem o retângulo de foco do Qt em volta do texto
        from PySide6.QtWidgets import QStyle
        option.state &= ~QStyle.StateFlag.State_HasFocus
        option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, option, widget)

    def mousePressEvent(self, event):
        ed = self.canvas.editor
        if ed is not None and event.button() == Qt.MouseButton.LeftButton and not event.modifiers() \
                and ed.click_off_story(event.scenePos()):
            event.accept()
            return
        if ed is not None:
            ed.story_pressed()
        super().mousePressEvent(event)

    def text_region(self) -> QRectF:
        """Onde o clique vai para o texto da nota: da primeira linha até uma linha abaixo da
        última, entre as margens. Fora disso o clique abre uma caixa de texto."""
        c = self.canvas
        m = c._text_margins
        doc = self.document()
        layout = doc.documentLayout()
        # só onde já há texto (com nota vazia, a primeira linha); fora disso, caixa no clique
        block = doc.lastBlock()
        while block.isValid() and block != doc.firstBlock() and not block.text().strip():
            block = block.previous()
        line = QFontMetricsF(doc.defaultFont()).lineSpacing()
        bottom = max(layout.blockBoundingRect(block).bottom(), m["top"] + line + 4)
        return self.mapRectToScene(QRectF(m["left"] - 6, 0, c.page_w - m["left"] - m["right"] + 12, bottom))


class PageItem(QGraphicsItem):
    """Folha: papel (liso, caderno, quadriculado, xadrez), página de PDF por baixo, cabeçalho,
    rodapé e número da página."""

    def __init__(self, canvas, index: int):
        super().__init__()
        self.canvas = canvas
        self.index = index
        self.setZValue(-100)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        c = self.canvas
        return QRectF(-8, self.index * c.page_h - 8, c.page_w + 16, c.page_h + 16)

    def paint(self, painter: QPainter, option, widget=None):
        c = self.canvas
        top = self.index * c.page_h
        rect = QRectF(0, top, c.page_w, c.page_h)
        doc = c.doc
        canvas = doc["canvas"]
        simple = canvas.get("simpleNote")
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not c.exporting:
            painter.setPen(Qt.PenStyle.NoPen)
            for i, alpha in enumerate((18, 10, 5)):
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRect(rect.adjusted(-1 - i, -1 - i + GAP / 2, 1 + i, 1 + i + 1 - GAP / 2))
        painter.fillRect(rect, QColor("#FFF7C2") if simple else QColor("white"))
        page = doc["pages"][self.index] if self.index < len(doc["pages"]) else {}
        bg = page.get("background")
        if bg and bg.get("asset"):
            views = c.views()
            zoom = views[0].transform().m11() if views else 1.0
            img = c.assets.pdf_page(bg["asset"], int(bg.get("page") or 0), int(c.page_w * max(1.0, zoom) * 1.4))
            if img is not None:
                pw, ph = c.assets.pdf_page_size(bg["asset"], int(bg.get("page") or 0))
                scale = min(c.page_w / pw, c.page_h / ph)
                tw, th = pw * scale, ph * scale
                painter.drawImage(QRectF((c.page_w - tw) / 2, top + (c.page_h - th) / 2, tw, th), img)
        paper = page.get("paper") or canvas.get("paper")
        if paper and paper.get("kind") not in (None, "plain"):
            self.paint_paper(painter, rect, paper, simple)
        if simple:
            painter.fillRect(QRectF(0, top, c.page_w, 18), QColor("#8B5E3C"))
        self.paint_bands(painter, top)

    def paint_paper(self, painter, rect: QRectF, paper: dict, simple: bool):
        c = self.canvas
        kind = paper.get("kind")
        spacing = max(0.3 * model.CM, min(2 * model.CM, float(paper.get("spacing") or model.RULED_LINE)))
        area = QRectF(rect)
        half = paper.get("half")
        if half == "top":
            area.setHeight(rect.height() / 2)
        elif half == "bottom":
            area.setTop(rect.top() + rect.height() / 2)
        painter.save()
        painter.setClipRect(area)
        if kind == "ruled":
            m = model.text_margins(c.doc)
            whole = not half and not (c.doc["pages"][self.index].get("paper") if self.index < len(c.doc["pages"]) else None)
            line_color = QColor("#9DB8D6") if simple else QColor("#B9CDE3")
            painter.setPen(QPen(line_color, 0.8))
            if whole:
                # a pauta acompanha as linhas do texto: cada linha ocupa uma faixa
                y = rect.top() + m["top"] + c.ruled_baseline + 1.2
                while y > rect.top() + spacing:
                    y -= spacing
            else:
                y = area.top() + spacing
            while y < area.bottom() - 2:
                if y > area.top() + 4:
                    painter.drawLine(QPointF(area.left() + 6, y), QPointF(area.right() - 6, y))
                y += spacing
            if simple or whole:
                painter.setPen(QPen(QColor("#E58A8A"), 1))
                x = m["left"] - 8
                painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        elif kind == "grid":
            painter.setPen(QPen(QColor("#C9D6E4"), 0.6))
            x = area.left() + spacing
            while x < area.right():
                painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
                x += spacing
            y = area.top() + spacing
            while y < area.bottom():
                painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
                y += spacing
        elif kind == "checker":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#EEF2F6"))
            row = 0
            y = area.top()
            while y < area.bottom():
                col = 0
                x = area.left()
                while x < area.right():
                    if (row + col) % 2 == 0:
                        painter.drawRect(QRectF(x, y, spacing, spacing))
                    x += spacing
                    col += 1
                y += spacing
                row += 1
        painter.restore()

    def paint_bands(self, painter, top: float):
        c = self.canvas
        canvas = c.doc["canvas"]
        m = canvas.get("margins") or model.WORD_MARGINS
        (h0, h1), (f0, f1) = model.header_band_rect_y(c.doc)
        left, right = m["left"], c.page_w - m["right"]
        for band, y0, y1 in ((canvas.get("header"), h0, h1), (canvas.get("footer"), f0, f1)):
            if not model.header_has_content(band):
                continue
            r = QRectF(left, top + y0, right - left, y1 - y0)
            align = band.get("alignment") or "center"
            flag = {"leading": Qt.AlignmentFlag.AlignLeft, "trailing": Qt.AlignmentFlag.AlignRight}.get(align, Qt.AlignmentFlag.AlignHCenter)
            img = c.assets.image(band.get("image"), 600) if band.get("image") else None
            if img is None and band.get("pdf"):
                img = c.assets.pdf_page(band["pdf"], 0, 600)
            text_rect = QRectF(r)
            if img is not None:
                scale = min(r.height() / img.height(), r.width() / img.width())
                iw, ih = img.width() * scale, img.height() * scale
                if align == "trailing":
                    ir = QRectF(r.right() - iw, r.top() + (r.height() - ih) / 2, iw, ih)
                    text_rect.setRight(ir.left() - 8)
                elif align == "center" and not band.get("text"):
                    ir = QRectF(r.center().x() - iw / 2, r.top() + (r.height() - ih) / 2, iw, ih)
                else:
                    ir = QRectF(r.left(), r.top() + (r.height() - ih) / 2, iw, ih)
                    text_rect.setLeft(ir.right() + 8)
                painter.drawImage(ir, img)
            if band.get("text"):
                f = QFont(c.default_family)
                f.setPointSizeF(float(band.get("fontSize") or 10))
                painter.setFont(f)
                painter.setPen(QColor("#4B5563"))
                painter.drawText(text_rect, flag | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, band["text"])
        numbers = canvas.get("pageNumbers")
        if numbers:
            start = int(numbers.get("start") or 1)
            if numbers.get("skipFirst") and self.index == 0:
                return
            total = c.page_count() + start - 1
            text = model.page_number_text(numbers.get("format") or "n", self.index + start, total)
            f = QFont(c.default_family)
            f.setPointSizeF(float(numbers.get("size") or 11))
            painter.setFont(f)
            painter.setPen(QColor("#374151"))
            y0, y1 = (h0, h1) if numbers.get("position") == "header" else (f0, f1)
            align = numbers.get("alignment") or "center"
            flag = {"leading": Qt.AlignmentFlag.AlignLeft, "trailing": Qt.AlignmentFlag.AlignRight}.get(align, Qt.AlignmentFlag.AlignHCenter)
            painter.drawText(QRectF(left, top + y0, right - left, y1 - y0), flag | Qt.AlignmentFlag.AlignVCenter, text)


class GapItem(QGraphicsItem):
    """Faixa da cor da mesa entre as páginas (por cima de tudo, sem pegar cliques)."""

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.setZValue(9000)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        c = self.canvas
        return QRectF(-4000, -GAP, c.page_w + 8000, c.page_count() * c.page_h + 2 * GAP)

    def paint(self, painter, option, widget=None):
        if self.canvas.exporting:
            return
        c = self.canvas
        desk = QColor(theme.DESK)
        for i in range(1, c.page_count()):
            y = i * c.page_h
            painter.fillRect(QRectF(-4000, y - GAP / 2, c.page_w + 8000, GAP), desk)
            painter.fillRect(QRectF(0, y - GAP / 2 - 1, c.page_w, 1), QColor(0, 0, 0, 22))
            painter.fillRect(QRectF(0, y + GAP / 2, c.page_w, 1), QColor(0, 0, 0, 16))


class GuideItem(QGraphicsItem):
    """Linhas de alinhamento ao arrastar (bordas e centros de outros objetos e da página) e a
    linha tracejada quando um objeto invade o cabeçalho ou o rodapé."""

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.lines: list[tuple[QPointF, QPointF]] = []
        self.warning: QRectF | None = None
        self.setZValue(9500)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        c = self.canvas
        return QRectF(-200, -200, c.page_w + 400, c.page_count() * c.page_h + 400)

    def set(self, lines, warning=None):
        self.lines = lines
        self.warning = warning
        self.update()

    def paint(self, painter, option, widget=None):
        if self.canvas.exporting:
            return
        views = self.canvas.views()
        s = 1.0 / (views[0].transform().m11() if views else 1.0)
        painter.setPen(QPen(QColor("#E5484D"), 1 * s))
        for a, b in self.lines:
            painter.drawLine(a, b)
        if self.warning is not None:
            painter.setPen(QPen(QColor("#6B7280"), 1 * s, Qt.PenStyle.DashLine))
            painter.drawLine(self.warning.topLeft(), self.warning.topRight())
            painter.setFont(theme.ui_font(8))
            painter.drawText(QRectF(self.warning.left(), self.warning.top() - 14 * s, self.warning.width(), 12 * s),
                             Qt.AlignmentFlag.AlignCenter, "O objeto está invadindo o cabeçalho ou o rodapé")


class CanvasScene(QGraphicsScene):
    pagesChanged = Signal()

    def __init__(self, doc: dict, assets, editor=None, resolver=None, default_font=None):
        super().__init__()
        self.doc = doc
        self.assets = assets
        self.editor = editor
        self.resolver = resolver
        self.exporting = False
        self.snapping = True
        self.page_w, self.page_h = model.page_size(doc)
        family, size = default_font or (theme.default_text_family(), 12.0)
        self.default_family = family
        self.default_size = float(size)
        self.items_by_id: dict[str, items_mod.BlockItem] = {}
        self.strokes_by_id: dict[str, StrokeItem] = {}
        self.connectors: dict[str, items_mod.ConnectorItem] = {}
        self.graveyard: dict[str, object] = {}
        self.page_items: list[PageItem] = []
        self._pending = None
        self._dragged: set = set()
        self.ruled_baseline = 0.8 * model.RULED_LINE
        self.setBackgroundBrush(QColor(theme.DESK))
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)

        self.story = StoryItem(self)
        self.addItem(self.story)
        self.gap = GapItem(self)
        self.addItem(self.gap)
        self.guides = GuideItem(self)
        self.addItem(self.guides)
        self.setup_story()
        for state in sorted(doc.get("blocks", []), key=lambda b: b.get("z", 0)):
            self.add_block(state)
        for state in doc.get("strokes", []):
            self.add_stroke(state)
        for state in doc.get("relations", []):
            self.add_connector(state)
        self.story.document().documentLayout().documentSizeChanged.connect(lambda *_: self.update_pages())
        self.story.document().contentsChange.connect(self._story_changed)
        self.update_pages()

    # ------------------------------------------------------------------ texto da nota
    def setup_story(self) -> None:
        doc = self.story.document()
        f = QFont(self.default_family)
        f.setPointSizeF(self.default_size)
        doc.setDefaultFont(f)
        doc.setDocumentMargin(0)
        self.story.setDefaultTextColor(QColor("#1F2933"))
        opt = doc.defaultTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        story = self.doc.get("story") or {}
        if story.get("html"):
            doc.setHtml(story["html"])
        else:
            doc.setPlainText(story.get("text") or "")
        self.apply_page_format()
        doc.clearUndoRedoStacks()

    def apply_page_format(self) -> None:
        """Tamanho da página e margens do texto (com cabeçalho e rodapé)."""
        self.page_w, self.page_h = model.page_size(self.doc)
        doc = self.story.document()
        m = model.text_margins(self.doc)
        if self.ruled_text():
            # a primeira linha começa numa faixa da pauta
            L = model.RULED_LINE
            m["top"] = math.ceil(m["top"] / L) * L if not self.doc["canvas"].get("simpleNote") else m["top"]
        doc.setPageSize(QSizeF(self.page_w, self.page_h))
        fmt = doc.rootFrame().frameFormat()
        fmt.setTopMargin(m["top"])
        fmt.setBottomMargin(m["bottom"])
        fmt.setLeftMargin(m["left"])
        fmt.setRightMargin(m["right"])
        doc.rootFrame().setFrameFormat(fmt)
        self._text_margins = m
        if self.ruled_text():
            self.apply_ruled_lines()
        self.update_pages()
        for p in self.page_items:
            p.update()

    def ruled_text(self) -> bool:
        paper = self.doc["canvas"].get("paper") or {}
        return paper.get("kind") == "ruled"

    def apply_ruled_lines(self, first_block=None, last_block=None) -> None:
        """Papel caderno na nota toda: cada linha do texto ocupa uma faixa de 0,8 cm (duas ou
        mais para letras grandes), sem espaço extra entre linhas."""
        L = float((self.doc["canvas"].get("paper") or {}).get("spacing") or model.RULED_LINE)
        doc = self.story.document()
        block = first_block or doc.begin()
        end = last_block.next() if last_block is not None else None
        cursor = QTextCursor(doc)
        was = doc.isUndoRedoEnabled()
        doc.setUndoRedoEnabled(False)
        try:
            while block.isValid() and block != end:
                biggest = self.default_size
                it = block.begin()
                while not it.atEnd():
                    frag = it.fragment()
                    if frag.isValid():
                        size = frag.charFormat().font().pointSizeF()
                        if size > 0:
                            biggest = max(biggest, size)
                    it += 1
                bands = 1 if biggest <= 20 else 2 if biggest <= 40 else 3
                want = L * bands
                bf = block.blockFormat()
                if abs(bf.lineHeight() - want) > 0.01 or bf.lineHeightType() != 2 or bf.topMargin() or bf.bottomMargin():
                    cursor.setPosition(block.position())
                    nf = QTextBlockFormat()
                    nf.setLineHeight(want, 2)       # FixedHeight
                    nf.setTopMargin(0)
                    nf.setBottomMargin(0)
                    cursor.mergeBlockFormat(nf)
                block = block.next()
        finally:
            doc.setUndoRedoEnabled(was)
        fm = QFontMetricsF(doc.defaultFont())
        ratio = fm.ascent() / max(1e-6, fm.ascent() + fm.descent())
        self.ruled_baseline = L * ratio

    def _story_changed(self, position: int, removed: int, added: int) -> None:
        if self.ruled_text():
            doc = self.story.document()
            first = doc.findBlock(position)
            last = doc.findBlock(position + added)
            QTimer.singleShot(0, lambda: self.apply_ruled_lines(doc.findBlock(position), doc.findBlock(position + added)))
        if self.editor is not None:
            self.editor.content_changed()

    def story_page_count(self) -> int:
        return max(1, self.story.document().pageCount())

    def page_count(self) -> int:
        return len(self.page_items) or len(self.doc["pages"])

    def update_pages(self) -> None:
        story_pages = self.story_page_count()
        pages = self.doc["pages"]
        changed = False
        while len(pages) < story_pages:
            pages.append(model.new_page(auto=True))
            changed = True
        # páginas geradas pelo texto que ficaram vazias saem (só se não tiverem mais nada)
        while len(pages) > story_pages and pages[-1].get("auto") and not self._page_has_content(pages[-1]["id"]):
            pages.pop()
            changed = True
        n = len(pages)
        while len(self.page_items) < n:
            item = PageItem(self, len(self.page_items))
            self.addItem(item)
            self.page_items.append(item)
        while len(self.page_items) > n:
            self.removeItem(self.page_items.pop())
        pad = 16.0
        self.setSceneRect(QRectF(-pad, -GAP - 24, self.page_w + 2 * pad, n * self.page_h + GAP + 80))
        self.gap.prepareGeometryChange()
        self.guides.prepareGeometryChange()
        for p in self.page_items:
            p.prepareGeometryChange()
            p.update()
        if changed or True:
            self.pagesChanged.emit()

    def _page_has_content(self, page_id: str) -> bool:
        first = self.doc["pages"][0]["id"]
        idx = self.page_index_of(page_id)
        for it in self.items_by_id.values():
            if self.page_at_y(it.mapToScene(QPointF(it.w / 2, it.h / 2)).y()) == idx:
                return True
        for st in self.strokes_by_id.values():
            if (st.data_state.get("pageID") or first) == page_id:
                return True
        page = self.doc["pages"][idx]
        return bool(page.get("background") or page.get("paper"))

    # ------------------------------------------------------------------ páginas
    def page_index_of(self, page_id: str | None) -> int:
        if not page_id:
            return 0
        for i, p in enumerate(self.doc["pages"]):
            if p["id"] == page_id:
                return i
        return 0

    def page_id_at(self, index: int) -> str:
        pages = self.doc["pages"]
        return pages[max(0, min(index, len(pages) - 1))]["id"]

    def page_at_y(self, y: float) -> int:
        n = max(1, len(self.doc["pages"]))
        return max(0, min(n - 1, int(y // self.page_h)))

    def grid_at(self, index: int, y: float):
        """(lado do quadrado, origem y na página) se o ponto (y na página) cai em papel
        quadriculado; senão None."""
        pages = self.doc["pages"]
        page = pages[index] if 0 <= index < len(pages) else {}
        paper = page.get("paper") or self.doc["canvas"].get("paper")
        if not paper or paper.get("kind") != "grid":
            return None
        spacing = max(0.3 * model.CM, min(2 * model.CM, float(paper.get("spacing") or model.RULED_LINE)))
        half = paper.get("half")
        if half == "top":
            return (spacing, 0.0) if y < self.page_h / 2 else None
        if half == "bottom":
            return (spacing, self.page_h / 2) if y >= self.page_h / 2 else None
        return spacing, 0.0

    def page_rect(self, index: int) -> QRectF:
        return QRectF(0, index * self.page_h, self.page_w, self.page_h)

    def to_page(self, scene_pt: QPointF) -> tuple[str, float, float]:
        idx = self.page_at_y(scene_pt.y())
        return self.page_id_at(idx), scene_pt.x(), scene_pt.y() - idx * self.page_h

    def add_page(self, after: int | None = None) -> int:
        page = model.new_page()
        idx = len(self.doc["pages"]) if after is None else after + 1
        # páginas abaixo descem junto com seus objetos
        self.doc["pages"].insert(idx, page)
        self.relayout_objects()
        self.update_pages()
        return idx

    def delete_page(self, index: int) -> None:
        pages = self.doc["pages"]
        if len(pages) <= 1 or index >= len(pages):
            return
        page_id = pages[index]["id"]
        for bid, it in list(self.items_by_id.items()):
            if it.data_state.get("pageID") == page_id or (index == 0 and not it.data_state.get("pageID")):
                self.remove_block(bid)
        for sid, st in list(self.strokes_by_id.items()):
            if st.data_state.get("pageID") == page_id:
                self.remove_stroke(sid)
        pages.pop(index)
        if index == 0:
            # a 1ª página tem o id da nota; os objetos da nova 1ª página continuam nela
            pass
        self.relayout_objects()
        self.update_pages()

    def relayout_objects(self) -> None:
        """Reposiciona objetos e traços pelas páginas (depois de incluir ou tirar páginas)."""
        for it in self.items_by_id.values():
            it.set_state(it.data_state)
        for st in self.strokes_by_id.values():
            st.set_state(st.data_state)
        self.refresh_connectors()

    # ------------------------------------------------------------------ objetos
    def add_block(self, state: dict):
        old = self.graveyard.pop(state["id"], None)
        if old is not None:
            old.set_state(state)
            item = old
        else:
            item = items_mod.make_item(self, state)
        if item.scene() is not self:
            self.addItem(item)
        self.items_by_id[state["id"]] = item
        return item

    def remove_block(self, block_id: str) -> None:
        item = self.items_by_id.pop(block_id, None)
        if item is None:
            return
        if self.editor is not None:
            self.editor.block_removed(item)
        item.setSelected(False)
        self.removeItem(item)
        self.graveyard[block_id] = item
        for rid, conn in list(self.connectors.items()):
            if block_id in (conn.data_state.get("sourceID"), conn.data_state.get("targetID")):
                self.remove_connector(rid)

    def add_stroke(self, state: dict):
        item = self.graveyard.pop("s:" + state["id"], None)
        if item is not None:
            item.set_state(state)
        else:
            item = StrokeItem(self, state)
        if item.scene() is not self:
            self.addItem(item)
        self.strokes_by_id[state["id"]] = item
        return item

    def remove_stroke(self, stroke_id: str) -> None:
        item = self.strokes_by_id.pop(stroke_id, None)
        if item is not None:
            item.setSelected(False)
            self.removeItem(item)
            self.graveyard["s:" + stroke_id] = item

    def add_connector(self, state: dict):
        item = items_mod.ConnectorItem(self, state)
        self.addItem(item)
        self.connectors[state["id"]] = item
        return item

    def remove_connector(self, rel_id: str) -> None:
        item = self.connectors.pop(rel_id, None)
        if item is not None:
            self.removeItem(item)

    def refresh_connectors(self, block_id: str | None = None) -> None:
        for conn in self.connectors.values():
            if block_id is None or block_id in (conn.data_state.get("sourceID"), conn.data_state.get("targetID")):
                conn.refresh()

    def next_z(self) -> int:
        zs = [int(it.zValue() - 10) for it in self.items_by_id.values()]
        return (max(zs) + 1) if zs else 1

    def raise_on_drag(self, item) -> None:
        self._dragged = {it for it in self.selectedItems() if isinstance(it, items_mod.BlockItem)} | {item}
        self._drag_start = {id(it): QPointF(it.pos()) for it in self._dragged}

    def resolve_note(self, doc_id: str | None):
        return self.resolver(doc_id) if (self.resolver and doc_id) else None

    # ------------------------------------------------------------------ alinhamento
    def snap(self, item, value: QPointF) -> QPointF:
        threshold = 5.0 / max(0.2, self.views()[0].transform().m11() if self.views() else 1.0)
        w, h = item.w, item.h
        if abs(item.rotation()) > 0.1:
            return value
        xs_item = [value.x(), value.x() + w / 2, value.x() + w]
        ys_item = [value.y(), value.y() + h / 2, value.y() + h]
        idx = self.page_at_y(value.y() + h / 2)
        top = idx * self.page_h
        m = self._text_margins if hasattr(self, "_text_margins") else model.WORD_MARGINS
        cand_x = [0, self.page_w / 2, self.page_w, m["left"], self.page_w - m["right"]]
        cand_y = [top + self.page_h / 2, top + m["top"], top + self.page_h - m["bottom"]]
        for other in self.items_by_id.values():
            if other is item or abs(other.rotation()) > 0.1:
                continue
            p = other.pos()
            if abs(p.y() + other.h / 2 - (value.y() + h / 2)) > self.page_h:
                continue
            cand_x += [p.x(), p.x() + other.w / 2, p.x() + other.w]
            cand_y += [p.y(), p.y() + other.h / 2, p.y() + other.h]
        dx = dy = None
        gx = gy = None
        for i, xi in enumerate(xs_item):
            for c in cand_x:
                if abs(c - xi) <= threshold and (dx is None or abs(c - xi) < abs(dx)):
                    dx, gx = c - xi, c
        for i, yi in enumerate(ys_item):
            for c in cand_y:
                if abs(c - yi) <= threshold and (dy is None or abs(c - yi) < abs(dy)):
                    dy, gy = c - yi, c
        new = QPointF(value.x() + (dx or 0), value.y() + (dy or 0))
        lines = []
        if gx is not None:
            lines.append((QPointF(gx, top), QPointF(gx, top + self.page_h)))
        if gy is not None:
            lines.append((QPointF(0, gy), QPointF(self.page_w, gy)))
        self.guides.set(lines, self._band_warning(new, w, h))
        return new

    def _band_warning(self, pos: QPointF, w: float, h: float):
        canvas = self.doc["canvas"]
        if not (model.header_has_content(canvas.get("header")) or model.header_has_content(canvas.get("footer"))
                or canvas.get("pageNumbers")):
            return None
        idx = self.page_at_y(pos.y() + h / 2)
        top = idx * self.page_h
        m = self._text_margins
        y0, y1 = pos.y() - top, pos.y() + h - top
        if y0 < m["top"] - 4 and (model.header_has_content(canvas.get("header")) or
                                  (canvas.get("pageNumbers") or {}).get("position") == "header"):
            return QRectF(0, top + m["top"], self.page_w, 1)
        if y1 > self.page_h - m["bottom"] + 4:
            return QRectF(0, top + self.page_h - m["bottom"], self.page_w, 1)
        return None

    def clear_guides(self) -> None:
        self.guides.set([], None)

    def item_moved(self, item) -> None:
        self.refresh_connectors(getattr(item, "block_id", None))

    # ------------------------------------------------------------------ desfazer
    def snapshot(self) -> dict:
        snap = {}
        for bid, it in self.items_by_id.items():
            snap["b:" + bid] = it.state()
        for sid, st in self.strokes_by_id.items():
            snap["s:" + sid] = st.state()
        for rid, c in self.connectors.items():
            snap["r:" + rid] = c.state()
        snap["canvas"] = copy.deepcopy(self.doc["canvas"])
        snap["pages"] = copy.deepcopy([{k: v for k, v in p.items()} for p in self.doc["pages"]])
        snap["title"] = self.doc.get("title")
        return snap

    def begin_change(self) -> None:
        if self._pending is None:
            self._pending = self.snapshot()

    def end_change(self, label: str) -> None:
        before, self._pending = self._pending, None
        if before is None:
            return
        if self._dragged:
            moved = [it for it in self._dragged if it.scene() is self and
                     (it.pos() - self._drag_start.get(id(it), it.pos())).manhattanLength() > 0.5]
            self._dragged = set()
            if moved:
                z = self.next_z()
                for it in sorted(moved, key=lambda i: i.zValue()):
                    it.setZValue(10 + z)
                    z += 1
                self.refresh_connectors()
        self._commit(before, label)

    def _commit(self, before: dict, label: str) -> None:
        after = self.snapshot()
        diff = {}
        for key in set(before) | set(after):
            a, b = before.get(key), after.get(key)
            if a != b:
                diff[key] = (a, b)
        # páginas geradas pelo texto não entram sozinhas no desfazer
        if set(diff) == {"pages"} and label in ("Mover", "Redimensionar"):
            return
        if diff and self.editor is not None:
            self.editor.history.push_delta(label, diff)
            self.editor.content_changed()

    @contextmanager
    def change(self, label: str):
        saved = self._pending
        self._pending = None
        before = self.snapshot()
        try:
            yield
        finally:
            self._commit(before, label)
            self._pending = saved

    def apply_states(self, states: dict) -> None:
        order = sorted(states, key=lambda k: (0 if k in ("canvas", "pages", "title") else 1 if k.startswith("b:") else
                                              2 if k.startswith("s:") else 3, k))
        relayout = False
        for key in order:
            state = states[key]
            if key == "canvas":
                self.doc["canvas"] = copy.deepcopy(state)
                relayout = True
            elif key == "pages":
                self.doc["pages"] = copy.deepcopy(state)
                relayout = True
            elif key == "title":
                self.doc["title"] = state
                if self.editor is not None:
                    self.editor.title_changed_externally()
            elif key.startswith("b:"):
                bid = key[2:]
                if state is None:
                    self.remove_block(bid)
                elif bid in self.items_by_id:
                    self.items_by_id[bid].set_state(state)
                else:
                    self.add_block(state)
            elif key.startswith("s:"):
                sid = key[2:]
                if state is None:
                    self.remove_stroke(sid)
                elif sid in self.strokes_by_id:
                    self.strokes_by_id[sid].set_state(state)
                else:
                    self.add_stroke(state)
            elif key.startswith("r:"):
                rid = key[2:]
                if state is None:
                    self.remove_connector(rid)
                elif rid in self.connectors:
                    self.connectors[rid].set_state(state)
                else:
                    self.add_connector(state)
        if relayout:
            self.apply_page_format()
            self.relayout_objects()
        self.refresh_connectors()

    # ------------------------------------------------------------------ gravar
    def serialize(self) -> dict:
        doc = self.doc
        text = self.story.document().toPlainText()
        doc["story"] = {"html": self.story.document().toHtml() if text.strip() or self._story_has_objects() else "",
                        "text": text}
        doc["blocks"] = [it.state() for it in sorted(self.items_by_id.values(), key=lambda i: i.zValue())]
        doc["strokes"] = [st.state() for st in self.strokes_by_id.values()]
        doc["relations"] = [c.state() for c in self.connectors.values()]
        return doc

    def _story_has_objects(self) -> bool:
        return len(self.story.document().rootFrame().childFrames()) > 0

    # ------------------------------------------------------------------ imagens
    def render_page(self, index: int, width_px: int, background: bool = True) -> QImage:
        rect = self.page_rect(index)
        scale = width_px / rect.width()
        img = QImage(int(width_px), int(rect.height() * scale), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("white"))
        selected = self.selectedItems()
        for it in selected:
            it.setSelected(False)
        self.exporting = True
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.render(p, QRectF(0, 0, img.width(), img.height()), rect)
        p.end()
        self.exporting = False
        for it in selected:
            it.setSelected(True)
        return img
