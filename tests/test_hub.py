import importlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import numpy as np
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver.exceptions import ToolError

from tidy_one.catalog import Catalog
from tidy_one.embed import TextEncoder
from tidy_one.embed.fake import FakeEncoder
from tidy_one.hub import build_server, ingest, ingest_file
from tidy_one.model import Chunk, Document, Record, delete_to_json, finalize_chunks, record_to_json

ENC = FakeEncoder()
ingest_mod = importlib.import_module("tidy_one.hub.ingest")  # the package re-exports the function under the same name
REPO = Path(__file__).resolve().parents[1]
TOOLS = {"search", "fetch", "list_sources", "stats"}


def make_record(doc_id: str, texts: list[str], *, source_id: str = "file:mba", **kw) -> Record:
    doc = Document(
        doc_id=doc_id,
        source_id=source_id,
        native_id=doc_id,
        modality=kw.pop("modality", "text"),
        title=kw.pop("title", doc_id),
        uri=f"file:///{doc_id}",
        **kw,
    )
    chunks = finalize_chunks(doc_id, [Chunk(i, t) for i, t in enumerate(texts)])
    vecs = {"kure-v1": dict(zip([c.chunk_id for c in chunks], ENC.encode_passages(texts)))} if chunks else {}
    return Record(doc, chunks, vecs)


def corpus() -> list[str]:
    return [
        record_to_json(
            make_record(
                "file:mba:budget",
                ["2024년 3분기 예산 보고서 초안. 마케팅 예산을 줄이고 서버 비용을 늘린다.", "부록: 분기별 집행 내역"],
                title="3분기 예산 보고서",
                updated_at="2024-07-02T09:00:00Z",
            )
        ),
        record_to_json(
            make_record(
                "photos:jeju",
                ["성산일출봉에서 찍은 해돋이 사진"],
                source_id="photos:mba",
                modality="image",
                title="IMG_1234.HEIC",
                taken_at="2023-08-15T06:10:00Z",
                place_ko="제주 서귀포시",
                place_en="Seogwipo, Jeju",
            )
        ),
        record_to_json(
            make_record(
                "notion:acme:deploy",
                ["Deploy checklist for the hub server: run migrations, restart tidy-hub, check logs."],
                source_id="notion:acme",
                title="Hub deploy checklist",
                updated_at="2025-01-10T12:00:00Z",
            )
        ),
    ]


@pytest.fixture
def cat(tmp_path):
    c = Catalog(str(tmp_path / "catalog.sqlite"))
    yield c
    c.close()


@pytest.fixture
def loaded(cat):
    counts = ingest(corpus(), cat)
    assert counts["upserted"] == 3 and counts["failed"] == 0
    return cat


def call(server, name: str, **args) -> dict:
    res = anyio.run(server.call_tool, name, args)
    assert not res.is_error, res.content[0].text
    text = res.content[0].text
    obj = json.loads(text)
    assert text == json.dumps(obj, ensure_ascii=False, separators=(",", ":"))  # compact JSON text
    return obj


# -- ingest -----------------------------------------------------------------


def test_ingest_mixed_valid_and_invalid_lines(cat):
    good = corpus()
    bad_vec = json.loads(good[0])
    bad_vec["document"]["doc_id"] = "file:mba:badvec"
    bad_vec["vec_text"] = {"kure-v1": {"file:mba:badvec#body:0": "not base64!"}}
    no_doc_id = json.loads(good[0])
    del no_doc_id["document"]["doc_id"]
    bad_modality = json.loads(good[0])
    bad_modality["document"].update(doc_id="x:1", modality="hologram")
    dup = record_to_json(
        Record(
            Document("x:dup", "file:mba", "dup", "text", "dup", "file:///dup"),
            [Chunk(0, "a", chunk_id="same"), Chunk(1, "b", chunk_id="same")],
        )
    )
    lines = [
        good[0],  # 1
        "",  # 2: blank, ignored
        "{not json",  # 3
        json.dumps({"v": 99, "op": "upsert"}),  # 4
        json.dumps({"v": 1, "op": "merge"}),  # 5
        json.dumps(no_doc_id, ensure_ascii=False),  # 6
        json.dumps(bad_modality, ensure_ascii=False),  # 7
        json.dumps(bad_vec, ensure_ascii=False),  # 8
        dup,  # 9: catalog rejects duplicate chunk ids
        good[1],  # 10
        json.dumps({"v": 1, "op": "delete", "doc_id": "", "deleted_at": "2025-01-01T00:00:00Z"}),  # 11
        delete_to_json("file:mba:budget", "2025-02-01T00:00:00Z") + "\n",  # 12
        good[2],  # 13
    ]
    counts = ingest(iter(lines), cat)
    assert counts["upserted"] == 3
    assert counts["deleted"] == 1
    assert counts["failed"] == 8
    assert [e["line_no"] for e in counts["errors"]] == [3, 4, 5, 6, 7, 8, 9, 11]
    assert all(len(e["error"]) <= ingest_mod.ERROR_CHARS for e in counts["errors"])
    assert "JSONDecodeError" in counts["errors"][0]["error"]
    assert "modality" in counts["errors"][4]["error"]
    assert "duplicate" in counts["errors"][6]["error"]

    stats = cat.stats()
    assert stats["documents"] == 2 and stats["deleted"] == 1
    assert cat.get_document("file:mba:budget") is None
    assert cat.get_document("x:dup") is None and cat.get_document("file:mba:badvec") is None
    assert {h["doc_id"] for h in cat.search("체크리스트 deploy", None, None)} == {"notion:acme:deploy"}


