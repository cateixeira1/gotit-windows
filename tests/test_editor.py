"""Editor de ponta a ponta, sem tela: inserir, desfazer, gravar e reabrir."""

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QTextCursor

import items
import model
from conftest import pump


def open_new(window, qapp, **kw):
    window.new_note() if not kw.get("simple") else window.new_simple_note()
    pump(qapp, 80)
    return window.editor


def reopen(window, qapp, doc_id):
    window.editor.save_now()
    window.editor.close_document()
    window.open_note(doc_id)
    pump(qapp, 80)
    return window.editor


def test_typing_saves_and_reopens(window, qapp):
    ed = open_new(window, qapp)
    story = ed.scene.story
    story.textCursor().insertText("Olá, mundo")
    c = story.textCursor()
    c.insertText(" do Got It!")
    ed.save_now()
    doc_id = ed.doc["id"]
    ed = reopen(window, qapp, doc_id)
    assert "Olá, mundo do Got It!" in ed.scene.story.document().toPlainText()
    assert window.store.search("mundo")[0].doc_id == doc_id


def test_insert_objects_undo_redo(window, qapp):
    ed = open_new(window, qapp)
    ed.insert_sticky("#FFB8D2")
    ed.insert_calendar()
    ed._add("sticker", 96, 96, "Sticker", emoji="⭐")
    ed.finish_shape_drag("rectangle", QPointF(100, 300), QPointF(240, 380))
    ed.finish_shape_drag("arrow", QPointF(100, 420), QPointF(300, 420))
    kinds = sorted(it.kind for it in ed.scene.items_by_id.values())
    assert kinds == ["calendar", "line", "shape", "sticker", "sticky"]
    ed.stop_all_editing()
    for _ in range(5):
        ed.undo()
    assert ed.scene.items_by_id == {}
    for _ in range(5):
        ed.redo()
    assert len(ed.scene.items_by_id) == 5
    doc_id = ed.doc["id"]
    ed.content_changed()
    ed = reopen(window, qapp, doc_id)
    assert sorted(it.kind for it in ed.scene.items_by_id.values()) == kinds


def test_objects_avoid_each_other_and_text(window, qapp):
    ed = open_new(window, qapp)
    ed.scene.story.textCursor().insertText("Linha de texto que ocupa o topo da página")
    pump(qapp, 30)
    a = ed._add("calendar", 132, 148, "x")
    b = ed._add("calendar", 132, 148, "x")
    from PySide6.QtCore import QRectF, QSizeF
    ra, rb = QRectF(a.pos(), QSizeF(a.w, a.h)), QRectF(b.pos(), QSizeF(b.w, b.h))
    assert not ra.intersects(rb)
    m = ed.scene._text_margins
    assert a.pos().y() > m["top"] + 5            # abaixo do texto já escrito


def test_text_box_editing_and_undo_of_typing(window, qapp):
    ed = open_new(window, qapp)
    ed.insert_text_box()
    box = next(iter(ed.scene.items_by_id.values()))
    assert box.editing
    box.text.textCursor().insertText("abc")
    assert box.text.document().toPlainText() == "abc"
    ed.undo()                                    # a digitação
    assert box.text.document().toPlainText() == ""
    ed.undo()                                    # a caixa
    assert ed.scene.items_by_id == {}
    ed.redo()
    ed.redo()
    assert next(iter(ed.scene.items_by_id.values())).text.document().toPlainText() == "abc"


def test_move_is_one_undo_step(window, qapp):
    ed = open_new(window, qapp)
    ed.insert_calendar()
    cal = next(iter(ed.scene.items_by_id.values()))
    start = QPointF(cal.pos())
    with ed.scene.change("Mover"):
        cal.setPos(start + QPointF(50, 30))
    ed.undo()
    assert cal.pos() == start
    ed.redo()
    assert cal.pos() == start + QPointF(50, 30)


def test_ink_recognition_and_eraser(window, qapp):
    ed = open_new(window, qapp)
    import math
    circle = [(300 + 80 * math.cos(t / 40 * 2 * math.pi), 400 + 50 * math.sin(t / 40 * 2 * math.pi), 0.5) for t in range(44)]
    ed.finish_stroke(0, "pen", circle)
    shapes_ = [it for it in ed.scene.items_by_id.values() if it.kind == "shape"]
    assert shapes_ and shapes_[0].data_state["shape"] == "ellipse"
    pencil_line = [(100 + i * 3, 600, 0.5) for i in range(40)]
    ed.finish_stroke(0, "pencil", pencil_line)
    assert len(ed.scene.strokes_by_id) == 1
    ed.eraser_whole = False
    ed.scene.begin_change()
    ed.erase_at(QPointF(160, 600))
    ed.scene.end_change("Apagar traço")
    assert len(ed.scene.strokes_by_id) == 2      # partido ao meio
    ed.undo()
    assert len(ed.scene.strokes_by_id) == 1


