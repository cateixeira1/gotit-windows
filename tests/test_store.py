"""Biblioteca: notas, pastas, Lixeira, busca sem acentos, ligações, cópia de segurança."""

import json

import model
from store import Store


def make(store, title, text="", kind="note", folder=None):
    doc = model.new_document(title, kind=kind)
    doc["story"] = {"html": "", "text": text}
    return store.create(doc, folder)


def test_create_load_save_revision(tmp_path):
    s = Store(tmp_path)
    doc = make(s, "Contrato", "Vence em março")
    loaded = s.load(doc["id"])
    assert loaded["title"] == "Contrato" and loaded["revision"] == 0
    loaded["title"] = "Contrato de aluguel"
    saved = s.save(loaded)
    assert saved["revision"] == 1
    assert s.info(doc["id"]).title == "Contrato de aluguel"


def test_search_ignores_accents_and_case_and_prefixes(tmp_path):
    s = Store(tmp_path)
    make(s, "Processo", "Pedido de indenização por danos morais")
    make(s, "Receita", "Bolo de cenoura com cobertura")
    assert [h.title for h in s.search("INDENIZACAO")] == ["Processo"]
    assert [h.title for h in s.search("indeniz danos")] == ["Processo"]
    assert s.search("proc")[0].title == "Processo"          # título também entra
    assert s.search("bolo indenizacao") == []                 # cada palavra precisa aparecer
    hit = s.search("cenoura")[0]
    assert "[[cenoura]]" in hit.snippet


def test_search_excludes_trash_and_blocks_are_indexed(tmp_path):
    s = Store(tmp_path)
    doc = make(s, "Reunião", "")
    doc["blocks"] = [{"id": model.new_id(), "kind": "sticky", "text": "ligar para a gráfica", "frame": {}}]
    s.save(doc)
    assert s.search("grafica")
    s.trash(doc["id"])
    assert s.search("grafica") == []
    s.restore(doc["id"])
    assert s.search("grafica")


def test_folders_generic_name_and_merge(tmp_path):
    s = Store(tmp_path)
    a, b = make(s, "A"), make(s, "B")
    assert s.generic_folder_name() == "Pasta 1"
    s.create_folder("Pasta 7")
    assert s.generic_folder_name() == "Pasta 8"              # maior número + 1, sem preencher lacunas
    f = s.create_folder(s.generic_folder_name(), containing=[a["id"], b["id"]])
    assert {n.id for n in s.notes(folder_id=f.id)} == {a["id"], b["id"]}
    sub = s.create_folder("Sub", f.id)
    assert not s.move_folder(f.id, sub.id)                   # não vai para dentro de uma subpasta
    s.delete_folder(f.id)                                     # notas sobem para a pasta de cima
    assert {n.id for n in s.notes(folder_id=None)} >= {a["id"], b["id"]}
    assert s.folder(sub.id).parent_id is None


def test_trash_order_and_delete_forever(tmp_path):
    s = Store(tmp_path)
    a, b = make(s, "A"), make(s, "B")
    s.trash(a["id"])
    s.trash(b["id"])
    assert [n.title for n in s.notes(trashed=True)] == ["B", "A"]
    s.delete_forever(a["id"])
    assert s.load(a["id"]) is None
    assert s.empty_trash() == 1
    assert s.notes(trashed=True) == []


def test_links_cited_by(tmp_path):
    s = Store(tmp_path)
    target = make(s, "Alvo")
    src = make(s, "Origem")
    src["story"] = {"html": f'<a href="gotit://nota/{target["id"]}">Alvo</a>', "text": "Alvo"}
    s.save(src)
    assert [n.title for n in s.cited_by(target["id"])] == ["Origem"]


def test_assets_by_hash_and_garbage(tmp_path):
    s = Store(tmp_path)
    digest = s.import_bytes(b"conteudo", ".bin")
    assert s.import_bytes(b"conteudo", ".bin") == digest
    assert s.asset_path(digest).read_bytes() == b"conteudo"
    assert s.collect_garbage(min_age_seconds=0) == 1
    assert s.asset_path(digest) is None


def test_backup_and_restore_without_duplicates(tmp_path):
    s = Store(tmp_path / "a")
    make(s, "Uma", "texto")
    dest = s.backup_to(tmp_path / "bk")
    other = Store(tmp_path / "b")
    assert other.restore_from(dest) == 1
    assert other.restore_from(dest) == 0
    assert other.search("texto")


def test_model_first_free_spot_skips_occupied():
    doc = model.new_document("x")
    pid = doc["pages"][0]["id"]
    m = model.text_margins(doc)
    x, y = model.first_free_spot(doc, pid, 100, 100)
    assert (round(x), round(y)) == (round(m["left"]), round(m["top"]))
    x2, y2 = model.first_free_spot(doc, pid, 100, 100, occupied=[(x, y, 100, 100)])
    assert (x2, y2) != (x, y)


def test_page_number_formats():
    assert model.page_number_text("page_of", 2, 5) == "Página 2 de 5"
    assert model.page_number_text("dash", 3, 5) == "– 3 –"
    assert model.page_number_text("n", 1, 1) == "1"
