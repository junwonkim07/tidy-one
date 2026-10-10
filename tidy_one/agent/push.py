"""`tidy push`: send outbox batches to the hub over ssh (or apply them to a local catalog).

Batches go oldest first and stop at the first failure, so a later tombstone never overtakes the
upsert it cancels. A batch counts as delivered only when the hub applied every line: if it reports
any `failed` line (or `tidy ingest` exits non-zero), the batch stays in the outbox and is sent again
whole, which is safe because upserts and tombstones are idempotent. Every line is re-checked before
it leaves: records flagged SENS_SECRET and lines that do not parse are dropped, never sent.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Any, Callable, Iterable

from tidy_one.agent.config import Config
from tidy_one.agent.run import stamp
from tidy_one.agent.state import State, exclusive_lock
from tidy_one.model import SENS_SECRET, parse_line

log = logging.getLogger("tidy_one.agent")

SSH_DEFAULT_ARGS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30"]


class PushError(RuntimeError):
    pass


@dataclass
class PushStats:
    target: str = ""
    sent: list[str] = field(default_factory=list)
    lines: int = 0
    blocked: int = 0  # secret or unparseable lines held back
    counts: dict[str, int] = field(default_factory=dict)  # summed hub/catalog ingest counts
    pending: int = 0  # batches still in the outbox afterwards
    pruned: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def pending_batches(outbox_dir: str) -> list[Path]:
    d = Path(outbox_dir)
    return sorted(p for p in d.glob("*.jsonl") if p.is_file()) if d.is_dir() else []


def sent_batches(outbox_dir: str) -> list[Path]:
    d = Path(outbox_dir) / "sent"
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def safe_line(line: str) -> bool:
    """True if the line parses as a wire record and is not flagged SENS_SECRET."""
    try:
        obj = json.loads(line)
    except ValueError:
        return False
    if not isinstance(obj, dict):
        return False
    if obj.get("op") == "delete":
        return isinstance(obj.get("doc_id"), str)
    doc = obj.get("document")
    if obj.get("op") != "upsert" or not isinstance(doc, dict):
        return False
    try:
        return not int(doc.get("sensitivity") or 0) & SENS_SECRET
    except (TypeError, ValueError):
        return False


def filtered_lines(path: Path, stats: PushStats) -> Iterable[str]:
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if safe_line(line):
                stats.lines += 1
                yield line
            else:
                stats.blocked += 1
                log.warning("held back a secret or malformed line in %s", path.name)


def apply_lines(lines: Iterable[str], catalog: Any) -> dict[str, int]:
    """Minimal ingest used when the hub package is not installed: apply each line, count failures."""
    counts = {"upserted": 0, "deleted": 0, "failed": 0}  # same count keys as tidy_one.hub.ingest
    for line in lines:
        try:
            op, payload = parse_line(line)
            if op == "delete":
                catalog.delete(*payload)
                counts["deleted"] += 1
            else:
                catalog.apply(payload)
                counts["upserted"] += 1
        except Exception as e:
            counts["failed"] += 1
            log.warning("ingest: bad line: %s", type(e).__name__)
    return counts


def ingest_fn() -> Callable[[Iterable[str], Any], dict]:
    """The hub's `ingest(lines, catalog)` when available, else `apply_lines`."""
    for module in ("tidy_one.hub.ingest", "tidy_one.hub"):
        try:
            fn = getattr(importlib.import_module(module), "ingest", None)
        except ImportError:
            continue
        if callable(fn):
            return fn
    return apply_lines


def _merge(total: dict[str, int], counts: Any) -> None:
    if isinstance(counts, dict):
        for k, v in counts.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                total[k] = total.get(k, 0) + int(v)


