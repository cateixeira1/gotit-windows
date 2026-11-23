"""Transcrição de áudio no computador (Whisper small, pelo faster-whisper). O texto vai para um
bloco próprio ao lado do áudio (ou para o texto da nota). Nada sai do computador."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout)

import models
import theme

LANGUAGES = [("pt", "Português"), ("en", "Inglês"), ("es", "Espanhol"), ("it", "Italiano"), ("fr", "Francês"),
             ("de", "Alemão"), (None, "Detectar sozinho")]
_model = None
_lock = threading.Lock()


def load(window):
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            path = models.path_of(window.store.data_dir, models.SPEECH)
            threads = max(1, (os.cpu_count() or 4) - 1)
            _model = WhisperModel(str(path), device="cpu", compute_type="int8", cpu_threads=threads)
        return _model


def decode(path) -> "np.ndarray":
    """Áudio em 16 kHz mono (float32), lido pelo PyAV (m4a, mp3, wav, ogg, flac, vídeo...)."""
    import av
    import numpy as np
    chunks = []
    with av.open(str(path)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def shutdown() -> None:
    global _model
    with _lock:
        _model = None


class Job(QObject):
    progress = Signal(float, str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, window, path, language):
        super().__init__()
        self.window, self.path, self.language = window, path, language
        self.cancel = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.progress.emit(0.0, "Carregando o modelo de voz…")
            wm = load(self.window)
            self.progress.emit(0.0, "Lendo o áudio…")
            audio = decode(self.path)
            segments, info = wm.transcribe(audio, language=self.language, vad_filter=True, beam_size=3,
                                           condition_on_previous_text=True)
            total = max(1.0, float(info.duration or 1))
            parts = []
            for seg in segments:
                if self.cancel.is_set():
                    self.failed.emit("Transcrição cancelada.")
                    return
                parts.append(seg.text.strip())
                self.progress.emit(min(1.0, seg.end / total), " ".join(parts)[-160:])
            text = " ".join(p for p in parts if p).strip()
            if total > 20 and len(text) < total * 0.5:
                text += ("\n\n(O áudio tem partes sem fala reconhecível, ou a gravação está muito baixa.)" if text else "")
            self.done.emit(text)
        except Exception as exc:
            self.failed.emit(f"Não foi possível transcrever: {type(exc).__name__}: {exc}")


class TranscribeDialog(QDialog):
    def __init__(self, window, item):
        super().__init__(window)
        self.window, self.item = window, item
        self.setWindowTitle("Transcrever o áudio")
        self.setMinimumWidth(460)
        self.text = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.lang = QComboBox()
        for code, title in LANGUAGES:
            self.lang.addItem(title, code)
        saved = window.settings.value("transcriptionLanguage", "pt")
        self.lang.setCurrentIndex(max(0, self.lang.findData(saved if saved != "auto" else None)))
        self.place = QComboBox()
        self.place.addItem("Num bloco ao lado do áudio", "card")
        self.place.addItem("No fim do texto da nota", "story")
        self.place.setCurrentIndex(max(0, self.place.findData(window.settings.value("transcriptionPlace", "card"))))
        form.addRow("Idioma", self.lang)
        form.addRow("Onde colocar", self.place)
        lay.addLayout(form)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.status = QLabel("Tudo roda neste computador.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel = QPushButton("Cancelar")
        self.go = QPushButton("Transcrever")
        self.go.setProperty("primary", True)
        row.addWidget(self.cancel)
        row.addWidget(self.go)
        lay.addLayout(row)
        self.cancel.clicked.connect(self.reject)
        self.go.clicked.connect(self.start)
        self.job = None

    def start(self):
        path = self.window.store.asset_path(self.item.data_state.get("asset"))
        if not path:
            self.status.setText("O arquivo deste áudio não foi encontrado.")
            return
        code = self.lang.currentData()
        self.window.settings.setValue("transcriptionLanguage", code or "auto")
        self.window.settings.setValue("transcriptionPlace", self.place.currentData())
        self.go.setEnabled(False)
        self.bar.show()
        self.job = Job(self.window, path, code)
        self.job.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.job.done.connect(self._done, Qt.ConnectionType.QueuedConnection)
        self.job.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        self.job.start()

    def _progress(self, frac, text):
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text or "Transcrevendo…")

    def _done(self, text):
        self.text = text
        self.accept()

    def _failed(self, msg):
        self.status.setText(msg)
        self.go.setEnabled(True)
        self.bar.hide()

    def reject(self):
        if self.job is not None:
            self.job.cancel.set()
        super().reject()


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(window, editor, item) -> None:
    if not available():
        editor.toast("A transcrição não está neste pacote do Got It!.")
        return
    if not models.ensure(window, "speech", "A transcrição transforma a gravação em texto aqui mesmo, sem internet."):
        return
    dlg = TranscribeDialog(window, item)
    if dlg.exec() != QDialog.DialogCode.Accepted or dlg.text is None:
        return
    if not dlg.text.strip():
        editor.toast("Não foi reconhecida fala neste áudio.")
        return
    if window.settings.value("transcriptionPlace", "card") == "story":
        editor.insert_plain_text(dlg.text, title=f"Transcrição — {item.data_state.get('caption') or 'áudio'}")
    else:
        editor.insert_transcript(item, dlg.text)
