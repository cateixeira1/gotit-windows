"""Escrita à mão vira texto e equações escritas à mão são resolvidas, pelo reconhecimento de
escrita do próprio Windows (Windows Ink, o mesmo do Painel de Escrita). Roda no computador.

Para português, o Windows precisa do pacote de escrita à mão: Configurações › Hora e idioma ›
Idioma e região › Português (Brasil) › Opções de idioma › Manuscrito."""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal

import mathsolve
import model

_state = {"checked": False, "recognizers": [], "error": ""}
_pending: list = []


def _probe() -> None:
    try:
        from winrt.windows.ui.input.inking import InkRecognizerContainer
        names = [r.name for r in InkRecognizerContainer().get_recognizers()]
        _state["recognizers"] = names
    except Exception as exc:
        _state["error"] = f"{type(exc).__name__}: {exc}"


def recognizers() -> list[str]:
    if not _state["checked"]:
        _state["checked"] = True
        if sys.platform != "win32":
            _state["error"] = "só no Windows"
            return []
        t = threading.Thread(target=_probe, daemon=True)
        t.start()
        t.join(5)
    return _state["recognizers"]


def available() -> bool:
    return bool(recognizers())


def preferred(names: list[str]) -> str | None:
    for key in ("Portugu", "Brasil", "Brazil"):
        for n in names:
            if key.lower() in n.lower():
                return n
    return names[0] if names else None


def status_text() -> str:
    names = recognizers()
    if names:
        best = preferred(names)
        extra = "" if "portugu" in (best or "").lower() else (
            " Para escrever em português, instale o manuscrito do Português (Brasil) em Configurações › Hora e idioma › "
            "Idioma e região › Português (Brasil) › Opções de idioma.")
        return f"Escrita à mão: usando “{best}”.{extra}"
    return explanation()


def explanation() -> str:
    return ("A escrita à mão vira texto pelo reconhecimento de escrita do próprio Windows, que funciona sem internet. "
            "Este computador ainda não tem um reconhecedor instalado. Para instalar o de português: Configurações › "
            "Hora e idioma › Idioma e região › Português (Brasil) › Opções de idioma › Manuscrito › Baixar. "
            "Depois, abra o Got It! de novo.")


class _Bridge(QObject):
    result = Signal(object)


def recognize(points_per_stroke: list[list[tuple[float, float, float]]]) -> str:
    """Texto reconhecido (bloqueia; chamar fora da thread da janela)."""
    import asyncio
    from winrt.windows.ui.input.inking import (InkPoint, InkRecognitionTarget, InkRecognizerContainer, InkStrokeBuilder,
                                               InkStrokeContainer)

    async def run() -> str:
        builder = InkStrokeBuilder()
        container = InkStrokeContainer()
        for pts in points_per_stroke:
            ink_points = [InkPoint((float(x), float(y)), float(max(0.05, min(1.0, p or 0.5)))) for x, y, p in pts]
            if len(ink_points) < 2:
                continue
            container.add_stroke(builder.create_stroke_from_ink_points(ink_points, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
        rc = InkRecognizerContainer()
        names = {r.name: r for r in rc.get_recognizers()}
        best = preferred(list(names))
        if best:
            rc.set_default_recognizer(names[best])
        results = await rc.recognize_async(container, InkRecognitionTarget.ALL)
        words = []
        for r in results:
            cands = list(r.get_text_candidates())
            if cands:
                words.append(cands[0])
        return " ".join(words).strip()
    return asyncio.run(run())


def recognize_into(editor, strokes) -> None:
    """Depois de uma pausa na escrita: resolve a equação (resposta em azul ao lado) ou troca a
    escrita por texto na fonte escolhida (um só passo de desfazer)."""
    if not available():
        return
    scene = editor.scene
    canvas = editor.doc["canvas"]
    by_page: dict[str, list] = {}
    for st in strokes:
        by_page.setdefault(st.data_state.get("pageID"), []).append(st)
    page_id, group = max(by_page.items(), key=lambda kv: len(kv[1]))
    ids = [st.stroke_id for st in group]
    pts = [[tuple(p) for p in st.data_state.get("points", [])] for st in group]
    bridge = _Bridge()
    _pending.append(bridge)

    def work():
        try:
            text = recognize(pts)
        except Exception as exc:
            text = ""
            bridge.error = str(exc)
        bridge.result.emit(text)

    def apply(text: str):
        _pending.remove(bridge) if bridge in _pending else None
        if editor.scene is not scene or not text:
            return
        alive = [scene.strokes_by_id[i] for i in ids if i in scene.strokes_by_id]
        if not alive:
            return
        xs = [p[0] for st in alive for p in st.data_state["points"]]
        ys = [p[1] for st in alive for p in st.data_state["points"]]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        answer = mathsolve.answer_text(text) if canvas.get("solveEquations") else None
        if answer:
            state = {"id": model.new_id(), "kind": "text", "pageID": page_id,
                     "frame": {"x": x1 + 12, "y": (y0 + y1) / 2 - 18, "width": max(120, len(answer) * 11), "height": 36},
                     "z": scene.next_z(), "text": answer, "html": "", "foreground": "#2563EB",
                     "fontName": canvas.get("handwritingFont") if canvas.get("handwritingFont") != "Fonte do texto" else None,
                     "fontSize": max(12.0, min(36.0, (y1 - y0) * 0.6))}
            with scene.change("Resolver equação"):
                scene.add_block(state)
            return
        if not canvas.get("handwritingToText"):
            return
        family = canvas.get("handwritingFont") or "Caveat"
        lines = max(1, round((y1 - y0) / 40))
        size = max(10.0, min(48.0, (y1 - y0) / lines * 0.62))
        if family == "Caveat":
            size *= 1.16           # a Caveat tem maiúsculas menores: o tamanho real fica maior
        state = {"id": model.new_id(), "kind": "text", "pageID": page_id,
                 "frame": {"x": x0, "y": y0 - 4, "width": max(80, x1 - x0 + 24), "height": max(30, y1 - y0 + 8)},
                 "z": scene.next_z(), "text": text, "html": "", "foreground": alive[0].data_state.get("color") or "#1F2933",
                 "fontName": None if family == "Fonte do texto" else family, "fontSize": round(size, 1)}
        with scene.change("Escrita vira texto"):
            for st in alive:
                scene.remove_stroke(st.stroke_id)
            scene.add_block(state)

    bridge.result.connect(apply, Qt.ConnectionType.QueuedConnection)
    threading.Thread(target=work, daemon=True).start()