def _parse_counts(stdout: bytes) -> dict:
    for line in reversed(stdout.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    return {}


def _failed(counts: Any) -> int:
    """Lines the hub could not apply, per its ingest counts."""
    if not isinstance(counts, dict):
        return 0
    try:
        return int(counts.get("failed") or 0)
    except (TypeError, ValueError):
        return 1


def _first_error(counts: Any) -> str:
    errors = counts.get("errors") if isinstance(counts, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return f"; first: line {errors[0].get('line_no')}: {errors[0].get('error')}"
    return ""


def ssh_command(cfg: Config) -> list[str]:
    if not cfg.hub.ssh:
        raise PushError("hub.ssh is not set in the config; set it, or use `tidy push --local [DB]`")
    return ["ssh", *SSH_DEFAULT_ARGS, *cfg.hub.ssh_args, cfg.hub.ssh, cfg.hub.remote_cmd]


def _send_ssh(cmd: list[str], data: IO[bytes], timeout: float, run: Callable[..., Any]) -> dict:
    try:
        proc = run(cmd, stdin=data, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PushError(f"ssh timed out after {timeout:.0f}s") from None
    except OSError as e:
        raise PushError(f"cannot run ssh: {e}") from None
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        counts = _parse_counts(proc.stdout or b"")
        detail = f"{_failed(counts)} lines not applied{_first_error(counts)}" if _failed(counts) else ""
        raise PushError(f"ssh exited {proc.returncode}: {detail or (err[-1] if err else 'no output')}")
    return _parse_counts(proc.stdout or b"")


def _prune_sent(outbox_dir: str, keep_days: int) -> int:
    if keep_days <= 0:
        return 0
    cutoff = time.time() - keep_days * 86400
    n = 0
    for p in sent_batches(outbox_dir):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n


def push(
    cfg: Config,
    *,
    local_db: str | None = None,
    keep: bool = False,
    run: Callable[..., Any] = subprocess.run,
) -> PushStats:
    """Send pending batches oldest first. With `local_db`, apply them to that catalog instead of ssh.

    Sent batches move to `outbox/sent/` (unless `keep`) and their files are marked pushed in the state.
    Raises `Busy` if another push holds the lock; failures, including lines the hub could not apply,
    stop the loop with the batch still pending and land in `stats.error`.
    """
    stats = PushStats(target=f"local:{local_db}" if local_db else (cfg.hub.ssh or ""))
    os.makedirs(cfg.outbox_dir, exist_ok=True)
    with exclusive_lock(os.path.join(cfg.outbox_dir, ".push.lock")):
        batches = pending_batches(cfg.outbox_dir)
        cmd = ssh_command(cfg) if batches and not local_db else None
        catalog = None
        state = State(cfg.state_db) if batches and os.path.exists(cfg.state_db) else None
        try:
            if local_db and batches:
                from tidy_one.catalog import Catalog

                catalog = Catalog(local_db, durable=True)
            ingest = ingest_fn()
            for batch in batches:
                try:
                    if catalog is not None:
                        counts = ingest(filtered_lines(batch, stats), catalog)
                    else:
                        with tempfile.TemporaryFile(dir=cfg.outbox_dir) as tmp:
                            for line in filtered_lines(batch, stats):
                                tmp.write(line.encode("utf-8") + b"\n")
                            tmp.flush()
                            tmp.seek(0)
                            counts = _send_ssh(cmd, tmp, cfg.hub.timeout, run)
                except PushError as e:
                    stats.error = f"{batch.name}: {e}"
                    log.error("push stopped at %s: %s", batch.name, e)
                    break
                _merge(stats.counts, counts)
                failed = _failed(counts)
                if failed:  # not delivered: keep the batch (and the files unpushed) for the next push
                    stats.error = f"{batch.name}: the hub could not apply {failed} lines{_first_error(counts)}"
                    log.error("push stopped at %s: %s", batch.name, stats.error)
                    break
                if not keep:
                    sent = Path(cfg.outbox_dir) / "sent"
                    sent.mkdir(exist_ok=True)
                    dest = sent / batch.name
                    os.replace(batch, dest)
                    os.utime(dest)
                    if state is not None:
                        state.mark_pushed(batch.name, stamp())
                stats.sent.append(batch.name)
                log.info("pushed %s to %s %s", batch.name, stats.target, json.dumps(counts, default=str))
        finally:
            if catalog is not None:
                catalog.close()
            if state is not None:
                state.close()
        stats.pending = len(pending_batches(cfg.outbox_dir))
        stats.pruned = _prune_sent(cfg.outbox_dir, cfg.keep_sent_days)
    return stats
