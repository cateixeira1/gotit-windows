"""Biblioteca de demonstração (para capturas de tela no CI e testes manuais)."""

from __future__ import annotations

import io
import math
import shutil
import struct
import wave
from datetime import date
from pathlib import Path

import model

STORY = """
<h1 style="font-size:24pt">Plano do lançamento</h1>
<p>Objetivo: deixar o <b>Got It!</b> pronto para o <span style="background-color:#FFF07A">teste com 10 pessoas</span> até sexta.</p>
<ul>
<li>Revisar o texto da tela inicial</li>
<li>Gravar o áudio de boas-vindas</li>
<li><i>Conferir a impressão em A4</i></li>
</ul>
<p>Pendências: falar com a equipe de design sobre o ícone e o post-it amarelo.</p>
<p style="text-align:justify">O canvas mistura texto como no Word, objetos soltos, tinta com pressão da caneta e mídias. Tudo fica no computador.</p>
"""


def _png(width: int, height: int) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, width, height)
    g.setColorAt(0, QColor("#2E6474"))
    g.setColorAt(1, QColor("#7FB3C2"))
    p.fillRect(img.rect(), g)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#F1BE5D"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(width * 0.62, height * 0.18, height * 0.42, height * 0.42))
    p.setBrush(QColor(255, 255, 255, 70))
    for i in range(5):
        p.drawEllipse(QRectF(40 + i * 120, height * 0.7, 160, 70))
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba.data())


def _wav(seconds: float = 3.0) -> bytes:
    rate = 16000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * t / rate) * (1 - t / (rate * seconds))))
                          for t in range(int(rate * seconds)))
        w.writeframes(frames)
    return buf.getvalue()


def _stroke(page_id, pts, color="#2563EB", width=2.4, tool="pen"):
    return {"id": model.new_id(), "pageID": page_id, "tool": tool, "color": color, "width": width,
            "points": [[round(x, 2), round(y, 2), round(p, 3)] for x, y, p in pts]}


