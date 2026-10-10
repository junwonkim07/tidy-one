import json
import os
import plistlib
import re
import sqlite3
import stat
import subprocess
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from tidy_one.agent import Busy, ConfigError, State, index, load_config, push, write_default_config
from tidy_one.agent.config import DEFAULT_ROOTS, hostname_slug
from tidy_one.agent.push import safe_line
from tidy_one.agent.run import file_doc_id, file_uri
from tidy_one.agent.state import exclusive_lock
from tidy_one.catalog import Catalog
from tidy_one.embed.fake import FakeEncoder
from tidy_one.model import SENS_SECRET, Chunk, Document, Record, delete_to_json, iter_lines, parse_line, record_to_json

REPO = Path(__file__).resolve().parents[1]

MEETING = """# 3분기 마케팅 회의록

참석자: 홍길동, 성춘향, 이몽룡

이번 회의에서는 신제품 출시 일정과 광고 예산을 논의했다. 출시일은 11월 둘째 주로 확정했다.

광고 예산은 지난 분기보다 20% 늘리기로 했고, 인스타그램 캠페인을 먼저 시작한다.
"""

PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\n"


def long_doc(n: int) -> str:
    paras = [
        f"{i}번째 안건은 프로젝트 {i}의 일정 점검이다. "
        + "담당자는 진행 상황을 공유했고 다음 주까지 보고서를 제출하기로 했다. " * 6
        + f"안건 {i} 끝."
        for i in range(n)
    ]
    return "# 주간 업무 보고\n\n" + "\n\n".join(paras) + "\n"


