"""Walk local folders for indexable files without following symlinks or waking iCloud placeholders."""

from __future__ import annotations

import fnmatch
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Iterator

from tidy_one.extract.sensitive import is_secret_dirname, is_secret_path

SF_DATALESS = getattr(stat, "SF_DATALESS", 0x40000000)  # <sys/stat.h>: iCloud "optimised storage" placeholder
UF_HIDDEN = getattr(stat, "UF_HIDDEN", 0x00008000)
MAX_FILE_BYTES = 200 * 1024 * 1024

SKIP_DIRS = frozenset({
    "node_modules", "bower_components", "venv", "__pycache__", "site-packages", "DerivedData",
    "Pods", "Carthage", "__MACOSX", "$RECYCLE.BIN", "System Volume Information",
})
BUILD_DIRS = frozenset({"build", "dist", "target", "out", "_build"})
PROJECT_MARKERS = frozenset({
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml", "go.mod", "pom.xml",
    "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile", "Package.swift", "Gemfile",
    "composer.json", "mix.exs", "pubspec.yaml",
})
PACKAGE_SUFFIXES = (
    ".app", ".photoslibrary", ".photolibrary", ".migratedphotolibrary", ".aplibrary", ".bundle",
    ".framework", ".plugin", ".kext", ".xpc", ".appex", ".xcodeproj", ".xcworkspace", ".xcarchive",
    ".musiclibrary", ".tvlibrary", ".imovielibrary", ".fcpbundle", ".logicx", ".band", ".sparsebundle",
    ".lrdata", ".egg-info", ".dist-info", ".noindex", ".download",
)
SKIP_FILE_SUFFIXES = (".crdownload", ".part", ".partial", ".tmp", ".swp", ".lock")
CACHEDIR_TAG = "CACHEDIR.TAG"  # https://bford.info/cachedir/: tools mark regenerable cache folders with it


@dataclass
class FileInfo:
    path: str
    size: int
    mtime: float  # epoch seconds
    ctime: float  # creation time (st_birthtime on macOS, else st_ctime)


class _Excludes:
    """User glob excludes. Patterns without '/' match the file or folder name; others match the full path."""

    def __init__(self, patterns: Iterable[str]):
        names, paths = [], []
        for p in patterns:
            p = _nfc(os.path.expanduser(p.strip())).lower()
            if not p:
                continue
            if "/" in p.rstrip("/"):
                p = p.rstrip("/")
                if not p.startswith(("/", "*")):
                    p = "*/" + p
                paths.append(p)
            else:
                names.append(p.rstrip("/"))
        self._names = re.compile("|".join(fnmatch.translate(p) for p in names)) if names else None
        self._paths = re.compile("|".join(fnmatch.translate(p) for p in paths)) if paths else None

    def match(self, path: str, name: str, is_dir: bool) -> bool:
        if self._names and self._names.match(_nfc(name).lower()):
            return True
        if self._paths:
            p = _nfc(path).lower()
            return bool(self._paths.match(p) or (is_dir and self._paths.match(p + "/")))
        return False


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _st_flags(st: os.stat_result, path: str) -> int:
    return getattr(st, "st_flags", 0)


def _birthtime(st: os.stat_result) -> float:
    return float(getattr(st, "st_birthtime", st.st_ctime))


def _skip_dir(name: str, path: str, siblings: set[str], library: str, ex: _Excludes, skip_secrets: bool) -> bool:
    low = name.lower()
    return (
        name in SKIP_DIRS
        or low.endswith(PACKAGE_SUFFIXES)
        or path == library
        or (low in BUILD_DIRS and not siblings.isdisjoint(PROJECT_MARKERS))
        or (skip_secrets and is_secret_dirname(name))
        or ex.match(path, name, True)
    )


def scan(
    roots: list[str],
    excludes: Iterable[str] = (),
    *,
    max_bytes: int = MAX_FILE_BYTES,
    skip_repos: bool = True,
    skip_secrets: bool = True,
) -> Iterator[FileInfo]:
    """Yield regular files under `roots` in sorted order.

    Skip rules apply below each root (an explicitly listed root is always walked): hidden entries,
    dev/build/cache folders, app bundles and libraries, ~/Library, code repositories (folders with
    `.git`, unless `skip_repos=False`), Python venvs, iCloud dataless placeholders, symlinks,
    files over `max_bytes`, secret-looking paths and user `excludes` globs.
    """
    ex = _Excludes(excludes)
    library = os.path.realpath(os.path.join(os.path.expanduser("~"), "Library"))
    seen: set[tuple[int, int]] = set()
    for root in roots:
        root = os.path.realpath(os.path.expanduser(root))
        try:
            st = os.stat(root)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            if st.st_size <= max_bytes and not (skip_secrets and is_secret_path(root)):
                yield FileInfo(root, st.st_size, st.st_mtime, _birthtime(st))
            continue
        if not stat.S_ISDIR(st.st_mode) or (st.st_dev, st.st_ino) in seen:
            continue
        seen.add((st.st_dev, st.st_ino))
        stack = [(root, True)]
        while stack:
            d, is_root = stack.pop()
            try:
                with os.scandir(d) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            names = {e.name for e in entries}
            if not is_root and (
                (skip_repos and ".git" in names) or "pyvenv.cfg" in names or CACHEDIR_TAG in names
            ):
                continue
            subdirs = []
            for e in entries:
                name = e.name
                if name.startswith((".", "~$")) or name == "Icon\r":
                    continue
                try:
                    est = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISLNK(est.st_mode) or _st_flags(est, e.path) & (SF_DATALESS | UF_HIDDEN):
                    continue
                if stat.S_ISDIR(est.st_mode):
                    key = (est.st_dev, est.st_ino)
                    if key in seen or _skip_dir(name, e.path, names, library, ex, skip_secrets):
                        continue
                    seen.add(key)
                    subdirs.append(e.path)
                elif stat.S_ISREG(est.st_mode):
                    if (
                        est.st_size > max_bytes
                        or name.lower().endswith(SKIP_FILE_SUFFIXES)
                        or ex.match(e.path, name, False)
                        or (skip_secrets and is_secret_path(e.path))
                    ):
                        continue
                    yield FileInfo(e.path, est.st_size, est.st_mtime, _birthtime(est))
            stack.extend((p, False) for p in reversed(subdirs))
