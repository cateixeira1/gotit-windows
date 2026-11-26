"""Barra de formatação (em cima), painel de ferramentas em grade (à direita, como no iPad),
painel de páginas (à esquerda) e os botões redondos da caneta e do assistente."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QToolButton, QVBoxLayout, QWidget, QWidgetAction, QWidgetItem)

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


BAR_ICON = "#2C2C2E"        # quase preto, como os símbolos da Apple
BAR_ACTIVE = theme.ACCENT


def bar_button(name: str, tip: str, checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setObjectName("barbtn")
    b.setIcon(icons.icon(name, BAR_ICON, BAR_ACTIVE))
    b.setIconSize(QSize(18, 18))
    b.setFixedSize(30, 30)
    b.setToolTip(tip)
    b.setAccessibleName(tip.split(" (")[0])
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)        # o cursor continua no texto
    return b


class BarFlow(QLayout):
    """Layout da barra de cima: duas linhas de grupos. Cada linha quebra sozinha quando a janela
    fica estreita (a janela pode ficar tão estreita quanto o maior grupo). Os itens marcados
    ``right`` ficam no fim da primeira linha (zoom, páginas, ferramentas e o menu da nota)."""

    def __init__(self, parent=None, hspace: int = 12, vspace: int = 2):
        super().__init__(parent)
        self._items: list[tuple] = []       # (QLayoutItem, linha, à direita)
        self.hspace, self.vspace = hspace, vspace

    def add(self, widget, row: int, right: bool = False) -> None:
        self.addChildWidget(widget)
        self._items.append((QWidgetItem(widget), row, right))
        self.invalidate()

    # API do QLayout
    def addItem(self, item):
        self._items.append((item, 0, False))

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i][0] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i)[0] if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, apply=True)

    def sizeHint(self):
        m = self.contentsMargins()
        rows = {0: 0, 1: 0}
        for it, row, _ in self._items:
            if not it.isEmpty():
                rows[row] += it.sizeHint().width() + self.hspace
        w = max(rows.values()) + m.left() + m.right()
        return QSize(w, self.heightForWidth(w))

    def minimumSize(self):
        m = self.contentsMargins()
        w = max([it.minimumSize().width() for it, _, _ in self._items if not it.isEmpty()] + [0])
        return QSize(w + m.left() + m.right(), 34 + m.top() + m.bottom())

    def _do(self, rect, apply: bool) -> int:
        m = self.contentsMargins()
        left, right_edge = rect.x() + m.left(), rect.x() + rect.width() - m.right()
        y = rect.y() + m.top()
        lines = []                       # [(itens [(item, x)], linha lógica)]
        for row in (0, 1):
            trailing = [it for it, r, is_right in self._items if r == row and is_right and not it.isEmpty()]
            trail_w = sum(it.sizeHint().width() for it in trailing) + self.hspace * max(0, len(trailing) - 1)
            cur, x, first, start = [], left, True, len(lines)
            for it, r, is_right in self._items:
                if r != row or is_right or it.isEmpty():
                    continue
                w = it.sizeHint().width()
                limit = right_edge - (trail_w + self.hspace if first and trailing else 0)
                if cur and x + w > limit:
                    lines.append((cur, row))
                    cur, x, first = [], left, False
                cur.append((it, x))
                x += w + self.hspace
            lines.append((cur, row))
            if trailing:
                # no fim da primeira linha desta fileira (ou numa linha própria, se não couber)
                head = lines[start][0]
                used = (head[-1][1] + head[-1][0].sizeHint().width()) if head else left
                x = right_edge - trail_w
                placed = []
                for it in trailing:
                    placed.append((it, x))
                    x += it.sizeHint().width() + self.hspace
                if head and used + self.hspace > right_edge - trail_w:
                    shift = (right_edge - trail_w) - left
                    lines.insert(start + 1, ([(it, px - shift) for it, px in placed], row))
                else:
                    lines[start] = (head + placed, row)
        lines = [ln for ln in lines if ln[0]]
        total = 0
        for i, (items, row) in enumerate(lines):
            h = max([it.sizeHint().height() for it, _ in items] + [30])
            if apply:
                for it, x in items:
                    sh = it.sizeHint()
                    it.setGeometry(QRect(x, y + (h - sh.height()) // 2, sh.width(), sh.height()))
            gap = self.vspace + (4 if i + 1 < len(lines) and lines[i + 1][1] != row else 0)
            y += h + gap
            total += h + gap
        return total - self.vspace + m.top() + m.bottom()


def group(*widgets, spacing: int = 1) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        lay.addWidget(x)
    return w


class FormatBar(QFrame):
    """Barra de cima, em duas linhas, com tudo à vista (nada escondido em "mais opções").

    A ordem segue o uso: na 1ª linha, o que se faz com as palavras (desfazer, estilo, fonte e
    tamanho, negrito/itálico/sublinhado, cor e marca-texto), da esquerda — onde o olho começa —
    para a direita; na 2ª, o que se faz com o parágrafo (alinhamento, listas, recuos, espaçamento)
    e depois inserir e revisar. Ícones de traço fino, sem molduras, grupos separados por espaço."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setObjectName("formatbar")
        self.setStyleSheet(
            f"#formatbar {{ background: #FFFFFF; border-bottom: 1px solid #E6E8EB; }}"
            "#formatbar QToolButton#barbtn { border: none; border-radius: 7px; padding: 0; background: transparent; }"
            "#formatbar QToolButton#barbtn:hover { background: rgba(0, 0, 0, 0.055); }"
            "#formatbar QToolButton#barbtn:pressed { background: rgba(0, 0, 0, 0.10); }"
            f"#formatbar QToolButton#barbtn:checked {{ background: rgba(46, 111, 183, 0.13); }}"
            "#formatbar QToolButton#barbtn::menu-button { border: none; width: 11px; }"
            "#formatbar QToolButton#barbtn[popupMode=\"1\"] { padding-right: 10px; }"
            "#formatbar QComboBox { background: #F2F3F5; border: 1px solid transparent; border-radius: 7px; padding: 2px 8px; }"
            "#formatbar QComboBox:hover { background: #EAECEF; }"
            f"#formatbar QComboBox:focus {{ border: 1px solid {theme.ACCENT}; background: white; }}")
        flow = BarFlow(self)
        flow.setContentsMargins(10, 6, 10, 6)
        self.flow = flow
        ed = editor
        self.last_color = theme.TEXT_COLORS[1][1] if len(theme.TEXT_COLORS) > 1 else "#C0392B"

        # ---------------------------------------------------------- 1ª linha: palavras
        self.sidebar = bar_button("sidebar", "Mostrar ou esconder o menu (Ctrl+\\)")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Título")
        self.title.setFont(theme.ui_font(11, True))
        self.title.setFixedWidth(176)
        self.title.setStyleSheet("QLineEdit { border: 1px solid transparent; background: transparent; padding: 3px 6px; }"
                                 "QLineEdit:hover { border: 1px solid #DDE2E7; } QLineEdit:focus { border: 1px solid %s; background: white; }" % theme.ACCENT)
        self.undo = bar_button("undo", "Desfazer (Ctrl+Z)")
        self.redo = bar_button("redo", "Refazer (Ctrl+Y)")
        self.style_combo = QComboBox()
        self.style_combo.setToolTip("Estilo do parágrafo")
        for sid, title, *_ in textfmt.NAMED_STYLES:
            self.style_combo.addItem(title, sid)
        self.style_combo.setFixedWidth(104)
        self.font_combo = QComboBox()
        self.font_combo.setToolTip("Fonte")
        self.font_combo.setFixedWidth(146)
        self.font_combo.setMaxVisibleItems(18)
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        self.size_combo.setToolTip("Tamanho da fonte")
        self.size_combo.setFixedWidth(58)
        for sz in FONT_SIZES:
            self.size_combo.addItem(str(sz))
        self.grow = bar_button("font-grow", "Aumentar a fonte (Ctrl+])")
        self.shrink = bar_button("font-shrink", "Diminuir a fonte (Ctrl+[)")
        self.bold = bar_button("bold", "Negrito (Ctrl+B)", True)
        self.italic = bar_button("italic", "Itálico (Ctrl+I)", True)
        self.underline = bar_button("underline", "Sublinhado (Ctrl+U)", True)
        self.strike = bar_button("strike", "Tachado", True)
        self.color = bar_button("text-color", "Cor do texto (clique: a última cor; seta: escolher)")
        self.color.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.color.setFixedSize(42, 30)
        self.highlight = bar_button("highlight", "Marca-texto (clique: a cor escolhida; seta: escolher). "
                                                 "Com uma cor escolhida, arraste com o botão direito do mouse sobre o texto para destacar")
        self.highlight.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.highlight.setFixedSize(42, 30)
        self.zoom = QToolButton()
        self.zoom.setObjectName("barbtn")
        self.zoom.setText("100%")
        self.zoom.setToolTip("Zoom (Ctrl + roda do mouse)")
        self.zoom.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.zoom.setFixedHeight(30)
        self.zoom.setMinimumWidth(58)
        self.zoom.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_cards = QToolButton()
        self.add_cards.setIcon(icons.icon("plus", theme.INK))
        self.add_cards.setText("Adicionar notas")
        self.add_cards.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_cards.setToolTip("Adicionar notas a esta Teia")
        self.add_cards.clicked.connect(editor.add_notes_to_teia)
        self.add_cards.hide()
        self.pages = bar_button("pages", "Páginas", True)
        self.tools = bar_button("shapes", "Ferramentas (desenhar, inserir, formas, página)", True)
        self.note_menu = bar_button("more", "Mais: exportar, abrir no Prumo PDF, imprimir, citada em…")
        self.note_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.note_menu.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")

        # ---------------------------------------------------------- 2ª linha: parágrafo, inserir, revisar
        self.aligns = {}
        self.align_group = QButtonGroup(self)
        self.align_group.setExclusive(True)
        for key, icon, tip in (("left", "align-left", "Alinhar à esquerda (Ctrl+L)"), ("center", "align-center", "Centralizar (Ctrl+E)"),
                               ("right", "align-right", "Alinhar à direita (Ctrl+R)"), ("justify", "align-justify", "Justificar (Ctrl+J)")):
            b = bar_button(icon, tip, True)
            b.clicked.connect(lambda _=False, k=key: ed.fmt("align", k))
            self.aligns[key] = b
            self.align_group.addButton(b)
        self.bullets = bar_button("list", "Lista com marcadores (ou escreva \"- \" no começo da linha)", True)
        self.numbers = bar_button("list-num", "Lista numerada (ou escreva \"1. \" no começo da linha)", True)
        self.checklist = bar_button("checklist", "Lista de tarefas, com caixinhas para marcar (ou escreva \"[] \")", True)
        self.lists = self.bullets          # compatibilidade
        self.outdent = bar_button("outdent", "Diminuir recuo")
        self.indent = bar_button("indent", "Aumentar recuo")
        self.spacing = bar_button("line-spacing", "Espaçamento entre linhas e parágrafos")
        self.spacing.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.spacing.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        self.sup = bar_button("superscript", "Sobrescrito (1º, m²)", True)
        self.sub = bar_button("subscript", "Subscrito (H₂O)", True)
        self.clear = bar_button("clear-format", "Limpar a formatação do trecho")
        self.link = bar_button("link", "Inserir link (Ctrl+K)")
        self.note_link = bar_button("note-link", "Ligar a outra nota")
        self.table = bar_button("table", "Inserir tabela")
        self.find = bar_button("find", "Localizar e substituir (Ctrl+H)")
        self.proof = bar_button("spellcheck", "Revisar o texto (ortografia e gramática, pelo assistente)")
        self.proof.clicked.connect(editor.proofread)
        self.cite = bar_button("quote", "Citação ABNT do trecho selecionado")
        self.signature = bar_button("signature", "Linha de assinatura")
        self.keep = bar_button("keep-next", "Manter com o parágrafo seguinte (não separa na quebra de página)", True)
        self.ruler = bar_button("ruler", "Mostrar a régua (recuos e tabulações)", True)
        self.more_text = None

        self.text_widgets = [self.style_combo, self.font_combo, self.size_combo, self.grow, self.shrink, self.bold,
                             self.italic, self.underline, self.strike, self.color, self.highlight, *self.aligns.values(),
                             self.bullets, self.numbers, self.checklist, self.outdent, self.indent, self.spacing, self.sup,
                             self.sub, self.clear, self.link, self.note_link, self.find, self.proof, self.cite,
                             self.signature, self.keep]
        for w in (group(self.sidebar, self.title, spacing=4), group(self.undo, self.redo), self.style_combo,
                  group(self.font_combo, self.size_combo, spacing=4), group(self.grow, self.shrink),
                  group(self.bold, self.italic, self.underline, self.strike), group(self.color, self.highlight, spacing=2)):
            flow.add(w, 0)
        for w in (self.add_cards, group(self.pages, self.tools, self.note_menu)):
            flow.add(w, 0, right=True)
        for w in (group(*self.aligns.values()), group(self.bullets, self.numbers, self.checklist),
                  group(self.outdent, self.indent, self.spacing), group(self.sup, self.sub, self.clear),
                  group(self.link, self.note_link, self.table), group(self.find, self.proof, self.cite, self.signature, self.keep),
                  self.ruler):
            flow.add(w, 1)
        flow.add(self.zoom, 1, right=True)
        self.bullets.clicked.connect(lambda: ed.fmt("bullets"))
        self.numbers.clicked.connect(lambda: ed.fmt("numbers"))
        self.checklist.clicked.connect(lambda: ed.fmt("checklist"))
        self.outdent.clicked.connect(lambda: ed.fmt("indent", -1))
        self.indent.clicked.connect(lambda: ed.fmt("indent", 1))
        self.grow.clicked.connect(lambda: ed.fmt("grow", 1))
        self.shrink.clicked.connect(lambda: ed.fmt("grow", -1))
        self.sup.clicked.connect(lambda: ed.fmt("valign", "super"))
        self.sub.clicked.connect(lambda: ed.fmt("valign", "sub"))
        self.clear.clicked.connect(lambda: ed.fmt("clear"))
        self.link.clicked.connect(ed.insert_link)
        self.note_link.clicked.connect(ed.link_to_note)
        self.table.clicked.connect(ed.insert_table)
        self.find.clicked.connect(ed.find_replace)
        self.cite.clicked.connect(ed.cite_current)
        self.signature.clicked.connect(ed.insert_signature)
        self.keep.clicked.connect(ed.set_keep_with_next)
        self.color.clicked.connect(lambda: ed.fmt("color", self.last_color))
        self.highlight.clicked.connect(lambda: ed.fmt("highlight", ed.last_highlight))
        self._build_menus()
        self.show_colors()

    def show_colors(self) -> None:
        """O botão mostra a cor que um clique aplica."""
        self.color.setIcon(color_icon_bar("text-color", self.last_color))
        hl = self.editor.last_highlight or "#F4FF2E"
        base = icons.pixmap("highlight", BAR_ICON, 20)
        pm = QPixmap(base.size())
        pm.setDevicePixelRatio(base.devicePixelRatio())
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.drawPixmap(0, 0, base)
        p.fillRect(2, 17, 16, 3, QColor(hl))
        p.end()
        self.highlight.setIcon(QIcon(pm))

    def _build_menus(self):
        ed = self.editor
        m = QMenu(self)
        for title, value in theme.TEXT_COLORS:
            a = m.addAction(swatch_icon(value), title)
            a.triggered.connect(lambda _=False, v=value: self._pick_color(v))
        self.color.setMenu(m)
        m = QMenu(self)
        for title, value in theme.HIGHLIGHTS:
            a = m.addAction(swatch_icon(value), title)
            a.triggered.connect(lambda _=False, v=value: ed.pick_highlight(v))
        m.addSeparator()
        m.addAction(swatch_icon(None), "Tirar destaque").triggered.connect(lambda: ed.fmt("highlight", None))
        self.highlight.setMenu(m)
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

    def _pick_color(self, value: str) -> None:
        self.last_color = value
        self.show_colors()
        self.editor.fmt("color", value)

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
        for w, key in ((self.bold, "bold"), (self.italic, "italic"), (self.underline, "underline"), (self.strike, "strike"),
                       (self.sup, "super"), (self.sub, "sub"), (self.keep, "keep")):
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
        b = self.aligns.get(state.get("align") or "left")
        if b is not None:
            b.setChecked(True)
        kind = state.get("list")
        self.bullets.setChecked(kind == "bullets")
        self.numbers.setChecked(kind == "numbers")
        self.checklist.setChecked(kind == "check")
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
        self.setFixedWidth(300)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("toolshost")
        host.setStyleSheet(f"#toolshost {{ background: {theme.CARD}; border-left: 1px solid {theme.LINE}; }}")
        self.setWidget(host)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(12, 10, 20, 16)        # a barra de rolagem não cobre a última coluna
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