class CountingEncoder(FakeEncoder):
    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    def encode_passages(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        self.texts.extend(texts)
        return super().encode_passages(texts, batch_size)


def write_config(path: Path, root: Path, base: Path, extra: str = "") -> None:
    q = json.dumps
    path.write_text(
        "\n".join([
            'device_id = "test-mac"',
            f"roots = [{q(str(root))}]",
            f"outbox_dir = {q(str(base / 'outbox'))}",
            f"state_db = {q(str(base / 'state.sqlite'))}",
            f"model_dir = {q(str(base / 'models'))}",
            f"catalog_db = {q(str(base / 'catalog.sqlite'))}",
            extra,
        ]),
        encoding="utf-8",
    )


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for var in ("TIDY_DB", "TIDY_MODEL_DIR", "TIDY_CONFIG", "TIDY_FAKE_ENCODER"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "docs"
    root.mkdir()
    write_config(tmp_path / "config.toml", root, tmp_path / "data")
    return load_config(tmp_path / "config.toml")


def root_of(cfg) -> Path:
    return Path(cfg.roots[0])


def disk_path(p: Path) -> str:
    return unicodedata.normalize("NFC", os.path.realpath(p))


def outbox_lines(cfg, names: list[str] | None = None) -> list[str]:
    out = Path(cfg.outbox_dir)
    files = [out / n for n in names] if names is not None else sorted(out.glob("*.jsonl"))
    return [line for f in files for line in iter_lines(str(f))]


def records(lines: list[str]) -> tuple[dict[str, Record], list[str]]:
    ups, dels = {}, []
    for line in lines:
        op, payload = parse_line(line)
        if op == "upsert":
            ups[payload.document.native_id] = payload
        else:
            dels.append(payload[0])
    return ups, dels


def search_ids(db: str, query: str) -> list[str]:
    with Catalog(db) as cat:
        return [h["doc_id"] for h in cat.search(query, FakeEncoder().encode_query(query), None, k=5)]


def test_index_push_local_then_search_korean(cfg, tmp_path):
    root = root_of(cfg)
    (root / "회의록.md").write_text(MEETING, encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "groceries.txt").write_text("Grocery list: apples, bread, coffee beans.", encoding="utf-8")

    stats = index(cfg, encoder=FakeEncoder())
    assert (stats.new, stats.changed, stats.errors, stats.records) == (2, 0, 0, 2)
    assert len(stats.batches) == 1 and stats.batches[0].endswith("-0001.jsonl")
    assert not list(Path(cfg.outbox_dir).glob("*.tmp"))

    ups, dels = records(outbox_lines(cfg))
    assert dels == []
    path = disk_path(root / "회의록.md")
    rec = ups[path]
    doc = rec.document
    assert doc.doc_id == file_doc_id("test-mac", path) and doc.doc_id.startswith("file:test-mac:")
    assert doc.source_id == "file:test-mac" and doc.device_id == "test-mac"
    assert doc.uri == file_uri(path) and doc.uri.startswith("file:///") and "%" in doc.uri
    assert doc.modality == "text" and doc.content_hash and len(doc.content_hash) == 64
    # local wall time with its UTC offset: the date part is the owner's day, the instant is exact
    updated = datetime.fromisoformat(doc.updated_at)
    assert updated.utcoffset() is not None and doc.size_bytes == len(MEETING.encode())
    assert updated.timestamp() == int(os.stat(path).st_mtime)
    assert rec.chunks[-1].field == "meta"
    vecs = rec.vec_text["kure-v1"]
    assert set(vecs) == {c.chunk_id for c in rec.chunks}
    assert all(abs(float(np.linalg.norm(v)) - 1) < 1e-3 for v in vecs.values())

    db = str(tmp_path / "local.sqlite")
    ps = push(cfg, local_db=db)
    assert ps.error is None and ps.sent == stats.batches and ps.pending == 0 and ps.blocked == 0
    assert ps.counts.get("upserted", ps.counts.get("upserts", 2)) == 2
    assert (Path(cfg.outbox_dir) / "sent" / stats.batches[0]).exists()
    with State(cfg.state_db) as st:
        assert st.counts()["unpushed"] == 0 and st.counts()["files"] == 2

    ids = search_ids(db, "마케팅 회의")
    assert ids and ids[0] == doc.doc_id
    assert search_ids(db, "coffee beans")[0] == ups[disk_path(root / "sub" / "groceries.txt")].document.doc_id

    again = index(cfg, encoder=FakeEncoder())
    assert (again.unchanged, again.records, again.batches) == (2, 0, [])


def test_modified_file_reembeds_only_changed_chunks(cfg):
    root = root_of(cfg)
    report, other = root / "report.md", root / "other.md"
    report.write_text(long_doc(8), encoding="utf-8")
    other.write_text(MEETING, encoding="utf-8")
    first = CountingEncoder()
    s1 = index(cfg, encoder=first)
    ups1, _ = records(outbox_lines(cfg, s1.batches))
    old = ups1[disk_path(report)]
    assert len([c for c in old.chunks if c.field == "body"]) >= 3
    assert s1.embedded == len(first.texts) == len({c.chunk_hash for r in ups1.values() for c in r.chunks})

    report.write_text(long_doc(9), encoding="utf-8")
    enc = CountingEncoder()
    s2 = index(cfg, encoder=enc)
    assert (s2.changed, s2.new, s2.unchanged) == (1, 0, 1)
    ups2, dels2 = records(outbox_lines(cfg, s2.batches))
    assert list(ups2) == [disk_path(report)] and dels2 == []
    new = ups2[disk_path(report)]
    old_hashes = {c.chunk_hash for c in old.chunks}
    new_texts = {c.text for c in new.chunks if c.chunk_hash not in old_hashes}
    assert 0 < len(enc.texts) < len(new.chunks)
    assert set(enc.texts) == new_texts
    assert s2.embedded == len(enc.texts) and s2.cached == len(new.chunks) - len(enc.texts)
    vecs = new.vec_text["kure-v1"]
    assert set(vecs) == {c.chunk_id for c in new.chunks}
    ref = FakeEncoder()
    for c in new.chunks:  # cached (float16) and fresh vectors both match the encoder
        assert np.allclose(vecs[c.chunk_id], ref.encode_query(c.text), atol=2e-3)

    t = report.stat().st_mtime + 100
    os.utime(report, (t, t))
    enc3 = CountingEncoder()
    s3 = index(cfg, encoder=enc3)
    assert (s3.touched, s3.changed, s3.records, enc3.texts) == (1, 0, 0, [])


def test_rename_reuses_cached_body_vectors(cfg):
    root = root_of(cfg)
    (root / "보고서.md").write_text(long_doc(5), encoding="utf-8")
    index(cfg, encoder=FakeEncoder())
    os.rename(root / "보고서.md", root / "주간보고.md")
    enc = CountingEncoder()
    s = index(cfg, encoder=enc)
    assert (s.new, s.tombstoned) == (1, 1)
    assert len(enc.texts) == 1 and "주간보고.md" in enc.texts[0]
    ups, dels = records(outbox_lines(cfg, s.batches))
    assert dels == [file_doc_id("test-mac", disk_path(root / "보고서.md"))]
    assert list(ups) == [disk_path(root / "주간보고.md")]


def test_deleted_file_becomes_tombstone(cfg, tmp_path):
    root = root_of(cfg)
    (root / "회의록.md").write_text(MEETING, encoding="utf-8")
    (root / "report.md").write_text(long_doc(4), encoding="utf-8")
    index(cfg, encoder=FakeEncoder())
    db = str(tmp_path / "local.sqlite")
    push(cfg, local_db=db)
    doc_id = file_doc_id("test-mac", disk_path(root / "회의록.md"))
    assert doc_id in search_ids(db, "마케팅 회의")
    with State(cfg.state_db) as st:
        cached_before = st.counts()["cached_vectors"]

    (root / "회의록.md").unlink()
    s = index(cfg, encoder=FakeEncoder())
    assert (s.tombstoned, s.records, s.unchanged) == (1, 1, 1)
    ups, dels = records(outbox_lines(cfg))
    assert ups == {} and dels == [doc_id]
    with State(cfg.state_db) as st:
        assert st.get(disk_path(root / "회의록.md")) is None
        assert st.counts()["cached_vectors"] < cached_before
    push(cfg, local_db=db)
    with Catalog(db) as cat:
        assert cat.get_document(doc_id) is None
    assert doc_id not in search_ids(db, "마케팅 회의")


def test_secret_files_never_reach_the_outbox(cfg, tmp_path):
    root = root_of(cfg)
    (root / "passwords.txt").write_text("bank: hunter2", encoding="utf-8")
    (root / ".env").write_text("API_KEY=abc", encoding="utf-8")
    (root / "server.pem").write_text("not really a cert", encoding="utf-8")
    (root / "keys.md").write_text("# deploy notes\n\n" + PRIVATE_KEY, encoding="utf-8")
    (root / "plan.md").write_text(MEETING, encoding="utf-8")

    s = index(cfg, encoder=FakeEncoder())
    assert (s.new, s.secret) == (1, 1)
    lines = outbox_lines(cfg)
    ups, _ = records(lines)
    assert list(ups) == [disk_path(root / "plan.md")]
    blob = "\n".join(lines)
    for needle in ("passwords", "hunter2", ".env", "server.pem", "keys.md", "PRIVATE KEY", "b3BlbnNzaC1rZXk"):
        assert needle not in blob
    with State(cfg.state_db) as st:
        assert st.get(disk_path(root / "keys.md")).status == "secret"
        assert st.get(disk_path(root / "passwords.txt")) is None

    db = str(tmp_path / "local.sqlite")
    push(cfg, local_db=db)
    plan_id = file_doc_id("test-mac", disk_path(root / "plan.md"))
    with (root / "plan.md").open("a", encoding="utf-8") as f:
        f.write("\n" + PRIVATE_KEY)
    s2 = index(cfg, encoder=FakeEncoder())
    assert (s2.secret, s2.tombstoned) == (1, 1)
    ups2, dels2 = records(outbox_lines(cfg))
    assert ups2 == {} and dels2 == [plan_id]
    assert "PRIVATE KEY" not in "\n".join(outbox_lines(cfg))
    push(cfg, local_db=db)
    with Catalog(db) as cat:
        assert cat.get_document(plan_id) is None
    s3 = index(cfg, encoder=FakeEncoder())
    assert (s3.unchanged, s3.records) == (2, 0)


def test_push_holds_back_secret_and_malformed_lines(cfg):
    out = Path(cfg.outbox_dir)
    out.mkdir(parents=True)

    def rec(doc_id: str, sensitivity: int) -> str:
        doc = Document(doc_id, "file:test-mac", doc_id, "text", doc_id, f"file:///{doc_id}", sensitivity=sensitivity)
        return record_to_json(Record(doc, [Chunk(0, "본문 텍스트", chunk_id=f"{doc_id}#body:0")]))

    lines = [
        rec("file:test-mac:secret", SENS_SECRET),
        "{not json",
        delete_to_json("file:test-mac:gone", "2026-10-10T00:00:00Z"),
        rec("file:test-mac:ok", 0),
        '{"v": 1, "op": "upsert", "document": {"sensitivity": "x"}}',
    ]
    (out / "20260101T000000Z-0001.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert [safe_line(line) for line in lines] == [False, False, True, True, False]

    calls = []

    def fake_run(cmd, stdin, capture_output, timeout):
        calls.append((cmd, stdin.read().decode()))
        return subprocess.CompletedProcess(cmd, 0, stdout=b'note\n{"upserted": 1, "deleted": 1}\n', stderr=b"")

    cfg.hub.ssh = "memory@hub"
    ps = push(cfg, run=fake_run)
    assert ps.error is None and ps.blocked == 3 and ps.lines == 2
    assert ps.counts == {"upserted": 1, "deleted": 1}
    cmd, sent = calls[0]
    assert cmd[0] == "ssh" and "BatchMode=yes" in cmd and cmd[-2:] == ["memory@hub", "tidy ingest -"]
    assert "secret" not in sent and "not json" not in sent
    assert [json.loads(line)["op"] for line in sent.splitlines()] == ["delete", "upsert"]
    assert (out / "sent" / "20260101T000000Z-0001.jsonl").exists()


def test_push_over_ssh_stops_at_failure_and_keeps_batches(cfg):
    root = root_of(cfg)
    for i in range(3):
        (root / f"note{i}.txt").write_text(f"메모 {i}: 다음 주 일정 정리", encoding="utf-8")
    cfg.hub.ssh = "memory@hub"
    stats = index(cfg, encoder=FakeEncoder())
    assert len(stats.batches) == 1

    def failing(cmd, stdin, capture_output, timeout):
        err = b"ssh: connect to host hub port 22: refused\n"
        return subprocess.CompletedProcess(cmd, 255, stdout=b"", stderr=err)

    ps = push(cfg, run=failing)
    assert ps.sent == [] and ps.pending == 1 and "255" in ps.error and "refused" in ps.error
    with State(cfg.state_db) as st:
        assert st.counts()["unpushed"] == 3

    def ok(cmd, stdin, capture_output, timeout):
        n = len(stdin.read().splitlines())
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"upserted": n}).encode() + b"\n", stderr=b"")

    ps2 = push(cfg, run=ok)
    assert ps2.error is None and ps2.sent == stats.batches and ps2.counts == {"upserted": 3}
    with State(cfg.state_db) as st:
        assert st.counts()["unpushed"] == 0