def build(folder: Path, keep: bool = False) -> Path:
    from store import Store
    folder = Path(folder)
    if folder.exists() and not keep:
        shutil.rmtree(folder)
    if keep and (folder / "gotit.sqlite").exists():
        return folder
    store = Store(folder)
    work = store.create_folder("Trabalho")

    doc = model.new_document("Plano do lançamento")
    pid = doc["pages"][0]["id"]
    from PySide6.QtGui import QTextDocument
    plain = QTextDocument()
    plain.setHtml(STORY)
    doc["story"] = {"html": STORY, "text": plain.toPlainText()}
    img = store.import_bytes(_png(640, 400), ".png")
    audio = store.import_bytes(_wav(), ".wav")
    rect_id, ell_id = model.new_id(), model.new_id()
    doc["blocks"] = [
        {"id": model.new_id(), "kind": "sticky", "pageID": pid, "frame": {"x": 330, "y": 468, "width": 180, "height": 180},
         "fill": "#FFF27A", "text": "Ligar para a gráfica às 15h!", "html": "", "foreground": "#2B2B2B", "rotation": -3, "z": 5},
        {"id": model.new_id(), "kind": "calendar", "pageID": pid, "frame": {"x": 85, "y": 470, "width": 112, "height": 126},
         "date": date.today().isoformat(), "z": 4},
        {"id": model.new_id(), "kind": "sticker", "pageID": pid, "frame": {"x": 224, "y": 492, "width": 72, "height": 72},
         "emoji": "⭐", "z": 6},
        {"id": rect_id, "kind": "shape", "shape": "rectangle", "pageID": pid,
         "frame": {"x": 95, "y": 680, "width": 150, "height": 64}, "stroke": "#2F6FB5", "fill": "#E8F0FB", "lineWidth": 2,
         "text": "Ideia", "html": "", "z": 7},
        {"id": ell_id, "kind": "shape", "shape": "ellipse", "pageID": pid,
         "frame": {"x": 340, "y": 680, "width": 160, "height": 70}, "stroke": "#16A34A", "fill": "#ECFDF3", "lineWidth": 2,
         "text": "Protótipo", "html": "", "z": 8},
        {"id": model.new_id(), "kind": "image", "pageID": doc["pages"][0]["id"],
         "frame": {"x": 85, "y": 72, "width": 300, "height": 188}, "asset": img, "caption": "Paisagem", "z": 2},
        {"id": model.new_id(), "kind": "audio", "pageID": doc["pages"][0]["id"],
         "frame": {"x": 85, "y": 290, "width": 300, "height": 60}, "asset": audio, "caption": "Boas-vindas", "duration": 3.0, "z": 3},
        {"id": model.new_id(), "kind": "table", "pageID": doc["pages"][0]["id"], "frame": {"x": 85, "y": 380, "width": 425, "height": 96},
         "rows": 3, "columns": 3, "header": True, "text": "", "html": "", "fontSize": 11, "z": 1},
    ]
    second = model.new_page()
    doc["pages"].append(second)
    for b in doc["blocks"][5:]:
        b["pageID"] = second["id"]
    doc["relations"] = [{"id": model.new_id(), "sourceID": rect_id, "targetID": ell_id, "kind": "connector",
                         "style": {"color": "#334155", "width": 2, "arrowAtEnd": True, "routing": "straight"}}]
    wave_pts = [(90 + i * 4, 452 + 5 * math.sin(i / 3.0), 0.35 + 0.5 * abs(math.sin(i / 9))) for i in range(60)]
    circle = [(470 + 30 * math.cos(t / 20 * math.pi), 215 + 18 * math.sin(t / 20 * math.pi), 0.6) for t in range(42)]
    doc["strokes"] = [_stroke(pid, wave_pts, "#DC2626", 2.6), _stroke(pid, circle, "#2563EB", 2.2),
                      _stroke(pid, [(110 + i * 6, 162, 0.5) for i in range(40)], "#F1BE5D", 14, "marker")]
    doc["canvas"]["header"] = {"text": "Color Software · Got It!", "alignment": "trailing", "height": 30, "fontSize": 9}
    doc["canvas"]["pageNumbers"] = {"position": "footer", "alignment": "center", "format": "page_of", "start": 1,
                                    "skipFirst": False, "size": 10}
    store.create(doc)
    main_id = doc["id"]

    ruled = model.new_document("Aula de Direito Civil")
    ruled["canvas"]["paper"] = {"kind": "ruled", "spacing": model.RULED_LINE}
    ruled["story"] = {"html": "", "text": "Responsabilidade civil\nElementos: conduta, dano, nexo causal e culpa.\n"
                                          "Art. 186 e 927 do Código Civil.\nPrazo prescricional: 3 anos."}
    store.create(ruled, work.id)

    simple = model.new_document("Lista de compras", simple=True)
    simple["story"] = {"html": "", "text": "Café\nPão de queijo\nPapel A4\nPost-its amarelos"}
    store.create(simple)

    grid = model.new_document("Rascunho do diagrama")
    grid["canvas"]["paper"] = {"kind": "grid", "spacing": 0.5 * model.CM}
    gp = grid["pages"][0]["id"]
    a, b, c = model.new_id(), model.new_id(), model.new_id()
    grid["blocks"] = [
        {"id": a, "kind": "shape", "shape": "rectangle", "pageID": gp, "frame": {"x": 120, "y": 140, "width": 140, "height": 70},
         "stroke": "#1F2933", "fill": "#FFF27A", "lineWidth": 2, "text": "Início", "html": "", "z": 1},
        {"id": b, "kind": "shape", "shape": "diamond", "pageID": gp, "frame": {"x": 330, "y": 130, "width": 140, "height": 90},
         "stroke": "#1F2933", "fill": "#A9DDF7", "lineWidth": 2, "text": "Decisão", "html": "", "z": 2},
        {"id": c, "kind": "shape", "shape": "triangle", "pageID": gp, "frame": {"x": 340, "y": 300, "width": 120, "height": 100},
         "stroke": "#1F2933", "fill": "#C6EBA1", "lineWidth": 2, "text": "Fim", "html": "", "z": 3},
    ]
    grid["relations"] = [
        {"id": model.new_id(), "sourceID": a, "targetID": b, "kind": "connector", "style": {"color": "#334155", "width": 2, "arrowAtEnd": True}},
        {"id": model.new_id(), "sourceID": b, "targetID": c, "kind": "connector", "style": {"color": "#DC2626", "width": 2, "arrowAtEnd": True}},
    ]
    store.create(grid)

    for i in range(4):
        n = model.new_document(f"Nota {i + 5}")
        n["story"] = {"html": "", "text": f"Ideias soltas número {i + 1}.\nReunião na segunda."}
        store.create(n)

    teia = model.new_document("Teia do projeto", kind="web")
    tp = teia["pages"][0]["id"]
    cards = []
    for i, (doc_id, x, y) in enumerate(((main_id, 60, 80), (grid["id"], 330, 70), (ruled["id"], 600, 110), (simple["id"], 360, 340))):
        cid = model.new_id()
        cards.append(cid)
        teia["blocks"].append({"id": cid, "kind": "noteRef", "documentID": doc_id, "pageID": tp,
                               "frame": {"x": x, "y": y, "width": 190, "height": 240}, "z": i + 1})
    teia["blocks"].append({"id": model.new_id(), "kind": "sticky", "pageID": tp, "frame": {"x": 80, "y": 360, "width": 170, "height": 150},
                           "fill": "#FFB8D2", "text": "Juntar tudo antes da reunião", "html": "", "foreground": "#2B2B2B", "z": 9})
    teia["relations"] = [{"id": model.new_id(), "sourceID": cards[0], "targetID": cards[3], "kind": "connector",
                          "style": {"color": "#DC2626", "width": 2.5, "arrowAtEnd": True}}]
    store.create(teia)

    trashed = model.new_document("Nota antiga")
    trashed["story"] = {"html": "", "text": "Rascunho que foi para a Lixeira."}
    store.create(trashed)
    store.trash(trashed["id"])
    store.mark_opened(main_id)
    store.close()
    return folder


