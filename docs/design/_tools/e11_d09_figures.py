"""Stdlib PNG renderer for E11-D09's figure A (rendered by the tool, not a Penpot board).

Imported by ``e11_d09_handoff_audit.py --figures <dir>``; never run on its own path at import.
Pure Python: a 24-bit PNG writer (``zlib`` + ``struct``), axis-aligned rectangles, 1 px lines with
a dash pattern, a 45-degree hatch and a 5 x 7 bitmap font (upper case, digits and the symbols the
labels need; lower case is drawn with the upper-case glyph and the sheet says so), so the figure is
reproducible on any host without numpy or PIL. Every colour comes from the audit's resolved
dark-theme tokens and every number from its counts; nothing is typed here that the pack does not
carry. No network call is made and no URL literal exists in this file.

Figure A - the asset sheet: the seven E11-D05 section 7 patterns as swatches at 1:1 and 4:1 with
their geometry text, the glyph-set union as monochrome text with its count, and the twelve icon
names E11-D05 CR-6 requests, each marked "requested - not at the base".
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
    " ": (0, 0, 0, 0, 0, 0, 0),
    ".": (0, 0, 0, 0, 0, 0x0C, 0x0C),
    ",": (0, 0, 0, 0, 0x0C, 0x04, 0x08),
    ":": (0, 0x0C, 0x0C, 0, 0x0C, 0x0C, 0),
    "-": (0, 0, 0, 0x1F, 0, 0, 0),
    "+": (0, 0x04, 0x04, 0x1F, 0x04, 0x04, 0),
    "/": (0x01, 0x01, 0x02, 0x04, 0x08, 0x10, 0x10),
    "%": (0x19, 0x1A, 0x02, 0x04, 0x08, 0x0B, 0x13),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "·": (0, 0, 0, 0x0C, 0x0C, 0, 0),
    "\u00d7": (0, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0),
    "\u2013": (0, 0, 0, 0x1F, 0, 0, 0),
    "▲": (0x04, 0x04, 0x0E, 0x0E, 0x1F, 0x1F, 0),
    "▼": (0, 0x1F, 0x1F, 0x0E, 0x0E, 0x04, 0x04),
    "°": (0x0E, 0x0A, 0x0E, 0, 0, 0, 0),
    "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0, 0x04),
}


def hex_rgb(h: str) -> RGB:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def text_w(s: str, scale: int = 2) -> int:
    return len(s) * 6 * scale


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


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
                self.put(xx, yy, c if alpha >= 1 else mix(self.get(xx, yy), c, alpha))

    def frame(self, x: int, y: int, w: int, h: int, c: RGB, t: int = 1) -> None:
        self.rect(x, y, w, t, c)
        self.rect(x, y + h - t, w, t, c)
        self.rect(x, y, t, h, c)
        self.rect(x + w - t, y, t, h, c)

    def dashed_h(
        self, x: int, y: int, w: int, c: RGB, on: int = 4, off: int = 4, t: int = 1
    ) -> None:
        xx = x
        while xx < x + w:
            self.rect(xx, y, min(on, x + w - xx), t, c)
            xx += on + off

    def dashed_frame(self, x: int, y: int, w: int, h: int, c: RGB, on: int, off: int) -> None:
        self.dashed_h(x, y, w, c, on, off)
        self.dashed_h(x, y + h - 1, w, c, on, off)
        yy = y
        while yy < y + h:
            self.rect(x, yy, 1, min(on, y + h - yy), c)
            self.rect(x + w - 1, yy, 1, min(on, y + h - yy), c)
            yy += on + off

    def hatch(
        self, x: int, y: int, w: int, h: int, c: RGB, pitch: int, t: int = 1, alpha: float = 1.0
    ) -> None:
        """45-degree lines at `pitch` px, `t` px thick, clipped to the rectangle."""
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if ((xx - x) + (yy - y)) % pitch < t:
                    self.put(xx, yy, c if alpha >= 1 else mix(self.get(xx, yy), c, alpha))

    def text(self, x: int, y: int, s: str, c: RGB, scale: int = 2) -> int:
        cx = x
        for ch in s:
            g = FONT.get(ch) or FONT.get(ch.upper()) or FONT["?"]
            for row, bits in enumerate(g):
                for col in range(5):
                    if bits & (0x10 >> col):
                        self.rect(cx + col * scale, y + row * scale, scale, scale, c)
            cx += 6 * scale
        return cx - x

    def png(self) -> bytes:
        raw = bytearray()
        stride = self.w * 3
        for yy in range(self.h):
            raw.append(0)
            raw += self.px[yy * stride : (yy + 1) * stride]

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b"")
        )


def _tok(d: dict[str, Any], name: str, fallback: str) -> RGB:
    return hex_rgb(d["theme_hex"]["dark"].get(name) or fallback)


def render_sheet(d: dict[str, Any]) -> Canvas:
    bg = _tok(d, "color.surface.app", "#0B0E11")
    canvas_c = _tok(d, "color.surface.canvas", "#11151A")
    raised = _tok(d, "color.surface.raised", "#161B22")
    text = _tok(d, "color.text.primary", "#E8EAED")
    text2 = _tok(d, "color.text.secondary", "#B1BAC4")
    text3 = _tok(d, "color.text.tertiary", "#8B949E")
    border = _tok(d, "color.border.default", "#2E363E")
    strong = _tok(d, "color.border.strong", "#3D4650")
    up = _tok(d, "color.candle.up", "#2EBD59")
    c = Canvas(1280, 820, bg)
    c.text(32, 24, "E11-D09 FIGURE A - ASSET SHEET (RENDERED BY THE TOOL)", text, 2)
    c.text(
        32,
        46,
        "PATTERNS FROM E11-D05 SECTION 7 AT 1:1 AND 4:1 - INKS ARE THE RESOLVED DARK TOKENS - "
        "NO BINARY ASSET IS INVENTED",
        text3,
        1,
    )
    y = 72
    pats = d["patterns"]
    for i, p in enumerate(pats):
        row_y = y + i * 72
        c.rect(32, row_y, 1216, 64, canvas_c)
        c.frame(32, row_y, 1216, 64, border)
        c.text(44, row_y + 8, p["id"].upper(), text, 1)
        c.text(44, row_y + 22, p["geometry"][:70].upper(), text2, 1)
        c.text(44, row_y + 36, ("INK " + p["ink"][:60]).upper(), text3, 1)
        c.text(
            44,
            row_y + 50,
            ("OPACITY " + p["opacity"] + " - " + p["meaning"][:40]).upper(),
            text3,
            1,
        )
        pid = p["id"]
        # 1:1 swatch (48 x 48) and 4:1 swatch (192 x 48)
        sx, s4 = 740, 820
        c.rect(sx, row_y + 8, 48, 48, raised)
        c.rect(s4, row_y + 8, 192, 48, raised)
        if pid == "pattern.hatch.estimated":
            c.rect(sx, row_y + 8, 48, 48, up)
            c.hatch(sx, row_y + 8, 48, 48, text, 2, 1, 0.3)
            c.rect(s4, row_y + 8, 192, 48, up)
            c.hatch(s4, row_y + 8, 192, 48, text, 8, 4, 0.3)
        elif pid == "pattern.dashed.estimated":
            c.dashed_h(sx, row_y + 32, 48, up, 4, 3)
            c.dashed_h(s4, row_y + 32, 192, up, 16, 12, 4)
        elif pid in ("pattern.hatch.gap", "pattern.hatch.absent"):
            ink = strong if pid == "pattern.hatch.gap" else text3
            c.hatch(sx, row_y + 8, 48, 48, ink, 6, 1)
            c.dashed_frame(sx, row_y + 8, 48, 48, text3, 4, 4)
            c.hatch(s4, row_y + 8, 192, 48, ink, 24, 4)
            c.dashed_frame(s4, row_y + 8, 192, 48, text3, 16, 16)
        elif pid == "pattern.dashed.tested":
            c.dashed_h(sx, row_y + 32, 48, mix(raised, up, 0.7), 4, 3)
            c.dashed_h(s4, row_y + 32, 192, mix(raised, up, 0.7), 16, 12, 4)
        elif pid == "pattern.outline.imbalance":
            c.rect(sx + 8, row_y + 16, 32, 32, up)
            c.frame(
                sx + 8, row_y + 16, 32, 32, _tok(d, "color.status.warning.strong", "#F5C86B"), 2
            )
            c.rect(s4 + 32, row_y + 8, 128, 48, up)
            c.frame(
                s4 + 32, row_y + 8, 128, 48, _tok(d, "color.status.warning.strong", "#F5C86B"), 6
            )
        elif pid == "glyph.notch.delta":
            c.rect(sx + 8, row_y + 16, 32, 32, up)
            for k in range(6):
                c.rect(sx + 40 - k, row_y + 16 + k, 1, 1, bg)
            c.rect(s4 + 32, row_y + 8, 128, 48, up)
            for k in range(24):
                c.rect(s4 + 160 - k - 1, row_y + 8 + k, 1, 1, bg)
            c.rect(s4 + 136, row_y + 8, 24, 24, bg, 0.0)
        c.text(sx, row_y + 58, "1:1", text3, 1)
        c.text(s4, row_y + 58, "4:1", text3, 1)
    y = y + len(pats) * 72 + 16
    gl = d["glyphs"]
    c.text(
        32,
        y,
        f"GLYPH UNION FROM THE GL STRINGS - {gl['count']} GLYPHS (PROPOSED INPUT TO E11-K01); "
        "LOWER CASE DRAWN AS UPPER CASE BY THIS BITMAP FONT",
        text,
        1,
    )
    c.rect(32, y + 16, 1216, 40, canvas_c)
    c.frame(32, y + 16, 1216, 40, border)
    c.text(44, y + 26, "".join(gl["union"]), text, 2)
    y += 72
    c.text(
        32,
        y,
        f"EXTRAS BEYOND 26 SECTION 3.7: {''.join(gl['extras_vs_26'])}   "
        f"MISSING FROM THE STRINGS: {''.join(gl['missing_vs_26'])}",
        text3,
        1,
    )
    y += 24
    c.text(
        32,
        y,
        f"ICONS REQUESTED BY E11-D05 CR-6 ({len(d['icons'])}) - EACH REQUESTED, NOT AT THE BASE",
        text,
        1,
    )
    y += 16
    for i, name in enumerate(d["icons"]):
        col, row = i % 4, i // 4
        bx, by = 32 + col * 304, y + row * 26
        c.rect(bx, by, 292, 20, raised)
        c.frame(bx, by, 292, 20, border)
        c.text(bx + 6, by + 4, (name + " - REQUESTED").upper(), text2, 1)
    y += (len(d["icons"]) + 3) // 4 * 26 + 8
    fo = d["fonts"]
    fam = ", ".join(str(v) for v in fo["families"].values()).upper()
    wts = ", ".join(str(v) for v in fo["weights"].values())
    c.text(
        32,
        y,
        f"FONTS BY TOKEN: {fam} - WEIGHTS {wts} - FILES AT THE BASE: {len(fo['font_files'])}",
        text3,
        1,
    )
    y += 20
    c.text(32, y, "PAGE E11-D09 CHART-ENGINE HANDOFF PACK - FIGURE A - TEXT PR", text3, 1)
    return c


def render_all(out_dir: Path, d: dict[str, Any]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "E11-D09-figA-asset-sheet.png"
    target.write_bytes(render_sheet(d).png())
    return [target]