def test_push_without_target_or_batches(cfg):
    assert push(cfg).sent == []
    (root_of(cfg) / "a.txt").write_text("hello", encoding="utf-8")
    index(cfg, encoder=FakeEncoder())
    with pytest.raises(Exception, match="hub.ssh"):
        push(cfg)


def test_no_embed_then_embed_adds_vectors(cfg):
    root = root_of(cfg)
    (root / "a.md").write_text(MEETING, encoding="utf-8")
    s1 = index(cfg, embed=False)
    ups1, _ = records(outbox_lines(cfg, s1.batches))
    assert ups1[disk_path(root / "a.md")].vec_text == {}
    assert index(cfg, embed=False).records == 0
    s2 = index(cfg, encoder=FakeEncoder())
    assert s2.changed == 1
    ups2, _ = records(outbox_lines(cfg, s2.batches))
    assert ups2[disk_path(root / "a.md")].vec_text["kure-v1"]


def test_limit_and_dry_run(cfg):
    root = root_of(cfg)
    for name in ("a.txt", "b.txt", "c.txt"):
        (root / name).write_text(f"file {name}", encoding="utf-8")
    dry = index(cfg, encoder=FakeEncoder(), dry_run=True)
    assert (dry.new, dry.records, dry.batches) == (3, 0, [])
    assert not list(Path(cfg.outbox_dir).glob("*.jsonl"))
    s1 = index(cfg, encoder=FakeEncoder(), limit=1)
    assert (s1.new, s1.limited, s1.records) == (1, True, 1)
    s2 = index(cfg, encoder=FakeEncoder())
    assert (s2.new, s2.unchanged, s2.limited) == (2, 1, False)
    (root / "a.txt").unlink()
    dry2 = index(cfg, encoder=FakeEncoder(), dry_run=True)
    assert (dry2.tombstoned, dry2.records) == (1, 0)
    with State(cfg.state_db) as st:
        assert st.counts()["files"] == 3


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_files_are_skipped_and_kept(cfg):
    root = root_of(cfg)
    (root / "locked").mkdir()
    (root / "locked" / "inner.txt").write_text("안쪽 파일", encoding="utf-8")
    (root / "good.txt").write_text("좋은 파일", encoding="utf-8")
    bad = root / "bad.txt"
    bad.write_text("읽을 수 없는 파일", encoding="utf-8")
    bad.chmod(0)
    try:
        s = index(cfg, encoder=FakeEncoder())
        assert (s.new, s.errors) == (2, 1)
        (root / "locked").chmod(0)
        s2 = index(cfg, encoder=FakeEncoder())
        assert (s2.tombstoned, s2.kept_offline, s2.errors) == (0, 1, 1)
    finally:
        bad.chmod(0o644)
        (root / "locked").chmod(0o755)
    s3 = index(cfg, encoder=FakeEncoder())
    assert (s3.new, s3.errors, s3.unchanged) == (1, 0, 2)


