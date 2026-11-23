"""Busca por significado: EmbeddingGemma 2 (270M) pelo LiteRT-LM, vetores de 256 dimensões
normalizados (os mesmos prompts e limiares do Got It! para iPhone). Alguns segundos depois de
cada mudança, só os trechos novos ou alterados são lidos de novo; a Lixeira fica de fora."""

from __future__ import annotations

import hashlib
import queue
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import model
import models

DIM = 256
CHUNK = 900
MIN_SCORE = 0.66
WINDOW = 0.06
MODEL_TAG = f"embeddinggemma-2-270m/{DIM}"

_index = None


@dataclass
class Hit:
    doc_id: str
    title: str
    kind: str
    part: str
    snippet: str
    count: int
    folder_id: str | None
    score: float = 0.0


def document_prompt(title: str, text: str) -> str:
    return f"title: {title.strip() or 'none'} | text: {text}"


def query_prompt(query: str) -> str:
    return f"task: search result | query: {query}"


def chunks(text: str, limit: int = CHUNK) -> list[str]:
    """Trechos de até ``limit`` caracteres, cortados em parágrafo ou frase."""
    text = text.strip()
    if not text:
        return []
    out, cur = [], ""
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > limit:
            cut = max(para.rfind(". ", 0, limit), para.rfind(" ", 0, limit))
            cut = cut + 1 if cut > limit // 2 else limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if len(cur) + len(para) + 1 > limit and cur:
            out.append(cur)
            cur = para
        else:
            cur = (cur + "\n" + para).strip()
    if cur:
        out.append(cur)
    return out


