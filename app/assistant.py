"""Assistente do Got It! no computador: Gemma 4 E2B pelo LiteRT-LM (o mesmo modelo, motor e
instruções do Got It! para iPhone). Resume a nota aberta, cria perguntas de revisão, propõe
título, pasta e pendências, e responde perguntas às notas citando os trechos usados como fontes.
Nada sai do computador."""

from __future__ import annotations

import html
import os
import re
import threading
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

import icons
import model
import models
import theme

SYSTEM = ("Você é o assistente do Got It!, um app de notas. Responda sempre em português do Brasil, "
          "de forma clara e direta. Use apenas o que está no texto fornecido; não invente fatos, "
          "datas, nomes ou números. Se a informação pedida não estiver no texto, diga isso.")
NOTE_LIMIT = 9000
SOURCES_LIMIT = 6000
MAX_SOURCES = 6
CONTEXT = 4096
ANSWER_TOKENS = 700

_engine = None
_engine_lock = threading.Lock()
_panel = None


# ---------------------------------------------------------------------- textos
def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def note_text(doc: dict, limit: int = NOTE_LIMIT) -> tuple[str, bool]:
    """Texto da nota em ordem de leitura (texto, caixas, post-its, transcrições, tabelas,
    legendas), cortado em parágrafo ou frase."""
    page_of = {p["id"]: i for i, p in enumerate(doc["pages"])}
    parts = []
    story = (doc.get("story") or {}).get("text") or ""
    if story.strip():
        parts.append((-1, 0, 0, story.strip()))
    for b in doc.get("blocks", []):
        t = (b.get("text") or "").strip()
        cap = (b.get("caption") or "").strip()
        f = b.get("frame") or {}
        idx = page_of.get(b.get("pageID"), 0)
        for piece in (t, cap):
            if piece:
                parts.append((idx, f.get("y", 0), f.get("x", 0), piece))
    parts.sort(key=lambda p: p[:3])
    whole = "\n\n".join(p[3] for p in parts)
    if len(whole) <= limit:
        return whole, False
    head = whole[:limit]
    for mark in ("\n\n", ". ", "\n", " "):
        cut = head.rfind(mark)
        if cut > limit // 2:
            return head[:cut].strip() + ("." if mark == ". " else ""), True
    return head, True


def heading(title: str) -> str:
    return f"Nota: {title.strip()}" if title.strip() else "Nota sem título"


