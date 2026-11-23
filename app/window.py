"""Janela principal: menu à esquerda e a nota aberta à direita."""

from __future__ import annotations

import copy

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

import core
import icons
import model
import theme
from assets import Assets
from editor import Editor
from sidebar import Sidebar
from store import Store
from thumbs import Thumbs


class EmptyState(QWidget):
    def __init__(self, window):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(2)
        logo = QLabel()
        from PySide6.QtGui import QPixmap
        pm = QPixmap(str(core.asset_path("icon-256.png")))
        if not pm.isNull():
            logo.setPixmap(pm.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Got It!")
        title.setFont(theme.ui_font(22, True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Escreva, desenhe, grave e junte tudo numa nota.")
        sub.setStyleSheet(f"color: {theme.MUTED};")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout()
        row.addStretch()
        for icon, text, fn in (("plus", "Nova nota", window.new_note), ("simple", "Nova nota simples", window.new_simple_note),
                               ("teia", "Nova Teia", lambda: window.new_teia([]))):
            b = QPushButton(icons.icon(icon), text)
            if text == "Nova nota":
                b.setProperty("primary", True)
                b.setIcon(icons.icon(icon, "#FFFFFF"))
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        for w in (logo, title, sub):
            lay.addWidget(w)
        lay.addSpacing(12)
        lay.addLayout(row)
        lay.addStretch(3)
        self.setStyleSheet(f"background: {theme.DESK};")


class MainWindow(QMainWindow):
    def __init__(self, data_dir=None):
        super().__init__()
        self.settings = QSettings(core.ORG_NAME, core.SETTINGS_APP)
        self.store = Store(data_dir or core.default_data_dir())
        self.store.ensure_index()
        self.assets = Assets(self.store)
        self.thumbs = Thumbs(self)
        import intelligence
        self.ai = intelligence.Intelligence(self)
        self.setWindowTitle(core.APP_NAME)
        self.setWindowIcon(QIcon(str(core.asset_path("GotIt.ico"))))
        self.resize(1440, 920)
        central = QWidget()
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = Sidebar(self)
        self.stack = QStackedWidget()
        self.empty = EmptyState(self)
        self.editor = Editor(self)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.editor)
        lay.addWidget(self.sidebar)
        lay.addWidget(self.stack, 1)
        self.editor.saved.connect(self._saved)
        self.editor.openRequested.connect(self.open_note)
        self.editor.sidebarToggle.connect(self.toggle_sidebar)
        self.editor.trashed.connect(self._after_trash)
        self.editor.teiaRequested.connect(self.new_teia)
        self.editor.assistantRequested.connect(lambda: self.ai.open_assistant())
        QShortcut(QKeySequence("Ctrl+\\"), self, self.toggle_sidebar)
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_note)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self, self.new_simple_note)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, lambda: (self.sidebar.show(), self.sidebar.search.setFocus()))
        self._sidebar_refresh = QTimer(self, singleShot=True, interval=400, timeout=self.sidebar.refresh)
        self.gc_timer = QTimer(self, interval=5 * 60 * 1000, timeout=lambda: self.store.collect_garbage())
        self.gc_timer.start()
        if self.settings.value("sidebarHidden", "false") == "true":
            self.sidebar.hide()

    # ------------------------------------------------------------------ início
    def start(self) -> None:
        mode = self.settings.value("onLaunch", "last")
        if mode == "new":
            self.new_note()
        elif mode == "simple":
            self.new_simple_note()
        elif mode == "last":
            last = self.store.last_opened()
            if last:
                self.open_note(last)

    # ------------------------------------------------------------------ notas
    def _count(self, kind: str) -> int:
        return len(self.store.notes(kind=kind)) + len([n for n in self.store.notes(trashed=True) if n.kind == kind])

    def new_note(self) -> None:
        doc = model.new_document(f"Nota {len(self.store.notes(kind='note')) + 1}")
        self.store.create(doc, self.sidebar.folder_id)
        self.sidebar.browsing = None
        self.open_note(doc["id"])

    def new_simple_note(self) -> None:
        doc = model.new_document(f"Nota {len(self.store.notes(kind='note')) + 1}", simple=True)
        self.store.create(doc, self.sidebar.folder_id)
        self.open_note(doc["id"])

    def new_teia(self, note_ids: list) -> None:
        doc = model.new_document(f"Teia {len(self.store.notes(kind='web')) + 1}", kind="web")
        self.store.create(doc, self.sidebar.folder_id)
        self.open_note(doc["id"])
        if note_ids:
            self.editor.add_note_cards(note_ids)
        else:
            QTimer.singleShot(50, self.editor.add_notes_to_teia)

    def open_note(self, doc_id: str, find: str | None = None, part: str | None = None) -> None:
        if self.editor.doc is not None and self.editor.doc["id"] == doc_id and not find:
            return
        doc = self.store.load(doc_id)
        if doc is None:
            QMessageBox.information(self, "Nota", "Esta nota não existe mais.")
            return
        info = self.store.info(doc_id)
        if info and info.trashed_at:
            self.store.restore(doc_id)
        self.stack.setCurrentWidget(self.editor)
        self.editor.open_document(doc, find, part)
        self.setWindowTitle(f"{doc['title']} — {core.APP_NAME}")
        self.sidebar.set_active(doc_id)

    def open_hit(self, hit, query: str) -> None:
        self.open_note(hit.doc_id, find=query, part=hit.part)

    def rename_note(self, doc_id: str, title: str) -> None:
        if self.editor.doc is not None and self.editor.doc["id"] == doc_id:
            self.editor.bar.title.setText(title)
            self.editor._title_edited()
        else:
            self.store.rename(doc_id, title)
        self.sidebar.refresh()

    def trash_note(self, doc_id: str) -> None:
        if self.editor.doc is not None and self.editor.doc["id"] == doc_id:
            self.editor.trash_note()
            return
        self.store.trash(doc_id)
        self._after_trash(doc_id)

    def _after_trash(self, doc_id: str) -> None:
        if self.editor.doc is None:
            self.stack.setCurrentWidget(self.empty)
            self.setWindowTitle(core.APP_NAME)
            self.sidebar.active_id = None
        self.sidebar.refresh()

    def _saved(self, doc_id: str) -> None:
        self.ai.note_saved(doc_id)
        if self.editor.doc is not None:
            self.setWindowTitle(f"{self.editor.doc['title']} — {core.APP_NAME}")
        self._sidebar_refresh.start()

    def thumbnail_updated(self, doc_id: str) -> None:
        self._sidebar_refresh.start()

    def refresh(self) -> None:
        self.sidebar.refresh()

    def toggle_sidebar(self) -> None:
        self.sidebar.setVisible(not self.sidebar.isVisible())
        self.settings.setValue("sidebarHidden", "false" if self.sidebar.isVisible() else "true")

    def resolve_note(self, doc_id: str | None):
        if not doc_id:
            return None
        info = self.store.info(doc_id)
        if info is None or info.trashed_at:
            return None
        created = model.parse_iso(info.created).astimezone()
        return {"title": info.title, "created": created.strftime("%d/%m/%Y"), "createdRaw": info.created,
                "preview": self.thumbs.get(info.id, info.revision) if info.kind == "note" else None}

    def fill_move_menu(self, menu: QMenu, doc_ids: list) -> None:
        def move(folder_id):
            if self.editor.doc is not None:
                self.editor.save_now()
            for d in doc_ids:
                self.store.move_note(d, folder_id)
            self.sidebar.refresh()
        menu.addAction(icons.icon("back"), "Início").triggered.connect(lambda: move(None))

        def add(parent, depth):
            for f in self.store.folders(parent):
                menu.addAction(icons.icon("folder"), "    " * depth + f.name).triggered.connect(lambda _=False, fid=f.id: move(fid))
                add(f.id, depth + 1)
        add(None, 0)

    def fill_folder_move_menu(self, menu: QMenu, folder_id: str) -> None:
        def move(parent):
            if not self.store.move_folder(folder_id, parent):
                QMessageBox.information(self, "Mover pasta", "Uma pasta não vai para dentro dela mesma nem de uma subpasta.")
            self.sidebar.refresh()
        menu.addAction(icons.icon("back"), "Início").triggered.connect(lambda: move(None))

        def add(parent, depth):
            for f in self.store.folders(parent):
                if f.id == folder_id:
                    continue
                menu.addAction(icons.icon("folder"), "    " * depth + f.name).triggered.connect(lambda _=False, fid=f.id: move(fid))
                add(f.id, depth + 1)
        add(None, 0)

    # ------------------------------------------------------------------ janelas
    def open_trash(self) -> None:
        import dialogs
        self.editor.save_now()
        dlg = dialogs.TrashDialog(self.store, self)
        dlg.exec()
        if dlg.changed:
            self.sidebar.refresh()

    def open_settings(self) -> None:
        import settings_dialog
        self.editor.save_now()
        dlg = settings_dialog.SettingsDialog(self)
        dlg.exec()
        self.sidebar.refresh()

    # ------------------------------------------------------------------ inteligência local
    def assistant_available(self) -> bool:
        return self.ai.assistant_visible()

    def handwriting_available(self) -> bool:
        return self.ai.handwriting_available()

    def explain_handwriting(self) -> None:
        self.ai.explain_handwriting()

    def recognize_handwriting(self, editor, strokes) -> None:
        self.ai.recognize_handwriting(editor, strokes)

    def transcribe(self, editor, item) -> None:
        self.ai.transcribe(editor, item)

    def remove_background(self, editor, item) -> None:
        self.ai.remove_background(editor, item)

    def ask_assistant_about(self, text: str) -> None:
        self.ai.open_assistant(prefill=text)

    def search_by_meaning(self, query: str, exclude: set) -> list:
        return self.ai.search_by_meaning(query, exclude)

    # ------------------------------------------------------------------ fechar
    def closeEvent(self, e):
        self.editor.save_now()
        for t in (self._sidebar_refresh, self.sidebar.search_timer, self.gc_timer, self.editor.save_timer,
                  self.editor.thumb_timer, self.editor.state_timer, self.editor.hw_timer):
            t.stop()
        self.editor.media.stop()
        self.editor.close_document()
        self.ai.shutdown()
        self.store.close()
        super().closeEvent(e)
