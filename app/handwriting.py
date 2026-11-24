"""Escrita à mão vira texto e equações escritas à mão são resolvidas, pelo reconhecimento de
escrita do próprio Windows (Windows Ink, o mesmo do Painel de Escrita) e, para contas, também
por um leitor de algarismos e sinais do próprio app (mathink), que funciona em qualquer PC.

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


RUN_IN_THREAD = True      # os testes desligam para rodar na hora
MATH_CHARS = set("0123456789.,+-−–*/×÷:=^()xX ")


class _Windows:
    """Reconhecedor do Windows, usado de uma thread só (um laço asyncio por sessão)."""

    def __init__(self):
        import asyncio
        from winrt.windows.ui.input.inking import InkRecognizerContainer
        self.loop = asyncio.new_event_loop()
        self.broken = False
        self.rc = InkRecognizerContainer()
        names = {r.name: r for r in self.rc.get_recognizers()}
        best = preferred(list(names))
        if best:
            self.rc.set_default_recognizer(names[best])

    def words(self, points_per_stroke) -> list[list[str]]:
        """Para cada palavra reconhecida, as leituras possíveis (a melhor primeiro)."""
        from winrt.windows.ui.input.inking import InkPoint, InkRecognitionTarget, InkStrokeBuilder, InkStrokeContainer
        builder = InkStrokeBuilder()
        container = InkStrokeContainer()
        for pts in points_per_stroke:
            ink_points = [InkPoint((float(p[0]), float(p[1])), float(max(0.05, min(1.0, (p[2] if len(p) > 2 else 0.5) or 0.5))))
                          for p in pts]
            if len(ink_points) < 2:       # um ponto só (o ponto decimal, o pingo): repete para virar traço
                if not ink_points:
                    continue
                x, y = pts[0][0], pts[0][1]
                ink_points = [InkPoint((float(x), float(y)), 0.5), InkPoint((float(x) + 0.6, float(y) + 0.6), 0.5)]
            container.add_stroke(builder.create_stroke_from_ink_points(ink_points, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))

        if self.broken:
            return []

        async def run():
            results = await self.rc.recognize_async(container, InkRecognitionTarget.ALL)
            return [list(r.get_text_candidates()) for r in results]
        import asyncio
        try:
            found = self.loop.run_until_complete(asyncio.wait_for(run(), 6))
        except asyncio.TimeoutError:
            self.broken = True        # reconhecedor travado: segue só com o leitor do app
            return []
        return [w for w in found if w]

    def close(self):
        self.loop.close()


def line_readings(words: list[list[str]], limit: int = 8) -> list[str]:
    """Frases possíveis a partir das leituras por palavra: a melhor de cada, depois trocando uma
    palavra por vez pela alternativa (o "1O" que era "10", o "x" que era "×")."""
    if not words:
        return []
    best = [w[0] for w in words]
    out = [" ".join(best)]
    for rank in range(1, 5):
        for i, w in enumerate(words):
            if rank < len(w):
                alt = best[:]
                alt[i] = w[rank]
                line = " ".join(alt)
                if line not in out:
                    out.append(line)
            if len(out) >= limit:
                return out
    return out


def recognize(points_per_stroke) -> str:
    """Texto reconhecido pelo Windows (bloqueia; chamar fora da thread da janela)."""
    win = _Windows()
    try:
        return " ".join(w[0] for w in win.words(points_per_stroke)).strip()
    finally:
        win.close()


def solve_strokes(points_per_stroke, win=None) -> tuple[str, str] | None:
    """(conta lida, resposta) para traços escritos à mão, ou None. Lê símbolo a símbolo (com o
    Windows, se houver, e com o leitor próprio do app) e também a linha inteira pelo Windows."""
    import mathink
    reader = None
    if win is not None:
        def reader(sym_strokes):
            out = []
            for w in win.words(sym_strokes):
                out.extend(w)
            return out
    readings = mathink.read(points_per_stroke, symbol_reader=reader)
    if win is not None:
        try:
            readings += line_readings(win.words(points_per_stroke))
        except Exception:
            pass
    for raw in readings:
        ans = mathsolve.answer_text(raw)
        if ans:
            return mathsolve.normalize_formula(raw) or raw, ans
    return None


def recognize_into(editor, grown_ids: list[str], new_ids: list[str] | None = None) -> None:
    """Depois de uma pausa na escrita, num grupo de traços na mesma linha: resolve a conta
    (resposta em azul ao lado, atualizada se a conta mudar) ou troca a escrita nova por texto
    na fonte escolhida (um só passo de desfazer). A conta funciona mesmo sem o reconhecedor do
    Windows; trocar escrita por texto precisa dele."""
    scene = editor.scene
    canvas = editor.doc["canvas"]
    new_ids = list(new_ids if new_ids is not None else grown_ids)
    grown = [scene.strokes_by_id[i] for i in grown_ids if i in scene.strokes_by_id]
    if not grown:
        return
    page_id = grown[0].data_state.get("pageID")
    pts_grown = [[tuple(p) for p in st.data_state.get("points", [])] for st in grown]
    pts_new = [[tuple(p) for p in scene.strokes_by_id[i].data_state.get("points", [])]
               for i in new_ids if i in scene.strokes_by_id]
    want_math = bool(canvas.get("solveEquations"))
    want_text = bool(canvas.get("handwritingToText")) and available()
    use_windows = available()
    bridge = _Bridge()
    _pending.append(bridge)

    def work():
        out = None
        win = None
        try:
            if use_windows:
                win = _Windows()
            if want_math:
                solved = solve_strokes(pts_grown, win)
                if solved:
                    out = ("math", solved)
            if out is None and want_text and win is not None:
                text = " ".join(w[0] for w in win.words(pts_new)).strip()
                # conta pela metade (ex.: "12 +" antes do resto): espera, não vira texto
                if text and not (want_math and set(text) <= MATH_CHARS):
                    out = ("text", text)
        except Exception as exc:
            bridge.error = f"{type(exc).__name__}: {exc}"
        finally:
            if win is not None:
                win.close()
        bridge.result.emit(out)

    def apply(out):
        if bridge in _pending:
            _pending.remove(bridge)
        if out is None or editor.scene is not scene:
            return
        kind, value = out
        if kind == "math":
            _place_answer(editor, page_id, grown_ids, value[1])
        else:
            _replace_with_text(editor, page_id, new_ids, value)

    if not RUN_IN_THREAD:
        bridge.result.connect(apply, Qt.ConnectionType.DirectConnection)
        work()
        return
    bridge.result.connect(apply, Qt.ConnectionType.QueuedConnection)
    threading.Thread(target=work, daemon=True).start()


def _bounds(strokes):
    xs = [p[0] for st in strokes for p in st.data_state["points"]]
    ys = [p[1] for st in strokes for p in st.data_state["points"]]
    return min(xs), min(ys), max(xs), max(ys)


def _place_answer(editor, page_id, stroke_ids, answer: str) -> None:
    scene = editor.scene
    canvas = editor.doc["canvas"]
    alive = [scene.strokes_by_id[i] for i in stroke_ids if i in scene.strokes_by_id]
    if not alive:
        return
    x0, y0, x1, y1 = _bounds(alive)
    size = max(14.0, min(40.0, (y1 - y0) * 0.75))
    ids = set(stroke_ids)
    for bid, it in list(scene.items_by_id.items()):
        st = it.data_state
        if st.get("equationOf") and ids & set(st["equationOf"]):
            if st.get("text") == answer and set(st["equationOf"]) == ids:
                return
            new = it.state()
            new["text"] = answer
            new["html"] = ""
            new["equationOf"] = sorted(ids)
            new["frame"] = {**new["frame"], "x": x1 + 12, "y": (y0 + y1) / 2 - size * 0.8,
                            "width": max(60, len(answer) * size * 0.62 + 16)}
            with scene.change("Resolver conta"):
                scene.remove_block(bid)
                scene.add_block(new)
            return
    font = canvas.get("handwritingFont")
    state = {"id": model.new_id(), "kind": "text", "pageID": page_id,
             "frame": {"x": x1 + 12, "y": (y0 + y1) / 2 - size * 0.8,
                       "width": max(60, len(answer) * size * 0.62 + 16), "height": size * 1.6},
             "z": scene.next_z(), "text": answer, "html": "", "foreground": "#2563EB",
             "fontName": None if font in (None, "Fonte do texto") else font, "fontSize": round(size, 1),
             "equationOf": sorted(ids)}
    with scene.change("Resolver conta"):
        scene.add_block(state)


def _replace_with_text(editor, page_id, stroke_ids, text: str) -> None:
    scene = editor.scene
    canvas = editor.doc["canvas"]
    alive = [scene.strokes_by_id[i] for i in stroke_ids if i in scene.strokes_by_id]
    if not alive:
        return
    x0, y0, x1, y1 = _bounds(alive)
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
