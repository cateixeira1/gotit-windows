"""Miniaturas das notas por revisão: só a nota que mudou desde a última miniatura é aberta e
desenhada; a nota aberta é desenhada da memória."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

import core

WIDTH = 300


class Thumbs:
    def __init__(self, window):
        self.window = window
        self.dir = core.cache_dir(window.store.data_dir) / "thumbs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memory: dict[str, tuple[int, QImage]] = {}
        self._rendering: set[str] = set()

    def _path(self, doc_id: str, rev: int) -> Path:
        return self.dir / f"{doc_id}-{rev}.png"

    def _drop_old(self, doc_id: str, keep: int) -> None:
        for p in self.dir.glob(f"{doc_id}-*.png"):
            if p.name != f"{doc_id}-{keep}.png":
                try:
                    p.unlink()
                except OSError:
                    pass

    def put_live(self, doc_id: str, rev: int, image: QImage) -> None:
        self.memory[doc_id] = (rev, image)
        try:
            image.save(str(self._path(doc_id, rev)), "PNG")
            self._drop_old(doc_id, rev)
        except Exception:
            pass

    def get(self, doc_id: str, rev: int) -> QImage | None:
        hit = self.memory.get(doc_id)
        if hit and hit[0] == rev:
            return hit[1]
        path = self._path(doc_id, rev)
        if path.exists():
            img = QImage(str(path))
            if not img.isNull():
                self.memory[doc_id] = (rev, img)
                return img
        if doc_id in self._rendering:
            return hit[1] if hit else None
        return self.render(doc_id, rev)

    def render(self, doc_id: str, rev: int) -> QImage | None:
        from canvas import CanvasScene
        doc = self.window.store.load(doc_id)
        if doc is None:
            return None
        self._rendering.add(doc_id)
        try:
            family = self.window.settings.value("defaultFont", None)
            size = float(self.window.settings.value("defaultFontSize", 12))
            import theme
            scene = CanvasScene(doc, self.window.assets, editor=None, resolver=self.window.resolve_note,
                                default_font=(family or theme.default_text_family(), size))
            img = scene.render_page(0, WIDTH)
            scene.deleteLater()
        except Exception:
            img = None
        finally:
            self._rendering.discard(doc_id)
        if img is not None:
            self.put_live(doc_id, doc.get("revision", rev), img)
        return img

    def small(self, info) -> QImage | None:
        img = self.get(info.id, info.revision)
        return img.scaledToWidth(88, Qt.TransformationMode.SmoothTransformation) if img is not None else None

    def forget(self, doc_id: str) -> None:
        self.memory.pop(doc_id, None)
        for p in self.dir.glob(f"{doc_id}-*.png"):
            try:
                p.unlink()
            except OSError:
                pass
