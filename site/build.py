#!/usr/bin/env python3
"""Build the tidy-one landing page.

    python3 build.py

Renders src/template.html with the copy in i18n/{ko,en,zh}.json into

    dist/index.html      Korean (default)
    dist/en/index.html   English
    dist/zh/index.html   Simplified Chinese

and copies src/assets/ to dist/assets/. It also draws the pixel art
(inline SVG sprites, favicon, Open Graph image, touch icon) from the
bitmaps below, so the art stays in the Sage palette and needs no tools.

Standard library only (Python 3.9+). SITE_BASE_URL is the absolute base used
for canonical, hreflang, og:url, og:image, the sitemap and robots.txt. It
defaults to the GitHub Pages project URL; set it for another host, e.g.

    SITE_BASE_URL=https://tidy-one.example python3 build.py

(SITE_URL is still read as an older alias.) Links inside the pages (assets,
language switcher, home) are relative, so dist/ works at / on a local server
and under /tidy-one/ on GitHub Pages without rebuilding.
"""

import hashlib
import html
import json
import os
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
I18N = ROOT / "i18n"
DIST = ROOT / "dist"

DEFAULT_BASE_URL = "https://junwonkim07.github.io/tidy-one"
SITE_BASE_URL = (
    os.environ.get("SITE_BASE_URL") or os.environ.get("SITE_URL") or DEFAULT_BASE_URL
).strip().rstrip("/")
if not re.match(r"^https?://[^/\s]+(/[^\s]*)?$", SITE_BASE_URL):
    sys.exit("SITE_BASE_URL must be an absolute http(s) URL, got %r" % SITE_BASE_URL)
REPO_URL = "https://github.com/junwonkim07/tidy-one"

# code, output dir (relative to dist), <html lang>, hreflang
LANGS = [
    ("ko", "", "ko", "ko"),
    ("en", "en/", "en", "en"),
    ("zh", "zh/", "zh-Hans", "zh-Hans"),
]
SWITCH_LABEL = {"ko": "KO", "en": "EN", "zh": "中文"}

# ---------------------------------------------------------------- palette
PALETTE = {
    "M": "#CAD2C5",  # mist
    "G": "#84A98C",  # sage
    "D": "#52796F",  # deep sage
    "P": "#354F52",  # pine
    "S": "#2F3E46",  # slate
    "W": "#F8F9F7",  # paper
}
# On the dark (slate) band the same bitmaps are re-inked.
ON_DARK = {"S": "#CAD2C5", "M": "#354F52", "G": "#84A98C", "D": "#84A98C", "P": "#52796F", "W": "#2F3E46"}

