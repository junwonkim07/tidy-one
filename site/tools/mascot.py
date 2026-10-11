"""tidy-one mascot at 32px resolution: a small server box with a screen face and a note card on top.
Writes theme-able SVGs (CSS vars with light fallbacks), crisp PNGs and a preview sheet.

    uv run --with pillow python tools/mascot.py src/assets/mascot [sheet-dir]

The preview sheets go to sheet-dir when it is given (keep them out of src/assets), else next to the art."""
import os
import sys

from PIL import Image

OUT = sys.argv[1]
SHEETS = sys.argv[2] if len(sys.argv) > 2 else OUT
W, H = 40, 36
PAL = {
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

# body box
BX0, BY0, BX1, BY1 = 7, 10, 32, 29     # inclusive
SX0, SY0, SX1, SY1 = 10, 13, 29, 23    # screen
CX0, CY0, CX1, CY1 = 15, 3, 24, 11     # note card on top (overlaps body top)


def blank():
    return [["."] * W for _ in range(H)]


def fill(g, x0, y0, x1, y1, c):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if 0 <= x < W and 0 <= y < H:
                g[y][x] = c


def put(g, pts, c):
    for x, y in pts:
        if 0 <= x < W and 0 <= y < H:
            g[y][x] = c


def rbox(g, x0, y0, x1, y1, fillc, line="O", r=2):
    """Rounded box: 1px outline, corners cut by radius r (1 or 2)."""
    fill(g, x0, y0, x1, y1, line)
    fill(g, x0 + 1, y0 + 1, x1 - 1, y1 - 1, fillc)
    corners = [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]
    for cx, cy, sx, sy in corners:
        g[cy][cx] = "."
        if r >= 2:
            g[cy][cx + sx] = "."
            g[cy + sy][cx] = "."
            g[cy + sy][cx + sx] = line  # inner corner pixel keeps the outline continuous


def stamp(g, x0, y0, rows):
    """Draw a small bitmap (palette letters, '.' = leave as is) with its top-left at x0, y0."""
    for dy, row in enumerate(rows):
        for dx, c in enumerate(row):
            if c != ".":
                put(g, [(x0 + dx, y0 + dy)], c)


def base(eyes="open", mouth="smile"):
    g = blank()
    # note card (behind the body top)
    rbox(g, CX0, CY0, CX1, CY1, "D", r=1)
    fill(g, CX0 + 2, CY0 + 2, CX1 - 3, CY0 + 2, "d")
    fill(g, CX0 + 2, CY0 + 4, CX1 - 2, CY0 + 4, "d")
    # body
    rbox(g, BX0, BY0, BX1, BY1, "B", r=2)
    # slot the card goes into
    fill(g, CX0 - 1, BY0, CX1 + 1, BY0, "O")
    fill(g, CX0, BY0 + 1, CX1, BY0 + 1, "b")
    # soft shade along the bottom of the body
    fill(g, BX0 + 1, BY1 - 1, BX1 - 1, BY1 - 1, "b")
    g[BY1 - 1][BX0 + 1] = "B"; g[BY1 - 1][BX1 - 1] = "B"
    # screen: rounded bezel; the cut corners show the body, never the page behind it
    rbox(g, SX0, SY0, SX1, SY1, "S", r=1)
    put(g, [(SX0, SY0), (SX1, SY0), (SX0, SY1), (SX1, SY1)], "B")
    # drive slot + leds under the screen
    fill(g, SX0 + 1, SY1 + 3, SX0 + 11, SY1 + 3, "O")
    put(g, [(SX1 - 4, SY1 + 3), (SX1 - 3, SY1 + 3)], "M")
    put(g, [(SX1 - 1, SY1 + 3)], "d")
    # feet
    fill(g, BX0 + 3, BY1 + 1, BX0 + 7, BY1 + 2, "O")
    fill(g, BX1 - 7, BY1 + 1, BX1 - 3, BY1 + 2, "O")
    face(g, eyes, mouth)
    return g


LE, RE, EY = 14, 22, SY0 + 2   # 4-wide eyes, symmetric around the screen centre


def face(g, eyes, mouth):
    for ex in (LE, RE):
        if eyes == "open":
            fill(g, ex, EY, ex + 3, EY + 3, "E")
            for cx, cy in ((ex, EY), (ex + 3, EY), (ex, EY + 3), (ex + 3, EY + 3)):
                g[cy][cx] = "S"
            g[EY + 1][ex + 2] = "W"
        elif eyes == "closed":
            put(g, [(ex, EY + 2), (ex + 1, EY + 3), (ex + 2, EY + 3), (ex + 3, EY + 2)], "E")
        elif eyes == "happy":
            put(g, [(ex, EY + 3), (ex + 1, EY + 2), (ex + 2, EY + 2), (ex + 3, EY + 3)], "E")
            put(g, [(ex + 1, EY + 1), (ex + 2, EY + 1)], "E")
        elif eyes == "right":
            fill(g, ex + 2, EY, ex + 3, EY + 3, "E")
            g[EY][ex + 3] = "S"; g[EY + 3][ex + 3] = "S"
            g[EY + 1][ex + 3] = "W"
    put(g, [(LE - 2, EY + 4), (LE - 1, EY + 4), (RE + 4, EY + 4), (RE + 5, EY + 4)], "C")
    mx = (SX0 + SX1) // 2
    if mouth == "smile":
        put(g, [(mx - 3, EY + 4), (mx + 2, EY + 4)], "M")
        fill(g, mx - 2, EY + 5, mx + 1, EY + 5, "M")
    elif mouth == "o":
        fill(g, mx - 1, EY + 4, mx, EY + 5, "M")
    elif mouth == "flat":
        fill(g, mx - 1, EY + 5, mx, EY + 5, "M")


poses = {}
poses["idle"] = base()
poses["blink"] = base(eyes="closed")

g = base(eyes="closed", mouth="flat")
put(g, [(33, 1), (34, 1), (35, 1), (36, 1), (36, 2), (35, 3), (34, 4), (33, 5), (34, 5), (35, 5), (36, 5)], "d")
put(g, [(36, 7), (37, 7), (38, 7), (38, 8), (37, 9), (36, 10), (37, 10), (38, 10)], "M")
poses["sleep"] = g

# wave: a mitten (thumb towards the face) raised above the body, in two frames that site.js
# swaps while it waves: the hand upright, then tipped outwards, with a small motion mark
MITTEN = [
    "...OOOO.",
    "..OBBBBO",
    "..OBBBBO",
    ".OOBBBBO",
    "OBBOBBBO",
    "OBBOBBBO",
    ".OBBBBBO",
    "..OBBBBO",
    "...OOOO.",
]
MITTEN_OUT = [
    "....OOO.",
    "...OBBBO",
    "..OBBBBO",
    ".OOBBBBO",
    "OBBOBBBO",
    "OBBOBBO.",
    ".OBBBBO.",
    "..OBBBO.",
    "...OOO..",
]
g = base(eyes="happy", mouth="smile")
stamp(g, 31, 0, MITTEN)
fill(g, 35, 9, 36, 9, "O")                                                # wrist
put(g, [(35, 10), (34, 11), (34, 12), (33, 13), (33, 14), (33, 15)], "O")   # arm
put(g, [(36, 10), (35, 11), (35, 12), (34, 13), (34, 14)], "O")
put(g, [(28, 2), (27, 3), (27, 4), (28, 5)], "M")                          # motion mark
poses["wave"] = g

g = base(eyes="happy", mouth="smile")
stamp(g, 32, 1, MITTEN_OUT)
fill(g, 35, 10, 36, 10, "O")                                              # wrist
put(g, [(35, 11), (34, 12), (34, 13), (33, 14), (33, 15)], "O")             # arm
put(g, [(36, 11), (35, 12), (35, 13), (34, 14)], "O")
put(g, [(29, 4), (28, 5), (28, 6), (29, 7)], "M")                          # motion mark
poses["wave2"] = g

g = base(eyes="right", mouth="o")
put(g, [(33, 22), (34, 21)], "O")                                         # arm
rbox(g, 33, 9, 39, 15, "E", r=2)                                          # lens ring + glass
put(g, [(35, 11)], "W")
put(g, [(34, 16), (34, 17), (34, 18), (34, 19), (34, 20)], "O")           # handle
poses["search"] = g

g = base(eyes="open", mouth="smile")
put(g, [(33, 21), (34, 21)], "O")                                         # arm
fill(g, 35, 14, 35, 28, "O")                                              # broom handle
fill(g, 33, 29, 38, 30, "d")                                              # bristles
fill(g, 32, 31, 39, 32, "d")
put(g, [(33, 30), (35, 30), (37, 30)], "M")
fill(g, 1, 27, 4, 32, "M")                                                # tidy stack
fill(g, 1, 27, 4, 27, "d"); fill(g, 1, 30, 4, 30, "d")
put(g, [(5, 23)], "D")                                                    # last loose pixel
poses["tidy"] = g

# second sweep frame: the broom leans and the bristles swing one pixel left (alternates with "tidy")
g = base(eyes="open", mouth="smile")
put(g, [(33, 21), (34, 21)], "O")                                         # arm
put(g, [(37, 14), (37, 15), (37, 16), (36, 17), (36, 18), (36, 19)], "O")  # broom handle, leaning
fill(g, 35, 20, 35, 24, "O")
fill(g, 34, 25, 34, 28, "O")
fill(g, 32, 29, 37, 30, "d")                                              # bristles
fill(g, 31, 31, 38, 32, "d")
put(g, [(32, 30), (34, 30), (36, 30)], "M")
fill(g, 1, 27, 4, 32, "M")                                                # tidy stack
fill(g, 1, 27, 4, 27, "d"); fill(g, 1, 30, 4, 30, "d")
put(g, [(5, 23)], "D")                                                    # last loose pixel
poses["tidy2"] = g


def to_svg(g):
    rects = []
    for y in range(H):
        x = 0
        while x < W:
            c = g[y][x]
            if c == ".":
                x += 1
                continue
            x2 = x
            while x2 + 1 < W and g[y][x2 + 1] == c:
                x2 += 1
            var, hexv = PAL[c]
            rects.append(f'<rect x="{x}" y="{y}" width="{x2 - x + 1}" height="1" fill="var({var},{hexv})"/>')
            x = x2 + 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W * 4}" height="{H * 4}" '
            f'shape-rendering="crispEdges" role="img" aria-label="tidy-one mascot">' + "".join(rects) + "</svg>\n")


def to_png(g, scale):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y in range(H):
        for x in range(W):
            c = g[y][x]
            if c != ".":
                h = PAL[c][1].lstrip("#")
                im.putpixel((x, y), (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255))
    return im.resize((W * scale, H * scale), Image.NEAREST)


os.makedirs(OUT, exist_ok=True)
for name, g in poses.items():
    with open(os.path.join(OUT, f"mascot-{name}.svg"), "w") as f:
        f.write(to_svg(g))
    to_png(g, 16).save(os.path.join(OUT, f"mascot-{name}.png"))
for bg, tag in (((247, 248, 246, 255), "light"), ((30, 42, 47, 255), "dark")):
    rows = (len(poses) + 2) // 3
    sheet = Image.new("RGBA", (W * 8 * 3 + 40, (H * 8 + 10) * rows + 10), bg)
    for i, (name, g) in enumerate(poses.items()):
        im = to_png(g, 8)
        sheet.paste(im, (10 + (i % 3) * (W * 8 + 10), 10 + (i // 3) * (H * 8 + 10)), im)
    sheet.save(os.path.join(SHEETS, f"_sheet-{tag}.png"))
print("poses:", list(poses), "canvas", W, "x", H)
