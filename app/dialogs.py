"""Janelas auxiliares: página, cabeçalho e rodapé, numeração, papel, localizar e substituir,
links, escolher notas, data do calendário, tabela, stickers, Lixeira, leitor de PDF."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget)

import icons
import model
import theme

CM = model.CM

PAGE_SIZES = [("A4", 210, 297), ("A5", 148, 210), ("A3", 297, 420), ("Carta", 215.9, 279.4),
              ("Ofício", 215.9, 355.6), ("Personalizado", 0, 0)]
ALIGNS = [("leading", "Esquerda"), ("center", "Centro"), ("trailing", "Direita")]
NUMBER_FORMATS = [("n", "1"), ("page", "Página 1"), ("page_of", "Página 1 de N"), ("slash", "1/N"), ("dash", "– 1 –")]


def buttons(dialog: QDialog, ok_text: str = "OK") -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    box.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
    box.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def cm_spin(value_pt: float, lo: float = 0.0, hi: float = 100.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(2)
    s.setSingleStep(0.1)
    s.setSuffix(" cm")
    s.setValue(round(value_pt / CM, 2))
    return s


# ---------------------------------------------------------------------- página
class PageSetupDialog(QDialog):
    def __init__(self, canvas: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tamanho da página e margens")
        size = canvas["size"]
        m = canvas.get("margins") or model.WORD_MARGINS
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.preset = QComboBox()
        for name, w, h in PAGE_SIZES:
            self.preset.addItem(name if not w else f"{name} ({w:g} × {h:g} mm)", (w, h))
        self.landscape = QCheckBox("Paisagem")
        w_mm, h_mm = size["width"] / model.MM, size["height"] / model.MM
        self.landscape.setChecked(w_mm > h_mm)
        self.width = QDoubleSpinBox()
        self.height = QDoubleSpinBox()
        for spin in (self.width, self.height):
            spin.setRange(5, 300)
            spin.setDecimals(2)
            spin.setSuffix(" cm")
        self.width.setValue(round(w_mm / 10, 2))
        self.height.setValue(round(h_mm / 10, 2))
        match = len(PAGE_SIZES) - 1
        for i, (_, pw, ph) in enumerate(PAGE_SIZES[:-1]):
            if {round(pw), round(ph)} == {round(w_mm), round(h_mm)}:
                match = i
        self.preset.setCurrentIndex(match)
        form.addRow("Tamanho", self.preset)
        form.addRow("", self.landscape)
        form.addRow("Largura", self.width)
        form.addRow("Altura", self.height)
        lay.addLayout(form)
        group = QGroupBox("Margens do texto")
        g = QFormLayout(group)
        self.top, self.bottom = cm_spin(m["top"], 0, 10), cm_spin(m["bottom"], 0, 10)
        self.left, self.right = cm_spin(m["left"], 0, 10), cm_spin(m["right"], 0, 10)
        g.addRow("Superior", self.top)
        g.addRow("Inferior", self.bottom)
        g.addRow("Esquerda", self.left)
        g.addRow("Direita", self.right)
        word = QPushButton("Margens do Word (Normal)")
        word.clicked.connect(self._word)
        g.addRow("", word)
        lay.addWidget(group)
        note = QLabel("Mudar o tamanho não muda nem apaga objetos: os que ficarem fora da página continuam onde estão.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(note)
        lay.addWidget(buttons(self, "Aplicar"))
        self.preset.currentIndexChanged.connect(self._preset)
        self.landscape.toggled.connect(self._preset)

    def _word(self):
        self.top.setValue(2.5)
        self.bottom.setValue(2.5)
        self.left.setValue(3.0)
        self.right.setValue(3.0)

    def _preset(self):
        w, h = self.preset.currentData()
        if not w:
            return
        if self.landscape.isChecked():
            w, h = max(w, h), min(w, h)
        else:
            w, h = min(w, h), max(w, h)
        self.width.setValue(w / 10)
        self.height.setValue(h / 10)

    def result_canvas(self, canvas: dict) -> dict:
        out = dict(canvas)
        out["size"] = {"width": self.width.value() * CM, "height": self.height.value() * CM}
        out["margins"] = {"top": self.top.value() * CM, "bottom": self.bottom.value() * CM,
                          "left": self.left.value() * CM, "right": self.right.value() * CM}
        return out


class BandEditor(QWidget):
    def __init__(self, band: dict | None, pick_image, parent=None):
        super().__init__(parent)
        band = band or {}
        self.pick_image = pick_image
        self.image = band.get("image")
        self.pdf = band.get("pdf")
        form = QFormLayout(self)
        self.text = QLineEdit(band.get("text") or "")
        self.text.setPlaceholderText("Texto (por exemplo, nome do escritório ou do processo)")
        self.align = QComboBox()
        for key, title in ALIGNS:
            self.align.addItem(title, key)
        self.align.setCurrentIndex(max(0, [a for a, _ in ALIGNS].index(band.get("alignment") or "center")))
        self.height = QDoubleSpinBox()
        self.height.setRange(0.4, 6)
        self.height.setSuffix(" cm")
        self.height.setValue(round(float(band.get("height") or 36) / CM, 2))
        self.size = QSpinBox()
        self.size.setRange(6, 36)
        self.size.setSuffix(" pt")
        self.size.setValue(int(band.get("fontSize") or 10))
        row = QHBoxLayout()
        self.image_label = QLabel(self._image_text())
        choose = QPushButton("Escolher imagem ou PDF…")
        clear = QPushButton("Tirar")
        choose.clicked.connect(self._choose)
        clear.clicked.connect(self._clear)
        row.addWidget(self.image_label, 1)
        row.addWidget(choose)
        row.addWidget(clear)
        form.addRow("Texto", self.text)
        form.addRow("Alinhamento", self.align)
        form.addRow("Tamanho da letra", self.size)
        form.addRow("Altura", self.height)
        form.addRow("Imagem", row)

    def _image_text(self):
        return "Imagem escolhida" if self.image else "Primeira página do PDF" if self.pdf else "Nenhuma"

    def _choose(self):
        got = self.pick_image()
        if got:
            kind, digest = got
            self.image, self.pdf = (digest, None) if kind == "image" else (None, digest)
            self.image_label.setText(self._image_text())

    def _clear(self):
        self.image = self.pdf = None
        self.image_label.setText(self._image_text())

    def value(self) -> dict | None:
        band = {"text": self.text.text().strip(), "alignment": self.align.currentData(), "height": self.height.value() * CM,
                "fontSize": self.size.value(), "image": self.image, "pdf": self.pdf}
        if not band["text"] and not band["image"] and not band["pdf"]:
            return None
        if band["pdf"] and not band["image"]:
            band["image"] = None
        return band


class HeaderFooterDialog(QDialog):
    def __init__(self, canvas: dict, pick_image, tab: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cabeçalho, rodapé e números de página")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        self.header = BandEditor(canvas.get("header"), pick_image)
        self.footer = BandEditor(canvas.get("footer"), pick_image)
        tabs.addTab(self.header, "Cabeçalho")
        tabs.addTab(self.footer, "Rodapé")
        nums = QWidget()
        form = QFormLayout(nums)
        n = canvas.get("pageNumbers") or {}
        self.numbered = QCheckBox("Numerar as páginas")
        self.numbered.setChecked(bool(canvas.get("pageNumbers")))
        self.position = QComboBox()
        self.position.addItem("No rodapé", "footer")
        self.position.addItem("No cabeçalho", "header")
        self.position.setCurrentIndex(1 if n.get("position") == "header" else 0)
        self.num_align = QComboBox()
        for key, title in ALIGNS:
            self.num_align.addItem(title, key)
        self.num_align.setCurrentIndex([a for a, _ in ALIGNS].index(n.get("alignment") or "center"))
        self.fmt = QComboBox()
        for key, title in NUMBER_FORMATS:
            self.fmt.addItem(title, key)
        keys = [k for k, _ in NUMBER_FORMATS]
        self.fmt.setCurrentIndex(keys.index(n.get("format")) if n.get("format") in keys else 0)
        self.start = QSpinBox()
        self.start.setRange(0, 9999)
        self.start.setValue(int(n.get("start") or 1))
        self.skip = QCheckBox("Sem número na primeira página")
        self.skip.setChecked(bool(n.get("skipFirst")))
        self.num_size = QSpinBox()
        self.num_size.setRange(8, 48)
        self.num_size.setSuffix(" pt")
        self.num_size.setValue(int(n.get("size") or 11))
        # aberto por "Numerar páginas": já vem marcado; mexer em qualquer opção também marca
        if tab == 2 and not canvas.get("pageNumbers"):
            self.numbered.setChecked(True)
        for combo in (self.position, self.num_align, self.fmt):
            combo.currentIndexChanged.connect(lambda _=0: self.numbered.setChecked(True))
        for spin in (self.start, self.num_size):
            spin.valueChanged.connect(lambda _=0: self.numbered.setChecked(True))
        self.skip.toggled.connect(lambda on: on and self.numbered.setChecked(True))
        form.addRow(self.numbered)
        form.addRow("Posição", self.position)
        form.addRow("Alinhamento", self.num_align)
        form.addRow("Formato", self.fmt)
        form.addRow("Número inicial", self.start)
        form.addRow("Tamanho do número", self.num_size)
        form.addRow(self.skip)
        tabs.addTab(nums, "Números de página")
        tabs.setCurrentIndex(tab)
        lay.addWidget(tabs)
        note = QLabel("O texto da nota passa a começar abaixo do cabeçalho e a terminar acima do rodapé.")
        note.setStyleSheet(f"color: {theme.MUTED};")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addWidget(buttons(self, "Aplicar"))

    def result_canvas(self, canvas: dict) -> dict:
        out = dict(canvas)
        out["header"] = self.header.value()
        out["footer"] = self.footer.value()
        out["pageNumbers"] = {"position": self.position.currentData(), "alignment": self.num_align.currentData(),
                              "format": self.fmt.currentData(), "start": self.start.value(),
                              "skipFirst": self.skip.isChecked(), "size": self.num_size.value()} if self.numbered.isChecked() else None
        return out


class PaperDialog(QDialog):
    def __init__(self, paper: dict | None, parent=None, grid_typing: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Papel")
        paper = paper or {}
        lay = QVBoxLayout(self)
        self.kind = QButtonGroup(self)
        row = QHBoxLayout()
        for i, (key, title) in enumerate(model.PAPER_KINDS):
            b = QRadioButton(title)
            b.setProperty("key", key)
            self.kind.addButton(b, i)
            row.addWidget(b)
            if key == (paper.get("kind") or "plain"):
                b.setChecked(True)
        lay.addLayout(row)
        form = QFormLayout()
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.3, 2.0)
        self.spacing.setSingleStep(0.1)
        self.spacing.setSuffix(" cm")
        self.spacing.setValue(round(float(paper.get("spacing") or model.RULED_LINE) / CM, 2))
        form.addRow("Tamanho da linha ou do quadrado", self.spacing)
        self.scope = QComboBox()
        self.scope.addItem("Na nota toda", "note")
        self.scope.addItem("Só nesta página", "page")
        self.scope.addItem("Na metade de cima desta página", "top")
        self.scope.addItem("Na metade de baixo desta página", "bottom")
        form.addRow("Onde", self.scope)
        lay.addLayout(form)
        self.grid_typing = QCheckBox("No quadriculado, clicar num quadrado digita uma conta (um caractere por quadrado)")
        self.grid_typing.setChecked(grid_typing)
        lay.addWidget(self.grid_typing)
        note = QLabel("No papel caderno na nota toda, cada linha do texto ocupa uma faixa da pauta.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(note)
        lay.addWidget(buttons(self, "Aplicar"))

    def value(self) -> tuple[dict | None, str]:
        key = self.kind.checkedButton().property("key") if self.kind.checkedButton() else "plain"
        scope = self.scope.currentData()
        if key == "plain":
            return None, scope
        paper = {"kind": key, "spacing": self.spacing.value() * CM}
        if scope in ("top", "bottom"):
            paper["half"] = scope
        return paper, scope


# ---------------------------------------------------------------------- texto
class FindReplaceDialog(QDialog):
    find_next = Signal(str, bool, bool, bool)        # texto, maiúsculas, palavra inteira, para trás
    replace_one = Signal(str, str, bool, bool)
    replace_all = Signal(str, str, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Localizar e substituir")
        self.setModal(False)
        lay = QFormLayout(self)
        self.needle = QLineEdit()
        self.repl = QLineEdit()
        self.case = QCheckBox("Diferenciar maiúsculas")
        self.whole = QCheckBox("Palavra inteira")
        self.info = QLabel("")
        self.info.setStyleSheet(f"color: {theme.MUTED};")
        lay.addRow("Localizar", self.needle)
        lay.addRow("Substituir por", self.repl)
        opts = QHBoxLayout()
        opts.addWidget(self.case)
        opts.addWidget(self.whole)
        lay.addRow(opts)
        row = QHBoxLayout()
        prev = QPushButton("Anterior")
        nxt = QPushButton("Próximo")
        nxt.setProperty("primary", True)
        one = QPushButton("Substituir")
        every = QPushButton("Substituir tudo")
        for b in (prev, nxt, one, every):
            row.addWidget(b)
        lay.addRow(row)
        lay.addRow(self.info)
        nxt.clicked.connect(lambda: self.find_next.emit(self.needle.text(), self.case.isChecked(), self.whole.isChecked(), False))
        prev.clicked.connect(lambda: self.find_next.emit(self.needle.text(), self.case.isChecked(), self.whole.isChecked(), True))
        one.clicked.connect(lambda: self.replace_one.emit(self.needle.text(), self.repl.text(), self.case.isChecked(), self.whole.isChecked()))
        every.clicked.connect(lambda: self.replace_all.emit(self.needle.text(), self.repl.text(), self.case.isChecked(), self.whole.isChecked()))
        self.needle.returnPressed.connect(nxt.click)


class NotePicker(QDialog):
    """Escolher notas (para link ou para a Teia), com busca pelo título."""

    def __init__(self, notes, title: str, multi: bool = False, previews=None, parent=None, ok_text="Escolher"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 520)
        self.notes = notes
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar pelo título")
        self.list = QListWidget()
        self.list.setIconSize(QSize(44, 58))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection if multi else QAbstractItemView.SelectionMode.SingleSelection)
        for n in notes:
            it = QListWidgetItem(f"{n.title}\n{('Teia · ' if n.kind == 'web' else '')}{model.parse_iso(n.created).astimezone().strftime('%d/%m/%Y')}")
            it.setData(Qt.ItemDataRole.UserRole, n.id)
            if previews:
                img = previews(n)
                if img is not None:
                    it.setIcon(QIcon(QPixmap.fromImage(img)))
            self.list.addItem(it)
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(buttons(self, ok_text))
        self.search.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())

    def _filter(self, text: str):
        from store import Store
        import unicodedata

        def fold(s):
            return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
        t = fold(text)
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in fold(it.text()))

    def chosen(self) -> list[str]:
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()]


class LinkDialog(QDialog):
    def __init__(self, parent=None, url: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Inserir link")
        self.setMinimumWidth(420)
        lay = QFormLayout(self)
        self.url = QLineEdit(url)
        self.url.setPlaceholderText("https://… ou mailto:…")
        self.text = QLineEdit()
        self.text.setPlaceholderText("(opcional) texto do link")
        lay.addRow("Endereço", self.url)
        lay.addRow("Texto", self.text)
        hint = QLabel("Só endereços da web (http, https) e de e-mail (mailto) viram link.")
        hint.setStyleSheet(f"color: {theme.MUTED};")
        lay.addRow(hint)
        lay.addRow(buttons(self, "Inserir"))

    def value(self) -> tuple[str, str]:
        url = self.url.text().strip()
        if url and "://" not in url and not url.lower().startswith("mailto:"):
            url = ("mailto:" + url) if "@" in url and " " not in url else "https://" + url
        return url, self.text.text().strip()


MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro")


def data_por_extenso(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


class SignatureDialog(QDialog):
    """Linha de assinatura: nome, segunda linha (cargo, OAB, CPF) e local e data (opcionais)."""

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Linha de assinatura")
        self.setMinimumWidth(440)
        lay = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nome de quem assina")
        self.second = QLineEdit()
        self.second.setPlaceholderText("(opcional) cargo, OAB, CPF…")
        self.place = QLineEdit()
        self.place.setPlaceholderText("(opcional) cidade")
        self.with_date = QCheckBox(f"Pôr local e data ({data_por_extenso()})")
        self.with_date.toggled.connect(self.place.setEnabled)
        self.place.setEnabled(False)
        lay.addRow("Nome", self.name)
        lay.addRow("Segunda linha", self.second)
        lay.addRow(self.with_date)
        lay.addRow("Local", self.place)
        lay.addRow(buttons(self, "Inserir"))

    def values(self) -> tuple[str, str, str]:
        place = ""
        if self.with_date.isChecked():
            city = self.place.text().strip()
            place = (city + ", " if city else "") + data_por_extenso() + "."
        return self.name.text().strip(), self.second.text().strip(), place


class LineSpacingDialog(QDialog):
    def __init__(self, parent=None, factor: float = 1.0, before: float = 0.0, after: float = 0.0):
        super().__init__(parent)
        self.setWindowTitle("Espaçamento")
        lay = QFormLayout(self)
        self.factor = QDoubleSpinBox()
        self.factor.setRange(0.8, 5.0)
        self.factor.setSingleStep(0.05)
        self.factor.setDecimals(2)
        self.factor.setValue(factor)
        self.factor.setSuffix(" linha(s)")
        self.before = QDoubleSpinBox()
        self.before.setRange(0, 96)
        self.before.setSuffix(" pt")
        self.before.setValue(before)
        self.after = QDoubleSpinBox()
        self.after.setRange(0, 96)
        self.after.setSuffix(" pt")
        self.after.setValue(after)
        lay.addRow("Entre linhas", self.factor)
        lay.addRow("Antes do parágrafo", self.before)
        lay.addRow("Depois do parágrafo", self.after)
        lay.addRow(buttons(self, "Aplicar"))

    def values(self) -> tuple[float, float, float]:
        return self.factor.value(), self.before.value(), self.after.value()


class CalendarDialog(QDialog):
    def __init__(self, day: date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data do calendário")
        lay = QVBoxLayout(self)
        self.cal = QCalendarWidget()
        self.cal.setSelectedDate(QDate(day.year, day.month, day.day))
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        lay.addWidget(self.cal)
        row = QHBoxLayout()
        today = QPushButton("Hoje")
        today.clicked.connect(lambda: self.cal.setSelectedDate(QDate.currentDate()))
        row.addWidget(today)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(buttons(self))
        self.cal.activated.connect(lambda *_: self.accept())

    def value(self) -> str:
        d = self.cal.selectedDate()
        return f"{d.year():04d}-{d.month():02d}-{d.day():02d}"


class TableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inserir tabela")
        lay = QFormLayout(self)
        self.rows = QSpinBox()
        self.rows.setRange(1, 60)
        self.rows.setValue(3)
        self.cols = QSpinBox()
        self.cols.setRange(1, 12)
        self.cols.setValue(3)
        self.where = QComboBox()
        self.where.addItem("No texto, onde está o cursor", "story")
        self.where.addItem("Solta na página (pode ser arrastada)", "free")
        lay.addRow("Linhas", self.rows)
        lay.addRow("Colunas", self.cols)
        lay.addRow("Onde", self.where)
        lay.addRow(buttons(self, "Inserir"))


class StickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stickers")
        self.choice = None
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        cols = 8
        for i, emoji in enumerate(model.STICKER_EMOJI):
            b = QToolButton()
            b.setText(emoji)
            f = QFont("Segoe UI Emoji")
            f.setPointSize(22)
            b.setFont(f)
            b.setFixedSize(52, 52)
            b.setToolTip(f"Sticker {emoji}")
            b.clicked.connect(lambda _=False, e=emoji: self._pick(("emoji", e)))
            grid.addWidget(b, i // cols, i % cols)
        lay.addLayout(grid)
        extra = QHBoxLayout()
        sticky = QPushButton("Post-it")
        sticky.setIcon(icons.icon("sticky"))
        cal = QPushButton("Calendário")
        cal.setIcon(icons.icon("calendar"))
        img = QPushButton("Usar uma imagem do computador…")
        img.setIcon(icons.icon("image"))
        sticky.clicked.connect(lambda: self._pick(("sticky", None)))
        cal.clicked.connect(lambda: self._pick(("calendar", None)))
        img.clicked.connect(lambda: self._pick(("image", None)))
        extra.addWidget(sticky)
        extra.addWidget(cal)
        extra.addWidget(img)
        lay.addLayout(extra)

    def _pick(self, choice):
        self.choice = choice
        self.accept()


class TrashDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Lixeira")
        self.resize(480, 520)
        self.changed = False
        lay = QVBoxLayout(self)
        info = QLabel("Notas e Teias apagadas ficam aqui inteiras até serem restauradas ou apagadas para sempre. "
                      "Nada é apagado sozinho.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(info)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        restore = QPushButton("Restaurar")
        restore.setIcon(icons.icon("restore"))
        forever = QPushButton("Apagar para sempre")
        forever.setProperty("danger", True)
        empty = QPushButton("Esvaziar a Lixeira")
        empty.setProperty("danger", True)
        close = QPushButton("Fechar")
        row.addWidget(restore)
        row.addWidget(forever)
        row.addStretch()
        row.addWidget(empty)
        row.addWidget(close)
        lay.addLayout(row)
        restore.clicked.connect(self._restore)
        forever.clicked.connect(self._forever)
        empty.clicked.connect(self._empty)
        close.clicked.connect(self.accept)
        self.reload()

    def reload(self):
        self.list.clear()
        for n in self.store.notes(trashed=True):
            when = model.parse_iso(n.trashed_at).astimezone().strftime("%d/%m/%Y %H:%M")
            it = QListWidgetItem(icons.icon("teia" if n.kind == "web" else "note"), f"{n.title}   ·   apagada em {when}")
            it.setData(Qt.ItemDataRole.UserRole, n.id)
            self.list.addItem(it)
        if self.list.count() == 0:
            it = QListWidgetItem("A Lixeira está vazia.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)

    def _ids(self):
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems() if it.data(Qt.ItemDataRole.UserRole)]

    def _restore(self):
        for i in self._ids():
            self.store.restore(i)
        self.changed = True
        self.reload()

    def _forever(self):
        ids = self._ids()
        if not ids:
            return
        if QMessageBox.question(self, "Apagar para sempre",
                                f"Apagar {len(ids)} item(ns) para sempre? Isso não pode ser desfeito.") != QMessageBox.StandardButton.Yes:
            return
        for i in ids:
            self.store.delete_forever(i)
        self.changed = True
        self.reload()

    def _empty(self):
        if not self.store.notes(trashed=True):
            return
        if QMessageBox.question(self, "Esvaziar a Lixeira",
                                "Apagar para sempre tudo o que está na Lixeira? Isso não pode ser desfeito.") != QMessageBox.StandardButton.Yes:
            return
        self.store.empty_trash()
        self.changed = True
        self.reload()


class PdfViewer(QDialog):
    """Leitor simples: todas as páginas, com zoom; dá para anotar o PDF na nota."""
    annotate = Signal()

    def __init__(self, assets, digest: str, title: str, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title or "PDF")
        self.resize(900, 820)
        self.assets, self.digest = assets, digest
        self.zoom = 1.0
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        out = QToolButton()
        out.setIcon(icons.icon("zoom-out"))
        inn = QToolButton()
        inn.setIcon(icons.icon("zoom-in"))
        ann = QPushButton("Anotar este PDF na nota")
        ann.setIcon(icons.icon("pdf-annotate"))
        ext = QPushButton("Abrir no leitor do Windows")
        bar.addWidget(out)
        bar.addWidget(inn)
        bar.addStretch()
        bar.addWidget(ann)
        bar.addWidget(ext)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"background: {theme.DESK};")
        lay.addWidget(self.scroll, 1)
        out.clicked.connect(lambda: self._zoom(0.8))
        inn.clicked.connect(lambda: self._zoom(1.25))
        ann.clicked.connect(lambda: (self.annotate.emit(), self.accept()))
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        ext.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        self._render()

    def _zoom(self, f):
        self.zoom = max(0.4, min(3.0, self.zoom * f))
        self._render()

    def _render(self):
        host = QWidget()
        v = QVBoxLayout(host)
        v.setSpacing(14)
        n = self.assets.pdf_page_count(self.digest)
        width = int(760 * self.zoom)
        for i in range(min(n, 300)):
            img = self.assets.pdf_page(self.digest, i, int(width * 1.5))
            lab = QLabel()
            if img is not None:
                pm = QPixmap.fromImage(img).scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
                lab.setPixmap(pm)
            lab.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            v.addWidget(lab)
        v.addStretch()
        self.scroll.setWidget(host)