# ---------------------------------------------------------------- bitmaps
# '.' is transparent; letters map through PALETTE.
SPRITES = {
    "mark": [
        ".........GGG",
        "SSS.SSS..GGG",
        "SSS.SSS..GGG",
        "SSS.SSS.....",
        "............",
        "SSS.PPP.PPP.",
        "SSS.PPP.PPP.",
        "SSS.PPP.PPP.",
        "............",
        "PPP.PPP.DDD.",
        "PPP.PPP.DDD.",
        "PPP.PPP.DDD.",
    ],
    # feature icons, 12 x 12
    "devices": [
        "............",
        "SSSSSSSSS...",
        "SMMMMMMMS...",
        "SMGGGMMMS...",
        "SMMMMMMMSSSS",
        "SMDDDDMMSMMS",
        "SMMMMMMMSGMS",
        "SSSSSSSSSMMS",
        "...SSS..SDDS",
        ".SSSSSSSSMMS",
        "........SSSS",
        "............",
    ],
    "formats": [
        "....SSSSSSS.",
        "....SMMMMMS.",
        "..SSSSSSSMS.",
        "..SMMMMMSMS.",
        "SSSSSSSMSMS.",
        "SMMMMMSMSSS.",
        "SMGGGMSMS...",
        "SMMMMMSSS...",
        "SMDDDMS.....",
        "SMMMMMS.....",
        "SSSSSSS.....",
        "............",
    ],
    # magnifier: a solid slate ring and handle, so it carries the same weight as the other icons
    "search": [
        "..SSSS......",
        ".SSMMSS.....",
        "SSMGGMSS....",
        "SMGMMMMS....",
        "SMMMMMMS....",
        "SSMMMMSS....",
        ".SSMMSS.....",
        "..SSSSSS....",
        "......SSS...",
        ".......SSS..",
        "........SSS.",
        ".........SS.",
    ],
    # two agent heads wired to one index (the how-it-works motif, small)
    "agents": [
        "SSSSS..SSSSS",
        "SDMDS..SDGDS",
        "SMMMS..SGGGS",
        "SMDMS..SGDGS",
        "SSSSS..SSSSS",
        "..G......G..",
        "..G......G..",
        "...GG..GG...",
        "....SSSS....",
        "....SDDS....",
        "....SDDS....",
        "....SSSS....",
    ],
    # privacy icons, 12 x 12 (drawn on the dark band)
    "lock": [
        "....SSSS....",
        "...S....S...",
        "..S......S..",
        "..S......S..",
        ".SSSSSSSSSS.",
        ".SGGGGGGGGS.",
        ".SGGGMMGGGS.",
        ".SGGGMMGGGS.",
        ".SGGGGMGGGS.",
        ".SGGGGGGGGS.",
        ".SSSSSSSSSS.",
        "............",
    ],
    "key": [
        "............",
        "............",
        "............",
        "..SSSS......",
        ".S....S.....",
        ".S.GG.SSSSSS",
        ".S.GG.S..S.S",
        ".S....S..S.S",
        "..SSSS......",
        "............",
        "............",
        "............",
    ],
    "code": [
        "............",
        "........GG..",
        "...S....G...",
        "..S....GG.S.",
        ".S.....G...S",
        "S.....GG....",
        ".S....G....S",
        "..S..GG...S.",
        "...S.G......",
        ".....G......",
        "............",
        "............",
    ],
    # roadmap marks, 9 x 9
    "done": [
        "GGGGGGGGG",
        "GGGGGGGGG",
        "GGGGGGSSG",
        "GGGGGSSGG",
        "GSSGSSGGG",
        "GGSSSGGGG",
        "GGGSGGGGG",
        "GGGGGGGGG",
        "GGGGGGGGG",
    ],
    "next": [
        "D.D.D.D.D",
        ".........",
        "D.......D",
        ".........",
        "D.......D",
        ".........",
        "D.......D",
        ".........",
        "D.D.D.D.D",
    ],
    # how-it-works nodes, 28 x 20
    "node_device": [
        "............................",
        "............................",
        "............................",
        "............................",
        ".SSSSSSSSSSSSSSSSSS.........",
        ".SMMMMMMMMMMMMMMMMS.........",
        ".SMGGGGGMMMMMMMMMMS..SSSSSSS",
        ".SMMMMMMMMMMMMMMMMS..SMMMMMS",
        ".SMDDDDDDDDDMMMMMMS..SMGGGMS",
        ".SMMMMMMMMMMMMMMMMS..SMMMMMS",
        ".SMDDDDDDMMMMMMMMMS..SMDDDMS",
        ".SMMMMMMMMMMMMMMMMS..SMMMMMS",
        ".SMDDDDDDDDDDMMMMMS..SMDDMMS",
        ".SSSSSSSSSSSSSSSSSS..SMMMMMS",
        "SPPPPPPPPPPPPPPPPPPS.SMMMMMS",
        "SSSSSSSSSSSSSSSSSSSS.SSSPSSS",
        "....................SSSSSSSS",
        "............................",
        "............................",
        "............................",
    ],
    "node_server": [
        "................",
        "................",
        "................",
        "SSSSSSSSSSSSSSSS",
        "SMMMMMMMMMMMMMMS",
        "SMGGGGGGMMMMDMMS",
        "SMMMMMMMMMMMMMMS",
        "SSSSSSSSSSSSSSSS",
        "SMMMMMMMMMMMMMMS",
        "SMGGGGGGMMMMDMMS",
        "SMMMMMMMMMMMMMMS",
        "SSSSSSSSSSSSSSSS",
        "SMMMMMMMMMMMMMMS",
        "SMGGGGGGMMMMGMMS",
        "SMMMMMMMMMMMMMMS",
        "SSSSSSSSSSSSSSSS",
        ".SS..........SS.",
        "................",
        "................",
        "................",
    ],
    "node_agents": [
        "....................",
        "...GG..........GG...",
        "...SS..........SS...",
        "SSSSSSSS....SSSSSSSS",
        "SMMMMMMS....SGGGGGGS",
        "SMSMMSMS....SGSGGSGS",
        "SMMMMMMS....SGGGGGGS",
        "SMSMMSMS....SGSGGSGS",
        "SMMSSMMS....SGGSSGGS",
        "SSSSSSSS....SSSSSSSS",
        ".........GG.........",
        ".........SS.........",
        "......SSSSSSSS......",
        "......SMMMMMMS......",
        "......SMSMMSMS......",
        "......SMMMMMMS......",
        "......SMSMMSMS......",
        "......SMMSSMMS......",
        "......SSSSSSSS......",
        "....................",
    ],
}