def test_missing_root_keeps_documents(cfg, tmp_path):
    root = root_of(cfg)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    index(cfg, encoder=FakeEncoder())
    root.rename(tmp_path / "unmounted")
    s = index(cfg, encoder=FakeEncoder())
    assert (s.scanned, s.tombstoned, s.records) == (0, 0, 0)


def test_index_lock(cfg):
    with exclusive_lock(cfg.state_db + ".lock"):
        with pytest.raises(Busy):
            index(cfg, encoder=FakeEncoder())


def test_config_defaults_init_and_validation(tmp_path, monkeypatch):
    for var in ("TIDY_DB", "TIDY_MODEL_DIR"):
        monkeypatch.delenv(var, raising=False)
    path = tmp_path / "cfg" / "config.toml"
    monkeypatch.setenv("TIDY_CONFIG", str(path))
    d = load_config()
    assert d.path == "" and not d.device_id_pinned and d.device_id == hostname_slug()
    assert d.roots == [os.path.abspath(os.path.expanduser(r)) for r in DEFAULT_ROOTS]
    assert d.hub.ssh is None and d.hub.remote_cmd == "tidy ingest -" and d.excludes == []
    assert d.outbox_dir.endswith("/.local/share/tidy-one/outbox")

    p, created = write_default_config()
    assert p == path and created
    text = path.read_text(encoding="utf-8")
    assert write_default_config() == (path, False) and path.read_text(encoding="utf-8") == text
    c = load_config()
    assert c.path == str(path) and c.device_id_pinned and c.roots == d.roots and c.hub.ssh is None

    monkeypatch.setenv("TIDY_DB", str(tmp_path / "env.sqlite"))
    assert load_config().catalog_db == str(tmp_path / "env.sqlite")

    assert hostname_slug("Junwon-MacBook-Air.local") == "junwon-macbook-air"
    assert hostname_slug("홍길동의 MacBook Pro") == "macbook-pro"
    bad = tmp_path / "bad.toml"
    for body in ('rootz = ["~"]', 'device_id = "a:b"', "roots = '~/Documents'", '[hub]\nsssh = "x"'):
        bad.write_text(body, encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(bad)


def test_launchd_plist():
    with open(REPO / "client" / "macos" / "com.tidy-one.agent.plist", "rb") as f:
        pl = plistlib.load(f)
    assert pl["Label"] == "com.tidy-one.agent"
    assert pl["StartInterval"] == 1800 and pl["Nice"] == 10 and pl["LowPriorityIO"] is True
    sh, flag, script = pl["ProgramArguments"]
    assert (sh, flag) == ("/bin/sh", "-lc")
    assert "~/.local/bin/tidy index && ~/.local/bin/tidy push" in script
    assert "Library/Logs/tidy-one.log" in script


# -- regressions ---------------------------------------------------------------


def test_push_keeps_a_batch_the_hub_could_not_apply(cfg, tmp_path, monkeypatch):
    """A batch with failed lines (database locked, older hub) stays in the outbox and its files unpushed."""
    root = root_of(cfg)
    (root / "회의록.md").write_text(MEETING, encoding="utf-8")
    stats = index(cfg, encoder=FakeEncoder())
    db = str(tmp_path / "local.sqlite")
    real_apply = Catalog.apply

    def locked(self, rec):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Catalog, "apply", locked)
    ps = push(cfg, local_db=db)
    assert ps.sent == [] and ps.pending == 1 and ps.counts["failed"] == 1
    assert "could not apply 1 lines" in ps.error and "database is locked" in ps.error
    assert (Path(cfg.outbox_dir) / stats.batches[0]).exists()
    with State(cfg.state_db) as st:
        assert st.counts()["unpushed"] == 1
    assert index(cfg, encoder=FakeEncoder()).records == 0  # the file is unchanged; the batch is what gets retried

    monkeypatch.setattr(Catalog, "apply", real_apply)
    ps2 = push(cfg, local_db=db)
    assert ps2.error is None and ps2.sent == stats.batches and ps2.counts["upserted"] == 1
    with State(cfg.state_db) as st:
        assert st.counts()["unpushed"] == 0
    assert search_ids(db, "마케팅 회의") == [file_doc_id("test-mac", disk_path(root / "회의록.md"))]


