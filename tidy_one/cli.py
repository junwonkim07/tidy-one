"""`tidy` command line: device agent (init, index, push, status) and hub/debug commands (ingest, serve, search)."""

from __future__ import annotations

import argparse
import inspect
import io
import json
import logging
import os
import sys
from typing import Any
from urllib.parse import unquote

EXIT_BUSY = 75  # EX_TEMPFAIL: another run holds the lock; launchd simply tries again next interval


def _config(args: argparse.Namespace) -> Any:
    from tidy_one.agent.config import load_config

    return load_config(args.config)


def _db(args: argparse.Namespace) -> str:
    if getattr(args, "db", None):
        return os.path.abspath(os.path.expanduser(args.db))
    return _config(args).catalog_db


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str))


def cmd_init(args: argparse.Namespace) -> int:
    from tidy_one.agent.config import write_default_config

    path, created = write_default_config(args.config)
    print(f"{'wrote' if created else 'exists, left unchanged:'} {path}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from tidy_one.agent.run import index

    stats = index(_config(args), embed=not args.no_embed, limit=args.limit, dry_run=args.dry_run,
                  progress_every=args.progress)
    if args.json:
        _print_json(stats.as_dict())
    else:
        s = stats
        print(
            f"{'dry run: ' if s.dry_run else ''}{s.scanned} scanned, {s.new} new, {s.changed} changed, "
            f"{s.unchanged} unchanged, {s.secret} secret skipped, {s.tombstoned} removed, {s.errors} errors; "
            f"{s.embedded} chunks embedded ({s.cached} cached); {s.records} records in {len(s.batches)} batches"
            + (" (stopped at --limit)" if s.limited else "")
        )
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    from tidy_one.agent.push import push

    cfg = _config(args)
    local = args.local
    if local == "":
        local = cfg.catalog_db
    stats = push(cfg, local_db=os.path.abspath(os.path.expanduser(local)) if local else None, keep=args.keep)
    if args.json:
        _print_json(stats.as_dict())
    else:
        counts = ", ".join(f"{k} {v}" for k, v in stats.counts.items())
        print(
            f"{len(stats.sent)} batches pushed to {stats.target} ({stats.lines} lines"
            + (f"; {counts}" if counts else "") + f"); {stats.pending} pending"
            + (f"; {stats.blocked} lines held back" if stats.blocked else "")
            + (f"; error: {stats.error}" if stats.error else "")
        )
    return 1 if stats.error else 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from tidy_one.agent.push import ingest_fn
    from tidy_one.catalog import Catalog

    def lines(f: Any) -> Any:
        for raw in f:
            if raw.strip():
                yield raw.strip()

    with Catalog(_db(args), durable=True) as catalog:  # the device drops its copy once we exit 0
        if args.file in (None, "-"):  # bytes, so a non-UTF-8 locale on the hub cannot break decoding
            stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
            counts = ingest_fn()(lines(stdin), catalog)
        else:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                counts = ingest_fn()(lines(f), catalog)
    print(json.dumps(counts, default=str))
    failed = (counts.get("failed") or 0) if isinstance(counts, dict) else 0
    if failed:  # non-zero, so `tidy push` keeps the batch and sends it again
        errors = counts.get("errors") or []
        first = f"; first: line {errors[0].get('line_no')}: {errors[0].get('error')}" if errors else ""
        print(f"tidy ingest: {failed} lines not applied{first}", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    os.environ["TIDY_DB"] = _db(args)
    if args.port:
        os.environ["TIDY_PORT"] = str(args.port)
    if args.model_dir:
        os.environ["TIDY_MODEL_DIR"] = os.path.abspath(os.path.expanduser(args.model_dir))
    elif not os.environ.get("TIDY_MODEL_DIR"):
        from tidy_one.agent.config import ConfigError

        try:  # the config's model_dir, so `tidy serve` finds the same model as `tidy search`
            os.environ["TIDY_MODEL_DIR"] = _config(args).model_dir
        except ConfigError:
            pass
    try:
        from tidy_one.hub import server
    except ImportError as e:
        print(f"tidy serve: hub server is not available ({e})", file=sys.stderr)
        return 1
    fn = next((getattr(server, n) for n in ("serve", "main", "run") if callable(getattr(server, n, None))), None)
    if fn is None:
        print("tidy serve: tidy_one.hub.server has no serve()/main()", file=sys.stderr)
        return 1
    params = inspect.signature(fn).parameters
    given = {"db": os.environ["TIDY_DB"], "db_path": os.environ["TIDY_DB"], "port": args.port,
             "model_dir": os.environ.get("TIDY_MODEL_DIR"), "argv": []}
    kwargs = {k: v for k, v in given.items() if k in params and v is not None}
    rc = fn(**kwargs)
    return rc if isinstance(rc, int) else 0


def _query_encoder(model_dir: str) -> Any:
    if os.environ.get("TIDY_FAKE_ENCODER") == "1":
        from tidy_one.embed.fake import FakeEncoder

        return FakeEncoder()
    from tidy_one.embed.text import TextEncoder

    enc = TextEncoder("kure-v1", "int8", model_dir=model_dir)
    return enc if enc.available else None


def _display_uri(uri: str) -> str:
    return unquote(uri[len("file://"):]) if uri.startswith("file://") else uri


def cmd_search(args: argparse.Namespace) -> int:
    from tidy_one.catalog import Catalog

    db = _db(args)
    if not os.path.exists(db):
        print(f"tidy search: no catalog at {db} (run `tidy push --local` first)", file=sys.stderr)
        return 1
    model_dir = os.path.abspath(os.path.expanduser(args.model_dir)) if args.model_dir else _config(args).model_dir
    enc = None if args.keyword_only else _query_encoder(model_dir)
    qvec = enc.encode_query(args.query) if enc is not None and args.query.strip() else None
    with Catalog(db) as catalog:
        hits = catalog.search(args.query, qvec, None, kind=args.kind, source=args.source,
                              date_from=args.date_from, date_to=args.date_to, place=args.place, k=args.k)
    if args.json:
        _print_json(hits)
        return 0
    if enc is None and not args.keyword_only:
        print("(no int8 model found: keyword search only)", file=sys.stderr)
    if not hits:
        print("no results")
    for i, h in enumerate(hits, 1):
        when = (h.get("taken_at") or h.get("updated_at") or "")[:10]
        where = f" p.{h['page']}" if h.get("page") else ""
        print(f"{i:2d}. {h['title']}  [{h['modality']} · {','.join(h['signals'])} · {h['score']:.4f}] {when}")
        print(f"    {_display_uri(h['uri'])}{where}")
        excerpt = " ".join((h.get("excerpt") or "").split())
        if excerpt:
            print(f"    {excerpt[:200]}")
    return 0


def _count_lines(path: Any) -> int:
    n = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            n += block.count(b"\n")
    return n


def cmd_status(args: argparse.Namespace) -> int:
    from tidy_one.agent.push import pending_batches, sent_batches
    from tidy_one.agent.state import State

    cfg = _config(args)
    counts: dict[str, Any] = {}
    device_id = cfg.device_id
    if os.path.exists(cfg.state_db):
        with State(cfg.state_db) as st:
            counts = st.counts()
            device_id = cfg.device_id if cfg.device_id_pinned else (st.get_meta("device_id") or cfg.device_id)
    pending = pending_batches(cfg.outbox_dir)
    out = {
        "config": cfg.path or None,
        "device_id": device_id,
        "roots": cfg.roots,
        "hub": cfg.hub.ssh,
        **{k: counts.get(k, 0) for k in ("files", "secret_skipped", "chunks", "unpushed", "cached_vectors")},
        "last_indexed_at": counts.get("last_indexed_at"),
        "last_pushed_at": counts.get("last_pushed_at"),
        "outbox_batches": len(pending),
        "outbox_records": sum(_count_lines(p) for p in pending),
        "sent_batches": len(sent_batches(cfg.outbox_dir)),
    }
    if args.json:
        _print_json(out)
        return 0
    print(f"device   {out['device_id']}  (config: {out['config'] or 'defaults'})")
    print(f"roots    {', '.join(out['roots'])}")
    print(f"files    {out['files']} indexed, {out['secret_skipped']} secret skipped, {out['chunks']} chunks, "
          f"{out['unpushed']} not pushed")
    print(f"outbox   {out['outbox_batches']} batches pending ({out['outbox_records']} records), "
          f"{out['sent_batches']} sent")
    print(f"hub      {out['hub'] or 'not set (local only)'}")
    print(f"last     indexed {out['last_indexed_at'] or '-'}, pushed {out['last_pushed_at'] or '-'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tidy", description="One tidy, private index of your files for every AI agent.")
    p.add_argument("-c", "--config", help="config file (default: $TIDY_CONFIG or ~/.config/tidy-one/config.toml)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    p.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="write a commented default config (never overwrites)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("index", help="index changed files into outbox batches")
    s.add_argument("--limit", type=int, help="index at most N new or changed files (skips removals)")
    s.add_argument("--dry-run", action="store_true", help="only count what would change")
    s.add_argument("--no-embed", action="store_true", help="send text without vectors (re-embedded later)")
    s.add_argument("--progress", type=int, default=500, metavar="N", help="log progress every N files")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("push", help="send outbox batches to the hub over ssh")
    s.add_argument("--local", nargs="?", const="", metavar="DB", help="apply to a local catalog instead "
                   "(default: catalog_db from the config)")
    s.add_argument("--keep", action="store_true", help="leave batches in the outbox after sending")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_push)

    s = sub.add_parser("ingest", help="apply JSONL records to a catalog (hub side of push)")
    s.add_argument("file", nargs="?", default="-", help="JSONL file, or - for stdin")
    s.add_argument("--db", help="catalog path (default: $TIDY_DB or catalog_db)")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("serve", help="run the MCP server")
    s.add_argument("--db", help="catalog path (default: $TIDY_DB or catalog_db)")
    s.add_argument("--port", type=int, help="port on 127.0.0.1 (default: $TIDY_PORT or 8100)")
    s.add_argument("--model-dir", help="model directory for the int8 query encoder "
                   "(default: $TIDY_MODEL_DIR or model_dir from the config)")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("search", help="search a catalog and print compact hits")
    s.add_argument("query")
    s.add_argument("--db", help="catalog path (default: $TIDY_DB or catalog_db)")
    s.add_argument("--kind", choices=["text", "image", "video", "audio", "message"])
    s.add_argument("--source", help="source id prefix, e.g. file:my-mac")
    s.add_argument("--date-from", help="YYYY, YYYY-MM or YYYY-MM-DD (inclusive)")
    s.add_argument("--date-to", help="YYYY, YYYY-MM or YYYY-MM-DD (inclusive)")
    s.add_argument("--place", help="place name filter")
    s.add_argument("--keyword-only", action="store_true", help="skip the query embedding (full-text + trigram only)")
    s.add_argument("--k", type=int, default=10)
    s.add_argument("--model-dir", help="model directory for the int8 query encoder")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("status", help="show index, outbox and hub status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, stream=sys.stderr, format="%(asctime)s tidy: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    from tidy_one.agent.config import ConfigError
    from tidy_one.agent.push import PushError
    from tidy_one.agent.state import Busy

    try:
        return args.fn(args)
    except Busy as e:
        print(f"tidy {args.command}: {e}", file=sys.stderr)
        return EXIT_BUSY
    except (ConfigError, PushError, FileNotFoundError) as e:
        print(f"tidy {args.command}: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
