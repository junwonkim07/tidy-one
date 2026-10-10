"""Turn one local file into text blocks (with page numbers where the format has them) plus metadata.

Text formats are decoded directly (UTF-8/16/32 with or without BOM, CP949/EUC-KR fallback), PDF with
pypdf page by page, Office files with markitdown, HWPX from its section XML and binary HWP from its
OLE BodyText records (falling back to the PrvText preview). Everything else is metadata-only.
"""

from __future__ import annotations

import codecs
import io
import logging
import mimetypes
import os
import re
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable
from xml.etree import ElementTree as ET

from tidy_one.extract.scan import SF_DATALESS
from tidy_one.extract.sensitive import content_sensitivity, is_secret_path
from tidy_one.model import SENS_NONE, SENS_SECRET, Modality

MAX_TEXT_CHARS = 2_000_000
MAX_TEXT_BYTES = 16 * 1024 * 1024  # raw bytes read from a plain-text file
MAX_XML_BYTES = 64 * 1024 * 1024  # per decompressed HWPX/HWP part

_MIME = {
    ".md": "text/markdown", ".markdown": "text/markdown", ".mdx": "text/markdown",
    ".txt": "text/plain", ".text": "text/plain", ".rst": "text/x-rst", ".org": "text/x-org",
    ".tex": "text/x-tex", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".json": "application/json", ".jsonl": "application/x-ndjson", ".ndjson": "application/x-ndjson",
    ".yaml": "application/yaml", ".yml": "application/yaml", ".rtf": "application/rtf",
    ".html": "text/html", ".htm": "text/html", ".xhtml": "application/xhtml+xml",
    ".srt": "application/x-subrip", ".vtt": "text/vtt", ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".hwp": "application/x-hwp", ".hwpx": "application/hwp+zip",
    ".heic": "image/heic", ".heif": "image/heif", ".webp": "image/webp", ".avif": "image/avif",
    ".dng": "image/x-adobe-dng", ".cr2": "image/x-canon-cr2", ".cr3": "image/x-canon-cr3",
    ".nef": "image/x-nikon-nef", ".arw": "image/x-sony-arw", ".raf": "image/x-fuji-raf",
    ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".aac": "audio/aac",
    ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/opus", ".caf": "audio/x-caf",
    ".aiff": "audio/aiff", ".aif": "audio/aiff", ".amr": "audio/amr",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v", ".mkv": "video/x-matroska",
    ".webm": "video/webm", ".avi": "video/x-msvideo", ".3gp": "video/3gpp", ".mts": "video/mp2t",
}

_PLAIN = {".txt", ".text", ".rst", ".org", ".tex", ".csv", ".tsv", ".json", ".jsonl", ".ndjson",
          ".yaml", ".yml", ".srt", ".vtt"}
_MARKDOWN = {".md", ".markdown", ".mdx"}
_HTML = {".html", ".htm", ".xhtml"}
_OFFICE = {".docx", ".pptx", ".xlsx", ".xlsm"}

log = logging.getLogger(__name__)

_SURROGATE = re.compile("[\ud800-\udfff]")


@dataclass
class TextBlock:
    text: str
    page: int | None = None  # 1-based page (PDF) or slide (PPTX); None when the format has no pages


@dataclass
class Extracted:
    title: str
    mime: str | None
    modality: Modality
    text_blocks: list[TextBlock] = field(default_factory=list)
    sensitivity: int = SENS_NONE
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.text_blocks)


class _Sink:
    """Collects blocks up to the character budget and records truncation."""

    def __init__(self, ex: Extracted, max_chars: int):
        self.ex = ex
        self.left = max_chars

    @property
    def full(self) -> bool:
        return self.left <= 0

    def add(self, text: str, page: int | None = None) -> None:
        text = clean_text(text)
        if not text.strip():
            return
        if self.full:
            self.ex.extra["truncated"] = True
            return
        if len(text) > self.left:
            text = text[: self.left]
            self.ex.extra["truncated"] = True
        self.left -= len(text)
        self.ex.text_blocks.append(TextBlock(text, page))


