"""Local hybrid policy search backed by SQLite FTS5 and sentence embeddings."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RRF_K = 60


class PolicyIndexUnavailable(RuntimeError):
    """Raised when the configured semantic index cannot be created or loaded."""


class Encoder(Protocol):
    model_name: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        ...


class SentenceTransformerEncoder:
    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise PolicyIndexUnavailable(
                "Hybrid policy search requires sentence-transformers; install requirements.txt "
                "or set POLICY_SEMANTIC_MODE=keyword for offline keyword-only operation."
            ) from exc
        try:
            self.model = SentenceTransformer(model_name)
        except OSError as exc:
            raise PolicyIndexUnavailable(
                f"Could not load embedding model {model_name!r}; check the model name and "
                "download/cache it before running offline."
            ) from exc
        self.model_name = model_name

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]


@lru_cache(maxsize=2)
def _load_encoder(model_name: str) -> SentenceTransformerEncoder:
    return SentenceTransformerEncoder(model_name)


def _semantic_mode(value: Optional[str]) -> str:
    mode = value or os.environ.get("POLICY_SEMANTIC_MODE", "hybrid")
    if mode not in {"hybrid", "keyword"}:
        raise ValueError("POLICY_SEMANTIC_MODE must be 'hybrid' or 'keyword'.")
    return mode


def _fts_query(query: str) -> str:
    terms = re.findall(r"\w+", unicodedata.normalize("NFC", query).lower())
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def _normalized(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm or not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding vectors must contain finite values and have non-zero length.")
    return [value / norm for value in vector]


class PolicySearchIndex:
    def __init__(self, chunks: list[dict], *, encoder: Optional[Encoder] = None,
                 semantic_mode: Optional[str] = None, connection: Optional[sqlite3.Connection] = None):
        self.chunks = chunks
        self.encoder = encoder
        self.semantic_mode = _semantic_mode(semantic_mode)
        self.connection = connection if connection is not None else sqlite3.connect(
            ":memory:", check_same_thread=False
        )
        self._lock = threading.RLock()
        self._signature: tuple[str, ...] = ()
        self._semantic_ready = False
        self._rebuild()

    def _active_encoder(self) -> Encoder:
        if self.encoder is None:
            model_name = os.environ.get("POLICY_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
            self.encoder = _load_encoder(model_name)
        return self.encoder

    def _chunk_signature(self) -> tuple[str, ...]:
        return tuple(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in self.chunks)

    def _rebuild(self) -> None:
        conn = self.connection
        conn.execute("DROP TABLE IF EXISTS policy_search_fts")
        conn.execute(
            "CREATE VIRTUAL TABLE policy_search_fts USING "
            "fts5(chunk_id UNINDEXED, category UNINDEXED, section, text, tokenize='unicode61')"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS policy_search_embeddings "
            "(chunk_id TEXT PRIMARY KEY, category TEXT NOT NULL, "
            "model_name TEXT NOT NULL, vector_json TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_policy_search_embeddings_category "
            "ON policy_search_embeddings(category)"
        )
        conn.execute("DELETE FROM policy_search_embeddings")
        conn.executemany(
            "INSERT INTO policy_search_fts(chunk_id, category, section, text) VALUES (?, ?, ?, ?)",
            [(c["chunk_id"], c["category"], c["section"], c["text"]) for c in self.chunks],
        )
        conn.commit()
        self._semantic_ready = self.semantic_mode == "keyword" or not self.chunks
        self._signature = self._chunk_signature()

    def _ensure_semantic(self) -> None:
        if self._semantic_ready:
            return
        encoder = self._active_encoder()
        texts = [f'{c["section"]}\n{c["text"]}' for c in self.chunks]
        vectors = encoder.encode(texts)
        if len(vectors) != len(self.chunks):
            raise ValueError("Embedding model returned a different number of vectors than input chunks.")
        normalized = [_normalized(vector) for vector in vectors]
        self.connection.executemany(
            "INSERT INTO policy_search_embeddings(chunk_id, category, model_name, vector_json) "
            "VALUES (?, ?, ?, ?)",
            [(c["chunk_id"], c["category"], encoder.model_name, json.dumps(v))
             for c, v in zip(self.chunks, normalized)],
        )
        self.connection.commit()
        self._semantic_ready = True

    def _ensure_current(self) -> None:
        if self._chunk_signature() != self._signature:
            self._rebuild()

    def search(self, query: str, category: str, limit: int) -> list[dict]:
        with self._lock:
            return self._search(query, category, limit)

    def _search(self, query: str, category: str, limit: int) -> list[dict]:
        self._ensure_current()
        conn = self.connection
        rankings: dict[str, dict[str, int]] = {"keyword": {}, "semantic": {}}
        fts_query = _fts_query(query)
        candidate_limit = max(20, limit * 5)
        if fts_query:
            keyword_rows = conn.execute(
                "SELECT chunk_id FROM policy_search_fts WHERE policy_search_fts MATCH ? "
                "AND category = ? ORDER BY bm25(policy_search_fts), chunk_id LIMIT ?",
                (fts_query, category, candidate_limit),
            ).fetchall()
            rankings["keyword"] = {row[0]: rank for rank, row in enumerate(keyword_rows, 1)}

        semantic_scores: list[tuple[float, str]] = []
        if self.semantic_mode == "hybrid" and self.chunks:
            self._ensure_semantic()
            encoder = self._active_encoder()
            query_vector = _normalized(encoder.encode([query])[0])
            rows = conn.execute(
                "SELECT chunk_id, vector_json FROM policy_search_embeddings WHERE category = ?",
                (category,),
            ).fetchall()
            chunk_by_id = {chunk["chunk_id"]: chunk for chunk in self.chunks}
            for chunk_id, vector_json in rows:
                if chunk_id in chunk_by_id:
                    vector = json.loads(vector_json)
                    if len(query_vector) != len(vector):
                        raise ValueError("Query and policy embeddings have incompatible dimensions.")
                    score = sum(left * right for left, right in zip(query_vector, vector))
                    semantic_scores.append((score, chunk_id))
            semantic_scores.sort(key=lambda item: (-item[0], item[1]))
            rankings["semantic"] = {
                chunk_id: rank for rank, (_, chunk_id) in enumerate(semantic_scores[:candidate_limit], 1)
            }

        fused: dict[str, float] = {}
        for ranking in rankings.values():
            for chunk_id, rank in ranking.items():
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        chunk_by_id = {chunk["chunk_id"]: chunk for chunk in self.chunks}
        ordered = sorted(fused, key=lambda chunk_id: (-fused[chunk_id], chunk_id))[:limit]
        return [dict(chunk_by_id[cid], score=fused[cid]) for cid in ordered if cid in chunk_by_id]

    def persist_to(self, connection: sqlite3.Connection) -> None:
        """Copy the generated retrieval index into the normalized fixture database."""
        with self._lock:
            self._persist_to(connection)

    def _persist_to(self, connection: sqlite3.Connection) -> None:
        self._ensure_semantic()
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS policy_chunks_fts USING "
            "fts5(chunk_id UNINDEXED, category UNINDEXED, section, text, tokenize='unicode61')"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS policy_embeddings "
            "(chunk_id TEXT PRIMARY KEY REFERENCES policy_chunks(chunk_id), category TEXT NOT NULL, "
            "model_name TEXT NOT NULL, vector_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_policy_embeddings_category ON policy_embeddings(category)"
        )
        connection.execute("DELETE FROM policy_chunks_fts")
        connection.execute("DELETE FROM policy_embeddings")
        connection.executemany(
            "INSERT INTO policy_chunks_fts(chunk_id, category, section, text) VALUES (?, ?, ?, ?)",
            [(c["chunk_id"], c["category"], c["section"], c["text"]) for c in self.chunks],
        )
        embeddings = self.connection.execute(
            "SELECT chunk_id, category, model_name, vector_json FROM policy_search_embeddings"
        ).fetchall()
        connection.executemany(
            "INSERT INTO policy_embeddings(chunk_id, category, model_name, vector_json) VALUES (?, ?, ?, ?)",
            embeddings,
        )
