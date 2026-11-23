import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from main import make_app
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or make_app([sys.argv[0]])
    yield app


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    monkeypatch.setenv("GOTIT_DATA", str(tmp_path / "data"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    from window import MainWindow
    win = MainWindow(tmp_path / "data")
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()
    yield win
    win.editor.dirty = False
    win.close()
    qapp.processEvents()


def pump(qapp, ms: int = 50):
    import time
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        qapp.processEvents()