def guess_mime(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    return _MIME.get(ext) or mimetypes.guess_type(path, strict=False)[0]


def modality_for(mime: str | None) -> Modality:
    top = (mime or "").split("/", 1)[0]
    return top if top in ("image", "video", "audio") else "text"  # type: ignore[return-value]


def fix_surrogates(text: str) -> str:
    """Join UTF-16 surrogate pairs into their character and replace lone halves with U+FFFD.

    RTF writes characters beyond the BMP (emoji, CJK Ext-B) as two \\uN halves, and pypdf decodes some
    ToUnicode maps with `surrogatepass`; a lone surrogate cannot be encoded, so hashing the text fails."""
    if not _SURROGATE.search(text):
        return text
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def clean_text(text: str) -> str:
    """NFC, unix newlines, no NULs/BOMs, no trailing spaces, at most one blank line in a row."""
    text = fix_surrogates(text)
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = text.replace("\x00", "").replace("\ufeff", "")
    text = re.sub(r"[ \t\u3000]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def _decode(data: bytes, enc: str, final: bool) -> str:
    return codecs.getincrementaldecoder(enc)("strict").decode(data, final=final)


def _hangul_ratio(text: str) -> float:
    non_ascii = [c for c in text if ord(c) > 127]
    if not non_ascii:
        return 1.0
    return sum(1 for c in non_ascii if "\uac00" <= c <= "\ud7a3" or "\u3131" <= c <= "\u318e") / len(non_ascii)


def decode_bytes(data: bytes, *, partial: bool = False) -> tuple[str, str]:
    """Decode text bytes; returns (text, encoding). `partial` tolerates a cut multi-byte tail."""
    final = not partial
    for bom, enc in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF32_LE, "utf-32"),
                     (codecs.BOM_UTF32_BE, "utf-32"), (codecs.BOM_UTF16_LE, "utf-16"),
                     (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            return codecs.getincrementaldecoder(enc)("replace").decode(data, final=final), enc
    sample = data[:8192]
    if b"\x00" in sample and len(sample) >= 4:
        even = sample[0::2].count(0) / (len(sample) / 2)
        odd = sample[1::2].count(0) / (len(sample) / 2)
        for enc, ok in (("utf-16-le", odd > 0.05 and even < odd / 4), ("utf-16-be", even > 0.05 and odd < even / 4)):
            if ok:
                try:
                    return _decode(data, enc, final), enc
                except UnicodeDecodeError:
                    pass
    try:
        return _decode(data, "utf-8", final), "utf-8"
    except UnicodeDecodeError:
        pass
    korean = None
    try:
        korean = _decode(data, "cp949", final)
        if _hangul_ratio(korean[:20000]) >= 0.5:
            return korean, "cp949"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data[:1_000_000]).best()
        if best is not None and best.encoding:
            return data.decode(best.encoding, errors="replace"), best.encoding
    except Exception:
        pass
    if korean is not None:
        return korean, "cp949"
    return data.decode("utf-8", errors="replace"), "utf-8"


def _read_text(path: str, ex: Extracted) -> str:
    with open(path, "rb") as f:
        data = f.read(MAX_TEXT_BYTES + 1)
    partial = len(data) > MAX_TEXT_BYTES
    if partial:
        data = data[:MAX_TEXT_BYTES]
        ex.extra["truncated"] = True
    text, enc = decode_bytes(data, partial=partial)
    ex.extra["encoding"] = enc
    return text


def _plain(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    sink.add(_read_text(path, ex))


_FRONT = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
_FRONT_TITLE = re.compile(r"^title:[ \t]*[\"']?(.+?)[\"']?[ \t]*$", re.M)
_ATX = re.compile(r"^#{1,2}\s+(.+?)\s*#*\s*$", re.M)


def _markdown(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    text = clean_text(_read_text(path, ex))
    front = _FRONT.match(text)
    m = (front and _FRONT_TITLE.search(front.group(1))) or _ATX.search(text[front.end() if front else 0 :][:5000])
    if m:
        title = re.sub(r"[*_`]+", "", m.group(1)).strip()
        if title:
            ex.title = title
    sink.add(text)


def _html(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    raw = _read_text(path, ex)
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        if soup.title and soup.title.string and soup.title.string.strip():
            ex.title = " ".join(soup.title.string.split())
        for tag in soup(["script", "style", "noscript", "template", "svg", "head"]):
            tag.decompose()
        text = soup.get_text("\n")
    except ImportError:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        if m and m.group(1).strip():
            ex.title = " ".join(m.group(1).split())
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", "\n", text)
    sink.add(re.sub(r"\n\s*\n+", "\n\n", "\n".join(line.strip() for line in text.splitlines())))


_RTF_TOKEN = re.compile(
    r"\\([a-z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|([^\\{}\r\n]+)", re.I
)
_RTF_SKIP = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "fldinst", "themedata",
    "colorschememapping", "latentstyles", "datastore", "xmlnstbl", "listtable", "listoverridetable",
    "rsidtbl", "generator", "header", "headerl", "headerr", "headerf", "footer", "footerl", "footerr",
    "footerf", "filetbl", "revtbl", "expandedcolortbl", "nonshppict", "mmathpr", "pgdsctbl",
}
_RTF_CHARS = {"par": "\n", "line": "\n", "sect": "\n\n", "page": "\n\n", "row": "\n", "cell": "\t",
              "tab": "\t", "emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022",
              "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c", "rdblquote": "\u201d"}


def rtf_to_text(rtf: str) -> tuple[str, str | None]:
    """Plain text and \\info title from RTF; handles \\uN escapes and \\'hh bytes in the document code page."""
    out: list[str] = []
    title: list[str] = []
    hexbuf = bytearray()
    codepage = "cp1252"
    stack: list[tuple[bool, int, bool]] = []
    skip, uc, in_title, pending = False, 1, False, 0

    def emit(s: str) -> None:
        if in_title:
            title.append(s)
        elif not skip:
            out.append(s)

    def flush() -> None:
        if hexbuf:
            emit(bytes(hexbuf).decode(codepage, errors="replace"))
            hexbuf.clear()

    for m in _RTF_TOKEN.finditer(rtf):
        word, arg, hexc, sym, brace, text = m.groups()
        if hexc is not None:
            if pending:
                pending -= 1
            else:
                hexbuf.append(int(hexc, 16))
            continue
        flush()
        if text is not None:
            drop = min(pending, len(text))
            pending -= drop
            if text[drop:]:
                emit(text[drop:])
        elif word is not None:
            w = word.lower()
            if w == "u" and arg:
                emit(chr(int(arg) % 65536))
                pending = uc
            elif w == "uc" and arg:
                uc = int(arg)
            elif w == "ansicpg" and arg:
                try:
                    codepage = codecs.lookup(f"cp{arg}").name
                except LookupError:
                    pass
            elif w == "title":
                in_title, skip = True, True
            elif w in _RTF_SKIP:
                skip = True
            elif w in _RTF_CHARS:
                emit(_RTF_CHARS[w])
        elif brace == "{":
            stack.append((skip, uc, in_title))
            pending = 0
        elif brace == "}":
            if stack:
                skip, uc, in_title = stack.pop()
            pending = 0
        elif sym is not None:
            pending = 0
            if sym == "*":
                skip = True
            elif sym in "\\{}":
                emit(sym)
            elif sym == "~":
                emit("\u00a0")
            elif sym == "_":
                emit("-")
    flush()
    t = fix_surrogates(" ".join("".join(title).split()))
    return fix_surrogates("".join(out)), (t or None)


def _rtf(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    text, title = rtf_to_text(_read_text(path, ex))
    if title:
        ex.title = title
    sink.add(text)


def _clean_meta_title(t: Any) -> str | None:
    if not t:
        return None
    t = " ".join(str(t).replace("\x00", "").split())
    t = re.sub(r"^Microsoft (?:Word|PowerPoint|Excel) - ", "", t)
    if not t or t.lower() in {"untitled", "제목 없음", "제목없음", "슬라이드 1", "powerpoint presentation"}:
        return None
    return unicodedata.normalize("NFC", t)


def _pdf(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            ok = bool(reader.decrypt(""))
        except Exception:
            ok = False
        if not ok:
            ex.extra["encrypted"] = True
            return
    try:
        title = _clean_meta_title(reader.metadata.title if reader.metadata else None)
    except Exception:
        title = None
    if title:
        ex.title = title
    ex.extra["pages"] = len(reader.pages)
    empty: list[int] = []
    chars = done = 0
    for i, page in enumerate(reader.pages, 1):
        if sink.full:
            ex.extra["truncated"] = True
            break
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        visible = len("".join(text.split()))
        chars += visible
        done += 1
        if visible == 0:
            empty.append(i)
        sink.add(text, i)
    if done and (chars < 20 * done or len(empty) * 2 > done):
        ex.extra["needs_ocr"] = True
    if empty and len(empty) < done:
        ex.extra["pages_without_text"] = empty[:500]


_SLIDE = re.compile(r"<!-- Slide number: (\d+) -->")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _ooxml_title(path: str) -> str | None:
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("docProps/core.xml"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError, OSError):
        return None
    el = root.find("{http://purl.org/dc/elements/1.1/}title")
    return _clean_meta_title(el.text) if el is not None else None


def _office(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    from markitdown import StreamInfo
    from markitdown.converters import DocxConverter, PptxConverter, XlsxConverter

    conv = {".docx": DocxConverter, ".pptx": PptxConverter, ".xlsx": XlsxConverter, ".xlsm": XlsxConverter}[ext]()
    with open(path, "rb") as f:
        res = conv.convert(f, StreamInfo(extension=".xlsx" if ext == ".xlsm" else ext,
                                         filename=os.path.basename(path), local_path=path))
    title = _ooxml_title(path) or _clean_meta_title(res.title)
    if title:
        ex.title = title
    md = _MD_IMAGE.sub(lambda m: m.group(1), res.markdown or "")
    if ext == ".pptx":
        parts = _SLIDE.split(md)
        ex.extra["slides"] = (len(parts) - 1) // 2
        for k in range(1, len(parts) - 1, 2):
            sink.add(_HTML_COMMENT.sub("", parts[k + 1]), int(parts[k]))
        return
    if ext in (".xlsx", ".xlsm"):
        md = re.sub(r"(?<=\|) NaN(?= \|)", " ", md)
        sheets = re.split(r"(?m)^## (.+)\n", md)
        if len(sheets) > 1:
            ex.extra["sheets"] = sheets[1::2][:200]
            for k in range(1, len(sheets) - 1, 2):
                sink.add(f"## {sheets[k]}\n{sheets[k + 1]}")
            return
    sink.add(_HTML_COMMENT.sub("", md))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def hwpx_section_text(xml: bytes) -> str:
    """Paragraph text of one HWPX `Contents/sectionN.xml` (OWPML `hp:p`/`hp:t`)."""
    out: list[str] = []
    for _, el in ET.iterparse(io.BytesIO(xml), events=("end",)):
        name = _local(el.tag)
        if name == "t":
            out.append(el.text or "")
            for child in el:
                cn = _local(child.tag)
                out.append("\t" if cn == "tab" else "\n" if cn == "lineBreak" else "")
                out.append(child.tail or "")
        elif name == "p":
            out.append("\n")
            el.clear()
    return "".join(out)


def _hwpx(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    def num(n: str) -> int:
        return int(re.sub(r"\D", "", n) or 0)

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "Contents/content.hpf" in names:
            try:
                root = ET.fromstring(z.read("Contents/content.hpf"))
                for el in root.iter():
                    if _local(el.tag) == "title" and el.text and el.text.strip():
                        ex.title = unicodedata.normalize("NFC", el.text.strip())
                        break
            except ET.ParseError:
                pass
        sections = sorted((n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n)), key=num)
        for n in sections:
            if sink.full:
                ex.extra["truncated"] = True
                break
            if z.getinfo(n).file_size > MAX_XML_BYTES:
                ex.extra["truncated"] = True
                continue
            sink.add(hwpx_section_text(z.read(n)))
        if not ex.text_blocks and "Preview/PrvText.txt" in names:
            sink.add(decode_bytes(z.read("Preview/PrvText.txt")[:MAX_TEXT_BYTES])[0])
            ex.extra["preview_only"] = True


HWPTAG_PARA_TEXT = 67  # HWPTAG_BEGIN (16) + 51
_HWP_CHAR_CTRLS = {0, 10, 13, *range(24, 32)}  # one WCHAR; every other control < 32 spans 8 WCHARs


def hwp_para_text(rec: bytes) -> str:
    """Text of one HWPTAG_PARA_TEXT record (UTF-16LE with inline/extended control blocks)."""
    buf = bytearray()
    i, n = 0, len(rec) // 2
    while i < n:
        c = rec[2 * i] | (rec[2 * i + 1] << 8)
        if c >= 32:
            buf += rec[2 * i : 2 * i + 2]
            i += 1
        elif c in _HWP_CHAR_CTRLS:
            if c == 10:
                buf += b"\n\x00"
            i += 1
        else:
            if c == 9:
                buf += b"\t\x00"
            i += 8
    return buf.decode("utf-16-le", errors="replace")


def hwp_records_text(data: bytes) -> str:
    """Concatenated paragraph text of a decompressed HWP BodyText section stream."""
    out: list[str] = []
    pos, n = 0, len(data)
    while pos + 4 <= n:
        hdr = int.from_bytes(data[pos : pos + 4], "little")
        pos += 4
        tag, size = hdr & 0x3FF, (hdr >> 20) & 0xFFF
        if size == 0xFFF:
            if pos + 4 > n:
                break
            size = int.from_bytes(data[pos : pos + 4], "little")
            pos += 4
        if tag == HWPTAG_PARA_TEXT:
            out.append(hwp_para_text(data[pos : pos + size]))
        pos += size
    return "\n".join(out)


def _hwp(path: str, ext: str, ex: Extracted, sink: _Sink) -> None:
    import olefile

    if not olefile.isOleFile(path):
        ex.extra["error"] = "not_ole"
        return
    with olefile.OleFileIO(path) as ole:
        header = ole.openstream("FileHeader").read(256) if ole.exists("FileHeader") else b""
        if not header.startswith(b"HWP Document File"):
            ex.extra["error"] = "not_hwp"
            return
        props = int.from_bytes(header[36:40], "little")
        compressed, encrypted, distribution = props & 1, props & 2, props & 4
        try:
            title = ole.getproperties("\x05HwpSummaryInformation").get(2)
            title = _clean_meta_title(title.decode("utf-16-le", "ignore") if isinstance(title, bytes) else title)
            if title:
                ex.title = title
        except Exception:
            pass
        if not (encrypted or distribution):
            sections = sorted(
                (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
                key=lambda e: int(re.sub(r"\D", "", e[1]) or 0),
            )
            for entry in sections:
                if sink.full:
                    ex.extra["truncated"] = True
                    break
                data = ole.openstream(entry).read()
                if compressed:
                    data = zlib.decompressobj(-15).decompress(data, MAX_XML_BYTES)
                sink.add(hwp_records_text(data))
        else:
            ex.extra["hwp_protected"] = True
        if not ex.text_blocks and ole.exists("PrvText"):
            prv = ole.openstream("PrvText").read().decode("utf-16-le", errors="replace")
            sink.add(prv.rstrip("\x00"))
            ex.extra["preview_only"] = True


_HANDLERS: dict[str, Callable[[str, str, Extracted, _Sink], None]] = {
    **{e: _plain for e in _PLAIN},
    **{e: _markdown for e in _MARKDOWN},
    **{e: _html for e in _HTML},
    **{e: _office for e in _OFFICE},
    ".rtf": _rtf,
    ".pdf": _pdf,
    ".hwpx": _hwpx,
    ".hwp": _hwp,
}


def extract_file(path: str, *, max_chars: int = MAX_TEXT_CHARS) -> Extracted:
    """Extract text blocks and metadata from a local file.

    Secret-looking paths are never opened and secret-looking content is dropped; both come back
    with `SENS_SECRET` and no text, and the caller must skip the file entirely.
    """
    path = os.path.expanduser(path)
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    mime = guess_mime(path)
    ex = Extracted(title=unicodedata.normalize("NFC", stem or name), mime=mime, modality=modality_for(mime))
    if is_secret_path(path):
        ex.sensitivity = SENS_SECRET
        ex.extra["skipped"] = "secret_path"
        return ex
    handler = _HANDLERS.get(ext)
    if handler is None:
        return ex
    ex.extra["extractor"] = handler.__name__.lstrip("_")
    try:
        if getattr(os.stat(path), "st_flags", 0) & SF_DATALESS:  # reading would download it from iCloud
            ex.extra["dataless"] = True
            return ex
        handler(path, ext, ex, _Sink(ex, max_chars))
    except Exception as e:  # a broken file must never stop a scan
        log.debug("extract failed for %s: %s", path, type(e).__name__)
        ex.text_blocks = []
        ex.extra["error"] = type(e).__name__
    ex.title = fix_surrogates(ex.title)  # metadata titles (PDF, RTF \info) can carry lone surrogates too
    if ex.text_blocks:
        flags = content_sensitivity(ex.text)
        if flags & SENS_SECRET:
            ex.text_blocks = []
            ex.extra["skipped"] = "secret_content"
        ex.sensitivity |= flags
    return ex
