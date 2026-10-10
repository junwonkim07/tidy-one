"""`tidy ingest`: apply outbox JSON lines (upserts and tombstones) from device agents to the catalog.

Lines stream through one at a time. A line that fails to decode, parse, validate or apply is
recorded in `errors` and skipped; the rest of the stream still lands. A storage error (database
locked, disk full, I/O) stops the stream instead: every later line would fail the same way, and
the device re-sends the whole batch, since any `failed` line keeps it in the outbox.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable, Iterable
from typing import Any, get_args

from tidy_one.catalog import Catalog
from tidy_one.model import Modality, Record, parse_line

BATCH = 200  # progress callback interval, in records
MAX_ERRORS = 100  # errors listed in the result; `failed` keeps counting past it
ERROR_CHARS = 300

_MODALITIES = frozenset(get_args(Modality))


def _check_record(rec: Record) -> None:
    doc = rec.document
    for name in ("doc_id", "source_id"):
        v = getattr(doc, name)
        if not isinstance(v, str) or not v.strip():
            raise TypeError(f"document.{name} must be a non-empty string")
    if doc.modality not in _MODALITIES:
        raise ValueError(f"document.modality must be one of {sorted(_MODALITIES)}")
    if not isinstance(doc.sensitivity, int):
        raise TypeError("document.sensitivity must be an integer")
    for c in rec.chunks:
        if not isinstance(c.text, str) or not isinstance(c.ordinal, int):
            raise TypeError("every chunk needs text (string) and ordinal (integer)")


def _describe(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:ERROR_CHARS]


def ingest(
    lines: Iterable[str | bytes],
    catalog: Catalog,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Apply wire-format lines to `catalog` and return counts.

    Result: `{upserted, deleted, failed, errors: [{line_no, error}]}`; `line_no` is 1-based over the
    input including blank lines. Each record commits on its own (`Catalog.apply` owns the
    transaction), so a bad record never rolls back its neighbours. `on_progress` receives the
    running counts every `BATCH` records.
    """
    counts: dict[str, Any] = {"upserted": 0, "deleted": 0, "failed": 0, "errors": []}
    done = 0
    for line_no, raw in enumerate(lines, 1):
        try:
            line = (raw.decode("utf-8") if isinstance(raw, bytes) else raw).strip()
            if not line:
                continue
            op, payload = parse_line(line)
            if op == "delete":
                doc_id, deleted_at = payload
                if not isinstance(doc_id, str) or not doc_id or not isinstance(deleted_at, str) or not deleted_at:
                    raise TypeError("delete needs doc_id and deleted_at strings")
                catalog.delete(doc_id, deleted_at)
                counts["deleted"] += 1
            else:
                _check_record(payload)
                catalog.apply(payload)
                counts["upserted"] += 1
        except (sqlite3.OperationalError, OSError) as e:  # storage trouble: the rest would fail too
            counts["failed"] += 1
            if len(counts["errors"]) < MAX_ERRORS:
                counts["errors"].append({"line_no": line_no, "error": _describe(e) + " (ingest stopped here)"})
            break
        except Exception as e:  # noqa: BLE001 - one bad line never stops the ingest
            counts["failed"] += 1
            if len(counts["errors"]) < MAX_ERRORS:
                counts["errors"].append({"line_no": line_no, "error": _describe(e)})
        done += 1
        if on_progress is not None and done % BATCH == 0:
            on_progress(counts)
    return counts


def ingest_file(
    path: str, catalog: Catalog, on_progress: Callable[[dict[str, Any]], None] | None = None
) -> dict[str, Any]:
    """`tidy ingest [FILE|-]`: ingest a JSONL file, or stdin for '-'. Bytes are decoded per line."""
    if path == "-":
        return ingest(sys.stdin.buffer, catalog, on_progress)
    with open(path, "rb") as f:
        return ingest(f, catalog, on_progress)
