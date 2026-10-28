"""Theme gate for an exported board PNG (boards review round 2, B-2).

Usage: ``python3 themegate.py <png> <dark|light>``

Counts the pixels that are exactly one of the three text colours of each theme (``color.text.primary``,
``.secondary`` and ``.tertiary``, resolved from ``packages/ui/tokens``) and fails when the other theme's
text colours exceed 10 % of the board's own. A board exported with the other theme's saved fills reads as
dark-on-dark or light-on-light and has more of the other theme's text pixels than its own. The 10 % margin
allows for light-theme borders that share #B1BAC4 with the dark theme's secondary text (4-5 % on a legible
light board). Exits 0 on PASS and 1 on FAIL.
"""

from __future__ import annotations

import sys

from PIL import Image

RGB = tuple[int, int, int]

DARK_TEXT: frozenset[RGB] = frozenset({(0xE8, 0xEA, 0xED), (0xB1, 0xBA, 0xC4), (0x8B, 0x94, 0x9E)})
LIGHT_TEXT: frozenset[RGB] = frozenset({(0x14, 0x17, 0x1A), (0x3A, 0x41, 0x48), (0x52, 0x5C, 0x66)})
MARGIN = 0.10


def count(png: str) -> tuple[int, int]:
    """Return (dark-theme text pixels, light-theme text pixels) of the PNG."""
    colours = Image.open(png).convert("RGB").getcolors(maxcolors=1 << 24) or []
    dark = sum(n for n, rgb in colours if rgb in DARK_TEXT)
    light = sum(n for n, rgb in colours if rgb in LIGHT_TEXT)
    return dark, light


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[2] not in ("dark", "light"):
        print("usage: themegate.py <png> <dark|light>", file=sys.stderr)
        return 2
    png, theme = argv[1], argv[2]
    dark, light = count(png)
    own, other = (dark, light) if theme == "dark" else (light, dark)
    ok = own > 0 and other <= MARGIN * own
    name = png.rsplit("/", 1)[-1]
    print(f"{'PASS' if ok else 'FAIL'} {name} theme={theme} own={own} other={other}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
