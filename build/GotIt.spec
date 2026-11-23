# -*- mode: python ; coding: utf-8 -*-
# Empacotamento do Got It! com o PyInstaller (modo pasta, que abre mais rápido que arquivo único).
# Uso: pyinstaller build/GotIt.spec --noconfirm

import os
import re
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "app")

datas = [(os.path.join(ROOT, "assets"), "assets")]
binaries = []
hiddenimports = [m[:-3] for m in os.listdir(APP) if m.endswith(".py")]

# Inteligência no computador: motores e arquivos que vêm com cada pacote (os modelos são baixados depois).
for pkg in ("litert_lm", "faster_whisper", "ctranslate2", "av", "onnxruntime", "tokenizers"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # pacote opcional ausente: o app explica o que falta
        print(f"[GotIt.spec] {pkg} ausente: {exc}")
hiddenimports += collect_submodules("winrt")
binaries += collect_dynamic_libs("pillow_heif")
datas += collect_data_files("pypdfium2_raw") + collect_data_files("pypdfium2")

a = Analysis(
    [os.path.join(APP, "main.py")],
    pathex=[APP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest", "torch", "tensorflow",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)

# Traduções do próprio Qt: só português e inglês (botões padrão dos diálogos).
def _drop_data(entry):
    dest = entry[0].replace("\\", "/").lower()
    if "pyside6/translations/" in dest and dest.endswith(".qm"):
        stem = os.path.basename(dest)[:-3]
        return not (stem.endswith("_pt_br") or stem.endswith("_pt") or stem.endswith("_en"))
    return False


a.datas = [d for d in a.datas if not _drop_data(d)]
a.binaries = [b for b in a.binaries if os.path.basename(b[0]).lower() != "opengl32sw.dll"]

pyz = PYZ(a.pure)

_ver = re.search(r'APP_VERSION = "([0-9.]+)"', open(os.path.join(APP, "core.py"), encoding="utf-8").read()).group(1)
_nums = tuple(int(x) for x in (_ver.split(".") + ["0", "0", "0"])[:4])
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums),
    kids=[StringFileInfo([StringTable("041604B0", [
        StringStruct("CompanyName", "Color Software"),
        StringStruct("FileDescription", "Got It!"),
        StringStruct("FileVersion", _ver),
        StringStruct("ProductName", "Got It!"),
        StringStruct("ProductVersion", _ver),
        StringStruct("OriginalFilename", "GotIt.exe"),
        StringStruct("LegalCopyright", "Color Software"),
    ])]), VarFileInfo([VarStruct("Translation", [0x0416, 1200])])])

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GotIt",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "assets", "GotIt.ico"),
    version=version_info,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GotIt")