def test_push_over_ssh_treats_failed_lines_as_undelivered(cfg):
    root = root_of(cfg)
    (root / "a.txt").write_text("메모 하나", encoding="utf-8")
    stats = index(cfg, encoder=FakeEncoder())
    cfg.hub.ssh = "memory@hub"
    out = {"upserted": 0, "deleted": 0, "failed": 1, "errors": [{"line_no": 1, "error": "TypeError: unexpected"}]}

    def old_hub(cmd, stdin, capture_output, timeout):  # an older `tidy ingest` that exits 0 on failed lines
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out).encode() + b"\n", stderr=b"")

    ps = push(cfg, run=old_hub)
    assert ps.sent == [] and ps.pending == 1 and "TypeError" in ps.error

    def new_hub(cmd, stdin, capture_output, timeout):  # `tidy ingest` now exits 1 when a line failed
        err = b"tidy ingest: 1 lines not applied\n"
        return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps(out).encode() + b"\n", stderr=err)

    ps = push(cfg, run=new_hub)
    assert ps.sent == [] and ps.pending == 1 and "exited 1" in ps.error and "TypeError" in ps.error
    assert (Path(cfg.outbox_dir) / stats.batches[0]).exists()


def test_removing_a_root_withdraws_its_documents(tmp_path, monkeypatch):
    for var in ("TIDY_DB", "TIDY_MODEL_DIR", "TIDY_CONFIG", "TIDY_FAKE_ENCODER"):
        monkeypatch.delenv(var, raising=False)
    public, private = tmp_path / "public", tmp_path / "private"
    (public / "work").mkdir(parents=True)
    private.mkdir()
    (public / "work" / "plan.md").write_text(MEETING, encoding="utf-8")
    (public / "todo.txt").write_text("장보기 목록", encoding="utf-8")
    (private / "diary.txt").write_text("개인 일기: 오늘은 쉬었다", encoding="utf-8")
    write_config(tmp_path / "config.toml", public, tmp_path / "data")
    cfg = load_config(tmp_path / "config.toml")
    cfg.roots = [str(public), str(private)]
    db = str(tmp_path / "local.sqlite")
    index(cfg, encoder=FakeEncoder())
    push(cfg, local_db=db)
    diary = file_doc_id("test-mac", disk_path(private / "diary.txt"))
    assert diary in search_ids(db, "개인 일기")

    cfg.roots = [str(public)]  # the owner takes the private folder out of the index
    s = index(cfg, encoder=FakeEncoder())
    assert (s.tombstoned, s.unrooted, s.records) == (1, 1, 1)
    push(cfg, local_db=db)
    assert diary not in search_ids(db, "개인 일기")
    with State(cfg.state_db) as st:
        assert st.get(disk_path(private / "diary.txt")) is None

    cfg.roots = [str(public / "work")]  # narrowing a root works the same way
    s2 = index(cfg, encoder=FakeEncoder())
    assert (s2.tombstoned, s2.unrooted, s2.unchanged) == (1, 1, 1)


