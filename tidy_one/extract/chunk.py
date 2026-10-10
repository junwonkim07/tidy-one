"""Korean-aware chunking: ~900-char body chunks with overlap, plus one metadata chunk per document.

Text is cut at the coarsest boundary that fits: blank lines, then sentence ends (`다.`, `요.`, any
Hangul + `.?!`, `. `, `? `, `! `, CJK full stops), then line breaks, then spaces; only a run with no
whitespace at all is cut mid-token. Chunks never span two pages.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import unicodedata
from typing import Callable, Iterable, Protocol

from tidy_one.model import Chunk, chunk_hash_for, finalize_chunks

_CLOSE = "\"'”’)\\]」』》〉"
_PARA = re.compile(r"\n[ \t]*\n\s*")
_SENT = re.compile(
    rf"(?:(?<=[가-힣])[.?!]+(?=[\s가-힣{_CLOSE}]|$)|[.?!…]+(?=[\s{_CLOSE}]|$)|[。？！]+)[{_CLOSE}]*[ \t]*"
)
_LINE = re.compile(r"\n+")
_WORD = re.compile(r"\s+")
_LEVELS = (_PARA, _SENT, _LINE, _WORD)

_HOME_KO = {"Desktop": "데스크탑", "Documents": "문서", "Downloads": "다운로드", "Pictures": "사진",
            "Movies": "동영상", "Music": "음악", "Public": "공개"}

MAX_CHARS = 900
OVERLAP = 120
CHUNKER_VERSION = 2  # bump when chunk boundaries change; the agent then re-chunks unchanged files once


class _Block(Protocol):
    text: str
    page: int | None


def _cut(text: str, pat: re.Pattern[str]) -> list[str]:
    parts, start = [], 0
    for m in pat.finditer(text):
        end = m.end()
        if start < end < len(text):
            parts.append(text[start:end])
            start = end
    parts.append(text[start:])
    return [p for p in parts if p]


def split_text(text: str, limit: int, level: int = 0) -> list[str]:
    """Pieces of at most `limit` chars whose concatenation is `text`, cut at the coarsest boundary."""
    if len(text) <= limit:
        return [text]
    for i in range(level, len(_LEVELS)):
        parts = _cut(text, _LEVELS[i])
        if len(parts) > 1:
            return [q for p in parts for q in split_text(p, limit, i)]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _tail(text: str, n: int) -> str:
    """Last <= n chars of `text`, starting at a sentence or line start if possible, else at a word start."""
    if n <= 0:
        return ""
    if len(text) <= n:
        return text.lstrip()
    t = text[-n:]
    for pat in (_SENT, _LINE):
        m = pat.search(t)
        if m and len(t) - m.end() >= n // 4:
            return t[m.end() :].lstrip()
    if text[-n - 1].isspace():
        return t.lstrip()
    m = _WORD.search(t)
    if m and m.end() < len(t):
        return t[m.end() :]
    return t


def _pack(pieces: list[str], max_chars: int, overlap: int) -> list[str]:
    out: list[str] = []
    cur = ""
    for p in pieces:
        if cur and len(cur) + len(p) > max_chars:
            out.append(cur)
            cur = _tail(cur, overlap)
        cur += p
    out.append(cur)
    return [c.strip() for c in out if c.strip()]


_WS_RUN = re.compile(r"\s+")


def repeated_prefix(prev: str, nxt: str, overlap: int = OVERLAP) -> int | None:
    """Length of the start of `nxt` that `_pack` copied from the end of `prev` (consecutive body chunks of
    one page), or None when `nxt` does not begin the way `_pack` would have begun it.

    `_pack` started `nxt` with `_tail(cur, overlap)`, where `cur` was `prev` plus the whitespace its
    `strip()` removed; that whitespace also follows the repeated text inside `nxt`, so each whitespace
    run there is tried. Recomputing the tail is exact even for repetitive text (identical rows or
    sentences), where searching for the longest suffix that `nxt` starts with would swallow new rows."""
    if not prev or not nxt:
        return None
    cands = {""}
    for m in _WS_RUN.finditer(nxt, 0, overlap + 64):
        if m.start() <= overlap:
            run = m.group()
            cands.update(run[:k] for k in range(1, len(run) + 1))
    for w in sorted(cands, key=len, reverse=True):
        t = _tail(prev + w, overlap)
        if len(t) > len(w) and nxt.startswith(t):
            return len(t) - len(w)
    return None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _when(v: float | int | str | dt.datetime | None) -> dt.datetime | None:
    try:
        if v is None:
            return None
        if isinstance(v, dt.datetime):
            d = v
        elif isinstance(v, (int, float)):
            return dt.datetime.fromtimestamp(v)
        else:
            d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.astimezone() if d.tzinfo else d
    except (ValueError, OSError, OverflowError):
        return None


def korean_date(v: float | int | str | dt.datetime | None) -> str | None:
    """'2026년 10월 3일 (2026-10-03)' in local time, or None."""
    d = _when(v)
    return f"{d.year}년 {d.month}월 {d.day}일 ({d:%Y-%m-%d})" if d else None


def path_components(path: str) -> list[str]:
    """Folder names of `path` relative to the home folder (iCloud Drive and Korean names spelled out)."""
    path = unicodedata.normalize("NFC", os.path.expanduser(path))
    home = unicodedata.normalize("NFC", os.path.expanduser("~"))
    folder = os.path.dirname(path)
    rel = os.path.relpath(folder, home) if folder == home or folder.startswith(home + os.sep) else folder
    parts = [p for p in rel.split(os.sep) if p and p != "."]
    if parts[:3] == ["Library", "Mobile Documents", "com~apple~CloudDocs"]:
        parts = ["iCloud Drive", *parts[3:]]
    elif parts[:2] == ["Library", "CloudStorage"]:
        parts = parts[2:]
    if parts and parts[0] in _HOME_KO:
        parts[0] = f"{parts[0]}({_HOME_KO[parts[0]]})"
    return parts


def meta_text(
    title: str | None = None,
    path: str | None = None,
    created: float | str | dt.datetime | None = None,
    modified: float | str | dt.datetime | None = None,
    extra: Iterable[str] = (),
) -> str:
    lines = []
    if title:
        lines.append(f"제목: {unicodedata.normalize('NFC', title)}")
    if path:
        folders = path_components(path)
        if folders:
            lines.append("폴더: " + " / ".join(folders))
        lines.append("파일: " + unicodedata.normalize("NFC", os.path.basename(path)))
    for label, v in (("수정", modified), ("생성", created)):
        d = korean_date(v)
        if d:
            lines.append(f"{label}: {d}")
    lines.extend(e for e in extra if e)
    return "\n".join(lines)


def _fit_tokens(
    chunks: list[str], max_chars: int, overlap: int, count_tokens: Callable[[list[str]], list[int]], max_tokens: int
) -> list[str]:
    """Re-split every chunk the embedding model would truncate (more than `max_tokens` tokens). Dense
    Hangul, Hanja or emoji text runs well past 0.57 tokens per character, so 900 characters can exceed
    512 tokens. A chunk that fits is kept as it is, so its hash, and the cached vector, do not change."""
    out: list[str] = []
    for text, n in zip(chunks, count_tokens(chunks), strict=True):
        limit = int(min(len(text), max_chars) * max_tokens / max(n, 1) * 0.9)
        if n <= max_tokens or limit < 2 * overlap + 16:
            out.append(text)
            continue
        out.extend(_fit_tokens(_pack(split_text(text, limit - overlap), limit, overlap), limit, overlap,
                               count_tokens, max_tokens))
    return out


def chunk_blocks(
    blocks: Iterable[_Block],
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP,
    *,
    title: str | None = None,
    path: str | None = None,
    created: float | str | dt.datetime | None = None,
    modified: float | str | dt.datetime | None = None,
    meta_extra: Iterable[str] = (),
    doc_id: str | None = None,
    count_tokens: Callable[[list[str]], list[int]] | None = None,
    max_tokens: int = 512,
) -> list[Chunk]:
    """Body chunks (`field="body"`, page kept) followed by one `field="meta"` chunk.

    Consecutive blocks on the same page are merged before splitting. Ordinals are unique per
    document with the meta chunk last. With `doc_id`, chunk ids and hashes are filled via
    `finalize_chunks`; without it only hashes are. With `count_tokens` (the embedding model's
    tokenizer), body chunks longer than `max_tokens` tokens are split further so none is truncated.
    """
    overlap = max(0, min(overlap, max_chars // 2))
    groups: list[tuple[int | None, list[str]]] = []
    for b in blocks:
        if groups and groups[-1][0] == b.page:
            groups[-1][1].append(b.text)
        else:
            groups.append((b.page, [b.text]))
    out: list[Chunk] = []
    for page, texts in groups:
        text = _normalize("\n\n".join(texts))
        if not text:
            continue
        pieces = _pack(split_text(text, max_chars - overlap), max_chars, overlap)
        if count_tokens is not None:
            pieces = _fit_tokens(pieces, max_chars, overlap, count_tokens, max_tokens)
        for t in pieces:
            out.append(Chunk(ordinal=len(out), text=t, field="body", page=page))
    meta = meta_text(title, path, created, modified, meta_extra)
    if meta:
        out.append(Chunk(ordinal=len(out), text=meta[:max_chars], field="meta"))
    if doc_id:
        return finalize_chunks(doc_id, out)
    for c in out:
        c.chunk_hash = c.chunk_hash or chunk_hash_for(c.text)
    return out
