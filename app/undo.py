"""Desfazer e refazer únicos para a nota: digitação (pelo histórico de cada texto, agrupada por
pausa de 1 s e no máximo 5 s) e mudanças em objetos, tinta, páginas e ajustes (diferenças por
objeto, aplicadas no lugar, sem recriar a página)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor

LIMIT = 300


@dataclass
class TextEntry:
    item: object
    count: int = 1
    first: float = field(default_factory=time.monotonic)
    last: float = field(default_factory=time.monotonic)
    label: str = "Digitação"
    steps: int = -1


@dataclass
class DeltaEntry:
    label: str
    diff: dict


class History(QObject):
    changed = Signal()

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.entries: list = []
        self.index = 0
        self.applying = False

    def clear(self) -> None:
        self.entries.clear()
        self.index = 0
        self.changed.emit()

    def _truncate(self) -> None:
        del self.entries[self.index:]

    def _trim(self) -> None:
        extra = len(self.entries) - LIMIT
        if extra > 0:
            del self.entries[:extra]
            self.index -= extra

    def text_command(self, item) -> None:
        if self.applying:
            return
        now = time.monotonic()
        steps = item.document().availableUndoSteps()
        top = self.entries[self.index - 1] if self.index else None
        # edição juntada à anterior (joinPreviousEditBlock): o Qt avisa de novo, mas continua sendo
        # um passo só no texto; não conta outro (senão o desfazer voltaria passos a mais)
        if isinstance(top, TextEntry) and top.item is item and steps == top.steps and self.index == len(self.entries):
            top.last = now
            return
        self._truncate()
        if isinstance(top, TextEntry) and top.item is item and now - top.last < 1.0 and now - top.first < 5.0:
            top.count += 1
            top.last = now
            top.steps = steps
        else:
            self.entries.append(TextEntry(item, steps=steps))
            self.index += 1
        self._trim()
        self.changed.emit()

    def break_group(self) -> None:
        """Colar, mudar de posição ou formatar separam a digitação seguinte."""
        top = self.entries[self.index - 1] if self.index else None
        if isinstance(top, TextEntry):
            top.last = -1e9

    def push_delta(self, label: str, diff: dict) -> None:
        if self.applying or not diff:
            return
        self._truncate()
        self.entries.append(DeltaEntry(label, diff))
        self.index += 1
        self._trim()
        self.changed.emit()

    def can_undo(self) -> bool:
        return self.index > 0

    def can_redo(self) -> bool:
        return self.index < len(self.entries)

    def undo_label(self) -> str:
        return self.entries[self.index - 1].label if self.can_undo() else ""

    def redo_label(self) -> str:
        return self.entries[self.index].label if self.can_redo() else ""

    def undo(self) -> None:
        if not self.can_undo():
            return
        entry = self.entries[self.index - 1]
        self.applying = True
        try:
            if isinstance(entry, TextEntry):
                self._text(entry, undo=True)
            else:
                self.editor.scene.apply_states({k: v[0] for k, v in entry.diff.items()})
        finally:
            self.applying = False
        self.index -= 1
        self.changed.emit()
        self.editor.content_changed()

    def redo(self) -> None:
        if not self.can_redo():
            return
        entry = self.entries[self.index]
        self.applying = True
        try:
            if isinstance(entry, TextEntry):
                self._text(entry, undo=False)
            else:
                self.editor.scene.apply_states({k: v[1] for k, v in entry.diff.items()})
        finally:
            self.applying = False
        self.index += 1
        self.changed.emit()
        self.editor.content_changed()

    def _text(self, entry: TextEntry, undo: bool) -> None:
        item = entry.item
        try:
            doc = item.document()
        except RuntimeError:
            return
        cursor = QTextCursor(doc)
        for _ in range(entry.count):
            if undo and doc.isUndoAvailable():
                doc.undo(cursor)
            elif not undo and doc.isRedoAvailable():
                doc.redo(cursor)
        self.editor.focus_text(item, cursor)