def test_line_between_shapes_becomes_connector(window, qapp):
    ed = open_new(window, qapp)
    ed.finish_shape_drag("rectangle", QPointF(100, 200), QPointF(200, 260))
    ed.finish_shape_drag("ellipse", QPointF(400, 200), QPointF(500, 260))
    line = [(150 + i * 5, 230, 0.5) for i in range(61)]
    ed.finish_stroke(0, "pen", line)
    assert len(ed.scene.connectors) == 1


def test_pages_header_footer_and_export(window, qapp, tmp_path):
    ed = open_new(window, qapp)
    with ed.scene.change("Cabeçalho"):
        ed.doc["canvas"]["header"] = {"text": "Escritório", "alignment": "center", "height": 30}
        ed.doc["canvas"]["pageNumbers"] = {"position": "footer", "alignment": "center", "format": "page_of", "start": 1}
        ed.scene.apply_page_format()
    top_with_header = ed.scene._text_margins["top"]
    ed.add_page()
    assert ed.scene.page_count() == 2
    c = ed.scene.story.textCursor()
    c.insertText("palavra " * 1200)
    pump(qapp, 50)
    assert ed.scene.page_count() >= 3            # o texto cria páginas
    ed.undo()
    pump(qapp, 50)
    out = tmp_path / "nota.pdf"
    ed.export_pdf_to(str(out))
    import pypdfium2
    pdf = pypdfium2.PdfDocument(str(out))
    assert len(pdf) == ed.scene.page_count()
    assert "Escritório" in pdf[0].get_textpage().get_text_range()
    pdf.close()
    assert top_with_header >= model.WORD_MARGINS["top"]


def test_paper_ruled_lines_fixed_height(window, qapp):
    ed = open_new(window, qapp)
    with ed.scene.change("Papel"):
        ed.doc["canvas"]["paper"] = {"kind": "ruled", "spacing": model.RULED_LINE}
        ed.scene.apply_page_format()
    ed.scene.story.textCursor().insertText("um\ndois")
    pump(qapp, 50)
    doc = ed.scene.story.document()
    b = doc.begin()
    lay = doc.documentLayout()
    y0, y1 = lay.blockBoundingRect(b).y(), lay.blockBoundingRect(b.next()).y()
    assert abs((y1 - y0) - model.RULED_LINE) < 0.5


def test_table_in_story_and_free_table(window, qapp):
    ed = open_new(window, qapp)
    import textfmt
    textfmt.insert_table(ed.scene.story, 2, 3)
    assert ed.scene.story.textCursor().currentTable() is not None
    ed.table_action(ed.scene.story, "row_below")
    assert ed.scene.story.textCursor().currentTable().rows() == 3
    ed._add("table", 300, 90, "Tabela", rows=2, columns=2, header=True, text="", html="")
    t = next(it for it in ed.scene.items_by_id.values() if it.kind == "table")
    st = t.state()
    assert st["rows"] == 2 and st["columns"] == 2


def test_formatting_whole_box_when_selected(window, qapp):
    ed = open_new(window, qapp)
    ed.insert_sticky("#FFF27A")
    s = next(iter(ed.scene.items_by_id.values()))
    s.text.textCursor().insertText("importante")
    s.stop_editing()
    ed.scene.setFocusItem(None)
    ed.scene.clearSelection()
    s.setSelected(True)
    ed.fmt("bold")
    c = QTextCursor(s.text.document())
    c.setPosition(3)
    assert c.charFormat().fontWeight() >= 600


def test_teia_cards_and_open(window, qapp):
    window.new_note()
    pump(qapp, 50)
    note_id = window.editor.doc["id"]
    window.new_teia([note_id])
    pump(qapp, 80)
    ed = window.editor
    cards = [it for it in ed.scene.items_by_id.values() if it.kind == "noteRef"]
    assert len(cards) == 1
    info = ed.scene.resolve_note(note_id)
    assert info and info["title"].startswith("Nota")
    cards[0].activate()
    pump(qapp, 80)
    assert window.editor.doc["id"] == note_id


