"""Got It! para Windows — ponto de entrada.

    GotIt.exe                       abre o app
    GotIt.exe --data PASTA          usa outra pasta de dados (testes)
    GotIt.exe --demo PASTA [--screen NOME --shot ARQUIVO.png]   biblioteca de demonstração e captura de tela
    GotIt.exe --self-test RELATORIO.json                        confere o pacote (usado pelo instalador)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

if getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core


def _app_id() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(core.APP_USER_MODEL_ID)
        except Exception:
            pass


def make_app(argv):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(core.APP_NAME)
    app.setOrganizationName(core.ORG_NAME)
    app.setApplicationVersion(core.APP_VERSION)
    app.setWindowIcon(QIcon(str(core.asset_path("GotIt.ico"))))
    import theme
    theme.apply(app)
    theme.register_fonts()
    return app


def self_test(report: str) -> int:
    """Confere se o pacote abre: Qt, fontes, PDF, banco com FTS5, mídia e IA (o que houver)."""
    result = {"version": core.APP_VERSION, "ok": False, "checks": {}}
    try:
        app = make_app([sys.argv[0], "-platform", "offscreen"] if sys.platform != "win32" else [sys.argv[0]])
        import tempfile
        import theme
        result["checks"]["fonts"] = theme.register_fonts()
        from store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            import model
            doc = store.create(model.new_document("Teste"))
            doc["story"] = {"html": "", "text": "indenização"}
            store.save(doc)
            result["checks"]["fts5"] = len(store.search("indenizacao")) == 1
            store.close()
        import pypdfium2
        result["checks"]["pdfium"] = pypdfium2.version.PDFIUM_INFO.build if hasattr(pypdfium2, "version") else True
        try:
            from PySide6 import QtMultimedia  # noqa: F401
            result["checks"]["multimedia"] = True
        except Exception as e:
            result["checks"]["multimedia"] = f"ausente: {e}"
        import mathink
        import mathsolve
        line = [[(10.0, 0.0), (12.0, 40.0)],                          # 1
                [(30.0, 20.0), (50.0, 20.0)], [(40.0, 10.0), (40.0, 30.0)],   # +
                [(65.0, 1.0), (64.0, 41.0)],                          # 1
                [(80.0, 15.0), (100.0, 15.0)], [(80.0, 25.0), (100.0, 25.0)]]  # =
        result["checks"]["mathink"] = mathink.read(line)[:1]
        result["checks"]["mathsolve"] = mathsolve.answer_text("12+7=") == "19"
        try:
            import handwriting
            result["checks"]["windows_handwriting"] = handwriting.recognizers() or handwriting._state.get("error") or []
        except Exception as e:
            result["checks"]["windows_handwriting"] = f"erro: {type(e).__name__}"
        for name in ("litert_lm", "faster_whisper", "winrt.windows.ui.input.inking"):
            try:
                __import__(name)
                result["checks"][name] = True
            except Exception as e:
                result["checks"][name] = f"ausente: {type(e).__name__}"
        result["ok"] = bool(result["checks"]["fts5"])
        del app
    except Exception:
        result["error"] = traceback.format_exc()
    Path(report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data")
    parser.add_argument("--demo")
    parser.add_argument("--screen")
    parser.add_argument("--shot")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--self-test")
    parser.add_argument("files", nargs="*")
    args, rest = parser.parse_known_args()
    if args.self_test:
        return self_test(args.self_test)
    _app_id()
    app = make_app([sys.argv[0]] + rest)
    data = args.data
    if args.demo:
        import demo
        data = demo.build(Path(args.demo), keep=args.keep)
    from window import MainWindow
    win = MainWindow(Path(data) if data else None)
    if args.screen:
        import demo
        demo.show(win, args.screen, args.shot)
        return app.exec()
    win.show()
    win.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