class Index:
    def __init__(self, window):
        self.window = window
        self.path = Path(window.store.data_dir) / "semantic.sqlite"
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS docs(doc_id TEXT PRIMARY KEY, revision INTEGER, model TEXT);
            CREATE TABLE IF NOT EXISTS chunks(doc_id TEXT, part TEXT, hash TEXT, text TEXT, vector BLOB);
            CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
        """)
        # leitura das notas por uma conexão própria (a thread de indexação não usa a da janela)
        self.notes_db = sqlite3.connect(str(window.store.db_path), check_same_thread=False)
        self.lock = threading.Lock()
        self.engine = None
        self.queue: queue.Queue = queue.Queue()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self._matrix = None

    # ------------------------------------------------------------------ motor
    def _engine(self):
        if self.engine is None:
            import litert_lm
            litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
            path = models.path_of(self.window.store.data_dir, models.SEMANTIC)
            self.engine = litert_lm.EmbeddingEngine(str(path))
            self.options = litert_lm.EmbeddingOptions(normalize=True, output_size=DIM)
        return self.engine

    def embed(self, text: str) -> np.ndarray:
        with self.lock:
            v = np.asarray(self._engine().compute_embedding(text, self.options).embedding, dtype=np.float32)
        n = float(np.linalg.norm(v)) or 1.0
        return v / n

    def release(self) -> None:
        with self.lock:
            if self.engine is not None:
                self.engine.close()
                self.engine = None

    # ------------------------------------------------------------------ indexação
    def schedule_all(self) -> None:
        self.queue.put("*")

    def schedule(self, doc_id: str) -> None:
        self.queue.put(doc_id)

    def _work(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            try:
                if item == "*":
                    for (doc_id,) in self.notes_db.execute("SELECT id FROM documents WHERE trashed_at IS NULL").fetchall():
                        self._index(doc_id)
                    self._prune()
                else:
                    self._index(item)
                self._matrix = None
            except Exception:
                pass

    def _index(self, doc_id: str) -> None:
        import json
        found = self.notes_db.execute("SELECT revision, trashed_at, json FROM documents WHERE id=?", (doc_id,)).fetchone()
        if found is None or found[1]:
            self.db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            self.db.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))
            return
        revision = found[0]
        row = self.db.execute("SELECT revision, model FROM docs WHERE doc_id=?", (doc_id,)).fetchone()
        if row and row[0] == revision and row[1] == MODEL_TAG:
            return
        doc = model.normalize(json.loads(found[2]))
        wanted = []
        for part, text in model.collect_text(doc):
            for piece in chunks(text):
                h = hashlib.sha256(f"{doc['title']}\n{piece}".encode()).hexdigest()
                wanted.append((part, h, piece))
        have = {r[0]: r for r in self.db.execute("SELECT hash, part, text, vector FROM chunks WHERE doc_id=?", (doc_id,))}
        rows = []
        for part, h, piece in wanted:
            if h in have:
                rows.append((doc_id, part, h, piece, have[h][3]))
                continue
            vec = self.embed(document_prompt(doc["title"], piece))
            rows.append((doc_id, part, h, piece, vec.astype(np.float32).tobytes()))
        self.db.execute("BEGIN")
        self.db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        self.db.executemany("INSERT INTO chunks(doc_id, part, hash, text, vector) VALUES(?,?,?,?,?)", rows)
        self.db.execute("INSERT OR REPLACE INTO docs(doc_id, revision, model) VALUES(?,?,?)", (doc_id, revision, MODEL_TAG))
        self.db.execute("COMMIT")

    def _prune(self) -> None:
        live = {r[0] for r in self.notes_db.execute("SELECT id FROM documents WHERE trashed_at IS NULL")}
        for (doc_id,) in self.db.execute("SELECT doc_id FROM docs").fetchall():
            if doc_id not in live:
                self.db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
                self.db.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))

    # ------------------------------------------------------------------ busca
    def _load_matrix(self):
        if self._matrix is None:
            rows = self.db.execute("SELECT rowid, doc_id, part, vector FROM chunks").fetchall()
            if not rows:
                self._matrix = (np.zeros((0, DIM), np.float32), [])
            else:
                mat = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float32).reshape(len(rows), DIM)
                self._matrix = (mat, [(r[0], r[1], r[2]) for r in rows])
        return self._matrix

    def passages(self, query: str, limit: int = 12, only: set | None = None) -> list[tuple[float, str, str, str]]:
        """(pontuação, nota, parte, texto) dos trechos mais próximos."""
        mat, meta = self._load_matrix()
        if not meta:
            return []
        q = self.embed(query_prompt(query))
        scores = mat @ q
        order = np.argsort(-scores)
        out = []
        for i in order:
            rowid, doc_id, part = meta[i]
            if only is not None and doc_id not in only:
                continue
            text = self.db.execute("SELECT text FROM chunks WHERE rowid=?", (rowid,)).fetchone()
            out.append((float(scores[i]), doc_id, part, text[0] if text else ""))
            if len(out) >= limit:
                break
        return out

    def close(self) -> None:
        self.queue.put(None)
        self.release()


def enabled(window) -> bool:
    return window.settings.value("semanticSearch", "false") == "true" and models.is_ready(window.store.data_dir, models.SEMANTIC)


def index(window) -> Index | None:
    global _index
    if not enabled(window):
        return None
    if _index is None:
        try:
            _index = Index(window)
            _index.schedule_all()
        except Exception:
            _index = None
    return _index


def search(window, query: str, exclude: set) -> list[Hit]:
    idx = index(window)
    if idx is None or len(query.strip()) < 3:
        return []
    try:
        found = idx.passages(query, limit=40)
    except Exception:
        return []
    if not found:
        return []
    best = found[0][0]
    hits: dict[str, Hit] = {}
    for score, doc_id, part, text in found:
        if score < MIN_SCORE or score < best - WINDOW or doc_id in exclude:
            continue
        if doc_id in hits:
            hits[doc_id].count += 1
            continue
        info = window.store.info(doc_id)
        if not info or info.trashed_at:
            continue
        snippet = text[:160] + ("…" if len(text) > 160 else "")
        hits[doc_id] = Hit(doc_id, info.title, info.kind, part, snippet, 1, info.folder_id, score)
        if len(hits) >= 8:
            break
    return list(hits.values())


def note_changed(window, doc_id: str) -> None:
    idx = index(window)
    if idx is not None:
        idx.schedule(doc_id)


def shutdown() -> None:
    global _index
    if _index is not None:
        _index.close()
        _index = None
