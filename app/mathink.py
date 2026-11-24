"""Leitura de contas escritas à mão, sem depender do reconhecedor do Windows.

1. Os traços são separados em símbolos (traços que se sobrepõem na horizontal são um símbolo:
   o "=" tem dois traços, o "+" dois, o "4" às vezes dois).
2. Sinais saem da forma: traço reto deitado é "−", dois deitados empilhados são "=", um deitado
   e um em pé cruzados são "+", dois diagonais cruzados são "x", reta inclinada é "/", ponto
   pequeno é ",", símbolo pequeno e alto é expoente.
3. Algarismos (e x, parênteses) pelo reconhecedor $P (Vatavu, Anthony e Wobbrock, 2012):
   compara a nuvem de pontos com modelos de cada algarismo escrito de vários jeitos.

Devolve leituras possíveis da linha, da mais provável para a menos; quem chama fica com a
primeira que forma uma conta válida."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

Point = tuple[float, float]
N = 32                     # pontos de cada nuvem
MAX_DISTANCE = 0.95        # acima disso o símbolo não é algarismo (letra, rabisco)


# ---------------------------------------------------------------------- modelos
def _arc(cx, cy, rx, ry, a0, a1, steps=18):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / steps))) for i in range(steps + 1)]


def _templates() -> list[tuple[str, list[list[Point]]]]:
    """Algarismos em 0..100 (y para baixo), cada um de alguns jeitos comuns de escrever."""
    t = []

    def add(name, *strokes):
        t.append((name, [list(s) for s in strokes]))

    add("0", _arc(50, 50, 30, 46, -90, 270))
    add("0", _arc(50, 50, 30, 46, -90, -450))
    add("0", _arc(50, 50, 34, 46, -60, 300))
    add("1", [(50, 0), (50, 100)])
    add("1", [(30, 18), (52, 0), (50, 100)])
    add("1", [(32, 20), (52, 0), (50, 100)], [(30, 100), (70, 100)])
    add("2", _arc(50, 30, 30, 28, 195, 375) + [(18, 100), (85, 100)])
    add("2", _arc(48, 28, 28, 26, 210, 390) + [(25, 85), (15, 100), (40, 92), (88, 98)])
    add("2", _arc(50, 32, 32, 30, 180, 360) + [(15, 100), (88, 100)])
    add("3", _arc(50, 26, 28, 24, 200, 450) + _arc(50, 76, 30, 24, 270, 520))
    add("3", _arc(48, 26, 30, 24, 210, 440)[:-1] + [(40, 50)] + _arc(48, 75, 32, 25, 280, 510))
    add("3", [(18, 0), (78, 0), (45, 42)] + _arc(48, 72, 32, 28, 280, 520))
    add("4", [(62, 0), (12, 66), (88, 66)], [(66, 30), (66, 100)])
    add("4", [(22, 0), (18, 60), (85, 60)], [(68, 0), (68, 100)])
    add("4", [(70, 100), (70, 0), (12, 66), (90, 66)])
    add("5", [(28, 0), (24, 45)] + _arc(48, 70, 32, 28, 220, 520), [(28, 0), (82, 0)])
    add("5", [(82, 0), (28, 0), (24, 45)] + _arc(48, 70, 32, 28, 220, 520))
    add("5", [(28, 0), (24, 45)] + _arc(48, 70, 32, 28, 220, 520), [(28, 2), (82, 0)])
    add("6", [(72, 4), (48, 14), (30, 40), (24, 68)] + _arc(50, 72, 26, 26, 180, -180))
    add("6", [(68, 0), (36, 30), (25, 65)] + _arc(50, 73, 25, 25, 160, -200))
    add("7", [(12, 0), (88, 0), (35, 100)])
    add("7", [(12, 0), (88, 0)], [(88, 0), (35, 100)])
    add("7", [(12, 0), (88, 0), (35, 100)], [(35, 50), (80, 50)])
    add("8", _arc(50, 26, 22, 24, -20, -340) + _arc(50, 74, 27, 25, 270, 630))
    add("8", _arc(50, 26, 22, 24, 200, -140) + _arc(50, 74, 27, 25, 270, -90))
    add("8", _arc(50, 26, 22, 24, 0, 360), _arc(50, 74, 27, 25, 0, 360))
    add("9", _arc(45, 28, 26, 27, 0, -360) + [(71, 28), (66, 100)])
    add("9", _arc(45, 28, 26, 27, -20, -380) + [(70, 35), (68, 70), (55, 100)])
    add("9", _arc(45, 28, 26, 27, 0, 360) + [(71, 28), (66, 100)])
    add("x", [(12, 12), (88, 88)], [(88, 12), (12, 88)])
    add("x", _arc(10, 50, 40, 40, -60, 60), _arc(90, 50, 40, 40, 240, 120))
    add("(", _arc(85, 50, 55, 52, 240, 120))
    add(")", _arc(15, 50, 55, 52, -60, 60))
    return t


# ---------------------------------------------------------------------- $P
@dataclass
class Cloud:
    name: str
    points: list[tuple[float, float, int]]
    strokes: int = 1


def _resample(strokes: list[list[Point]], n: int = N) -> list[tuple[float, float, int]]:
    pts = [(p[0], p[1], i) for i, s in enumerate(strokes) for p in s]
    length = 0.0
    for a, b in zip(pts, pts[1:]):
        if a[2] == b[2]:
            length += math.hypot(b[0] - a[0], b[1] - a[1])
    if length == 0:
        return [pts[0]] * n
    step = length / (n - 1)
    out = [pts[0]]
    acc = 0.0
    i = 1
    pts = list(pts)
    while i < len(pts) and len(out) < n:
        a, b = pts[i - 1], pts[i]
        if a[2] == b[2]:
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            if acc + d >= step and d > 0:
                t = (step - acc) / d
                q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2])
                out.append(q)
                pts.insert(i, q)
                acc = 0.0
            else:
                acc += d
        i += 1
    while len(out) < n:
        out.append(pts[-1])
    return out[:n]


def _normalize(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    size = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    return [((p[0] - cx) / size, (p[1] - cy) / size, p[2]) for p in points]


def _declutter(strokes: list[list[Point]]) -> list[list[Point]]:
    """Tira o tremor da mão e do mouse: pontos mais perto que 4% do tamanho saem e o resto é
    suavizado, para o tremor não pesar no comprimento do traço."""
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    size = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    gap = 0.04 * size
    out = []
    for s in strokes:
        kept = [s[0]]
        for p in s[1:]:
            if math.hypot(p[0] - kept[-1][0], p[1] - kept[-1][1]) >= gap:
                kept.append(p)
        if len(kept) > 1 and kept[-1] != s[-1]:
            kept[-1] = s[-1]
        if len(kept) > 2:
            kept = [kept[0]] + [((a[0] + 2 * b[0] + c[0]) / 4, (a[1] + 2 * b[1] + c[1]) / 4)
                                for a, b, c in zip(kept, kept[1:], kept[2:])] + [kept[-1]]
        out.append(kept)
    return out


def make_cloud(name: str, strokes: list[list[Point]]) -> Cloud:
    strokes = _declutter([s for s in strokes if s])
    return Cloud(name, _normalize(_resample(strokes)), len(strokes))


def _cloud_distance(a, b, start: int) -> float:
    n = len(a)
    matched = [False] * n
    total = 0.0
    weight = n
    i = start
    for _ in range(n):
        best, idx = math.inf, -1
        ax, ay = a[i][0], a[i][1]
        for j in range(n):
            if not matched[j]:
                d = (ax - b[j][0]) ** 2 + (ay - b[j][1]) ** 2
                if d < best:
                    best, idx = d, j
        matched[idx] = True
        total += (weight / n) * math.sqrt(best)
        weight -= 1
        i = (i + 1) % n
    return total


def match(a: Cloud, b: Cloud) -> float:
    step = max(1, int(len(a.points) ** 0.5))
    best = math.inf
    for i in range(0, len(a.points), step):
        best = min(best, _cloud_distance(a.points, b.points, i), _cloud_distance(b.points, a.points, i))
    return best / len(a.points) * 2


_TEMPLATES: list[Cloud] | None = None


def _variant(strokes, slant: float, aspect: float):
    """O mesmo algarismo inclinado (itálico para os dois lados) e mais estreito ou mais largo."""
    return [[(50 + (x - 50) * aspect + slant * (100 - y), y) for x, y in s] for s in strokes]


def templates() -> list[Cloud]:
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = []
        for name, strokes in _templates():
            for slant in (-0.22, 0.0, 0.22):
                for aspect in (0.7, 1.0, 1.25):
                    _TEMPLATES.append(make_cloud(name, _variant(strokes, slant, aspect)))
    return _TEMPLATES


_STACK = None


def _stack():
    global _STACK
    if _STACK is None:
        import numpy as np
        _STACK = np.array([[(p[0], p[1]) for p in t.points] for t in templates()], dtype=np.float32)
    return _STACK


def classify(strokes: list[list[Point]], top: int = 3, shortlist: int = 24) -> list[tuple[str, float]]:
    """(algarismo, distância) dos mais parecidos, um por algarismo. Uma triagem rápida (distância
    média ao ponto mais próximo, de todos os modelos de uma vez) escolhe os modelos que passam
    pela comparação completa do $P."""
    import numpy as np
    cloud = make_cloud("?", strokes)
    pts = np.array([(p[0], p[1]) for p in cloud.points], dtype=np.float32)
    stack = _stack()
    d = np.sqrt(((stack[:, :, None, :] - pts[None, None, :, :]) ** 2).sum(-1))    # T × N × N
    chamfer = d.min(axis=2).mean(axis=1) + d.min(axis=1).mean(axis=1)
    order = np.argsort(chamfer)[:shortlist]
    tmpl = templates()
    best: dict[str, float] = {}
    for t in (tmpl[i] for i in order):
        d = match(cloud, t)
        # traços a mais ou a menos que o modelo pesam um pouco
        d *= 1 + 0.15 * abs(t.strokes - cloud.strokes)
        if d < best.get(t.name, math.inf):
            best[t.name] = d
    return sorted(best.items(), key=lambda kv: kv[1])[:top]


# ---------------------------------------------------------------------- forma dos sinais
@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


def box_of(strokes) -> Box:
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    return Box(min(xs), min(ys), max(xs), max(ys))


def straight(stroke: list[Point]) -> tuple[bool, float, float]:
    """(é reta, ângulo em graus 0..180 com y para cima, comprimento)."""
    a, b = stroke[0], stroke[-1]
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if length < 1e-6:
        return False, 0.0, 0.0
    dev = max(_seg_dist(p, a, b) for p in stroke)
    travel = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(stroke, stroke[1:]))
    ang = math.degrees(math.atan2(-(b[1] - a[1]), b[0] - a[0])) % 180
    return dev <= max(1.5, 0.14 * length) and travel <= 1.25 * length, ang, length


def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = dx * dx + dy * dy
    t = 0.0 if ln == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ln))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def _horizontal(ang):
    return ang < 22 or ang > 158


def _vertical(ang):
    return 62 < ang < 118


def _segments_cross(a, b) -> bool:
    (p1, p2), (p3, p4) = (a[0], a[-1]), (b[0], b[-1])

    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def operator(strokes: list[list[Point]], line_h: float) -> str | None:
    """Sinal pela forma, ou None para mandar ao reconhecedor de algarismos."""
    box = box_of(strokes)
    if max(box.w, box.h) < 0.18 * line_h:
        return "."
    info = [straight(s) for s in strokes]
    if len(strokes) == 1:
        ok, ang, length = info[0]
        if ok and _horizontal(ang) and box.h < 0.35 * max(box.w, 1):
            return "-"
        if ok and 30 <= ang <= 62 and box.h > 0.5 * line_h:
            return "/"
        return None
    if len(strokes) == 2 and all(i[0] for i in info):
        (_, a1, l1), (_, a2, l2) = info
        if _horizontal(a1) and _horizontal(a2):
            b1, b2 = box_of([strokes[0]]), box_of([strokes[1]])
            if abs(b1.cy - b2.cy) > 0.12 * max(l1, l2):
                return "="
            return "-"
        cross = _segments_cross(strokes[0], strokes[1])
        if cross and ((_horizontal(a1) and _vertical(a2)) or (_vertical(a1) and _horizontal(a2))):
            return "+"
        if cross and not (_horizontal(a1) or _horizontal(a2) or _vertical(a1) or _vertical(a2)) and (a1 - 90) * (a2 - 90) < 0:
            return "x"
    return None


# ---------------------------------------------------------------------- linha
@dataclass
class Symbol:
    strokes: list
    box: Box
    options: list[tuple[str, float]] = field(default_factory=list)
    superscript: bool = False


def segment(strokes: list[list[Point]]) -> list[Symbol]:
    """Junta traços que se sobrepõem na horizontal (da esquerda para a direita)."""
    items = sorted(((box_of([s]), s) for s in strokes if len(s) >= 1), key=lambda bs: bs[0].x0)
    groups: list[list] = []
    for box, s in items:
        if groups:
            g = groups[-1]
            gb = box_of([st for _, st in g])
            overlap = min(gb.x1, box.x1) - max(gb.x0, box.x0)
            narrow = max(1.0, min(gb.w, box.w))
            # traço fino (o "1", a perna do "4") só junta se estiver bem dentro do outro
            thin = min(gb.w, box.w) < 0.25 * max(gb.h, box.h, 1)
            if thin:
                slim, wide = (box, gb) if box.w <= gb.w else (gb, box)
                cx = (slim.x0 + slim.x1) / 2
                join = wide.x0 + 0.12 * wide.w <= cx <= wide.x1 - 0.12 * wide.w
            else:
                join = overlap > 0.45 * narrow
            if join:
                g.append((box, s))
                continue
        groups.append([(box, s)])
    return [Symbol([s for _, s in g], box_of([s for _, s in g])) for g in groups]


def read(strokes: list[list[Point]], symbol_reader=None, limit: int = 8) -> list[str]:
    """Leituras possíveis da linha. ``symbol_reader(strokes) -> [str]`` (opcional) dá as
    leituras do reconhecedor do Windows para um símbolo; elas vêm antes das do $P."""
    strokes = [[(float(p[0]), float(p[1])) for p in s] for s in strokes if s]
    if not strokes:
        return []
    symbols = segment(strokes)
    tall = sorted(s.box.h for s in symbols if s.box.h > 0)
    line_h = tall[len(tall) * 2 // 3] if tall else 20.0
    base = sorted(s.box.y1 for s in symbols)[len(symbols) // 2]
    for sym in symbols:
        op = operator(sym.strokes, line_h)
        if op:
            sym.options = [(op, 0.0)]
            continue
        found = []
        if symbol_reader is not None:
            try:
                for i, cand in enumerate(symbol_reader(sym.strokes)):
                    c = _symbol_char(cand)
                    if c and c not in [f[0] for f in found]:
                        found.append((c, 0.05 * i))
            except Exception:
                pass
        for name, dist in classify(sym.strokes):
            if dist <= MAX_DISTANCE and name not in [f[0] for f in found]:
                found.append((name, 0.3 + dist))
        if not found:
            return []
        sym.options = found[:3]
        # expoente: algarismo pequeno com a base bem acima da linha
        sym.superscript = sym.box.h < 0.7 * line_h and sym.box.y1 < base - 0.35 * line_h
    combos = []
    choices = [s.options for s in symbols]
    # a melhor leitura e as que trocam um ou dois símbolos pela segunda opção
    for combo in itertools.islice(itertools.product(*choices), 4000):
        cost = sum(c[1] for c in combo)
        combos.append((cost, combo))
    combos.sort(key=lambda c: c[0])
    out = []
    for _, combo in combos:
        text = ""
        prev_sup = False
        for sym, (ch, _) in zip(symbols, combo):
            if sym.superscript and ch.isdigit() and not prev_sup:
                text += "^"
            text += ch
            prev_sup = sym.superscript
        if text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


SYMBOL_MAP = {"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "i": "1", "!": "1", "z": "2",
              "Z": "2", "S": "5", "s": "5", "b": "6", "G": "6", "B": "8", "g": "9", "q": "9", "X": "x", "×": "x",
              "t": "+", "T": "+", "—": "-", "–": "-", "−": "-", "_": "-", "~": "-", ",": "."}


def _symbol_char(cand: str) -> str | None:
    cand = cand.strip()
    if len(cand) != 1:
        return None
    c = SYMBOL_MAP.get(cand, cand)
    return c if c in "0123456789x()" else None
