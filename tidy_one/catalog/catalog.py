"""Hub catalog: documents, chunks, Kiwi + trigram FTS and int8 vectors in one SQLite file.

Search runs up to four signals (Kiwi BM25, trigram, text kNN, visual kNN) under the same
filters, fuses them with weighted reciprocal rank fusion and groups hits by document.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Self

import numpy as np
import sqlite_vec

from tidy_one.extract.chunk import repeated_prefix
from tidy_one.model import SENS_SECRET, Document, Record, chunk_hash_for, chunk_id_for
from tidy_one.text.morph import is_identifier, morph, word_stem

RRF_K = 60
WEIGHTS = {"fts": 1.0, "trigram": 0.5, "vec": 1.0, "visual": 0.8, "recent": 1.0}
SIGNAL_ORDER = ("fts", "trigram", "vec", "visual", "recent")
TEXT_DIM = 1024
VISUAL_DIM = 768
FRAME_BITS = 12
MAX_FRAMES = 1 << FRAME_BITS
EXCERPT_CHARS = 300
MAX_KNN = 4096
SCAN_BUDGET_S = 0.15  # substring scans for 1-2 character queries stop here
PER_DOC = 3  # chunks one document may hold in a signal's candidate list, so a long file cannot fill it alone
OVERFETCH = 4  # raw chunk candidates fetched per kept candidate before the per-document cap
EXACT_MAX = 10000  # with a place filter, up to this many candidate vectors are scored exactly (~12us each)
MERGE_WINDOW = 400  # fetch: how far back a chunk from another chunker may repeat its predecessor

Hit = tuple[str, int | None, float | None]  # (doc_id, chunk rowid, frame t_sec)

_SCHEMA = Path(__file__).with_name("schema.sql")
_TOP = "\U0010ffff"
_PUNCT = "\"'`.,;:!?()[]{}<>«»“”‘’…·、。"
_HANGUL_WORD = re.compile(r"[가-힣]{2,}")
_HANGUL = re.compile(r"[가-힣]")
_WORDCHAR = re.compile(r"\w")
# Line labels of the extractor's meta chunk (tidy_one.extract.chunk.meta_text). They are kept in the stored
# text but left out of the full-text and trigram indexes and the substring scan, or a query containing
# 파일/폴더/제목/수정/생성 would match every meta chunk.
_META_LABELS = ("제목", "폴더", "파일", "수정", "생성")
_META_LABEL = re.compile(r"(?m)^(?:" + "|".join(_META_LABELS) + r"):[ \t]*")
_SCAN_TEXT = "c.text"
for _label in _META_LABELS:
    _SCAN_TEXT = f"replace({_SCAN_TEXT}, '{_label}:', '')"
_SCAN_TEXT = f"(CASE WHEN c.field = 'meta' THEN {_SCAN_TEXT} ELSE c.text END)"
_NUM_TAIL = re.compile(r"^([\x21-\x7e]+)[가-힣]+$")  # IMG_1234를, v1.2에서, 2024-03-05에, 3월
_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
_FIELD_ORDER = {f: i for i, f in enumerate(["body", "asr", "ocr", "caption", "summary", "labels", "meta"])}
_LIST_COLS = ("participants", "persons", "labels")
_DOC_FIELDS = [f.name for f in dataclasses.fields(Document)]
_DOC_COLS = [("extra_json" if f == "extra" else f) for f in _DOC_FIELDS] + ["ingested_at", "deleted_at"]
_LIVE = f"deleted_at IS NULL AND (sensitivity & {SENS_SECRET}) = 0"


def quantize(v: np.ndarray) -> bytes:
    """Unit float vector -> int8 bytes: round(clip(v, -1, 1) * 127)."""
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    return np.round(np.clip(a, -1.0, 1.0) * 127.0).astype(np.int8).tobytes()


def rrf_fuse(
    rankings: dict[str, list[str]], weights: dict[str, float] | None = None, k: int = RRF_K
) -> list[tuple[str, float]]:
    """Weighted reciprocal rank fusion over best-first lists (duplicates keep their first rank)."""
    weights = WEIGHTS if weights is None else weights
    scores: dict[str, float] = {}
    for signal, items in rankings.items():
        w = weights.get(signal, 1.0)
        rank = 0
        seen: set[str] = set()
        for key in items:
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            scores[key] = scores.get(key, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def make_excerpt(text: str, terms: list[str], size: int = EXCERPT_CHARS) -> str:
    """At most `size` chars of `text`, centred on the first match of the earliest-listed term found."""
    text = " ".join(text.split())
    if len(text) <= size:
        return text
    low = text.lower()
    pos, tlen = -1, 0
    for t in terms:
        i = low.find(t.lower())
        if i >= 0:
            pos, tlen = i, len(t)
            break
    if pos < 0:
        return text[: size - 1] + "…"
    start = max(0, min(pos + tlen // 2 - size // 2, len(text) - size))
    end = start + size
    piece = text[start:end]
    if start > 0:
        piece = "…" + piece[1:]
    if end < len(text):
        piece = piece[:-1] + "…"
    return piece


def day_number(s: str | None, upper: bool = False) -> int | None:
    """'2024-03-05T..' -> 20240305; partial dates widen to the first (or last, if upper) day."""
    m = _DATE.match((s or "").strip())
    if not m:
        return None
    y, mo, d = m.groups()
    return int(y + (mo or ("12" if upper else "01")) + (d or ("31" if upper else "01")))


def _nfc(s: str | None) -> str:
    return unicodedata.normalize("NFC", s or "")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _words(q: str) -> list[str]:
    return [w for w in (raw.strip(_PUNCT) for raw in q.split()) if w]


def _query_terms(q: str) -> list[str]:
    """Strings to look for when centring an excerpt, longest first."""
    terms = dict.fromkeys([q, *_words(q), *morph(q).split()])
    long = [t for t in terms if len(t) >= 2] or [t for t in terms if t]
    return sorted(long, key=len, reverse=True)


def _fts_query(q: str) -> str | None:
    """OR of quoted morphemes; Hangul nouns also match as prefixes (회의 -> 회의록)."""
    tokens = morph(q).split() or [w.lower() for w in _words(q)]
    terms = []
    for t in dict.fromkeys(tokens):
        if not _WORDCHAR.search(t):
            continue
        term = '"' + t.replace('"', '""') + '"'
        terms.append(term + "*" if _HANGUL_WORD.fullmatch(t) else term)
    return " OR ".join(terms) or None


def _ident_term(w: str) -> str | None:
    """`w` as an identifier or long number without a trailing Hangul particle (IMG_1234를 -> IMG_1234,
    v1.2에서 -> v1.2); None for anything else, including a number with its counter (3월, 2층, 10시)."""
    m = _NUM_TAIL.match(w)
    base = m.group(1).strip(_PUNCT) if m else w
    if base.isdigit():
        return base if len(base) >= 3 else None
    return base if is_identifier(base) else None


def _trigram_terms(q: str) -> list[str]:
    """Substring-search terms: identifier-like words and long numbers, and Hangul words by their stem
    (particles and endings dropped). Stems of 3+ syllables always: Kiwi may split a compound in a document
    (근로 계약서) that it keeps whole in a short query (근로계약서), so only the surface text matches.
    Shorter stems only when the query is that one word; they need the slower substring scan."""
    words = _words(q)
    terms = []
    for w in words:
        t = _ident_term(w)
        if t:
            terms.append(t)
        elif _HANGUL.search(w):
            s = word_stem(w)
            if len(s) >= 3 or (len(words) == 1 and s):
                terms.append(s)
    return list(dict.fromkeys(terms))


def _merge_overlap(prev: str, nxt: str) -> str:
    """Join consecutive chunks, dropping the overlap the chunker repeated at the boundary.

    The overlap of `tidy_one.extract.chunk` is recomputed exactly. For chunks from elsewhere, the
    shortest suffix of `prev` that `nxt` starts with is dropped: in repetitive text a longer match
    would also swallow new rows, so ambiguity duplicates a little text instead of losing it."""
    n = repeated_prefix(prev, nxt)
    if n is not None:
        return prev + nxt[n:]
    tail = prev[-MERGE_WINDOW:]
    probe = nxt[:16]
    best = -1
    i = tail.find(probe) if len(probe) >= 16 else -1
    while i >= 0:
        if nxt.startswith(tail[i:]):
            best = i
        i = tail.find(probe, i + 1)
    return prev + nxt[len(tail) - best :] if best >= 0 else prev + "\n" + nxt


def _per_doc(hits: Iterable[Hit], n: int, per_doc: int = PER_DOC) -> list[Hit]:
    """First n hits, keeping at most per_doc chunks of any one document (order preserved)."""
    counts: dict[str, int] = {}
    out: list[Hit] = []
    for h in hits:
        c = counts.get(h[0], 0)
        if c >= per_doc:
            continue
        counts[h[0]] = c + 1
        out.append(h)
        if len(out) >= n:
            break
    return out


def _unique_chunks(hits: list[Hit]) -> list[Hit]:
    """Drop repeated (document, chunk) hits; documents without chunks (chunk None) stay distinct."""
    seen: set[tuple[str, int | None]] = set()
    out = []
    for h in hits:
        key = (h[0], h[1])
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def _json_list(v: Any) -> str | None:
    return None if v is None else json.dumps(list(v), ensure_ascii=False)


@dataclasses.dataclass(frozen=True)
class _Filters:
    kind: str | None = None
    source: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    place: str | None = None

    def any(self) -> bool:
        return any((self.kind, self.source, self.date_from, self.date_to, self.place))

    def sql(self) -> tuple[str, list[Any]]:
        """WHERE clause over `documents d`, always excluding deleted and secret documents."""
        conds = ["d.deleted_at IS NULL", f"(d.sensitivity & {SENS_SECRET}) = 0"]
        params: list[Any] = []
        if self.kind:
            conds.append("d.modality = ?")
            params.append(self.kind)
        if self.source:
            conds.append("d.source_id >= ? AND d.source_id < ?")
            params += [self.source, self.source + _TOP]
        if self.date_from:
            conds.append("d.sort_at >= ?")
            params.append(self.date_from)
        if self.date_to:
            conds.append("d.sort_at <= ?")
            params.append(self.date_to + _TOP)
        if self.place:
            pat = "%" + self.place.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conds.append("(d.place_ko LIKE ? ESCAPE '\\' OR d.place_en LIKE ? ESCAPE '\\')")
            params += [pat, pat]
        return " AND ".join(conds), params


def private_db_file(path: str) -> None:
    """Create `path` (and its folder) readable by the owner only, before SQLite opens it: SQLite gives the
    -wal and -shm files the main file's mode, and the catalog holds the full text of private documents."""
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder, mode=0o700, exist_ok=True)
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        pass
    for p in (path, path + "-wal", path + "-shm"):
        try:
            if os.stat(p).st_mode & 0o077:
                os.chmod(p, 0o600)
        except OSError:  # missing, or owned by someone else
            pass


