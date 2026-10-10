import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UV = os.environ.get("UV") or shutil.which("uv")
pytestmark = pytest.mark.skipif(UV is None, reason="uv not on PATH")

MEETING = """# 3분기 마케팅 회의록

이번 회의에서는 신제품 출시 일정과 광고 예산을 논의했다. 출시일은 11월 둘째 주로 확정했다.
"""


def tidy(env: dict, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(
        [UV, "run", "--no-sync", "tidy", *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=300
    )
    if check:
        assert p.returncode == 0, p.stderr
    return p


def last_json(out: str):
    return json.loads(out.strip().splitlines()[-1])


def write_config(path: Path, root: Path, base: Path, hub: str = "") -> None:
    q = json.dumps
    path.write_text(
        "\n".join([
            'device_id = "cli-mac"',
            f"roots = [{q(str(root))}]",
            f"outbox_dir = {q(str(base / 'outbox'))}",
            f"state_db = {q(str(base / 'state.sqlite'))}",
            f"model_dir = {q(str(base / 'models'))}",
            f"catalog_db = {q(str(base / 'local.sqlite'))}",
            hub,
        ]),
        encoding="utf-8",
    )


@pytest.fixture
def env(tmp_path):
    e = {k: v for k, v in os.environ.items() if not k.startswith("TIDY_")}
    e["TIDY_FAKE_ENCODER"] = "1"
    e["TIDY_CONFIG"] = str(tmp_path / "config.toml")
    return e


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "docs"
    r.mkdir()
    (r / "회의록.md").write_text(MEETING, encoding="utf-8")
    (r / "memo.txt").write_text("Grocery list: apples, bread, coffee beans.", encoding="utf-8")
    return r


def test_init_never_overwrites(tmp_path, env):
    cfg = tmp_path / "new" / "config.toml"
    env["TIDY_CONFIG"] = str(cfg)
    assert "wrote" in tidy(env, "init").stdout
    text = cfg.read_text(encoding="utf-8")
    assert "device_id" in text and "roots" in text and "[hub]" in text
    assert "unchanged" in tidy(env, "init").stdout
    assert cfg.read_text(encoding="utf-8") == text


def test_index_status_push_local_search(tmp_path, env, root):
    write_config(tmp_path / "config.toml", root, tmp_path / "data")
    dry = last_json(tidy(env, "index", "--dry-run", "--json").stdout)
    assert (dry["new"], dry["records"]) == (2, 0)

    s = last_json(tidy(env, "index", "--json").stdout)
    assert (s["new"], s["errors"], s["device_id"], len(s["batches"])) == (2, 0, "cli-mac", 1)
    st = last_json(tidy(env, "status", "--json").stdout)
    assert (st["files"], st["outbox_batches"], st["outbox_records"], st["unpushed"]) == (2, 1, 2, 2)
    assert st["device_id"] == "cli-mac" and st["hub"] is None

    batch = tmp_path / "data" / "outbox" / s["batches"][0]
    counts = last_json(tidy(env, "ingest", str(batch), "--db", str(tmp_path / "other.sqlite")).stdout)
    # hub ingest reports `failed` (int) plus an `errors` list; the fallback apply_lines uses the same count keys
    assert counts["upserted"] == 2 and not counts.get("failed") and not counts.get("errors")

    ps = last_json(tidy(env, "push", "--local", "--json").stdout)
    assert ps["sent"] == s["batches"] and ps["error"] is None and ps["blocked"] == 0
    assert (tmp_path / "data" / "local.sqlite").exists()

    hits = last_json(tidy(env, "search", "마케팅 회의", "--json").stdout)
    assert hits[0]["title"] == "3분기 마케팅 회의록" and hits[0]["source_id"] == "file:cli-mac"
    out = tidy(env, "search", "마케팅 회의", "--k", "3").stdout
    assert "3분기 마케팅 회의록" in out and "회의록.md" in out
    other = last_json(tidy(env, "search", "coffee", "--db", str(tmp_path / "other.sqlite"), "--json").stdout)
    assert other[0]["title"] == "memo"

    st2 = last_json(tidy(env, "status", "--json").stdout)
    assert (st2["outbox_batches"], st2["sent_batches"], st2["unpushed"]) == (0, 1, 0)
    assert "batches pending" in tidy(env, "status").stdout


def test_push_over_ssh_into_ingest(tmp_path, env, root):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text('#!/bin/sh\nfor last; do :; done\nexec /bin/sh -c "$last"\n', encoding="utf-8")
    ssh.chmod(0o755)
    hub_db = tmp_path / "hub" / "catalog.sqlite"
    remote = f"{shlex.quote(sys.executable)} -m tidy_one.cli -q ingest - --db {shlex.quote(str(hub_db))}"
    hub = f'[hub]\nssh = "fakehub"\nremote_cmd = {json.dumps(remote)}'
    write_config(tmp_path / "config.toml", root, tmp_path / "data", hub)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

    tidy(env, "index")
    ps = last_json(tidy(env, "push", "--json").stdout)
    assert ps["error"] is None and len(ps["sent"]) == 1 and ps["lines"] == 2 and ps["target"] == "fakehub"
    assert ps["counts"].get("failed", 0) == 0
    hits = last_json(tidy(env, "search", "마케팅", "--db", str(hub_db), "--json").stdout)
    assert hits[0]["title"] == "3분기 마케팅 회의록"

    ssh.write_text('#!/bin/sh\necho "ssh: connect to host fakehub port 22: Connection refused" >&2\nexit 255\n',
                   encoding="utf-8")
    (root / "new.txt").write_text("새 메모", encoding="utf-8")
    tidy(env, "index")
    p = tidy(env, "push", check=False)
    assert p.returncode == 1 and "255" in p.stdout and "refused" in p.stdout
    assert last_json(tidy(env, "status", "--json").stdout)["outbox_batches"] == 1


def test_cli_errors(tmp_path, env, root):
    write_config(tmp_path / "config.toml", root, tmp_path / "data")
    tidy(env, "-q", "index")
    p = tidy(env, "push", check=False)
    assert p.returncode == 1 and "hub.ssh" in p.stderr
    missing = tmp_path / "none.sqlite"
    p = tidy(env, "search", "x", "--db", str(missing), check=False)
    assert p.returncode == 1 and "no catalog" in p.stderr and not missing.exists()
    (tmp_path / "config.toml").write_text("roots = 1\n", encoding="utf-8")
    p = tidy(env, "status", check=False)
    assert p.returncode == 1 and "roots" in p.stderr


def test_serve_passes_db_port_and_model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`tidy serve` hands the hub the catalog, port and model_dir (flag, else env, else config)."""
    import importlib

    from tidy_one import cli

    server = importlib.import_module("tidy_one.hub.server")
    calls: list[dict] = []

    def fake_run(db: str | None = None, port: int | None = None, model_dir: str | None = None) -> None:
        calls.append({"db": db, "port": port, "model_dir": model_dir})

    monkeypatch.setattr(server, "run", fake_run)
    cfg = tmp_path / "config.toml"
    write_config(cfg, tmp_path / "root", tmp_path)
    # serve exports TIDY_DB/TIDY_PORT/TIDY_MODEL_DIR for the hub; give it a private copy of the environment
    env = {k: v for k, v in os.environ.items() if k not in ("TIDY_MODEL_DIR", "TIDY_DB", "TIDY_PORT")}
    monkeypatch.setattr(os, "environ", env)

    assert cli.main(["-c", str(cfg), "serve", "--db", str(tmp_path / "c.sqlite"), "--port", "8123"]) == 0
    assert calls[-1] == {"db": str(tmp_path / "c.sqlite"), "port": 8123, "model_dir": str(tmp_path / "models")}

    for var in ("TIDY_MODEL_DIR", "TIDY_DB", "TIDY_PORT"):
        env.pop(var, None)
    assert cli.main(["-c", str(cfg), "serve", "--model-dir", str(tmp_path / "m2")]) == 0
    assert calls[-1]["model_dir"] == str(tmp_path / "m2")
    assert calls[-1]["db"] == str(tmp_path / "local.sqlite") and calls[-1]["port"] is None
