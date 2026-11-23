"""Formatação de texto como no Word: fonte, tamanho, negrito, itálico, sublinhado, tachado,
cores, destaque, alinhamento, listas, recuos, espaço entre linhas, links e estilos nomeados.

Age sobre a seleção do texto em edição; numa caixa selecionada (sem edição), vale para o texto
todo da caixa."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat,
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
        fmt = QTextListFormat()
        fmt.setStyle(style)
        fmt.setIndent(1)
        c.createList(fmt)
    c.endEditBlock()


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
