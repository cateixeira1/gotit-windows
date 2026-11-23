"""Modelo das notas: um dicionário JSON com os mesmos nomes de campos do Got It! para iPhone
(CanvasDocument), adaptado ao editor do Windows.

Unidade interna: ponto (1/72 pol.). A4 = 210 × 297 mm. O texto principal da nota (a área do
Word) fica em ``story`` como HTML do Qt; objetos (caixas de texto, formas, post-its, imagens,
PDFs, áudio, vídeo, tabelas, cartões da Teia) ficam em ``blocks``, cada um numa página
(``pageID``) com o quadro relativo a ela; a tinta fica em ``strokes``.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

MM = 72 / 25.4
CM = 72 / 2.54
A4 = (210 * MM, 297 * MM)
A5 = (148 * MM, 210 * MM)

# Margens "Normal" do Word em português: 2,5 cm em cima e embaixo, 3 cm nos lados.
WORD_MARGINS = {"top": 2.5 * CM, "bottom": 2.5 * CM, "left": 3 * CM, "right": 3 * CM}

STICKY_COLORS = [  # mesmas cores do iPhone (StickyNoteColor)
    ("Amarelo", "#FFF27A"), ("Rosa", "#FFB8D2"), ("Azul", "#A9DDF7"),
    ("Verde", "#C6EBA1"), ("Laranja", "#FFC98A"),
]
STICKY_SIDE = 200.0
CALENDAR_SIZE = (132.0, 148.0)
AUDIO_HEIGHT = 60.0

STICKER_EMOJI = [
    "⭐", "✅", "❗", "❓", "⚠️", "📌", "📎", "💡", "🔥", "🎯", "🚩", "🛑",
    "❤️", "👍", "👏", "🎉", "😀", "😂", "😍", "🤔", "🙏", "💪", "👀", "✨",
    "⏰", "📝", "📚", "⚖️", "🏥", "💊", "🩺", "📞", "✉️", "💰", "📈",
    "🏠", "🚗", "✈️", "☕", "🍰", "🐱", "☀️", "🌧️", "🔒", "🔑", "➡️", "⬇️",
]

SHAPE_KINDS = ["rectangle", "ellipse", "diamond", "triangle", "line", "arrow"]
SHAPE_TITLES = {"rectangle": "Retângulo", "ellipse": "Elipse", "diamond": "Losango",
                "triangle": "Triângulo", "line": "Linha", "arrow": "Seta"}

PAPER_KINDS = [("plain", "Liso"), ("ruled", "Caderno"), ("grid", "Quadriculado"), ("checker", "Xadrez")]
RULED_LINE = 0.8 * CM   # faixa de cada linha do papel caderno


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)


def default_canvas(size=A4) -> dict:
    return {
        "size": {"width": size[0], "height": size[1]},
        "displayUnit": "centimeters",
        "margins": dict(WORD_MARGINS),
        "header": None,
        "footer": None,
        "pageNumbers": None,
        "paper": None,
        "simpleNote": False,
        "recognizeDiagrams": True,
        "solveEquations": True,
        "handwritingToText": False,
        "handwritingFont": "Caveat",
    }


def new_page(auto: bool = False) -> dict:
    page = {"id": new_id()}
    if auto:
        page["auto"] = True
    return page


def new_document(title: str = "Nota sem título", kind: str = "note", simple: bool = False) -> dict:
    stamp = now_iso()
    doc_id = new_id()
    if kind == "web":
        canvas = default_canvas((A4[1], A4[0]))   # Teia nova em paisagem
        canvas["margins"] = {"top": 24.0, "bottom": 24.0, "left": 24.0, "right": 24.0}
        canvas["recognizeDiagrams"] = True
    elif simple:
        canvas = default_canvas(A5)
        canvas["simpleNote"] = True
        canvas["margins"] = {"top": 2 * RULED_LINE + 18, "bottom": RULED_LINE, "left": 1.6 * CM, "right": 0.8 * CM}
        canvas["paper"] = {"kind": "ruled", "spacing": RULED_LINE}
    else:
        canvas = default_canvas()
    return {
        "format": "gotit-windows/1",
        "id": doc_id,
        "title": title,
        "kind": kind,
        "revision": 0,
        "createdAt": stamp,
        "updatedAt": stamp,
        "canvas": canvas,
        "pages": [{"id": doc_id}],          # como no iPhone, a 1ª página tem o id da nota
        "story": {"html": "", "text": ""},
        "blocks": [],
        "strokes": [],
        "relations": [],
        "namedStyles": [],
    }


def normalize(doc: dict) -> dict:
    """Completa campos que faltam (notas de versões anteriores abrem iguais)."""
    doc = copy.deepcopy(doc)
    base = new_document(doc.get("title") or "Nota sem título", doc.get("kind", "note"),
                        bool((doc.get("canvas") or {}).get("simpleNote")))
    for key, value in base.items():
        if key in ("id", "createdAt", "updatedAt", "pages"):
            continue
        doc.setdefault(key, value)
    canvas = doc.setdefault("canvas", {})
    for key, value in base["canvas"].items():
        canvas.setdefault(key, value)
    if not doc.get("pages"):
        doc["pages"] = [{"id": doc["id"]}]
    doc.setdefault("createdAt", now_iso())
    doc.setdefault("updatedAt", doc["createdAt"])
    doc.setdefault("story", {"html": "", "text": ""})
    return doc


def page_size(doc: dict) -> tuple[float, float]:
    size = doc["canvas"]["size"]
    return float(size["width"]), float(size["height"])


def page_index(doc: dict, page_id: str | None) -> int:
    for i, page in enumerate(doc["pages"]):
        if page["id"] == page_id:
            return i
    return 0


def text_margins(doc: dict) -> dict:
    """Margens do texto em cada página, já descontando cabeçalho e rodapé (o texto é repaginado
    abaixo do cabeçalho e acima do rodapé, como no iPhone)."""
    canvas = doc["canvas"]
    m = dict(canvas.get("margins") or WORD_MARGINS)
    header, footer = canvas.get("header"), canvas.get("footer")
    numbers = canvas.get("pageNumbers")
    band_top, band_bottom = header_band_rect_y(doc)
    if header and header_has_content(header) or (numbers and numbers.get("position") == "header"):
        m["top"] = max(m["top"], band_top[1] + 10)
    if footer and header_has_content(footer) or (numbers and numbers.get("position", "footer") == "footer"):
        m["bottom"] = max(m["bottom"], page_size(doc)[1] - band_bottom[0] + 10)
    return m


def header_has_content(band: dict | None) -> bool:
    return bool(band and (band.get("text") or band.get("image")))


def header_band_rect_y(doc: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """Faixas (y0, y1) do cabeçalho e do rodapé numa página."""
    w, h = page_size(doc)
    canvas = doc["canvas"]
    header = canvas.get("header") or {}
    footer = canvas.get("footer") or {}
    hh = float(header.get("height") or 36)
    fh = float(footer.get("height") or 36)
    top0 = 0.45 * CM + 8
    return (top0, top0 + hh), (h - top0 - fh, h - top0)


def page_number_text(fmt: str, number: int, total: int) -> str:
    if fmt == "page":
        return f"Página {number}"
    if fmt == "page_of":
        return f"Página {number} de {total}"
    if fmt == "dash":
        return f"– {number} –"
    if fmt == "slash":
        return f"{number}/{total}"
    return str(number)


def generic_folder_name(existing: list[str]) -> str:
    """"Pasta N": N = maior número já usado num nome genérico + 1 (sem preencher lacunas)."""
    highest = 0
    for name in existing:
        parts = name.strip().split()
        if len(parts) == 2 and parts[0] == "Pasta" and parts[1].isdigit():
            highest = max(highest, int(parts[1]))
    return f"Pasta {highest + 1}"


def blocks_on_page(doc: dict, page_id: str) -> list[dict]:
    first = doc["pages"][0]["id"]
    return [b for b in doc["blocks"] if (b.get("pageID") or first) == page_id]


def first_free_spot(doc: dict, page_id: str, width: float, height: float, occupied: list[tuple] | None = None) -> tuple[float, float]:
    """Primeiro espaço livre a partir do canto superior esquerdo da área de texto (como o
    `Placement` do iPhone); sobrepõe só com a página cheia."""
    pw, ph = page_size(doc)
    m = text_margins(doc)
    rects = list(occupied or [])
    for b in blocks_on_page(doc, page_id):
        f = b["frame"]
        rects.append((f["x"], f["y"], f["width"], f["height"]))
    step = 12.0
    y = m["top"]
    while y + height <= ph - m["bottom"] + 0.5:
        x = m["left"]
        while x + width <= pw - m["right"] + 0.5:
            if not any(_overlap((x, y, width, height), r, 6) for r in rects):
                return x, y
            x += step
        y += step
    return m["left"], m["top"]


def _overlap(a, b, gap: float) -> bool:
    return not (a[0] + a[2] + gap <= b[0] or b[0] + b[2] + gap <= a[0]
                or a[1] + a[3] + gap <= b[1] or b[1] + b[3] + gap <= a[1])


def collect_text(doc: dict) -> list[tuple[str, str]]:
    """(onde, texto) de tudo que entra na busca: texto da nota, caixas, post-its, formas,
    tabelas, transcrições e legendas."""
    parts: list[tuple[str, str]] = []
    story = (doc.get("story") or {}).get("text") or ""
    if story.strip():
        parts.append(("story", story))
    for b in doc.get("blocks", []):
        text = b.get("text") or ""
        if text.strip():
            parts.append((b["id"], text))
        caption = b.get("caption") or ""
        if caption.strip():
            parts.append((b["id"], caption))
    return parts


def asset_hashes(doc: dict) -> set[str]:
    hashes: set[str] = set()
    for b in doc.get("blocks", []):
        for key in ("asset", "poster", "original"):
            if b.get(key):
                hashes.add(b[key])
    for p in doc.get("pages", []):
        bg = p.get("background")
        if bg and bg.get("asset"):
            hashes.add(bg["asset"])
    canvas = doc.get("canvas", {})
    for band in (canvas.get("header"), canvas.get("footer")):
        if band and band.get("image"):
            hashes.add(band["image"])
    return hashes


def linked_note_ids(doc: dict) -> set[str]:
    """Notas citadas: links gotit://nota/<id> no texto e cartões de Teia."""
    import re
    ids: set[str] = set()
    pattern = re.compile(r"gotit://nota/([0-9a-fA-F-]{36})")
    html = (doc.get("story") or {}).get("html") or ""
    ids.update(m.lower() for m in pattern.findall(html))
    for b in doc.get("blocks", []):
        if b.get("html"):
            ids.update(m.lower() for m in pattern.findall(b["html"]))
        if b.get("kind") == "noteRef" and b.get("documentID"):
            ids.add(b["documentID"].lower())
    ids.discard(doc["id"].lower())
    return ids