def test_rules_change_rechecks_unchanged_files(cfg, tmp_path, monkeypatch):
    """A secret the old rules missed is withdrawn once the rules learn it, though the file never changed."""
    from tidy_one.agent import run as run_mod
    from tidy_one.extract import sensitive

    root = root_of(cfg)
    (root / "notes.txt").write_text("배포 메모\nDEPLOY_KEY=zzk-AbCdEfGhIjKlMnOpQrSt\n", encoding="utf-8")
    (root / "plan.md").write_text(MEETING, encoding="utf-8")
    db = str(tmp_path / "local.sqlite")
    enc = CountingEncoder()
    assert index(cfg, encoder=enc).records == 2
    push(cfg, local_db=db)
    notes = file_doc_id("test-mac", disk_path(root / "notes.txt"))
    assert notes in search_ids(db, "배포 메모")

    monkeypatch.setattr(sensitive, "_SECRET_CONTENT", [*sensitive._SECRET_CONTENT, re.compile(r"zzk-[A-Za-z]{20}")])
    monkeypatch.setattr(run_mod, "CHECK_STAMP", "rules-v2")
    embedded = len(enc.texts)
    s = index(cfg, encoder=enc)
    assert (s.secret, s.tombstoned, s.touched, s.records, s.unchanged) == (1, 1, 1, 1, 0)
    assert len(enc.texts) == embedded  # the unchanged, still-clean file is neither re-sent nor re-embedded
    ups, dels = records(outbox_lines(cfg, s.batches))
    assert ups == {} and dels == [notes]
    push(cfg, local_db=db)
    assert notes not in search_ids(db, "배포 메모")
    again = index(cfg, encoder=enc)
    assert (again.unchanged, again.records) == (2, 0)