def show(win, screen: str, shot: str | None) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    win.resize(1440, 920)
    win.show()
    store = win.store
    notes = {n.title: n.id for n in store.notes()}
    dialog = []

    def open_title(t):
        if t in notes:
            win.open_note(notes[t])

    if screen in ("home", "editor", "tools"):
        open_title("Plano do lançamento")
    elif screen == "teia":
        open_title("Teia do projeto")
    elif screen == "simple":
        open_title("Lista de compras")
    elif screen == "ruled":
        open_title("Aula de Direito Civil")
    elif screen == "diagram":
        open_title("Rascunho do diagrama")
    elif screen == "search":
        open_title("Plano do lançamento")
        win.sidebar.search.setText("reuniao")
        win.sidebar.refresh()
    elif screen == "all":
        open_title("Plano do lançamento")
        win.sidebar.browse("note")
    elif screen == "page2":
        open_title("Plano do lançamento")
        QTimer.singleShot(600, lambda: win.editor.scroll_to_page(1))
    elif screen == "empty":
        win.editor.close_document()
        win.stack.setCurrentWidget(win.empty)
    elif screen == "settings":
        import settings_dialog
        d = settings_dialog.SettingsDialog(win)
        d.show()
        dialog.append(d)
    elif screen == "assistant":
        open_title("Plano do lançamento")
        import assistant
        assistant.open_panel(win)
        dialog.append(assistant._panel)
    elif screen == "trash":
        import dialogs
        d = dialogs.TrashDialog(store, win)
        d.show()
        dialog.append(d)

    def grab():
        target = dialog[0] if dialog and dialog[0].isWindow() else win
        pm = target.grab()
        if shot:
            pm.save(shot)
        win.editor.dirty = False
        QApplication.quit()
    QTimer.singleShot(1800, grab)