# 5 x 9 pixel font for the Open Graph wordmark (rows 0-1 ascender, 7-8 descender)
GLYPHS = {
    "t": [".#...", ".#...", "####.", ".#...", ".#...", ".#...", "..##.", ".....", "....."],
    "i": ["..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###.", ".....", "....."],
    "d": ["....#", "....#", ".####", "#...#", "#...#", "#...#", ".####", ".....", "....."],
    "y": [".....", ".....", "#...#", "#...#", "#...#", "#...#", ".####", "....#", ".###."],
    "-": [".....", ".....", ".....", ".....", ".###.", ".....", ".....", ".....", "....."],
    "o": [".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###.", ".....", "....."],
    "n": [".....", ".....", "####.", "#...#", "#...#", "#...#", "#...#", ".....", "....."],
    "e": [".....", ".....", ".###.", "#...#", "#####", "#....", ".###.", ".....", "....."],
}


def sprite_paths(rows, palette):
    """Merge each colour's horizontal runs into one compact SVG path."""
    runs = {}
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            ch = row[x]
            if ch == ".":
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == ch:
                x += 1
            runs.setdefault(ch, []).append("M%d %dh%dv1h-%dz" % (start, y, x - start, x - start))
    out = []
    for ch, parts in runs.items():
        out.append('<path fill="%s" d="%s"/>' % (palette[ch], "".join(parts)))
    return "".join(out)


def sprite_svg(name, scale, cls="px", dark=False):
    rows = SPRITES[name]
    h, w = len(rows), len(rows[0])
    pal = ON_DARK if dark else PALETTE
    return (
        '<svg class="%s" viewBox="0 0 %d %d" width="%d" height="%d" aria-hidden="true" '
        'focusable="false" shape-rendering="crispEdges">%s</svg>'
        % (cls, w, h, w * scale, h * scale, sprite_paths(rows, pal))
    )


def favicon_svg():
    # 16 x 16 slate tile with stepped corners, the mark re-inked in light tones
    tile = "M1 0h14v1h1v14h-1v1H1v-1H0V1h1z"
    pal = {"S": "#CAD2C5", "P": "#CAD2C5", "D": "#84A98C", "G": "#84A98C"}
    inner = sprite_paths(SPRITES["mark"], pal)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">'
        '<path fill="#2F3E46" d="%s"/><g transform="translate(2 2)">%s</g></svg>\n' % (tile, inner)
    )


# ---------------------------------------------------------------- PNG (stdlib)
def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def write_png(path, w, h, pixels):
    """pixels: bytearray of RGB, row-major."""
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw.extend(pixels[y * stride:(y + 1) * stride])

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


class Raster:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(hex_rgb(bg)) * (w * h))

    def rect(self, x, y, w, h, color):
        r, g, b = hex_rgb(color)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        line = bytes((r, g, b)) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.buf[i:i + len(line)] = line


BAYER4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
TONES = ["#2F3E46", "#354F52", "#52796F", "#84A98C", "#CAD2C5"]


class Rng:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def __call__(self):
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return self.s / 4294967296.0


