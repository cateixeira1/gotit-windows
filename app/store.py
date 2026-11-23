"""Biblioteca do Got It!: notas e Teias (JSON no SQLite), pastas, Lixeira, busca (FTS5, sem
acentos nem maiúsculas), ligações entre notas e mídias guardadas por SHA-256."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import model

SCHEMA_VERSION = 1
SEARCH_INDEX_VERSION = 1


@dataclass
class NoteInfo:
    id: str
    kind: str
    title: str
    created: str
    updated: str
    revision: int
    folder_id: str | None
    trashed_at: str | None = None

    @property
    def is_web(self) -> bool:
        return self.kind == "web"


@dataclass
class Folder:
    id: str
    parent_id: str | None
    name: str
    created: str


@dataclass
class SearchHit:
    doc_id: str
    title: str
    kind: str
    part: str
    snippet: str
    count: int
    folder_id: str | None


def _row_id(doc_id: str, part: str) -> int:
    """Número fixo de cada trecho no índice (FNV-1a de 63 bits), para trocar ou apagar sem
    varrer o índice inteiro."""
    h = 0xcbf29ce484222325
    for byte in f"{doc_id}/{part}".encode():
        h ^= byte
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h & 0x7FFFFFFFFFFFFFFF or 1


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir = self.data_dir / "assets"
        self.assets_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / "gotit.sqlite"
        self.db = sqlite3.connect(str(self.db_path), isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    # ------------------------------------------------------------------ esquema
    def _migrate(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        # executescript faz o próprio COMMIT: a transação vai dentro do script
        self.db.executescript(f"""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS folders(
                    id TEXT PRIMARY KEY, parent_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
                    name TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL, revision INTEGER NOT NULL,
                    json TEXT NOT NULL, folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
                    trashed_at TEXT, opened_at TEXT);
                CREATE INDEX IF NOT EXISTS documents_folder ON documents(folder_id);
                CREATE TABLE IF NOT EXISTS note_links(
                    source TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    target TEXT NOT NULL, PRIMARY KEY(source, target));
                CREATE INDEX IF NOT EXISTS note_links_target ON note_links(target);
                CREATE TABLE IF NOT EXISTS search_rows(
                    doc_id TEXT NOT NULL, row INTEGER NOT NULL PRIMARY KEY);
                CREATE INDEX IF NOT EXISTS search_rows_doc ON search_rows(doc_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                    doc_id UNINDEXED, part UNINDEXED, title, body,
                    tokenize="unicode61 remove_diacritics 2");
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
                PRAGMA user_version={SCHEMA_VERSION};
                COMMIT;
            """)

    class _Tx:
        def __init__(self, db):
            self.db = db

        def __enter__(self):
            self.db.execute("BEGIN IMMEDIATE")

        def __exit__(self, exc_type, *_):
            self.db.execute("ROLLBACK" if exc_type else "COMMIT")
            return False

    def _tx(self):
        return Store._Tx(self.db)

    def close(self) -> None:
        try:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.db.close()

    # ------------------------------------------------------------------ notas
    def create(self, doc: dict, folder_id: str | None = None) -> dict:
        doc = model.normalize(doc)
        with self._tx():
            self.db.execute(
                "INSERT INTO documents(id, kind, title, created, updated, revision, json, folder_id) VALUES(?,?,?,?,?,?,?,?)",
                (doc["id"], doc["kind"], doc["title"], doc["createdAt"], doc["updatedAt"], doc["revision"],
                 json.dumps(doc, ensure_ascii=False), folder_id))
            self._index(doc)
        return doc

    def load(self, doc_id: str) -> dict | None:
        row = self.db.execute("SELECT json FROM documents WHERE id=?", (doc_id,)).fetchone()
        return model.normalize(json.loads(row["json"])) if row else None

    def save(self, doc: dict, touch: bool = True) -> dict:
        """Grava a nota inteira e atualiza busca e ligações na mesma transação."""
        doc = dict(doc)
        if touch:
            doc["updatedAt"] = model.now_iso()
        doc["revision"] = int(doc.get("revision", 0)) + 1
        payload = json.dumps(doc, ensure_ascii=False)
        with self._tx():
            cur = self.db.execute(
                "UPDATE documents SET kind=?, title=?, updated=?, revision=?, json=? WHERE id=?",
                (doc["kind"], doc["title"], doc["updatedAt"], doc["revision"], payload, doc["id"]))
            if cur.rowcount == 0:
                self.db.execute(
                    "INSERT INTO documents(id, kind, title, created, updated, revision, json) VALUES(?,?,?,?,?,?,?)",
                    (doc["id"], doc["kind"], doc["title"], doc["createdAt"], doc["updatedAt"], doc["revision"], payload))
            self._index(doc)
        return doc

    def rename(self, doc_id: str, title: str) -> None:
        doc = self.load(doc_id)
        if doc:
            doc["title"] = title
            self.save(doc)

    def mark_opened(self, doc_id: str) -> None:
        self.db.execute("UPDATE documents SET opened_at=? WHERE id=?", (model.now_iso(), doc_id))

    def info(self, doc_id: str) -> NoteInfo | None:
        row = self.db.execute(
            "SELECT id, kind, title, created, updated, revision, folder_id, trashed_at FROM documents WHERE id=?",
            (doc_id,)).fetchone()
        return NoteInfo(**dict(row)) if row else None

    def notes(self, kind: str | None = None, folder_id: str | None = "*", trashed: bool = False,
              limit: int | None = None) -> list[NoteInfo]:
        """Mais recentes primeiro (criação ou edição). ``folder_id="*"``: todas as pastas."""
        sql = "SELECT id, kind, title, created, updated, revision, folder_id, trashed_at FROM documents WHERE "
        sql += "trashed_at IS NOT NULL" if trashed else "trashed_at IS NULL"
        args: list = []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if folder_id != "*":
            if folder_id is None:
                sql += " AND folder_id IS NULL"
            else:
                sql += " AND folder_id=?"
                args.append(folder_id)
        sql += " ORDER BY trashed_at DESC, max(updated, created) DESC, rowid DESC" if trashed else \
            " ORDER BY max(updated, created) DESC, rowid DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [NoteInfo(**dict(r)) for r in self.db.execute(sql, args)]

    def last_opened(self) -> str | None:
        row = self.db.execute(
            "SELECT id FROM documents WHERE trashed_at IS NULL AND opened_at IS NOT NULL ORDER BY opened_at DESC LIMIT 1").fetchone()
        return row["id"] if row else None

    # ------------------------------------------------------------------ Lixeira
    def trash(self, doc_id: str) -> None:
        stamp = model.now_iso()
        # dois apagados no mesmo milissegundo não trocam de ordem
        while self.db.execute("SELECT 1 FROM documents WHERE trashed_at=?", (stamp,)).fetchone():
            time.sleep(0.002)
            stamp = model.now_iso()
        self.db.execute("UPDATE documents SET trashed_at=? WHERE id=?", (stamp, doc_id))

    def restore(self, doc_id: str) -> None:
        folder = self.db.execute("SELECT folder_id FROM documents WHERE id=?", (doc_id,)).fetchone()
        exists = folder and folder["folder_id"] and self.folder(folder["folder_id"])
        self.db.execute("UPDATE documents SET trashed_at=NULL, folder_id=? WHERE id=?",
                        (folder["folder_id"] if exists else None, doc_id))

    def delete_forever(self, doc_id: str) -> None:
        with self._tx():
            self._unindex(doc_id)
            self.db.execute("DELETE FROM documents WHERE id=?", (doc_id,))

    def empty_trash(self) -> int:
        ids = [r["id"] for r in self.db.execute("SELECT id FROM documents WHERE trashed_at IS NOT NULL")]
        for doc_id in ids:
            self.delete_forever(doc_id)
        return len(ids)

    # ------------------------------------------------------------------ pastas
    def folders(self, parent_id: str | None = "*") -> list[Folder]:
        if parent_id == "*":
            rows = self.db.execute("SELECT * FROM folders ORDER BY name COLLATE NOCASE")
        elif parent_id is None:
            rows = self.db.execute("SELECT * FROM folders WHERE parent_id IS NULL ORDER BY name COLLATE NOCASE")
        else:
            rows = self.db.execute("SELECT * FROM folders WHERE parent_id=? ORDER BY name COLLATE NOCASE", (parent_id,))
        return [Folder(**dict(r)) for r in rows]

    def folder(self, folder_id: str | None) -> Folder | None:
        if not folder_id:
            return None
        row = self.db.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
        return Folder(**dict(row)) if row else None

    def folder_path(self, folder_id: str | None) -> list[Folder]:
        path, seen = [], set()
        while folder_id and folder_id not in seen:
            seen.add(folder_id)
            f = self.folder(folder_id)
            if not f:
                break
            path.insert(0, f)
            folder_id = f.parent_id
        return path

    def folder_count(self, folder_id: str) -> int:
        notes = self.db.execute("SELECT count(*) FROM documents WHERE folder_id=? AND trashed_at IS NULL", (folder_id,)).fetchone()[0]
        subs = self.db.execute("SELECT count(*) FROM folders WHERE parent_id=?", (folder_id,)).fetchone()[0]
        return notes + subs

    def generic_folder_name(self) -> str:
        return model.generic_folder_name([f.name for f in self.folders("*")])

    def create_folder(self, name: str, parent_id: str | None = None, containing: list[str] | None = None) -> Folder:
        """Cria a pasta e, se pedido, já move as notas para dentro, numa transação só: ou a pasta
        existe com elas dentro, ou nada mudou."""
        folder = Folder(model.new_id(), parent_id, name.strip() or self.generic_folder_name(), model.now_iso())
        with self._tx():
            self.db.execute("INSERT INTO folders(id, parent_id, name, created) VALUES(?,?,?,?)",
                            (folder.id, folder.parent_id, folder.name, folder.created))
            for doc_id in containing or []:
                self.db.execute("UPDATE documents SET folder_id=? WHERE id=?", (folder.id, doc_id))
        return folder

    def rename_folder(self, folder_id: str, name: str) -> None:
        if name.strip():
            self.db.execute("UPDATE folders SET name=? WHERE id=?", (name.strip(), folder_id))

    def delete_folder(self, folder_id: str) -> None:
        """Nunca apaga notas: o conteúdo sobe para a pasta de cima."""
        f = self.folder(folder_id)
        if not f:
            return
        with self._tx():
            self.db.execute("UPDATE documents SET folder_id=? WHERE folder_id=?", (f.parent_id, folder_id))
            self.db.execute("UPDATE folders SET parent_id=? WHERE parent_id=?", (f.parent_id, folder_id))
            self.db.execute("DELETE FROM folders WHERE id=?", (folder_id,))

    def move_note(self, doc_id: str, folder_id: str | None) -> None:
        self.db.execute("UPDATE documents SET folder_id=? WHERE id=?", (folder_id, doc_id))

    def move_folder(self, folder_id: str, parent_id: str | None) -> bool:
        """Uma pasta não vai para dentro dela mesma nem de uma subpasta."""
        if parent_id and (parent_id == folder_id or any(f.id == folder_id for f in self.folder_path(parent_id))):
            return False
        self.db.execute("UPDATE folders SET parent_id=? WHERE id=?", (parent_id, folder_id))
        return True

    # ------------------------------------------------------------------ busca
    def _unindex(self, doc_id: str) -> None:
        rows = [r["row"] for r in self.db.execute("SELECT row FROM search_rows WHERE doc_id=?", (doc_id,))]
        for row in rows:
            self.db.execute("DELETE FROM search WHERE rowid=?", (row,))
        self.db.execute("DELETE FROM search_rows WHERE doc_id=?", (doc_id,))
        self.db.execute("DELETE FROM note_links WHERE source=?", (doc_id,))

    def _index(self, doc: dict) -> None:
        self._unindex(doc["id"])
        parts = model.collect_text(doc) or [("story", "")]
        title = doc.get("title") or ""
        for i, (part, text) in enumerate(parts):
            row = _row_id(doc["id"], part if part != "story" else "story")
            if self.db.execute("SELECT 1 FROM search_rows WHERE row=?", (row,)).fetchone():
                row = _row_id(doc["id"], f"{part}#{i}")
            self.db.execute("INSERT INTO search(rowid, doc_id, part, title, body) VALUES(?,?,?,?,?)",
                            (row, doc["id"], part, title, text))
            self.db.execute("INSERT INTO search_rows(doc_id, row) VALUES(?,?)", (doc["id"], row))
        for target in model.linked_note_ids(doc):
            self.db.execute("INSERT OR IGNORE INTO note_links(source, target) VALUES(?,?)", (doc["id"], target))

    def rebuild_index(self) -> None:
        with self._tx():
            self.db.execute("DELETE FROM search")
            self.db.execute("DELETE FROM search_rows")
            self.db.execute("DELETE FROM note_links")
            for r in self.db.execute("SELECT json FROM documents").fetchall():
                self._index(model.normalize(json.loads(r["json"])))
            self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('search_index', ?)", (str(SEARCH_INDEX_VERSION),))

    @staticmethod
    def fts_query(text: str) -> str:
        """Cada palavra precisa aparecer e pode ser o começo de uma palavra maior."""
        words = re.findall(r"\w+", text, flags=re.UNICODE)
        return " AND ".join(f'"{w}"*' for w in words)

    def search(self, text: str, limit: int = 60) -> list[SearchHit]:
        query = self.fts_query(text)
        if not query:
            return []
        rows = self.db.execute(
            """SELECT s.doc_id, s.part, snippet(search, -1, '[[', ']]', '…', 14) AS snip, d.title, d.kind, d.folder_id
               FROM search s JOIN documents d ON d.id = s.doc_id
               WHERE search MATCH ? AND d.trashed_at IS NULL ORDER BY rank LIMIT ?""",
            (query, limit * 4)).fetchall()
        hits: dict[str, SearchHit] = {}
        for r in rows:
            hit = hits.get(r["doc_id"])
            if hit:
                hit.count += 1
                continue
            hits[r["doc_id"]] = SearchHit(r["doc_id"], r["title"], r["kind"], r["part"], r["snip"], 1, r["folder_id"])
        return list(hits.values())[:limit]

    STOPWORDS = set("""a o as os um uma uns umas de do da dos das em no na nos nas por para pra com sem que qual quais
        quando onde como e ou mas se meu minha meus minhas seu sua seus suas é foi ser estar tem ter há isso isto
        esse essa este esta aquele aquela preciso precisa fazer faz sobre até ao aos à às the and of to in is""".split())

    def search_any(self, text: str, limit: int = 20) -> list[SearchHit]:
        """Qualquer palavra serve (para o assistente achar trechos de uma pergunta em linguagem natural)."""
        words = [w for w in re.findall(r"\w{3,}", text.lower(), flags=re.UNICODE) if w not in self.STOPWORDS]
        if not words:
            return []
        query = " OR ".join(f'"{w}"*' for w in words)
        rows = self.db.execute(
            """SELECT s.doc_id, s.part, snippet(search, -1, '[[', ']]', '…', 14) AS snip, d.title, d.kind, d.folder_id
               FROM search s JOIN documents d ON d.id = s.doc_id
               WHERE search MATCH ? AND d.trashed_at IS NULL ORDER BY rank LIMIT ?""", (query, limit)).fetchall()
        return [SearchHit(r["doc_id"], r["title"], r["kind"], r["part"], r["snip"], 1, r["folder_id"]) for r in rows]

    def cited_by(self, doc_id: str) -> list[NoteInfo]:
        rows = self.db.execute(
            """SELECT d.id, d.kind, d.title, d.created, d.updated, d.revision, d.folder_id, d.trashed_at
               FROM note_links l JOIN documents d ON d.id = l.source
               WHERE l.target=? AND d.trashed_at IS NULL ORDER BY d.updated DESC""", (doc_id.lower(),))
        return [NoteInfo(**dict(r)) for r in rows]

    # ------------------------------------------------------------------ mídias
    def asset_path(self, digest: str) -> Path | None:
        folder = self.assets_dir / digest[:2]
        if not folder.is_dir():
            return None
        for p in folder.glob(digest + "*"):
            return p
        return None

    def import_asset(self, source: Path | str, ext: str | None = None) -> str:
        """Copia o arquivo para a biblioteca, lendo em blocos de 1 MB (vídeos grandes não vão
        inteiros para a memória). Devolve o SHA-256."""
        source = Path(source)
        h = hashlib.sha256()
        with open(source, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        if self.asset_path(digest):
            return digest
        ext = (ext or source.suffix or "").lower()
        dest = self.assets_dir / digest[:2] / (digest + ext)
        dest.parent.mkdir(exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
        return digest

    def import_bytes(self, data: bytes, ext: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        if self.asset_path(digest):
            return digest
        dest = self.assets_dir / digest[:2] / (digest + ext.lower())
        dest.parent.mkdir(exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return digest

    def collect_garbage(self, min_age_seconds: float = 24 * 3600) -> int:
        """Apaga mídias que nenhuma nota (nem as da Lixeira) usa e que têm mais de um dia."""
        used: set[str] = set()
        for r in self.db.execute("SELECT json FROM documents"):
            used |= model.asset_hashes(json.loads(r["json"]))
        removed = 0
        now = time.time()
        for path in self.assets_dir.glob("*/*"):
            digest = path.name.split(".")[0]
            if digest in used or path.suffix == ".tmp" and now - path.stat().st_mtime < 3600:
                continue
            age = max(0.0, now - path.stat().st_mtime)      # relógio do disco pode estar uns ms à frente
            if age >= min_age_seconds:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    # ------------------------------------------------------------------ cópia de segurança
    def backup_to(self, folder: Path) -> Path:
        """Cópia completa (banco pela API de backup do SQLite + mídias) numa pasta comum."""
        stamp = time.strftime("%Y-%m-%d %H-%M")
        dest = Path(folder) / f"Got It - cópia {stamp}"
        dest.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest / "gotit.sqlite"))
        with target:
            self.db.backup(target)
        target.close()
        shutil.copytree(self.assets_dir, dest / "assets", dirs_exist_ok=True)
        return dest

    def restore_from(self, folder: Path) -> int:
        """Traz as notas de uma cópia de segurança sem duplicar: notas que já existem ficam com a
        versão mais nova."""
        folder = Path(folder)
        src_db = folder / "gotit.sqlite"
        if not src_db.exists():
            raise FileNotFoundError("Esta pasta não tem uma cópia do Got It!")
        src = sqlite3.connect(str(src_db))
        src.row_factory = sqlite3.Row
        count = 0
        folder_ids = {f.id for f in self.folders("*")}
        for f in src.execute("SELECT * FROM folders"):
            if f["id"] not in folder_ids:
                self.db.execute("INSERT INTO folders(id, parent_id, name, created) VALUES(?,?,?,?)",
                                (f["id"], None, f["name"], f["created"]))
        for f in src.execute("SELECT * FROM folders"):
            self.db.execute("UPDATE folders SET parent_id=? WHERE id=?", (f["parent_id"], f["id"]))
        for r in src.execute("SELECT * FROM documents"):
            mine = self.info(r["id"])
            if mine and mine.updated >= r["updated"]:
                continue
            doc = json.loads(r["json"])
            with self._tx():
                self.db.execute("DELETE FROM documents WHERE id=?", (r["id"],))
                self.db.execute(
                    "INSERT INTO documents(id, kind, title, created, updated, revision, json, folder_id, trashed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (r["id"], r["kind"], r["title"], r["created"], r["updated"], r["revision"], r["json"], r["folder_id"], r["trashed_at"]))
                self._index(model.normalize(doc))
            count += 1
        src.close()
        if (folder / "assets").is_dir():
            for path in (folder / "assets").glob("*/*"):
                dest = self.assets_dir / path.parent.name / path.name
                if not dest.exists():
                    dest.parent.mkdir(exist_ok=True)
                    shutil.copyfile(path, dest)
        return count

    def ensure_index(self) -> None:
        row = self.db.execute("SELECT value FROM meta WHERE key='search_index'").fetchone()
        if not row or row["value"] != str(SEARCH_INDEX_VERSION):
            self.rebuild_index()
