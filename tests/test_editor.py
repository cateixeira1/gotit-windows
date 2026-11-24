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


def _write(ed, text, x=120.0, y=300.0, size=34.0):
    g = _glyphs()
    for ch in text:
        sz = size * 0.7 if ch in "+=" else size
        dy = size * 0.15 if ch in "+=" else 0
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


def test_click_on_page_opens_text_box(window, qapp):
    ed = open_new(window, qapp)
    sc = ed.scene
    before = len(ed.history.entries)
    assert not ed.click_off_story(QPointF(sc._text_margins["left"] + 20, 8))        # 1ª linha: texto da nota
    assert ed.click_off_story(QPointF(300, 500))
    box = [it for it in sc.items_by_id.values() if it.data_state.get("autoBox")][0]
    assert box.editing
    box.stop_editing()                       # vazia: some, sem deixar passo de desfazer
    pump(qapp, 20)
    assert box.block_id not in sc.items_by_id and len(ed.history.entries) == before
    assert ed.click_off_story(QPointF(300, 500))
    box = [it for it in sc.items_by_id.values() if it.data_state.get("autoBox")][0]
    box.text.textCursor().insertText("lembrete")
    box.stop_editing()
    pump(qapp, 20)
    assert box.block_id in sc.items_by_id
    assert ed.click_off_story(QPointF(300, 700)) and box.block_id in sc.items_by_id   # selecionada: só tira a seleção
    assert not [it for it in sc.items_by_id.values() if it.data_state.get("autoBox") and it is not box]
    simple = open_new(window, qapp, simple=True)
    assert not simple.click_off_story(QPointF(300, 500))