def test_simple_note_has_no_tools(window, qapp):
    ed = open_new(window, qapp, simple=True)
    assert ed.doc["canvas"]["simpleNote"]
    assert not ed.tools.isVisible()


def test_pdf_annotate_pages(window, qapp, tmp_path):
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
    pdf_path = tmp_path / "doc.pdf"
    w = QPdfWriter(str(pdf_path))
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    p = QPainter(w)
    p.drawText(100, 100, "Página um")
    w.newPage()
    p.drawText(100, 100, "Página dois")
    p.end()
    ed = open_new(window, qapp)
    ed.annotate_pdf(window.store.import_asset(pdf_path), "doc")
    assert ed.scene.page_count() == 2
    assert ed.doc["pages"][0]["background"]["page"] == 0     # a 1ª página em branco recebe a 1ª do PDF
    ed.undo()
    assert ed.scene.page_count() == 1


def test_folder_by_drag_and_drop(window, qapp):
    window.new_note()
    a = window.editor.doc["id"]
    window.new_note()
    b = window.editor.doc["id"]
    pump(qapp, 30)
    import sidebar
    orig = sidebar.ask_folder_name
    sidebar.ask_folder_name = lambda parent, generic, **k: ""
    try:
        window.sidebar._merge(a, b)
    finally:
        sidebar.ask_folder_name = orig
    folders = window.store.folders("*")
    assert len(folders) == 1 and folders[0].name == "Pasta 1"
    assert {n.id for n in window.store.notes(folder_id=folders[0].id)} == {a, b}


def test_thumbnail_renders(window, qapp):
    ed = open_new(window, qapp)
    ed.scene.story.textCursor().insertText("Miniatura")
    ed._update_thumbs()
    img = window.thumbs.get(ed.doc["id"], ed.doc["revision"])
    assert img is not None and img.width() == 300


def _mouse(widget, kind, pos, buttons=Qt.MouseButton.LeftButton):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove, "release": QEvent.Type.MouseButtonRelease}[kind]
    btn = Qt.MouseButton.LeftButton if kind != "move" else Qt.MouseButton.NoButton
    held = buttons if kind != "release" else Qt.MouseButton.NoButton
    ev = QMouseEvent(t, QPointF(pos), widget.mapToGlobal(QPointF(pos)), btn, held, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)


def test_draw_with_mouse_and_move_object(window, qapp):
    ed = open_new(window, qapp)
    vp = ed.view.viewport()
    ed.set_tool("pencil")
    from PySide6.QtCore import QPoint
    _mouse(vp, "press", QPoint(300, 300))
    for i in range(1, 30):
        _mouse(vp, "move", QPoint(300 + i * 6, 300 + (i % 5) * 3))
    _mouse(vp, "release", QPoint(480, 300))
    assert len(ed.scene.strokes_by_id) == 1
    ed.set_tool("select")
    ed.insert_calendar()
    cal = next(iter(ed.scene.items_by_id.values()))
    ed.scene.clearSelection()
    center = ed.view.mapFromScene(cal.mapToScene(cal.w / 2, cal.h / 2))
    start = QPointF(cal.pos())
    _mouse(vp, "press", center)
    for i in range(1, 6):
        _mouse(vp, "move", center + QPoint(i * 10, i * 4))
    _mouse(vp, "release", center + QPoint(50, 20))
    assert (cal.pos() - start).manhattanLength() > 20
    n = ed.history.index
    ed.undo()
    assert (cal.pos() - start).manhattanLength() < 1
    assert ed.history.index == n - 1


def test_shape_tool_drag_creates_shape(window, qapp):
    ed = open_new(window, qapp)
    vp = ed.view.viewport()
    from PySide6.QtCore import QPoint
    ed.set_tool("shape:diamond")
    _mouse(vp, "press", QPoint(250, 400))
    _mouse(vp, "move", QPoint(320, 450))
    _mouse(vp, "release", QPoint(380, 480))
    shapes_ = [it for it in ed.scene.items_by_id.values() if it.kind == "shape"]
    assert len(shapes_) == 1 and shapes_[0].data_state["shape"] == "diamond"
    assert ed.tool == "select"


def test_delete_key_removes_selection(window, qapp):
    ed = open_new(window, qapp)
    ed.insert_calendar()
    ed.scene.setFocusItem(None)
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    ed.view.keyPressEvent(ev)
    assert ed.scene.items_by_id == {}


# ---------------------------------------------------------------- contas escritas à mão
def _dense(st):
    out = []
    for a, b in zip(st, st[1:]):
        for k in range(6):
            t = k / 6
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(st[-1])
    return out


