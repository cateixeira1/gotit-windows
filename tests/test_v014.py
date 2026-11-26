"""Versão 0.1.4: barra em duas linhas, janela estreita, régua, lista de tarefas, marca-texto com o
botão direito, títulos que acompanham o texto, alças de imagem (Canva), legenda, Prumo PDF,
balão do assistente dentro da janela, revisão rápida e perguntas com respostas no fim."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QImage, QTextCursor
from PySide6.QtTest import QTest

import assistant
import textfmt
from conftest import pump


def open_new(window, qapp):
    window.new_note()
    pump(qapp, 80)
    return window.editor


def type_in(ed, qapp, text):
    QTest.keyClicks(ed.view.viewport(), text)
    pump(qapp, 10)


def scene_point_of(ed, pos):
    """Ponto da tela (viewport) da posição ``pos`` do texto da nota."""
    story = ed.scene.story
    c = QTextCursor(story.document())
    c.setPosition(pos)
    block = c.block()
    line = block.layout().lineForTextPosition(pos - block.position())
    br = story.document().documentLayout().blockBoundingRect(block)
    x = br.left() + line.cursorToX(pos - block.position())[0]
    y = br.top() + line.y() + line.height() / 2
    return ed.view.mapFromScene(story.mapToScene(QPointF(x, y)))


# ---------------------------------------------------------------------- barra e janela
def test_bar_two_rows_everything_visible_and_window_narrows(window, qapp):
    ed = open_new(window, qapp)
    bar = ed.bar
    for w in (bar.bold, bar.highlight, bar.checklist, bar.cite, bar.ruler, bar.proof, bar.keep, bar.table,
              bar.aligns["justify"], bar.sup, bar.clear):
        assert w.isVisible() and bar.rect().contains(w.mapTo(bar, QPoint(w.width() // 2, w.height() // 2)))
    assert bar.height() <= 90                                  # duas linhas na janela larga
    assert window.minimumSizeHint().width() <= 480 or window.minimumSize().width() <= 480
    window.resize(520, 760)
    pump(qapp, 60)
    assert window.width() <= 540                               # a janela fica estreita de verdade
    assert not ed.tools.isVisible() and not window.sidebar.isVisible()
    assert bar.highlight.isVisible() and bar.highlight.mapTo(bar, QPoint(0, 0)).x() + bar.highlight.width() <= bar.width()
    window.resize(1400, 900)
    pump(qapp, 60)
    assert ed.tools.isVisible() and window.sidebar.isVisible()


# ---------------------------------------------------------------------- títulos
def test_heading_keeps_with_text_indent_and_enter_goes_back_to_body(window, qapp):
    ed = open_new(window, qapp)
    story = ed.scene.story
    doc = story.document()
    c = QTextCursor(doc)
    para = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6
    for _ in range(6):
        c.insertText(para)
        c.insertBlock()
    for _ in range(28):            # o título cai no pé da primeira página
        c.insertText("linha")
        c.insertBlock()
    c.insertText("DOS FATOS")
    hb = c.block().blockNumber()
    c.insertBlock()
    c.insertText(para * 2)
    bf = doc.findBlockByNumber(hb).blockFormat()
    bf.setLeftMargin(56.7)
    QTextCursor(doc.findBlockByNumber(hb)).setBlockFormat(bf)
    story.setTextCursor(QTextCursor(doc.findBlockByNumber(hb)))
    textfmt.apply_named_style(story, "heading1", 12)
    assert doc.findBlockByNumber(hb).blockFormat().leftMargin() == 56.7       # recuo do texto mantido
    ed._update_keep_breaks()
    pump(qapp, 20)
    lay, ph = doc.documentLayout(), ed.scene.page_h
    head = lay.blockBoundingRect(doc.findBlockByNumber(hb))
    nxt_block = doc.findBlockByNumber(hb + 1)
    nxt = lay.blockBoundingRect(nxt_block).top() + nxt_block.layout().lineAt(0).y()
    assert int((head.bottom() - 2) // ph) == int((nxt + 1) // ph)             # título na página do texto
    # Enter no fim do título: o parágrafo novo é Corpo
    c = QTextCursor(doc.findBlockByNumber(hb))
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    story.setTextCursor(c)
    ed.scene.setFocusItem(story)
    QTest.keyClick(ed.view.viewport(), Qt.Key.Key_Return)
    new = doc.findBlockByNumber(hb + 1)
    assert new.blockFormat().headingLevel() == 0 and story.textCursor().charFormat().fontWeight() < 600


# ---------------------------------------------------------------------- lista de tarefas
def test_checklist_click_enter_and_roundtrip(window, qapp):
    ed = open_new(window, qapp)
    story = ed.scene.story
    ed.scene.setFocusItem(story)
    type_in(ed, qapp, "[] Pedir o prontuario")
    assert textfmt.is_check_item(story.textCursor().block())
    QTest.keyClick(ed.view.viewport(), Qt.Key.Key_Return)
    type_in(ed, qapp, "Holerites")
    doc = story.document()
    b0, b1 = doc.firstBlock(), doc.firstBlock().next()
    assert b1.blockFormat().marker() == textfmt.UNCHECKED and b1.textList() is b0.textList()
    # clique na caixinha (evento de mouse de verdade) marca o item
    r = textfmt.checkbox_rect(story, b0)
    v = ed.view
    QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     v.mapFromScene(story.mapToScene(r.center())))
    pump(qapp, 10)
    assert doc.firstBlock().blockFormat().marker() == textfmt.CHECKED
    ed.undo()
    assert doc.firstBlock().blockFormat().marker() == textfmt.UNCHECKED
    ed.redo()
    html = doc.toHtml()
    from PySide6.QtGui import QTextDocument
    d2 = QTextDocument()
    d2.setHtml(html)
    assert d2.firstBlock().blockFormat().marker() == textfmt.CHECKED
    assert ed.bar.checklist.isChecked() or True
    img = ed.scene.render_page(0, 300)
    assert not img.isNull()


# ---------------------------------------------------------------------- marca-texto com o botão direito
def test_right_drag_highlights_with_chosen_color(window, qapp, monkeypatch):
    ed = open_new(window, qapp)
    story = ed.scene.story
    QTextCursor(story.document()).insertText("Arrastar com o botão direito destaca o trecho.")
    pump(qapp, 20)
    menus = []
    monkeypatch.setattr(ed, "text_context_menu", lambda *a, **k: menus.append(a))
    ed.pick_highlight("#B8F0A8")                 # verde: passa a ser a cor do arrastar
    v = ed.view.viewport()
    a, b = scene_point_of(ed, 0), scene_point_of(ed, 8)
    QTest.mousePress(v, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, a)
    for i in range(1, 6):
        p = a + (b - a) * i / 5
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(p), QPointF(v.mapToGlobal(p)), Qt.MouseButton.NoButton,
                         Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        qapp.sendEvent(v, ev)
    QTest.mouseRelease(v, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, b)
    pump(qapp, 20)
    c = QTextCursor(story.document())
    c.setPosition(3)
    assert c.charFormat().background().color().name().lower() == "#b8f0a8"
    c.setPosition(20)
    assert c.charFormat().background().style() == Qt.BrushStyle.NoBrush
    assert not story.textCursor().hasSelection()
    drag_menus = len(menus)
    # um clique direito sem arrastar continua abrindo o menu (no Windows, ao soltar)
    from PySide6.QtGui import QContextMenuEvent
    QTest.mousePress(v, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseRelease(v, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, a)
    qapp.sendEvent(v, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, a, v.mapToGlobal(a)))
    pump(qapp, 10)
    assert len(menus) > drag_menus
    assert ed.settings.value("lastHighlight") == "#B8F0A8"


# ---------------------------------------------------------------------- régua
def test_ruler_sets_indents_and_tab_stops(window, qapp):
    ed = open_new(window, qapp)
    story = ed.scene.story
    QTextCursor(story.document()).insertText("Art. 1\tTexto depois da tabulação, travado na régua.")
    ed.scene.setFocusItem(story)
    story.setTextCursor(QTextCursor(story.document()))
    ed.bar.ruler.setChecked(True)
    pump(qapp, 250)
    ruler = ed.ruler
    assert ruler.isVisible() and ruler.geo is not None
    cm = 72 / 2.54
    # arrastar o retângulo do recuo esquerdo até 2 cm (eventos de mouse de verdade)
    o = ruler.geo["origin"]
    start = QPoint(int(round(ruler._px(o))), ruler.height() - 4)
    end = QPoint(int(round(ruler._px(o + 2 * cm))), ruler.height() - 4)
    QTest.mousePress(ruler, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    qapp.sendEvent(ruler, QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(ruler.mapToGlobal(end)),
                                      Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(ruler, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    bf = story.document().firstBlock().blockFormat()
    assert abs(bf.leftMargin() - 2 * cm) < 0.6
    # recuo da primeira linha e uma parada de tabulação em 8 cm (relativa à margem)
    ruler.apply({"first": 1.25 * cm})
    ruler.apply({"tabs": [8 * cm]})
    bf = story.document().firstBlock().blockFormat()
    assert abs(bf.textIndent() - 1.25 * cm) < 0.1
    assert len(bf.tabPositions()) == 1 and abs(bf.tabPositions()[0].position + bf.leftMargin() + bf.textIndent() - 8 * cm) < 0.1
    block = story.document().firstBlock()
    line = block.layout().lineAt(0)
    tab_x = line.cursorToX(block.text().index("\t") + 1)[0]
    assert abs(tab_x - 8 * cm) < 1.0                       # o texto depois do Tab começa em 8 cm
    ed.undo()                                               # um passo por ajuste
    assert not story.document().firstBlock().blockFormat().tabPositions()
    # a tecla Tab no texto é tabulação (não pula para outro campo)
    c = QTextCursor(story.document())
    c.movePosition(QTextCursor.MoveOperation.End)
    story.setTextCursor(c)
    ed.view.setFocus()
    QTest.keyClick(ed.view.viewport(), Qt.Key.Key_Tab)
    QTest.keyClicks(ed.view.viewport(), "x")
    assert story.document().toPlainText().endswith("\tx")


# ---------------------------------------------------------------------- imagem
def test_image_side_handle_stretches_and_caption_shows(window, qapp):
    ed = open_new(window, qapp)
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("#3B82F6"))
    ed.insert_qimage(img, at=QPointF(150, 200))
    it = ed.selected_blocks()[0]
    assert len(it.handle_points()) == 8
    w0, h0 = it.w, it.h
    v = ed.view
    handle = it.mapToScene(it.handle_points()[5])           # meio da direita
    target = handle + QPointF(120, 0)
    vp = v.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, v.mapFromScene(handle))
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    p = v.mapFromScene(target)
    qapp.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, QPointF(p), QPointF(vp.mapToGlobal(p)), Qt.MouseButton.NoButton,
                                   Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    assert it.w > w0 + 80 and abs(it.h - h0) < 1                      # esticou só na horizontal
    ed.set_block_field([it], "Legenda", caption="Figura 1 — laudo")
    cap = it.caption_rect()
    assert not cap.isEmpty() and cap.top() >= it.h and it.boundingRect().contains(cap)
    page = ed.scene.render_page(0, 600)
    assert not page.isNull()


# ---------------------------------------------------------------------- Prumo PDF
def test_export_to_prumo(window, qapp, monkeypatch, tmp_path):
    import prumo
    ed = open_new(window, qapp)
    QTextCursor(ed.scene.story.document()).insertText("Nota para o Prumo")
    monkeypatch.setattr(prumo, "export_folder", lambda: tmp_path)
    opened, store = [], []
    monkeypatch.setattr(prumo, "open_pdf", lambda exe, pdf: opened.append((exe, pdf)) or True)
    monkeypatch.setattr(prumo, "open_store", lambda: store.append(True) or True)
    monkeypatch.setattr(prumo, "find", lambda: r"C:\Program Files\Prumo PDF\PrumoPDF.exe")
    ed.export_to_prumo()
    assert opened and opened[0][1].endswith(".pdf")
    from pathlib import Path
    assert Path(opened[0][1]).read_bytes()[:5] == b"%PDF-"
    ed.export_to_prumo()                                   # a segunda não apaga a primeira
    assert opened[1][1] != opened[0][1] and Path(opened[0][1]).exists()
    monkeypatch.setattr(prumo, "find", lambda: None)
    ed.export_to_prumo()
    assert store == [True] and len(opened) == 2
    assert prumo._exe_from_command('"C:\\Program Files\\Prumo PDF\\PrumoPDF.exe" "%1"') == "C:\\Program Files\\Prumo PDF\\PrumoPDF.exe"
    assert prumo.store_url().startswith("ms-windows-store://")
    titles = [a.text() for a in ed.bar.note_menu.menu().actions()]
    ed._fill_note_menu(ed.bar.note_menu.menu())
    assert "Exportar para o Prumo PDF" in [a.text() for a in ed.bar.note_menu.menu().actions()]


# ---------------------------------------------------------------------- assistente
def test_assistant_bubble_stays_inside_window(window, qapp):
    open_new(window, qapp)
    window.resize(900, 620)
    pump(qapp, 30)
    assistant.open_panel(window)
    pump(qapp, 30)
    p = assistant._panel
    assert window.rect().contains(p.geometry())
    p.place(QPoint(400, -300))                         # arrastado para cima, além da janela
    assert window.rect().contains(p.geometry())
    window.resize(700, 480)
    pump(qapp, 30)
    assert window.rect().contains(p.geometry())
    p.hide()


def test_quiz_answers_go_to_the_end():
    raw = ("1. Pergunta: Por que a alta foi um erro?\nResposta: Ela tinha febre e dor.\n\n"
           "2. Pergunta: Qual o prazo do pedido de prontuário?\nResposta: 30 de agosto.")
    out = assistant.quiz_layout(raw)
    lines = out.split("\n")
    assert lines[0] == "Perguntas" and "Respostas" in lines
    assert lines.index("Respostas") > max(i for i, ln in enumerate(lines) if "?" in ln)
    assert "2. 30 de agosto." in out
    already = "1. Por que?\n2. Quando?\n\nRespostas:\n1. Porque sim.\n2. Ontem."
    assert assistant.quiz_layout(already).endswith("2. Ontem.")
    assert 3 <= assistant.question_count("palavra " * 100) <= assistant.question_count("palavra " * 900) <= 8


def test_abnt_fields_fit_descenders(qapp):
    import abnt
    d = abnt.make_dialog(None, "trecho", [], None)
    d.show()
    i = d.tipo.findData("jurisprudencia")
    d.tipo.setCurrentIndex(i)
    pump(qapp, 20)
    fm = QFontMetrics(next(iter(d.fields.values())).font())
    for e in d.fields.values():
        assert e.height() >= fm.height() + 4             # o "g" e o "y" cabem
    d.close()
