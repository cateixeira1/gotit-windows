"""Formas perfeitas: reconhece retângulo, elipse, losango, triângulo, linha e seta desenhados à
mão pelo fecho convexo (como o reconhecedor do iPhone, após Fonseca & Jorge, CALI, 2002).
As razões usadas (maior triângulo e quadrilátero inscritos x fecho; fecho x retângulo mínimo)
não mudam quando a figura é esticada, então uma caixa torta pontua como um quadrado limpo.
Casos ambíguos mantêm a tinta: a escrita à mão sobrevive."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]


@dataclass
class Recognized:
    kind: str                       # rectangle, ellipse, diamond, triangle, line, arrow
    frame: tuple[float, float, float, float]
    rotation: float = 0.0           # graus
    vertices: list | None = None    # triângulo: cantos como frações do quadro
    points: list = field(default_factory=list)   # linha/seta: duas pontas (página)


@dataclass
class Limits:
    minimum_size: float = 36
    closure: float = 0.2
    retrace: float = 1.15
    solidity: float = 0.72
    triangle: float = 0.8
    quad: float = 0.85
    ellipse_quad: tuple = (0.5, 0.79)
    ellipse_fill: tuple = (0.7, 0.89)
    vertex_tolerance: float = 0.3
    line_deviation: float = 0.035
    coverage: float = 0.72


AUTOMATIC = Limits()
DELIBERATE = Limits(16, 0.32, 1.65, 0.55, 0.74, 0.79, (0.45, 0.84), (0.62, 0.93), 0.38, 0.07, 0.55)


def recognize(points: list, deliberate: bool = False) -> Recognized | None:
    pts = [(float(p[0]), float(p[1])) for p in points if math.isfinite(p[0]) and math.isfinite(p[1])]
    if len(pts) < 2:
        return None
    lim = DELIBERATE if deliberate else AUTOMATIC
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h = maxx - minx, maxy - miny
    diagonal = math.hypot(w, h)
    if max(w, h) < lim.minimum_size:
        return None
    line = _line(pts, lim)
    if line:
        return line
    path = resample(pts, 96)
    span = _closed_span(path, lim.closure * diagonal)
    if not span:
        return None
    head, tail = span
    if (tail - head + 1) < len(path) * lim.coverage:
        return None
    loop = path[head:tail + 1]
    hull = convex_hull(loop)
    if len(hull) < 3:
        return None
    hull_area = abs(signed_area(hull))
    hull_perim = perimeter(hull, True)
    rect = min_area_rect(hull)
    if hull_area <= 0 or rect["area"] <= 0 or min(rect["w"], rect["h"]) < max(6, 0.1 * max(rect["w"], rect["h"])):
        return None
    if perimeter(loop, True) / hull_perim > lim.retrace:
        return None
    if abs(signed_area(loop)) / hull_area < lim.solidity:
        return None
    small = _reduce(hull, 28)
    tri_area, tri = largest_polygon(small, 3)
    quad_area, quad = largest_polygon(small, 4)
    tri_ratio, quad_ratio = tri_area / hull_area, quad_area / hull_area
    fill = hull_area / rect["area"]
    frame = (minx, miny, w, h)
    if tri_ratio >= lim.triangle:
        return Recognized("triangle", frame, vertices=[[round((x - minx) / w, 4) if w else 0.5,
                                                         round((y - miny) / h, 4) if h else 0.5] for x, y in tri])
    if quad_ratio >= lim.quad:
        # caixa desenhada inclinada: mantém o ângulo (o fecho enche um retângulo girado e os cantos
        # são quase retos, ao contrário de um losango)
        angle, rw, rh = _tilt(rect)
        if abs(angle) >= 11 and fill >= 0.9 and _corner_deviation(quad) <= 0.35:
            cx, cy = rect["cx"], rect["cy"]
            return Recognized("rectangle", (cx - rw / 2, cy - rh / 2, rw, rh), rotation=angle)
        norm = [((x - minx) / w if w else 0.5, (y - miny) / h if h else 0.5) for x, y in quad]
        axis = _template_error(norm, [(0, 0), (1, 0), (1, 1), (0, 1)])
        diamond = _template_error(norm, [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)])
        if diamond <= lim.vertex_tolerance * 0.8 and diamond < axis * 0.8:
            return Recognized("diamond", frame)
        if axis <= lim.vertex_tolerance + 0.08:
            return Recognized("rectangle", frame)
        return None
    if lim.ellipse_quad[0] <= quad_ratio <= lim.ellipse_quad[1] and lim.ellipse_fill[0] <= fill <= lim.ellipse_fill[1] \
            and tri_ratio <= 0.62:
        angle, rw, rh = _tilt(rect)
        aspect = max(rect["w"], rect["h"]) / max(1e-6, min(rect["w"], rect["h"]))
        if aspect < 1.2 or abs(angle) < 11:
            return Recognized("ellipse", frame)
        cx, cy = rect["cx"], rect["cy"]
        return Recognized("ellipse", (cx - rw / 2, cy - rh / 2, rw, rh), rotation=angle)
    return None


def _tilt(rect: dict) -> tuple[float, float, float]:
    """Inclinação do retângulo mínimo em (-45°, 45°], com largura e altura correspondentes."""
    deg = math.degrees(rect["angle"]) % 180
    w, h = rect["w"], rect["h"]
    if deg > 135:
        deg -= 180
    elif deg > 45:
        deg -= 90
        w, h = h, w
    return deg, w, h


def _line(pts: list[Point], lim: Limits) -> Recognized | None:
    a, b = pts[0], pts[-1]
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if length < lim.minimum_size:
        return None
    dev = max(_seg_dist(p, a, b) for p in pts)
    travel = perimeter(pts, False)
    if dev / length <= lim.line_deviation * 1.6 and travel / length < 1.12:
        x0, y0 = min(a[0], b[0]), min(a[1], b[1])
        return Recognized("line", (x0, y0, abs(b[0] - a[0]), abs(b[1] - a[1])), points=[list(a), list(b)])
    # seta de um traço só: reta e, no fim, uma volta curta em "V"
    arrow = _arrow(pts, lim)
    if arrow:
        return arrow
    return None


def _arrow(pts: list[Point], lim: Limits) -> Recognized | None:
    n = len(pts)
    if n < 8:
        return None
    total = perimeter(pts, False)
    acc, cut = 0.0, n - 1
    for i in range(1, n):
        acc += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        if acc >= total * 0.62:
            cut = i
            break
    shaft = pts[:cut + 1]
    a = shaft[0]
    # a ponta é o ponto mais distante do começo
    far = max(range(n), key=lambda i: math.hypot(pts[i][0] - a[0], pts[i][1] - a[1]))
    tip = pts[far]
    length = math.hypot(tip[0] - a[0], tip[1] - a[1])
    if length < lim.minimum_size * 1.4 or far < n * 0.45:
        return None
    if max(_seg_dist(p, a, tip) for p in pts[:far + 1]) / length > lim.line_deviation * 2:
        return None
    head = pts[far:]
    if not head or len(head) < 3:
        return None
    head_len = perimeter(head, False)
    if not (0.08 * length <= head_len <= 0.9 * length):
        return None
    back = head[len(head) // 2] if len(head) > 2 else head[-1]
    ang_shaft = math.atan2(tip[1] - a[1], tip[0] - a[0])
    ang_back = math.atan2(back[1] - tip[1], back[0] - tip[0])
    diff = abs((ang_back - ang_shaft + math.pi) % (2 * math.pi) - math.pi)
    if diff < math.radians(110):
        return None
    x0, y0 = min(a[0], tip[0]), min(a[1], tip[1])
    return Recognized("arrow", (x0, y0, abs(tip[0] - a[0]), abs(tip[1] - a[1])), points=[list(a), list(tip)])


# ---------------------------------------------------------------------- geometria
def resample(pts: list[Point], count: int) -> list[Point]:
    total = perimeter(pts, False)
    if total == 0:
        return [pts[0]] * count
    step = total / (count - 1)
    out = [pts[0]]
    acc = 0.0
    prev = pts[0]
    i = 1
    while i < len(pts) and len(out) < count - 1:
        cur = pts[i]
        d = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        if acc + d >= step and d > 0:
            t = (step - acc) / d
            q = (prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1]))
            out.append(q)
            prev = q
            acc = 0.0
        else:
            acc += d
            prev = cur
            i += 1
    while len(out) < count:
        out.append(pts[-1])
    return out


def _closed_span(path: list[Point], tol: float):
    """Maior trecho que fecha (começo e fim próximos), cortando sobras nas pontas."""
    n = len(path)
    best = None
    for head in range(0, n // 4):
        for tail in range(n - 1, max(head + n // 2, n - n // 4) - 1, -1):
            if math.hypot(path[head][0] - path[tail][0], path[head][1] - path[tail][1]) <= tol:
                if best is None or (tail - head) > (best[1] - best[0]):
                    best = (head, tail)
                break
    return best


def perimeter(pts: list[Point], closed: bool) -> float:
    s = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    if closed and len(pts) > 1:
        s += math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
    return s


def signed_area(pts: list[Point]) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2


def convex_hull(pts: list[Point]) -> list[Point]:
    p = sorted(set(pts))
    if len(p) < 3:
        return p

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def min_area_rect(hull: list[Point]) -> dict:
    best = None
    n = len(hull)
    for i in range(n):
        a, b = hull[i], hull[(i + 1) % n]
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        c, s = math.cos(-ang), math.sin(-ang)
        rx = [p[0] * c - p[1] * s for p in hull]
        ry = [p[0] * s + p[1] * c for p in hull]
        w, h = max(rx) - min(rx), max(ry) - min(ry)
        area = w * h
        if best is None or area < best["area"]:
            mx, my = (max(rx) + min(rx)) / 2, (max(ry) + min(ry)) / 2
            cb, sb = math.cos(ang), math.sin(ang)
            best = {"area": area, "w": w, "h": h, "angle": ang, "cx": mx * cb - my * sb, "cy": mx * sb + my * cb}
    return best or {"area": 0, "w": 0, "h": 0, "angle": 0, "cx": 0, "cy": 0}


def _reduce(hull: list[Point], limit: int) -> list[Point]:
    if len(hull) <= limit:
        return hull
    step = len(hull) / limit
    return [hull[int(i * step)] for i in range(limit)]


def largest_polygon(hull: list[Point], k: int):
    n = len(hull)
    best_area, best = 0.0, hull[:k]
    if n < k:
        return abs(signed_area(hull)), hull
    if k == 3:
        for i in range(n):
            for j in range(i + 1, n):
                for m in range(j + 1, n):
                    a = abs(signed_area([hull[i], hull[j], hull[m]]))
                    if a > best_area:
                        best_area, best = a, [hull[i], hull[j], hull[m]]
        return best_area, best
    # quadrilátero: para cada diagonal (i, m), o ponto mais distante de cada lado
    for i in range(n):
        for m in range(i + 2, n):
            a, b = hull[i], hull[m]
            left = max(range(i + 1, m), key=lambda j: _tri(a, b, hull[j]), default=None)
            right = max([j for j in range(n) if j > m or j < i], key=lambda j: _tri(a, b, hull[j]), default=None)
            if left is None or right is None:
                continue
            area = _tri(a, b, hull[left]) + _tri(a, b, hull[right])
            if area > best_area:
                order = sorted([i, left, m, right])
                best_area, best = area, [hull[o] for o in order]
    return best_area, best


def _tri(a, b, c) -> float:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2


def _corner_deviation(quad) -> float:
    worst = 0.0
    for i in range(4):
        p, a, b = quad[i], quad[i - 1], quad[(i + 1) % 4]
        u, v = (a[0] - p[0], a[1] - p[1]), (b[0] - p[0], b[1] - p[1])
        ang = abs(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1]))
        worst = max(worst, abs(ang - math.pi / 2))
    return worst


def _template_error(points, template) -> float:
    total = 0.0
    for t in template:
        total += min(math.hypot(p[0] - t[0], p[1] - t[1]) for p in points)
    return total / len(template)


def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = dx * dx + dy * dy
    t = 0.0 if ln == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ln))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])
