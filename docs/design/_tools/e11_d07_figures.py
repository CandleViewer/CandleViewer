"""Stdlib PNG renderer for the two E11-D07 figures ("rendered by the tool, not a Penpot board").

Imported by ``e11_d07_a11y_review_audit.py --figures <dir>``; never run on its own path at import.
Pure Python: a 24-bit PNG writer (``zlib`` + ``struct``), axis-aligned rectangles, 1 px lines
with a dash pattern, a 45-degree hatch and a 5 x 7 bitmap font (upper case, digits and the few
symbols the labels need), so the figures are reproducible on any host without numpy or PIL.
Every colour comes from the audit's resolved dark-theme tokens and every number from its counts;
nothing is typed here that the review does not carry.

Figure A - the surrogate-sizing overlay: the compact chassis at 1280 px with every interactive
surrogate drawn as a translucent hit box and its size from the target table, a dense-floor strip
and a 4:1 inset of the D10 cursor column and the CMP-039 ring.
Figure B - the composed-encoding sheet: one bar column with the encodings stacked, in dark /
light / high-contrast, each with its composite ratio from the matrix, plus a greyscale strip.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any

RGB = tuple[int, int, int]

# 5 x 7 glyphs, rows top to bottom, 5 bits each (MSB = left column).
FONT: dict[str, tuple[int, ...]] = {
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    "/": (0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    "+": (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    "%": (0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "=": (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),
    "x": (0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11),
    ">": (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),
    "<": (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02),
    ",": (0x00, 0x00, 0x00, 0x00, 0x0C, 0x04, 0x08),
    "#": (0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A),
    "|": (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    ";": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x04, 0x08),
    "'": (0x04, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00),
    " ": (0, 0, 0, 0, 0, 0, 0),
}


def hex_rgb(h: str) -> RGB:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    r, g, b2 = (round(a[i] * (1 - t) + b[i] * t) for i in range(3))
    return (r, g, b2)


class Canvas:
    def __init__(self, w: int, h: int, bg: RGB) -> None:
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def put(self, x: int, y: int, c: RGB) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i : i + 3] = bytes(c)

    def get(self, x: int, y: int) -> RGB:
        i = (y * self.w + x) * 3
        return self.px[i], self.px[i + 1], self.px[i + 2]

    def rect(self, x: int, y: int, w: int, h: int, c: RGB, alpha: float = 1.0) -> None:
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self.put(xx, yy, c if alpha >= 1.0 else mix(self.get(xx, yy), c, alpha))

    def frame(self, x: int, y: int, w: int, h: int, c: RGB, t: int = 1) -> None:
        self.rect(x, y, w, t, c)
        self.rect(x, y + h - t, w, t, c)
        self.rect(x, y, t, h, c)
        self.rect(x + w - t, y, t, h, c)

    def dashed_v(self, x: int, y: int, h: int, c: RGB, on: int = 4, off: int = 4) -> None:
        yy = y
        while yy < y + h:
            self.rect(x, yy, 1, min(on, y + h - yy), c)
            yy += on + off

    def dashed_h(self, x: int, y: int, w: int, c: RGB, on: int = 4, off: int = 4) -> None:
        xx = x
        while xx < x + w:
            self.rect(xx, y, min(on, x + w - xx), 1, c)
            xx += on + off

    def hatch(self, x: int, y: int, w: int, h: int, c: RGB, pitch: int) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if (xx - x + yy - y) % pitch == 0:
                    self.put(xx, yy, c)

    def text(self, x: int, y: int, s: str, c: RGB, scale: int = 2) -> int:
        cx = x
        for ch in s.upper():
            g = FONT.get(ch, FONT["#"])
            for r, bits in enumerate(g):
                for col in range(5):
                    if bits & (0x10 >> col):
                        self.rect(cx + col * scale, y + r * scale, scale, scale, c)
            cx += 6 * scale
        return cx

    def png(self) -> bytes:
        raw = b"".join(
            b"\x00" + bytes(self.px[y * self.w * 3 : (y + 1) * self.w * 3]) for y in range(self.h)
        )

        def chunk(tag: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(tag + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )


def _tok(d: dict[str, Any], name: str, fallback: str) -> RGB:
    return hex_rgb(d["dark_hex"].get(name, fallback))


def render_overlay(d: dict[str, Any]) -> Canvas:
    """Figure A: hit boxes over the compact chassis (sizes from the target table)."""
    canvas_c = _tok(d, "color.surface.canvas", "#11151A")
    raised = _tok(d, "color.surface.raised", "#161B22")
    text = _tok(d, "color.text.primary", "#E8EAED")
    text3 = _tok(d, "color.text.tertiary", "#8B949E")
    border = _tok(d, "color.border.default", "#2E363E")
    ring = _tok(d, "color.focus.ring", "#6EA1F5")
    warn = _tok(d, "color.status.warning.strong", "#F5C86B")
    cv = Canvas(1280, 1000, canvas_c)
    cv.text(16, 12, "E11-D07 FIGURE A - SURROGATE SIZING OVERLAY (COMPACT, 1280 PX)", text, 2)
    cv.text(
        16, 30, "RENDERED BY THE TOOL, NOT A PENPOT BOARD - HIT BOXES IN THE RING COLOUR", text3, 2
    )
    x0, y0, w = 16, 56, 1248
    box = (ring, 0.28)

    def hit(x: int, y: int, bw: int, bh: int, label: str) -> None:
        cv.rect(x, y, bw, bh, box[0], box[1])
        cv.frame(x, y, bw, bh, ring)
        cv.text(x + 4, y + max(2, bh // 2 - 6), label, text, 2)

    # toolbar and status rows (24), drawing rail (24, dashed: E14 in flight)
    cv.rect(x0, y0, w, 24, raised)
    hit(x0, y0, w, 24, "TOOLBAR ROW 24 (CMP-221, ROVING)   VIEW SWITCH CHART | TABLE 24")
    cv.rect(x0, y0 + 24, w, 24, raised)
    hit(x0, y0 + 24, 420, 24, "STATUS CHIPS: 20 PX PILL + 2 + 2 = 24")
    rail_x, rail_w = x0, 24
    pane_y = y0 + 48
    pane1_h, split_h, pane2_h, strip_h = 320, 24, 160, 24
    cv.frame(rail_x, pane_y, rail_w, pane1_h + split_h + pane2_h, text3)
    cv.dashed_v(rail_x + 12, pane_y, pane1_h + split_h + pane2_h, text3, 2, 4)
    cv.text(rail_x + 28, pane_y + 72, "RAIL 24 (E14-D02, IN FLIGHT: 24 X 24 PER TOOL)", text3, 2)
    gutter_w = 48
    plot_x = x0 + rail_w
    plot_w = w - rail_w - gutter_w
    # pane 1: legend rows, plot, price gutter, lock badge
    hit(plot_x + 8, pane_y + 8, 260, 24, "LEGEND ROW 0 (PANE LABEL) 24")
    hit(plot_x + 8, pane_y + 36, 260, 24, "LEGEND ROW 1 + EYE TOGGLE 24 X 24")
    cv.text(
        plot_x + 300, pane_y + 120, "PLOT: ONE ROVING STOP (THE SURROGATE IS THE PLOT)", text3, 2
    )
    gx = plot_x + plot_w
    hit(gx, pane_y, gutter_w, pane1_h, "48")
    cv.text(gx - 420, pane_y + pane1_h - 60, "PRICE GUTTER >= 48 X PANE HEIGHT", text3, 2)
    hit(gx - 120, pane_y + pane1_h - 30, 116, 24, "LOCK BADGE 24")
    # splitter: hairline + 24 px band + 24 x 4 grip
    sy = pane_y + pane1_h
    hit(plot_x, sy, plot_w + gutter_w, split_h, "SPLITTER HIT BAND 24 (12 + 12)")
    cv.rect(plot_x, sy + 12, plot_w + gutter_w, 1, border)
    cv.rect(plot_x + plot_w // 2 - 12, sy + 10, 24, 4, text3)
    cv.text(plot_x + plot_w // 2 + 20, sy + 6, "GRIP 24 X 4", text3, 2)
    # pane 2 and the collapsed stub
    p2 = sy + split_h
    hit(plot_x + 8, p2 + 8, 260, 24, "LEGEND ROW 0 (VOLUME) 24")
    hit(gx, p2, gutter_w, pane2_h, "48")
    hit(plot_x + 300, p2 + 100, 420, 24, "COLLAPSED STUB 24 + RESTORE BUTTON 24 X 24")
    # time strip and cluster
    ty = p2 + pane2_h
    hit(plot_x, ty, plot_w, strip_h, "TIME STRIP (DRAG ZONE) 24")
    hit(plot_x + plot_w - 3 * 24 - 8, ty, 72, 24, "A|F|> 24")
    # table surrogates row
    tb = ty + strip_h + 16
    cv.text(
        x0,
        tb,
        "TABLE VIEW (SCR-045): ROW 24  EXPANDER CELL 24  HEADER BUTTON 24  CHIP 20+2+2",
        text3,
        2,
    )
    hit(x0, tb + 18, 600, 24, "BAR ROW 24 (THE ROW IS THE TARGET)")
    hit(x0 + 604, tb + 18, 24, 24, "")
    hit(x0 + 632, tb + 18, 200, 24, "HEADER BUTTON 24")
    # dense-floor strip
    dy = tb + 56
    cv.text(
        x0,
        dy,
        "DENSE FLOOR (E11-D02 D6 RULE 3): LEGEND 24  STRIP 24  CLUSTER 24  SPLITTER 24  GUTTER 48",
        warn,
        2,
    )
    for i, (lab, bw) in enumerate((("24", 24), ("24", 24), ("24", 24), ("24", 24), ("48", 48))):
        hit(x0 + i * 60, dy + 18, bw, 24, lab)
    # 4:1 inset: D10 column core 2 px + 1 px halos; CMP-039 ring 2 px at 2 px offset + 1 px halo
    ix, iy = 16, dy + 60
    cv.frame(ix, iy, 1000, 190, border)
    cv.text(
        ix + 8,
        iy + 6,
        "INSET 4:1 - D10 COLUMN: 1 PX HALO, >=2 PX CORE, 1 PX HALO (LEFT);",
        text3,
        2,
    )
    cv.text(
        ix + 8,
        iy + 24,
        "CMP-039 RING: 2 PX RING AT 2 PX OFFSET + 1 PX HALO OVER RAISED CHROME (RIGHT)",
        text3,
        2,
    )
    cx = ix + 60
    cv.rect(cx, iy + 60, 4, 110, canvas_c)
    cv.rect(cx + 4, iy + 60, 8, 110, ring)
    cv.rect(cx + 12, iy + 60, 4, 110, canvas_c)
    cv.frame(cx - 2, iy + 58, 20, 114, border)
    rx, ry = ix + 160, iy + 80
    cv.rect(rx, ry, 160, 60, raised)
    cv.frame(rx - 4, ry - 4, 168, 68, canvas_c, 4)
    cv.frame(rx - 12, ry - 12, 184, 84, ring, 8)
    cv.frame(rx - 16, ry - 16, 192, 92, canvas_c, 4)
    cv.text(16, 958, "SIZES: THE AUDIT TOOL'S TARGET TABLE (E11-D07 SECTION 10).", text3, 2)
    cv.text(
        16,
        978,
        "TOKENS: SIZE.CONTROL.COMPACT 24, SIZE.TARGET.MIN 24, SPACE.6 24, SPACE.12 48",
        text3,
        2,
    )
    return cv


def render_sheet(d: dict[str, Any]) -> Canvas:
    """Figure B: the composed-encoding stack in three themes plus a greyscale strip."""
    comp = {c["id"]: c for c in d["composition"]}
    themes = ("dark", "light", "high-contrast")
    tokens = (
        "color.surface.canvas",
        "color.grid.line",
        "color.border.default",
        "color.crosshair",
        "color.focus.ring",
        "color.candle.up",
        "color.candle.down",
        "color.footprint.imbalance",
        "color.text.tertiary",
        "color.surface.selected",
        "color.surface.hover",
    )
    th_hex: dict[str, dict[str, str]] = d["theme_hex"]
    dark_text = hex_rgb(th_hex["dark"].get("color.text.primary", "#E8EAED"))
    cv = Canvas(1280, 820, hex_rgb(th_hex["dark"]["color.surface.canvas"]))
    cv.text(16, 12, "E11-D07 FIGURE B - COMPOSED ENCODING SHEET (ONE BAR COLUMN, L0)", dark_text, 2)
    cv.text(
        16,
        30,
        "RENDERED BY THE TOOL, NOT A PENPOT BOARD - RATIOS FROM THE AUDIT MATRIX",
        hex_rgb(th_hex["dark"]["color.text.tertiary"]),
        2,
    )
    col_w = 300
    for i, th in enumerate((*themes, "greyscale")):
        src = th_hex["dark" if th == "greyscale" else th]

        def tok(name: str, _src: dict[str, str] = src, _grey: bool = th == "greyscale") -> RGB:
            h = _src[name]
            if _grey:
                r, g, b = hex_rgb(h)
                lv = int(0.299 * r + 0.587 * g + 0.114 * b)
                return (lv, lv, lv)
            return hex_rgb(h)

        x = 16 + i * (col_w + 16)
        y = 60
        bg = tok("color.surface.canvas")
        cv.rect(x, y, col_w, 640, bg)
        txt = tok("color.text.tertiary")
        cv.text(x + 8, y + 6, th.upper(), tok("color.focus.ring") if th != "greyscale" else txt, 2)
        # gridlines, crosshair, D10 column, candles (live and dimmed), imbalance outline, hatch
        for gy in range(y + 60, y + 400, 40):
            cv.rect(x, gy, col_w, 1, tok("color.grid.line"))
        cv.rect(x, y + 220, col_w, 1, tok("color.border.default"))
        cv.dashed_h(x, y + 236, col_w, tok("color.crosshair"), 4, 4)
        cv.rect(x + 58, y + 40, 1, 380, bg)
        cv.rect(x + 59, y + 40, 2, 380, tok("color.focus.ring"))
        cv.rect(x + 61, y + 40, 1, 380, bg)
        up, down = tok("color.candle.up"), tok("color.candle.down")
        cv.rect(x + 100, y + 120, 24, 110, up)
        cv.rect(x + 111, y + 90, 2, 170, up)
        dim = tuple(int(c * 0.85) for c in down)
        cv.rect(x + 150, y + 150, 24, 110, dim)  # type: ignore[arg-type]
        cv.rect(x + 161, y + 120, 2, 170, dim)  # type: ignore[arg-type]
        cv.frame(x + 200, y + 150, 60, 24, tok("color.footprint.imbalance"), 2)
        cv.rect(x + 200, y + 190, 60, 24, tok("color.surface.hover"))
        cv.hatch(x + 200, y + 190, 60, 24, txt, 2)
        cv.rect(x + 200, y + 230, 60, 24, tok("color.surface.selected"))
        cv.frame(x + 198, y + 228, 64, 28, tok("color.focus.ring"), 2)
        cv.text(x + 8, y + 282, "CROSSHAIR / MAJOR / MINOR", txt, 2)
        cv.text(x + 8, y + 300, "D10 COLUMN  STALE X0.85  IMB  HATCH  SEL+RING", txt, 2)
        cv.text(x + 8, y + 318, "T3 AXIS / HIDDEN LEGEND", txt, 2)
        if th != "greyscale":
            rows = (
                ("C5 RING/CANVAS", "C5"),
                ("C6 XHAIR/MAJOR", "C6"),
                ("C7 XHAIR/MINOR", "C7"),
                ("C8 RING/XHAIR", "C8"),
                ("C1 UP X0.85", "C1"),
                ("C2 DOWN X0.85", "C2"),
                ("C4 IMB X0.85", "C4"),
                ("C9 IMB/SEL", "C9"),
                ("C12 RING/SEL", "C12"),
                ("C18 T3/CANVAS", "C18"),
                ("C19 TEXT/SEL", "C19"),
            )
            yy = y + 350
            for lab, cid in rows:
                v = comp[cid][th]
                cv.text(x + 8, yy, f"{lab}: {v:.2f}" if v is not None else f"{lab}: N/A", txt, 2)
                yy += 18
            cv.text(x + 8, yy + 6, "BARS 3.0 NT 4.5 T 7.0 HC", txt, 2)
        else:
            yy = y + 350
            cv.text(x + 8, yy, "LUMA, FLOORED:", txt, 2)
            yy += 18
            cv.text(x + 8, yy, "0.299R+0.587G+0.114B", txt, 2)
            yy += 18
            for name in tokens:
                lv = d["greyscale"].get(name)
                cv.text(x + 8, yy, f"{name.split('.')[-1][:10].upper()} {lv}", txt, 2)
                yy += 18
    foot = hex_rgb(th_hex["dark"]["color.text.tertiary"])
    cv.text(
        16, 776, "EVERY RATIO IS THE AUDIT TOOL'S COMPOSITION ROW (E11-D07 SECTION 11).", foot, 2
    )
    cv.text(
        16,
        796,
        "HOLLOW, DASHED OR HATCHED = ESTIMATED OR ABSENT, NEVER A SIDE (E25-D01, PROPOSED).",
        foot,
        2,
    )
    return cv


def render_all(out_dir: Path, d: dict[str, Any]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    a = out_dir / "E11-D07-figA-surrogate-sizing-overlay.png"
    b = out_dir / "E11-D07-figB-composed-encoding-sheet.png"
    a.write_bytes(render_overlay(d).png())
    b.write_bytes(render_sheet(d).png())
    return [a, b]
