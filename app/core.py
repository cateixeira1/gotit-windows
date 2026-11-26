"""Versão, pastas e ajustes do Got It! para Windows."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Got It!"
APP_VERSION = "0.1.4"
APP_USER_MODEL_ID = "ColorSoftware.GotIt"
ORG_NAME = "Color Software"
SETTINGS_APP = "Got It"


def resource_dir() -> Path:
    """Pasta dos recursos (fontes, ícones): ao lado do app empacotado ou na raiz do repositório."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def asset_path(*parts: str) -> Path:
    return resource_dir().joinpath("assets", *parts)


def default_data_dir() -> Path:
    """Notas, mídias e índice de busca. Fora do OneDrive de propósito: um banco SQLite aberto não
    deve ser sincronizado arquivo a arquivo (a cópia de segurança fica em Ajustes)."""
    override = os.environ.get("GOTIT_DATA")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / ORG_NAME / "Got It"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "gotit"


def cache_dir(data_dir: Path) -> Path:
    path = data_dir / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir(data_dir: Path) -> Path:
    path = data_dir / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path
