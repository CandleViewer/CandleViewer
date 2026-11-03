"""themegate.py <png> dark|light|hc: is an exported board in the theme it claims?

Counts pixels in each theme's text colours (from packages/ui tokens as drawn):
dark text #E8EAED; light texts #14171A / #3A4148 / #525C66; hc primary #F6F8FA.
dark : PASS if dark-text >= 300 and >= 5x light-text pixels.
light: PASS if light-text >= 300 and >= 5x dark-text pixels.
hc   : PASS if hc-primary > 500 and > 10x light-text pixels.
"""
import sys
from PIL import Image

DARK = {(0xE8, 0xEA, 0xED)}
LIGHT = {(0x14, 0x17, 0x1A), (0x3A, 0x41, 0x48), (0x52, 0x5C, 0x66)}
HC = {(0xF6, 0xF8, 0xFA)}


def count(colours: list[tuple[int, tuple[int, int, int]]], want: set[tuple[int, int, int]]) -> int:
    return sum(n for n, rgb in colours if rgb in want)


def main() -> int:
    path, theme = sys.argv[1], sys.argv[2]
    colours = Image.open(path).convert("RGB").getcolors(1 << 24) or []
    d, lt, h = count(colours, DARK), count(colours, LIGHT), count(colours, HC)
    name = path.rsplit("/", 1)[-1]
    if theme == "dark":
        ok, own, other = d >= 300 and d >= 5 * max(lt, 1), d, lt
    elif theme == "light":
        ok, own, other = lt >= 300 and lt >= 5 * max(d, 1), lt, d
    else:
        ok, own, other = h > 500 and h > 10 * max(lt, 1), h, lt
    print(f"{'PASS' if ok else 'FAIL'} {name} theme={theme} own={own} other={other}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
