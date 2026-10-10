"""Shared data model and the JSONL wire format between device agents and the hub.

A device agent turns every source item (a file, a photo, a Notion page...) into one
`Record`: a `Document` plus its text `Chunk`s and, optionally, vectors. Records are
written as JSON lines ("outbox batches") and applied on the hub by `tidy ingest`.

Vectors travel as base64 of little-endian float32, already L2-normalised.
"""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Iterator, Literal

import numpy as np

Modality = Literal["text", "image", "video", "audio", "message"]
ChunkField = Literal["body", "ocr", "asr", "caption", "summary", "labels", "meta"]
Visibility = Literal["private", "shared", "workspace", "company-restricted"]

# sensitivity bit flags
SENS_NONE = 0
SENS_MEETING = 1  # meeting / call transcript
SENS_SCREEN = 2  # screen recording or screenshot
SENS_FACE = 4  # contains named people
SENS_ID = 8  # identity document, contract with personal numbers
SENS_SECRET = 16  # looks like credentials; never leaves the device

WIRE_VERSION = 1


@dataclass
class Document:
    doc_id: str  # 'file:<device>:<sha1(path)[:16]>' | 'photos:<uuid>' | 'notion:<ws>:<page>' ...
    source_id: str  # e.g. 'file:junwon-mba' | 'photos:junwon-mba' | 'notion:acme'
    native_id: str  # path, uuid, page id ... as the source knows it
    modality: Modality
    title: str
    uri: str  # how a human/agent opens it: file:///..., https://notion.so/..., photos://<uuid>
    mime: str | None = None
    author: str | None = None
    participants: list[str] | None = None
    created_at: str | None = None  # ISO 8601 with offset; file agents send local time ('...T08:30:00+09:00')
    updated_at: str | None = None
    taken_at: str | None = None  # photos/videos: capture time
    duration_s: float | None = None
    geo_cell: str | None = None  # coarse cell, never exact GPS
    place_ko: str | None = None
    place_en: str | None = None
    persons: list[str] | None = None  # opt-in, names only
    labels: list[str] | None = None
    size_bytes: int | None = None
    content_hash: str | None = None  # sha256 of the original bytes / exported text
    phash: str | None = None
    parent_id: str | None = None
    device_id: str | None = None
    visibility: Visibility = "private"
    sensitivity: int = SENS_NONE
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    ordinal: int
    text: str
    field: ChunkField = "body"
    page: int | None = None
    t_start: float | None = None
    t_end: float | None = None
    chunk_id: str = ""  # filled by chunk_id_for() if empty
    chunk_hash: str = ""  # filled by chunk_hash_for() if empty


@dataclass
class Record:
    document: Document
    chunks: list[Chunk]
    # model_id -> {chunk_id -> unit vector}; text space
    vec_text: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    # model_id -> list of (frame_id, t_sec or None, unit vector); visual space
    vec_visual: dict[str, list[tuple[str, float | None, np.ndarray]]] = field(default_factory=dict)


def normalize_text(text: str) -> str:
    """NFC + collapsed whitespace. Used for hashing so cosmetic changes don't re-embed."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def chunk_id_for(doc_id: str, field_: str, ordinal: int) -> str:
    return f"{doc_id}#{field_}:{ordinal}"


def chunk_hash_for(text: str, model_id: str = "") -> str:
    return hashlib.sha256(f"{model_id}\x00{normalize_text(text)}".encode()).hexdigest()[:32]


def finalize_chunks(doc_id: str, chunks: Iterable[Chunk]) -> list[Chunk]:
    out = []
    for c in chunks:
        if not c.chunk_id:
            c.chunk_id = chunk_id_for(doc_id, c.field, c.ordinal)
        if not c.chunk_hash:
            c.chunk_hash = chunk_hash_for(c.text)
        out.append(c)
    return out


def _vec_to_b64(v: np.ndarray) -> str:
    return base64.b64encode(np.asarray(v, dtype="<f4").tobytes()).decode("ascii")


def _vec_from_b64(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype="<f4").copy()


def record_to_json(rec: Record) -> str:
    obj = {
        "v": WIRE_VERSION,
        "op": "upsert",
        "document": asdict(rec.document),
        "chunks": [asdict(c) for c in rec.chunks],
        "vec_text": {m: {cid: _vec_to_b64(v) for cid, v in vs.items()} for m, vs in rec.vec_text.items()},
        "vec_visual": {
            m: [[fid, t, _vec_to_b64(v)] for fid, t, v in frames] for m, frames in rec.vec_visual.items()
        },
    }
    return json.dumps(obj, ensure_ascii=False)


def delete_to_json(doc_id: str, deleted_at: str) -> str:
    return json.dumps({"v": WIRE_VERSION, "op": "delete", "doc_id": doc_id, "deleted_at": deleted_at})


def parse_line(line: str) -> tuple[str, Any]:
    """Returns ('upsert', Record) or ('delete', (doc_id, deleted_at))."""
    obj = json.loads(line)
    if obj.get("v") != WIRE_VERSION:
        raise ValueError(f"unsupported wire version {obj.get('v')}")
    if obj["op"] == "delete":
        return "delete", (obj["doc_id"], obj["deleted_at"])
    if obj["op"] != "upsert":
        raise ValueError(f"unknown op {obj['op']}")
    doc = Document(**obj["document"])
    chunks = [Chunk(**c) for c in obj["chunks"]]
    vec_text = {m: {cid: _vec_from_b64(b) for cid, b in vs.items()} for m, vs in obj.get("vec_text", {}).items()}
    vec_visual = {
        m: [(fid, t, _vec_from_b64(b)) for fid, t, b in frames] for m, frames in obj.get("vec_visual", {}).items()
    }
    return "upsert", Record(doc, chunks, vec_text, vec_visual)


def iter_lines(path: str) -> Iterator[str]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield line
