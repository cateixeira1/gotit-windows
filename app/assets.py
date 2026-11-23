"""Leitura das mídias guardadas na biblioteca: imagens (reduzidas para a tela, com cache) e
páginas de PDF desenhadas pelo PDFium. O original por SHA-256 nunca muda."""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".heic", ".heif", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".wmv", ".mkv", ".webm"}
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".wma", ".ogg", ".flac", ".opus"}


class _LRU:
    def __init__(self, budget_bytes: int):
        self.budget = budget_bytes
        self.used = 0
        self.items: OrderedDict = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.items.get(key)
            if value is not None:
                self.items.move_to_end(key)
            return value

    def put(self, key, image: QImage):
        size = image.sizeInBytes() if hasattr(image, "sizeInBytes") else image.width() * image.height() * 4
        with self.lock:
            if key in self.items:
                return
            self.items[key] = image
            self.used += size
            while self.used > self.budget and len(self.items) > 1:
                _, old = self.items.popitem(last=False)
                self.used -= old.sizeInBytes()


class Assets:
    def __init__(self, store):
        self.store = store
        self.cache = _LRU(160 * 1024 * 1024)
        self._pdf_lock = threading.Lock()
        self._pdf_counts: dict[str, int] = {}
        self._pdf_sizes: dict[tuple[str, int], tuple[float, float]] = {}

    def path(self, digest: str | None) -> Path | None:
        return self.store.asset_path(digest) if digest else None

    # ------------------------------------------------------------------ imagens
    def image(self, digest: str | None, max_side: int = 2048) -> QImage | None:
        if not digest:
            return None
        bucket = 256
        while bucket < max_side and bucket < 4096:
            bucket *= 2
        key = ("img", digest, bucket)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        path = self.path(digest)
        if not path:
            return None
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > bucket:
            scale = bucket / max(size.width(), size.height())
            reader.setScaledSize(QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale))))
        image = reader.read()
        if image.isNull():
            image = self._pillow(path, bucket)
        if image is None or image.isNull():
            return None
        self.cache.put(key, image)
        return image

    @staticmethod
    def _pillow(path: Path, bucket: int) -> QImage | None:
        try:
            from PIL import Image, ImageOps
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGBA")
                im.thumbnail((bucket, bucket))
                data = im.tobytes("raw", "RGBA")
                return QImage(data, im.width, im.height, QImage.Format.Format_RGBA8888).copy()
        except Exception:
            return None

    def image_size(self, digest: str) -> tuple[int, int]:
        """Tamanho já com a orientação da foto (EXIF) aplicada."""
        img = self.image(digest, 1024)
        return (img.width(), img.height()) if img is not None else (400, 300)

    # ------------------------------------------------------------------ PDF
    def _pdf(self, digest: str):
        import pypdfium2 as pdfium
        path = self.path(digest)
        if not path:
            return None
        return pdfium.PdfDocument(str(path))

    def pdf_page_count(self, digest: str) -> int:
        if digest in self._pdf_counts:
            return self._pdf_counts[digest]
        with self._pdf_lock:
            try:
                pdf = self._pdf(digest)
                n = len(pdf) if pdf is not None else 0
                if pdf is not None:
                    pdf.close()
            except Exception:
                n = 0
        self._pdf_counts[digest] = n
        return n

    def pdf_page_size(self, digest: str, index: int) -> tuple[float, float]:
        key = (digest, index)
        if key in self._pdf_sizes:
            return self._pdf_sizes[key]
        with self._pdf_lock:
            try:
                pdf = self._pdf(digest)
                w, h = pdf[index].get_size()
                pdf.close()
            except Exception:
                w, h = 595.0, 842.0
        self._pdf_sizes[key] = (w, h)
        return w, h

    def pdf_page(self, digest: str | None, index: int, width_px: int) -> QImage | None:
        if not digest:
            return None
        bucket = 256
        while bucket < width_px and bucket < 3072:
            bucket = int(bucket * 1.5)
        key = ("pdf", digest, index, bucket)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        with self._pdf_lock:
            try:
                pdf = self._pdf(digest)
                if pdf is None or index >= len(pdf):
                    return None
                page = pdf[index]
                w, _ = page.get_size()
                bitmap = page.render(scale=bucket / max(1.0, w), draw_annots=True)
                pil = bitmap.to_pil().convert("RGB")
                pdf.close()
            except Exception:
                return None
        data = pil.tobytes("raw", "RGB")
        image = QImage(data, pil.width, pil.height, pil.width * 3, QImage.Format.Format_RGB888).copy()
        self.cache.put(key, image)
        return image

    def pdf_text(self, digest: str, limit_pages: int = 50) -> str:
        with self._pdf_lock:
            try:
                pdf = self._pdf(digest)
                parts = []
                for i in range(min(len(pdf), limit_pages)):
                    tp = pdf[i].get_textpage()
                    parts.append(tp.get_text_range())
                    tp.close()
                pdf.close()
                return "\n".join(parts)
            except Exception:
                return ""


def import_image_bytes_safe(path: Path) -> tuple[bytes, str] | None:
    """Fotos que o Qt não lê (HEIC do iPhone) viram JPEG ao entrar na nota."""
    reader = QImageReader(str(path))
    if reader.canRead():
        return None
    try:
        from PIL import Image, ImageOps
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            buf = io.BytesIO()
            if im.mode in ("RGBA", "LA", "P"):
                im.convert("RGBA").save(buf, "PNG")
                return buf.getvalue(), ".png"
            im.convert("RGB").save(buf, "JPEG", quality=92)
            return buf.getvalue(), ".jpg"
    except Exception:
        return None


def qimage_scaled(image: QImage, w: int, h: int) -> QImage:
    return image.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
