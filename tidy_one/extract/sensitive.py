"""Sensitivity checks: secret-looking paths and content (credentials, Korean ID numbers, cards, passports).

`SENS_SECRET` means the file never leaves the device and is not extracted at all.
`SENS_ID` marks documents that carry personal identity numbers.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import unicodedata

from tidy_one.model import SENS_ID, SENS_NONE, SENS_SECRET

# Bump when detection code changes in a way the pattern fingerprint below cannot see (e.g. valid_rrn).
RULES_REVISION = 2

_SECRET_SUFFIXES = (
    ".pem", ".key", ".kdbx", ".p12", ".pfx", ".p8", ".ppk", ".jks", ".keystore", ".ovpn",
)
_SECRET_PREFIXES = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
_SECRET_WORDS = (
    "password", "passwd", "secret", "credential", "token", "service-account", "service_account",
    "비밀번호", "암호",
)
_SECRET_NAMES = {".netrc", ".pgpass", ".npmrc", ".pypirc", ".git-credentials", "authorized_keys", "known_hosts"}
_SECRET_DIRS = {".ssh", ".gnupg", ".aws", ".password-store", "keychains"}
# key files named without a .key/.pem suffix: "deploy_key", "artcraft-host-key", "ssh_host_ed25519_key", "api-keys.txt"
_KEY_NAME = re.compile(
    r"(?:^|[-_. ])(?:host|private|priv|ssh|deploy|signing|server|client|master|api|access)[-_ ]?keys?"
    r"(?:\.(?:txt|md|bak|old|json|csv))?$|^ssh_host_\w+_key$|(?:^|[-_.])privkey"
)

# API token formats, matched only when not glued to a preceding word character
_TOKENS = [
    r"(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}(?![A-Za-z0-9])",  # AWS access key id
    r"AIza[0-9A-Za-z_\-]{35}(?![\w-])",  # Google API key
    r"GOCSPX-[A-Za-z0-9_\-]{24,}",  # Google OAuth client secret
    r"ya29\.[0-9A-Za-z_\-]{30,}",  # Google OAuth access token
    r"sk-ant-(?:api|admin|oat|ort)\d{2}-[A-Za-z0-9_\-]{20,}",  # Anthropic
    r"sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}",  # OpenAI project/service keys
    r"sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}(?![\w-])",  # OpenAI legacy
    r"sk-[A-Za-z0-9]{40,}(?![\w-])",
    r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}",  # GitHub
    r"github_pat_[A-Za-z0-9_]{22,}",
    r"xox[abposr]-[A-Za-z0-9-]{10,}",  # Slack
    r"xapp-\d-[A-Za-z0-9-]{10,}",
    r"[sr]k_live_[A-Za-z0-9]{20,}",  # Stripe
    r"(?:ntn_[A-Za-z0-9]{40,}|secret_[A-Za-z0-9]{43})(?![\w-])",  # Notion
    r"hf_[A-Za-z0-9]{34,}(?![\w-])",  # Hugging Face
    r"glpat-[A-Za-z0-9_\-]{20,}",  # GitLab personal access token
    r"npm_[A-Za-z0-9]{36,}(?![\w-])",  # npm
    r"SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{20,}",  # SendGrid
    r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",  # JWT (header.payload.signature)
    r"\d{8,10}:[A-Za-z0-9_\-]{35}(?![\w-])",  # Telegram bot token
]
# "비밀번호: Hunter2!@#", "pw = qwer1234": a credential label, then a value of 4+ non-space, non-Hangul
# characters with a digit or symbol in it (so "Password: must be 8 characters" is not a secret).
_PASSWORD_LINE = (
    r"(?i)(?<![A-Za-z])(?:password|passwd|passcode|pw|비밀번호|비번|패스워드|암호)\s{0,3}[:=：]\s{0,3}[\"']?"
    r"(?=[^\s가-힣]*[0-9!@#$%^&*()_+\-=?~.,;/\\|<>\[\]{}])(?!\*{3,}(?:\s|$))[^\s가-힣]{4,}"
)
_SECRET_CONTENT = [
    re.compile(r"(?<![\w-])(?:" + "|".join(_TOKENS) + ")"),
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40}"),
    re.compile(r"\"type\"\s*:\s*\"service_account\"[\s\S]{0,2000}\"private_key\"|"
               r"\"private_key\"\s*:\s*\"-----BEGIN"),
    re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{16,}"),
    re.compile(_PASSWORD_LINE),
    # scheme://user:password@host, unless the password is a placeholder such as "password" or "<pass>"
    re.compile(
        r"(?i)\b[a-z][a-z0-9+.\-]{1,20}://[^\s/:@]{1,128}:"
        r"(?!(?:password|passwd|pass|pwd|secret|x{3,}|\*+|<[^>@/\s]*>|\$\{[^}@/\s]*\}|\{[^}@/\s]*\})@)"
        r"[^\s/@]{1,256}@[^\s/@]"
    ),
]

_RRN = re.compile(r"(?<![\d-])(\d{2})(\d{2})(\d{2})\s?-\s?([1-4])(\d{6})(?![\d-])")
# not inside longer alphanumeric runs (hex digests, base64 ids); Hangul right before the number is fine
_CARD = re.compile(
    r"(?<![A-Za-z0-9-])(?:\d{4}([- ])\d{4}\1\d{4}\1\d{1,7}|\d{4}([- ])\d{6}\2\d{5}|\d{13,19})(?![A-Za-z0-9-])"
)
# Whitespace runs are bounded: three adjacent unbounded `\s*` backtrack cubically on a long blank run.
_PASSPORT = re.compile(
    r"(?:여권(?:\s{0,3}번호)?|(?i:passport)(?:\s{0,3}(?:(?i:no|number|num)\.?|#))?)\s{0,3}[:：]?\s{0,3}"
    r"([A-Z]{1,2}\d{7,8}|[MSRODG]\d{3}[A-Z]\d{4})(?![A-Za-z0-9])"
)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def is_secret_path(path: str) -> bool:
    """True for files that look like credentials by name or location; such files are never read."""
    p = _nfc(os.path.expanduser(path))
    parts = [c.lower() for c in p.split(os.sep) if c]
    if not parts:
        return False
    name = parts[-1]
    if any(d in _SECRET_DIRS for d in parts[:-1]):
        return True
    if name in _SECRET_NAMES or name.startswith(_SECRET_PREFIXES) or name.endswith(_SECRET_SUFFIXES):
        return True
    if ".keychain" in name or _KEY_NAME.search(name):
        return True
    return any(w in name for w in _SECRET_WORDS)


def is_secret_dirname(name: str) -> bool:
    """Directories never walked into: credential stores and folders named like secrets (the same words
    that make a file name secret, e.g. 암호, tokens, "API Keys")."""
    n = _nfc(name).lower()
    return n in _SECRET_DIRS or any(w in n for w in _SECRET_WORDS) or bool(_KEY_NAME.search(n))


def valid_rrn(s: str) -> bool:
    """Korean resident registration number check: plausible birth date and, before Oct 2020, checksum."""
    digits = re.sub(r"\D", "", s)
    if len(digits) != 13:
        return False
    yy, mm, dd, g = int(digits[:2]), int(digits[2:4]), int(digits[4:6]), int(digits[6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31) or g not in (1, 2, 3, 4):
        return False
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    check = (11 - sum(int(d) * w for d, w in zip(digits, weights)) % 11) % 10
    if check == int(digits[12]):
        return True
    # numbers issued from October 2020 have random trailing digits (no checksum)
    year = (2000 if g in (3, 4) else 1900) + yy
    return g in (3, 4) and (2020, 10) <= (year, mm) <= (_dt.date.today().year, 12)


def luhn_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _card_brand_ok(digits: str) -> bool:
    n = len(digits)
    two, four = int(digits[:2]), int(digits[:4])
    if digits[0] == "4":
        return n in (13, 16, 19)
    if 51 <= two <= 55 or 2221 <= four <= 2720:
        return n == 16
    if two in (34, 37):
        return n == 15
    if digits.startswith(("6011", "65", "62")) or 644 <= int(digits[:3]) <= 649:
        return 16 <= n <= 19
    if 3528 <= four <= 3589:
        return 16 <= n <= 19
    if 300 <= int(digits[:3]) <= 305 or two in (36, 38, 39):
        return 14 <= n <= 19
    return False


def find_card_numbers(text: str) -> list[str]:
    out = []
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _card_brand_ok(digits) and luhn_ok(digits):
            out.append(digits)
    return out


def find_rrns(text: str) -> list[str]:
    return [m.group(0) for m in _RRN.finditer(text) if valid_rrn(m.group(0))]


def find_passports(text: str) -> list[str]:
    return [m.group(1) for m in _PASSPORT.finditer(text)]


def has_secret_content(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_CONTENT)


def content_sensitivity(text: str) -> int:
    """Sensitivity flags for extracted text: SENS_SECRET for credentials, SENS_ID for ID/card/passport numbers."""
    flags = SENS_NONE
    if has_secret_content(text):
        flags |= SENS_SECRET
    if find_rrns(text) or find_card_numbers(text) or find_passports(text):
        flags |= SENS_ID
    return flags


def _fingerprint() -> str:
    parts = [str(RULES_REVISION), *_TOKENS, *(p.pattern for p in _SECRET_CONTENT), _RRN.pattern, _CARD.pattern,
             _PASSPORT.pattern]
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:12]


# Changes whenever content detection changes; the agent re-checks files indexed under another version.
RULES_VERSION = _fingerprint()