def test_ingest_is_idempotent_and_handles_bytes(cat, tmp_path):
    lines = corpus()
    path = tmp_path / "batch.jsonl"
    raw = [line.encode() + b"\n" for line in lines] + [b"\xff\xfe broken utf-8\n", lines[0].encode() + b"\n"]
    path.write_bytes(b"".join(raw))
    counts = ingest_file(str(path), cat)
    assert (counts["upserted"], counts["failed"]) == (4, 1)
    assert counts["errors"][0]["line_no"] == 4 and "UnicodeDecodeError" in counts["errors"][0]["error"]
    assert cat.stats()["documents"] == 3
    again = ingest(lines, cat)
    assert again["upserted"] == 3 and cat.stats()["documents"] == 3 and cat.stats()["chunks"] == 4


def test_ingest_progress_and_error_cap(cat, monkeypatch):
    monkeypatch.setattr(ingest_mod, "BATCH", 2)
    monkeypatch.setattr(ingest_mod, "MAX_ERRORS", 3)
    seen = []
    counts = ingest(["junk"] * 5 + corpus(), cat, on_progress=lambda c: seen.append(c["upserted"] + c["failed"]))
    assert seen == [2, 4, 6, 8]
    assert counts["failed"] == 5 and len(counts["errors"]) == 3 and counts["upserted"] == 3


# -- tools ------------------------------------------------------------------


def test_tool_list_and_schemas(cat):
    server = build_server(cat, ENC)
    tools = {t.name: t for t in anyio.run(server.list_tools)}
    assert set(tools) == TOOLS
    search = tools["search"]
    assert len(json.dumps(search.input_schema)) < 16 * 1024
    assert search.input_schema["required"] == ["query"]
    assert set(search.input_schema["properties"]) == {"query", "kind", "source", "date_from", "date_to", "place", "k"}
    for t in tools.values():
        assert t.annotations.read_only_hint
        assert "한국어 힌트" in t.description
    assert "fetch(doc_id)" in search.description and "place" in search.description


def test_search_tool_hybrid_with_fake_encoder(loaded):
    server = build_server(loaded, ENC)
    out = call(server, "search", query="3분기 예산 보고서")
    assert "note" not in out
    top = out["hits"][0]
    assert top["doc_id"] == "file:mba:budget"
    assert {"fts", "vec"} <= set(top["signals"])
    assert "예산" in top["excerpt"] and top["uri"] == "file:///file:mba:budget"
    assert all(v is not None for h in out["hits"] for v in h.values())

    photo = call(server, "search", query="해돋이", place="제주", kind="image", date_from="2023", date_to="2023-08")
    assert [h["doc_id"] for h in photo["hits"]] == ["photos:jeju"]
    assert call(server, "search", query="해돋이", place="부산")["hits"] == []

    recent = call(server, "search", query="", source="notion:")
    assert [h["doc_id"] for h in recent["hits"]] == ["notion:acme:deploy"]
    assert recent["hits"][0]["signals"] == ["recent"]

    assert len(call(server, "search", query="", k=500)["hits"]) == 3
    with pytest.raises(ToolError, match="date_from"):
        anyio.run(server.call_tool, "search", {"query": "예산", "date_from": "last week"})
    with pytest.raises(ToolError):
        anyio.run(server.call_tool, "search", {"query": "예산", "kind": "hologram"})


def test_search_falls_back_to_keywords_without_model(loaded, tmp_path):
    missing = TextEncoder("kure-v1", "int8", model_dir=str(tmp_path / "no-models"))
    for server in (build_server(loaded, missing), build_server(loaded, None)):
        out = call(server, "search", query="예산 보고서")
        assert out["hits"][0]["doc_id"] == "file:mba:budget"
        assert "vec" not in out["hits"][0]["signals"]
        assert "keyword results only" in out["note"]
        assert call(server, "stats")["semantic_search"]["available"] is False

    class Broken(FakeEncoder):
        def encode_query(self, text: str) -> np.ndarray:
            raise RuntimeError("onnx exploded")

    out = call(build_server(loaded, Broken()), "search", query="예산")
    assert out["hits"] and "failed" in out["note"]
    out = call(build_server(loaded, FakeEncoder(dim=8)), "search", query="예산")
    assert out["hits"] and "failed" in out["note"]
    out = call(build_server(loaded, FakeEncoder(model_id="other")), "search", query="예산")
    assert "not kure-v1" in out["note"]


