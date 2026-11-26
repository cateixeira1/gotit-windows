"""Revisão gramatical pelo assistente (Gemma 4 E2B, no computador).

O texto vai em partes de ~1200 caracteres, frase por frase e numeradas; o modelo devolve só as
frases que tinham erro, já corrigidas, e o app compara palavra por palavra para apontar o que
mudou (trecho, correção e o tipo de erro). Reescritas grandes são descartadas. Cada frase aparece
assim que chega. No fim pergunta se é para corrigir tudo (um passo de desfazer) ou um por um.

Medido num computador de 2 núcleos (26/11/2026), num texto de 3.500 caracteres com 11 erros: a lista
em JSON com explicações levava cerca de 30 s por trecho de 360 caracteres; assim, 38 s no texto
inteiro, com o primeiro erro na tela em 5 s, achando 8 dos 11 sem nenhum falso alarme.

É um modelo pequeno: acha boa parte dos erros de ortografia, acentuação e concordância, mas pode
deixar passar alguns e sugerir coisas que não são erro. Por isso nada é trocado sem a pessoa pedir.
"""

from __future__ import annotations

import json
import re
import threading

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QVBoxLayout)

import theme

SYSTEM = "Você é um revisor de textos em português do Brasil."
CHUNK = 1200          # caracteres por pedido (frases inteiras)

# Abreviações que não terminam frase (Dr. Fulano, art. 186, p. 12, fls. 3...)
ABBREV = {"dr", "dra", "drs", "dras", "sr", "sra", "srs", "sras", "srta", "prof", "profa", "exmo", "exma", "ilmo", "ilma",
          "art", "arts", "inc", "incs", "par", "p", "pp", "fl", "fls", "n", "nº", "no", "nos", "v", "vs", "obs", "ex",
          "min", "des", "rel", "proc", "ed", "vol", "cap", "cf", "etc", "ltda", "cia", "av", "r", "tel", "jan", "fev",
          "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez", "s.a", "dt", "sec", "séc", "pág", "págs"}


def prompt(numbered: str) -> str:
    """Frases numeradas; o modelo devolve só as que tinham erro, já corrigidas. Escrever a frase
    corrigida (e não uma lista em JSON com explicações) é várias vezes mais rápido no computador e
    acha os mesmos erros; o app compara palavra por palavra e aponta só o que mudou."""
    return ("Abaixo há frases numeradas. Corrija os erros de ortografia, acentuação, concordância, regência, crase "
            "e pontuação. Responda só com as frases que tinham erro, com o mesmo número, já corrigidas, sem mudar "
            "mais nada (nem estilo, nem palavras certas). Se nenhuma frase tiver erro, escreva só: nenhum\n\n" + numbered)


