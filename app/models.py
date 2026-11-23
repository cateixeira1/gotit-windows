"""Modelos de IA baixados só quando a pessoa pede, de uma revisão fixa do Hugging Face,
conferidos por tamanho e SHA-256 antes de usar (como no Got It! para iPhone). Um download
interrompido continua de onde parou. Depois de baixados, nada usa a internet."""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

import core
import theme

HF = "https://huggingface.co"


@dataclass(frozen=True)
class FileSpec:
    name: str
    size: int
    sha256: str
    repo: str
    revision: str

    @property
    def url(self) -> str:
        return f"{HF}/{self.repo}/resolve/{self.revision}/{self.name}"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    title: str
    description: str
    files: tuple = field(default_factory=tuple)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


ASSISTANT = ModelSpec(
    "assistant", "Assistente (Gemma 4 E2B)",
    "Resume notas, cria perguntas de revisão e responde perguntas sobre as suas notas, com as fontes.",
    (FileSpec("gemma-4-E2B-it.litertlm", 2_588_147_712, "181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c",
              "litert-community/gemma-4-E2B-it-litert-lm", "2d74ac41a33d7da82f39f7d5720a04c68514a103"),))
SEMANTIC = ModelSpec(
    "semantic", "Busca por significado (EmbeddingGemma)",
    "Acha notas pelo assunto, mesmo sem as mesmas palavras.",
    (FileSpec("embeddinggemma-2-text-270m.litertlm", 164_626_432, "2d079ee2f6f066b1f368e8d7c819f55214eaef1d0513b312321901f30ab286fb",
              "litert-community/embeddinggemma-2-text-270m-litert-lm", "9be6e8b90982095dc05c2bd162e4b954ee4dbac7"),))
