"""Ajustes: ao abrir o app, fonte padrão, biblioteca e cópia de segurança, inteligência local
(modelos baixados só quando pedidos) e sobre."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

import core
import theme


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.settings = window.settings
        self.setWindowTitle("Ajustes")
        self.resize(620, 720)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setSpacing(12)
        scroll.setWidget(host)
        outer.addWidget(scroll)

        g = QGroupBox("Ao abrir o app")
        f = QFormLayout(g)
        self.launch = QComboBox()
        for key, title in (("last", "Abrir a última nota"), ("list", "Mostrar só o menu"), ("new", "Criar uma nota nova"),
                           ("simple", "Criar uma nota simples")):
            self.launch.addItem(title, key)
        self.launch.setCurrentIndex(max(0, self.launch.findData(self.settings.value("onLaunch", "last"))))
        self.launch.currentIndexChanged.connect(lambda: self.settings.setValue("onLaunch", self.launch.currentData()))
        f.addRow("Mostrar", self.launch)
        lay.addWidget(g)

        g = QGroupBox("Texto")
        f = QFormLayout(g)
        self.font = QComboBox()
        for fam in theme.text_families():
            self.font.addItem(fam)
            self.font.setItemData(self.font.count() - 1, QFont(fam), Qt.ItemDataRole.FontRole)
        self.font.setCurrentText(self.settings.value("defaultFont", theme.default_text_family()))
        self.font.currentTextChanged.connect(lambda t: self.settings.setValue("defaultFont", t))
        self.size = QSpinBox()
        self.size.setRange(8, 36)
        self.size.setSuffix(" pt")
        self.size.setValue(int(float(self.settings.value("defaultFontSize", 12))))
        self.size.valueChanged.connect(lambda v: self.settings.setValue("defaultFontSize", v))
        f.addRow("Fonte padrão", self.font)
        f.addRow("Tamanho padrão", self.size)
        hint = QLabel("Vale para o texto sem fonte escolhida; muda ao abrir a nota de novo.")
        hint.setStyleSheet(f"color: {theme.MUTED};")
        f.addRow(hint)
        lay.addWidget(g)

        g = QGroupBox("Biblioteca")
        v = QVBoxLayout(g)
        path = QLabel(str(window.store.data_dir))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setWordWrap(True)
        v.addWidget(QLabel("As notas ficam só neste computador, na pasta:"))
        v.addWidget(path)
        row = QHBoxLayout()
        open_btn = QPushButton("Abrir a pasta")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(window.store.data_dir))))
        backup = QPushButton("Fazer cópia de segurança…")
        backup.setProperty("primary", True)
        backup.clicked.connect(self._backup)
        restore = QPushButton("Restaurar de uma cópia…")
        restore.clicked.connect(self._restore)
        row.addWidget(open_btn)
        row.addWidget(backup)
        row.addWidget(restore)
        v.addLayout(row)
        note = QLabel("A cópia é uma pasta comum (pendrive, HD externo, OneDrive). Restaurar não duplica notas: "
                      "fica a versão mais nova de cada uma.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        v.addWidget(note)
        lay.addWidget(g)

        g = QGroupBox("Inteligência no computador (sem internet depois de baixar)")
        v = QVBoxLayout(g)
        self.ai_box = v
        self._ai_rows()
        lay.addWidget(g)

        g = QGroupBox("Sobre")
        v = QVBoxLayout(g)
        about = QLabel(f"<b>{core.APP_NAME}</b> para Windows, versão {core.APP_VERSION}<br>"
                       "Color Software · colorsoftware.com.br<br><br>"
                       "Fontes de escrita à mão: Caveat, Patrick Hand, Kalam e Indie Flower (SIL Open Font License). "
                       "Qt for Python (LGPL), PDFium (BSD), LiteRT-LM (Apache 2.0), Gemma 4 e EmbeddingGemma (Apache 2.0), "
                       "faster-whisper e Whisper (MIT).")
        about.setWordWrap(True)
        about.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(about)
        lay.addWidget(g)
        lay.addStretch(1)
        close = QPushButton("Fechar")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        outer.addLayout(row)

    def _ai_rows(self) -> None:
        try:
            import models
        except Exception:
            self.ai_box.addWidget(QLabel("Os componentes de IA não estão neste pacote."))
            return
        for spec in models.SPECS:
            self.ai_box.addWidget(models.ModelRow(self.window, spec, self))
        import handwriting
        hw = QLabel(("✓ " if handwriting.available() else "• ") + handwriting.status_text())
        hw.setWordWrap(True)
        self.ai_box.addWidget(hw)

    def _backup(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Onde guardar a cópia de segurança", str(Path.home()))
        if not folder:
            return
        self.window.editor.save_now()
        dest = self.window.store.backup_to(Path(folder))
        QMessageBox.information(self, "Cópia de segurança", f"Cópia feita em:\n{dest}")

    def _restore(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pasta da cópia de segurança", str(Path.home()))
        if not folder:
            return
        try:
            n = self.window.store.restore_from(Path(folder))
        except FileNotFoundError as e:
            QMessageBox.warning(self, "Restaurar", str(e))
            return
        self.window.sidebar.refresh()
        QMessageBox.information(self, "Restaurar", f"{n} nota(s) trazidas da cópia.")
