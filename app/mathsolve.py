"""Equações de uma incógnita até o 2º grau, resolvidas sem IA e sem executar texto como código
(o mesmo resolvedor do Got It! para iPhone)."""

from __future__ import annotations

import math
import re


class EquationError(ValueError):
    pass


def normalize(expression: str) -> str:
    s = expression.lower()
    if "x" not in s and "×" in s:        # a escrita à mão às vezes lê o x da incógnita como ×
        s = s.replace("×", "x")
    for a, b in (("−", "-"), ("–", "-"), ("²", "^2"), ("×", "*"), (",", "."), ("·", "*"), (" ", "")):
        s = s.replace(a, b)
    return s


def _number(text: str) -> float:
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", text):
        raise EquationError("notação não suportada")
    v = float(text)
    if not math.isfinite(v):
        raise EquationError("número fora do alcance")
    return v


def _terms(expr: str) -> list[float]:
    if not expr:
        raise EquationError("lado vazio")
    coef = [0.0, 0.0, 0.0]
    i, n = 0, len(expr)
    while i < n:
        sign = 1.0
        if expr[i] in "+-":
            sign = -1.0 if expr[i] == "-" else 1.0
            i += 1
        start = i
        while i < n and expr[i] not in "+-":
            i += 1
        term = expr[start:i]
        if not term:
            raise EquationError("termo vazio")
        if "x" in term:
            prefix, suffix = term.split("x", 1)
            if prefix == "*":
                raise EquationError("coeficiente faltando")
            prefix = prefix.rstrip("*")
            power = {"": 1, "^1": 1, "^2": 2, "2": 2, "^0": 0}.get(suffix)
            if power is None:
                raise EquationError("só grau 0, 1 ou 2")
            c = 1.0 if prefix == "" else _number(prefix)
        else:
            power, c = 0, _number(term)
        coef[power] += sign * c
    return coef


def parse(expression: str) -> tuple[float, float, float]:
    if len(expression) > 2048:
        raise EquationError("expressão longa demais")
    s = normalize(expression)
    sides = s.split("=")
    if len(sides) != 2:
        raise EquationError("é preciso um sinal de igual")
    left, right = _terms(sides[0]), _terms(sides[1])
    return left[2] - right[2], left[1] - right[1], left[0] - right[0]


def solve(expression: str):
    """("roots", [..]) / ("none", []) / ("all", [])."""
    a, b, c = parse(expression)
    if a == 0:
        if b == 0:
            return ("all", []) if c == 0 else ("none", [])
        return "roots", [-c / b]
    if c == 0:
        other = -b / a
        return "roots", sorted({0.0, other})
    scale = max(abs(a), abs(b), abs(c))
    a, b, c = a / scale, b / scale, c / scale
    disc = b * b - 4 * a * c
    if disc < 0:
        return "none", []
    if disc == 0:
        return "roots", [-b / (2 * a)]
    q = -0.5 * (b + math.copysign(math.sqrt(disc), b if b != 0 else 1.0))
    return "roots", sorted([q / a, c / q])


def fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.4g}".replace(".", ",")


def answer_text(expression: str) -> str | None:
    """Texto da resposta (em azul, ao lado da equação) ou None se não for equação legível."""
    if "=" not in expression or "x" not in normalize(expression):
        return None
    try:
        kind, roots = solve(expression)
    except EquationError:
        return None
    if kind == "all":
        return "qualquer x"
    if kind == "none":
        return "sem solução real"
    return "  ou  ".join(f"x = {fmt(r)}" for r in roots)