_W = ("Systran/faster-whisper-small", "536b0662742c02347bc0e980a01041f333bce120")
SPEECH = ModelSpec(
    "speech", "Transcrição de áudio (Whisper small)",
    "Transforma gravações em texto, em português e em outros idiomas.",
    (FileSpec("config.json", 2370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828", *_W),
     FileSpec("tokenizer.json", 2_203_239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab", *_W),
     FileSpec("vocabulary.txt", 459_861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913", *_W),
     FileSpec("model.bin", 483_546_902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671", *_W)))

SPECS = (ASSISTANT, SEMANTIC, SPEECH)
BY_KEY = {s.key: s for s in SPECS}


def human(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB".replace(".", ",")
    return f"{n / 1e6:.0f} MB"


def folder(data_dir: Path, spec: ModelSpec) -> Path:
    path = core.models_dir(data_dir) / spec.key
    path.mkdir(parents=True, exist_ok=True)
    return path


def ready_marker(data_dir: Path, spec: ModelSpec) -> Path:
    return folder(data_dir, spec) / ".conferido"


def is_ready(data_dir: Path, spec: ModelSpec) -> bool:
    d = folder(data_dir, spec)
    if not all((d / f.name).exists() and (d / f.name).stat().st_size == f.size for f in spec.files):
        return False
    return ready_marker(data_dir, spec).exists()


def path_of(data_dir: Path, spec: ModelSpec) -> Path:
    """Arquivo único (Gemma, EmbeddingGemma) ou a pasta (Whisper)."""
    d = folder(data_dir, spec)
    return d / spec.files[0].name if len(spec.files) == 1 else d


def delete(data_dir: Path, spec: ModelSpec) -> None:
    shutil.rmtree(folder(data_dir, spec), ignore_errors=True)


def sha256_of(path: Path, cancel=None, progress=None) -> str:
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 << 20), b""):
            if cancel is not None and cancel.is_set():
                raise InterruptedError
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done)
    return h.hexdigest()


class Download(QObject):
    """Baixa os arquivos de um modelo numa thread; continua de onde parou (.part)."""
    progress = Signal(float, str)          # 0..1, texto
    finished = Signal(bool, str)           # ok, mensagem

    def __init__(self, data_dir: Path, spec: ModelSpec):
        super().__init__()
        self.data_dir, self.spec = data_dir, spec
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.cancel.set()

    def _run(self) -> None:
        try:
            d = folder(self.data_dir, self.spec)
            need = sum(f.size - ((d / (f.name + ".part")).stat().st_size if (d / (f.name + ".part")).exists() else 0)
                       for f in self.spec.files if not (d / f.name).exists())
            free = shutil.disk_usage(d).free
            if free < need + 200 * 1024 * 1024:
                self.finished.emit(False, f"Falta espaço no disco: são precisos {human(need)} e há {human(free)} livres.")
                return
            total = self.spec.size
            base = 0
            for f in self.spec.files:
                target = d / f.name
                if target.exists() and target.stat().st_size == f.size:
                    base += f.size
                    continue
                self._fetch(f, d, base, total)
                base += f.size
            # conferência: tamanho e SHA-256 de cada arquivo
            checked = 0
            for f in self.spec.files:
                target = d / f.name
                self.progress.emit(checked / total, f"Conferindo {f.name}…")
                digest = sha256_of(target, self.cancel, lambda n: self.progress.emit((checked + n) / total, "Conferindo o arquivo…"))
                if digest != f.sha256:
                    target.unlink(missing_ok=True)
                    self.finished.emit(False, "O arquivo baixado não confere com o publicado (tamanho ou SHA-256) e foi descartado. "
                                              "Tente de novo.")
                    return
                checked += f.size
            ready_marker(self.data_dir, self.spec).write_text("ok", encoding="utf-8")
            self.finished.emit(True, "Pronto.")
        except InterruptedError:
            self.finished.emit(False, "Download pausado. Ele continua de onde parou quando você tocar em Baixar de novo.")
        except Exception as exc:
            self.finished.emit(False, f"O download parou ({type(exc).__name__}: {exc}). Ele continua de onde parou "
                                      "quando você tentar de novo.")

    def _fetch(self, f: FileSpec, d: Path, base: int, total: int) -> None:
        part = d / (f.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        if have > f.size:
            part.unlink()
            have = 0
        req = urllib.request.Request(f.url, headers={"User-Agent": f"GotIt-Windows/{core.APP_VERSION}"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=60) as resp:
            if have and resp.status != 206:      # o servidor recomeçou do zero
                have = 0
                mode = "wb"
            else:
                mode = "ab" if have else "wb"
            with open(part, mode) as out:
                done = have
                while True:
                    if self.cancel.is_set():
                        raise InterruptedError
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    self.progress.emit((base + done) / total, f"{human(base + done)} de {human(total)}")
        if part.stat().st_size != f.size:
            raise IOError("o arquivo chegou incompleto")
        os.replace(part, d / f.name)


class ModelRow(QWidget):
    """Linha dos Ajustes: o que o modelo faz, tamanho, estado, Baixar/Pausar/Apagar."""

    def __init__(self, window, spec: ModelSpec, parent=None):
        super().__init__(parent)
        self.window, self.spec = window, spec
        self.download: Download | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 8)
        top = QHBoxLayout()
        title = QLabel(f"<b>{spec.title}</b> · {human(spec.size)}")
        self.status = QLabel()
        self.status.setStyleSheet(f"color: {theme.MUTED};")
        self.button = QPushButton()
        self.remove = QPushButton("Apagar")
        self.remove.setProperty("danger", True)
        top.addWidget(title, 1)
        top.addWidget(self.button)
        top.addWidget(self.remove)
        lay.addLayout(top)
        desc = QLabel(spec.description)
        desc.setWordWrap(True)
        lay.addWidget(desc)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        self.button.clicked.connect(self._toggle)
        self.remove.clicked.connect(self._delete)
        self._show()

    def _show(self) -> None:
        ready = is_ready(self.window.store.data_dir, self.spec)
        running = self.download is not None
        self.button.setText("Pausar" if running else ("Baixado" if ready else "Baixar"))
        self.button.setEnabled(running or not ready)
        self.button.setProperty("primary", not ready and not running)
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
        self.remove.setVisible(ready and not running)
        self.bar.setVisible(running)
        if ready:
            self.status.setText("Pronto: funciona sem internet.")
        elif not running:
            partial = any((folder(self.window.store.data_dir, self.spec) / (f.name + ".part")).exists() for f in self.spec.files)
            self.status.setText("Download pela metade: continua de onde parou." if partial else "Não baixado.")

    def _toggle(self) -> None:
        if self.download is not None:
            self.download.stop()
            return
        self.download = Download(self.window.store.data_dir, self.spec)
        self.download.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.download.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.download.start()
        self._show()

    def _progress(self, frac: float, text: str) -> None:
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text)

    def _finished(self, ok: bool, message: str) -> None:
        self.download = None
        self._show()
        if not ok:
            self.status.setText(message)
        if ok and self.spec.key == "semantic":
            self.window.settings.setValue("semanticSearch", "true")
            self.window.ai.semantic_ready()

    def _delete(self) -> None:
        if QMessageBox.question(self, "Apagar o modelo", f"Apagar {self.spec.title} ({human(self.spec.size)})? "
                                "Dá para baixar de novo depois.") != QMessageBox.StandardButton.Yes:
            return
        self.window.ai.release(self.spec.key)
        delete(self.window.store.data_dir, self.spec)
        self._show()


class DownloadDialog(QDialog):
    """Pede o modelo na hora em que a função é usada pela primeira vez."""

    def __init__(self, window, spec: ModelSpec, why: str):
        super().__init__(window)
        self.setWindowTitle(spec.title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        text = QLabel(f"{why}<br><br>Para isso o Got It! baixa uma vez <b>{spec.title}</b> ({human(spec.size)}). "
                      "Depois disso tudo roda neste computador, sem internet, e nada das suas notas sai daqui.")
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(text)
        self.row = ModelRow(window, spec)
        lay.addWidget(self.row)
        close = QPushButton("Fechar")
        close.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self.row.download_done = False
        orig = self.row._finished

        def finished(ok, message):
            orig(ok, message)
            if ok:
                QTimer.singleShot(300, self.accept)
        self.row._finished = finished

    def reject(self) -> None:
        if self.row.download is not None:
            self.row.download.stop()
        super().reject()


def ensure(window, key: str, why: str) -> bool:
    spec = BY_KEY[key]
    if is_ready(window.store.data_dir, spec):
        return True
    dlg = DownloadDialog(window, spec, why)
    return dlg.exec() == QDialog.DialogCode.Accepted and is_ready(window.store.data_dir, spec)
