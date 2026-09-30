# -*- coding: utf-8 -*-
"""In-pack vector index for campus retrieval.

Vectors live in the existing SQLite pack (table kb_vectors). Queries are
embedded with the same small Chinese model. A weak top score is treated as
an uncertain match and handed to the Qwen fallback.
"""

from __future__ import annotations

import sqlite3
import struct
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
VECTOR_TOP_K = 8
# Shown-hit cosine below this is a weak match and goes to Qwen.
SHOWN_SIM_UNCERTAIN_BELOW = 0.62
# If the query itself has no nearby passage, also go to Qwen.
OFFCORPUS_SIM_BELOW = 0.50
VECTOR_CANDIDATE_MIN = 0.68
VECTOR_BOOST_MIN = 0.70


def record_embed_text(record: dict[str, Any]) -> str:
    questions = record.get("questions") or []
    if isinstance(questions, str):
        questions = []
    question_text = " ".join(str(item) for item in questions[:8] if item)
    title = str(record.get("title") or "").strip()
    answer = str(record.get("answer") or "").replace("\n", " ").strip()[:360]
    return "\n".join(part for part in (title, question_text, answer) if part)


def _pack_floats(vector: np.ndarray) -> bytes:
    values = np.asarray(vector, dtype=np.float32).reshape(-1)
    return struct.pack(f"<{len(values)}f", *values.tolist())


def _unpack_floats(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding

    options = {'threads': max(1, int(os.environ.get('CAMPUS_EMBED_THREADS', '2'))),
               'local_files_only': True}
    # Online requests must never check/download model files over the network.
    explicit = os.environ.get('CAMPUS_EMBED_MODEL_DIR', '').strip()
    cache = Path(os.environ.get('FASTEMBED_CACHE_PATH') or
                 Path(__file__).resolve().parents[1] / '.cache' / 'fastembed')
    repo = cache / 'models--Qdrant--bge-small-zh-v1.5'
    if explicit:
        model_dir = Path(explicit)
    elif (repo / 'refs' / 'main').is_file():
        revision = (repo / 'refs' / 'main').read_text().strip()
        model_dir = repo / 'snapshots' / revision
    else:
        raise FileNotFoundError('Campus embedding model must be provisioned locally')
    for filename in ('model_optimized.onnx', 'tokenizer.json', 'config.json',
                     'tokenizer_config.json', 'special_tokens_map.json'):
        if not (model_dir / filename).is_file():
            raise FileNotFoundError(str(model_dir / filename))
    return TextEmbedding(EMBED_MODEL, specific_model_path=str(model_dir), **options)


def embed_passages(texts: list[str]) -> np.ndarray:
    model = _embedder()
    rows = [np.asarray(item, dtype=np.float32) for item in model.embed(texts)]
    return _normalize(np.vstack(rows))


@lru_cache(maxsize=128)
def embed_query(text: str) -> np.ndarray:
    model = _embedder()
    query_embed = getattr(model, "query_embed", None)
    if query_embed is not None:
        vector = next(query_embed([text]))
    else:
        vector = next(model.embed([text]))
    row = np.asarray(vector, dtype=np.float32).reshape(1, -1)
    return _normalize(row)[0]


def write_vectors(sqlite_path: str | Path, *, batch_size: int = 64) -> int:
    path = Path(sqlite_path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, title, answer, questions_json FROM kb_records ORDER BY rowid"
        ).fetchall()
        import json

        records = []
        for row in rows:
            try:
                questions = json.loads(row["questions_json"] or "[]")
            except json.JSONDecodeError:
                questions = []
            records.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "answer": row["answer"] or "",
                    "questions": questions,
                }
            )
        conn.execute("DROP TABLE IF EXISTS kb_vectors")
        conn.execute(
            """CREATE TABLE kb_vectors (
                id TEXT PRIMARY KEY,
                dim INTEGER NOT NULL,
                vec BLOB NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO kb_meta(key, value) VALUES('vector_model', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (EMBED_MODEL,),
        )
        written = 0
        for start in range(0, len(records), batch_size):
            chunk = records[start : start + batch_size]
            matrix = embed_passages([record_embed_text(rec) for rec in chunk])
            payload = [
                (rec["id"], int(matrix.shape[1]), _pack_floats(matrix[idx]))
                for idx, rec in enumerate(chunk)
            ]
            conn.executemany(
                "INSERT INTO kb_vectors(id, dim, vec) VALUES(?,?,?)",
                payload,
            )
            written += len(payload)
            conn.commit()
            print(f"vectors {written}/{len(records)}", flush=True)
        return written
    finally:
        conn.close()


def _load_matrix(path: str):
    info = Path(path).stat()
    return _load_matrix_version(path, info.st_mtime_ns, info.st_size)


@lru_cache(maxsize=1)
def _load_matrix_version(path: str, _mtime_ns: int, _size: int):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT id, vec FROM kb_vectors").fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if not rows:
        return None
    ids = [row[0] for row in rows]
    matrix = np.vstack([_unpack_floats(row[1]) for row in rows])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix /= norms
    return ids, matrix


def search_record_vectors(question: str, sqlite_path: str, *, limit: int = VECTOR_TOP_K) -> list[tuple[str, float]]:
    text = (question or "").strip()
    if not text or not sqlite_path:
        return []
    loaded = _load_matrix(str(sqlite_path))
    if not loaded:
        return []
    ids, matrix = loaded
    try:
        query = embed_query(text)
    except Exception:
        return []
    if query.shape[0] != matrix.shape[1]:
        return []
    scores = matrix @ query
    k = max(1, min(int(limit), len(ids)))
    top = np.argpartition(scores, -k)[-k:]
    top = top[np.argsort(scores[top])[::-1]]
    return [(ids[int(idx)], float(scores[int(idx)])) for idx in top]


def vector_is_uncertain(hits: list[tuple[str, float]], shown_id: str = "", scores: dict[str, float] | None = None) -> bool:
    if not hits:
        return False
    shown = (scores or {}).get(shown_id)
    if shown is None:
        # A strong neighbour says nothing about a different, lexically selected answer.
        if shown_id:
            return True
        return hits[0][1] < OFFCORPUS_SIM_BELOW
    return shown < SHOWN_SIM_UNCERTAIN_BELOW


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("sqlite", type=Path)
    args = parser.parse_args()
    count = write_vectors(args.sqlite)
    print(f"wrote {count} vectors model={EMBED_MODEL}")


if __name__ == "__main__":
    main()