def _glyphs():
    import mathink

    def arc(cx, cy, rx, ry, a0, a1):
        return mathink._arc(cx, cy, rx, ry, a0, a1, 16)
    return {
        "1": [[(44, 8), (50, 0), (49, 100)]],
        "2": [[*arc(48, 28, 26, 27, 190, 370), (40, 70), (20, 98), (80, 96)]],
        "7": [[(15, 4), (84, 0), (40, 100)]],
        "+": [[(10, 50), (90, 50)], [(50, 10), (50, 90)]],
        "=": [[(10, 38), (90, 37)], [(10, 66), (90, 64)]],
    }


def _write(ed, text, x=120.0, y=300.0, size=34.0, cell=None):
    """Escreve com a "caneta". Com ``cell``: um caractere por quadrado a partir de (x, y)."""
    g = _glyphs()
    if cell:
        size = cell * 0.7
    for ch in text:
        sz = size * 0.7 if ch in "+=" else size
        dy = size * 0.15 if ch in "+=" else 0
        if cell:
            x0 = x + (cell - sz * 0.9) / 2
            for st in g[ch]:
                ed.finish_stroke(0, "pen", [(x0 + px * sz / 100, y + (cell - size) / 2 + dy + py * sz / 100, 0.5)
                                            for px, py in _dense(st)])
            x += cell
            continue
        for st in g[ch]:
            dense = []
            for a, b in zip(st, st[1:]):
                for k in range(6):
                    t = k / 6
                    dense.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            dense.append(st[-1])
            ed.finish_stroke(0, "pen", [(x + px * sz / 100, y + dy + py * sz / 100, 0.5) for px, py in dense])
        x += sz * 0.9 + 8


def test_handwritten_sum_is_solved_without_windows(window, qapp, monkeypatch):
    import handwriting
    monkeypatch.setattr(handwriting, "RUN_IN_THREAD", False)
    monkeypatch.setattr(handwriting, "available", lambda: False)
    ed = open_new(window, qapp)
    ed.doc["canvas"]["solveEquations"] = True
    ed.doc["canvas"]["recognizeDiagrams"] = True
    _write(ed, "12+7=")
    assert not [it for it in ed.scene.items_by_id.values() if it.kind in ("line", "shape")]   # "=" e "+" seguem tinta
    ed.ink_timer.stop()
    ed._ink_pause()
    answers = [it for it in ed.scene.items_by_id.values() if it.data_state.get("equationOf")]
    assert len(answers) == 1 and answers[0].data_state["text"] == "19"
    ed.undo()
    assert not [it for it in ed.scene.items_by_id.values() if it.data_state.get("equationOf")]


def test_handwritten_sum_in_background(window, qapp):
    """Como no app: leitura numa thread (no Windows com reconhecedor, junta as leituras dele)."""
    import time
    ed = open_new(window, qapp)
    ed.doc["canvas"]["solveEquations"] = True
    ed.doc["canvas"]["handwritingToText"] = False
    _write(ed, "12+7=", y=420)
    ed.ink_timer.stop()
    ed._ink_pause()
    end = time.monotonic() + 30
    answers = []
    while time.monotonic() < end and not answers:
        pump(qapp, 50)
        answers = [it for it in ed.scene.items_by_id.values() if it.data_state.get("equationOf")]
    assert answers and answers[0].data_state["text"] == "19"


def test_eraser_removes_recognized_shapes(window, qapp):
    import math
    ed = open_new(window, qapp)
    ed.doc["canvas"]["recognizeDiagrams"] = True
    circle = [(300 + 80 * math.cos(t / 40 * 2 * math.pi), 400 + 50 * math.sin(t / 40 * 2 * math.pi), 0.5) for t in range(44)]
    ed.finish_stroke(0, "pen", circle)
    shape = [it for it in ed.scene.items_by_id.values() if it.kind == "shape"][0]
    assert shape.data_state.get("fromInk")
    ed.scene.begin_change()
    ed.erase_at(QPointF(300, 400))          # no meio da elipse vazia: não apaga
    ed.erase_at(QPointF(380, 400))          # na borda: apaga
    ed.scene.end_change("Apagar")
    assert not [it for it in ed.scene.items_by_id.values() if it.kind == "shape"]
    ed.undo()
    assert [it for it in ed.scene.items_by_id.values() if it.kind == "shape"]


def _click(ed, qapp, scene_pt):
    from PySide6.QtTest import QTest
    v = ed.view
    QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, v.mapFromScene(scene_pt))
    pump(qapp, 20)


