"""Citações e referências no padrão ABNT.

- Citações (NBR 10520:2023): chamada autor-data com o sobrenome em letras maiúsculas e minúsculas
  — (Silva, 2020, p. 12) —, "et al." a partir de quatro autores, siglas em maiúsculas; citação
  direta de até três linhas entre aspas duplas no próprio parágrafo; com mais de três linhas, em
  parágrafo próprio, sem aspas, com recuo de 4 cm (recomendado), letra menor (10 pt) e espaço
  simples.
- Referências (NBR 6023:2018): SOBRENOME, Prenome. **Título**: subtítulo. Edição. Local: Editora,
  ano. — com os modelos de capítulo (*In*:), artigo, página da internet (Disponível em: / Acesso
  em:), legislação e jurisprudência; lista no fim do texto, alinhada à esquerda, em espaço
  simples, separada por uma linha em branco e em ordem alfabética.

A formatação é feita por regras (não pelo modelo de IA). O assistente, quando instalado, só ajuda
a preencher os campos a partir de um texto colado.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date

MESES_ABREV = ("jan.", "fev.", "mar.", "abr.", "maio", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez.")
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")
SUFIXOS = {"filho", "filha", "júnior", "junior", "jr.", "neto", "neta", "sobrinho", "sobrinha", "segundo", "terceiro"}

TIPOS = [("livro", "Livro"), ("capitulo", "Capítulo de livro"), ("artigo", "Artigo de revista ou periódico"),
         ("site", "Página da internet"), ("lei", "Lei, decreto ou Constituição"), ("jurisprudencia", "Jurisprudência")]

# campos de cada tipo: (chave, rótulo, obrigatório)
CAMPOS = {
    "livro": [("autores", "Autor(es)", True), ("titulo", "Título", True), ("subtitulo", "Subtítulo", False),
              ("edicao", "Edição (nº)", False), ("local", "Cidade", True), ("editora", "Editora", True),
              ("ano", "Ano", True), ("volume", "Volume", False), ("url", "Endereço (se on-line)", False)],
    "capitulo": [("autores", "Autor(es) do capítulo", True), ("capitulo", "Título do capítulo", True),
                 ("organizadores", "Organizador(es) do livro", False), ("titulo", "Título do livro", True),
                 ("subtitulo", "Subtítulo do livro", False), ("edicao", "Edição (nº)", False), ("local", "Cidade", True),
                 ("editora", "Editora", True), ("ano", "Ano", True), ("paginas", "Páginas do capítulo (ex.: 91-95)", True)],
    "artigo": [("autores", "Autor(es)", True), ("titulo", "Título do artigo", True), ("subtitulo", "Subtítulo", False),
               ("periodico", "Nome da revista", True), ("local", "Cidade", False), ("volume", "Volume", False),
               ("numero", "Número", False), ("paginas", "Páginas (ex.: 71-81)", False), ("mes", "Mês", False),
               ("ano", "Ano", True), ("doi", "DOI", False), ("url", "Endereço (se on-line)", False)],
    "site": [("autores", "Autor(es) ou instituição", False), ("titulo", "Título da página", True),
             ("local", "Cidade", False), ("ano", "Ano", True), ("url", "Endereço", True)],
    "lei": [("jurisdicao", "Jurisdição (ex.: BRASIL, SÃO PAULO (Estado))", True),
            ("especie", "Tipo (Lei, Decreto, Lei Complementar…)", True), ("numero", "Número", True),
            ("data", "Data (ex.: 10 de janeiro de 2002)", True), ("ementa", "Ementa (ex.: Institui o Código Civil)", False),
            ("publicacao", "Publicado em", True), ("data_pub", "Data da publicação (ex.: 11 jan. 2002)", True),
            ("url", "Endereço (se on-line)", False)],
    "jurisprudencia": [("jurisdicao", "Jurisdição (ex.: BRASIL)", True), ("tribunal", "Tribunal", True),
                       ("turma", "Turma ou câmara (ex.: 3. Turma)", False),
                       ("processo", "Tipo e número (ex.: Recurso Especial 1.858.576/SP)", True),
                       ("relator", "Relator(a) (ex.: Min. Fulano de Tal)", True),
                       ("julgamento", "Data do julgamento (ex.: 9 de março de 2021)", True),
                       ("publicacao", "Publicado em (ex.: Diário da Justiça Eletrônico)", True),
                       ("data_pub", "Data da publicação (ex.: 12 mar. 2021)", True), ("ano", "Ano", True),
                       ("url", "Endereço (se on-line)", False)],
}


def hoje_abnt(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.day} {MESES_ABREV[d.month - 1]} {d.year}"


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


# ---------------------------------------------------------------- nomes
def split_authors(text: str) -> list[str]:
    parts = re.split(r"\s*;\s*|\s*\n\s*|\s+e\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def is_entity(name: str) -> bool:
    """Instituição (entra pelo nome inteiro): sigla em maiúsculas ou nome com palavras de órgão."""
    n = name.strip()
    if n.isupper() and len(n) <= 12:
        return True
    return bool(re.search(r"\b(Ministério|Secretaria|Universidade|Instituto|Associação|Organização|Conselho|"
                          r"Tribunal|Supremo|Superior|Fundação|Agência|Banco|Câmara|Senado|Prefeitura|Governo)\b", n))


def surname_parts(name: str) -> tuple[str, str]:
    """('Gonçalves Filho', 'Carlos') para 'Carlos Gonçalves Filho'; aceita 'Gonçalves, Carlos'."""
    name = re.sub(r"\s+", " ", name.strip())
    if "," in name:
        last, first = name.split(",", 1)
        return last.strip(), first.strip()
    tokens = name.split(" ")
    if len(tokens) == 1:
        return tokens[0], ""
    last = [tokens.pop()]
    if fold(last[0]) in SUFIXOS and tokens:
        last.insert(0, tokens.pop())
    return " ".join(last), " ".join(tokens)


def ref_name(name: str) -> str:
    if ". " in name.strip().rstrip("."):        # "Brasil. Ministério da Saúde": jurisdição e depois o órgão
        head, rest = name.split(". ", 1)
        return f"{head.upper()}. {rest.strip()}"
    if is_entity(name):
        return name.upper()
    last, first = surname_parts(name)
    return f"{last.upper()}, {first}" if first else last.upper()


def call_name(name: str) -> str:
    if ". " in name.strip().rstrip("."):
        head = name.split(". ", 1)[0].strip()
        return head.title() if head.isupper() else head
    if is_entity(name):
        return name if not name.isupper() or len(name) <= 12 else name.title()
    last, _ = surname_parts(name)
    return last if not last.isupper() else last.title()


# ---------------------------------------------------------------- referência (lista de trechos com estilo)
Run = tuple  # (texto, negrito, itálico)


def _end(text: str) -> str:
    """Termina com ponto, sem dobrar depois de ? ou !."""
    text = text.rstrip()
    return text if text.endswith((".", "?", "!")) else text + "."


def _authors_runs(names: list[str]) -> list[Run]:
    if not names:
        return []
    return [("; ".join(ref_name(n) for n in names) + ". ", False, False)]


def _edicao(ed: str) -> str:
    ed = (ed or "").strip().rstrip(".").replace("ª", "").replace("a ed", "").strip()
    if not ed or ed in ("1",):
        return ""
    return f"{ed}. ed. " if ed.isdigit() else f"{ed}. "


def _online(src: dict) -> str:
    url = (src.get("url") or "").strip()
    if not url:
        return ""
    return f" Disponível em: {url}. Acesso em: {src.get('acesso') or hoje_abnt()}."


def _title_runs(src: dict, key="titulo", sub="subtitulo") -> list[Run]:
    t = (src.get(key) or "").strip().rstrip(".")
    s = (src.get(sub) or "").strip().rstrip(".")
    if not s and ":" in t:
        t, s = (x.strip() for x in t.split(":", 1))
    runs = [(t, True, False)]
    if s:
        runs.append((": " + s[0].lower() + s[1:] if s[:1].isupper() and not s[:2].isupper() else ": " + s, False, False))
    last = s or t
    runs.append((" " if last.endswith(("?", "!")) else ". ", False, False))
    return runs


def reference_runs(src: dict) -> list[Run]:
    tipo = src.get("tipo") or "livro"
    names = src.get("autores") or []
    if isinstance(names, str):
        names = split_authors(names)
    g = lambda k: (src.get(k) or "").strip()
    runs: list[Run] = []
    if tipo == "livro":
        runs += _authors_runs(names) + _title_runs(src)
        tail = _edicao(g("edicao")) + f"{g('local') or '[s. l.]'}: {g('editora') or '[s. n.]'}, {g('ano') or '[s. d.]'}."
        if g("volume"):
            tail += f" v. {g('volume')}."
        runs.append((tail + _online(src), False, False))
    elif tipo == "capitulo":
        runs += _authors_runs(names)
        runs.append((_end(g("capitulo")) + " ", False, False))
        runs.append(("In", False, True))
        runs.append((": ", False, False))
        orgs = split_authors(g("organizadores"))
        if orgs:
            runs.append(("; ".join(ref_name(n) for n in orgs) + (" (org.). " if len(orgs) == 1 else " (org.). "), False, False))
        runs += _title_runs(src)
        tail = _edicao(g("edicao")) + f"{g('local') or '[s. l.]'}: {g('editora') or '[s. n.]'}, {g('ano') or '[s. d.]'}."
        if g("paginas"):
            tail += f" p. {g('paginas')}."
        runs.append((tail + _online(src), False, False))
    elif tipo == "artigo":
        runs += _authors_runs(names)
        t, s = g("titulo").rstrip("."), g("subtitulo").rstrip(".")
        runs.append((_end(t + (": " + s if s else "")) + " ", False, False))
        runs.append((g("periodico"), True, False))
        bits = [g("local")] if g("local") else []
        if g("volume"):
            bits.append(f"v. {g('volume')}")
        if g("numero"):
            bits.append(f"n. {g('numero')}")
        if g("paginas"):
            bits.append(f"p. {g('paginas')}")
        when = " ".join(x for x in (g("mes"), g("ano")) if x)
        if when:
            bits.append(when)
        tail = (", " + ", ".join(bits) if bits else "") + "."
        if g("doi"):
            doi = g("doi")
            tail += f" DOI: {doi if doi.startswith('http') else 'https://doi.org/' + doi}."
        runs.append((tail + _online(src), False, False))
    elif tipo == "site":
        if names:
            runs += _authors_runs(names) + _title_runs(src)
        else:      # sem autor: entra pelo título, com a primeira palavra em maiúsculas
            t = g("titulo")
            first, _, rest = t.partition(" ")
            runs.append((first.upper() + (" " + rest if rest else "") + ". ", False, False))
        tail = ", ".join(x for x in (g("local"), g("ano")) if x)
        runs.append(((tail + "." if tail else "") + _online(src), False, False))
    elif tipo == "lei":
        juris = g("jurisdicao").upper() or "BRASIL"
        especie = g("especie") or "Lei"
        head = f"{juris}. "
        if fold(especie).startswith("constitui"):
            head += f"[Constituição ({g('ano') or g('data')[-4:]})]. {especie}. "
        else:
            head += f"{especie} nº {g('numero')}, de {g('data')}. "
        if g("ementa"):
            head += _end(g("ementa")) + " "
        runs.append((head, False, False))
        runs.append((g("publicacao") or "Diário Oficial da União", True, False))
        runs.append((f": {('seção 1, Brasília, DF, ' if 'uniao' in fold(g('publicacao') or 'união') else '')}{g('data_pub')}."
                     + _online(src), False, False))
    elif tipo == "jurisprudencia":
        juris = g("jurisdicao").upper() or "BRASIL"
        head = f"{juris}. {g('tribunal')}"
        if g("turma"):
            head += f" ({g('turma')})"
        head += f". {_end(g('processo'))} Relator: {g('relator')}, {g('julgamento')}. "
        runs.append((head, False, False))
        runs.append((g("publicacao"), True, False))
        runs.append((f", {g('data_pub')}." + _online(src), False, False))
    return [(t, b, i) for t, b, i in runs if t]


def reference_text(src: dict) -> str:
    return "".join(t for t, _, _ in reference_runs(src)).strip()


# ---------------------------------------------------------------- chamada no texto
def call_authors(src: dict) -> str:
    tipo = src.get("tipo") or "livro"
    if tipo in ("lei", "jurisprudencia"):
        j = (src.get("jurisdicao") or "BRASIL").split("(")[0].strip()
        return j.title() if j.isupper() else j
    names = src.get("autores") or []
    if isinstance(names, str):
        names = split_authors(names)
    if not names:
        t = (src.get("titulo") or "").split(" ")[0]
        return t.upper() + " ..." if t else "[S. a.]"
    calls = [call_name(n) for n in names]
    if len(calls) >= 4:
        return calls[0] + " et al."
    return "; ".join(calls)


def call(src: dict, page: str = "") -> str:
    year = (src.get("ano") or "").strip() or re.sub(r".*(\d{4}).*", r"\1", src.get("data_pub") or src.get("data") or "") or "[s. d.]"
    out = f"({call_authors(src)}, {year}"
    page = (page or "").strip()
    if page:
        if re.match(r"^\d", page):
            page = ("p. " if "-" not in page and "," not in page else "p. ") + page
        out += f", {page}"
    return out + ")"


def missing(src: dict) -> list[str]:
    """Rótulos dos campos obrigatórios em branco (o que o app pergunta antes de citar)."""
    out = []
    for key, label, required in CAMPOS.get(src.get("tipo") or "livro", []):
        v = src.get(key)
        if required and not (v if isinstance(v, list) else (v or "").strip()):
            out.append(label.split(" (")[0])
    return out


def is_long(text: str, font_metrics, column_width: float) -> bool:
    """Mais de três linhas no texto (contando as aspas e a chamada)."""
    width = font_metrics.horizontalAdvance(text) + font_metrics.horizontalAdvance(" “” (Sobrenome, 2000, p. 00)")
    return width > 3 * max(50.0, column_width)


def ref_key(src: dict) -> str:
    return fold(reference_text(src))


# ---------------------------------------------------------------- preencher com o assistente
def extraction_prompt(text: str) -> str:
    return ("Extraia os dados da fonte abaixo para uma referência bibliográfica. Devolva um objeto JSON com as "
            "chaves: \"tipo\" (livro, capitulo, artigo, site, lei ou jurisprudencia), \"autores\" (lista de nomes "
            "completos, na ordem), \"titulo\", \"subtitulo\", \"capitulo\", \"organizadores\", \"edicao\" (só o número), "
            "\"local\", \"editora\", \"ano\", \"volume\", \"numero\", \"paginas\", \"periodico\", \"mes\", \"doi\", \"url\", "
            "\"jurisdicao\", \"especie\", \"data\", \"ementa\", \"publicacao\", \"data_pub\", \"tribunal\", \"turma\", "
            "\"processo\", \"relator\", \"julgamento\". Use \"\" para o que não estiver na fonte; não invente nada.\n\n"
            "Fonte:\n" + text.strip()[:2500])


def parse_extraction(answer: str) -> dict:
    m = re.search(r"\{.*\}", answer or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[k] = [str(x).strip() for x in v if str(x).strip()]
        elif v not in (None, ""):
            out[k] = str(v).strip()
    if out.get("tipo") not in dict(TIPOS):
        out.pop("tipo", None)
    return out


# ---------------------------------------------------------------- janela "Citação ABNT"
def _qt():
    from PySide6 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def make_dialog(parent, quote: str, known: list[dict], window=None):
    QtCore, QtGui, W = _qt()

    class CitationDialog(W.QDialog):
        """Pergunta o que falta para a citação e a referência, mostra como vão ficar e só então
        aplica. Com o assistente instalado, pode preencher os campos a partir de um texto colado."""

        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("Citação ABNT")
            self.setMinimumWidth(560)
            self.values: dict = {}
            lay = W.QVBoxLayout(self)
            shown = quote if len(quote) < 220 else quote[:200] + "…"
            q = W.QLabel(f"Trecho: “{shown}”")
            q.setWordWrap(True)
            q.setStyleSheet("color: #52606D;")
            lay.addWidget(q)
            top = W.QFormLayout()
            self.kind = W.QComboBox()
            self.kind.addItem("Direta — o trecho é cópia literal da fonte", "direta")
            self.kind.addItem("Indireta — o trecho é paráfrase (com minhas palavras)", "indireta")
            top.addRow("Citação", self.kind)
            self.known = W.QComboBox()
            self.known.addItem("Nova fonte", None)
            for src in known:
                self.known.addItem(reference_text(src)[:90], src)
            if known:
                top.addRow("Fonte", self.known)
            self.tipo = W.QComboBox()
            for key, title in TIPOS:
                self.tipo.addItem(title, key)
            top.addRow("Tipo de fonte", self.tipo)
            self.page = W.QLineEdit()
            self.page.setPlaceholderText("ex.: 12, 12-13 ou art. 186")
            top.addRow("Página do trecho", self.page)
            lay.addLayout(top)
            self.box = W.QWidget()
            self.form = W.QFormLayout(self.box)
            self.form.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.box)
            self.fields: dict[str, W.QLineEdit] = {}
            row = W.QHBoxLayout()
            self.fill = W.QPushButton("Preencher a partir de um texto…")
            self.fill.setToolTip("Cole os dados da fonte (como estiverem) e o assistente preenche os campos")
            self.fill.setVisible(bool(window is not None and window.assistant_available()))
            self.fill.clicked.connect(self.ask_assistant)
            self.status = W.QLabel("")
            self.status.setStyleSheet("color: #52606D;")
            row.addWidget(self.fill)
            row.addWidget(self.status, 1)
            lay.addLayout(row)
            self.preview = W.QLabel()
            self.preview.setWordWrap(True)
            self.preview.setTextFormat(QtCore.Qt.TextFormat.RichText)
            self.preview.setStyleSheet("background: #F5F7FA; border-radius: 6px; padding: 8px;")
            lay.addWidget(self.preview)
            note = W.QLabel("Formato: NBR 10520:2023 (citações) e NBR 6023:2018 (referências). "
                            "A referência entra em REFERÊNCIAS, no fim do texto, em ordem alfabética.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #7B8794; font-size: 11px;")
            lay.addWidget(note)
            bb = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
            bb.button(W.QDialogButtonBox.StandardButton.Ok).setText("Citar")
            bb.button(W.QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
            bb.accepted.connect(self.try_accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.tipo.currentIndexChanged.connect(self.build)
            self.known.currentIndexChanged.connect(self.use_known)
            self.kind.currentIndexChanged.connect(self.update_preview)
            self.page.textChanged.connect(self.update_preview)
            self.build()

        def collect(self) -> dict:
            for key, edit in self.fields.items():
                self.values[key] = edit.text().strip()
            src = {k: v for k, v in self.values.items() if v}
            src["tipo"] = self.tipo.currentData()
            if isinstance(src.get("autores"), str):
                src["autores"] = split_authors(src["autores"])
            return src

        def build(self) -> None:
            self.collect()
            while self.form.rowCount():
                self.form.removeRow(0)
            self.fields = {}
            for key, label, required in CAMPOS[self.tipo.currentData()]:
                e = W.QLineEdit(self.values.get(key, "") if not isinstance(self.values.get(key), list)
                                else "; ".join(self.values[key]))
                if key == "autores":
                    e.setPlaceholderText("Nome Sobrenome; Nome Sobrenome (ou a instituição)")
                e.textChanged.connect(self.update_preview)
                self.fields[key] = e
                self.form.addRow(label + (" *" if required else ""), e)
            self.update_preview()

        def use_known(self) -> None:
            src = self.known.currentData()
            if not src:
                return
            self.values = {k: ("; ".join(v) if isinstance(v, list) else v) for k, v in src.items()}
            i = self.tipo.findData(src.get("tipo") or "livro")
            self.tipo.blockSignals(True)
            self.tipo.setCurrentIndex(max(0, i))
            self.tipo.blockSignals(False)
            self.fields = {}
            while self.form.rowCount():
                self.form.removeRow(0)
            vals = dict(self.values)
            self.build()
            for k, e in self.fields.items():
                e.setText(vals.get(k, ""))

        def result_source(self) -> dict:
            src = self.collect()
            known = self.known.currentData()
            if known and known.get("acesso"):
                src["acesso"] = known["acesso"]
            elif src.get("url"):
                src["acesso"] = hoje_abnt()
            return src

        def update_preview(self) -> None:
            import html as h
            src = self.collect()
            ref = "".join(("<b>%s</b>" if b else "<i>%s</i>" if i else "%s") % h.escape(t) for t, b, i in reference_runs(src))
            page = self.page.text() if self.kind.currentData() == "direta" else ""
            if not any(v for k, v in src.items() if k != "tipo"):
                self.preview.setText("<span style='color:#7B8794'>Preencha os campos: aqui aparece como a citação "
                                     "e a referência vão ficar.</span>")
                return
            self.preview.setText(f"<b>No texto:</b> {h.escape(call(src, page))}<br><b>Referência:</b> {ref}")

        def try_accept(self) -> None:
            src = self.collect()
            lack = missing(src)
            if self.kind.currentData() == "direta" and not self.page.text().strip() and src["tipo"] in ("livro", "capitulo", "artigo"):
                lack.append("Página do trecho")
            if lack:
                W.QMessageBox.information(self, "Citação ABNT", "Para montar a citação e a referência, falta:\n\n• "
                                          + "\n• ".join(lack) + "\n\n(Se não existir — por exemplo, a obra não tem "
                                          "editora —, escreva “s. n.”; sem página, escreva “não paginado”.)")
                for key, label, _ in CAMPOS[src["tipo"]]:
                    if label.split(" (")[0] in lack:
                        self.fields[key].setFocus()
                        break
                else:
                    self.page.setFocus()
                return
            self.accept()

        def ask_assistant(self) -> None:
            text, ok = W.QInputDialog.getMultiLineText(self, "Preencher com o assistente",
                                                       "Cole os dados da fonte (do jeito que estiverem):")
            if not ok or not text.strip():
                return
            import models
            if not models.ensure(window, models.ASSISTANT.key, "O assistente roda no seu computador (nada sai dele)."):
                return
            import assistant
            self.fill.setEnabled(False)
            self.status.setText("O assistente está lendo a fonte…")
            self._runner = assistant.Runner(window, extraction_prompt(text), 500)
            self._runner.status.connect(self.status.setText)
            self._runner.failed.connect(lambda m: (self.status.setText(m), self.fill.setEnabled(True)))
            self._runner.done.connect(self._filled)
            self._runner.start()

        def _filled(self, answer: str) -> None:
            self.fill.setEnabled(True)
            data = parse_extraction(answer)
            if not data:
                self.status.setText("Não deu para ler os dados; preencha à mão.")
                return
            self.status.setText("Campos preenchidos — confira antes de citar.")
            if data.get("tipo"):
                self.tipo.setCurrentIndex(max(0, self.tipo.findData(data["tipo"])))
            for k, v in data.items():
                if k in self.fields:
                    self.fields[k].setText("; ".join(v) if isinstance(v, list) else v)
            self.update_preview()

    return CitationDialog()


# ---------------------------------------------------------------- aplicar no texto
LONG_INDENT = 4 / 2.54 * 72       # 4 cm em pontos
LONG_SIZE = 10.0


def apply_citation(item, src: dict, kind: str, page: str, column_width: float) -> None:
    """Troca o trecho selecionado pela citação: direta curta entre aspas com a chamada; direta
    longa em parágrafo próprio (recuo de 4 cm, 10 pt, espaço simples, sem aspas); indireta com a
    chamada logo depois (antes do ponto final). Um passo de desfazer."""
    QtCore, QtGui, _ = _qt()
    c = item.textCursor()
    if not c.hasSelection():
        return
    start, end = c.selectionStart(), c.selectionEnd()
    text = c.selectedText().replace(" ", " ").replace(" ", " ").strip()
    text = text.strip("\"“”«»'")
    fmt = QtGui.QTextCursor(item.document())
    fmt.setPosition(start + 1 if end > start else start)
    base = fmt.charFormat()
    tail_dot = ""
    if text.endswith((".", ";")) and kind != "indireta":
        tail_dot, text = text[-1], text[:-1].rstrip()
    chamada = call(src, page if kind == "direta" else "")
    c.beginEditBlock()
    if kind == "indireta":
        c.setPosition(end)
        doc_text = item.document().toPlainText()
        insert_at = end
        if end > 0 and doc_text[end - 1:end] in ".;":
            insert_at = end - 1
        c.setPosition(insert_at)
        c.insertText(" " + chamada, base)
    else:
        fm = QtGui.QFontMetricsF(base.font())
        if not is_long(text, fm, column_width):
            c.insertText(f"“{text}” {chamada}{tail_dot or ''}", base)
        else:
            c.removeSelectedText()
            if not c.atBlockStart():
                c.insertBlock()
            small = QtGui.QTextCharFormat(base)
            small.setFontPointSize(LONG_SIZE)
            c.insertText(f"{text} {chamada}.", small)
            bf = c.blockFormat()
            bf.setLeftMargin(LONG_INDENT)
            bf.setTextIndent(0)
            bf.setLineHeight(100, 1)
            bf.setAlignment(QtCore.Qt.AlignmentFlag.AlignJustify)
            c.setBlockFormat(bf)
            if not c.atBlockEnd():
                c.insertBlock()
                nf = c.blockFormat()
                nf.setLeftMargin(0)
                nf.setLineHeight(100, 0)
                c.setBlockFormat(nf)
                c.setCharFormat(base)
    c.endEditBlock()
    item.setTextCursor(c)


def present(src: dict, texts: list[str]) -> bool:
    """A fonte continua citada em algum lugar (senão sai da lista de referências)?"""
    who = call_authors(src).replace(" et al.", "")
    year = (src.get("ano") or "").strip() or re.sub(r".*(\d{4}).*", r"\1", src.get("data_pub") or "")
    pat = re.compile(re.escape(who.split(";")[0].strip()) + r"[^()]{0,80}?" + re.escape(year))
    return any(pat.search(t) for t in texts)


HEADING = "REFERÊNCIAS"


def _heading(doc):
    found = None
    b = doc.firstBlock()
    while b.isValid():
        if b.text().strip() == HEADING:
            found = b
        b = b.next()
    return found


def rebuild_references(doc, sources: list[dict], join: bool = True, known: list[dict] | None = None) -> None:
    """Refaz a seção REFERÊNCIAS no fim do texto da nota: título centralizado em negrito; cada
    referência alinhada à esquerda, em espaço simples, separada por uma linha em branco; ordem
    alfabética. Depois do título só tira linhas em branco e referências que o próprio app escreveu
    (reconhecidas pelo texto), então o que a pessoa escrever ali fica."""
    QtCore, QtGui, _ = _qt()
    seen, uniq = set(), []
    for s in sources:
        k = ref_key(s)
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    uniq.sort(key=ref_key)
    ours = {reference_text(s) for s in (known or []) + sources}
    c = QtGui.QTextCursor(doc)
    if join:
        c.joinPreviousEditBlock()
    else:
        c.beginEditBlock()
    head = _heading(doc)
    if head is not None:
        numbers = []
        b = head.next()
        while b.isValid():
            if not b.text().strip() or b.text().strip() in ours:
                numbers.append(b.blockNumber())
            b = b.next()
        if not uniq:
            numbers.append(head.blockNumber())
            prev = head.previous()
            if prev.isValid() and not prev.text().strip():
                numbers.append(prev.blockNumber())
        for n in sorted(set(numbers), reverse=True):     # de baixo para cima
            blk = doc.findBlockByNumber(n)
            cur = QtGui.QTextCursor(doc)
            nxt, prev = blk.next(), blk.previous()
            if nxt.isValid():
                cur.setPosition(blk.position())
                cur.setPosition(nxt.position(), QtGui.QTextCursor.MoveMode.KeepAnchor)
            elif prev.isValid():
                cur.setPosition(prev.position() + prev.length() - 1)
                cur.setPosition(blk.position() + blk.length() - 1, QtGui.QTextCursor.MoveMode.KeepAnchor)
            else:
                cur.setPosition(blk.position())
                cur.setPosition(blk.position() + blk.length() - 1, QtGui.QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
    if uniq:
        plain = QtGui.QTextCharFormat()
        plain.setFontWeight(QtGui.QFont.Weight.Normal)
        plain.setFontItalic(False)
        left = QtGui.QTextBlockFormat()
        left.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        left.setLineHeight(100, 1)
        head = _heading(doc)
        if head is None:
            c.movePosition(QtGui.QTextCursor.MoveOperation.End)
            if c.block().text().strip():
                c.insertBlock(left, plain)
            centered = QtGui.QTextBlockFormat(left)
            centered.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            centered.setHeadingLevel(1)
            bold = QtGui.QTextCharFormat(plain)
            bold.setFontWeight(QtGui.QFont.Weight.Bold)
            c.insertBlock(centered, bold)
            c.insertText(HEADING, bold)
            head = c.block()
        c.setPosition(head.position() + head.length() - 1)
        for src in uniq:
            for runs in ([], reference_runs(src)):      # linha em branco e a referência
                c.insertBlock(left, plain)
                for text, bold_on, italic_on in runs:
                    f = QtGui.QTextCharFormat(plain)
                    if bold_on:
                        f.setFontWeight(QtGui.QFont.Weight.Bold)
                    if italic_on:
                        f.setFontItalic(True)
                    c.insertText(text, f)
    c.endEditBlock()


def body_text(doc) -> str:
    """Texto da nota antes da seção de referências."""
    out = []
    head = _heading(doc)
    b = doc.firstBlock()
    while b.isValid() and (head is None or b.blockNumber() < head.blockNumber()):
        out.append(b.text())
        b = b.next()
    return "\n".join(out)
