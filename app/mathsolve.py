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
    """Como as pessoas escrevem: até 4 casas, vírgula decimal, sinal de menos."""
    if not math.isfinite(v):
        return "—"
    v = round(v, 4)
    if v == int(v) and abs(v) < 1e15:
        text = str(int(v))
    else:
        text = f"{v:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",").replace("-", "−")


def normalize_formula(raw: str) -> str | None:
    """O texto lido como fórmula (corrige o que a leitura da escrita confunde), ou None."""
    text = raw.strip()
    if "=" not in text or len(text) > 120:
        return None
    for a, b in (("×", "*"), ("·", "*"), ("•", "*"), ("÷", "/"), (":", "/"), ("−", "-"), ("–", "-"), ("—", "-"),
                 ("X", "x"), ("²", "^2"), (",", ".")):
        text = text.replace(a, b)
    text = "".join(text.split())
    digit_like = set("0123456789+-*/=^().")
    fixed = []
    for i, c in enumerate(text):
        before = text[i - 1] if i > 0 else None
        after = text[i + 1] if i + 1 < len(text) else None
        m = {"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8"}.get(c)
        if m and (before is None or before in digit_like) and (after is None or after in digit_like):
            fixed.append(m)
        else:
            fixed.append(c)
    text = "".join(fixed)
    text = re.sub(r"x2(?=[+\-=*/)]|$)", "x^2", text)
    if not set(text) <= set("0123456789.+-*/=^()x") or not any(c.isdigit() for c in text) or text.count("=") != 1:
        return None
    left, right = text.split("=")
    if not right and "x" in left:
        # conta sem lado direito: o x é o sinal de vezes ("3x4=")
        left = re.sub(r"(?<=[0-9)])x(?=[0-9(])", "*", left)
        if "x" in left:
            return None
        text = left + "="
    return text


class _Parser:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def sum(self):
        v = self.product()
        while self.peek() in ("+", "-") and self.peek():
            op = self.peek()
            self.i += 1
            r = self.product()
            v = v + r if op == "+" else v - r
        return v

    def product(self):
        v = self.power()
        while self.peek() in ("*", "/") and self.peek():
            op = self.peek()
            self.i += 1
            r = self.power()
            if op == "/":
                if r == 0:
                    raise EquationError("divisão por zero")
                v /= r
            else:
                v *= r
        return v

    def power(self):
        base = self.unary()
        if self.peek() == "^":
            self.i += 1
            e = self.power()
            if abs(e) > 64:
                raise EquationError("expoente grande demais")
            return base ** e
        return base

    def unary(self):
        if self.peek() == "-":
            self.i += 1
            return -self.unary()
        if self.peek() == "+":
            self.i += 1
            return self.unary()
        return self.atom()

    def atom(self):
        if self.peek() == "(":
            self.i += 1
            v = self.sum()
            if self.peek() != ")":
                raise EquationError("falta )")
            self.i += 1
            return v
        start = self.i
        while self.peek() and (self.peek().isdigit() or self.peek() == "."):
            self.i += 1
        try:
            return float(self.s[start:self.i])
        except ValueError:
            raise EquationError("número esperado")


def evaluate(expression: str) -> float:
    p = _Parser(expression)
    v = p.sum()
    if p.i != len(expression) or isinstance(v, complex) or not math.isfinite(v):
        raise EquationError("conta inválida")
    return v


def answer(formula: str) -> str | None:
    """"19" para "12+7=", "x = 3" para uma equação; None se não der para responder."""
    left, right = formula.split("=")
    if "x" not in formula:
        if right:
            return None
        try:
            return fmt(evaluate(left))
        except (EquationError, OverflowError, ZeroDivisionError):
            return None
    if not right:
        return None
    try:
        kind, roots = solve(formula)
    except EquationError:
        return None
    if kind == "all":
        return "todo x real"
    if kind == "none":
        return "sem solução real"
    return " ou ".join(f"x = {fmt(r)}" for r in roots)


def answer_text(raw: str) -> str | None:
    formula = normalize_formula(raw)
    return answer(formula) if formula else None
