"""Remover o fundo de imagens: desenho ou texto em papel ou quadro branco fica com o papel
transparente (compara cada pixel com o papel ao redor, para iluminação desigual), com prévia e
controle de sensibilidade. Nada muda antes de "Aplicar"; o original continua guardado."""

from __future__ import annotations

import io

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

import theme


def _to_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=img.height() * img.bytesPerLine())
    arr = arr.reshape(img.height(), img.bytesPerLine())[:, : img.width() * 4].reshape(img.height(), img.width(), 4)
    return arr.copy()


def _box_blur(a: np.ndarray, r: int) -> np.ndarray:
    """Média numa janela (2r+1)² por imagem integral (fundo do papel ao redor de cada pixel)."""
    pad = np.pad(a, r + 1, mode="edge").astype(np.float64)
    ii = pad.cumsum(0).cumsum(1)
    h, w = a.shape
    k = 2 * r + 1
    s = ii[k:k + h, k:k + w] - ii[0:h, k:k + w] - ii[k:k + h, 0:w] + ii[0:h, 0:w]
    return s / (k * k)


def _max_filter(a: np.ndarray, r: int) -> np.ndarray:
    """Máximo numa janela (2r+1)², separável (o papel é o que há de mais claro por perto)."""
    out = a.copy()
    for axis in (0, 1):
        src = out.copy()
        for d in range(1, r + 1):
            if axis == 0:
                out[d:] = np.maximum(out[d:], src[:-d])
                out[:-d] = np.maximum(out[:-d], src[d:])
            else:
                out[:, d:] = np.maximum(out[:, d:], src[:, :-d])
                out[:, :-d] = np.maximum(out[:, :-d], src[:, d:])
    return out


def paper_background(gray: np.ndarray) -> np.ndarray:
    """Cor do papel em cada ponto (aguenta iluminação desigual e traços grossos)."""
    h, w = gray.shape
    f = max(1, int(max(h, w) / 512))
    small = gray[::f, ::f]
    r = max(6, min(small.shape) // 12)
    bg = _box_blur(_max_filter(small, r), max(2, r // 2))
    bg = np.repeat(np.repeat(bg, f, axis=0), f, axis=1)[:h, :w]
    return np.maximum(bg, 1.0)


def paper_mask(rgba: np.ndarray, sensitivity: float = 0.5) -> np.ndarray:
    """Alfa (0..255): tinta opaca, papel transparente."""
    gray = rgba[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    ratio = gray / paper_background(gray)          # 1 = igual ao papel, < 1 = mais escuro (tinta)
    cut = 0.93 - 0.22 * (1 - sensitivity)          # sensibilidade alta pega traços claros
    soft = 0.06
    alpha = np.clip((cut - ratio) / soft + 0.5, 0, 1)
    # tira pontinhos soltos: pixel de tinta precisa de vizinhos de tinta
    neigh = _box_blur(alpha.astype(np.float64), 1)
    alpha = np.where(neigh < 0.25, 0, alpha)
    return (alpha * 255).astype(np.uint8)


def apply_mask(rgba: np.ndarray, alpha: np.ndarray, unify: bool = True) -> QImage:
    out = rgba.copy()
    out[..., 3] = alpha
    if unify:
        # cor da tinta uniforme (a média dos pixels bem opacos), como no iPhone
        strong = alpha > 200
        if strong.any():
            color = np.median(out[..., :3][strong], axis=0)
            out[..., :3] = np.where(alpha[..., None] > 0, (0.65 * out[..., :3] + 0.35 * color).astype(np.uint8), out[..., :3])
    h, w = alpha.shape
    return QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


class CutoutDialog(QDialog):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remover o fundo")
        self.resize(760, 620)
        self.rgba = _to_array(image)
        self.result: QImage | None = None
        lay = QVBoxLayout(self)
        info = QLabel("Para desenhos e textos em papel ou quadro branco: o papel fica transparente. "
                      "Ajuste a sensibilidade até a prévia ficar boa.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EEE, stop:1 #CCC);"
                                   f"border: 1px solid {theme.LINE};")
        self.preview.setMinimumHeight(420)
        lay.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Sensibilidade"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.slider.valueChanged.connect(self._update)
        row.addWidget(self.slider, 1)
        lay.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancelar")
        ok = QPushButton("Aplicar")
        ok.setProperty("primary", True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self._update()

    def _update(self) -> None:
        alpha = paper_mask(self.rgba, self.slider.value() / 100)
        self.result = apply_mask(self.rgba, alpha)
        pm = QPixmap.fromImage(self.result).scaled(700, 420, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)


def remove_background(window, editor, item) -> None:
    img = editor.assets.image(item.data_state.get("asset"), 2048)
    if img is None:
        editor.toast("Não foi possível abrir esta imagem.")
        return
    dlg = CutoutDialog(img, editor)
    if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result is None:
        return
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    dlg.result.save(buf, "PNG")
    digest = window.store.import_bytes(bytes(ba.data()), ".png")
    editor.set_block_field([item], "Remover o fundo", asset=digest, original=item.data_state.get("original") or item.data_state.get("asset"))
