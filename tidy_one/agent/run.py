"""`tidy index`: scan roots, extract changed files, embed only new chunks, write outbox batches.

Change detection: unchanged (size, mtime) skips the file; otherwise the sha256 decides whether to
re-extract; after chunking, only chunk hashes missing from the vector cache are embedded. Files that
vanish from a complete scan, or that no configured root covers any more, become tombstones. When the
sensitivity rules or the chunker change, every file is checked again once: newly secret ones are
withdrawn, and only those whose chunks changed are sent again. State rows are committed only after the
batch holding their record is renamed into place, so a crash re-does work instead of losing it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote

import numpy as np

from tidy_one.agent.config import Config
from tidy_one.agent.state import STATUS_INDEXED, STATUS_SECRET, FileRow, State, exclusive_lock
from tidy_one.extract import chunk_blocks, extract_file, scan
from tidy_one.extract.chunk import CHUNKER_VERSION
from tidy_one.extract.scan import SF_DATALESS
from tidy_one.extract.sensitive import RULES_VERSION
from tidy_one.model import SENS_SECRET, Chunk, Document, Record, delete_to_json, record_to_json

log = logging.getLogger("tidy_one.agent")

MAX_BATCH_RECORDS = 500
MAX_BATCH_BYTES = 64 * 1024 * 1024
EMBED_POOL = 128  # chunks gathered across documents before one encode call (and before they are written out)
ENCODE_BATCH = 16
MAX_EMBED_FAILURES = 3  # documents in a row the encoder fails on before the run gives up
CHECK_STAMP = f"{RULES_VERSION}-c{CHUNKER_VERSION}"  # what a file was last checked with (FileRow.rules)


class Encoder(Protocol):
    model_id: str
    dim: int

    def encode_passages(self, texts: list[str], batch_size: int = 16) -> np.ndarray: ...


@dataclass
class IndexStats:
    device_id: str = ""
    scanned: int = 0
    unchanged: int = 0
    touched: int = 0  # mtime changed, bytes did not
    new: int = 0
    changed: int = 0
    secret: int = 0
    errors: int = 0
    tombstoned: int = 0
    unrooted: int = 0  # of those: under no configured root any more (root removed or narrowed)
    kept_offline: int = 0  # vanished from the scan but still on disk (iCloud-evicted or unreadable)
    chunks: int = 0
    embedded: int = 0
    cached: int = 0
    records: int = 0
    batches: list[str] = field(default_factory=list)
    limited: bool = False
    dry_run: bool = False
    vectors_gc: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def file_doc_id(device_id: str, path: str) -> str:
    return f"file:{device_id}:{hashlib.sha1(nfc(path).encode()).hexdigest()[:16]}"


def file_uri(path: str) -> str:
    return "file://" + quote(nfc(path), safe="/")


def iso_utc(ts: float | None = None) -> str:
    d = datetime.fromtimestamp(ts, UTC) if ts is not None else datetime.now(UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(ts: float) -> str:
    """ISO 8601 in this device's local time with its UTC offset ('2024-03-05T08:30:00+09:00'): the same
    instant as UTC, but the date part is the owner's calendar day, which the hub's date filters compare
    against and which the meta chunk shows."""
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def stamp() -> str:
    """Microsecond UTC timestamp for state bookkeeping (indexed_at / pushed_at ordering)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def default_encoder(cfg: Config) -> Encoder:
    """KURE-v1 passages on the fastest local backend (`$TIDY_EMBED_BACKEND`, default auto: Apple GPU and
    Neural Engine on Apple Silicon, fp32 ONNX on the CPU elsewhere); `TIDY_FAKE_ENCODER=1` swaps in the
    hash-based test encoder."""
    if os.environ.get("TIDY_FAKE_ENCODER") == "1":
        from tidy_one.embed.fake import FakeEncoder

        return FakeEncoder()
    from tidy_one.embed.backends import passage_encoder

    enc = passage_encoder("kure-v1", model_dir=cfg.model_dir)
    log.info("embedding backend: %s", type(enc).__name__)
    return enc


Op = tuple[str, Any]  # ("put", FileRow) | ("remove", path) | ("none", None)