def draw_og(path):
    """1200 x 630: scattered pixels on the left settle into an ordered grid on the right."""
    import math

    W, H, cell, sq = 1200, 630, 15, 12
    img = Raster(W, H, "#F8F9F7")
    cols, rows = W // cell, H // cell  # 80 x 42
    rnd = Rng(11)
    field_rows = 22
    taken = set()
    cells = []
    for y in range(field_rows):
        for x in range(cols):
            u, v = x / (cols - 1), y / (field_rows - 1)
            b = (BAYER4[(y & 3) * 4 + (x & 3)] + 0.5) / 16
            dens = 1.08 - v * 0.95 + 0.06 * math.sin(u * 7.0)
            if dens <= b:
                continue
            tone = min(4.99, max(0.0, (0.15 + 0.75 * (1 - u) + 0.35 * v) * 5 - 0.6 + (b - 0.5) * 1.1))
            cells.append((x, y, int(tone)))
    for x, y, t in cells:
        u = x / (cols - 1)
        mess = max(0.0, 1.0 - u * 1.55) ** 1.3  # 1 at the left edge, 0 from ~65%
        if mess > 0:
            if rnd() < mess * 0.55:
                continue  # dissolved
            ang = math.sin(x * 0.21 + y * 0.17) * 2.4 + rnd() * 2.0
            mag = mess * (2 + rnd() * 9)
            x = int(round(x + math.cos(ang) * mag))
            y = int(round(y + abs(math.sin(ang)) * mag * 0.9 + rnd() * mess * 6))
        if 0 <= x < cols and 0 <= y < rows - 16 and (x, y) not in taken:
            taken.add((x, y))
            img.rect(x * cell + 2, y * cell + 2, sq, sq, TONES[t])

    # wordmark: each font pixel is one grid cell
    word = "tidy-one"
    ox, oy = 4, rows - 14
    for i, ch in enumerate(word):
        g = GLYPHS[ch]
        for gy, line in enumerate(g):
            for gx, c in enumerate(line):
                if c == "#":
                    img.rect((ox + i * 6 + gx) * cell + 2, (oy + gy) * cell + 2, sq, sq, "#2F3E46")
    # the mark, bottom right, one cell per pixel
    mark = SPRITES["mark"]
    mx, my = cols - 4 - 12, rows - 16
    for gy, line in enumerate(mark):
        for gx, c in enumerate(line):
            if c != ".":
                img.rect((mx + gx) * cell + 2, (my + gy) * cell + 2, sq, sq, PALETTE[c])
    write_png(path, W, H, img.buf)


def draw_touch_icon(path):
    size, unit = 180, 10
    img = Raster(size, size, "#2F3E46")
    pal = {"S": "#CAD2C5", "P": "#CAD2C5", "D": "#84A98C", "G": "#84A98C"}
    off = (size - 12 * unit) // 2
    for gy, line in enumerate(SPRITES["mark"]):
        for gx, c in enumerate(line):
            if c != ".":
                img.rect(off + gx * unit, off + gy * unit, unit, unit, pal[c])
    write_png(path, size, size, img.buf)


# ---------------------------------------------------------------- templating
# {{ key }} escapes, {{{ key }}} is raw, {{ key | ph }} renders phrase markers (see phrase_html)
TOKEN = re.compile(r"\{\{(\{?)\s*([\w.]+)\s*(?:\|\s*(\w+)\s*)?\}?\}\}")
EDGE_SPACE = re.compile(r"^(\s*)(.*?)(\s*)$", re.S)


def plain(s):
    """Copy text without line-break markers (for attributes, titles and anything not marked up)."""
    return s.replace("|", "")


def phrase_html(s):
    """Turn line-break hints in the copy into markup.

    "a|b"   phrase boundary: each part moves to the next line as a whole (<span class="ph">,
            an inline block that wraps inside only when it alone is wider than the line)
    "a||b"  sentence boundary: each sentence is an inline block, so a sentence that fits
            stays whole and the next one starts a new line when it doesn't fit beside it

    Spaces stay in the copy (markers never replace a space), so plain() reads naturally.
    """

    def wrap(part, cls, inner):
        lead, core, trail = EDGE_SPACE.match(part).groups()
        body = '<span class="%s">%s</span>' % (cls, inner(core)) if core else ""
        return html.escape(lead) + body + html.escape(trail)

    def phrases(seg):
        parts = seg.split("|")
        if len(parts) == 1:
            return html.escape(seg, quote=True)
        return "".join(wrap(p, "ph", lambda c: html.escape(c, quote=True)) for p in parts)

    sentences = s.split("||")
    if len(sentences) == 1:
        out = phrases(s)
    else:
        out = "".join(wrap(sen, "sen", phrases) for sen in sentences)
    return trim_end_punct(out)


# Full-width punctuation that closes a display line (Chinese 。，、！？：；).
END_PUNCT = re.compile("([\u3001\u3002\uff01\uff0c\uff1a\uff1b\uff1f])((?:</span>)*)$")


def trim_end_punct(markup):
    """Mark a heading's final full-width stop so CSS can set it half width ("halt").

    The span goes inside the innermost wrapper, so nothing can break before the stop.
    """
    return END_PUNCT.sub(r'<span class="pe">\1</span>\2', markup)


FILTERS = {"ph": phrase_html}