def test_old_state_without_rules_column_is_migrated(tmp_path):
    path = str(tmp_path / "state.sqlite")
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE files (path TEXT PRIMARY KEY, doc_id TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL NOT NULL, "
        "content_hash TEXT, chunk_hashes TEXT NOT NULL DEFAULT '[]', model_id TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'indexed', indexed_at TEXT NOT NULL, batch TEXT, pushed_at TEXT);"
        "INSERT INTO files(path, doc_id, size, mtime, indexed_at) VALUES ('/a', 'file:x:1', 1, 1.0, 'now');"
    )
    db.close()
    with State(path) as st:
        row = st.get("/a")
        assert row is not None and row.rules == ""  # never checked under the current rules: re-checked next run


def test_no_embed_writes_records_as_it_goes(cfg, monkeypatch):
    """Without an encoder, documents must not pile up in memory until the whole scan ends."""
    from tidy_one.agent import run as run_mod

    monkeypatch.setattr(run_mod, "EMBED_POOL", 2)
    root = root_of(cfg)
    for i in range(6):
        (root / f"note{i}.txt").write_text(f"메모 {i}번 내용", encoding="utf-8")
    seen_at: list[int] = []
    real_emit = run_mod.Indexer._emit

    def spy(self, line, op):
        seen_at.append(self.stats.scanned)
        real_emit(self, line, op)

    monkeypatch.setattr(run_mod.Indexer, "_emit", spy)
    s = index(cfg, embed=False)
    assert s.records == 6 and seen_at[0] < 6