class OutboxWriter:
    """Writes `<UTC ts>-<n>.jsonl` batches (<= max_records lines) via `.tmp` + rename.

    `on_commit(name, ops)` runs right after a batch is renamed into place.
    """

    def __init__(
        self,
        outbox_dir: str,
        on_commit: Callable[[str, list[Op]], None],
        max_records: int = MAX_BATCH_RECORDS,
        max_bytes: int = MAX_BATCH_BYTES,
    ):
        self.dir = Path(outbox_dir)
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.on_commit = on_commit
        self.max_records = max_records
        self.max_bytes = max_bytes
        self.ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.n = 0
        self.names: list[str] = []
        self._f: Any = None
        self._name = ""
        self._ops: list[Op] = []
        self._count = 0
        self._bytes = 0

    def _open(self) -> None:
        while True:
            self.n += 1
            name = f"{self.ts}-{self.n:04d}.jsonl"
            if not (self.dir / name).exists() and not (self.dir / "sent" / name).exists():
                break
        self._name = name
        fd = os.open(self.dir / (name + ".tmp"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never world-readable
        self._f = os.fdopen(fd, "w", encoding="utf-8")
        self._ops, self._count, self._bytes = [], 0, 0

    def add(self, line: str, op: Op) -> None:
        if self._f is None:
            self._open()
        data = line + "\n"
        self._f.write(data)
        self._ops.append(op)
        self._count += 1
        self._bytes += len(data.encode("utf-8"))
        if self._count >= self.max_records or self._bytes >= self.max_bytes:
            self.close()

    def close(self) -> None:
        if self._f is None:
            return
        f, self._f = self._f, None
        f.flush()
        os.fsync(f.fileno())
        f.close()
        os.replace(self.dir / (self._name + ".tmp"), self.dir / self._name)
        self.names.append(self._name)
        self.on_commit(self._name, self._ops)

    def discard(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None
            (self.dir / (self._name + ".tmp")).unlink(missing_ok=True)


@dataclass
class _Pending:
    doc: Document
    chunks: list[Chunk]
    row: FileRow


def _present_but_unscanned(path: str, root: str) -> bool:
    """True when `path` still exists but the scan could not see it: an ancestor or the file is an
    iCloud placeholder, or permissions (e.g. macOS privacy prompts) hide it. Such files are kept."""
    rel = os.path.relpath(path, root)
    cur = root
    parts = [] if rel == "." else rel.split(os.sep)
    for part in parts:
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except (FileNotFoundError, NotADirectoryError):
            return False
        except OSError:
            return True
        if getattr(st, "st_flags", 0) & SF_DATALESS:
            return True
    return False


def _root_ok(root: str) -> bool:
    try:
        if os.path.isdir(root):
            os.listdir(root)
            return True
        return os.path.isfile(root)
    except OSError:
        return False


def _root_of(path: str, roots: list[str]) -> str | None:
    best = None
    for r in roots:
        if (path == r or path.startswith(r.rstrip(os.sep) + os.sep)) and (best is None or len(r) > len(best)):
            best = r
    return best


class Indexer:
    def __init__(
        self,
        cfg: Config,
        state: State,
        encoder: Encoder | None,
        *,
        dry_run: bool = False,
        limit: int | None = None,
        progress_every: int = 500,
    ):
        self.cfg = cfg
        self.state = state
        self.encoder = encoder
        self.model_id = encoder.model_id if encoder is not None else ""
        # the model's tokenizer, so no chunk is longer than the model reads (None: the encoder has none)
        self.count_tokens = getattr(encoder, "count_tokens", None)
        self.max_tokens = int(getattr(encoder, "max_len", 512))
        self.dry_run = dry_run
        self.limit = limit
        self.progress_every = progress_every
        self.stats = IndexStats(dry_run=dry_run)
        self.device_id = self._device_id()
        self.stats.device_id = self.device_id
        self.writer: OutboxWriter | None = None
        self.pending: list[_Pending] = []
        self.pending_new = 0
        self.embed_failures = 0
        self.t0 = time.monotonic()

    def _device_id(self) -> str:
        stored = self.state.get_meta("device_id")
        if self.cfg.device_id_pinned or stored is None:
            if stored is not None and stored != self.cfg.device_id:
                log.warning("device_id changed from %s to %s: documents get new ids", stored, self.cfg.device_id)
            if not self.dry_run:
                self.state.set_meta("device_id", self.cfg.device_id)
            return self.cfg.device_id
        return stored

    def _commit(self, name: str, ops: list[Op]) -> None:
        with self.state.transaction():
            for kind, arg in ops:
                if kind == "put":
                    arg.batch = name
                    self.state.put(arg)
                elif kind == "remove":
                    self.state.remove(arg)
        self.stats.batches.append(name)
        log.info("wrote %s (%d records)", name, len(ops))

    def _emit(self, line: str, op: Op) -> None:
        if self.writer is None:
            self.writer = OutboxWriter(self.cfg.outbox_dir, self._commit)
        self.writer.add(line, op)
        self.stats.records += 1

    def _fresh(self, row: FileRow | None, doc_id: str) -> bool:
        """Row still describes what this run would produce (same id, status, rules and chunker, and vectors
        if embedding)."""
        if row is None or row.doc_id != doc_id or row.rules != CHECK_STAMP:
            return False
        return row.status == STATUS_SECRET or self.encoder is None or row.model_id == self.model_id

    def run(self) -> IndexStats:
        cfg = self.cfg
        seen: set[str] = set()
        processed = 0
        if not self.dry_run:
            for tmp in Path(cfg.outbox_dir).glob("*.jsonl.tmp"):  # left by a crashed run (we hold the lock)
                tmp.unlink(missing_ok=True)
        try:
            for fi in scan(cfg.roots, cfg.excludes):
                path = nfc(fi.path)
                seen.add(path)
                self.stats.scanned += 1
                if self.progress_every and self.stats.scanned % self.progress_every == 0:
                    self._progress()
                row = self.state.get(path)
                doc_id = file_doc_id(self.device_id, path)
                if row is not None and row.size == fi.size and row.mtime == fi.mtime and self._fresh(row, doc_id):
                    self.stats.unchanged += 1
                    continue
                if self.limit is not None and processed >= self.limit:
                    self.stats.limited = True
                    break
                processed += 1
                if self.dry_run:
                    if row is None:
                        self.stats.new += 1
                    else:
                        self.stats.changed += 1
                    continue
                try:
                    self._file(fi.path, path, fi.size, fi.mtime, fi.ctime, row, doc_id)
                except Exception as e:  # one bad file never stops the run
                    self.stats.errors += 1
                    log.warning("skipped %s: %s: %s", path, type(e).__name__, e)
                if self.pending_new >= EMBED_POOL:
                    self._flush()
            self._flush()
            if not self.stats.limited:
                self._tombstones(seen)
            if self.writer is not None:
                self.writer.close()
        except BaseException:
            if self.writer is not None:
                self.writer.discard()
            raise
        if not self.dry_run and not self.stats.limited:
            self.stats.vectors_gc = self.state.gc_vectors()
        self.stats.seconds = round(time.monotonic() - self.t0, 3)
        return self.stats

    def _progress(self) -> None:
        s = self.stats
        dt = max(time.monotonic() - self.t0, 1e-6)
        log.info(
            "scanned %d · new %d · changed %d · embedded %d chunks (%.1f/s) · errors %d",
            s.scanned, s.new, s.changed, s.embedded, s.embedded / dt, s.errors,
        )

    def _file(
        self, disk_path: str, path: str, size: int, mtime: float, ctime: float, row: FileRow | None, doc_id: str
    ) -> None:
        content_hash = sha256_file(disk_path)
        if row is not None and row.content_hash == content_hash and self._fresh(row, doc_id):
            self.state.touch(path, size, mtime)
            self.stats.touched += 1
            return
        ex = extract_file(disk_path)
        now = stamp()
        if ex.sensitivity & SENS_SECRET:
            self.stats.secret += 1
            secret_row = FileRow(path, doc_id, size, mtime, content_hash, [], "", STATUS_SECRET, now, rules=CHECK_STAMP)
            if row is not None and row.status == STATUS_INDEXED:
                self._emit(delete_to_json(row.doc_id, iso_utc()), ("put", secret_row))
                self.stats.tombstoned += 1
            else:
                self.state.put(secret_row)
            return
        chunks = chunk_blocks(ex.text_blocks, title=ex.title, path=path, created=ctime, modified=mtime, doc_id=doc_id,
                              count_tokens=self.count_tokens, max_tokens=self.max_tokens)
        if (
            row is not None
            and row.status == STATUS_INDEXED
            and row.doc_id == doc_id
            and row.content_hash == content_hash
            and (self.encoder is None or row.model_id == self.model_id)
            and row.chunk_hashes == [c.chunk_hash for c in chunks]
        ):  # same bytes re-checked under new rules: still not secret, and the hub already has these chunks
            self.state.touch(path, size, mtime, CHECK_STAMP)
            self.stats.touched += 1
            return
        if row is not None and row.status == STATUS_INDEXED and row.doc_id != doc_id:  # device_id changed
            self._emit(delete_to_json(row.doc_id, iso_utc()), ("none", None))
        if row is None:
            self.stats.new += 1
        else:
            self.stats.changed += 1
        doc = Document(
            doc_id=doc_id,
            source_id=f"file:{self.device_id}",
            native_id=path,
            modality=ex.modality,
            title=ex.title,
            uri=file_uri(path),
            mime=ex.mime,
            created_at=iso_local(ctime),
            updated_at=iso_local(mtime),
            size_bytes=size,
            content_hash=content_hash,
            device_id=self.device_id,
            sensitivity=ex.sensitivity,
            extra=ex.extra,
        )
        new_row = FileRow(
            path, doc_id, size, mtime, content_hash, [c.chunk_hash for c in chunks], self.model_id, STATUS_INDEXED,
            now, pushed_at=row.pushed_at if row is not None else None, rules=CHECK_STAMP,
        )
        self.pending.append(_Pending(doc, chunks, new_row))
        self.stats.chunks += len(chunks)
        self.pending_new += len(chunks)  # with or without an encoder, so --no-embed also writes as it goes

    def _vectors(self, pending: list[_Pending]) -> dict[str, np.ndarray]:
        """Vectors for every chunk of `pending`: cached ones from the state, the rest embedded and cached."""
        assert self.encoder is not None
        texts = {c.chunk_hash: c.text for p in pending for c in p.chunks}
        vecs = self.state.vectors(self.model_id, texts)
        missing = [h for h in texts if h not in vecs]
        self.stats.cached += len(texts) - len(missing)
        if missing:
            out = self.encoder.encode_passages([texts[h] for h in missing], batch_size=ENCODE_BATCH)
            new = {h: np.asarray(v, dtype=np.float32) for h, v in zip(missing, out, strict=True)}
            self.state.put_vectors(self.model_id, new)
            vecs.update(new)
            self.stats.embedded += len(missing)
            log.info("embedded %d chunks (%d this run, %.1f/s)", len(missing), self.stats.embedded,
                     self.stats.embedded / max(time.monotonic() - self.t0, 1e-6))
        return vecs

    def _flush(self) -> None:
        """Embed what the pending documents need (one encode call across documents) and emit them.

        If the pooled call fails, documents are retried one by one and those that still fail are
        skipped (retried next run); several failures in a row mean the encoder itself is broken."""
        if not self.pending:
            return
        pending, self.pending, self.pending_new = self.pending, [], 0
        vecs: dict[str, np.ndarray] = {}
        if self.encoder is not None:
            try:
                vecs = self._vectors(pending)
                self.embed_failures = 0
            except Exception:
                ok = []
                for p in pending:
                    try:
                        vecs.update(self._vectors([p]))
                        ok.append(p)
                        self.embed_failures = 0
                    except Exception as e:
                        self.embed_failures += 1
                        self.stats.errors += 1
                        log.warning("embedding failed for %s: %s", p.doc.native_id, type(e).__name__)
                        if self.embed_failures >= MAX_EMBED_FAILURES:
                            raise
                pending = ok
        for p in pending:
            vec_text = {self.model_id: {c.chunk_id: vecs[c.chunk_hash] for c in p.chunks}} if self.encoder else {}
            self._emit(record_to_json(Record(p.doc, p.chunks, vec_text)), ("put", p.row))

    def _tombstones(self, seen: set[str]) -> None:
        roots = [nfc(os.path.realpath(r)) for r in self.cfg.roots]
        ok = {r: _root_ok(r) for r in roots}
        for r, good in ok.items():
            if not good:
                log.warning("root not readable, keeping its documents: %s", r)
        for path, doc_id, status in self.state.entries():
            if path in seen:
                continue
            root = _root_of(path, roots)
            if root is None:  # its root was removed from the config or narrowed: the owner took it out
                if status == STATUS_INDEXED:
                    self.stats.unrooted += 1
            elif not ok[root]:
                continue
            elif _present_but_unscanned(path, root):
                self.stats.kept_offline += 1
                continue
            if status == STATUS_INDEXED:
                self.stats.tombstoned += 1
                if not self.dry_run:
                    self._emit(delete_to_json(doc_id, iso_utc()), ("remove", path))
            elif not self.dry_run:
                self.state.remove(path)
        if self.stats.unrooted:
            log.info("removing %d documents no configured root covers any more", self.stats.unrooted)


def index(
    cfg: Config,
    *,
    encoder: Encoder | None = None,
    embed: bool = True,
    limit: int | None = None,
    dry_run: bool = False,
    progress_every: int = 500,
) -> IndexStats:
    """One incremental pass over `cfg.roots`. Raises `Busy` if another index run holds the lock."""
    if embed and encoder is None:
        encoder = default_encoder(cfg)  # lazy: nothing loads until the first encode
        if not dry_run and not getattr(encoder, "available", True):
            from tidy_one.embed.text import ModelFilesMissing

            raise ModelFilesMissing(
                f"embedding model not found under {cfg.model_dir}; run `uv run --extra export python "
                "scripts/export_kure.py`, or index without vectors using --no-embed"
            )
    if not embed:
        encoder = None
    os.makedirs(os.path.dirname(cfg.state_db), exist_ok=True)
    with exclusive_lock(cfg.state_db + ".lock"), State(cfg.state_db) as state:
        stats = Indexer(cfg, state, encoder, dry_run=dry_run, limit=limit, progress_every=progress_every).run()
    log.debug(
        "%sscanned %d · new %d · changed %d · unchanged %d · secret %d · tombstoned %d · errors %d · "
        "embedded %d (cached %d) · %d records in %d batches · %.1fs",
        "dry run: " if dry_run else "", stats.scanned, stats.new, stats.changed, stats.unchanged, stats.secret,
        stats.tombstoned, stats.errors, stats.embedded, stats.cached, stats.records, len(stats.batches), stats.seconds,
    )
    return stats