def lookup(ctx, dotted):
    cur = ctx
    for part in dotted.split("."):
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(dotted)
    return cur


def render(template, ctx, lang):
    missing = []

    def sub(m):
        raw, key, flt = m.group(1) == "{", m.group(2), m.group(3)
        try:
            val = lookup(ctx, key)
        except KeyError:
            missing.append(key)
            return ""
        if not isinstance(val, str):
            raise TypeError("%s: {{ %s }} is not a string" % (lang, key))
        if raw:
            return val
        if flt:
            if flt not in FILTERS:
                sys.exit("[%s] unknown filter '%s' on {{ %s }}" % (lang, flt, key))
            return FILTERS[flt](val)
        return html.escape(plain(val), quote=True)

    out = TOKEN.sub(sub, template)
    if missing:
        sys.exit("[%s] missing keys: %s" % (lang, ", ".join(sorted(set(missing)))))
    return out


def flatten_keys(d, prefix=""):
    keys = set()
    for k, v in d.items():
        p = prefix + k
        if isinstance(v, dict):
            keys |= flatten_keys(v, p + ".")
        else:
            keys.add(p)
    return keys


def esc(s):
    return html.escape(s, quote=True)


def page_url(out_dir):
    return SITE_BASE_URL + "/" + out_dir


def build_context(code, out_dir, html_lang, copy, all_copy, version):
    root = "../" if out_dir else ""
    ctx = dict(copy)

    # hreflang + og:locale alternates
    alt = []
    for c, d, _hl, hreflang in LANGS:
        alt.append('<link rel="alternate" hreflang="%s" href="%s">' % (hreflang, page_url(d)))
    alt.append('<link rel="alternate" hreflang="x-default" href="%s">' % page_url(""))
    og_alt = "".join(
        '<meta property="og:locale:alternate" content="%s">' % all_copy[c]["meta"]["locale"]
        for c, *_ in LANGS
        if c != code
    )

    # language switcher (relative links, work on any host or sub-path).
    # The accessible name starts with the visible code ("KO 한국어") so speech input can use it.
    links = []
    for c, d, hl, _ in LANGS:
        href = (root + d) or "./"
        cur = ' aria-current="page"' if c == code else ""
        name = copy["nav"]["lang_" + c]
        label = "%s %s" % (SWITCH_LABEL[c], name)
        links.append(
            '<a href="%s" hreflang="%s" lang="%s" data-lang="%s" title="%s" aria-label="%s"%s>%s</a>'
            % (href, hl, hl, c, esc(name), esc(label), cur, SWITCH_LABEL[c])
        )

    # fonts: Inter Tight + JetBrains Mono everywhere, Pretendard for ko. Chinese uses the system
    # CJK fonts (PingFang SC, Microsoft YaHei, Noto Sans CJK SC) instead of ~1 MB of web fonts.
    # Font CSS never blocks first paint: preload, switch to a stylesheet on load, noscript fallback.
    def font_css(url):
        u = esc(url)
        return (
            '<link rel="preload" as="style" href="%s" onload="this.onload=null;this.rel=\'stylesheet\'">'
            '<noscript><link rel="stylesheet" href="%s"></noscript>' % (u, u)
        )

    families = "family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500"
    fonts = [font_css("https://fonts.googleapis.com/css2?%s&display=swap" % families)]
    if code == "ko":
        fonts.insert(0, '<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>')
        fonts.append(
            font_css(
                "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/"
                "dist/web/variable/pretendardvariable-dynamic-subset.min.css"
            )
        )

    def list_items(items, cls):
        return "".join('<li class="%s">%s</li>' % (cls, esc(i)) for i in items)

    def road_items(items, mark):
        icon = sprite_svg(mark, 2, "px road-mark")
        return "".join("<li>%s<span>%s</span></li>" % (icon, esc(i)) for i in items)

    # first-visit language suggestion (only rendered on the Korean root page)
    suggest = {}
    for c, d, hl, _ in LANGS:
        suggest[c] = {
            "href": d,
            "lang": hl,
            "label": all_copy[c]["nav"]["language"],
            "name": all_copy[c]["nav"]["lang_" + c],
        }

    # game: 12 slots in a 4 x 3 grid, coloured by diagonal so the tidy result is the hero's
    # slate-to-sage gradient (sage only on the last diagonals)
    by_diagonal = ["#2F3E46", "#2F3E46", "#354F52", "#52796F", "#84A98C", "#84A98C"]
    slots = []
    for i in range(12):
        x, y = i % 4, i // 4
        slots.append('<li class="slot" data-c="%s"></li>' % by_diagonal[x + y])

    json_ld = {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": "tidy-one",
        "description": copy["meta"]["description"],
        "codeRepository": REPO_URL,
        "license": "https://opensource.org/licenses/MIT",
        "programmingLanguage": "Python",
        "inLanguage": html_lang,
        "author": {"@type": "Person", "name": "Junwon Kim"},
        "url": page_url(out_dir),
    }

    ctx["_"] = {
        "html_lang": html_lang,
        "root": root,
        "home": "./",
        "repo": REPO_URL,
        "releases": REPO_URL + "/releases",
        "canonical": page_url(out_dir),
        "og_image": SITE_BASE_URL + "/assets/og.png",
        "hreflang": "\n".join(alt),
        "og_locale_alternates": og_alt,
        "font_links": "\n".join(fonts),
        "lang_links": "".join(links),
        "version": version,
        "h1_sep": "" if code == "zh" else " ",
        "logo": sprite_svg("mark", 2, "px brand-mark"),
        "mark_small": sprite_svg("mark", 2, "px"),
        "icon_devices": sprite_svg("devices", 4),
        "icon_formats": sprite_svg("formats", 4),
        "icon_search": sprite_svg("search", 4),
        "icon_agents": sprite_svg("agents", 4),
        "icon_lock": sprite_svg("lock", 4, dark=True),
        "icon_key": sprite_svg("key", 4, dark=True),
        "icon_code": sprite_svg("code", 4, dark=True),
        "node_device": sprite_svg("node_device", 4, "px node"),
        "node_server": sprite_svg("node_server", 4, "px node"),
        "node_agents": sprite_svg("node_agents", 4, "px node"),
        "works_items": list_items(copy["works_with"]["items"], "tool"),
        "done_items": road_items(copy["status"]["done"], "done"),
        "next_items": road_items(copy["status"]["next"], "next"),
        "game_slots": "".join(slots),
        "game_total": "12",
        "suggest_json": json.dumps(suggest, ensure_ascii=False).replace("</", "<\\/"),
        "json_ld": json.dumps(json_ld, ensure_ascii=False).replace("</", "<\\/"),
        "is_root": "true" if code == "ko" else "false",
        "code": code,
    }
    return ctx