class Catalog:
    """One SQLite catalog. Thread-safe: every public method holds the connection lock.

    `durable=True` commits with `synchronous=FULL`, so a write that returned survives a power loss;
    `tidy ingest` and `tidy push --local` use it because the device forgets a batch once it is applied.
    """

    def __init__(
        self, path: str, text_model_id: str = "kure-v1", visual_model_id: str | None = None, *, durable: bool = False
    ):
        self.path = path
        self.text_model_id = text_model_id
        self._visual_model_id = visual_model_id
        self._lock = threading.RLock()
        db_path = path if path == ":memory:" else os.path.expanduser(path)
        if db_path != ":memory:":
            private_db_file(db_path)
        db = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute("PRAGMA busy_timeout = 5000")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute(f"PRAGMA synchronous = {'FULL' if durable else 'NORMAL'}")
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(_SCHEMA.read_text(encoding="utf-8"))
        self._db = db

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- models -------------------------------------------------------------

    def register_model(self, model_id: str, space: str, dim: int, quant: str = "int8", active: bool = True) -> None:
        """Accept (active) or stop accepting vectors from `model_id` in `space` ('text'|'visual')."""
        with self._lock:
            self._db.execute(
                "INSERT INTO models(model_id, space, dim, quant, active) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(model_id) DO UPDATE SET space = excluded.space, dim = excluded.dim, "
                "quant = excluded.quant, active = excluded.active",
                (model_id, space, dim, quant, int(active)),
            )

    def visual_model_id(self) -> str | None:
        if self._visual_model_id:
            return self._visual_model_id
        row = self._db.execute(
            "SELECT model_id FROM models WHERE space = 'visual' AND active = 1 AND dim = ? ORDER BY model_id LIMIT 1",
            (VISUAL_DIM,),
        ).fetchone()
        return row["model_id"] if row else None

    # -- writes -------------------------------------------------------------

    def apply(self, rec: Record) -> None:
        """Upsert the document and replace its chunks and vectors in one transaction."""
        doc = rec.document
        secret = bool(doc.sensitivity & SENS_SECRET)
        title = _nfc(doc.title)
        chunks = []
        indexed: list[str] = []  # text for the full-text and trigram indexes: meta chunks without labels
        for c in [] if secret else rec.chunks:
            text = _nfc(c.text)
            plain = _META_LABEL.sub("", text) if c.field == "meta" else text
            tm = morph(plain)
            cid = c.chunk_id or chunk_id_for(doc.doc_id, c.field, c.ordinal)
            row = (cid, doc.doc_id, c.ordinal, c.field, c.page, c.t_start, c.t_end, text, tm,
                   c.chunk_hash or chunk_hash_for(c.text), len(tm.split()))  # fmt: skip
            chunks.append(row)
            indexed.append(plain)
        ids = [r[0] for r in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate chunk ids in {doc.doc_id}")
        title_morph = morph(title)
        day = day_number(doc.taken_at or doc.updated_at or doc.created_at) or 0
        now = _now()
        values = []
        for f in _DOC_FIELDS:
            v = getattr(doc, f)
            if f == "extra":
                v = json.dumps(v or {}, ensure_ascii=False)
            elif f in _LIST_COLS:
                v = _json_list(v)
            elif f == "title":
                v = title
            values.append(v)
        values += [now, None]

        with self._lock:
            models = {r["model_id"]: r for r in self._db.execute("SELECT * FROM models")}
            seen: dict[str, tuple[str, int]] = {}

            def accepts(model_id: str, space: str, dim: int, sample: np.ndarray | None) -> bool:
                if sample is not None:
                    seen[model_id] = (space, int(np.asarray(sample).size))
                m = models.get(model_id)
                return bool(m and m["active"] and m["space"] == space and m["dim"] == dim)

            # vec_text rowid is the chunk rowid, so one vector per chunk: the serving model wins.
            text_vecs: dict[str, tuple[str, bytes]] = {}
            frames: list[tuple[str, str, float | None, bytes]] = []
            if not secret:
                known = set(ids)
                for model_id in sorted(rec.vec_text, key=lambda m: m != self.text_model_id):
                    vs = rec.vec_text[model_id]
                    if not accepts(model_id, "text", TEXT_DIM, next(iter(vs.values()), None)):
                        continue
                    for cid, v in vs.items():
                        a = np.asarray(v, dtype=np.float32).reshape(-1)
                        if cid in known and a.size == TEXT_DIM and np.isfinite(a).all():
                            text_vecs.setdefault(cid, (model_id, quantize(a)))
                for model_id, fs in rec.vec_visual.items():
                    if not accepts(model_id, "visual", VISUAL_DIM, fs[0][2] if fs else None):
                        continue
                    for fid, t, v in fs:
                        a = np.asarray(v, dtype=np.float32).reshape(-1)
                        if a.size == VISUAL_DIM and np.isfinite(a).all() and len(frames) < MAX_FRAMES:
                            frames.append((model_id, fid, None if t is None else float(t), quantize(a)))

            db = self._db
            db.execute("BEGIN IMMEDIATE")
            try:
                old = db.execute("SELECT id, n_frames FROM documents WHERE doc_id = ?", (doc.doc_id,)).fetchone()
                self._drop_content(doc.doc_id, old)
                cols = ", ".join(_DOC_COLS)
                updates = ", ".join(f"{c} = excluded.{c}" for c in _DOC_COLS if c != "doc_id")
                db.execute(
                    f"INSERT INTO documents({cols}, n_frames) VALUES ({', '.join('?' * len(_DOC_COLS))}, ?) "
                    f"ON CONFLICT(doc_id) DO UPDATE SET {updates}, n_frames = excluded.n_frames",
                    [*values, len(frames)],
                )
                doc_rowid = db.execute("SELECT id FROM documents WHERE doc_id = ?", (doc.doc_id,)).fetchone()[0]
                db.execute(
                    "INSERT OR IGNORE INTO sources(source_id, kind, device_id, default_visibility) VALUES (?, ?, ?, ?)",
                    (doc.source_id, doc.source_id.split(":", 1)[0], doc.device_id, doc.visibility),
                )
                source_n = db.execute("SELECT id FROM sources WHERE source_id = ?", (doc.source_id,)).fetchone()[0]
                meta = (doc.modality, source_n, day)
                for row, plain in zip(chunks, indexed, strict=True):
                    rowid = db.execute(
                        "INSERT INTO chunks(chunk_id, doc_id, ordinal, field, page, t_start, t_end, text, "
                        "text_morph, chunk_hash, token_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    ).lastrowid
                    tm = row[8]
                    db.execute(
                        "INSERT INTO chunks_fts(rowid, text_morph, title) VALUES (?, ?, ?)", (rowid, tm, title_morph)
                    )
                    db.execute("INSERT INTO chunks_trigram(rowid, text, title) VALUES (?, ?, ?)", (rowid, plain, title))
                    if row[0] in text_vecs:
                        model_id, blob = text_vecs[row[0]]
                        db.execute(
                            "INSERT INTO vec_text(rowid, embedding, model_id, modality, source_n, day) "
                            "VALUES (?, vec_int8(?), ?, ?, ?, ?)",
                            (rowid, blob, model_id, *meta),
                        )
                for i, (model_id, fid, t, blob) in enumerate(frames):
                    db.execute(
                        "INSERT INTO vec_visual(rowid, embedding, model_id, modality, source_n, day, frame_id, t_sec) "
                        "VALUES (?, vec_int8(?), ?, ?, ?, ?, ?, ?)",
                        ((doc_rowid << FRAME_BITS) + i, blob, model_id, *meta, fid, t),
                    )
                for model_id, (space, dim) in seen.items():
                    db.execute(
                        "INSERT INTO models(model_id, space, dim, active, seen_at) VALUES (?, ?, ?, 0, ?) "
                        "ON CONFLICT(model_id) DO UPDATE SET seen_at = excluded.seen_at",
                        (model_id, space, dim, now),
                    )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def delete(self, doc_id: str, deleted_at: str) -> None:
        """Tombstone the document and drop its chunks and vectors (no-op if unknown)."""
        with self._lock:
            db = self._db
            db.execute("BEGIN IMMEDIATE")
            try:
                old = db.execute("SELECT id, n_frames FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
                if old is not None:
                    self._drop_content(doc_id, old)
                    db.execute(
                        "UPDATE documents SET deleted_at = ?, n_frames = 0 WHERE doc_id = ?", (deleted_at, doc_id)
                    )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _drop_content(self, doc_id: str, old: sqlite3.Row | None) -> None:
        db = self._db
        rows = [(r[0],) for r in db.execute("SELECT id FROM chunks WHERE doc_id = ?", (doc_id,))]
        if rows:
            db.executemany("DELETE FROM chunks_fts WHERE rowid = ?", rows)
            db.executemany("DELETE FROM chunks_trigram WHERE rowid = ?", rows)
            db.executemany("DELETE FROM vec_text WHERE rowid = ?", rows)
            db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        if old is not None and old["n_frames"]:
            base = old["id"] << FRAME_BITS
            db.executemany("DELETE FROM vec_visual WHERE rowid = ?", [(base + i,) for i in range(old["n_frames"])])

    # -- search -------------------------------------------------------------

    def search(
        self,
        query: str,
        qvec_text: np.ndarray | None = None,
        qvec_visual: np.ndarray | None = None,
        *,
        kind: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        place: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Hybrid search; filters apply to every signal. Returns at most k hits, best first."""
        k = max(1, min(int(k), 100))
        n = max(k * 5, 50)
        q = _nfc(query).strip()
        f = _Filters(kind or None, source or None, date_from or None, date_to or None, place or None)
        with self._lock:
            lists: dict[str, list[Hit]] = {}
            if q:
                lists["fts"] = self._search_fts(q, f, n)
                lists["trigram"] = self._search_trigram(q, f, n)
            if qvec_text is not None:
                lists["vec"] = self._search_vec(qvec_text, f, n)
            if qvec_visual is not None and kind in (None, "image", "video"):
                lists["visual"] = self._search_visual(qvec_visual, f, n)
            if not q and qvec_text is None and qvec_visual is None:
                lists["recent"] = self._recent(f, k)
            lists = {s: hits for s, hits in lists.items() if hits}
            return self._assemble(q, lists, k) if lists else []

    def _ranked_fts(self, table: str, weights: str, match: str, f: _Filters, n: int) -> list[Hit]:
        """BM25 over an FTS table. Without filters the top n come straight from the index:
        deleted and secret documents have no chunks, so no join is needed to rank."""
        where, wp = f.sql()
        inner = f"SELECT rowid AS id, bm25({table}{weights}) AS s FROM {table} WHERE {table} MATCH ?"
        ip: list[Any] = [match]
        raw = n * OVERFETCH
        if not f.any():
            inner += " ORDER BY s LIMIT ?"
            ip.append(raw)
        sql = (
            f"WITH m AS MATERIALIZED ({inner}) SELECT c.doc_id, c.id FROM m JOIN chunks c ON c.id = m.id "
            f"JOIN documents d ON d.doc_id = c.doc_id WHERE {where} ORDER BY m.s LIMIT ?"
        )
        try:
            return _per_doc(((r[0], r[1], None) for r in self._db.execute(sql, [*ip, *wp, raw])), n)
        except sqlite3.OperationalError:
            return []

    def _search_fts(self, q: str, f: _Filters, n: int) -> list[Hit]:
        match = _fts_query(q)
        return self._ranked_fts("chunks_fts", ", 1.0, 1.5", match, f, n) if match else []

    def _search_trigram(self, q: str, f: _Filters, n: int) -> list[Hit]:
        terms = _trigram_terms(q)
        long = [t for t in terms if len(t) >= 3]
        short = [t.lower() for t in terms if len(t) < 3]
        out: list[Hit] = []
        if long:
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in long)
            out += self._ranked_fts("chunks_trigram", "", match, f, n)
        if short:
            out += self._substring_scan(short, f, n)
        return _unique_chunks(out)

    def _substring_scan(self, terms: list[str], f: _Filters, n: int) -> list[Hit]:
        """Trigram MATCH needs 3 chars, so 1-2 char terms scan titles, then chunk text, within a time budget.
        Meta chunks are scanned without their line labels, and one document keeps at most PER_DOC hits."""
        where, wp = f.sql()
        out: list[Hit] = []
        deadline = time.monotonic() + SCAN_BUDGET_S
        self._db.set_progress_handler(lambda: time.monotonic() > deadline, 2000)
        try:
            for t in terms:
                title_sql = (
                    "SELECT d.doc_id, (SELECT min(c.id) FROM chunks c WHERE c.doc_id = d.doc_id) FROM documents d "
                    f"WHERE instr(lower(d.title), ?) > 0 AND {where} LIMIT ?"
                )
                text_sql = (
                    "SELECT c.doc_id, c.id FROM chunks c JOIN documents d ON d.doc_id = c.doc_id "
                    f"WHERE instr(lower({_SCAN_TEXT}), ?) > 0 AND {where} LIMIT ?"
                )
                for sql in (title_sql, text_sql):
                    for r in self._db.execute(sql, [t, *wp, n * OVERFETCH]):
                        out.append((r[0], r[1], None))
        except sqlite3.OperationalError:
            pass  # interrupted by the budget: keep what was found
        finally:
            self._db.set_progress_handler(None, 0)
        return _per_doc(_unique_chunks(out), n)

    def _knn_conds(self, f: _Filters) -> tuple[list[str], list[Any]] | None:
        """Filters pushed into the vec0 scan (None when the source prefix matches no source)."""
        conds: list[str] = []
        params: list[Any] = []
        if f.kind:
            conds.append("modality = ?")
            params.append(f.kind)
        if f.source:
            ns = [r[0] for r in self._db.execute(
                "SELECT id FROM sources WHERE source_id >= ? AND source_id < ?", (f.source, f.source + _TOP)
            )]  # fmt: skip
            if not ns:
                return None
            conds.append(f"source_n IN ({', '.join('?' * len(ns))})")
            params += ns
        lo, hi = day_number(f.date_from), day_number(f.date_to, upper=True)
        if f.date_from or f.date_to:
            conds.append("day > 0")
        if lo is not None:
            conds.append("day >= ?")
            params.append(lo)
        if hi is not None:
            conds.append("day <= ?")
            params.append(hi)
        return conds, params

    def _knn(
        self, table: str, cols: str, join: str, qv: np.ndarray, model_id: str, f: _Filters, kk: int, n: int
    ) -> list[sqlite3.Row]:
        pushed = self._knn_conds(f)
        if pushed is None:
            return []
        conds, params = pushed
        where, wp = f.sql()
        knn = " AND ".join(["embedding MATCH vec_int8(?)", "k = ?", "model_id = ?", *conds])
        sql = (
            f"WITH knn AS (SELECT rowid, distance{cols} FROM {table} WHERE {knn}) "
            f"{join} WHERE {where} ORDER BY knn.distance LIMIT ?"
        )
        return self._db.execute(sql, [quantize(qv), min(MAX_KNN, kk), model_id, *params, *wp, n]).fetchall()

    def _exact_knn(
        self, table: str, extra: str, cands: list[tuple[int, str]], qv: np.ndarray, model_id: str
    ) -> list[tuple[str, int, Any]]:
        """(doc_id, rowid, extra column) of every candidate rowid with a `model_id` vector, nearest first,
        scored one by one (vec0 serves `rowid = ?` as a point lookup; `rowid IN (...)` scans the table)."""
        q = quantize(qv)
        sql = f"SELECT model_id, vec_distance_l2(embedding, vec_int8(?)){extra} FROM {table} WHERE rowid = ?"
        scored = []
        for rowid, doc_id in cands:
            r = self._db.execute(sql, (q, rowid)).fetchone()
            if r is not None and r[0] == model_id:
                scored.append((r[1], rowid, doc_id, r[2] if extra else None))
        scored.sort()
        return [(doc_id, rowid, x) for _, rowid, doc_id, x in scored]

    def _place_candidates(self, sql: str, f: _Filters) -> list[tuple] | None:
        """Rows of `sql` (filtered by every filter, place included), or None when there are too many to
        score exactly. The place filter has no column in the vec0 tables, so a kNN scan cannot apply it:
        nearest neighbours from other places can fill every slot before the place filter runs."""
        where, wp = f.sql()
        rows = self._db.execute(f"{sql} WHERE {where} LIMIT ?", [*wp, EXACT_MAX + 1]).fetchall()
        return None if len(rows) > EXACT_MAX else rows

    def _search_vec(self, qvec: np.ndarray, f: _Filters, n: int) -> list[Hit]:
        qv = np.asarray(qvec, dtype=np.float32).reshape(-1)
        if qv.size != TEXT_DIM:
            raise ValueError(f"qvec_text has {qv.size} dims, expected {TEXT_DIM}")
        raw = n * OVERFETCH
        if f.place:
            cands = self._place_candidates(
                "SELECT c.id, c.doc_id FROM chunks c JOIN documents d ON d.doc_id = c.doc_id", f
            )
            if cands is not None:
                best = self._exact_knn("vec_text", "", cands, qv, self.text_model_id)
                return _per_doc(((doc_id, rowid, None) for doc_id, rowid, _ in best), n)
        join = (
            "SELECT c.doc_id, c.id FROM knn JOIN chunks c ON c.id = knn.rowid JOIN documents d ON d.doc_id = c.doc_id"
        )
        rows = self._knn("vec_text", "", join, qv, self.text_model_id, f, MAX_KNN if f.place else raw, raw)
        return _per_doc(((r[0], r[1], None) for r in rows), n)

    def _search_visual(self, qvec: np.ndarray, f: _Filters, n: int) -> list[Hit]:
        """Nearest frames, at most PER_DOC per document: one video can hold up to MAX_FRAMES near-identical
        frames, so candidates are fetched up to MAX_KNN before the cap."""
        model_id = self.visual_model_id()
        qv = np.asarray(qvec, dtype=np.float32).reshape(-1)
        if model_id is None or qv.size != VISUAL_DIM:
            return []
        if f.place:
            docs = self._place_candidates("SELECT d.id, d.doc_id, d.n_frames FROM documents d", f)
            if docs is not None and sum(r[2] for r in docs) <= EXACT_MAX:
                cands = [((did << FRAME_BITS) + i, doc_id) for did, doc_id, nf in docs for i in range(nf)]
                best = self._exact_knn("vec_visual", ", t_sec", cands, qv, model_id)
                return _per_doc(((doc_id, None, t) for doc_id, _, t in best), n)
        join = f"SELECT d.doc_id, knn.t_sec FROM knn JOIN documents d ON d.id = (knn.rowid >> {FRAME_BITS})"
        rows = self._knn("vec_visual", ", t_sec", join, qv, model_id, f, MAX_KNN, MAX_KNN)
        return _per_doc(((r[0], None, r[1]) for r in rows), n)

    def _recent(self, f: _Filters, k: int) -> list[Hit]:
        where, wp = f.sql()
        sql = f"SELECT d.doc_id FROM documents d WHERE {where} ORDER BY d.sort_at DESC LIMIT ?"
        return [(r[0], None, None) for r in self._db.execute(sql, [*wp, k])]

    def _assemble(self, q: str, lists: dict[str, list[Hit]], k: int) -> list[dict]:
        fused = rrf_fuse({s: [h[0] for h in hits] for s, hits in lists.items()})[:k]
        chunk_score: dict[int, float] = {}
        best_chunk: dict[str, int] = {}
        frame_t: dict[str, float] = {}
        for signal, hits in lists.items():
            w = WEIGHTS.get(signal, 1.0)
            for rank, (doc_id, cid, t) in enumerate(hits, 1):
                if cid is not None:
                    chunk_score[cid] = chunk_score.get(cid, 0.0) + w / (RRF_K + rank)
                    cur = best_chunk.get(doc_id)
                    if cur is None or chunk_score[cid] > chunk_score[cur]:
                        best_chunk[doc_id] = cid
                elif t is not None and doc_id not in frame_t:
                    frame_t[doc_id] = t
        doc_ids = [d for d, _ in fused]
        docs = {
            r["doc_id"]: r
            for r in self._db.execute(
                "SELECT doc_id, title, uri, modality, source_id, updated_at, taken_at FROM documents "
                f"WHERE doc_id IN ({', '.join('?' * len(doc_ids))})",
                doc_ids,
            )
        }
        for d in doc_ids:
            if d not in best_chunk:
                row = self._db.execute(
                    "SELECT id FROM chunks WHERE doc_id = ? ORDER BY field = 'meta', ordinal LIMIT 1", (d,)
                ).fetchone()
                if row:
                    best_chunk[d] = row[0]
        cids = [best_chunk[d] for d in doc_ids if d in best_chunk]
        chunks = {
            r["id"]: r
            for r in self._db.execute(
                f"SELECT id, text, field, page, t_start FROM chunks WHERE id IN ({', '.join('?' * len(cids))})", cids
            )
        }
        terms = _query_terms(q) if q else []
        present = {s: {h[0] for h in hits} for s, hits in lists.items()}
        out = []
        for doc_id, score in fused:
            d = docs.get(doc_id)
            if d is None:
                continue
            c = chunks.get(best_chunk.get(doc_id, -1))
            t_start = c["t_start"] if c is not None and c["t_start"] is not None else frame_t.get(doc_id)
            out.append(
                {
                    "doc_id": doc_id,
                    "title": d["title"],
                    "uri": d["uri"],
                    "modality": d["modality"],
                    "source_id": d["source_id"],
                    "updated_at": d["updated_at"],
                    "taken_at": d["taken_at"],
                    "score": round(score, 6),
                    "excerpt": make_excerpt(c["text"], terms) if c is not None else "",
                    "field": c["field"] if c is not None else None,
                    "page": c["page"] if c is not None else None,
                    "t_start": t_start,
                    "signals": [s for s in SIGNAL_ORDER if doc_id in present.get(s, ())],
                }
            )
        return out

    # -- reads --------------------------------------------------------------

    def _doc_row(self, doc_id: str) -> sqlite3.Row | None:
        return self._db.execute(f"SELECT * FROM documents WHERE doc_id = ? AND {_LIVE}", (doc_id,)).fetchone()

    def _doc_dict(self, row: sqlite3.Row) -> dict:
        out: dict[str, Any] = {}
        for f in _DOC_FIELDS:
            if f == "extra":
                out["extra"] = json.loads(row["extra_json"] or "{}")
            elif f in _LIST_COLS:
                out[f] = json.loads(row[f]) if row[f] is not None else None
            else:
                out[f] = row[f]
        out["ingested_at"] = row["ingested_at"]
        return out

    def get_document(self, doc_id: str) -> dict | None:
        """Document metadata plus chunk count; None for unknown, deleted or secret documents."""
        with self._lock:
            row = self._doc_row(doc_id)
            if row is None:
                return None
            out = self._doc_dict(row)
            out["n_chunks"] = self._db.execute("SELECT count(*) FROM chunks WHERE doc_id = ?", (doc_id,)).fetchone()[0]
            return out

    def fetch(self, doc_id: str, offset: int = 0, length: int = 4000) -> dict:
        """Slice of the document's text (chunks joined by field, overlaps removed) plus metadata."""
        with self._lock:
            row = self._doc_row(doc_id)
            if row is None:
                return {"doc_id": doc_id, "error": "not found"}
            out = self._doc_dict(row)
            rows = self._db.execute(
                "SELECT field, ordinal, page, text FROM chunks WHERE doc_id = ?", (doc_id,)
            ).fetchall()
        rows.sort(key=lambda r: (_FIELD_ORDER.get(r["field"], len(_FIELD_ORDER)), r["field"], r["ordinal"]))
        sections: list[str] = []
        field = page = None
        for r in rows:
            if r["field"] != field:
                sections.append(r["text"])
                field = r["field"]
            elif r["page"] == page:  # chunks overlap only within one page
                sections[-1] = _merge_overlap(sections[-1], r["text"])
            else:
                sections[-1] += "\n" + r["text"]
            page = r["page"]
        text = "\n\n".join(sections)
        offset = max(0, int(offset))
        piece = text[offset : offset + max(0, int(length))]
        end = offset + len(piece)
        out.update(
            offset=offset,
            length=len(piece),
            total_chars=len(text),
            next_offset=end if end < len(text) else None,
            text=piece,
        )
        return out

    def list_sources(self) -> list[dict]:
        """Sources seen in documents (live counts, last update) merged with the sources table."""
        with self._lock:
            out: dict[str, dict] = {}
            for r in self._db.execute("SELECT * FROM sources"):
                src = dict(zip(r.keys(), r, strict=True))
                del src["id"]
                out[r["source_id"]] = {**src, "documents": 0, "last_updated": None, "last_ingested": None}
            for r in self._db.execute(
                "SELECT source_id, count(*) AS n, max(coalesce(updated_at, created_at)) AS last_updated, "
                f"max(ingested_at) AS last_ingested FROM documents WHERE {_LIVE} GROUP BY source_id"
            ):
                s = out.setdefault(r["source_id"], {"source_id": r["source_id"], "kind": r["source_id"].split(":")[0]})
                s.update(documents=r["n"], last_updated=r["last_updated"], last_ingested=r["last_ingested"])
        return sorted(out.values(), key=lambda s: s["source_id"])

    def stats(self) -> dict:
        """Counts, models and file size, for the hub's `stats` tool."""
        with self._lock:

            def one(sql: str) -> Any:
                return self._db.execute(sql).fetchone()[0]

            out = {
                "documents": one(f"SELECT count(*) FROM documents WHERE {_LIVE}"),
                "deleted": one("SELECT count(*) FROM documents WHERE deleted_at IS NOT NULL"),
                "secret": one(f"SELECT count(*) FROM documents WHERE (sensitivity & {SENS_SECRET}) != 0"),
                "chunks": one("SELECT count(*) FROM chunks"),
                "vec_text": one("SELECT count(*) FROM vec_text"),
                "vec_visual": one("SELECT count(*) FROM vec_visual"),
                "by_modality": dict(
                    self._db.execute(f"SELECT modality, count(*) FROM documents WHERE {_LIVE} GROUP BY modality")
                ),
                "sources": one("SELECT count(*) FROM sources"),
                "last_ingested_at": one("SELECT max(ingested_at) FROM documents"),
                "models": [dict(r) for r in self._db.execute("SELECT * FROM models ORDER BY model_id")],
                "text_model_id": self.text_model_id,
                "visual_model_id": self.visual_model_id(),
                "sqlite_vec": one("SELECT vec_version()"),
            }
        if self.path != ":memory:":
            p = os.path.expanduser(self.path)
            out["db_bytes"] = sum(os.path.getsize(x) for x in (p, p + "-wal") if os.path.exists(x))
        return out
