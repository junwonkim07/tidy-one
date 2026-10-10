"""`tidy serve`: the hub's MCP server (streamable HTTP, 127.0.0.1 only) over the catalog.

Tools: search, fetch, list_sources, stats. Results are compact JSON text. Queries are embedded
with the int8 KURE encoder; without model files, search falls back to keyword signals and says so.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Annotated, Any, Literal, Protocol

import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from tidy_one import __version__
from tidy_one.catalog import Catalog
from tidy_one.catalog.catalog import TEXT_DIM
from tidy_one.embed.text import ModelFilesMissing

log = logging.getLogger("tidy_one.hub")

DEFAULT_DB = "~/.local/share/tidy-one/catalog.sqlite"
DEFAULT_PORT = 8100
HOST = "127.0.0.1"
MCP_PATH = "/mcp"
MAX_K = 50
MAX_FETCH = 20000
MAX_QUERY = 2000

Kind = Literal["text", "image", "video", "audio", "message"]

_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2}(T[\d:.]+Z?)?)?)?$")
_HIDDEN = frozenset({"content_hash", "phash"})
_Q = "What to find, in any wording (Korean or English). May be empty when filters are set."
_SOURCE = "source_id or prefix from list_sources, e.g. 'notion:' or 'file:'."
_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = (
    "tidy-one is the owner's private index of files, notes, photos, videos and messages across devices. "
    "Call search (pass kind/source/date/place filters when the request implies them), then fetch(doc_id) "
    "to read a document before answering; cite its title and uri. "
    "한국어 질문은 번역하지 말고 그대로 검색하세요."
)


class QueryEncoder(Protocol):
    model_id: str

    def encode_query(self, text: str) -> np.ndarray: ...


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in _HIDDEN and v is not None and v != "" and v != [] and v != {}}


def _check_date(name: str, value: str | None) -> str | None:
    value = (value or "").strip() or None
    if value is not None and not _DATE.match(value):
        raise ToolError(f"{name} must look like 2024, 2024-03 or 2024-03-05 (got {value[:40]!r})")
    return value


class _Embedder:
    """Query vectors from the shared encoder, or (None, note) when semantic search is unavailable."""

    def __init__(self, encoder: QueryEncoder | None, model_id: str):
        self.encoder = encoder
        self.model_id = model_id
        self._warned = False

    def status(self) -> dict[str, Any]:
        enc = self.encoder
        if enc is None:
            return {"available": False}
        model_id = getattr(enc, "model_id", self.model_id)
        ok = bool(getattr(enc, "available", True)) and model_id == self.model_id
        return _compact({"model_id": model_id, "variant": getattr(enc, "variant", None)}) | {"available": ok}

    def __call__(self, query: str) -> tuple[np.ndarray | None, str | None]:
        enc = self.encoder
        if enc is None:
            return None, "semantic search is off (no query encoder); keyword results only"
        if getattr(enc, "model_id", self.model_id) != self.model_id:
            return None, f"semantic search is off (encoder is not {self.model_id}); keyword results only"
        try:
            v = np.asarray(enc.encode_query(query), dtype=np.float32).reshape(-1)
        except ModelFilesMissing:
            if not self._warned:
                log.warning("query model files missing; serving keyword search only")
                self._warned = True
            return None, "semantic search is off (embedding model files missing); keyword results only"
        except Exception:
            log.exception("query embedding failed")
            return None, "semantic search failed for this query; keyword results only"
        if v.size != TEXT_DIM or not np.isfinite(v).all():
            log.error("query encoder returned a bad vector (%d dims, expected %d finite)", v.size, TEXT_DIM)
            return None, "semantic search failed for this query; keyword results only"
        return v, None


def build_server(catalog: Catalog, encoder: QueryEncoder | None = None) -> MCPServer:
    """MCP server with search/fetch/list_sources/stats over `catalog`; `encoder` embeds queries (None: keyword only)."""
    embed = _Embedder(encoder, catalog.text_model_id)
    mcp = MCPServer("tidy-one", instructions=INSTRUCTIONS, version=__version__)

    @mcp.tool(title="Search my index", annotations=_READ_ONLY, structured_output=False)
    def search(
        query: Annotated[str, Field(description=_Q)],
        kind: Annotated[Kind | None, Field(description="Only this modality.")] = None,
        source: Annotated[str | None, Field(description=_SOURCE)] = None,
        date_from: Annotated[str | None, Field(description="Inclusive start: YYYY, YYYY-MM or YYYY-MM-DD.")] = None,
        date_to: Annotated[str | None, Field(description="Inclusive end: YYYY, YYYY-MM or YYYY-MM-DD.")] = None,
        place: Annotated[str | None, Field(description="Place name in Korean or English, e.g. 제주, Seoul.")] = None,
        k: Annotated[int, Field(description="Number of results, 1-50.")] = 10,
    ) -> str:
        """Search the owner's private files, notes, photos, videos and messages by meaning and keywords.

        Put time and place constraints in date_from/date_to/place (and kind/source) instead of the query text.
        An empty query with filters lists the newest matching items. Each hit has doc_id, title, uri and an
        excerpt; call fetch(doc_id) to read the full text before answering.
        한국어 힌트: 기간·장소는 date_from/date_to/place로 넘기고, 답하기 전에 doc_id로 fetch를 호출해 본문을 확인하세요.
        """
        q = (query or "").strip()[:MAX_QUERY]
        d_from, d_to = _check_date("date_from", date_from), _check_date("date_to", date_to)
        qvec, note = embed(q) if q else (None, None)
        hits = catalog.search(
            q,
            qvec,
            None,
            kind=kind,
            source=(source or "").strip() or None,
            date_from=d_from,
            date_to=d_to,
            place=(place or "").strip() or None,
            k=max(1, min(int(k), MAX_K)),
        )
        out: dict[str, Any] = {"hits": [_compact(h) for h in hits]}
        if not hits:
            note = " ".join(filter(None, [note, "no matches; try other words or fewer filters"]))
        if note:
            out["note"] = note
        return _json(out)

    @mcp.tool(title="Read a document", annotations=_READ_ONLY, structured_output=False)
    def fetch(
        doc_id: Annotated[str, Field(description="doc_id from a search hit.")],
        offset: Annotated[int, Field(description="Character offset to start from.")] = 0,
        length: Annotated[int, Field(description="Characters to return, up to 20000.")] = 4000,
    ) -> str:
        """Read a document's text and metadata (title, uri, dates, place, people) by doc_id from search.

        Long documents come in slices: while next_offset is present, call again with offset=next_offset.
        한국어 힌트: search 결과의 doc_id로 본문을 읽고, next_offset이 있으면 offset으로 넘겨 이어 읽으세요.
        """
        res = catalog.fetch(doc_id, max(0, int(offset)), max(1, min(int(length), MAX_FETCH)))
        if res.get("error"):
            raise ToolError(f"document not found (deleted or never indexed): {doc_id[:200]}")
        return _json(_compact(res) | {"next_offset": res.get("next_offset")})

    @mcp.tool(title="List sources", annotations=_READ_ONLY, structured_output=False)
    def list_sources() -> str:
        """List indexed sources (device folders, photo libraries, workspaces) with document counts and last update.

        Pass a source_id, or a prefix such as 'file:', as search(source=...).
        한국어 힌트: 특정 기기·서비스로 좁히려면 여기서 source_id를 찾아 search의 source로 넘기세요.
        """
        return _json({"sources": [_compact(s) for s in catalog.list_sources()]})

    @mcp.tool(title="Index stats", annotations=_READ_ONLY, structured_output=False)
    def stats() -> str:
        """Index health: document, chunk and vector counts, models, database size and semantic search status.

        한국어 힌트: 색인 규모와 의미 검색(임베딩) 사용 가능 여부를 확인할 때 쓰세요.
        """
        return _json(catalog.stats() | {"semantic_search": embed.status()})

    return mcp


def _warm(encoder: Any) -> None:
    """Load Kiwi and the query model in the background so the first search is not slow."""
    from tidy_one.text.morph import warmup

    try:
        warmup()
        if getattr(encoder, "available", False):
            encoder.encode_query("warmup")
            log.info("query encoder %s (%s) loaded", encoder.model_id, getattr(encoder, "variant", "?"))
        else:
            log.warning("query model files missing under %s; keyword search only", getattr(encoder, "path", "?"))
    except Exception:
        log.exception("warmup failed")


def run(db: str | None = None, port: int | None = None, model_dir: str | None = None) -> None:
    """Serve http://127.0.0.1:$TIDY_PORT/mcp over $TIDY_DB with the int8 query encoder from $TIDY_MODEL_DIR."""
    from tidy_one.embed import TextEncoder

    db = db or os.environ.get("TIDY_DB") or DEFAULT_DB
    port = int(port or os.environ.get("TIDY_PORT") or DEFAULT_PORT)
    model_dir = model_dir or os.environ.get("TIDY_MODEL_DIR") or None
    catalog = Catalog(db)
    encoder = TextEncoder(catalog.text_model_id, "int8", model_dir=model_dir)
    server = build_server(catalog, encoder)
    threading.Thread(target=_warm, args=(encoder,), name="tidy-warmup", daemon=True).start()
    log.info("tidy-one hub serving %s on http://%s:%d%s", db, HOST, port, MCP_PATH)
    try:
        server.run(
            "streamable-http",
            host=HOST,
            port=port,
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
        )
    finally:
        catalog.close()
