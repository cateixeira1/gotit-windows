"""Áudio e vídeo: tocar no próprio bloco, gravar pelo microfone, abrir vídeos e pegar o primeiro
quadro para a capa (Qt Multimedia, que no Windows usa o Media Foundation)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSlider, QVBoxLayout,
                               QWidget, QToolButton)

import icons
import theme

try:
    from PySide6.QtMultimedia import (QAudioInput, QAudioOutput, QMediaCaptureSession, QMediaDevices, QMediaFormat,
                                      QMediaPlayer, QMediaRecorder, QVideoSink)
    HAVE_MULTIMEDIA = True
except Exception:   # pragma: no cover - sem o módulo, áudio e vídeo ficam só como arquivos
    HAVE_MULTIMEDIA = False


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds + 0.5))
    return f"{seconds // 60}:{seconds % 60:02d}"


class AudioController(QObject):
    """Um áudio por vez, como num aparelho: tocar outro pausa o anterior."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.item = None
        self.player = None
        self._pos = 0.0
        self._dur = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)

    def _ensure(self) -> bool:
        if not HAVE_MULTIMEDIA:
            return False
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.output = QAudioOutput(self)
            self.player.setAudioOutput(self.output)
            self.player.durationChanged.connect(self._duration)
            self.player.playbackStateChanged.connect(lambda *_: self._repaint())
            self.player.mediaStatusChanged.connect(self._status)
        return True

    def _duration(self, ms: int) -> None:
        self._dur = ms / 1000.0
        if self.item is not None and ms > 0:
            self.item.data_state["duration"] = round(self._dur, 2)
            self._repaint()

    def _status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._pos = 0.0
            self.timer.stop()
            self._repaint()

    def _tick(self) -> None:
        if self.player is not None:
            self._pos = self.player.position() / 1000.0
        self._repaint()

    def _repaint(self) -> None:
        if self.item is not None:
            try:
                self.item.update()
            except RuntimeError:
                self.item = None

    def is_playing(self, block_id: str) -> bool:
        return bool(self.player and self.item is not None and getattr(self.item, "block_id", None) == block_id
                    and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

    def position(self, block_id: str) -> tuple[float, float]:
        if self.item is not None and getattr(self.item, "block_id", None) == block_id:
            return self._pos, self._dur
        return 0.0, 0.0

    def toggle(self, item) -> None:
        if not self._ensure():
            self.editor.toast("Este computador não tem o módulo de áudio do Qt.")
            return
        if self.item is item:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
                self.timer.stop()
            else:
                self.player.play()
                self.timer.start()
            self._repaint()
            return
        old = self.item
        self.stop()
        path = self.editor.store.asset_path(item.data_state.get("asset"))
        if not path:
            self.editor.toast("O arquivo deste áudio não foi encontrado.")
            return
        self.item = item
        self._pos = 0.0
        self._dur = float(item.data_state.get("duration") or 0)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.timer.start()
        if old is not None:
            try:
                old.update()
            except RuntimeError:
                pass
        self._repaint()

    def seek(self, item, fraction: float) -> None:
        if self.item is not item:
            self.toggle(item)
        if self.player is not None and self._dur:
            self.player.setPosition(int(max(0.0, min(1.0, fraction)) * self._dur * 1000))
            self._pos = self.player.position() / 1000.0
            self._repaint()

    def stop(self) -> None:
        if self.player is not None:
            self.player.stop()
        self.timer.stop()
        old, self.item = self.item, None
        if old is not None:
            try:
                old.update()
            except RuntimeError:
                pass


class RecorderDialog(QDialog):
    """Gravar áudio pelo microfone do computador."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gravar áudio")
        self.setMinimumWidth(380)
        self.path: Path | None = None
        self.duration = 0.0
        self._started = 0.0
        self._paused_total = 0.0
        self._paused_at = 0.0
        lay = QVBoxLayout(self)
        self.status = QLabel("Pronto para gravar.")
        self.status.setFont(theme.ui_font(10.5, True))
        self.clock = QLabel("0:00")
        self.clock.setFont(theme.ui_font(26, True))
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.device = QLabel("")
        self.device.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(self.status)
        lay.addWidget(self.clock)
        lay.addWidget(self.device)
        row = QHBoxLayout()
        self.rec = QPushButton("Gravar")
        self.rec.setProperty("primary", True)
        self.pause = QPushButton("Pausar")
        self.pause.setEnabled(False)
        self.done = QPushButton("Inserir na nota")
        self.done.setEnabled(False)
        cancel = QPushButton("Cancelar")
        row.addWidget(self.rec)
        row.addWidget(self.pause)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.done)
        lay.addLayout(row)
        cancel.clicked.connect(self.reject)
        self.rec.clicked.connect(self.toggle)
        self.pause.clicked.connect(self.toggle_pause)
        self.done.clicked.connect(self.finish)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.recorder = None
        if not HAVE_MULTIMEDIA:
            self.status.setText("O módulo de áudio não está disponível.")
            self.rec.setEnabled(False)
            return
        dev = QMediaDevices.defaultAudioInput()
        if dev.isNull():
            self.status.setText("Nenhum microfone encontrado.")
            self.device.setText("Ligue um microfone e abra esta janela de novo.")
            self.rec.setEnabled(False)
            return
        self.device.setText(f"Microfone: {dev.description()}")
        self.session = QMediaCaptureSession(self)
        self.input = QAudioInput(dev, self)
        self.session.setAudioInput(self.input)
        self.recorder = QMediaRecorder(self)
        self.session.setRecorder(self.recorder)
        fmt = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
        fmt.setAudioCodec(QMediaFormat.AudioCodec.AAC)
        self.recorder.setMediaFormat(fmt)
        self.recorder.setQuality(QMediaRecorder.Quality.HighQuality)
        self.recorder.errorOccurred.connect(lambda *_: self.status.setText(f"Erro ao gravar: {self.recorder.errorString()}"))
        self.recorder.recorderStateChanged.connect(self._state)
        tmp = Path(tempfile.gettempdir()) / f"gotit-gravacao-{int(time.time() * 1000)}.m4a"
        self.target = tmp
        self.recorder.setOutputLocation(QUrl.fromLocalFile(str(tmp)))

    def _state(self, state) -> None:
        if state == QMediaRecorder.RecorderState.StoppedState and self._finishing:
            loc = self.recorder.actualLocation().toLocalFile()
            self.path = Path(loc) if loc else self.target
            self.accept()

    _finishing = False

    def toggle(self) -> None:
        if self.recorder is None:
            return
        if self.recorder.recorderState() == QMediaRecorder.RecorderState.StoppedState:
            self.recorder.record()
            self._started = time.monotonic()
            self.timer.start(200)
            self.status.setText("Gravando…")
            self.rec.setText("Parar")
            self.pause.setEnabled(True)
            self.done.setEnabled(True)
        else:
            self.finish()

    def toggle_pause(self) -> None:
        if self.recorder.recorderState() == QMediaRecorder.RecorderState.PausedState:
            self.recorder.record()
            self._paused_total += time.monotonic() - self._paused_at
            self.pause.setText("Pausar")
            self.status.setText("Gravando…")
        else:
            self.recorder.pause()
            self._paused_at = time.monotonic()
            self.pause.setText("Continuar")
            self.status.setText("Pausado")

    def _tick(self) -> None:
        if self.recorder and self.recorder.recorderState() == QMediaRecorder.RecorderState.RecordingState:
            self.duration = time.monotonic() - self._started - self._paused_total
            self.clock.setText(fmt_time(self.duration))

    def finish(self) -> None:
        if self.recorder is None:
            return
        self._finishing = True
        self.timer.stop()
        self.status.setText("Terminando a gravação…")
        self.recorder.stop()
        QTimer.singleShot(4000, self._fallback)

    def _fallback(self) -> None:
        if self.isVisible() and self.target.exists():
            self.path = self.target
            self.accept()

    def reject(self) -> None:
        if self.recorder is not None and self.recorder.recorderState() != QMediaRecorder.RecorderState.StoppedState:
            self._finishing = False
            self.recorder.stop()
        super().reject()


class VideoDialog(QDialog):
    def __init__(self, path: Path, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title or "Vídeo")
        self.resize(960, 600)
        self.setStyleSheet("background: #0B0F14; color: white;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        from PySide6.QtMultimediaWidgets import QVideoWidget
        self.video = QVideoWidget()
        lay.addWidget(self.video, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 0, 12, 0)
        self.play = QToolButton()
        self.play.setIcon(icons.icon("pause", "#FFFFFF"))
        self.play.setIconSize(icons.size(22))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.time = QLabel("0:00 / 0:00")
        full = QToolButton()
        full.setIcon(icons.icon("fit", "#FFFFFF"))
        full.setToolTip("Tela cheia")
        bar.addWidget(self.play)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.time)
        bar.addWidget(full)
        lay.addLayout(bar)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.positionChanged.connect(self._pos)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.play.clicked.connect(self._toggle)
        full.clicked.connect(lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen())
        self.player.play()

    def _pos(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time.setText(f"{fmt_time(ms / 1000)} / {fmt_time(self.player.duration() / 1000)}")

    def _toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play.setIcon(icons.icon("play", "#FFFFFF"))
        else:
            self.player.play()
            self.play.setIcon(icons.icon("pause", "#FFFFFF"))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self._toggle()
            return
        if e.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.player.stop()
        super().closeEvent(e)


class FrameGrabber(QObject):
    """Primeiro quadro e duração de um vídeo (ou só a duração de um áudio), sem mostrar nada."""
    done = Signal(object, float)

    def __init__(self, path: Path, parent=None, want_frame: bool = True):
        super().__init__(parent)
        self._image = None
        self._dur = 0.0
        self._finished = False
        if not HAVE_MULTIMEDIA:
            QTimer.singleShot(0, self._finish)
            return
        self.player = QMediaPlayer(self)
        self.player.durationChanged.connect(self._duration)
        if want_frame:
            self.sink = QVideoSink(self)
            self.player.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self._frame)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.mediaStatusChanged.connect(self._status)
        self.want_frame = want_frame
        if want_frame:
            self.player.play()
        QTimer.singleShot(6000, self._finish)

    def _duration(self, ms):
        self._dur = ms / 1000.0
        if not self.want_frame and ms > 0:
            self._finish()

    def _status(self, status):
        if status in (QMediaPlayer.MediaStatus.InvalidMedia,):
            self._finish()

    def _frame(self, frame):
        if self._image is None and frame.isValid():
            img = frame.toImage()
            if not img.isNull():
                self._image = img.copy()
                self._finish()

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        try:
            if HAVE_MULTIMEDIA:
                self.player.stop()
        except Exception:
            pass
        self.done.emit(self._image, self._dur)
