#!/usr/bin/env python3
"""Build the tidy-one landing page.

    python3 build.py

Renders src/template.html with the copy in i18n/en.json and the client list in
i18n/clients.json into

    dist/index.html      the page (English)
    dist/en/index.html   redirect to ../ (the page used to have /en/ and /zh/ versions)
    dist/zh/index.html   redirect to ../

and copies src/assets/ to dist/assets/. Along the way it inlines

  * one hidden SVG sprite with the 16 x 16 pixel icons (ICONS below) and the mascot
    poses (src/assets/mascot/mascot-*.svg), so every use follows the light/dark theme
    through CSS custom properties,
  * the client logos (src/assets/logos/*.svg, fill="currentColor"),

and draws favicon.svg, apple-touch-icon.png and og.png from the mascot bitmaps.

Standard library only (Python 3.9+). SITE_BASE_URL is the absolute base used
for canonical, og:url, og:image, the sitemap and robots.txt. It defaults to the
GitHub Pages project URL; set it for another host, e.g.

    SITE_BASE_URL=https://tidy-one.example python3 build.py

(SITE_URL is still read as an older alias.) Links inside the page (assets, home)
are relative, so dist/ works at / on a local server and under /tidy-one/ on
GitHub Pages without rebuilding.
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
COPY_FILE = I18N / "en.json"
CLIENTS_FILE = I18N / "clients.json"
MASCOT_DIR = SRC / "assets" / "mascot"

DEFAULT_BASE_URL = "https://junwonkim07.github.io/tidy-one"
SITE_BASE_URL = (
    os.environ.get("SITE_BASE_URL") or os.environ.get("SITE_URL") or DEFAULT_BASE_URL
).strip().rstrip("/")
if not re.match(r"^https?://[^/\s]+(/[^\s]*)?$", SITE_BASE_URL):
    sys.exit("SITE_BASE_URL must be an absolute http(s) URL, got %r" % SITE_BASE_URL)
REPO_URL = "https://github.com/junwonkim07/tidy-one"

# Old language URLs that now redirect to the English page.
OLD_PAGES = ["en/", "zh/"]

# ---------------------------------------------------------------- palette
PALETTE = {
    "mist": "#CAD2C5",
    "sage": "#84A98C",
    "deep": "#52796F",
    "pine": "#354F52",
    "slate": "#2F3E46",
    "paper": "#F8F9F7",
    "paper2": "#EEF1EC",
}

# ---------------------------------------------------------------- pixel icons
# 16 x 16. '#' is drawn in currentColor, '+' in the accent (--icon-accent), '.' is empty.
# One-pixel outlines with cut corners and an accent fill, like the mascot.
ICONS = {
    "hourglass": [
        "................",
        "..############..",
        "...#........#...",
        "...#++++++++#...",
        "....#++++++#....",
        ".....#++++#.....",
        "......#++#......",
        ".......##.......",
        "......#..#......",
        ".....#....#.....",
        "....#..++..#....",
        "...#.++++++.#...",
        "...#++++++++#...",
        "..############..",
        "................",
        "................",
    ],
    "check": [
        "................",
        "..############..",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#+++++++++##+#.",
        ".#++++++++##++#.",
        ".#+++++++##+++#.",
        ".#+##+++##++++#.",
        ".#++##+##+++++#.",
        ".#+++###++++++#.",
        ".#++++#+++++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        "..############..",
        "................",
    ],
    "scatter": [
        "................",
        ".###.......++...",
        ".###.......++...",
        ".###............",
        "......++........",
        "......++....###.",
        "............###.",
        "..++........###.",
        "..++............",
        "........###.....",
        "........###.....",
        "........###..++.",
        "..###........++.",
        "..###...........",
        "..###.....++....",
        "..........++....",
    ],
    "grid": [
        "................",
        ".######..######.",
        ".#....#..#++++#.",
        ".#....#..#++++#.",
        ".#....#..#++++#.",
        ".#....#..#++++#.",
        ".######..######.",
        "................",
        "................",
        ".######..######.",
        ".#++++#..#....#.",
        ".#++++#..#....#.",
        ".#++++#..#....#.",
        ".#++++#..#....#.",
        ".######..######.",
        "................",
    ],
    "flow": [
        "................",
        "................",
        "......####......",
        "......#++#......",
        "......#++#......",
        "......####......",
        ".......##.......",
        "......#..#......",
        ".....#....#.....",
        "....#......#....",
        "..####....####..",
        "..#++#....#++#..",
        "..#++#....#++#..",
        "..####....####..",
        "................",
        "................",
    ],
    "shield": [
        "................",
        ".......##.......",
        ".....##++##.....",
        "...##++++++##...",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..#++++##++++#..",
        "..#+++####+++#..",
        "..#++++##++++#..",
        "..#++++##++++#..",
        "...#++++++++#...",
        "...#++++++++#...",
        "....#++++++#....",
        ".....##++##.....",
        ".......##.......",
        "................",
    ],
    "plug": [
        "................",
        ".....#....#.....",
        ".....#....#.....",
        ".....#....#.....",
        "...##########...",
        "...#++++++++#...",
        "...#++++++++#...",
        "...#++++++++#...",
        "....#++++++#....",
        ".....##++##.....",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "................",
    ],
    "flag": [
        "................",
        "...##...........",
        "...##########...",
        "...##+++++++#...",
        "...##++++++#....",
        "...##+++++#.....",
        "...##++++++#....",
        "...##+++++++#...",
        "...##########...",
        "...##...........",
        "...##...........",
        "...##...........",
        "...##...........",
        "..####..........",
        "................",
        "................",
    ],
    "laptop": [
        "................",
        "................",
        "................",
        "..############..",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..############..",
        ".#............#.",
        "################",
        "................",
        "................",
        "................",
    ],
    "window": [
        "................",
        "................",
        ".##############.",
        ".#+++++##+++++#.",
        ".#+++++##+++++#.",
        ".#+++++##+++++#.",
        ".##############.",
        ".#+++++##+++++#.",
        ".#+++++##+++++#.",
        ".#+++++##+++++#.",
        ".##############.",
        ".......##.......",
        ".......##.......",
        ".....######.....",
        "................",
        "................",
    ],
    "phone": [
        "................",
        ".....######.....",
        "....#......#....",
        "....#++++++#....",
        "....#++++++#....",
        "....#++++++#....",
        "....#++++++#....",
        "....#++++++#....",
        "....#++++++#....",
        "....#++++++#....",
        "....#......#....",
        "....#..##..#....",
        "....#......#....",
        ".....######.....",
        "................",
        "................",
    ],
    "doc": [
        "................",
        "...########.....",
        "...#++++++##....",
        "...#++++++#+#...",
        "...#++++++####..",
        "...#+++++++++#..",
        "...#+######++#..",
        "...#+++++++++#..",
        "...#+######++#..",
        "...#+++++++++#..",
        "...#+####++++#..",
        "...#+++++++++#..",
        "...#+++++++++#..",
        "...###########..",
        "................",
        "................",
    ],
    "photo": [
        "................",
        "................",
        ".##############.",
        ".#............#.",
        ".#.........++.#.",
        ".#.........++.#.",
        ".#............#.",
        ".#....+.......#.",
        ".#...+++......#.",
        ".#..+++++..+..#.",
        ".#.+++++++++++#.",
        ".#++++++++++++#.",
        ".##############.",
        "................",
        "................",
        "................",
    ],
    "video": [
        "................",
        "................",
        "..############..",
        ".#++++++++++++#.",
        ".#++++#+++++++#.",
        ".#++++##++++++#.",
        ".#++++###+++++#.",
        ".#++++####++++#.",
        ".#++++###+++++#.",
        ".#++++##++++++#.",
        ".#++++#+++++++#.",
        ".#++++++++++++#.",
        "..############..",
        "................",
        "................",
        "................",
    ],
    "cloud": [
        "................",
        "................",
        "................",
        ".......####.....",
        "......#++++#....",
        "...###++++++#...",
        "..#+++++++++##..",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        "..############..",
        "................",
        "................",
        "................",
        "................",
        "................",
    ],
    "mail": [
        "................",
        "................",
        "................",
        ".##############.",
        ".##++++++++++##.",
        ".#+#++++++++#+#.",
        ".#++#++++++#++#.",
        ".#+++#++++#+++#.",
        ".#++++####++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".##############.",
        "................",
        "................",
        "................",
        "................",
    ],
    "mic": [
        "................",
        "......####......",
        ".....#++++#.....",
        ".....#++++#.....",
        ".....#++++#.....",
        ".....#++++#.....",
        "...#.#++++#.#...",
        "...#..####..#...",
        "....#......#....",
        ".....######.....",
        ".......##.......",
        ".......##.......",
        ".....######.....",
        "................",
        "................",
        "................",
    ],
    "chat": [
        "................",
        "................",
        "..############..",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#+##++##++##+#.",
        ".#+##++##++##+#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        "..###++#######..",
        "....#+#.........",
        "....##..........",
        "................",
        "................",
        "................",
        "................",
    ],
    "note": [
        "................",
        "..###########...",
        "..#+++++++++#...",
        "..#+##+++++##...",
        "..#+++++++++#...",
        "..#+#######+#...",
        "..#+++++++++#...",
        "..#+#######+#...",
        "..#+++++++++#...",
        "..#+#####+++#...",
        "..#+++++++++#...",
        "..#++++++++##...",
        "..#+++++++#+#...",
        "..##########....",
        "................",
        "................",
    ],
    "folder": [
        "................",
        "................",
        ".#####..........",
        ".#+++##########.",
        ".#++++++++++++#.",
        ".##############.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".#++++++++++++#.",
        ".##############.",
        "................",
        "................",
        "................",
    ],
    "search": [
        "................",
        "....######......",
        "...#++++++#.....",
        "..#++++++++#....",
        "..#+##+++++#....",
        "..#+#++++++#....",
        "..#++++++++#....",
        "..#++++++++#....",
        "...#++++++##....",
        "....#######.....",
        "..........###...",
        "...........###..",
        "............###.",
        ".............##.",
        "................",
        "................",
    ],
    "bot": [
        "................",
        ".......##.......",
        ".......##.......",
        "...##########...",
        "..#++++++++++#..",
        "..#+##++++##+#..",
        "..#+##++++##+#..",
        "..#++++++++++#..",
        "..#+++####+++#..",
        "..#++++++++++#..",
        "...##########...",
        ".....#....#.....",
        "....###..###....",
        "................",
        "................",
        "................",
    ],
    "server": [
        "................",
        ".##############.",
        ".#++++++++++++#.",
        ".#+####+++##++#.",
        ".#++++++++++++#.",
        ".##############.",
        ".#++++++++++++#.",
        ".#+####+++##++#.",
        ".#++++++++++++#.",
        ".##############.",
        ".#++++++++++++#.",
        ".#+####+++##++#.",
        ".#++++++++++++#.",
        ".##############.",
        "..##........##..",
        "................",
    ],
    "devices": [
        "................",
        "................",
        ".########.......",
        ".#++++++#.......",
        ".#++++++#.......",
        ".#++++++#..#####",
        ".#++++++#..#+++#",
        ".#++++++#..#+++#",
        ".########..#+++#",
        "##########.#+++#",
        "...........#+++#",
        "...........#####",
        "................",
        "................",
        "................",
        "................",
    ],
    "house": [
        "................",
        ".......##.......",
        "......####......",
        ".....##++##.....",
        "....##++++##....",
        "...##++++++##...",
        "..##++++++++##..",
        ".##############.",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..#+++####+++#..",
        "..#+++#..#+++#..",
        "..#+++#..#+++#..",
        "..############..",
        "................",
        "................",
    ],
    "key": [
        "................",
        "................",
        "................",
        "................",
        "..###...........",
        ".#+++#..........",
        "#++.++#.........",
        "#+...+##########",
        "#++.++##########",
        ".#+++#....##.##.",
        "..###.....##.##.",
        "................",
        "................",
        "................",
        "................",
        "................",
    ],
    "lock": [
        "................",
        ".....######.....",
        "....##....##....",
        "....#......#....",
        "....#......#....",
        "....#......#....",
        "..############..",
        "..#++++++++++#..",
        "..#++++##++++#..",
        "..#++++##++++#..",
        "..#+++++#++++#..",
        "..#++++++++++#..",
        "..#++++++++++#..",
        "..############..",
        "................",
        "................",
    ],
    "terminal": [
        "................",
        "................",
        ".##############.",
        ".##############.",
        ".#++++++++++++#.",
        ".#+#++++++++++#.",
        ".#++#+++++++++#.",
        ".#+++#++++++++#.",
        ".#++#+++++++++#.",
        ".#+#+++####+++#.",
        ".#++++++++++++#.",
        ".##############.",
        "................",
        "................",
        "................",
        "................",
    ],
    "branch": [
        "................",
        "..####....####..",
        "..#++#....#++#..",
        "..#++#....#++#..",
        "..####....####..",
        "...##......##...",
        "...##......##...",
        "...##.....##....",
        "...##....##.....",
        "...##..##.......",
        "...####.........",
        "...##...........",
        "..####..........",
        "..#++#..........",
        "..#++#..........",
        "..####..........",
    ],
    "scale": [
        "................",
        ".......##.......",
        ".##############.",
        ".#.....##.....#.",
        ".#.....##.....#.",
        "#.#....##....#.#",
        "#.#....##....#.#",
        "#####..##..#####",
        "#+++#..##..#+++#",
        ".###...##...###.",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".....######.....",
        "....########....",
        "................",
    ],
    "bell": [
        "................",
        ".......##.......",
        ".....######.....",
        "....#++++++#....",
        "...#++++++++#...",
        "...#++++++++#...",
        "...#++++++++#...",
        "...#++++++++#...",
        "..#++++++++++#..",
        ".#++++++++++++#.",
        ".##############.",
        "......####......",
        ".......##.......",
        "................",
        "................",
        "................",
    ],
    "book": [
        "................",
        "................",
        ".####......####.",
        "#++++##..##++++#",
        "#++++++##++++++#",
        "#+###++##++###+#",
        "#++++++##++++++#",
        "#+###++##++###+#",
        "#++++++##++++++#",
        "#+###++##++###+#",
        "#++++++##++++++#",
        "#####++##++#####",
        ".....######.....",
        "................",
        "................",
        "................",
    ],
    "sun": [
        "................",
        ".......##.......",
        ".......##.......",
        "...#........#...",
        "................",
        "......####......",
        ".....#++++#.....",
        ".##..#++++#..##.",
        ".##..#++++#..##.",
        ".....#++++#.....",
        "......####......",
        "................",
        "...#........#...",
        ".......##.......",
        ".......##.......",
        "................",
    ],
    "moon": [
        "................",
        "................",
        "....##..........",
        "...#+#..........",
        "..#++#..........",
        ".#++#...........",
        ".#++#...........",
        ".#+++#..........",
        ".#+++#..........",
        ".#++++#......#..",
        "..#++++#######..",
        "..#+++++++++#...",
        "...##+++++##....",
        ".....#####......",
        "................",
        "................",
    ],
    "arrowup": [
        "................",
        "................",
        ".......##.......",
        "......####......",
        ".....######.....",
        "....########....",
        "...###.##.###...",
        "..###..##..###..",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "................",
        "................",
    ],
    "broom": [
        "..............##",
        ".............##.",
        "............##..",
        "...........##...",
        "..........##....",
        ".........##.....",
        "......#####.....",
        ".....#+++##.....",
        "....#++++#......",
        "...#++++#.......",
        "..#+#+#+#.......",
        ".#+#+#+#........",
        "#+#+#+#.........",
        "#######.........",
        "................",
        "................",
    ],
}

# how-it-works nodes, drawn larger. Letters map to theme variables (see NODE_VARS).
NODES = {
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
NODE_VARS = {
    "S": "var(--art-line,#2F3E46)",
    "M": "var(--art-fill,#CAD2C5)",
    "G": "var(--art-a1,#84A98C)",
    "D": "var(--art-a2,#52796F)",
    "P": "var(--art-a3,#354F52)",
}

# The mascot's head at 16 x 16: favicon, touch icon and the brand mark in the header and footer.
# Letters follow tools/mascot.py: O line, B body, b shade, S screen, E eye, W glint, M smile,
# C cheek, D card, d card lines.
HEAD = [
    ".....OOOOOO.....",
    ".....ODDDDO.....",
    ".....OddddO.....",
    ".OOOOOOOOOOOOOO.",
    "OBBBBbbbbbbBBBBO",
    "OBOOOOOOOOOOOOBO",
    "OBOSSSSSSSSSSOBO",
    "OBOSEWSSSSEWSOBO",
    "OBOSEESSSSEESOBO",
    "OBOCSSMSSMSSCOBO",
    "OBOSSSSMMSSSSOBO",
    "OBOOOOOOOOOOOOBO",
    "OBBBBBBBBBBBBBBO",
    "ObbbbbbbbbbbbbbO",
    ".OOOOOOOOOOOOOO.",
    "..OOO......OOO..",
]
MASCOT_VARS = {
    "O": ("--m-line", "#2F3E46"),
    "B": ("--m-body", "#CAD2C5"),
    "b": ("--m-shade", "#84A98C"),
    "S": ("--m-screen", "#354F52"),
    "E": ("--m-eye", "#CAD2C5"),
    "W": ("--m-glint", "#FFFFFF"),
    "M": ("--m-smile", "#84A98C"),
    "C": ("--m-cheek", "#52796F"),
    "D": ("--m-card", "#84A98C"),
    "d": ("--m-card2", "#52796F"),
}
MASCOT_POSES = ["idle", "blink", "wave", "search", "sleep", "tidy", "tidy2"]

# 5 x 9 pixel font for the Open Graph image (rows 0-1 ascender, 2-6 x-height, 7-8 descender)
GLYPHS = {
    "a": [".....", ".....", ".###.", "....#", ".####", "#...#", ".####", ".....", "....."],
    "c": [".....", ".....", ".####", "#....", "#....", "#....", ".####", ".....", "....."],
    "d": ["....#", "....#", ".####", "#...#", "#...#", "#...#", ".####", ".....", "....."],
    "e": [".....", ".....", ".###.", "#...#", "#####", "#....", ".###.", ".....", "....."],
    "f": ["..##.", ".#...", "####.", ".#...", ".#...", ".#...", ".#...", ".....", "....."],
    "g": [".....", ".....", ".####", "#...#", "#...#", "#...#", ".####", "....#", ".###."],
    "i": ["..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###.", ".....", "....."],
    "l": [".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###.", ".....", "....."],
    "m": [".....", ".....", "##.#.", "#.#.#", "#.#.#", "#.#.#", "#.#.#", ".....", "....."],
    "n": [".....", ".....", "####.", "#...#", "#...#", "#...#", "#...#", ".....", "....."],
    "o": [".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###.", ".....", "....."],
    "p": [".....", ".....", "####.", "#...#", "#...#", "#...#", "####.", "#....", "#...."],
    "r": [".....", ".....", "#.##.", "##..#", "#....", "#....", "#....", ".....", "....."],
    "s": [".....", ".....", ".####", "#....", ".###.", "....#", "####.", ".....", "....."],
    "t": [".#...", ".#...", "####.", ".#...", ".#...", ".#...", "..##.", ".....", "....."],
    "u": [".....", ".....", "#...#", "#...#", "#...#", "#...#", ".####", ".....", "....."],
    "v": [".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#..", ".....", "....."],
    "y": [".....", ".....", "#...#", "#...#", "#...#", "#...#", ".####", "....#", ".###."],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#", ".....", "....."],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####", ".....", "....."],
    "-": [".....", ".....", ".....", ".....", ".###.", ".....", ".....", ".....", "....."],
    ",": [".....", ".....", ".....", ".....", ".....", ".##..", ".##..", "..#..", ".#..."],
    ".": [".....", ".....", ".....", ".....", ".....", ".##..", ".##..", ".....", "....."],
    " ": [".....", ".....", ".....", ".....", ".....", ".....", ".....", ".....", "....."],
}


def check_bitmaps():
    for name, rows in ICONS.items():
        if len(rows) != 16 or any(len(r) != 16 for r in rows):
            sys.exit("icon %s is not 16 x 16" % name)
    for name, rows in NODES.items():
        if any(len(r) != len(rows[0]) for r in rows):
            sys.exit("node %s has ragged rows" % name)
    if len(HEAD) != 16 or any(len(r) != 16 for r in HEAD):
        sys.exit("HEAD is not 16 x 16")


def runs(rows):
    """Horizontal runs per character: {ch: [(x, y, w), ...]}."""
    out = {}
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
            out.setdefault(ch, []).append((start, y, x - start))
    return out


def run_path(parts):
    return "".join("M%d %dh%dv1h-%dz" % (x, y, w, w) for x, y, w in parts)


def style_fill(value):
    # Fills go in a style attribute: custom properties in it resolve wherever the <use> is.
    return 'style="fill:%s"' % value


# ---------------------------------------------------------------- sprite
def icon_def(name):
    r = runs(ICONS[name])
    parts = []
    if "#" in r:
        parts.append('<path fill="currentColor" d="%s"/>' % run_path(r["#"]))
    if "+" in r:
        parts.append('<path %s d="%s"/>' % (style_fill("var(--icon-accent,#84A98C)"), run_path(r["+"])))
    return '<g id="i-%s">%s</g>' % (name, "".join(parts))


RECT = re.compile(
    r'<rect x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" fill="var\((--m-[\w-]+),\s*(#[0-9A-Fa-f]{6})\)"\s*/>'
)


def read_mascot(pose):
    """Parse a generated mascot SVG into {(var, fallback): [(x, y, w, h), ...]} in source order."""
    text = (MASCOT_DIR / ("mascot-%s.svg" % pose)).read_text(encoding="utf-8")
    rects = RECT.findall(text)
    if not rects or len(rects) != text.count("<rect"):
        sys.exit("mascot-%s.svg: unexpected markup (regenerate it with tools/mascot.py)" % pose)
    out = {}
    for x, y, w, h, var, hexv in rects:
        out.setdefault((var, hexv.upper()), []).append((int(x), int(y), int(w), int(h)))
    return out


def mascot_def(pose):
    parts = []
    for (var, hexv), rects in read_mascot(pose).items():
        d = "".join("M%d %dh%dv%dh-%dz" % (x, y, w, h, w) for x, y, w, h in rects)
        parts.append('<path %s d="%s"/>' % (style_fill("var(%s,%s)" % (var, hexv)), d))
    return '<g id="m-%s">%s</g>' % (pose, "".join(parts))


def head_def():
    parts = []
    for ch, rr in runs(HEAD).items():
        var, hexv = MASCOT_VARS[ch]
        parts.append('<path %s d="%s"/>' % (style_fill("var(%s,%s)" % (var, hexv)), run_path(rr)))
    return '<g id="m-head">%s</g>' % "".join(parts)


def sprite():
    defs = [icon_def(n) for n in ICONS] + [mascot_def(p) for p in MASCOT_POSES] + [head_def()]
    return (
        '<svg class="sprite" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" '
        'shape-rendering="crispEdges"><defs>%s</defs></svg>' % "".join(defs)
    )


def icon(name, cls=""):
    if name not in ICONS:
        sys.exit("unknown icon %r" % name)
    return (
        '<svg class="ic%s" viewBox="0 0 16 16" aria-hidden="true" focusable="false" '
        'shape-rendering="crispEdges"><use href="#i-%s"/></svg>' % ((" " + cls) if cls else "", name)
    )


def mascot(pose, cls=""):
    # 40 x 32 crops the four empty rows under the feet; the broom's bristles (row 32) may poke
    # out below (overflow is visible), so the feet stand on whatever line the mascot sits on.
    return (
        '<svg class="mascot%s" viewBox="0 0 40 32" aria-hidden="true" focusable="false" '
        'shape-rendering="crispEdges"><use href="#m-%s"/></svg>' % ((" " + cls) if cls else "", pose)
    )


def head(cls=""):
    return (
        '<svg class="head%s" viewBox="0 0 16 16" aria-hidden="true" focusable="false" '
        'shape-rendering="crispEdges"><use href="#m-head"/></svg>' % ((" " + cls) if cls else "")
    )


def node_svg(name):
    rows = NODES[name]
    h, w = len(rows), len(rows[0])
    paths = "".join(
        '<path %s d="%s"/>' % (style_fill(NODE_VARS[ch]), run_path(rr)) for ch, rr in runs(rows).items()
    )
    return (
        '<svg class="node" viewBox="0 0 %d %d" width="%d" height="%d" aria-hidden="true" '
        'focusable="false" shape-rendering="crispEdges">%s</svg>' % (w, h, w * 4, h * 4, paths)
    )


# ---------------------------------------------------------------- client logos
LOGO_SVG = re.compile(r"^\s*<svg\b[^>]*\bviewBox=\"0 0 24 24\"[^>]*>(.*)</svg>\s*$", re.S)


def logo_svg(rel):
    path = SRC / "assets" / rel
    text = path.read_text(encoding="utf-8")
    m = LOGO_SVG.match(text)
    if not m:
        sys.exit("%s: expected one 24 x 24 <svg>" % rel)
    inner = m.group(1).strip()
    if re.search(r"<script|<foreignObject|\son\w+\s*=|href\s*=", inner, re.I):
        sys.exit("%s: unexpected content" % rel)
    if 'fill="currentColor"' not in inner:
        sys.exit("%s: the path should use fill=\"currentColor\"" % rel)
    return '<svg class="logo" viewBox="0 0 24 24" aria-hidden="true" focusable="false">%s</svg>' % inner


def client_items(clients):
    out = []
    for c in clients:
        name, url, logo = c["name"], c["url"], c.get("logo") or ""
        if not re.match(r"^https://", url):
            sys.exit("clients.json: %s needs an https URL" % name)
        if logo:
            mark = '<span class="client-mark">%s</span>' % logo_svg(logo)
            cls = "client"
        else:
            # no logo file: the name itself is set as a wordmark in the logo's place
            mark = '<span class="client-mark client-word" aria-hidden="true">%s</span>' % esc(name)
            cls = "client client-text"
        out.append(
            '<li class="%s"><a href="%s" rel="noopener">%s<span class="client-name">%s</span></a></li>'
            % (cls, esc(url), mark, esc(name))
        )
    return "".join(out)


# ---------------------------------------------------------------- favicon
def favicon_svg():
    """The mascot's head; outline and screen switch to lighter tones on a dark browser theme."""
    classes = {"O": "o", "B": "b", "b": "s", "S": "sc", "E": "e", "W": "w", "M": "m", "C": "c", "D": "d", "d": "d2"}
    paths = "".join('<path class="%s" d="%s"/>' % (classes[ch], run_path(rr)) for ch, rr in runs(HEAD).items())
    css = (
        ".o{fill:#2F3E46}.b{fill:#CAD2C5}.s{fill:#84A98C}.sc{fill:#354F52}.e{fill:#CAD2C5}.w{fill:#fff}"
        ".m{fill:#84A98C}.c{fill:#52796F}.d{fill:#84A98C}.d2{fill:#52796F}"
        "@media (prefers-color-scheme:dark){.o{fill:#84A98C}.s{fill:#52796F}.sc{fill:#1E2A2F}.d{fill:#CAD2C5}.d2{fill:#52796F}}"
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">'
        "<style>%s</style>%s</svg>\n" % (css, paths)
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

    def mascot(self, pose, ox, oy, unit):
        for (_var, hexv), rects in read_mascot(pose).items():
            for x, y, w, h in rects:
                self.rect(ox + x * unit, oy + y * unit, w * unit, h * unit, hexv)

    def text(self, s, ox, oy, unit, color, gap=1):
        """Pixel font, set proportionally: each font pixel is a unit x unit square; returns the width."""
        x = ox
        for ch in s:
            g = GLYPHS[ch]
            lo, hi = glyph_span(ch)
            for gy, line in enumerate(g):
                for gx, c in enumerate(line):
                    if c == "#":
                        self.rect(x + (gx - lo) * unit, oy + gy * unit, unit, unit, color)
            x += (hi - lo + 1 + gap) * unit
        return x - ox - gap * unit


def glyph_span(ch):
    """First and last inked column of a glyph (a space is three columns wide)."""
    cols = [i for i in range(5) if any(row[i] == "#" for row in GLYPHS[ch])]
    return (min(cols), max(cols)) if cols else (0, 2)


class Rng:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def __call__(self):
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return self.s / 4294967296.0


def draw_og(path):
    """1200 x 630: the wordmark and tagline on the left; on the right the mascot, standing on a
    mist floor, has swept most pixels into a tidy stack and is reaching for the last few."""
    W, H = 1200, 630
    img = Raster(W, H, PALETTE["paper"])
    floor = 512
    img.rect(0, floor, W, 2, PALETTE["mist"])
    img.rect(0, floor + 2, W, H - floor - 2, PALETTE["paper2"])

    # wordmark + tagline
    x0, y0 = 72, 168
    img.text("tidy-one", x0, y0, 17, PALETTE["slate"])
    tu, ty = 5, y0 + 9 * 17 + 48
    img.text("one tidy, private memory", x0, ty, tu, PALETTE["pine"])
    img.text("for all your AI agents.", x0, ty + 11 * tu + 4, tu, PALETTE["pine"])

    # the mascot, 8 px per art pixel, feet on the floor line (the feet end at row 32)
    mu = 8
    mx, my = 812, floor - 32 * mu
    img.mascot("tidy", mx, my, mu)

    # the last loose pixels, to the right of the broom
    loose = [(1146, floor - 22, 14, "deep"), (1166, floor - 44, 12, "sage"), (1180, floor - 14, 12, "pine"),
             (1156, floor - 70, 10, "sage"), (1184, floor - 58, 8, "deep")]
    for x, y, size, tone in loose:
        img.rect(x, y, size, size, PALETTE[tone])
    write_png(path, W, H, img.buf)


def draw_touch_icon(path):
    size = 180
    img = Raster(size, size, PALETTE["paper2"])
    unit = 4  # 40 x 36 art at 4x = 160 x 144; the feet end at row 32, so centre rows 3..32
    ox = (size - 40 * unit) // 2
    oy = (size - 30 * unit) // 2 - 3 * unit
    img.mascot("idle", ox, oy, unit)
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
        return phrases(s)
    return "".join(wrap(sen, "sen", phrases) for sen in sentences)


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


def render(template, ctx):
    missing = []

    def sub(m):
        raw, key, flt = m.group(1) == "{", m.group(2), m.group(3)
        try:
            val = lookup(ctx, key)
        except KeyError:
            missing.append(key)
            return ""
        if not isinstance(val, str):
            raise TypeError("{{ %s }} is not a string" % key)
        if raw:
            return val
        if flt:
            if flt not in FILTERS:
                sys.exit("unknown filter '%s' on {{ %s }}" % (flt, key))
            return FILTERS[flt](val)
        return html.escape(plain(val), quote=True)

    out = TOKEN.sub(sub, template)
    if missing:
        sys.exit("missing keys: %s" % ", ".join(sorted(set(missing))))
    return out


def esc(s):
    return html.escape(s, quote=True)


def page_url(out_dir=""):
    return SITE_BASE_URL + "/" + out_dir


def build_context(copy, clients, version):
    ctx = dict(copy)

    # Inter Tight only (no monospace anywhere). Font CSS never blocks first paint: preload,
    # switch to a stylesheet on load, noscript fallback.
    font_url = esc("https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600&display=swap")
    fonts = (
        '<link rel="preload" as="style" href="%s" onload="this.onload=null;this.rel=\'stylesheet\'">'
        '<noscript><link rel="stylesheet" href="%s"></noscript>' % (font_url, font_url)
    )

    def chips(items):
        return '<ul class="chips">%s</ul>' % "".join(
            '<li class="chip">%s<span>%s</span></li>' % (icon(i), esc(label)) for i, label in items
        )

    def road_items(items, mark):
        out = []
        for names, text in items:
            topic = "".join(icon(n, "topic") for n in names.split())
            out.append(
                '<li>%s<span class="road-topics">%s</span><span class="road-text">%s</span></li>'
                % (icon(mark, "road-mark"), topic, esc(text))
            )
        return "".join(out)

    # game: 12 slots in a 4 x 3 grid, toned by diagonal so the tidy result runs from the
    # darkest tone to sage, like the hero field (tones are theme variables, see site.css)
    by_diagonal = [0, 0, 1, 2, 3, 3]
    slots = "".join('<li class="slot" data-t="%d"></li>' % by_diagonal[i % 4 + i // 4] for i in range(12))

    json_ld = {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": "tidy-one",
        "description": copy["meta"]["description"],
        "codeRepository": REPO_URL,
        "license": "https://opensource.org/licenses/MIT",
        "programmingLanguage": "Python",
        "inLanguage": "en",
        "author": {"@type": "Person", "name": "Junwon Kim"},
        "url": page_url(),
    }

    feats = copy["features"]
    ctx["_"] = {
        "home": "./",
        "repo": REPO_URL,
        "releases": REPO_URL + "/releases",
        "license": REPO_URL + "/blob/main/LICENSE",
        "readme": REPO_URL + "#readme",
        "canonical": page_url(),
        "og_image": SITE_BASE_URL + "/assets/og.png",
        "font_links": fonts,
        "version": version,
        "sprite": sprite(),
        "ic": {n: icon(n) for n in ICONS},
        "m": {p: mascot(p) for p in MASCOT_POSES},
        "head": head(),
        "node_device": node_svg("node_device"),
        "node_server": node_svg("node_server"),
        "node_agents": node_svg("node_agents"),
        "device_chips": chips(feats["devices"]["chips"]),
        "format_chips": chips(feats["formats"]["chips"]),
        "clients": client_items(clients),
        "done_items": road_items(copy["status"]["done"], "check"),
        "next_items": road_items(copy["status"]["next"], "hourglass"),
        "game_slots": slots,
        "game_total": "12",
        "json_ld": json.dumps(json_ld, ensure_ascii=False).replace("</", "<\\/"),
    }
    return ctx


REDIRECT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tidy-one</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="%(canonical)s">
<meta http-equiv="refresh" content="0; url=../">
<script>window.location.replace("../" + window.location.hash);</script>
</head>
<body>
<p><a href="../">tidy-one</a></p>
</body>
</html>
"""


def main():
    check_bitmaps()
    template = (SRC / "template.html").read_text(encoding="utf-8")
    copy = json.loads(COPY_FILE.read_text(encoding="utf-8"))
    clients = json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))

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

    out = render(template, build_context(copy, clients, version))
    target = DIST / "index.html"
    target.write_text(out, encoding="utf-8")
    print("wrote %s (%d bytes)" % (target.relative_to(ROOT), len(out.encode("utf-8"))))

    # the old language pages keep working: they send visitors (and their #section) to the page
    for old in OLD_PAGES:
        stub = DIST / old / "index.html"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(REDIRECT % {"canonical": esc(page_url())}, encoding="utf-8")
        print("wrote %s (redirect to ../)" % stub.relative_to(ROOT))

    # GitHub Pages niceties
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % SITE_BASE_URL, encoding="utf-8")
    (DIST / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n    <loc>%s</loc>\n  </url>\n</urlset>\n" % page_url(),
        encoding="utf-8",
    )
    print("done -> %s" % DIST.relative_to(ROOT))


if __name__ == "__main__":
    main()