def test_dates_use_the_device_local_day(cfg, tmp_path, monkeypatch):
    """A file changed at 08:30 KST on March 5 is found by a March 5 filter, not March 4."""
    monkeypatch.setenv("TZ", "Asia/Seoul")
    time.tzset()
    try:
        root = root_of(cfg)
        p = root / "morning.txt"
        p.write_text("아침 회의 메모", encoding="utf-8")
        ts = datetime.fromisoformat("2024-03-05T08:30:00+09:00").timestamp()
        os.utime(p, (ts, ts))
        s = index(cfg, encoder=FakeEncoder())
        ups, _ = records(outbox_lines(cfg, s.batches))
        doc = ups[disk_path(p)].document
        assert doc.updated_at == "2024-03-05T08:30:00+09:00"
        assert "수정: 2024년 3월 5일" in ups[disk_path(p)].chunks[-1].text
        db = str(tmp_path / "local.sqlite")
        push(cfg, local_db=db)
        qv = FakeEncoder().encode_query("아침 회의")
        with Catalog(db) as cat:
            for vec in (None, qv):
                assert [h["doc_id"] for h in cat.search("회의", vec, None, date_from="2024-03-05",
                                                        date_to="2024-03-05")] == [doc.doc_id]
                assert cat.search("회의", vec, None, date_from="2024-03-04", date_to="2024-03-04") == []
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_state_outbox_and_catalog_files_are_owner_only(cfg, tmp_path):
    old = os.umask(0o022)
    try:
        (root_of(cfg) / "a.txt").write_text("메모", encoding="utf-8")
        s = index(cfg, encoder=FakeEncoder())
        assert stat.S_IMODE((Path(cfg.outbox_dir) / s.batches[0]).stat().st_mode) == 0o600
        assert stat.S_IMODE(Path(cfg.outbox_dir).stat().st_mode) == 0o700
        fresh = str(tmp_path / "fresh" / "state.sqlite")
        with State(fresh) as st:  # the first open creates -wal and -shm; they exist while it is open
            st.set_meta("probe", "1")
            for p in (fresh, fresh + "-wal", fresh + "-shm"):
                assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p
        db = str(tmp_path / "local" / "catalog.sqlite")
        push(cfg, local_db=db)
        with Catalog(db) as cat:
            assert cat.stats()["documents"] == 1
            for p in (db, db + "-wal", db + "-shm"):
                assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p
    finally:
        os.umask(old)


class TokenEncoder(FakeEncoder):
    """Fake encoder with a tokenizer: one token per Hangul syllable, one per 4 other characters."""

    max_len = 512

    def count_tokens(self, texts: list[str]) -> list[int]:
        return [2 + sum(1 for ch in t if "가" <= ch <= "힣") + sum(1 for ch in t if not "가" <= ch <= "힣") // 4
                for t in texts]


def test_index_splits_chunks_the_model_would_truncate(cfg, tmp_path):
    root = root_of(cfg)
    dense = "".join(f"근로계약서표준양식개정안검토결과보고서{i}번. " for i in range(120))
    (root / "dense.txt").write_text(dense, encoding="utf-8")
    enc = TokenEncoder()
    s = index(cfg, encoder=enc)
    ups, _ = records(outbox_lines(cfg, s.batches))
    body = [c.text for c in ups[disk_path(root / "dense.txt")].chunks if c.field == "body"]
    assert max(enc.count_tokens(body)) <= 512
    db = str(tmp_path / "local.sqlite")
    push(cfg, local_db=db)
    with Catalog(db) as cat:
        text = cat.fetch(file_doc_id("test-mac", disk_path(root / "dense.txt")), 0, 100_000)["text"]
    assert text.split("\n\n제목:")[0] == dense.strip()


def test_rtf_with_emoji_is_indexed(cfg):
    bs = chr(92)
    rtf = "{" + bs + "rtf1" + bs + "ansi " + bs + "uc0" + "".join(f"{bs}u{c} " for c in (54924, -10179, -8704)) + \
          " memo" + bs + "par}"
    (root_of(cfg) / "memo.rtf").write_text(rtf, encoding="utf-8")
    s = index(cfg, encoder=FakeEncoder())
    assert (s.records, s.errors) == (1, 0)
    assert index(cfg, encoder=FakeEncoder()).unchanged == 1
