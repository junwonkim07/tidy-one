"""Per-device index state (`state.sqlite`): what was indexed from each path, plus a chunk-vector cache.

The cache is keyed by (model_id, chunk_hash), so unchanged chunks are never re-embedded, even after
edits elsewhere in the file or a rename. Vectors are cached as float16 (far below int8 catalog precision).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Iterable, Iterator

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  content_hash TEXT,
  chunk_hashes TEXT NOT NULL DEFAULT '[]',
  model_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'indexed',
  indexed_at TEXT NOT NULL,
  batch TEXT,
  pushed_at TEXT,
  rules TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS files_doc ON files(doc_id);
CREATE INDEX IF NOT EXISTS files_batch ON files(batch);
CREATE TABLE IF NOT EXISTS vecs (
  model_id TEXT NOT NULL,
  chunk_hash TEXT NOT NULL,
  vec BLOB NOT NULL,
  PRIMARY KEY (model_id, chunk_hash)
) WITHOUT ROWID;
PRAGMA user_version = 1;
"""

STATUS_INDEXED = "indexed"
STATUS_SECRET = "secret"  # seen, never extracted or sent


class Busy(RuntimeError):
    """Another tidy process holds the lock."""


@contextlib.contextmanager
def exclusive_lock(path: str) -> Iterator[None]:
    """Non-blocking advisory lock on `path`; raises Busy if held. Released when the process exits."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(f"another tidy process holds {path}") from None
        yield
    finally:
        os.close(fd)


@dataclass
class FileRow:
    path: str  # NFC absolute path
    doc_id: str
    size: int
    mtime: float
    content_hash: str | None
    chunk_hashes: list[str] = field(default_factory=list)
    model_id: str = ""  # '' = indexed without vectors
    status: str = STATUS_INDEXED
    indexed_at: str = ""
    batch: str | None = None  # outbox batch holding the latest record for this path
    pushed_at: str | None = None
    rules: str = ""  # sensitivity rules / chunker version the file was last checked with


_COLS = (
    "path, doc_id, size, mtime, content_hash, chunk_hashes, model_id, status, indexed_at, batch, pushed_at, rules"
)


def _row(r: tuple) -> FileRow:
    return FileRow(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6], r[7], r[8], r[9], r[10], r[11])


def _private_file(path: str) -> None:
    """Create `path` owner-only before SQLite opens it (its -wal and -shm files copy the main file's mode)."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        pass
    for p in (path, path + "-wal", path + "-shm"):
        with contextlib.suppress(OSError):
            if os.stat(p).st_mode & 0o077:
                os.chmod(p, 0o600)


class State:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            folder = os.path.dirname(os.path.abspath(path))
            if not os.path.isdir(folder):
                os.makedirs(folder, mode=0o700, exist_ok=True)
            _private_file(path)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.executescript(SCHEMA)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(files)")}
        if "rules" not in cols:  # state written before the column existed: every file gets re-checked
            self._db.execute("ALTER TABLE files ADD COLUMN rules TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> State:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")

    def get_meta(self, key: str) -> str | None:
        r = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def get(self, path: str) -> FileRow | None:
        r = self._db.execute(f"SELECT {_COLS} FROM files WHERE path = ?", (path,)).fetchone()
        return _row(r) if r else None

    def rows(self) -> Iterator[FileRow]:
        for r in self._db.execute(f"SELECT {_COLS} FROM files ORDER BY path").fetchall():
            yield _row(r)

    def entries(self) -> list[tuple[str, str, str]]:
        """(path, doc_id, status) of every known file, without the chunk lists."""
        return self._db.execute("SELECT path, doc_id, status FROM files ORDER BY path").fetchall()

    def put(self, row: FileRow) -> None:
        self._db.execute(
            f"INSERT OR REPLACE INTO files({_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row.path, row.doc_id, row.size, row.mtime, row.content_hash, json.dumps(row.chunk_hashes),
             row.model_id, row.status, row.indexed_at, row.batch, row.pushed_at, row.rules),
        )

    def touch(self, path: str, size: int, mtime: float, rules: str | None = None) -> None:
        if rules is None:
            self._db.execute("UPDATE files SET size = ?, mtime = ? WHERE path = ?", (size, mtime, path))
        else:
            self._db.execute(
                "UPDATE files SET size = ?, mtime = ?, rules = ? WHERE path = ?", (size, mtime, rules, path)
            )

    def remove(self, path: str) -> None:
        self._db.execute("DELETE FROM files WHERE path = ?", (path,))

    def mark_pushed(self, batch: str, at: str) -> int:
        """Files whose latest record is in `batch` are now on the hub."""
        return self._db.execute("UPDATE files SET pushed_at = ? WHERE batch = ?", (at, batch)).rowcount

    def vectors(self, model_id: str, hashes: Iterable[str]) -> dict[str, np.ndarray]:
        """Cached unit vectors (float32) for the given chunk hashes; missing ones are absent."""
        out: dict[str, np.ndarray] = {}
        hs = list(dict.fromkeys(hashes))
        for i in range(0, len(hs), 500):
            part = hs[i : i + 500]
            q = f"SELECT chunk_hash, vec FROM vecs WHERE model_id = ? AND chunk_hash IN ({','.join('?' * len(part))})"
            for h, blob in self._db.execute(q, (model_id, *part)):
                v = np.frombuffer(blob, dtype="<f2").astype(np.float32)
                n = float(np.linalg.norm(v))
                out[h] = v / n if n else v
        return out

    def put_vectors(self, model_id: str, vecs: dict[str, np.ndarray]) -> None:
        with self.transaction():
            self._db.executemany(
                "INSERT OR REPLACE INTO vecs(model_id, chunk_hash, vec) VALUES (?, ?, ?)",
                [(model_id, h, np.asarray(v, dtype="<f2").tobytes()) for h, v in vecs.items()],
            )

    def gc_vectors(self) -> int:
        """Drop cached vectors no indexed file refers to any more (under the model it was indexed with)."""
        db = self._db
        with self.transaction():
            db.execute(
                "CREATE TEMP TABLE IF NOT EXISTS live(model_id TEXT, h TEXT, PRIMARY KEY (model_id, h)) WITHOUT ROWID"
            )
            db.execute("DELETE FROM live")
            db.execute(
                "INSERT OR IGNORE INTO live SELECT f.model_id, j.value FROM files f, json_each(f.chunk_hashes) j "
                "WHERE f.model_id != ''"
            )
            n = db.execute(
                "DELETE FROM vecs WHERE (model_id, chunk_hash) NOT IN (SELECT model_id, h FROM live)"
            ).rowcount
            db.execute("DELETE FROM live")
        return n

    def counts(self) -> dict:
        db = self._db
        by_status = dict(db.execute("SELECT status, count(*) FROM files GROUP BY status").fetchall())
        chunks = db.execute(
            "SELECT coalesce(sum(json_array_length(chunk_hashes)), 0) FROM files WHERE status = ?", (STATUS_INDEXED,)
        ).fetchone()[0]
        unpushed = db.execute(
            "SELECT count(*) FROM files WHERE status = ? AND (pushed_at IS NULL OR pushed_at < indexed_at)",
            (STATUS_INDEXED,),
        ).fetchone()[0]
        last = db.execute("SELECT max(indexed_at), max(pushed_at) FROM files").fetchone()
        return {
            "files": by_status.get(STATUS_INDEXED, 0),
            "secret_skipped": by_status.get(STATUS_SECRET, 0),
            "chunks": chunks,
            "unpushed": unpushed,
            "cached_vectors": db.execute("SELECT count(*) FROM vecs").fetchone()[0],
            "last_indexed_at": last[0],
            "last_pushed_at": last[1],
        }
