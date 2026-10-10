"""Korean-aware analysis for FTS5: Kiwi content morphemes joined by spaces.

The same `morph()` runs on documents and on queries, so whatever Kiwi does to a word it
does on both sides. Output is meant for an FTS5 `unicode61 tokenchars '_'` column.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from typing import Any

_NOUNS = {"NNG", "NNP", "NR", "XR", "SH", "SN"}
_STEMS = {"VV", "VA"}
_PREFIXED = {"NNG", "NNP", "XR"}  # what a prefix (XPN: 비, 불, 재, 미 ...) attaches to
_CONTENT = _NOUNS | _STEMS | {"NNB", "SL"}  # tags whose end marks where a word's particles and endings begin
_WEB = {"W_URL", "W_EMAIL", "W_HASHTAG", "W_MENTION", "W_SERIAL"}
_STOP_STEMS = {"하", "되", "있", "없", "않", "같"}
# English function words: in an OR query they match nearly every English chunk and drown the content words.
_STOP_LATIN = frozenset(
    "a an the and or but if then of to in on at by for with from into onto as is are was were be been being am "
    "do does did doing have has had i me my mine you your yours he him his she her it its we us our they them "
    "their this that these those there here what which who whom whose how where when why can could should "
    "would will shall must not no nor so than too very just about over under again also only own same such "
    "some any each both all more most other few up down out off".split()
)
_MAX_TOKEN = 64

_PUNCT = "\"'`.,;:!?()[]{}<>«»“”‘’…·、。"
_IDENT = re.compile(r"^(?=.*[0-9_])(?=.*[A-Za-z0-9])[\w.\-/:#@+]{2,}$")
_JOSA_TAIL = re.compile(r"^([\x21-\x7e]*[A-Za-z][\x21-\x7e]*)[가-힣]+$")

_kiwi: Any = None
_init_lock = threading.Lock()
_use_lock = threading.Lock()


def _get_kiwi() -> Any:
    global _kiwi
    if _kiwi is None:
        with _init_lock:
            if _kiwi is None:
                from kiwipiepy import Kiwi

                _kiwi = Kiwi(load_multi_dict=False)
    return _kiwi


def warmup() -> None:
    """Load the Kiwi model now (~0.6s, ~400MB RSS) instead of on the first call."""
    morph("워밍업")


def is_identifier(token: str) -> bool:
    """Single token with digits or underscores: file names, versions, ids, numbers."""
    return bool(_IDENT.match(token)) and not token.isdigit()


def identifier_tokens(text: str) -> list[str]:
    """Whitespace tokens (stripped of surrounding punctuation) that look like identifiers."""
    out = []
    for raw in text.split():
        tok = raw.strip(_PUNCT)
        m = _JOSA_TAIL.match(tok)
        if m:
            tok = m.group(1).strip(_PUNCT)
        if len(tok) <= _MAX_TOKEN and is_identifier(tok):
            out.append(tok.lower())
    return out


def _keep(form: str, tag: str) -> str | None:
    if tag in _NOUNS:
        return form
    if tag in _STEMS:
        return None if form in _STOP_STEMS else form
    if tag == "SL":
        low = form.lower()
        # acronyms (IT, US, WHO, AS) are content words even when their lowercase form is a stopword
        return None if low in _STOP_LATIN and not (len(form) > 1 and form.isupper()) else low
    if tag in _WEB:
        return form.lstrip("#@").lower()
    return None


def _tag(t: Any) -> str:
    return str(t.tag).split("-", 1)[0]


def _tokenize(text: str) -> list[Any]:
    kiwi = _get_kiwi()
    with _use_lock:
        return kiwi.tokenize(text)


def morph(text: str) -> str:
    """Content morphemes (nouns, verb/adjective stems, roots, Latin, Hanja, numbers) + identifiers.

    A prefix glued to a noun (비공개, 불가능, 재발급) also yields the joined form next to the bare noun,
    so 비공개 still matches 공개 but scores the exact word higher."""
    text = unicodedata.normalize("NFC", text or "")
    if not text.strip():
        return ""
    try:
        tokens = _tokenize(text)
        parts = []
        for i, t in enumerate(tokens):
            tag = _tag(t)
            if tag == "XPN" and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if _tag(nxt) in _PREFIXED and nxt.start == t.start + t.len:
                    parts.append(t.form + nxt.form)
                continue
            parts.append(_keep(t.form, tag))
    except Exception:
        parts = [w.strip(_PUNCT).lower() for w in text.split()]
    out = [p for p in parts if p and len(p) <= _MAX_TOKEN]
    out.extend(identifier_tokens(text))
    return " ".join(out)


def word_stem(word: str) -> str:
    """`word` without its trailing particles and endings, as written: 회의를 -> 회의, 근로계약서를 -> 근로계약서,
    계약했다 -> 계약. The span runs from the word's start to the end of its last content morpheme, so
    prefixes and odd analyses inside a compound (온보딩자료) keep the surface text intact."""
    word = unicodedata.normalize("NFC", word or "").strip()
    if not word:
        return ""
    try:
        end = max((t.start + t.len for t in _tokenize(word) if _tag(t) in _CONTENT), default=0)
    except Exception:
        return word
    return word[:end] if end else word
