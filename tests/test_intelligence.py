"""Inteligência local: equações, recorte do papel, textos do assistente, trechos da busca por
significado e, quando os modelos estão presentes (GOTIT_MODELS), o Gemma e o EmbeddingGemma de verdade."""

import os
import shutil
from pathlib import Path

import numpy as np
import pytest

import assistant
import mathsolve
import model
import models
import semantic

MODELS = Path(os.environ.get("GOTIT_MODELS", "/home/claude/models"))


def test_equations():
    assert mathsolve.answer_text("x^2-5x+6=0") == "x = 2 ou x = 3"
    assert mathsolve.answer_text("2x + 4 = 10") == "x = 3"
    assert mathsolve.answer_text("x²=-1") == "sem solução real"
    assert mathsolve.answer_text("3x=3x") == "todo x real"
    assert mathsolve.answer_text("0,5x=2") == "x = 4"
    assert mathsolve.answer_text("x+y=1") is None          # duas incógnitas: não inventa resposta
    assert mathsolve.answer_text("x^3=8") is None           # só até o 2º grau
    assert mathsolve.answer_text("olá") is None


def test_paper_mask_keeps_ink_and_drops_paper():
    import cutout
    img = np.full((120, 200, 4), 245, np.uint8)
    img[..., 3] = 255
    img[:, :100, :3] -= 30                                   # metade do papel mais escura (sombra)
    img[50:70, 20:180, :3] = 20                              # traço de tinta
    alpha = cutout.paper_mask(img, 0.5)
    assert alpha[60, 100] > 200
    assert alpha[10, 50] == 0 and alpha[10, 150] == 0


def test_note_text_order_and_cut():
    doc = model.new_document("Plano")
    pid = doc["pages"][0]["id"]
    doc["story"] = {"html": "", "text": "Texto principal."}
    doc["blocks"] = [{"id": "b", "kind": "sticky", "pageID": pid, "frame": {"x": 10, "y": 500}, "text": "Post-it de baixo"},
                     {"id": "a", "kind": "text", "pageID": pid, "frame": {"x": 10, "y": 100}, "text": "Caixa de cima"}]
    text, cut = assistant.note_text(doc)
    assert text.index("Texto principal") < text.index("Caixa de cima") < text.index("Post-it de baixo")
    assert not cut
    long_text, cut = assistant.note_text({**doc, "blocks": [], "story": {"text": "Frase. " * 3000}}, 100)
    assert cut and len(long_text) <= 100 and long_text.endswith(".")


def test_summary_plan_and_trim():
    plan = assistant.SummaryPlan(300)
    assert plan.max_words == 60 and plan.topics == 3
    answer = "Aqui está:\n- um\n- dois\n- três\n- quatro\n\nPendências:\n- ligar"
    trimmed = assistant.trimmed_summary(answer, plan)
    assert "quatro" not in trimmed and "Pendências" in trimmed and "Aqui está" not in trimmed


def test_citations_and_proposal_validation():
    assert assistant.citations("Vence em março [2]. Também [1, 3] e [9].", 3) == [2, 1, 3]
    folders = {"f1": "Trabalho", "f2": "Casa"}
    note = "Ligar para o cliente amanhã e enviar o contrato até sexta"
    prop = assistant.parse_proposal("Título: Contrato do cliente\nPasta: Trabalho\nPendências:\n- Ligar para o cliente\n"
                                    "- Comprar um carro\n- Enviar o contrato", "Nota 1", folders, None, note)
    assert prop["title"] == "Contrato do cliente" and prop["folder"] == "f1"
    assert prop["tasks"] == ["Ligar para o cliente", "Enviar o contrato"]   # tarefa sem palavra da nota sai


def test_chunks():
    parts = semantic.chunks("a" * 50 + "\n" + ("Frase longa. " * 150))
    assert all(len(p) <= semantic.CHUNK for p in parts) and len(parts) >= 2


def _install(window, spec, files):
    d = models.folder(window.store.data_dir, spec)
    for f in files:
        os.symlink(MODELS / f, d / f)
    models.ready_marker(window.store.data_dir, spec).write_text("ok")


@pytest.mark.skipif(not (MODELS / "embeddinggemma-2-text-270m.litertlm").exists(), reason="modelo ausente")
def test_semantic_search_real_model(window, qapp):
    pytest.importorskip("litert_lm")
    _install(window, models.SEMANTIC, ["embeddinggemma-2-text-270m.litertlm"])
    window.settings.setValue("semanticSearch", "true")
    for title, text in (("Contrato", "O contrato de locação do apartamento vence em 15 de março de 2027."),
                        ("Receita", "Bolo de cenoura com cobertura de chocolate, forno a 180 graus."),
                        ("Hospital", "Exame de sangue marcado no hospital na segunda às 8h.")):
        d = model.new_document(title)
        d["story"] = {"html": "", "text": text}
        window.store.create(d)
    idx = semantic.index(window)
    for info in window.store.notes():
        idx._index(info.id)
    idx._matrix = None
    hits = semantic.search(window, "quando termina o aluguel", set())
    assert hits and hits[0].title == "Contrato"
    semantic.shutdown()


@pytest.mark.skipif(not (MODELS / "gemma-4-E2B-it.litertlm").exists(), reason="modelo ausente")
def test_assistant_answers_with_citation(window, qapp):
    pytest.importorskip("litert_lm")
    _install(window, models.ASSISTANT, ["gemma-4-E2B-it.litertlm"])
    sources = [{"doc_id": "1", "part": "story", "title": "Receita", "text": "Bolo de cenoura com cobertura de chocolate."},
               {"doc_id": "2", "part": "story", "title": "Contrato",
                "text": "O contrato de locação do apartamento da Rua Augusta vence em 15 de março de 2027."}]
    runner = assistant.Runner(window, assistant.question_prompt("Quando vence o contrato do apartamento?", sources), 120)
    got = {}
    runner.done.connect(lambda t: got.setdefault("text", t))
    runner.failed.connect(lambda t: got.setdefault("error", t))
    runner._run()
    assert "error" not in got, got
    assert "2027" in got["text"] and 2 in assistant.citations(got["text"], 2)
    assistant.release()


@pytest.mark.skipif(not (MODELS / "whisper" / "model.bin").exists(), reason="modelo ausente")
def test_transcription_real_model(window, qapp, tmp_path):
    pytest.importorskip("faster_whisper")
    import speech
    d = models.folder(window.store.data_dir, models.SPEECH)
    for f in ("config.json", "tokenizer.json", "vocabulary.txt", "model.bin"):
        os.symlink(MODELS / "whisper" / f, d / f)
    models.ready_marker(window.store.data_dir, models.SPEECH).write_text("ok")
    sample = Path(os.environ.get("GOTIT_AUDIO_SAMPLE", "/tmp/fw/tests/data/jfk.flac"))
    if not sample.exists():
        pytest.skip("sem áudio de exemplo")
    job = speech.Job(window, sample, "en")
    got = {}
    job.done.connect(lambda t: got.setdefault("text", t))
    job.failed.connect(lambda t: got.setdefault("error", t))
    job._run()
    assert "error" not in got, got
    assert "country" in got["text"].lower()
    speech.shutdown()