def main():
    template = (SRC / "template.html").read_text(encoding="utf-8")
    all_copy = {}
    for code, *_ in LANGS:
        all_copy[code] = json.loads((I18N / ("%s.json" % code)).read_text(encoding="utf-8"))

    base_keys = flatten_keys(all_copy["ko"])
    for code in all_copy:
        diff = base_keys ^ flatten_keys(all_copy[code])
        if diff:
            sys.exit("i18n/%s.json keys differ from ko.json: %s" % (code, ", ".join(sorted(diff))))

    # generated art lives in src/assets (deterministic, so rebuilding causes no diff)
    assets = SRC / "assets"
    (assets / "favicon.svg").write_text(favicon_svg(), encoding="utf-8")
    draw_og(assets / "og.png")
    draw_touch_icon(assets / "apple-touch-icon.png")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    shutil.copytree(assets, DIST / "assets")

    h = hashlib.sha1()
    for name in ("site.css", "site.js"):
        h.update((SRC / "assets" / name).read_bytes())
    version = h.hexdigest()[:8]

    for code, out_dir, html_lang, _ in LANGS:
        ctx = build_context(code, out_dir, html_lang, all_copy[code], all_copy, version)
        out = render(template, ctx, code)
        target = DIST / out_dir / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(out, encoding="utf-8")
        print("wrote %s (%d bytes)" % (target.relative_to(ROOT), len(out.encode("utf-8"))))

    # GitHub Pages niceties
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % SITE_BASE_URL, encoding="utf-8")
    urls = []
    for _c, d, _hl, _ in LANGS:
        alts = "".join(
            '\n    <xhtml:link rel="alternate" hreflang="%s" href="%s"/>' % (hl2, page_url(d2))
            for _c2, d2, _h2, hl2 in LANGS
        )
        urls.append("  <url>\n    <loc>%s</loc>%s\n  </url>" % (page_url(d), alts))
    (DIST / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n%s\n</urlset>\n' % "\n".join(urls),
        encoding="utf-8",
    )
    print("done -> %s" % DIST.relative_to(ROOT))


if __name__ == "__main__":
    main()