def _type(ed, qapp, text):
    from PySide6.QtTest import QTest
    QTest.keyClicks(ed.view.viewport(), text)
    pump(qapp, 20)


def test_click_and_type_anywhere_on_the_page(window, qapp):
    window.resize(1300, 900)
    window.show()
    pump(qapp, 50)
    ed = open_new(window, qapp)
    ed.set_tool("select")
    sc = ed.scene
    m = sc._text_margins
    story = sc.story
    before = story.document().toPlainText()
    _click(ed, qapp, QPointF(300, 420))
    assert story.pending is not None
    _click(ed, qapp, QPointF(250, 500))           # clicar e sair sem digitar: nada muda
    assert story.document().toPlainText() == before
    _type(ed, qapp, "Oi")
    c = story.textCursor()
    rect = story.document().documentLayout().blockBoundingRect(c.block())
    assert c.block().text() == "Oi"
    assert abs(rect.center().y() - 500) < 20                     # na altura do clique
    assert abs(m["left"] + c.blockFormat().leftMargin() - 250) < 1   # e no ponto do clique
    ed.undo()
    assert story.document().toPlainText() == before            # um passo desfaz tudo
    # clique fora das margens: vai para o ponto mais próximo dentro delas
    _click(ed, qapp, QPointF(8, 600))
    assert story.pending is not None and abs(story.pending.x() - m["left"]) < 1
    # caixa de texto: um clique já edita
    ed.insert_text_box()
    pump(qapp, 20)
    box = [it for it in sc.items_by_id.values() if it.kind == "text"][0]
    _type(ed, qapp, "caixa")
    ed.stop_all_editing()
    sc.clearSelection()
    _click(ed, qapp, box.text.mapToScene(QPointF(14, 10)))
    assert box.editing



def _answers(ed):
    return [it for it in ed.scene.items_by_id.values() if it.data_state.get("equationOf")]


def test_answer_sits_on_the_baseline_and_can_be_erased(window, qapp, monkeypatch):
    import handwriting
    monkeypatch.setattr(handwriting, "RUN_IN_THREAD", False)
    monkeypatch.setattr(handwriting, "available", lambda: False)
    ed = open_new(window, qapp)
    ed.doc["canvas"]["solveEquations"] = True
    _write(ed, "12+7=", y=300, size=34)
    ed.ink_timer.stop()
    ed._ink_pause()
    (ans,) = _answers(ed)
    line = ans.text.document().firstBlock().layout().lineAt(0)
    base = ans.mapToScene(ans.text.pos() + QPointF(0, line.y() + line.ascent())).y()
    assert abs(base - 334) < 1.5                       # algarismos vão de y=300 a 334
    ed.scene.begin_change()
    r = ans.sceneBoundingRect()
    ed.erase_at(QPointF(r.center().x(), 320))
    ed.scene.end_change("Apagar")
    assert not _answers(ed)


def test_partial_eraser_cuts_only_where_it_passes(window, qapp):
    ed = open_new(window, qapp)
    ed.doc["canvas"]["recognizeDiagrams"] = False
    ed.finish_stroke(0, "pen", [(100.0, 500.0, 0.5), (400.0, 500.0, 0.5)])
    ed.eraser_whole = False
    ed.scene.begin_change()
    ed.erase_at(QPointF(250, 500))
    ed.scene.end_change("Apagar")
    pieces = sorted(st.data_state["points"][0][0] for st in ed.scene.strokes_by_id.values())
    assert len(pieces) == 2 and pieces[0] == 100.0
    # linha reconhecida (forma perfeita) também é cortada, não some inteira
    ed.doc["canvas"]["recognizeDiagrams"] = True
    ed.finish_stroke(0, "pen", [(100.0 + i * 10, 650.0, 0.5) for i in range(31)])
    lines = [it for it in ed.scene.items_by_id.values() if it.kind == "line"]
    assert len(lines) == 1
    ed.scene.begin_change()
    ed.erase_at(QPointF(250, 650))
    ed.scene.end_change("Apagar")
    assert len([it for it in ed.scene.items_by_id.values() if it.kind == "line"]) == 2


def _grid_note(window, qapp):
    import model
    ed = open_new(window, qapp)
    with ed.scene.change("Papel"):
        ed.doc["canvas"]["paper"] = {"kind": "grid", "spacing": model.CM}
        ed.scene.apply_page_format()
    return ed, ed.scene.grid_at(0, 400)[0]