def sentences(text: str) -> list[tuple[int, int]]:
    """Frases de um parágrafo como (início, fim), sem cortar em "Dr.", "art. 186", "R$ 1.800,00"."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch in ".!?…":
            j = i + 1
            while j < n and text[j] in ".!?…\"'”’)»":
                j += 1
            if j < n and text[j] == " ":
                k = j
                while k < n and text[k] == " ":
                    k += 1
                word = re.findall(r"[\w.]+$", text[start:i])
                prev = (word[0] if word else "").lower().rstrip(".")
                nxt = text[k] if k < n else ""
                if (nxt.isupper() or nxt.isdigit() or nxt in "\"“«(—–-") and prev not in ABBREV and not (len(prev) == 1 and prev.isalpha()):
                    if text[start:j].strip():
                        out.append((start, j))
                    start, i = k, k
                    continue
            i = j
            continue
        i += 1
    if text[start:].strip():
        out.append((start, len(text.rstrip())))
    return out


_TOKEN = re.compile(r"\w+|\s+|[^\w\s]", re.UNICODE)
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "«": '"', "»": '"'})


def _fold(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def motive(wrong: str, right: str) -> str:
    """Rótulo curto do tipo de erro, pela diferença entre os trechos."""
    if "à" in right.lower() and "à" not in wrong.lower():
        return "Crase"
    if _fold(wrong) == _fold(right):
        return "Acentuação" if wrong.lower() != right.lower() else "Maiúscula/minúscula"
    if re.sub(r"[\w\s]", "", wrong) != re.sub(r"[\w\s]", "", right) and re.sub(r"[^\w]", "", wrong) == re.sub(r"[^\w]", "", right):
        return "Pontuação"
    if "à" in right.lower() and "à" not in wrong.lower():
        return "Crase"
    ww, rw = wrong.split(), right.split()
    if len(ww) == len(rw) == 1:
        a, b = _fold(ww[0]), _fold(rw[0])
        common = 0
        while common < min(len(a), len(b)) and a[common] == b[common]:
            common += 1
        # só o fim da palavra mudou (plural, pessoa do verbo): concordância
        if common >= 3 and common >= min(len(a), len(b)) - 3 and abs(len(a) - len(b)) <= 3 and a != b:
            if max(len(a), len(b)) - common <= 3:
                return "Concordância"
        return "Ortografia"
    return "Concordância ou regência"


def diff(original: str, corrected: str) -> list[dict]:
    """O que mudou entre a frase e a frase corrigida, em trechos pequenos (palavra a palavra).
    Reescritas grandes (o modelo mudou a frase em vez de corrigir) são descartadas."""
    import difflib
    a = [m for m in _TOKEN.finditer(original)]
    b = [m for m in _TOKEN.finditer(corrected.strip())]
    ta = [m.group(0).translate(_QUOTES) if not m.group(0).isspace() else " " for m in a]
    tb = [m.group(0).translate(_QUOTES) if not m.group(0).isspace() else " " for m in b]
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    # reescrita (e não correção): as letras da frase mudaram demais
    if difflib.SequenceMatcher(None, _fold(original), _fold(corrected), autojunk=False).ratio() < 0.72:
        return []
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]

    def nwords(i1, i2):
        return sum(1 for t in ta[i1:i2] if re.match(r"\w", t))
    # junta mudanças vizinhas (separadas só por um espaço) num trecho de até 3 palavras:
    # "Os cliente chegou" -> "Os clientes chegaram" aparece como uma correção só
    merged = []
    for op in ops:
        if merged and op[1] - merged[-1][2] <= 1 and all(not t.strip() for t in ta[merged[-1][2]:op[1]]):
            prev = merged[-1]
            pure = prev[0] != "replace" or op[0] != "replace"
            if pure or nwords(prev[1], op[2]) <= 3:
                merged[-1] = ("replace", prev[1], op[2], prev[3], op[4])
                continue
        merged.append(op)
    out = []
    for tag, i1, i2, j1, j2 in merged:
        # trecho com palavras inteiras; inserção pura ganha a palavra vizinha como âncora
        if i1 == i2:
            if i1 > 0:
                i1 -= 1
                j1 -= 1
                while i1 > 0 and not ta[i1].strip():
                    i1 -= 1
                    j1 -= 1
            elif i2 < len(ta):
                i2 += 1
                j2 += 1
        if i1 >= len(a) or i2 <= i1:
            continue
        start, end = a[i1].start(), a[i2 - 1].end()
        wrong = original[start:end]
        right = "".join(m.group(0) for m in b[j1:j2]) if j2 > j1 else ""
        # ponto final que o modelo esqueceu, espaços e aspas diferentes: não é erro
        if wrong.strip() in (".", "") and i2 >= len(ta) - 1 and not right.strip():
            continue
        if wrong.translate(_QUOTES).strip() == right.translate(_QUOTES).strip():
            continue
        # ponto final acrescentado no fim (títulos e itens de lista não levam): não é erro
        if i2 >= len(ta) - 1 and right.rstrip(".") == wrong.rstrip("."):
            continue
        nw, nr = len(re.findall(r"\w+", wrong)), len(re.findall(r"\w+", right))
        if nw > 4 or nr > 5 or len(wrong) > 48:
            continue
        out.append({"start": start, "trecho": wrong, "correcao": right, "motivo": motive(wrong, right)})
    return out


def chunks(doc) -> list[list[QTextCursor]]:
    """Partes de até ~1200 caracteres, feitas de frases inteiras. Cada frase é um QTextCursor com a
    frase selecionada (acompanha o que a pessoa escrever enquanto a revisão anda)."""
    parts, cur, size = [], [], 0
    b = doc.firstBlock()
    while b.isValid():
        t = b.text()
        if t.strip():
            for s, e in sentences(t):
                if cur and size + (e - s) > CHUNK:
                    parts.append(cur)
                    cur, size = [], 0
                c = QTextCursor(doc)
                c.setPosition(b.position() + s)
                c.setPosition(b.position() + e, QTextCursor.MoveMode.KeepAnchor)
                cur.append(c)
                size += e - s
        b = b.next()
    if cur:
        parts.append(cur)
    return parts


def numbered(texts: list[str]) -> str:
    return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))


def parse_lines(answer: str, count: int) -> dict[int, str]:
    """Linhas "N. frase corrigida" da resposta (só números de frases que existem)."""
    out = {}
    for line in answer.split("\n"):
        m = re.match(r"^\s*\**\s*(\d{1,3})\s*[.)\-:]\s*\**\s*(.+?)\s*$", line)
        if m and 1 <= int(m.group(1)) <= count:
            out[int(m.group(1)) - 1] = m.group(2).strip().strip("*").strip()
    return out


class Issue:
    def __init__(self, cursor: QTextCursor, trecho: str, correcao: str, motivo: str):
        self.cursor, self.trecho, self.correcao, self.motivo = cursor, trecho, correcao, motivo
        self.done = False

    def valid(self) -> bool:
        return not self.done and self.cursor.selectedText() == self.trecho


def physical_threads() -> int:
    """Núcleos físicos (os "lógicos" do hyper-threading disputam a mesma unidade de cálculo)."""
    import os
    import sys
    n = os.cpu_count() or 4
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class INFO(ctypes.Structure):
                _fields_ = [("mask", ctypes.c_size_t), ("rel", wintypes.DWORD), ("pad", ctypes.c_byte * 16)]
            size = wintypes.DWORD(0)
            ctypes.windll.kernel32.GetLogicalProcessorInformation(None, ctypes.byref(size))
            buf = (INFO * (size.value // ctypes.sizeof(INFO)))()
            if ctypes.windll.kernel32.GetLogicalProcessorInformation(buf, ctypes.byref(size)):
                cores = sum(1 for i in buf if i.rel == 0)       # RelationProcessorCore
                if cores:
                    return max(1, cores)
        except Exception:
            pass
    else:
        try:
            ids, phys = set(), "0"
            for line in open("/proc/cpuinfo", encoding="utf-8"):
                if line.startswith("physical id"):
                    phys = line.split(":")[1].strip()
                elif line.startswith("core id"):
                    ids.add((phys, line.split(":")[1].strip()))
            if ids:
                return len(ids)
        except Exception:
            pass
    return max(1, n // 2 if n >= 4 else n)


class Worker(QObject):
    """Lê as partes uma a uma e devolve cada frase corrigida assim que ela chega (o que foi achado
    aparece na hora, sem esperar a parte inteira)."""
    found = Signal(int, int, list)      # parte, frase, sugestões
    progress = Signal(float)            # 0..1
    finished = Signal()
    failed = Signal(str)

    def __init__(self, window, parts: list[list[str]]):
        super().__init__()
        self.window, self.parts = window, parts
        self.cancel = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            import assistant
            engine = assistant.get_engine(self.window)
            total = sum(len(t) for part in self.parts for t in part) or 1
            done = 0
            for pi, texts in enumerate(self.parts):
                if self.cancel.is_set():
                    break
                sizes = [len(t) for t in texts]
                conv = assistant.conversation(engine, SYSTEM, temperature=0.1,
                                              max_tokens=min(1400, int(sum(sizes) / 2.2) + 120))
                out, emitted = "", set()

                def flush(final: bool) -> None:
                    lines = out.split("\n")
                    ready = "\n".join(lines if final else lines[:-1])
                    for si, fixed in parse_lines(ready, len(texts)).items():
                        if si in emitted:
                            continue
                        emitted.add(si)
                        sugg = diff(texts[si], fixed)
                        if sugg:
                            self.found.emit(pi, si, sugg)
                        self.progress.emit(min(1.0, (done + sum(sizes[:si + 1])) / total))
                try:
                    for msg in conv.send_message_async(prompt(numbered(texts))):
                        if self.cancel.is_set():
                            break
                        for part in msg.get("content", []) if isinstance(msg, dict) else []:
                            if part.get("type") == "text":
                                out += part.get("text", "")
                                if "\n" in part.get("text", ""):
                                    flush(False)
                    flush(True)
                finally:
                    try:
                        conv.close()
                    except Exception:
                        pass
                done += sum(sizes)
                self.progress.emit(done / total)
        except Exception as exc:
            self.failed.emit(f"A revisão parou: {type(exc).__name__}: {exc}")
            return
        self.finished.emit()


def paint_issues(item, painter: QPainter) -> None:
    """Sublinhado ondulado vermelho nos trechos apontados (e fundo no trecho em revisão)."""
    issues = getattr(item, "issues", None)
    if not issues:
        return
    doc = item.document()
    layout = doc.documentLayout()
    current = getattr(item, "current_issue", None)
    for iss in issues:
        if not iss.valid():
            continue
        a, b = iss.cursor.selectionStart(), iss.cursor.selectionEnd()
        block = doc.findBlock(a)
        while block.isValid() and block.position() <= b:
            br = layout.blockBoundingRect(block)
            tl = block.layout()
            for li in range(tl.lineCount()):
                line = tl.lineAt(li)
                ls, le = block.position() + line.textStart(), block.position() + line.textStart() + line.textLength()
                s, e = max(a, ls), min(b, le)
                if s >= e:
                    continue
                x1 = line.cursorToX(s - block.position())[0]
                x2 = line.cursorToX(e - block.position())[0]
                y = br.top() + line.y() + line.ascent() + 2
                r = QRectF(br.left() + x1, br.top() + line.y(), x2 - x1, line.height())
                if iss is current:
                    painter.fillRect(r, QColor(255, 196, 0, 90))
                pen = QPen(QColor("#E03131"), 1.1)
                painter.setPen(pen)
                x, up = br.left() + x1, True
                path_pts = []
                while x < br.left() + x2:
                    path_pts.append(QPointF(x, y + (0 if up else 2)))
                    x += 2
                    up = not up
                for p1, p2 in zip(path_pts, path_pts[1:]):
                    painter.drawLine(p1, p2)
            block = block.next()


class ProofPanel(QDialog):
    """Janela da revisão: lista o que foi achado, pergunta se corrige tudo ou um por um."""

    def __init__(self, editor, item):
        super().__init__(editor, Qt.WindowType.Tool)
        self.editor, self.item = editor, item
        self.setWindowTitle("Revisão do texto")
        self.setMinimumSize(380, 420)
        self.issues: list[Issue] = []
        item.issues = self.issues
        item.current_issue = None
        lay = QVBoxLayout(self)
        self.status = QLabel("Preparando…")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.list = QListWidget()
        self.list.itemClicked.connect(lambda it: self.show_issue(self.list.row(it)))
        lay.addWidget(self.list, 1)
        self.ask = QLabel("")
        self.ask.setWordWrap(True)
        self.ask.setStyleSheet(f"color: {theme.INK}; font-weight: 600;")
        lay.addWidget(self.ask)
        row = QHBoxLayout()
        self.all_btn = QPushButton("Corrigir tudo")
        self.one_btn = QPushButton("Revisar um por um")
        self.fix_btn = QPushButton("Corrigir")
        self.skip_btn = QPushButton("Pular")
        for b in (self.all_btn, self.one_btn, self.fix_btn, self.skip_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.all_btn.clicked.connect(self.fix_all)
        self.one_btn.clicked.connect(lambda: self.show_issue(self._next(-1)))
        self.fix_btn.clicked.connect(self.fix_current)
        self.skip_btn.clicked.connect(self.skip_current)
        self.fix_btn.hide()
        self.skip_btn.hide()
        self.all_btn.setEnabled(False)
        self.one_btn.setEnabled(False)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        lay.insertWidget(1, self.bar)
        self.parts = chunks(item.document())
        self.worker = None
        self.row = -1
        self.started = 0.0

    def start(self) -> None:
        texts = [[c.selectedText() for c in part] for part in self.parts]
        if not texts:
            self.status.setText("Não há texto para revisar.")
            self.bar.hide()
            return
        import time
        self.started = time.monotonic()
        self.status.setText("Revisando… os erros aparecem aqui assim que são achados.")
        self.worker = Worker(self.editor.window, texts)
        self.worker.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.worker.found.connect(self.add_found, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self.finish, Qt.ConnectionType.QueuedConnection)
        self.worker.failed.connect(lambda m: self.status.setText(m), Qt.ConnectionType.QueuedConnection)
        self.worker.start()

    def _progress(self, frac: float) -> None:
        self.bar.setValue(int(frac * 1000))
        n = len(self.live())
        found = "nenhum erro até agora" if not n else f"{n} possíve{'is' if n > 1 else 'l'} erro{'s' if n > 1 else ''} até agora"
        self.status.setText(f"Revisando… {int(frac * 100)}% ({found})")

    def live(self) -> list[Issue]:
        return [i for i in self.issues if i.valid()]

    def add_found(self, part: int, sentence: int, sugg: list) -> None:
        taken = [i.cursor for i in self.issues]
        base = self.parts[part][sentence]
        for s in sugg:
            c = QTextCursor(base.document())
            pos = base.selectionStart() + s["start"]
            c.setPosition(pos)
            c.setPosition(pos + len(s["trecho"]), QTextCursor.MoveMode.KeepAnchor)
            if c.selectedText() != s["trecho"] or any(t.selectionStart() < c.selectionEnd() and c.selectionStart() < t.selectionEnd()
                                                       for t in taken):
                continue
            iss = Issue(c, s["trecho"], s["correcao"], s["motivo"])
            self.issues.append(iss)
            taken.append(c)
            it = QListWidgetItem(f"{s['trecho']}  →  {s['correcao']}" + (f"\n{s['motivo']}" if s["motivo"] else ""))
            self.list.addItem(it)
        self.item.update()

    def finish(self) -> None:
        import time
        self.bar.hide()
        n = len(self.live())
        secs = f" em {time.monotonic() - self.started:.0f} s" if self.started else ""
        if not n:
            self.status.setText(f"Revisão concluída{secs}: o assistente não achou erros.")
            self.ask.setText("")
            return
        self.status.setText(f"Revisão concluída{secs}: {n} possível erro destacado no texto." if n == 1 else
                            f"Revisão concluída{secs}: {n} possíveis erros destacados no texto.")
        self.ask.setText("Quer que eu corrija tudo ou prefere revisar um por um?")
        self.all_btn.setEnabled(True)
        self.one_btn.setEnabled(True)

    def _next(self, after: int) -> int:
        for r in range(after + 1, len(self.issues)):
            if self.issues[r].valid():
                return r
        return -1

    def show_issue(self, row: int) -> None:
        self.row = row
        if row < 0 or not self.issues[row].valid():
            self.item.current_issue = None
            self.fix_btn.hide()
            self.skip_btn.hide()
            self.item.update()
            if not self.live():
                self.ask.setText("Pronto: revisão terminada.")
            return
        iss = self.issues[row]
        self.list.setCurrentRow(row)
        self.item.current_issue = iss
        self.fix_btn.show()
        self.skip_btn.show()
        self.ask.setText(f"“{iss.trecho}” → “{iss.correcao}”" + (f" — {iss.motivo}" if iss.motivo else ""))
        c = QTextCursor(iss.cursor)
        self.editor.ensure_rect_visible(self.item, c)
        self.item.update()

    def _apply(self, iss: Issue) -> None:
        if iss.valid():
            iss.cursor.insertText(iss.correcao)
        iss.done = True
        r = self.issues.index(iss)
        it = self.list.item(r)
        if it is not None:
            it.setForeground(QColor("#9AA5B1"))

    def fix_current(self) -> None:
        if 0 <= self.row < len(self.issues):
            self.editor.history.break_group()
            self._apply(self.issues[self.row])
            self.editor.history.break_group()
            self.editor.content_changed()
        self.show_issue(self._next(self.row))

    def skip_current(self) -> None:
        if 0 <= self.row < len(self.issues):
            iss = self.issues[self.row]
            iss.done = True
            self.list.item(self.row).setForeground(QColor("#9AA5B1"))
        self.show_issue(self._next(self.row))

    def fix_all(self) -> None:
        live = self.live()
        if not live:
            return
        doc = self.item.document()
        c = QTextCursor(doc)
        self.editor.history.break_group()
        c.beginEditBlock()
        for iss in live:
            self._apply(iss)
        c.endEditBlock()
        self.editor.history.break_group()
        self.editor.content_changed()
        self.item.current_issue = None
        self.item.update()
        self.ask.setText(f"Pronto: {len(live)} correç{'ões' if len(live) > 1 else 'ão'} feita{'s' if len(live) > 1 else ''} "
                         "(Ctrl+Z desfaz todas de uma vez).")
        self.all_btn.setEnabled(False)
        self.one_btn.setEnabled(False)

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
        self.item.issues = []
        self.item.current_issue = None
        self.item.update()
        super().closeEvent(event)
