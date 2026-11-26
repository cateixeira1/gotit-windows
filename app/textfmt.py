"""Formatação de texto como no Word: fonte, tamanho, negrito, itálico, sublinhado, tachado,
cores, destaque, alinhamento, listas, recuos, espaço entre linhas, links e estilos nomeados.

Age sobre a seleção do texto em edição; numa caixa selecionada (sem edição), vale para o texto
todo da caixa."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat,
                           QTextListFormat)

NAMED_STYLE_PROP = QTextFormat.Property.UserProperty + 1

NAMED_STYLES = [
    # id, título, tamanho relativo ao corpo, negrito, itálico, cor, recuo
    ("title", "Título", 2.0, True, False, "#111827", 0),
    ("subtitle", "Subtítulo", 1.4, False, False, "#4B5563", 0),
    ("heading1", "Título 1", 1.6, True, False, "#1F2933", 0),
    ("heading2", "Título 2", 1.3, True, False, "#1F2933", 0),
    ("body", "Corpo", 1.0, False, False, "#1F2933", 0),
    ("quote", "Citação", 1.0, False, True, "#4B5563", 24),
]

ALLOWED_LINK = re.compile(r"^(https?://|mailto:|gotit://nota/)", re.IGNORECASE)


def is_allowed_link(href: str) -> bool:
    """Só endereços http(s), mailto e links entre notas viram link."""
    return bool(ALLOWED_LINK.match(href.strip()))


def cursor_for(item, whole_if_not_editing: bool = True) -> QTextCursor:
    c = item.textCursor()
    owner = getattr(item, "owner", None)
    editing = bool(item.textInteractionFlags() & Qt.TextInteractionFlag.TextEditable)
    if owner is not None and not editing and whole_if_not_editing:
        c = QTextCursor(item.document())
        c.select(QTextCursor.SelectionType.Document)
    return c


def _merge(item, fmt: QTextCharFormat) -> None:
    c = cursor_for(item)
    if c.hasSelection():
        c.mergeCharFormat(fmt)
        return
    # sem seleção: vale para a palavra sob o cursor (como no Word) e para o que for digitado
    word = QTextCursor(c)
    word.select(QTextCursor.SelectionType.WordUnderCursor)
    if word.hasSelection() and word.selectionStart() < c.position() < word.selectionEnd():
        word.mergeCharFormat(fmt)
    tc = item.textCursor()
    tc.mergeCharFormat(fmt)
    item.setTextCursor(tc)


def current(item) -> QTextCharFormat:
    c = cursor_for(item)
    if c.hasSelection():
        probe = QTextCursor(c.document())
        probe.setPosition(c.selectionStart() + 1)
        return probe.charFormat()
    return item.textCursor().charFormat()


def toggle_bold(item) -> None:
    fmt = QTextCharFormat()
    fmt.setFontWeight(QFont.Weight.Normal if current(item).fontWeight() >= QFont.Weight.DemiBold else QFont.Weight.Bold)
    _merge(item, fmt)


def toggle_italic(item) -> None:
    fmt = QTextCharFormat()
    fmt.setFontItalic(not current(item).fontItalic())
    _merge(item, fmt)


def toggle_underline(item) -> None:
    fmt = QTextCharFormat()
    fmt.setFontUnderline(not current(item).fontUnderline())
    _merge(item, fmt)


def toggle_strike(item) -> None:
    fmt = QTextCharFormat()
    fmt.setFontStrikeOut(not current(item).fontStrikeOut())
    _merge(item, fmt)


def set_family(item, family: str) -> None:
    fmt = QTextCharFormat()
    fmt.setFontFamilies([family])
    _merge(item, fmt)


def set_size(item, size: float) -> None:
    fmt = QTextCharFormat()
    fmt.setFontPointSize(size)
    _merge(item, fmt)


def grow(item, step: int) -> None:
    size = current(item).fontPointSize() or item.document().defaultFont().pointSizeF() or 12
    sizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48, 60, 72]
    if step > 0:
        nxt = next((s for s in sizes if s > size + 0.1), size + 8)
    else:
        nxt = next((s for s in reversed(sizes) if s < size - 0.1), max(6, size - 2))
    set_size(item, nxt)


def set_color(item, color: str) -> None:
    fmt = QTextCharFormat()
    fmt.setForeground(QBrush(QColor(color)))
    _merge(item, fmt)


def set_highlight(item, color: str | None) -> None:
    fmt = QTextCharFormat()
    if color:
        fmt.setBackground(QBrush(QColor(color)))
        _merge(item, fmt)
    else:
        c = cursor_for(item)
        if c.hasSelection():
            fmt.clearBackground()
            # mergeCharFormat não apaga propriedades: passa por cada trecho
            start, end = c.selectionStart(), c.selectionEnd()
            pos = start
            doc = item.document()
            while pos < end:
                probe = QTextCursor(doc)
                probe.setPosition(pos)
                block = probe.block()
                it = block.begin()
                while not it.atEnd():
                    frag = it.fragment()
                    fs, fe = frag.position(), frag.position() + frag.length()
                    s, e = max(fs, start), min(fe, end)
                    if s < e:
                        cur = QTextCursor(doc)
                        cur.setPosition(s)
                        cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
                        cf = frag.charFormat()
                        cf.clearBackground()
                        cur.setCharFormat(cf)
                    it += 1
                pos = block.position() + block.length()


def set_alignment(item, align: Qt.AlignmentFlag) -> None:
    c = cursor_for(item)
    bf = QTextBlockFormat()
    bf.setAlignment(align)
    c.mergeBlockFormat(bf)


def alignment(item) -> Qt.AlignmentFlag:
    return item.textCursor().blockFormat().alignment()


def _neighbor_list(block, style):
    """Lista do parágrafo anterior, se for do mesmo tipo (o item volta para ela e a numeração
    continua, em vez de recomeçar do 1)."""
    prev = block.previous()
    lst = prev.textList() if prev.isValid() else None
    return lst if lst is not None and lst.format().style() == style else None


def toggle_list(item, style: QTextListFormat.Style) -> None:
    c = cursor_for(item)
    current_list = c.currentList()
    if current_list is not None and current_list.format().style() == style:
        remove_list(item)
        return
    c.beginEditBlock()
    if current_list is not None:
        fmt = current_list.format()
        fmt.setStyle(style)
        current_list.setFormat(fmt)
    else:
        doc = item.document()
        first = doc.findBlock(c.selectionStart())
        lst = _neighbor_list(first, style)
        if lst is not None:
            block = first
            while block.isValid() and block.position() <= c.selectionEnd():
                lst.add(block)
                block = block.next()
        else:
            fmt = QTextListFormat()
            fmt.setStyle(style)
            fmt.setIndent(1)
            c.createList(fmt)
    c.endEditBlock()


AUTO_BULLET = re.compile(r"^\s*([-*•–])\s$")
AUTO_NUMBER = re.compile(r"^\s*(\d{1,3})[.)]\s$")
AUTO_LETTER = re.compile(r"^\s*([a-z])\)\s$")


def auto_list(item) -> bool:
    """Depois de um espaço no começo da linha: "- " (ou "* ", "• ") vira marcador; "1. ", "1) "
    vira lista numerada (continua a lista de cima se for o número seguinte); "a) " vira lista
    com letras. Fica num passo de desfazer próprio: Ctrl+Z volta ao "- " escrito."""
    c = item.textCursor()
    if c.hasSelection() or c.currentList() is not None or c.currentTable() is not None:
        return False
    head = c.block().text()[:c.positionInBlock()]
    style, start = None, 1
    if AUTO_BULLET.match(head):
        style = QTextListFormat.Style.ListDisc
    elif (m := AUTO_NUMBER.match(head)):
        style, start = QTextListFormat.Style.ListDecimal, int(m.group(1))
    elif (m := AUTO_LETTER.match(head)):
        style, start = QTextListFormat.Style.ListLowerAlpha, ord(m.group(1)) - ord("a") + 1
    if style is None:
        return False
    c.beginEditBlock()
    c.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
    c.removeSelectedText()
    lst = _neighbor_list(c.block(), style)
    if lst is not None and (style == QTextListFormat.Style.ListDisc or lst.count() + lst.format().start() == start):
        lst.add(c.block())
    else:
        fmt = QTextListFormat()
        fmt.setStyle(style)
        fmt.setIndent(1)
        if start != 1:
            fmt.setStart(start)
        c.createList(fmt)
    c.endEditBlock()
    item.setTextCursor(c)
    return True


def leave_list_item(item) -> bool:
    """Backspace no começo de um item: o parágrafo sai da lista (o texto fica) e os itens de
    baixo continuam na lista, renumerados."""
    c = item.textCursor()
    lst = c.currentList()
    if lst is None or c.hasSelection() or not c.atBlockStart():
        return False
    c.beginEditBlock()
    block = c.block()
    lst.remove(block)
    bf = block.blockFormat()
    bf.setIndent(0)
    bc = QTextCursor(block)
    bc.setBlockFormat(bf)
    c.endEditBlock()
    return True


# ---------------------------------------------------------------- parágrafos: manter com o próximo
KEEP, AUTO_BREAK = 1, 2      # bits do userState do bloco (vai junto no HTML: -qt-user-state)


def state_bits(block) -> int:
    v = block.userState()
    return 0 if v < 0 else v


def set_bits(block, bits: int, on: bool) -> None:
    v = state_bits(block)
    block.setUserState((v | bits) if on else (v & ~bits))


def keeps_with_next(block) -> bool:
    return bool(state_bits(block) & KEEP) or block.blockFormat().headingLevel() > 0


def set_keep_with_next(item, on: bool) -> None:
    c = cursor_for(item)
    doc = item.document()
    block = doc.findBlock(c.selectionStart())
    end = c.selectionEnd()
    while block.isValid() and block.position() <= end:
        set_bits(block, KEEP, on)
        block = block.next()
    doc.contentsChanged.emit()


def keep_breaks(doc, page_h: float) -> set[int]:
    """Números dos parágrafos que precisam começar na página seguinte para ficar com o próximo.
    Calcula numa cópia do documento (sem as quebras automáticas atuais), de cima para baixo."""
    work = doc.clone()
    work.setDefaultFont(doc.defaultFont())
    work.setDocumentMargin(doc.documentMargin())
    work.setPageSize(doc.pageSize())          # (setTextWidth apagaria a altura da página)
    rf = work.rootFrame().frameFormat()
    of = doc.rootFrame().frameFormat()
    for side in ("Top", "Bottom", "Left", "Right"):
        getattr(rf, "set" + side + "Margin")(getattr(of, side[0].lower() + side[1:] + "Margin")())
    work.rootFrame().setFrameFormat(rf)
    block = work.firstBlock()
    while block.isValid():
        if state_bits(doc.findBlockByNumber(block.blockNumber())) & AUTO_BREAK:
            c = QTextCursor(block)
            bf = block.blockFormat()
            bf.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_Auto)
            c.setBlockFormat(bf)
        block = block.next()
    layout = work.documentLayout()
    need: set[int] = set()

    def page_of(y: float) -> int:
        return int(y // page_h)
    block = work.firstBlock()
    guard = 0
    while block.isValid() and guard < 2000:
        guard += 1
        nxt = block.next()
        src = doc.findBlockByNumber(block.blockNumber())
        if nxt.isValid() and keeps_with_next(src) and block.text().strip():
            r, rn = layout.blockBoundingRect(block), layout.blockBoundingRect(nxt)
            last_y = r.bottom() - 2          # a última linha está na página do fim do parágrafo
            first_n = rn.top()
            if page_of(last_y + 1) != page_of(first_n + 1):
                start = block       # a corrente toda (vários "manter") desce junto
                while start.previous().isValid() and keeps_with_next(doc.findBlockByNumber(start.previous().blockNumber())) \
                        and start.previous().text().strip():
                    start = start.previous()
                top = layout.blockBoundingRect(start).top()
                prev = start.previous()
                at_page_top = not prev.isValid() or page_of(layout.blockBoundingRect(prev).bottom() - 1) != page_of(top + 1)
                if not at_page_top and start.blockNumber() not in need:
                    need.add(start.blockNumber())
                    c = QTextCursor(start)
                    bf = start.blockFormat()
                    bf.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
                    c.setBlockFormat(bf)
                    block = start
                    continue
        block = nxt
    return need


def apply_keep_breaks(doc, need: set[int]) -> bool:
    """Põe/tira as quebras automáticas para chegar em ``need``. Junta ao último passo de desfazer
    (não vira um passo próprio). Devolve True se mudou algo."""
    have = set()
    block = doc.firstBlock()
    while block.isValid():
        if state_bits(block) & AUTO_BREAK:
            have.add(block.blockNumber())
        block = block.next()
    if have == need:
        return False
    c = QTextCursor(doc)
    c.joinPreviousEditBlock()
    for n in have | need:
        block = doc.findBlockByNumber(n)
        if not block.isValid():
            continue
        bc = QTextCursor(block)
        bf = block.blockFormat()
        bf.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore if n in need
                              else QTextFormat.PageBreakFlag.PageBreak_Auto)
        bc.setBlockFormat(bf)
        set_bits(block, AUTO_BREAK, n in need)
    c.endEditBlock()
    return True


# ---------------------------------------------------------------- assinatura
def insert_signature(item, name: str, second: str = "", place_date: str = "", width_pt: float = 220.0) -> None:
    """Linha de assinatura centralizada: (local e data), espaço para assinar, a linha, o nome e
    uma segunda linha opcional (cargo, OAB, CPF). Tudo "mantido com o próximo" para não se
    separar entre páginas."""
    c = item.textCursor()
    c.beginEditBlock()
    if c.block().text().strip():
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        c.insertBlock()
    base = QTextBlockFormat()
    base.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    base.setTopMargin(0)
    base.setBottomMargin(0)
    plain = QTextCharFormat()
    font = item.document().defaultFont()
    fm = QFontMetricsF(font)
    unders = "_" * max(20, int(width_pt / max(1.0, fm.horizontalAdvance("_"))))
    rows = []
    if place_date:
        rows += [place_date, ""]
    rows += ["", unders, name or "Nome"]
    if second:
        rows.append(second)
    first = True
    blocks = []
    for text in rows:
        if not first:
            c.insertBlock(base, plain)
        else:
            c.setBlockFormat(base)
            c.setCharFormat(plain)
            first = False
        c.insertText(text, plain)
        blocks.append(c.block())
    for b in blocks[:-1]:
        set_bits(b, KEEP, True)
    c.endEditBlock()
    item.setTextCursor(c)



def remove_list(item) -> None:
    c = cursor_for(item)
    c.beginEditBlock()
    start, end = c.selectionStart(), c.selectionEnd()
    doc = item.document()
    block = doc.findBlock(start)
    while block.isValid() and block.position() <= end:
        lst = block.textList()
        if lst is not None:
            lst.remove(block)
            bc = QTextCursor(block)
            bf = block.blockFormat()
            bf.setIndent(0)
            bc.setBlockFormat(bf)
        block = block.next()
    c.endEditBlock()


def list_style(item):
    lst = item.textCursor().currentList()
    return lst.format().style() if lst is not None else None


def indent(item, delta: int) -> None:
    c = cursor_for(item)
    lst = c.currentList()
    if lst is not None:
        fmt = lst.format()
        fmt.setIndent(max(1, fmt.indent() + delta))
        lst.setFormat(fmt)
        return
    bf = c.blockFormat()
    bf.setIndent(max(0, bf.indent() + delta))
    c.setBlockFormat(bf)


def set_line_spacing(item, factor: float) -> None:
    c = cursor_for(item)
    bf = QTextBlockFormat()
    bf.setLineHeight(factor * 100, 1)   # ProportionalHeight
    c.mergeBlockFormat(bf)


def set_spacing(item, factor: float, before: float, after: float) -> None:
    c = cursor_for(item)
    bf = QTextBlockFormat()
    bf.setLineHeight(factor * 100, 1)
    bf.setTopMargin(before)
    bf.setBottomMargin(after)
    c.mergeBlockFormat(bf)


def set_paragraph_spacing(item, points: float) -> None:
    c = cursor_for(item)
    bf = QTextBlockFormat()
    bf.setBottomMargin(points)
    c.mergeBlockFormat(bf)


def insert_link(item, href: str, text: str | None = None) -> bool:
    if not is_allowed_link(href):
        return False
    c = item.textCursor()
    fmt = QTextCharFormat()
    fmt.setAnchor(True)
    fmt.setAnchorHref(href)
    fmt.setForeground(QBrush(QColor("#2563EB")))
    fmt.setFontUnderline(True)
    if c.hasSelection():
        c.mergeCharFormat(fmt)
    else:
        c.insertText(text or href, fmt)
        plain = QTextCharFormat()
        plain.setAnchor(False)
        plain.setAnchorHref("")
        plain.setFontUnderline(False)
        plain.setForeground(QBrush(QColor("#1F2933")))
        c.setCharFormat(plain)
        item.setTextCursor(c)
    return True


def remove_link(item) -> None:
    c = item.textCursor()
    if not c.hasSelection():
        c.select(QTextCursor.SelectionType.WordUnderCursor)
    fmt = QTextCharFormat()
    fmt.setAnchor(False)
    fmt.setAnchorHref("")
    fmt.setFontUnderline(False)
    fmt.setForeground(QBrush(QColor("#1F2933")))
    c.mergeCharFormat(fmt)


def apply_named_style(item, style_id: str, base_size: float) -> None:
    spec = next((s for s in NAMED_STYLES if s[0] == style_id), None)
    if not spec:
        return
    _, _, rel, bold, italic, color, left = spec
    c = cursor_for(item)
    c.beginEditBlock()
    start, end = c.selectionStart(), c.selectionEnd()
    sel = QTextCursor(item.document())
    sel.setPosition(item.document().findBlock(start).position())
    endblock = item.document().findBlock(end)
    sel.setPosition(endblock.position() + max(0, endblock.length() - 1), QTextCursor.MoveMode.KeepAnchor)
    cf = QTextCharFormat()
    cf.setFontPointSize(round(base_size * rel))
    cf.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    cf.setFontItalic(italic)
    cf.setForeground(QBrush(QColor(color)))
    sel.mergeCharFormat(cf)
    bf = QTextBlockFormat()
    bf.setLeftMargin(left)
    bf.setProperty(NAMED_STYLE_PROP, style_id)
    if style_id in ("title", "heading1", "heading2"):
        bf.setTopMargin(6)
        bf.setBottomMargin(4)
    sel.mergeBlockFormat(bf)
    c.endEditBlock()


def named_style(item) -> str | None:
    value = item.textCursor().blockFormat().property(NAMED_STYLE_PROP)
    return value if isinstance(value, str) else None


def find_all(doc, needle: str, case: bool = False, whole: bool = False) -> list[QTextCursor]:
    from PySide6.QtGui import QTextDocument
    flags = QTextDocument.FindFlag(0)
    if case:
        flags |= QTextDocument.FindFlag.FindCaseSensitively
    if whole:
        flags |= QTextDocument.FindFlag.FindWholeWords
    out = []
    c = QTextCursor(doc)
    while True:
        c = doc.find(needle, c, flags)
        if c.isNull():
            break
        out.append(QTextCursor(c))
    return out


def insert_table(item, rows: int, cols: int) -> None:
    from PySide6.QtGui import QTextLength, QTextTableFormat, QTextFrameFormat
    fmt = QTextTableFormat()
    fmt.setBorder(1)
    fmt.setBorderBrush(QBrush(QColor("#94A3B8")))
    fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
    fmt.setBorderCollapse(True)
    fmt.setCellPadding(5)
    fmt.setCellSpacing(0)
    fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
    c = item.textCursor()
    c.beginEditBlock()
    table = c.insertTable(rows, cols, fmt)
    for col in range(cols):
        cell = table.cellAt(0, col)
        cf = cell.format()
        cf.setBackground(QColor("#EEF2F6"))
        cell.setFormat(cf)
    c.endEditBlock()
    item.setTextCursor(table.cellAt(0, 0).firstCursorPosition())
