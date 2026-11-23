"""Texto editável dentro do canvas (o texto da nota e o de caixas, post-its, formas e tabelas).
Desfazer e refazer passam pelo histórico único do editor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QTextCursor
from PySide6.QtWidgets import QGraphicsTextItem


class EditableText(QGraphicsTextItem):
    def __init__(self, parent=None, owner=None):
        super().__init__(parent)
        self.owner = owner                      # BlockItem dono da caixa; None no texto da nota
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.document().setUndoRedoEnabled(True)
        self.document().undoCommandAdded.connect(self._undo_added)
        self.setOpenExternalLinks(False)

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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            href = self.document().documentLayout().anchorAt(event.pos())
            ed = self.editor()
            if href and ed is not None:
                ed.open_link(href)
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        ed = self.editor()
        if ed is None:
            return super().contextMenuEvent(event)
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