class SummaryPlan:
    minimum_words = 40

    def __init__(self, note_words: int):
        self.note_words = note_words
        self.max_words = min(120, max(20, note_words // 5))
        self.topics = min(6, max(1, self.max_words // 18))

    @property
    def max_tokens(self) -> int:
        return min(ANSWER_TOKENS, self.max_words * 2 + 160)


def summary_prompt(title: str, text: str, truncated: bool) -> tuple[str, SummaryPlan]:
    plan = SummaryPlan(word_count(text))
    shape = "em UMA frase curta" if plan.topics == 1 else f"em no máximo {plan.topics} tópicos (cada um com até 12 palavras)"
    cut = "A nota foi cortada por ser longa; resuma só o trecho fornecido.\n" if truncated else ""
    return (f"Faça um RESUMO da nota abaixo {shape}. O resumo inteiro deve ter no máximo {plan.max_words} "
            f"palavras; a nota tem {plan.note_words}. Resumir é condensar: junte as ideias, fique só com o "
            "essencial (decisões, datas, nomes, valores) e deixe de fora exemplos, explicações e "
            "detalhes. Não reescreva a nota trecho por trecho, não copie frases inteiras dela e não "
            "acrescente nada que não esteja nela. Não escreva introdução nem conclusão.\n"
            "Depois do resumo, só se a nota tiver tarefas ou prazos, escreva \"Pendências:\" e liste "
            "cada uma em poucas palavras (com o prazo, se houver). Se não houver, não escreva essa parte.\n"
            f"{cut}{heading(title)}\n---\n{text}\n---"), plan


def trimmed_summary(answer: str, plan: SummaryPlan) -> str:
    lines = answer.split("\n")
    todo = next((i for i, ln in enumerate(lines) if ln.replace("*", "").strip().lower().startswith("pendências")), None)
    head = lines[:todo] if todo is not None else lines
    tail = lines[todo:] if todo is not None else []

    def is_topic(line: str) -> bool:
        t = line.strip()
        return t.startswith(("* ", "- ", "• ")) or bool(re.match(r"^\d+[.)] ", t))
    if not any(is_topic(ln) for ln in head):
        return answer.strip()
    kept, topics = [], 0
    for ln in head:
        if is_topic(ln):
            topics += 1
            if topics <= max(plan.topics, 1):
                kept.append(ln)
        elif topics > 0 and ln.strip() and topics <= plan.topics:
            kept.append(ln)
    summary = "\n".join(kept).strip()
    rest = "\n".join(tail).strip()
    return summary + ("\n\n" + rest if rest else "")


def question_count(text: str) -> int:
    return min(8, max(3, word_count(text) // 120))


def questions_prompt(title: str, text: str, truncated: bool) -> str:
    """Perguntas para a pessoa testar se entendeu a nota: pontos principais da nota inteira, na
    ordem, com o porquê e as consequências (não detalhes soltos); respostas todas no fim."""
    cut = "A nota foi cortada por ser longa; use só o trecho fornecido.\n" if truncated else ""
    n = question_count(text)
    return (f"Leia a nota inteira abaixo e escreva {n} perguntas para a pessoa testar se entendeu e lembra do "
            "conteúdo. Cubra os pontos principais da nota do começo ao fim, na ordem em que aparecem, uma pergunta "
            "por ponto. Prefira perguntas que exijam entender o contexto: por que algo aconteceu ou importa, o que "
            "foi decidido, quais as consequências, prazos, valores e próximos passos. Evite perguntas sobre "
            "detalhes soltos e perguntas cuja resposta está escrita na própria pergunta. Cada pergunta deve poder "
            "ser respondida só com a nota.\n"
            "Formato: primeiro todas as perguntas, numeradas de 1 a "
            f"{n}, sem as respostas. Depois, uma linha só com \"Respostas:\" e as respostas curtas (até 2 frases), "
            "com os mesmos números.\n"
            f"{cut}{heading(title)}\n---\n{text}\n---")


def quiz_layout(answer: str) -> str:
    """Perguntas primeiro e as respostas todas no fim (para a pessoa se testar), mesmo que o modelo
    tenha posto cada resposta logo depois da pergunta."""
    questions, answers, in_answers, current = {}, {}, False, None
    for raw in answer.replace("**", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        low = line.lower().rstrip(":")
        if low in ("respostas", "gabarito"):
            in_answers, current = True, None
            continue
        if low in ("perguntas", "perguntas para revisar"):
            continue
        m = re.match(r"^(\d{1,2})\s*[.)\-:]\s*(.*)$", line)
        r = re.match(r"^(resposta|r)\s*[:.\-]\s*(.*)$", line, re.IGNORECASE)
        if m:
            num, body = int(m.group(1)), m.group(2).strip()
            body = re.sub(r"^(pergunta|resposta)\s*:\s*", "", body, flags=re.IGNORECASE)
            if in_answers:
                answers[num] = body
            else:
                questions[num] = body
            current = num
        elif r and current is not None:
            answers[current] = (answers.get(current, "") + " " + r.group(2)).strip()
        elif current is not None:
            target = answers if (in_answers or current in answers) else questions
            target[current] = (target.get(current, "") + " " + line).strip()
    if not questions:
        return answer.strip()
    out = ["Perguntas"] + [f"{n}. {q}" for n, q in sorted(questions.items())]
    if answers:
        out += ["", "Respostas"] + [f"{n}. {answers[n]}" for n in sorted(questions) if n in answers]
    return "\n".join(out)


def question_prompt(question: str, sources: list[dict]) -> str:
    numbered = "\n\n".join(f"[{i + 1}] {heading(s['title'])}\n{s['text']}" for i, s in enumerate(sources))
    return ("Responda à pergunta usando somente os trechos das notas abaixo. Depois de cada "
            "informação, indique de qual trecho ela veio, como [1] ou [2]. Se os trechos não "
            "responderem à pergunta, diga que não encontrou isso nas notas.\n\n"
            f"Trechos:\n{numbered}\n\nPergunta: {question.strip()}")


def organize_prompt(title: str, text: str, folders: list[str]) -> str:
    names = "; ".join(folders) if folders else "(nenhuma)"
    return ("Leia a nota abaixo e proponha, exatamente neste formato de linhas:\n"
            "Título: <um título curto de até 10 palavras>\n"
            "Pasta: <uma destas pastas, ou nenhuma: " + names + ">\n"
            "Pendências:\n- <tarefa curta tirada da nota>\n"
            "Use só o que está na nota. Se não houver tarefas, escreva \"Pendências: nenhuma\".\n"
            f"{heading(title)}\n---\n{text}\n---")


def parse_proposal(answer: str, current_title: str, folders: dict, current_folder: str | None, note: str) -> dict:
    """Só aceita: título de até 10 palavras diferente do atual; pasta que existe (e não é a
    atual); até 8 tarefas que tenham palavra ou número da própria nota, sem repetidas."""
    out = {"title": None, "folder": None, "tasks": []}
    words = {w.lower() for w in re.findall(r"\w{3,}", note, flags=re.UNICODE)}
    in_tasks = False
    for raw in answer.split("\n"):
        line = raw.strip().replace("**", "")
        low = line.lower()
        if low.startswith("título:"):
            t = line.split(":", 1)[1].strip().strip('"“”')
            if t and len(t.split()) <= 10 and t.lower() != (current_title or "").lower():
                out["title"] = t
            in_tasks = False
        elif low.startswith("pasta:"):
            name = line.split(":", 1)[1].strip().strip('"“”').lower()
            for fid, fname in folders.items():
                if fname.lower() == name and fid != current_folder:
                    out["folder"] = fid
            in_tasks = False
        elif low.startswith("pendências"):
            in_tasks = "nenhuma" not in low
        elif in_tasks and line[:1] in "-*•":
            task = line.lstrip("-*• ").strip()
            tw = {w.lower() for w in re.findall(r"\w{3,}", task, flags=re.UNICODE)}
            if task and (tw & words or re.search(r"\d", task)) and task not in out["tasks"] and len(out["tasks"]) < 8:
                out["tasks"].append(task)
    return out


def citations(answer: str, count: int) -> list[int]:
    found = []
    for inside in re.findall(r"\[([^\]]+)\]", answer):
        for piece in re.split(r"[,; ]+", inside):
            if piece.isdigit() and 1 <= int(piece) <= count and int(piece) not in found:
                found.append(int(piece))
    return found


def plain_text(markdown: str) -> str:
    out = []
    for line in markdown.split("\n"):
        text = line.replace("**", "").replace("__", "")
        stripped = text.lstrip(" ")
        indent = text[: len(text) - len(stripped)]
        if stripped.startswith(("* ", "- ")):
            text = indent + "• " + stripped[2:]
        elif stripped.startswith("#"):
            text = stripped.lstrip("#").lstrip()
        out.append(text)
    return "\n".join(out).strip()


def pick_sources(candidates: list[dict]) -> list[dict]:
    seen, picked, used = set(), [], 0
    for c in candidates:
        if len(picked) >= MAX_SOURCES or used >= SOURCES_LIMIT:
            break
        key = (c["doc_id"], c["part"], c["text"][:40])
        if key in seen:
            continue
        seen.add(key)
        s = dict(c)
        if len(s["text"]) > SOURCES_LIMIT - used:
            s["text"] = s["text"][: SOURCES_LIMIT - used] + "…"
        used += len(s["text"])
        picked.append(s)
    return picked


# ---------------------------------------------------------------------- motor
class Runner(QObject):
    chunk = Signal(str)
    status = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, window, prompt: str, max_tokens: int):
        super().__init__()
        self.window, self.prompt, self.max_tokens = window, prompt, max_tokens
        self.cancel = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        text = ""
        for attempt in (1, 2):
            try:
                engine = get_engine(self.window, self.status.emit)
                self.status.emit("Lendo a nota…")
                conv = conversation(engine, SYSTEM, temperature=0.3, max_tokens=self.max_tokens)
                try:
                    for msg in conv.send_message_async(self.prompt):
                        if self.cancel.is_set():
                            break
                        for part in msg.get("content", []) if isinstance(msg, dict) else []:
                            if part.get("type") == "text":
                                text += part.get("text", "")
                                self.chunk.emit(text)
                finally:
                    try:
                        conv.close()
                    except Exception:
                        pass
                self.done.emit(text)
                return
            except Exception as exc:
                if attempt == 1 and not text:
                    global _SPECULATIVE
                    _SPECULATIVE = False   # repete sem a decodificação especulativa
                    release()          # carrega o modelo de novo uma vez e repete
                    continue
                self.failed.emit(f"O assistente parou: {type(exc).__name__}: {exc}")
                return


_SPECULATIVE = True        # MTP: o mesmo texto, quase 2× mais rápido; desliga sozinho se o motor recusar


def conversation(engine, system: str, temperature: float, max_tokens: int):
    """Conversa nova com decodificação especulativa (MTP) quando o modelo e o motor aceitam: o
    Gemma 4 E2B propõe vários tokens de uma vez e confere; o resultado é o mesmo, mais rápido."""
    global _SPECULATIVE
    import litert_lm
    base = dict(system_message=system, sampler_config=litert_lm.SamplerConfig(temperature=temperature),
                max_output_tokens=max_tokens, thinking_config=litert_lm.ThinkingConfig(enable_thinking=False))
    if _SPECULATIVE:
        try:
            return engine.create_conversation(**base, speculative_decoding_config=litert_lm.SpeculativeDecodingConfig(
                mode=litert_lm.SpeculativeDecodingMode.ON))
        except Exception:
            _SPECULATIVE = False
    return engine.create_conversation(**base)


def get_engine(window, status=None):
    global _engine
    with _engine_lock:
        if _engine is None:
            import litert_lm
            litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
            if status:
                status("Carregando o modelo (alguns segundos na primeira vez)…")
            path = models.path_of(window.store.data_dir, models.ASSISTANT)
            import proofread
            threads = proofread.physical_threads()
            _engine = litert_lm.Engine(str(path), backend=litert_lm.Backend.CPU(thread_count=threads), max_num_tokens=CONTEXT,
                                       cache_dir=str(models.folder(window.store.data_dir, models.ASSISTANT)))
        return _engine


def release() -> None:
    global _engine
    with _engine_lock:
        if _engine is not None:
            try:
                _engine.close()
            except Exception:
                pass
            _engine = None


def shutdown() -> None:
    release()


# ---------------------------------------------------------------------- painel
class Bubble(QFrame):
    def __init__(self, text: str, mine: bool):
        super().__init__()
        self.setObjectName("bubble")
        bg = "#DCE8F7" if mine else "white"
        self.setStyleSheet(f"#bubble {{ background: {bg}; border: 1px solid {theme.LINE}; border-radius: 12px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 9, 12, 9)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lay.addWidget(self.label)


class PanelHeader(QWidget):
    """Cabeçalho do balão: arrastar move o balão, sempre dentro da janela do app."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self._grab = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._grab = e.globalPosition().toPoint() - self.panel.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._grab is not None:
            self.panel.place(e.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, e):
        self._grab = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)


class AssistantPanel(QFrame):
    """Balão do assistente, por cima da nota e sempre dentro da janela do app (não sai da tela
    ao ser arrastado; acompanha a janela quando ela muda de tamanho)."""
    MARGIN = 12

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("assistantPanel")
        self.setStyleSheet(f"#assistantPanel {{ background: {theme.WINDOW}; border: 1px solid #D9DEE3; border-radius: 14px; }}")
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)
        self.resize(440, 640)
        self.runner: Runner | None = None
        self.scope: list[str] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        header = PanelHeader(self)
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 2, 0, 2)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("sparkle", theme.TEAL, 22))
        t = QLabel("Assistente")
        t.setFont(theme.ui_font(13, True))
        self.where = QLabel("Gemma 4 E2B · neste computador")
        self.where.setStyleSheet(f"color: {theme.MUTED};")
        close = QToolButton()
        close.setIcon(icons.icon("close", theme.MUTED))
        close.setToolTip("Fechar")
        close.clicked.connect(self.hide)
        head.addWidget(ic)
        head.addWidget(t)
        head.addStretch()
        head.addWidget(self.where)
        head.addWidget(close)
        lay.addWidget(header)
        window.installEventFilter(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.host = QWidget()
        self.msgs = QVBoxLayout(self.host)
        self.msgs.setSpacing(10)
        self.msgs.addStretch(1)
        self.scroll.setWidget(self.host)
        self.host.setObjectName("chat")
        self.host.setStyleSheet(f"#chat {{ background: {theme.WINDOW}; }}")
        lay.addWidget(self.scroll, 1)
        self.suggest = QHBoxLayout()
        self.b_sum = QPushButton(icons.icon("note"), "Resumir esta nota")
        self.b_q = QPushButton(icons.icon("list-num"), "Perguntas para revisar")
        self.b_org = QPushButton(icons.icon("folder"), "Organizar esta nota")
        for b in (self.b_sum, self.b_q, self.b_org):
            self.suggest.addWidget(b)
        lay.addLayout(self.suggest)
        self.b_sum.clicked.connect(self.summarize)
        self.b_q.clicked.connect(self.study)
        self.b_org.clicked.connect(self.organize)
        row = QHBoxLayout()
        self.scope_btn = QToolButton()
        self.scope_btn.setIcon(icons.icon("plus"))
        self.scope_btn.setToolTip("Escolher as notas onde procurar")
        self.scope_btn.clicked.connect(self.choose_scope)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Perguntar às notas…")
        self.send = QPushButton("Enviar")
        self.send.setProperty("primary", True)
        row.addWidget(self.scope_btn)
        row.addWidget(self.input, 1)
        row.addWidget(self.send)
        lay.addLayout(row)
        self.scope_label = QLabel("")
        self.scope_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        lay.addWidget(self.scope_label)
        self.send.clicked.connect(self.ask)
        self.input.returnPressed.connect(self.ask)
        self.model_box = None
        self.refresh_state()

    # ------------------------------------------------------------------ posição
    def bounds(self):
        return self.window.rect().adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)

    def place(self, top_left=None) -> None:
        """Põe o balão no lugar pedido, mas sempre inteiro dentro da janela."""
        area = self.bounds()
        w = min(440, area.width())
        h = min(max(360, self.height()), area.height())
        if self.size() != QSize(w, h):
            self.resize(w, h)
        p = top_left if top_left is not None else self.pos()
        x = max(area.left(), min(p.x(), area.right() - w + 1))
        y = max(area.top(), min(p.y(), area.bottom() - h + 1))
        self.move(x, y)

    def dock(self) -> None:
        """Canto inferior direito da nota, acima do botão do assistente."""
        area = self.bounds()
        h = min(640, area.height())
        self.resize(min(440, area.width()), h)
        self.place(area.bottomRight() - QPoint(self.width() + 74, h - 1))

    def eventFilter(self, obj, ev):
        if obj is self.window and ev.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

    # ------------------------------------------------------------------ estado
    def refresh_state(self) -> None:
        ready = models.is_ready(self.window.store.data_dir, models.ASSISTANT)
        doc = self.window.editor.doc
        for b in (self.b_sum, self.b_q, self.b_org):
            b.setVisible(ready and doc is not None)
        self.input.setEnabled(ready)
        self.send.setEnabled(ready)
        if not ready and self.model_box is None:
            self.model_box = QFrame()
            self.model_box.setObjectName("modelbox")
            self.model_box.setStyleSheet(f"#modelbox {{ background: white; border: 1px solid {theme.LINE}; border-radius: 12px; }}")
            v = QVBoxLayout(self.model_box)
            msg = QLabel("O assistente roda inteiro neste computador, sem internet e sem enviar as suas notas. "
                         "Para isso, baixe uma vez o modelo Gemma 4 E2B, do Google (licença Apache 2.0).")
            msg.setWordWrap(True)
            v.addWidget(msg)
            row = models.ModelRow(self.window, models.ASSISTANT)
            orig = row._finished

            def finished(ok, message):
                orig(ok, message)
                if ok:
                    self.model_box.hide()
                    self.refresh_state()
            row._finished = finished
            v.addWidget(row)
            self.msgs.insertWidget(self.msgs.count() - 1, self.model_box)
        if ready and self.model_box is not None:
            self.model_box.hide()

    def _add(self, widget) -> None:
        self.msgs.insertWidget(self.msgs.count() - 1, widget)
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def _busy(self, on: bool) -> None:
        for w in (self.send, self.b_sum, self.b_q, self.b_org, self.input):
            w.setEnabled(not on)

    # ------------------------------------------------------------------ pedidos
    def _note(self):
        ed = self.window.editor
        if ed.doc is None:
            return None
        ed.save_now()
        return ed.scene.serialize()

    def summarize(self) -> None:
        doc = self._note()
        if doc is None:
            return
        text, cut = note_text(doc)
        if word_count(text) < SummaryPlan.minimum_words:
            self._add(Bubble("Esta nota é curta demais para resumir (menos de 40 palavras).", False))
            return
        prompt, plan = summary_prompt(doc["title"], text, cut)
        self._add(Bubble("Resumir esta nota", True))
        self._run(prompt, plan.max_tokens, title="Resumo", post=lambda a: trimmed_summary(a, plan),
                  note=("A nota foi cortada por ser longa: o resumo usa só o começo." if cut else ""))

    def study(self) -> None:
        doc = self._note()
        if doc is None:
            return
        text, cut = note_text(doc)
        if not text.strip():
            self._add(Bubble("A nota ainda não tem texto.", False))
            return
        self._add(Bubble("Perguntas para revisar", True))
        self._run(questions_prompt(doc["title"], text, cut), 120 + 70 * question_count(text), title="Perguntas para revisar",
                  post=quiz_layout)

    def organize(self) -> None:
        doc = self._note()
        if doc is None:
            return
        text, _ = note_text(doc)
        if not text.strip():
            self._add(Bubble("A nota ainda não tem texto.", False))
            return
        folders = {f.id: f.name for f in self.window.store.folders("*")}
        info = self.window.store.info(doc["id"])
        self._add(Bubble("Organizar esta nota", True))

        def show(answer: str):
            prop = parse_proposal(answer, doc["title"], folders, info.folder_id if info else None, text)
            self._proposal(doc["id"], prop, folders)
        self._run(organize_prompt(doc["title"], text, list(folders.values())), 300, raw=show)

    def ask(self) -> None:
        q = self.input.text().strip()
        if not q:
            return
        self.input.clear()
        self._add(Bubble(q, True))
        sources = self._find_sources(q)
        if not sources:
            self._add(Bubble("Não encontrei nada sobre isso nas notas.", False))
            return
        self._run(question_prompt(q, sources), ANSWER_TOKENS, title="Resposta", sources=sources)

    def _find_sources(self, q: str) -> list[dict]:
        store = self.window.store
        only = set(self.scope) if self.scope else None
        found = []
        try:
            import semantic
            idx = semantic.index(self.window)
            if idx is not None:
                for score, doc_id, part, text in idx.passages(q, limit=14, only=only):
                    info = store.info(doc_id)
                    if info and not info.trashed_at:
                        found.append({"doc_id": doc_id, "part": part, "title": info.title, "text": text})
        except Exception:
            pass
        if not found:
            hits = store.search(q) or store.search_any(q)
            for h in hits:
                if only is not None and h.doc_id not in only:
                    continue
                doc = store.load(h.doc_id)
                if not doc:
                    continue
                text = dict(model.collect_text(doc)).get(h.part) or note_text(doc, 1500)[0]
                found.append({"doc_id": h.doc_id, "part": h.part, "title": h.title, "text": text[:1500]})
            ed = self.window.editor
            if not found and only is None and ed.doc is not None:
                only = {ed.doc["id"]}           # sem nada nas buscas: a nota aberta
            if only is not None and not found:
                for doc_id in only:
                    doc = self._note() if (ed.doc is not None and ed.doc["id"] == doc_id) else store.load(doc_id)
                    if doc:
                        found.append({"doc_id": doc_id, "part": "story", "title": doc["title"], "text": note_text(doc, 1500)[0]})
        return pick_sources(found)

    def choose_scope(self) -> None:
        import dialogs
        dlg = dialogs.NotePicker(self.window.store.notes(), "Procurar só nestas notas", multi=True,
                                 previews=self.window.thumbs.small, parent=self, ok_text="Usar estas")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.scope = dlg.chosen()
            names = [self.window.store.info(i).title for i in self.scope if self.window.store.info(i)]
            self.scope_label.setText(("Procurando em: " + ", ".join(names)) if names else "")

    # ------------------------------------------------------------------ execução
    def _run(self, prompt: str, max_tokens: int, title: str = "", post=None, sources=None, note: str = "", raw=None):
        bubble = Bubble("…", False)
        self._add(bubble)
        self._busy(True)
        started = time.monotonic()
        self.runner = Runner(self.window, prompt, max_tokens)
        self.runner.status.connect(lambda s: bubble.label.setText(s), Qt.ConnectionType.QueuedConnection)
        self.runner.chunk.connect(lambda t: bubble.label.setText(t), Qt.ConnectionType.QueuedConnection)

        def done(answer: str):
            self._busy(False)
            if raw is not None:
                bubble.label.setText(answer.strip() or "(sem resposta)")
                raw(answer)
                return
            final = post(answer) if post else answer.strip()
            bubble.label.setText(plain_text(final) or "(sem resposta)")
            secs = time.monotonic() - started
            if note:
                n = QLabel(note)
                n.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
                bubble.lay.addWidget(n)
            cited = []
            nums = citations(final, len(sources)) if sources else []
            if nums:
                cited = [(n, sources[n - 1]) for n in nums]
                box = QLabel("<b>Fontes</b><br>" + "<br>".join(
                    f'<a href="{n}">[{n}] {html.escape(s["title"] or "Sem título")}</a>' for n, s in cited))
                box.setTextFormat(Qt.TextFormat.RichText)
                box.linkActivated.connect(lambda href: self._open_source(sources[int(href) - 1]))
                bubble.lay.addWidget(box)
            row = QHBoxLayout()
            copy = QPushButton(icons.icon("copy"), "Copiar")
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(plain_text(final)))
            insert = QPushButton(icons.icon("plus"), "Inserir na nota")
            insert.setEnabled(self.window.editor.doc is not None)
            insert.clicked.connect(lambda: self._insert(final, title, cited))
            t = QLabel(f"{secs:.0f} s")
            t.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
            row.addWidget(copy)
            row.addWidget(insert)
            row.addStretch()
            row.addWidget(t)
            bubble.lay.addLayout(row)

        def failed(msg: str):
            self._busy(False)
            bubble.label.setText(msg)
        self.runner.done.connect(done, Qt.ConnectionType.QueuedConnection)
        self.runner.failed.connect(failed, Qt.ConnectionType.QueuedConnection)
        self.runner.start()

    def _insert(self, answer: str, title: str, cited) -> None:
        ed = self.window.editor
        if ed.doc is None:
            return
        text = plain_text(answer)
        if cited:
            text += "\n\nFontes: " + "; ".join(f"[{n}] {s['title']}" for n, s in cited)
        ed.insert_plain_text(text, title=title or None)
        self.window.raise_()

    def _open_source(self, source: dict) -> None:
        words = " ".join(re.findall(r"\w{4,}", source["text"], flags=re.UNICODE)[:2])
        self.window.open_note(source["doc_id"], find=words or None, part=source["part"])

    def _proposal(self, doc_id: str, prop: dict, folders: dict) -> None:
        box = QFrame()
        box.setObjectName("proposal")
        box.setStyleSheet(f"#proposal {{ background: white; border: 1px solid {theme.LINE}; border-radius: 12px; }}")
        v = QVBoxLayout(box)
        checks = []
        if prop["title"]:
            c = QCheckBox(f"Título: {prop['title']}")
            c.setChecked(True)
            checks.append(("title", c))
            v.addWidget(c)
        if prop["folder"]:
            c = QCheckBox(f"Mover para a pasta: {folders[prop['folder']]}")
            c.setChecked(True)
            checks.append(("folder", c))
            v.addWidget(c)
        for task in prop["tasks"]:
            c = QCheckBox(f"Pendência: {task}")
            c.setChecked(True)
            checks.append(("task", c))
            v.addWidget(c)
        if not checks:
            v.addWidget(QLabel("Nada a propor para esta nota."))
            self._add(box)
            return
        apply = QPushButton("Aplicar")
        apply.setProperty("primary", True)
        v.addWidget(apply)

        def do_apply():
            ed = self.window.editor
            if ed.doc is None or ed.doc["id"] != doc_id:
                self.window.open_note(doc_id)
            tasks = []
            for kind, c in checks:
                if not c.isChecked():
                    continue
                if kind == "title":
                    ed.bar.title.setText(prop["title"])
                    ed._title_edited()
                elif kind == "folder":
                    self.window.store.move_note(doc_id, prop["folder"])
                else:
                    tasks.append(c.text().split(": ", 1)[1])
            if tasks:
                ed.insert_plain_text("\n".join("• " + t for t in tasks), title="Pendências")
            self.window.sidebar.refresh()
            apply.setEnabled(False)
            apply.setText("Aplicado")
        apply.clicked.connect(do_apply)
        self._add(box)


def open_panel(window, prefill: str = "") -> None:
    global _panel
    if _panel is None:
        _panel = AssistantPanel(window)
    _panel.refresh_state()
    if not _panel.isVisible():
        _panel.dock()
    else:
        _panel.place()
    _panel.show()
    _panel.raise_()
    if prefill:
        _panel.input.setText(f"Explique este trecho: {prefill[:400]}")
        _panel.input.setFocus()
