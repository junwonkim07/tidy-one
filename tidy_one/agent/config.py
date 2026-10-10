"""Device agent configuration: `~/.config/tidy-one/config.toml` (or `$TIDY_CONFIG`) over built-in defaults."""

from __future__ import annotations

import json
import os
import re
import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = "~/.config/tidy-one/config.toml"
DEFAULT_ROOTS = ["~/Documents", "~/Desktop", "~/Downloads", "~/Library/Mobile Documents/com~apple~CloudDocs"]
DEFAULT_OUTBOX = "~/.local/share/tidy-one/outbox"
DEFAULT_STATE = "~/.local/share/tidy-one/state.sqlite"
DEFAULT_CATALOG = "~/.local/share/tidy-one/catalog.sqlite"
DEFAULT_MODEL_DIR = "~/.cache/tidy-one/models"
DEFAULT_REMOTE_CMD = "tidy ingest -"
DEVICE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

_KEYS = {"device_id", "roots", "excludes", "outbox_dir", "state_db", "model_dir", "catalog_db", "keep_sent_days", "hub"}
_HUB_KEYS = {"ssh", "remote_cmd", "ssh_args", "timeout"}


class ConfigError(ValueError):
    pass


@dataclass
class HubConfig:
    ssh: str | None = None  # ssh target, e.g. "memory@hub" or a ~/.ssh/config alias
    remote_cmd: str = DEFAULT_REMOTE_CMD
    ssh_args: list[str] = field(default_factory=list)
    timeout: float = 1800.0


@dataclass
class Config:
    device_id: str
    roots: list[str]
    excludes: list[str]
    outbox_dir: str
    state_db: str
    model_dir: str
    catalog_db: str
    hub: HubConfig = field(default_factory=HubConfig)
    keep_sent_days: int = 7
    path: str = ""  # file the config was read from ("" if none existed)
    device_id_pinned: bool = False  # device_id came from the file, not the hostname


def config_path() -> Path:
    return Path(os.environ.get("TIDY_CONFIG") or DEFAULT_CONFIG).expanduser()


def hostname_slug(name: str | None = None) -> str:
    """'Junwon-MacBook-Air.local' -> 'junwon-macbook-air'."""
    name = (name if name is not None else socket.gethostname()).split(".")[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:63]
    return slug or "device"


def _expand(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))


def _str_list(v: object, key: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{key} must be a list of strings")
    return list(v)


def _str(v: object, key: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return v


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Read the TOML config (missing file = all defaults). Env `TIDY_MODEL_DIR` and `TIDY_DB` override
    `model_dir` and `catalog_db`. Unknown keys are rejected so typos do not silently index the wrong folders."""
    p = Path(path).expanduser() if path else config_path()
    data: dict = {}
    if p.exists():
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{p}: {e}") from None
    unknown = set(data) - _KEYS
    if unknown:
        raise ConfigError(f"{p}: unknown keys {sorted(unknown)}")
    hub_data = data.get("hub", {})
    if not isinstance(hub_data, dict):
        raise ConfigError("[hub] must be a table")
    unknown = set(hub_data) - _HUB_KEYS
    if unknown:
        raise ConfigError(f"{p}: unknown [hub] keys {sorted(unknown)}")

    device_id = data.get("device_id")
    if device_id is not None:
        device_id = _str(device_id, "device_id").strip()
        if not DEVICE_ID.match(device_id):
            raise ConfigError("device_id must be lowercase letters, digits, '.', '_' or '-' (no ':')")
    ssh = hub_data.get("ssh")
    timeout = hub_data.get("timeout", 1800.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError("hub.timeout must be a positive number of seconds")
    hub = HubConfig(
        ssh=_str(ssh, "hub.ssh") if ssh is not None else None,
        remote_cmd=_str(hub_data.get("remote_cmd", DEFAULT_REMOTE_CMD), "hub.remote_cmd"),
        ssh_args=_str_list(hub_data.get("ssh_args", []), "hub.ssh_args"),
        timeout=float(timeout),
    )
    keep = data.get("keep_sent_days", 7)
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 0:
        raise ConfigError("keep_sent_days must be a non-negative integer")
    model_dir = os.environ.get("TIDY_MODEL_DIR") or _str(data.get("model_dir", DEFAULT_MODEL_DIR), "model_dir")
    catalog_db = os.environ.get("TIDY_DB") or _str(data.get("catalog_db", DEFAULT_CATALOG), "catalog_db")
    return Config(
        device_id=device_id or hostname_slug(),
        roots=[_expand(r) for r in _str_list(data.get("roots", DEFAULT_ROOTS), "roots")],
        excludes=_str_list(data.get("excludes", []), "excludes"),
        outbox_dir=_expand(_str(data.get("outbox_dir", DEFAULT_OUTBOX), "outbox_dir")),
        state_db=_expand(_str(data.get("state_db", DEFAULT_STATE), "state_db")),
        model_dir=_expand(model_dir),
        catalog_db=_expand(catalog_db),
        hub=hub,
        keep_sent_days=keep,
        path=str(p) if p.exists() else "",
        device_id_pinned=device_id is not None,
    )


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def default_config_text(device_id: str | None = None) -> str:
    roots = "\n".join(f"  {_toml_str(r)}," for r in DEFAULT_ROOTS)
    return f"""# tidy-one device agent. Paths may start with ~.

# Part of every document id from this device: set it once and keep it.
device_id = {_toml_str(device_id or hostname_slug())}

# Folders to index. iCloud files that are only in the cloud are skipped, never downloaded.
roots = [
{roots}
]

# Globs to skip. Without "/" they match a file or folder name; with "/" the full path.
excludes = [
  # "*.dmg",
  # "~/Documents/Private/*",
]

# Batches wait here until `tidy push` sends them; sent ones move to outbox/sent/ and are
# removed after keep_sent_days.
outbox_dir = {_toml_str(DEFAULT_OUTBOX)}
keep_sent_days = 7
state_db = {_toml_str(DEFAULT_STATE)}
model_dir = {_toml_str(DEFAULT_MODEL_DIR)}

# Local catalog for `tidy push --local`, `tidy search` and `tidy serve` on this Mac.
catalog_db = {_toml_str(DEFAULT_CATALOG)}

[hub]
# ssh target of the hub (user@host or a ~/.ssh/config alias). Unset = nothing leaves this Mac.
# ssh = "memory@hub.example"
remote_cmd = {_toml_str(DEFAULT_REMOTE_CMD)}
# ssh_args = ["-p", "2222"]
"""


def write_default_config(path: str | os.PathLike[str] | None = None) -> tuple[Path, bool]:
    """Write the commented default config unless the file exists. Returns (path, created)."""
    p = Path(path).expanduser() if path else config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "x", encoding="utf-8") as f:
            f.write(default_config_text())
    except FileExistsError:
        return p, False
    return p, True