def test_grid_paper_handwriting_one_symbol_per_square(window, qapp, monkeypatch):
    import handwriting
    monkeypatch.setattr(handwriting, "RUN_IN_THREAD", False)
    monkeypatch.setattr(handwriting, "available", lambda: False)
    ed, cell = _grid_note(window, qapp)
    ed.doc["canvas"]["solveEquations"] = True
    _write(ed, "12+7=", x=5 * cell, y=20 * cell, cell=cell)
    ed.ink_timer.stop()
    ed._ink_pause()
    (ans,) = _answers(ed)
    st = ans.state()
    assert st["kind"] == "cells" and st["answer"] == "19"
    assert abs(st["frame"]["x"] - 10 * cell) < 0.5 and abs(st["frame"]["y"] - 20 * cell) < 0.5   # quadrado depois do "="


def test_grid_paper_typing_square_by_square(window, qapp):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    window.resize(1300, 900)
    window.show()
    pump(qapp, 50)
    ed, cell = _grid_note(window, qapp)
    ed.set_tool("select")
    sc = ed.scene
    before = ed.history.index
    _click(ed, qapp, QPointF(3.5 * cell, 18.5 * cell))          # clique de verdade num quadrado qualquer
    item = [it for it in sc.items_by_id.values() if it.kind == "cells"][0]
    assert item.editing
    _type(ed, qapp, "3.4=")
    st = item.state()
    assert st["text"] == "3.4=" and st["answer"] == "12"
    assert abs(st["frame"]["x"] - 3 * cell) < 0.5 and abs(st["frame"]["y"] - 18 * cell) < 0.5
    assert item.chars()[4] == ("1", True)                # o 12 começa no quadrado seguinte ao "="
    item.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert not item.editing and ed.history.index == before + 1
    _click(ed, qapp, QPointF(4.5 * cell, 18.5 * cell))          # clicar na conta volta a editar nela
    assert item.editing and item.cursor == 1
    ed.stop_all_editing()
    ed.undo()
    assert not [it for it in sc.items_by_id.values() if it.kind == "cells"]
    _click(ed, qapp, QPointF(3.5 * cell, 25.5 * cell))          # clica e sai sem digitar: não sobra nada
    ed.stop_all_editing()
    assert not [it for it in sc.items_by_id.values() if it.kind == "cells"] and ed.history.index == before


def test_page_numbers_dialog_starts_checked(window, qapp):
    import dialogs
    ed = open_new(window, qapp)
    dlg = dialogs.HeaderFooterDialog(ed.doc["canvas"], ed._pick_band_image, 2, ed)
    assert dlg.numbered.isChecked()
    assert dlg.result_canvas(ed.doc["canvas"])["pageNumbers"]["format"] == "n"


def test_recent_notes_include_folders(window, qapp):
    import sidebar
    a = window.store.create(__import__("model").new_document("Dentro da pasta"))["id"]
    f = window.store.create_folder("Clientes", None)
    window.store.move_note(a, f.id)
    window.sidebar.folder_id = None
    window.sidebar.refresh()
    cards = window.sidebar.findChildren(sidebar.NoteCard)
    mine = [c for c in cards if c.info.id == a]
    assert mine and mine[0].folder == "Clientes"


def test_auto_lists_and_renumbering(window, qapp):
    window.resize(1300, 900)
    window.show()
    pump(qapp, 50)
    ed = open_new(window, qapp)
    story = ed.scene.story
    ed.scene.setFocusItem(story)
    story.cursor_to_end()
    from PySide6.QtTest import QTest
    QTest.keyClicks(ed.view.viewport(), "1. um")
    pump(qapp, 10)
    c = story.textCursor()
    lst = c.currentList()
    assert lst is not None and c.block().text() == "um"
    for word in ("dois", "tres"):
        QTest.keyClick(ed.view.viewport(), Qt.Key.Key_Return)
        QTest.keyClicks(ed.view.viewport(), word)
    pump(qapp, 10)
    doc = story.document()
    dois = doc.findBlockByNumber(doc.blockCount() - 2)
    assert dois.text() == "dois" and lst.itemNumber(dois) == 1
    # tira o "dois" da lista (Backspace no começo): o "tres" vira o 2º, o texto fica
    c = QTextCursor(dois)
    story.setTextCursor(c)
    QTest.keyClick(ed.view.viewport(), Qt.Key.Key_Backspace)
    tres = doc.lastBlock()
    assert dois.textList() is None and dois.text() == "dois"
    assert tres.textList() is lst and lst.itemNumber(tres) == 1 and lst.itemText(tres).startswith("2")
    # "- " vira marcador; Ctrl+Z volta ao texto "- "
    story.cursor_to_end()
    QTest.keyClick(ed.view.viewport(), Qt.Key.Key_Return)
    QTest.keyClick(ed.view.viewport(), Qt.Key.Key_Return)
    QTest.keyClicks(ed.view.viewport(), "- ")
    pump(qapp, 10)
    assert story.textCursor().currentList() is not None
    ed.undo()
    assert story.textCursor().currentList() is None and story.textCursor().block().text() == "- "


