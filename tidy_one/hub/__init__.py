"""Hub side: `tidy ingest` (outbox JSONL -> catalog) and `tidy serve` (MCP server over the catalog)."""

from __future__ import annotations

import importlib
from typing import Any

from tidy_one.hub.ingest import ingest, ingest_file

__all__ = ["build_server", "ingest", "ingest_file", "run"]


def __getattr__(name: str) -> Any:
    # the mcp SDK takes ~0.6 s to import; `tidy ingest` should not pay for it
    if name in ("build_server", "run"):
        return getattr(importlib.import_module("tidy_one.hub.server"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
