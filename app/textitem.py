"""Texto editável dentro do canvas (o texto da nota e o de caixas, post-its, formas e tabelas).
Desfazer e refazer passam pelo histórico único do editor."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainterPath, QPen, QRegion, QTextCursor
from PySide6.QtWidgets import QGraphicsTextItem

CHECK_GRAY = QColor("#8E8E93")
CHECK_ON = QColor("#2E6FB7")


class EditableText(QGraphicsTextItem):
    def __init__(self, parent=None, owner=None):
        super().__init__(parent)
        self.owner = owner                      # BlockItem dono da caixa; None no texto da nota
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.document().setUndoRedoEnabled(True)
        self.document().undoCommandAdded.connect(self._undo_added)
        self.setOpenExternalLinks(False)
        opt = self.document().defaultTextOption()
        opt.setTabStopDistance(1.25 * 72 / 2.54)        # tabulação padrão do Word: 1,25 cm
        self.document().setDefaultTextOption(opt)

    issues: list = []            # trechos apontados pela revisão (sublinhado vermelho)
    current_issue = None

    # ------------------------------------------------------------------ caixinhas da lista de tarefas
    def check_items(self, area: QRectF | None = None) -> list:
        """(bloco, retângulo da caixinha) dos itens da lista de tarefas (só os visíveis em ``area``)."""
        import textfmt
        doc = self.document()
        out = []
        for lst in {b.textList() for b in self._list_blocks()}:
            for i in range(lst.count()):
                block = lst.item(i)
                if block.blockFormat().marker() == textfmt.NO_MARKER:
                    continue
                r = textfmt.checkbox_rect(self, block)
                if r is not None and (area is None or area.intersects(r.adjusted(-30, -4, 4, 4))):
                    out.append((block, r))
        return out

    def _list_blocks(self):
        doc = self.document()
        frames = [doc.rootFrame()]
        # basta um bloco de cada lista: as listas do documento ficam nos objetos do documento
        seen = []
        b = doc.firstBlock()
        while b.isValid():
            if b.textList() is not None and b.textList() not in [x.textList() for x in seen]:
                seen.append(b)
            b = b.next()
        return seen

    def check_at(self, pos: QPointF):
        for block, r in self.check_items(QRectF(pos.x() - 1, pos.y() - 1, 2, 2)):
            if r.adjusted(-4, -4, 4, 4).contains(pos):
                return block
        return None

    def paint(self, painter, option, widget=None):
        checks = self.check_items(QRectF(option.exposedRect)) if self.document().blockCount() < 4000 else []
        if checks:
            # a caixinha padrão do Qt (com um X) fica de fora; no lugar, uma caixinha arredondada
            full = QRegion(self.boundingRect().toAlignedRect().adjusted(-200, -10, 10, 10))
            for _, r in checks:
                full -= QRegion(r.adjusted(-r.width() * 0.6, -3, r.width() * 0.25, 3).toAlignedRect())
            painter.save()
            painter.setClipRegion(full, Qt.ClipOperation.IntersectClip)
            super().paint(painter, option, widget)
            painter.restore()
            self._paint_checks(painter, checks)
        else:
            super().paint(painter, option, widget)
        if self.issues:
            import proofread
            proofread.paint_issues(self, painter)

    def _paint_checks(self, painter, checks) -> None:
        import textfmt
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        for block, r in checks:
            on = block.blockFormat().marker() == textfmt.CHECKED
            rad = r.width() * 0.26
            if on:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(CHECK_ON)
                painter.drawRoundedRect(r, rad, rad)
                pen = QPen(QColor("white"), max(1.2, r.width() * 0.13), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                           Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                path = QPainterPath(QPointF(r.left() + r.width() * 0.24, r.top() + r.height() * 0.53))
                path.lineTo(r.left() + r.width() * 0.43, r.top() + r.height() * 0.72)
                path.lineTo(r.left() + r.width() * 0.77, r.top() + r.height() * 0.31)
                painter.drawPath(path)
            else:
                painter.setPen(QPen(CHECK_GRAY, max(1.0, r.width() * 0.09)))
                painter.setBrush(QColor(255, 255, 255, 200))
                painter.drawRoundedRect(r, rad, rad)
        painter.restore()

    def editor(self):
        sc = self.scene()
        return getattr(sc, "editor", None) if sc else None

    def _undo_added(self) -> None:
        ed = self.editor()
        if ed is not None:
            ed.history.text_command(self)

    def set_editing(self, on: bool) -> None:
        flags = Qt.TextInteractionFlag.TextEditorInteraction if on else Qt.TextInteractionFlag.NoTextInteraction
        self.setTextInteractionFlags(flags)
        self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons if on else Qt.MouseButton.NoButton)

    # ------------------------------------------------------------------ teclado
    def keyPressEvent(self, event) -> None:
        ed = self.editor()
        if ed is not None:
            if event.matches(QKeySequence.StandardKey.Undo):
                ed.undo()
                event.accept()
                return
            if event.matches(QKeySequence.StandardKey.Redo) or (
                    event.key() == Qt.Key.Key_Y and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                ed.redo()
                event.accept()
                return
            if ed.handle_text_key(self, event):
                event.accept()
                return
        super().keyPressEvent(event)
        if ed is not None and event.key() == Qt.Key.Key_Space and not event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier:
            ed.after_space(self)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        ed = self.editor()
        if ed is not None:
            ed.set_active_text(self)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        ed = self.editor()
        if ed is not None and self.owner is not None and event.reason() != Qt.FocusReason.PopupFocusReason:
            ed.text_focus_lost(self)

    # ------------------------------------------------------------------ mouse
    _rpress = None          # botão direito apertado: (ponto, posição no texto)
    _rdrag = False
    _skip_menu = False

    def _hit(self, pos) -> int:
        return self.document().documentLayout().hitTest(pos, Qt.HitTestAccuracy.FuzzyHit)

    def mousePressEvent(self, event) -> None:
        ed = self.editor()
        if event.button() == Qt.MouseButton.RightButton and ed is not None \
                and self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditable:
            # como no Prumo: apertar e arrastar com o botão direito destaca com a cor escolhida;
            # um clique só abre o menu
            self._rpress = (event.pos(), self._hit(event.pos()))
            self._rdrag = self._skip_menu = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not event.modifiers():
            block = self.check_at(event.pos())
            if block is not None and ed is not None:
                import textfmt
                ed.history.break_group()
                textfmt.toggle_check(block)
                ed.history.break_group()
                ed.content_changed()
                self.update()
                self._check_click = True        # o soltar deste clique não mexe no texto
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            href = self.document().documentLayout().anchorAt(event.pos())
            ed = self.editor()
            if href and ed is not None:
                ed.open_link(href)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._rpress is not None and event.buttons() & Qt.MouseButton.RightButton:
            start_pos, start = self._rpress
            if not self._rdrag and start >= 0 and (event.pos() - start_pos).manhattanLength() >= 4:
                self._rdrag = True
                self.setFocus(Qt.FocusReason.MouseFocusReason)
            if self._rdrag:
                pos = self._hit(event.pos())
                if pos >= 0:
                    c = self.textCursor()
                    c.setPosition(start)
                    c.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
                    self.setTextCursor(c)
                ed = self.editor()
                if ed is not None:
                    ed.view.ensureVisible(self.mapRectToScene(QRectF(event.pos(), event.pos()).adjusted(-2, -2, 2, 2)), 10, 40)
            event.accept()
            return
        super().mouseMoveEvent(event)

    _check_click = False

    def mouseReleaseEvent(self, event) -> None:
        if self._check_click and event.button() == Qt.MouseButton.LeftButton:
            self._check_click = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and self._rpress is not None:
            dragged, self._rpress, self._rdrag = self._rdrag, None, False
            ed = self.editor()
            if dragged and ed is not None:
                self._skip_menu = True          # o menu que o Windows manda ao soltar não abre
                if self.textCursor().hasSelection():
                    ed.highlight_drag(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        ed = self.editor()
        if ed is None:
            return super().contextMenuEvent(event)
        if self._skip_menu or self._rdrag:
            self._skip_menu = False
            event.accept()
            return
        cursor = self.textCursor()
        if not cursor.hasSelection():
            pos = self.document().documentLayout().hitTest(event.pos(), Qt.HitTestAccuracy.FuzzyHit)
            if pos >= 0:
                cursor.setPosition(pos)
                self.setTextCursor(cursor)
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        ed.text_context_menu(self, event.screenPos(), self.document().documentLayout().anchorAt(event.pos()))
        event.accept()

    # ------------------------------------------------------------------ ajudas
    def plain(self) -> str:
        return self.document().toPlainText()

    def cursor_to_end(self) -> None:
        c = self.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(c)