def test_keep_with_next_moves_heading_down(window, qapp):
    import textfmt
    ed = open_new(window, qapp)
    story = ed.scene.story
    doc = story.document()
    layout = doc.documentLayout()
    page_h = ed.scene.page_h
    page = lambda b: int((layout.blockBoundingRect(b).top() + 1) // page_h)
    # linhas até o título cair sozinho no pé da 1ª página
    for k in range(10, 200):
        c = QTextCursor(doc)
        c.select(QTextCursor.SelectionType.Document)
        c.insertText("\n".join(f"linha {i}" for i in range(k)) + "\nTítulo\nParágrafo do título")
        title = doc.lastBlock().previous()
        if page(title) == 0 and page(title.next()) == 1:
            break
    else:
        raise AssertionError("título não ficou sozinho no pé")
    story.setTextCursor(QTextCursor(title))
    ed.scene.setFocusItem(story)
    ed.set_keep_with_next(True)
    assert page(title) == page(title.next()) == 1
    assert textfmt.state_bits(title) & textfmt.AUTO_BREAK
    html = doc.toHtml()
    assert "-qt-user-state" in html                                 # vai junto ao gravar


def test_signature_line(window, qapp, monkeypatch):
    import dialogs
    ed = open_new(window, qapp)
    story = ed.scene.story
    ed.scene.setFocusItem(story)
    story.cursor_to_end()

    class Fake:
        def __init__(self, *a, **k): pass
        def exec(self): return 1
        def values(self): return "Fulana de Tal", "OAB/SP 000.000", "São Paulo, 1 de dezembro de 2026."
    monkeypatch.setattr(dialogs, "SignatureDialog", Fake)
    ed.insert_signature()
    text = story.document().toPlainText()
    assert "Fulana de Tal" in text and "OAB/SP 000.000" in text and "_____" in text
    block = story.document().findBlockByNumber(story.document().blockCount() - 2)
    assert block.text() == "Fulana de Tal" and block.blockFormat().alignment() & Qt.AlignmentFlag.AlignHCenter


def test_line_spacing_and_dashed_line(window, qapp):
    ed = open_new(window, qapp)
    story = ed.scene.story
    ed.scene.setFocusItem(story)
    ed.fmt("spacing3", (1.5, 0.0, 8.0))
    assert ed.current_spacing() == (1.5, 0.0, 8.0)
    ed.finish_shape_drag("dashed", QPointF(100, 300), QPointF(300, 300))
    line = [it for it in ed.scene.items_by_id.values() if it.kind == "line"][0]
    assert line.data_state.get("lineDash") == "dashed"


def test_abnt_citation_and_references(window, qapp):
    import abnt
    ed = open_new(window, qapp)
    story = ed.scene.story
    doc = story.document()
    c = QTextCursor(doc)
    c.insertText("Como ensina a doutrina, o dano moral dispensa prova do prejuízo. Isso é pacífico.")
    start = doc.toPlainText().index("o dano")
    c.setPosition(start)
    c.setPosition(doc.toPlainText().index(" Isso"), QTextCursor.MoveMode.KeepAnchor)
    story.setTextCursor(c)
    ed.scene.setFocusItem(story)
    livro = {"tipo": "livro", "autores": ["Carlos Roberto Gonçalves"], "titulo": "Direito civil brasileiro",
             "subtitulo": "responsabilidade civil", "edicao": "15", "local": "São Paulo", "editora": "Saraiva Jur", "ano": "2020"}
    ed.apply_abnt(story, livro, "direta", "12")
    text = doc.toPlainText()
    assert "“o dano moral dispensa prova do prejuízo” (Gonçalves, 2020, p. 12)." in text
    assert "REFERÊNCIAS" in text
    assert "GONÇALVES, Carlos Roberto. Direito civil brasileiro: responsabilidade civil. 15. ed. São Paulo: Saraiva Jur, 2020." in text
    # 2ª fonte: entra em ordem alfabética (Brasil antes de Gonçalves)
    c = QTextCursor(doc)
    c.setPosition(doc.toPlainText().index("Isso é pacífico"))
    c.setPosition(doc.toPlainText().index("Isso é pacífico") + len("Isso é pacífico."), QTextCursor.MoveMode.KeepAnchor)
    story.setTextCursor(c)
    lei = {"tipo": "lei", "jurisdicao": "BRASIL", "especie": "Lei", "numero": "10.406", "data": "10 de janeiro de 2002",
           "ementa": "Institui o Código Civil", "publicacao": "Diário Oficial da União", "data_pub": "11 jan. 2002"}
    ed.apply_abnt(story, lei, "indireta", "")
    text = doc.toPlainText()
    assert "Isso é pacífico (Brasil, 2002)." in text
    refs = text.split("REFERÊNCIAS", 1)[1]
    assert refs.index("BRASIL. Lei nº 10.406") < refs.index("GONÇALVES, Carlos")
    # negrito só no título da obra
    b = doc.lastBlock()
    assert b.text().startswith("GONÇALVES")
    it = b.begin()
    bolds = []
    while not it.atEnd():
        f = it.fragment()
        if f.charFormat().fontWeight() >= 700:
            bolds.append(f.text())
        it += 1
    assert bolds == ["Direito civil brasileiro"]
    # um passo de desfazer tira a 2ª citação e a referência dela
    ed.undo()
    assert "(Brasil, 2002)" not in doc.toPlainText() and "BRASIL. Lei" not in doc.toPlainText()
    # citação longa: parágrafo próprio com recuo de 4 cm e 10 pt
    ed.redo()
    c = QTextCursor(doc)
    c.movePosition(QTextCursor.MoveOperation.Start)
    c.insertText("Texto. " + "Palavra longa de citação direta " * 12 + "fim.")
    c.insertBlock()
    c.setPosition(len("Texto. "))
    c.setPosition(len("Texto. ") + len("Palavra longa de citação direta " * 12 + "fim."), QTextCursor.MoveMode.KeepAnchor)
    story.setTextCursor(c)
    ed.apply_abnt(story, livro, "direta", "30")
    quote = doc.findBlockByNumber(1)
    assert quote.text().endswith("(Gonçalves, 2020, p. 30).") and not quote.text().startswith("“")
    assert abs(quote.blockFormat().leftMargin() - abnt.LONG_INDENT) < 0.5
    assert QTextCursor(quote).charFormat().fontPointSize() in (0, 10) or quote.begin().fragment().charFormat().fontPointSize() == 10
    assert doc.toPlainText().count("GONÇALVES, Carlos") == 1          # a mesma fonte não repete


def test_proofread_highlights_and_fixes(window, qapp, monkeypatch):
    import proofread
    ed = open_new(window, qapp)
    story = ed.scene.story
    doc = story.document()
    QTextCursor(doc).insertText("Os cliente chegou na audiencia. Houveram problemas.")

    class FakeWorker(proofread.Worker):
        def start(self):
            answer = ('[{"trecho": "Os cliente", "correcao": "O cliente", "motivo": "concordância"},'
                      ' {"trecho": "audiencia", "correcao": "audiência", "motivo": "acento"},'
                      ' {"trecho": "não existe", "correcao": "x"}, {"trecho": "chegou", "correcao": "chegou"}]')
            for i, t in enumerate(self.texts):
                self.found.emit(i, proofread.parse(answer, t))
            self.finished.emit()
    monkeypatch.setattr(proofread, "Worker", FakeWorker)
    panel = proofread.ProofPanel(ed, story)
    panel.start()
    assert len(panel.live()) == 2 and story.issues                      # inválidas ficaram de fora
    assert "corrija tudo" in panel.ask.text()
    story.update()
    pump(qapp, 10)
    panel.show_issue(panel._next(-1))                                  # um por um
    panel.skip_current()
    panel.fix_current()
    assert doc.toPlainText() == "Os cliente chegou na audiência. Houveram problemas."
    ed.undo()
    assert "audiencia" in doc.toPlainText()
    # corrigir tudo: um passo de desfazer
    panel2 = proofread.ProofPanel(ed, story)
    panel2.start()
    panel2.fix_all()
    assert doc.toPlainText() == "O cliente chegou na audiência. Houveram problemas."
    ed.undo()
    assert doc.toPlainText() == "Os cliente chegou na audiencia. Houveram problemas."
    panel.close()
    panel2.close()
