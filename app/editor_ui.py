"""Barra de formatação (em cima), painel de ferramentas em grade (à direita, como no iPad),
painel de páginas (à esquerda) e os botões redondos da caneta e do assistente."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy, QSlider, QToolButton,
                               QVBoxLayout, QWidget, QWidgetAction)

import icons
import model
import theme
import textfmt

FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 48, 60, 72]


def tool_button(name: str, tip: str, checkable: bool = False, size: int = 20) -> QToolButton:
    b = QToolButton()
    b.setIcon(icons.icon(name, theme.INK, theme.ACCENT))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    return b


def swatch_icon(color: str | None, size: int = 18, ring: bool = False) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if color is None:
        p.setPen(QColor("#9AA5B1"))
        p.setBrush(QColor("white"))
        p.drawEllipse(3, 3, size * 2 - 6, size * 2 - 6)
        p.setPen(QColor("#DC2626"))
        p.drawLine(8, size * 2 - 8, size * 2 - 8, 8)
    else:
        p.setPen(QColor(0, 0, 0, 60))
        p.setBrush(QColor(color))
        p.drawEllipse(3, 3, size * 2 - 6, size * 2 - 6)
    if ring:
        p.setPen(QColor(theme.ACCENT))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(1, 1, size * 2 - 2, size * 2 - 2)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def color_icon_bar(name: str, color: str) -> QIcon:
    base = icons.pixmap(name, theme.INK, 20)
    pm = QPixmap(base.size())
    pm.setDevicePixelRatio(base.devicePixelRatio())
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.drawPixmap(0, 0, base)
    p.fillRect(2, 17, 16, 3, QColor(color))
    p.end()
    return QIcon(pm)


class FormatBar(QFrame):
    """Barra de cima: título, desfazer, estilos, fonte, tamanho, B I U S, cores, alinhamento,
    listas e mais opções; zoom, páginas, ferramentas e o menu da nota."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setObjectName("formatbar")
        self.setStyleSheet(f"#formatbar {{ background: {theme.CARD}; border-bottom: 1px solid {theme.LINE}; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(2)
        self.sidebar = tool_button("sidebar", "Mostrar ou esconder o menu (Ctrl+\\)")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Título")
        self.title.setFont(theme.ui_font(11, True))
        self.title.setMinimumWidth(170)
        self.title.setMaximumWidth(260)
        self.title.setStyleSheet("QLineEdit { border: 1px solid transparent; background: transparent; padding: 3px 6px; }"
                                 "QLineEdit:hover { border: 1px solid #DDE2E7; } QLineEdit:focus { border: 1px solid %s; background: white; }" % theme.ACCENT)
        self.undo = tool_button("undo", "Desfazer (Ctrl+Z)")
        self.redo = tool_button("redo", "Refazer (Ctrl+Y)")
        self.style_combo = QComboBox()
        self.style_combo.setToolTip("Estilo do parágrafo")
        for sid, title, *_ in textfmt.NAMED_STYLES:
            self.style_combo.addItem(title, sid)
        self.style_combo.setFixedWidth(104)
        self.font_combo = QComboBox()
        self.font_combo.setToolTip("Fonte")
        self.font_combo.setFixedWidth(150)
        self.font_combo.setMaxVisibleItems(18)
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        self.size_combo.setToolTip("Tamanho da fonte")
        self.size_combo.setFixedWidth(62)
        for s in FONT_SIZES:
            self.size_combo.addItem(str(s))
        self.bold = tool_button("bold", "Negrito (Ctrl+B)", True)
        self.italic = tool_button("italic", "Itálico (Ctrl+I)", True)
        self.underline = tool_button("underline", "Sublinhado (Ctrl+U)", True)
        self.strike = tool_button("strike", "Tachado", True)
        self.color = tool_button("text-color", "Cor do texto")
        self.color.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.highlight = tool_button("highlight", "Destacar (marca-texto)")
        self.highlight.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.align = tool_button("align-left", "Alinhamento")
        self.align.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.lists = tool_button("list", "Listas (ou escreva \"- \" ou \"1. \" no começo da linha)")
        self.lists.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.spacing = tool_button("line-spacing", "Espaçamento entre linhas e parágrafos")
        self.spacing.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.proof = tool_button("spellcheck", "Revisar o texto (ortografia e gramática, pelo assistente)")
        self.proof.clicked.connect(editor.proofread)
        self.more_text = tool_button("more", "Mais opções de texto")
        self.more_text.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.zoom = QToolButton()
        self.zoom.setText("100%")
        self.zoom.setToolTip("Zoom (Ctrl + roda do mouse)")
        self.zoom.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.zoom.setMinimumWidth(56)
        self.add_cards = QToolButton()
        self.add_cards.setIcon(icons.icon("plus", theme.INK))
        self.add_cards.setText("Adicionar notas")
        self.add_cards.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_cards.setToolTip("Adicionar notas a esta Teia")
        self.add_cards.clicked.connect(editor.add_notes_to_teia)
        self.add_cards.hide()
        self.pages = tool_button("pages", "Páginas", True)
        self.tools = tool_button("shapes", "Ferramentas", True)
        self.note_menu = tool_button("more", "Mais (exportar, imprimir, citada em…)")
        self.note_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        def sep():
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setStyleSheet(f"color: {theme.LINE};")
            line.setFixedHeight(22)
            return line
        self.text_widgets = [self.style_combo, self.font_combo, self.size_combo, self.bold, self.italic, self.underline,
                             self.strike, self.color, self.highlight, self.align, self.lists, self.spacing, self.proof,
                             self.more_text]
        for w in (self.sidebar, self.title, sep(), self.undo, self.redo, sep(), self.style_combo, self.font_combo,
                  self.size_combo, self.bold, self.italic, self.underline, self.strike, self.color, self.highlight,
                  self.align, self.lists, self.spacing, self.proof, self.more_text):
            row.addWidget(w)
        row.addStretch(1)
        for w in (self.add_cards, self.zoom, sep(), self.pages, self.tools, self.note_menu):
            row.addWidget(w)
        self._build_menus()

    def _build_menus(self):
        ed = self.editor
        m = QMenu(self)
        for title, value in theme.TEXT_COLORS:
            a = m.addAction(swatch_icon(value), title)
            a.triggered.connect(lambda _=False, v=value: ed.fmt("color", v))
        self.color.setMenu(m)
        m = QMenu(self)
        for title, value in theme.HIGHLIGHTS:
            a = m.addAction(swatch_icon(value), title)
            a.triggered.connect(lambda _=False, v=value: ed.fmt("highlight", v))
        m.addSeparator()
        m.addAction(swatch_icon(None), "Tirar destaque").triggered.connect(lambda: ed.fmt("highlight", None))
        self.highlight.setMenu(m)
        m = QMenu(self)
        for title, key, icon in (("Esquerda", "left", "align-left"), ("Centro", "center", "align-center"),
                                 ("Direita", "right", "align-right"), ("Justificado", "justify", "align-justify")):
            m.addAction(icons.icon(icon), title).triggered.connect(lambda _=False, k=key: ed.fmt("align", k))
        self.align.setMenu(m)
        m = QMenu(self)
        m.addAction(icons.icon("list"), "Com marcadores").triggered.connect(lambda: ed.fmt("bullets"))
        m.addAction(icons.icon("list-num"), "Numerada").triggered.connect(lambda: ed.fmt("numbers"))
        m.addAction("Remover lista").triggered.connect(lambda: ed.fmt("nolist"))
        self.lists.setMenu(m)
        m = QMenu(self)
        m.addAction(icons.icon("indent"), "Aumentar recuo").triggered.connect(lambda: ed.fmt("indent", 1))
        m.addAction(icons.icon("outdent"), "Diminuir recuo").triggered.connect(lambda: ed.fmt("indent", -1))
        self.keep_action = m.addAction(icons.icon("keep-next"), "Manter com o parágrafo seguinte")
        self.keep_action.setCheckable(True)
        self.keep_action.triggered.connect(ed.set_keep_with_next)
        m.aboutToShow.connect(lambda: self.keep_action.setChecked(ed.current_keep()))
        m.addAction(icons.icon("signature"), "Linha de assinatura…").triggered.connect(ed.insert_signature)
        m.addSeparator()
        m.addAction("Aumentar a fonte (Ctrl+])").triggered.connect(lambda: ed.fmt("grow", 1))
        m.addAction("Diminuir a fonte (Ctrl+[)").triggered.connect(lambda: ed.fmt("grow", -1))
        m.addSeparator()
        m.addAction(icons.icon("link"), "Inserir link… (Ctrl+K)").triggered.connect(ed.insert_link)
        m.addAction(icons.icon("note"), "Ligar a outra nota…").triggered.connect(ed.link_to_note)
        m.addAction(icons.icon("find"), "Localizar e substituir… (Ctrl+H)").triggered.connect(ed.find_replace)
        self.more_text.setMenu(m)
        m = QMenu(self)
        self.spacing_actions = []
        for f in (1.0, 1.15, 1.5, 2.0, 2.5, 3.0):
            a = m.addAction(f"{f:g}".replace(".", ","))
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, v=f: ed.fmt("spacing", v))
            self.spacing_actions.append((f, a))
        m.addSeparator()
        self.space_after = m.addAction("Espaço depois do parágrafo")
        self.space_after.setCheckable(True)
        self.space_after.triggered.connect(lambda on: ed.fmt("after", 8.0 if on else 0.0))
        m.addAction("Personalizar…").triggered.connect(ed.custom_spacing)

        def refresh():
            factor, _, after = ed.current_spacing()
            for f, a in self.spacing_actions:
                a.setChecked(abs(f - factor) < 0.01)
            self.space_after.setChecked(after > 0.5)
        m.aboutToShow.connect(refresh)
        self.spacing.setMenu(m)
        m = QMenu(self)
        m.addAction(icons.icon("fit"), "Ajustar à largura").triggered.connect(lambda: ed.view.fit_width())
        m.addAction(icons.icon("zoom-in"), "Ampliar (Ctrl++)").triggered.connect(lambda: ed.view.set_zoom(ed.view.zoom() * 1.25))
        m.addAction(icons.icon("zoom-out"), "Reduzir (Ctrl+-)").triggered.connect(lambda: ed.view.set_zoom(ed.view.zoom() * 0.8))
        m.addSeparator()
        for z in (50, 75, 100, 125, 150, 200):
            m.addAction(f"{z}%").triggered.connect(lambda _=False, v=z: ed.view.set_zoom(v / 100))
        self.zoom.setMenu(m)
        self.note_menu.setMenu(ed.build_note_menu(self))

    def set_fonts(self, families: list[str]) -> None:
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        for f in families:
            self.font_combo.addItem(f)
            self.font_combo.setItemData(self.font_combo.count() - 1, QFont(f), Qt.ItemDataRole.FontRole)
        self.font_combo.blockSignals(False)

    def show_state(self, state: dict | None) -> None:
        """Mostra o que está ligado onde está o cursor (botão pressionado, fonte e tamanho)."""
        enabled = state is not None
        for w in self.text_widgets:
            w.setEnabled(enabled)
        if not state:
            return
        for w, key in ((self.bold, "bold"), (self.italic, "italic"), (self.underline, "underline"), (self.strike, "strike")):
            w.blockSignals(True)
            w.setChecked(bool(state.get(key)))
            w.blockSignals(False)
        self.font_combo.blockSignals(True)
        i = self.font_combo.findText(state.get("family") or "")
        if i < 0 and state.get("family"):
            self.font_combo.addItem(state["family"])
            i = self.font_combo.count() - 1
        self.font_combo.setCurrentIndex(max(0, i))
        self.font_combo.blockSignals(False)
        self.size_combo.blockSignals(True)
        self.size_combo.setEditText(f"{state.get('size', 12):g}")
        self.size_combo.blockSignals(False)
        icon = {"center": "align-center", "right": "align-right", "justify": "align-justify"}.get(state.get("align"), "align-left")
        self.align.setIcon(icons.icon(icon, theme.INK, theme.ACCENT))
        self.lists.setCheckable(True)
        self.lists.setChecked(bool(state.get("list")))
        self.style_combo.blockSignals(True)
        idx = self.style_combo.findData(state.get("named") or "body")
        self.style_combo.setCurrentIndex(max(0, idx))
        self.style_combo.blockSignals(False)


