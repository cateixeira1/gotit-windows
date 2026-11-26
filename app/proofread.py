"""Revisão gramatical pelo assistente (Gemma 4 E2B, no computador).

O texto vai em partes de alguns parágrafos; para cada parte o modelo devolve uma lista JSON de
erros (trecho exato, correção e motivo). O app confere cada sugestão — o trecho tem de existir no
texto e a correção tem de ser diferente — e destaca os trechos na nota. No fim pergunta se é para
corrigir tudo (um passo de desfazer) ou revisar um por um.

É um modelo pequeno: acha boa parte dos erros de ortografia, acentuação e concordância, mas pode
deixar passar alguns e sugerir coisas que não são erro. Por isso nada é trocado sem a pessoa pedir.
"""

from __future__ import annotations

import json
import re
import threading

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

import theme

SYSTEM = "Você revisa textos em português do Brasil. Responda só com JSON."
CHUNK = 700


def prompt(text: str) -> str:
    return ("Encontre erros de ortografia, acentuação, concordância, regência, crase e pontuação no texto abaixo. "
            "Para cada erro, devolva um objeto com: \"trecho\" (copiado exatamente do texto, o menor trecho com o erro), "
            "\"correcao\" (o trecho corrigido) e \"motivo\" (curto). Não aponte estilo nem preferências. "
            "Se não houver erros, devolva []. Responda só com uma lista JSON.\n\nTexto:\n" + text)


def parse(answer: str, text: str) -> list[dict]:
    """Sugestões válidas: trecho presente no texto, correção diferente, nada enorme."""
    m = re.search(r"\[.*\]", answer or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    out, seen = [], set()
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        t, c = str(d.get("trecho") or "").strip(), str(d.get("correcao") or d.get("correção") or "").strip()
        why = str(d.get("motivo") or "").strip()
        if not t or not c or t == c or len(t) > 160 or t not in text or (t, c) in seen:
            continue
        seen.add((t, c))
        out.append({"trecho": t, "correcao": c, "motivo": why})
    return out


def chunks(doc) -> list[list]:
    """Partes de até ~700 caracteres, por parágrafo (os parágrafos vazios ficam de fora)."""
    parts, cur, size = [], [], 0
    b = doc.firstBlock()
    while b.isValid():
        t = b.text()
        if t.strip():
            if cur and size + len(t) > CHUNK:
                parts.append(cur)
                cur, size = [], 0
            c = QTextCursor(b)
            cur.append(c)
            size += len(t)
        b = b.next()
    if cur:
        parts.append(cur)
    return parts


class Issue:
    def __init__(self, cursor: QTextCursor, trecho: str, correcao: str, motivo: str):
        self.cursor, self.trecho, self.correcao, self.motivo = cursor, trecho, correcao, motivo
        self.done = False

    def valid(self) -> bool:
        return not self.done and self.cursor.selectedText() == self.trecho


def locate(block_cursors: list, sugg: dict, taken: list) -> QTextCursor | None:
    """Acha o trecho nos parágrafos da parte (o texto pode ter mudado desde o envio)."""
    for bc in block_cursors:
        block = bc.block()
        text = block.text()
        start = 0
        while True:
            i = text.find(sugg["trecho"], start)
            if i < 0:
                break
            pos = block.position() + i
            if not any(t.selectionStart() <= pos < t.selectionEnd() for t in taken):
                c = QTextCursor(block.document())
                c.setPosition(pos)
                c.setPosition(pos + len(sugg["trecho"]), QTextCursor.MoveMode.KeepAnchor)
                return c
            start = i + 1
    return None


class Worker(QObject):
    found = Signal(int, list)          # parte, sugestões
    progress = Signal(int, int)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, window, texts: list[str]):
        super().__init__()
        self.window, self.texts = window, texts
        self.cancel = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            import assistant
            import litert_lm
            engine = assistant.get_engine(self.window)
            for i, text in enumerate(self.texts):
                if self.cancel.is_set():
                    break
                self.progress.emit(i + 1, len(self.texts))
                conv = engine.create_conversation(
                    system_message=SYSTEM, sampler_config=litert_lm.SamplerConfig(temperature=0.1),
                    max_output_tokens=900, thinking_config=litert_lm.ThinkingConfig(enable_thinking=False))
                out = ""
                try:
                    for msg in conv.send_message_async(prompt(text)):
                        if self.cancel.is_set():
                            break
                        for part in msg.get("content", []) if isinstance(msg, dict) else []:
                            if part.get("type") == "text":
                                out += part.get("text", "")
                finally:
                    try:
                        conv.close()
                    except Exception:
                        pass
                self.found.emit(i, parse(out, text))
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
        self.parts = chunks(item.document())
        self.worker = None
        self.row = -1

    def start(self) -> None:
        texts = ["\n".join(c.block().text() for c in part) for part in self.parts]
        if not texts:
            self.status.setText("Não há texto para revisar.")
            return
        self.status.setText(f"O assistente está lendo o texto ({len(texts)} parte{'s' if len(texts) > 1 else ''})…")
        self.worker = Worker(self.editor.window, texts)
        self.worker.progress.connect(lambda i, n: self.status.setText(f"Lendo a parte {i} de {n}… "
                                                                       f"({len(self.live())} possíveis erros até agora)"))
        self.worker.found.connect(self.add_found)
        self.worker.finished.connect(self.finish)
        self.worker.failed.connect(lambda m: self.status.setText(m))
        self.worker.start()

    def live(self) -> list[Issue]:
        return [i for i in self.issues if i.valid()]

    def add_found(self, part: int, sugg: list) -> None:
        taken = [i.cursor for i in self.issues]
        for s in sugg:
            c = locate(self.parts[part], s, taken)
            if c is None:
                continue
            iss = Issue(c, s["trecho"], s["correcao"], s["motivo"])
            self.issues.append(iss)
            taken.append(c)
            it = QListWidgetItem(f"{s['trecho']}  →  {s['correcao']}" + (f"\n{s['motivo']}" if s["motivo"] else ""))
            self.list.addItem(it)
        self.item.update()

    def finish(self) -> None:
        n = len(self.live())
        if not n:
            self.status.setText("Revisão concluída: o assistente não achou erros.")
            self.ask.setText("")
            return
        self.status.setText(f"Revisão concluída: {n} possível erro destacado no texto." if n == 1 else
                            f"Revisão concluída: {n} possíveis erros destacados no texto.")
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
