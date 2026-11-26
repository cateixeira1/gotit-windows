"""Exportar para o Prumo PDF: a nota sai em PDF e abre no Prumo PDF (o leitor de PDF da Color
Software), para destacar, anotar, assinar e fazer OCR lá. Se o Prumo não estiver instalado neste
computador, abre a página dele na Microsoft Store.

Como o Got It! acha o Prumo no Windows (o instalador do Prumo, Inno Setup, registra estes
lugares — ver build/PrumoPDF.iss no repositório prumo-pdf-windows):
- o comando "abrir" do tipo de arquivo ``PrumoPDF.Document`` (HKCU e HKLM\\Software\\Classes);
- o local da instalação na lista de programas (AppId {6F1B2C4E-8D3A-4F5B-9C7E-2A1D0E3F4B5C});
- as pastas padrão (Arquivos de Programas e a pasta de programas do usuário).
O Prumo abre o arquivo passado na linha de comando e, se já estiver aberto, recebe o arquivo na
janela que já existe."""

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

# Quando o Prumo PDF for publicado na Microsoft Store, ponha aqui o Store ID (Product ID, 12
# caracteres, ex.: 9NBLGGH4R32N): o botão passa a abrir a página do app. Sem ele, abre a busca
# da Store por "Prumo PDF".
STORE_PRODUCT_ID = ""
STORE_SEARCH = "ms-windows-store://search/?query=Prumo PDF"
RELEASES = "https://github.com/cateixeira1/prumo-pdf-windows/releases"
EXE = "PrumoPDF.exe"
APP_ID = "{6F1B2C4E-8D3A-4F5B-9C7E-2A1D0E3F4B5C}_is1"


def store_url() -> str:
    return f"ms-windows-store://pdp/?ProductId={STORE_PRODUCT_ID}" if STORE_PRODUCT_ID else STORE_SEARCH


def _exe_from_command(command: str) -> str | None:
    """'"C:\\Program Files\\Prumo PDF\\PrumoPDF.exe" "%1"' -> caminho do .exe."""
    command = (command or "").strip()
    if not command:
        return None
    m = re.match(r'^"([^"]+)"', command)
    path = m.group(1) if m else (shlex.split(command, posix=False) or [""])[0]
    return path if path.lower().endswith(".exe") else None


def _registry_candidates() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    for root in roots:
        try:
            with winreg.OpenKey(root, r"Software\Classes\PrumoPDF.Document\shell\open\command") as k:
                exe = _exe_from_command(winreg.QueryValueEx(k, "")[0])
                if exe:
                    out.append(exe)
        except OSError:
            pass
    for root in roots:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}", 0,
                                    winreg.KEY_READ | view) as k:
                    loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                    if loc:
                        out.append(str(Path(loc) / EXE))
            except OSError:
                pass
    return out


def find() -> str | None:
    """Caminho do PrumoPDF.exe instalado, ou None."""
    candidates = []
    env = os.environ.get("GOTIT_PRUMO_EXE")
    if env:
        candidates.append(env)
    candidates += _registry_candidates()
    if sys.platform == "win32":
        for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            base = os.environ.get(var)
            if base:
                candidates.append(str(Path(base) / "Prumo PDF" / EXE))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(str(Path(local) / "Programs" / "Prumo PDF" / EXE))
    for c in candidates:
        try:
            if c and Path(c).is_file():
                return c
        except OSError:
            continue
    return None


def open_pdf(exe: str, pdf: str) -> bool:
    from PySide6.QtCore import QProcess
    ok, _pid = QProcess.startDetached(exe, [pdf], str(Path(exe).parent))
    return bool(ok)


def open_store() -> bool:
    """Página do Prumo na Microsoft Store (ou a busca por ele); sem a Store, a página de downloads."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    if QDesktopServices.openUrl(QUrl(store_url())):
        return True
    return QDesktopServices.openUrl(QUrl(RELEASES))


def export_folder() -> Path:
    """Documentos\\Got It — PDFs: os PDFs mandados ao Prumo ficam num lugar fácil de achar."""
    from PySide6.QtCore import QStandardPaths
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
    folder = Path(docs) / "Got It — PDFs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def pdf_path(title: str) -> Path:
    name = re.sub(r'[\\/:*?"<>|]+', "-", (title or "Nota").strip()) or "Nota"
    folder = export_folder()
    path = folder / f"{name}.pdf"
    n = 2
    while path.exists():             # nunca por cima: o PDF anterior pode ter anotações do Prumo
        path = folder / f"{name} ({n}).pdf"
        n += 1
    return path