class Tile(QToolButton):
    def __init__(self, icon: str, title: str, tall: bool = False):
        super().__init__()
        self.setIcon(icons.icon(icon, theme.INK, theme.ACCENT))
        self.setIconSize(QSize(24, 24))
        self.setText(title)                  # "\n" quebra o nome em duas linhas
        plain = title.replace("\n", " ")
        self.setToolTip(plain)
        self.setAccessibleName(plain)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setFixedSize(74, 76 if tall else 62)
        self.setFont(theme.ui_font(8))
        self.setStyleSheet("QToolButton { background: #F4F6F8; border: 1px solid #E3E7EB; border-radius: 10px; padding: 4px 2px; }"
                           "QToolButton:hover { background: #EAF0F7; border-color: #C9D7E8; }"
                           "QToolButton:checked { background: #DCE8F7; border-color: %s; }" % theme.ACCENT)


class ToolsPanel(QScrollArea):
    """Ferramentas em grade, por grupos (como a folha de Ferramentas do iPad)."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setWidgetResizable(True)
        self.setFixedWidth(296)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("toolshost")
        host.setStyleSheet(f"#toolshost {{ background: {theme.CARD}; border-left: 1px solid {theme.LINE}; }}")
        self.setWidget(host)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(12, 10, 12, 16)
        lay.setSpacing(6)
        self.tool_buttons: dict[str, QToolButton] = {}

        def header(text):
            lab = QLabel(text)
            lab.setFont(theme.ui_font(9, True))
            lab.setStyleSheet(f"color: {theme.MUTED}; padding-top: 8px;")
            lay.addWidget(lab)

        def grid(tiles, cols=3):
            g = QGridLayout()
            g.setSpacing(6)
            for i, t in enumerate(tiles):
                g.addWidget(t, i // cols, i % cols)
            lay.addLayout(g)

        ed = editor
        header("Desenhar")
        draw = []
        for key, title, icon in (("select", "Selecionar", "select"), ("pen", "Caneta", "pen"), ("marker", "Marcador", "marker"),
                                 ("pencil", "Lápis", "pencil"), ("eraser", "Borracha", "eraser"), ("lasso", "Laço", "drag")):
            t = Tile(icon, title)
            t.setCheckable(True)
            t.clicked.connect(lambda _=False, k=key: ed.set_tool(k))
            self.tool_buttons[key] = t
            draw.append(t)
        grid(draw)
        sw = QHBoxLayout()
        sw.setSpacing(4)
        self.swatches = []
        for c in theme.INK_COLORS:
            b = QToolButton()
            b.setIcon(swatch_icon(c))
            b.setIconSize(QSize(20, 20))
            b.setToolTip("Cor do traço")
            b.clicked.connect(lambda _=False, v=c: ed.set_ink_color(v))
            b.setProperty("color", c)
            self.swatches.append(b)
            sw.addWidget(b)
        sw.addStretch()
        lay.addLayout(sw)
        wl = QHBoxLayout()
        wl.addWidget(QLabel("Largura"))
        self.width = QSlider(Qt.Orientation.Horizontal)
        self.width.setRange(2, 40)
        self.width.setToolTip("Largura do traçado")
        self.width.valueChanged.connect(lambda v: ed.set_ink_width(v / 2))
        wl.addWidget(self.width, 1)
        lay.addLayout(wl)
        self.whole = QCheckBox("Borracha apaga o traço inteiro")
        self.whole.toggled.connect(ed.set_eraser_whole)
        lay.addWidget(self.whole)
        self.recognize = QCheckBox("Formas perfeitas (desenho vira forma)")
        self.recognize.setToolTip("Retângulos, elipses, losangos, triângulos, linhas e setas desenhados viram formas editáveis")
        self.recognize.toggled.connect(ed.set_recognize)
        lay.addWidget(self.recognize)
        self.handwriting = QCheckBox("Escrita vira texto")
        self.handwriting.setToolTip("O que você escrever à mão vira texto digitado (reconhecimento de escrita do Windows)")
        self.handwriting.toggled.connect(ed.set_handwriting)
        lay.addWidget(self.handwriting)
        hf = QHBoxLayout()
        hf.addWidget(QLabel("Fonte"))
        self.hw_font = QComboBox()
        for f in theme.HANDWRITING_FONTS + ["Fonte do texto"]:
            self.hw_font.addItem(f)
        self.hw_font.currentTextChanged.connect(ed.set_handwriting_font)
        hf.addWidget(self.hw_font, 1)
        lay.addLayout(hf)
        self.equations = QCheckBox("Resolver equações escritas à mão")
        self.equations.toggled.connect(ed.set_solve_equations)
        lay.addWidget(self.equations)

        header("Inserir")
        ins = []
        for icon, title, fn in (("textbox", "Texto", ed.insert_text_box), ("table", "Tabela", ed.insert_table),
                                ("image", "Imagem", ed.choose_images), ("pdf", "PDF", ed.choose_pdf),
                                ("pdf-annotate", "PDF para\nanotar", ed.choose_pdf_annotate), ("video", "Vídeo", ed.choose_video),
                                ("mic", "Gravar\náudio", ed.record_audio), ("wave", "Arquivo\nde áudio", ed.choose_audio),
                                ("sticker", "Sticker", ed.choose_sticker), ("calendar", "Calendário", ed.insert_calendar),
                                ("connector", "Conexão", lambda: ed.set_tool("connector")),
                                ("signature", "Assinatura", ed.insert_signature)):
            t = Tile(icon, title, tall=True)
            t.clicked.connect(lambda _=False, f=fn: f())
            if title == "Conexão":
                t.setCheckable(True)
                self.tool_buttons["connector"] = t
            ins.append(t)
        sticky = Tile("sticky", "Post-it", tall=True)
        menu = QMenu(sticky)
        for title, value in model.STICKY_COLORS:
            menu.addAction(swatch_icon(value), title).triggered.connect(lambda _=False, v=value: ed.insert_sticky(v))
        sticky.clicked.connect(lambda: ed.insert_sticky(model.STICKY_COLORS[0][1]))
        sticky.setMenu(menu)
        sticky.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        ins.insert(9, sticky)
        grid(ins)
        header("Formas")
        shp = []
        for kind in model.SHAPE_KINDS:
            t = Tile(kind, model.SHAPE_TITLES[kind])
            t.setCheckable(True)
            t.clicked.connect(lambda _=False, k=kind: ed.set_tool("shape:" + k))
            self.tool_buttons["shape:" + kind] = t
            shp.append(t)
        grid(shp)
        hint = QLabel("Arraste na página para desenhar a forma (Shift deixa proporcional).")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 8pt;")
        lay.addWidget(hint)

        header("Destacar")
        hl = QHBoxLayout()
        for title, value in theme.HIGHLIGHTS:
            b = QToolButton()
            b.setIcon(swatch_icon(value))
            b.setIconSize(QSize(22, 22))
            b.setToolTip(f"Destacar em {title}")
            b.clicked.connect(lambda _=False, v=value: ed.fmt("highlight", v))
            hl.addWidget(b)
        clear = QToolButton()
        clear.setIcon(swatch_icon(None))
        clear.setIconSize(QSize(22, 22))
        clear.setToolTip("Limpar destaque")
        clear.clicked.connect(lambda: ed.fmt("highlight", None))
        hl.addWidget(clear)
        hl.addStretch()
        lay.addLayout(hl)

        header("Página")
        pg = []
        for icon, title, fn in (("header", "Cabeçalho\ne rodapé", lambda: ed.header_footer(0)),
                                ("number", "Numerar\npáginas", lambda: ed.header_footer(2)),
                                ("paper", "Papel", ed.paper), ("page-size", "Tamanho e\nmargens", ed.page_setup),
                                ("plus", "Nova\npágina", ed.add_page)):
            t = Tile(icon, title, tall=True)
            t.clicked.connect(lambda _=False, f=fn: f())
            pg.append(t)
        grid(pg)
        lay.addStretch(1)

    def show_tool(self, tool: str) -> None:
        for key, b in self.tool_buttons.items():
            b.setChecked(key == tool)

    def show_ink(self, color: str, width: float) -> None:
        for b in self.swatches:
            b.setIcon(swatch_icon(b.property("color"), ring=b.property("color") == color))
        self.width.blockSignals(True)
        self.width.setValue(int(round(width * 2)))
        self.width.blockSignals(False)


class PagesPanel(QListWidget):
    """Miniaturas das páginas: um clique leva à página; botão direito inclui ou apaga."""
    page_clicked = Signal(int)

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setFixedWidth(150)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(False)
        self.setIconSize(QSize(104, 147))
        self.setSpacing(8)
        self.setMovement(QListWidget.Movement.Static)
        self.setStyleSheet(f"QListWidget {{ background: {theme.SIDEBAR}; border: none; border-right: 1px solid {theme.LINE}; }}"
                           "QListWidget::item { color: #4B5563; border-radius: 6px; padding: 2px; }"
                           f"QListWidget::item:selected {{ background: #DCE8F7; color: {theme.INK}; }}")
        self.itemClicked.connect(lambda it: self.page_clicked.emit(self.row(it)))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        it = self.itemAt(pos)
        m = QMenu(self)
        if it is not None:
            idx = self.row(it)
            m.addAction(icons.icon("plus"), "Nova página depois desta").triggered.connect(lambda: self.editor.add_page(after=idx))
            m.addAction(icons.icon("paper"), "Papel desta página…").triggered.connect(lambda: self.editor.paper(page=idx))
            m.addSeparator()
            m.addAction(icons.icon("trash"), "Apagar esta página").triggered.connect(lambda: self.editor.delete_page(idx))
        else:
            m.addAction(icons.icon("plus"), "Nova página").triggered.connect(lambda: self.editor.add_page())
        m.exec(self.mapToGlobal(pos))

    def set_pages(self, images: list) -> None:
        current = self.currentRow()
        self.clear()
        for i, img in enumerate(images):
            it = QListWidgetItem(QIcon(QPixmap.fromImage(img)) if img is not None else QIcon(), f"{i + 1}")
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.addItem(it)
        if 0 <= current < self.count():
            self.setCurrentRow(current)


class RoundButton(QToolButton):
    def __init__(self, icon: str, tip: str, color: str = theme.ACCENT):
        super().__init__()
        self.base = color
        self.setIcon(icons.icon(icon, "#FFFFFF"))
        self.setIconSize(QSize(24, 24))
        self.setFixedSize(52, 52)
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setCheckable(True)
        self.restyle()
        self.toggled.connect(lambda *_: self.restyle())

    def restyle(self):
        bg = theme.NAVY if self.isChecked() else self.base
        self.setStyleSheet(f"QToolButton {{ background: {bg}; border-radius: 26px; border: 2px solid rgba(255,255,255,0.9); }}"
                           f"QToolButton:hover {{ background: {QColor(bg).lighter(115).name()}; }}")