def test_fetch_list_sources_stats_tools(loaded):
    server = build_server(loaded, ENC)
    doc = call(server, "fetch", doc_id="file:mba:budget")
    assert doc["title"] == "3분기 예산 보고서" and "부록" in doc["text"] and doc["next_offset"] is None
    assert "content_hash" not in doc and "phash" not in doc

    part = call(server, "fetch", doc_id="file:mba:budget", offset=0, length=10)
    assert len(part["text"]) == 10 and part["next_offset"] == 10
    rest = call(server, "fetch", doc_id="file:mba:budget", offset=part["next_offset"], length=100000)
    assert part["text"] + rest["text"] == doc["text"]
    with pytest.raises(ToolError, match="not found"):
        anyio.run(server.call_tool, "fetch", {"doc_id": "nope"})

    sources = {s["source_id"]: s for s in call(server, "list_sources")["sources"]}
    assert set(sources) == {"file:mba", "photos:mba", "notion:acme"}
    assert sources["photos:mba"]["documents"] == 1

    stats = call(server, "stats")
    assert stats["documents"] == 3 and stats["vec_text"] == 4
    assert stats["semantic_search"] == {"model_id": "kure-v1", "available": True}


# -- live server --------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, proc: subprocess.Popen, log: Path, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"server exited early:\n{log.read_text(errors='replace')[-3000:]}")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"server did not start:\n{log.read_text(errors='replace')[-3000:]}")


async def _client_roundtrip(url: str) -> tuple[set[str], dict, dict, bool]:
    async with streamable_http_client(url) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name for t in (await session.list_tools()).tools}
        found = await session.call_tool("search", {"query": "deploy checklist", "k": 3})
        stats = await session.call_tool("stats", {})
        missing = await session.call_tool("fetch", {"doc_id": "nope"})
        return tools, json.loads(found.content[0].text), json.loads(stats.content[0].text), missing.is_error


def test_live_streamable_http_server(tmp_path):
    db = tmp_path / "catalog.sqlite"
    with Catalog(str(db)) as c:
        ingest(corpus(), c)
    port = _free_port()
    log = tmp_path / "server.log"
    env = {
        **os.environ,
        "TIDY_DB": str(db),
        "TIDY_MODEL_DIR": str(tmp_path / "models"),  # empty: exercises the keyword-only fallback
        "TIDY_PORT": str(port),
    }
    with open(log, "wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-c", "from tidy_one.hub.server import run; run()"],
            cwd=REPO,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_for_port(port, proc, log)
        tools, found, stats, missing_is_error = anyio.run(_client_roundtrip, f"http://127.0.0.1:{port}/mcp")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    assert tools == TOOLS
    assert found["hits"][0]["doc_id"] == "notion:acme:deploy"
    assert "model files missing" in found["note"]
    assert stats["documents"] == 3 and stats["semantic_search"]["available"] is False
    assert missing_is_error


def test_ingest_stops_at_a_storage_error(cat, monkeypatch):
    """A locked or full database fails every later line too: stop there, so the device re-sends the batch."""
    import sqlite3

    calls = []

    def locked(rec):
        calls.append(rec.document.doc_id)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cat, "apply", locked)
    counts = ingest(corpus(), cat)
    assert (counts["upserted"], counts["failed"], len(calls)) == (0, 1, 1)
    assert "database is locked" in counts["errors"][0]["error"] and "stopped" in counts["errors"][0]["error"]


def test_ingest_command_exits_nonzero_on_failed_lines(tmp_path, capsys):
    from tidy_one.cli import main

    db = str(tmp_path / "hub.sqlite")
    good = tmp_path / "good.jsonl"
    good.write_text("\n".join(corpus()) + "\n", encoding="utf-8")
    assert main(["-q", "ingest", str(good), "--db", db]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["upserted"] == 3
    bad = tmp_path / "bad.jsonl"
    doc = json.loads(corpus()[0])
    doc["document"]["field_from_a_newer_agent"] = 1  # an older hub's Document() rejects it
    bad.write_text(json.dumps(doc, ensure_ascii=False) + "\n" + corpus()[1] + "\n", encoding="utf-8")
    assert main(["-q", "ingest", str(bad), "--db", db]) == 1
    out = capsys.readouterr()
    assert json.loads(out.out.strip().splitlines()[-1])["failed"] == 1
    assert "1 lines not applied" in out.err and "line 1" in out.err
