"""E29-D02 positions and orders grid (SCR-063): WCAG contrast matrix over the real token JSON.

Standalone, offline, stdlib only. Resolves each theme (`dark`, `light`, `high-contrast`) with the
loader of `packages/ui/tokens/tests/verify_tokens.py` and measures every pair of
`docs/design/E29/E29-D02.md` §13 with `contrast_ratio()` of `docs/design/_tools/contrast_check.py`
(imported, not re-implemented), the method of `e13_d02_wires_audit.py`.

Usage: python3 -I docs/design/_tools/e29_d02_grid_audit.py   (prints Markdown; exit 1 on a FAIL)

Roles and bars (`05-accessibility-standard.md` §5): `text` 4.5:1, `non-text` 3:1. `rejected-*`
pairs are the ones the spec designed around: reported with the verdict they would get, never
gated. `decorative` pairs carry no meaning on their own: reported, never gated.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")

THEMES = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0, "rejected-text": 4.5, "rejected-non-text": 3.0}


def resolve_theme(name: str) -> dict[str, str]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    colours = {k: v for k, v in allt.items() if v.get("$type") == "color"}
    return {k: verify.resolve(v["$value"], allt) for k, v in colours.items()}


T = {n: resolve_theme(n) for n in THEMES}


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(theme: str, fg: str, bg: str) -> float:
    return float(
        contrast_check.contrast_ratio(rgb(T[theme]["color." + fg]), rgb(T[theme]["color." + bg]))
    )


# (element, fg, bg, role); token names without the leading "color.", in the order of §13.
PAIRS = [
    ("cell words and numerals", "text.primary", "surface.raised", "text"),
    ("same, hovered row", "text.primary", "surface.hover", "text"),
    ("same, selected row", "text.primary", "surface.selected", "text"),
    ("unit suffixes, secondary text, T2 reasons", "text.secondary", "surface.raised", "text"),
    ("same, selected row; T2 label there", "text.secondary", "surface.selected", "text"),
    ("T2 label and lock glyph", "text.tertiary", "surface.raised", "text"),
    ("T2 label, hovered row", "text.tertiary", "surface.hover", "text"),
    ("T2 menu item label", "text.tertiary", "surface.overlay", "text"),
    ("headers, tabs, toolbar labels", "text.secondary", "surface.canvas", "text"),
    ("group headers, active tab", "text.primary", "surface.canvas", "text"),
    ("totals rows", "text.primary", "surface.overlay", "text"),
    ("'as of' in the group header and the strip", "text.tertiary", "surface.canvas", "text"),
    ("side glyph and profit accent", "buy.default", "surface.raised", "non-text"),
    ("same, selected row", "buy.default", "surface.selected", "non-text"),
    ("side glyph and loss accent", "sell.default", "surface.raised", "non-text"),
    ("same, selected row", "sell.default", "surface.selected", "non-text"),
    ("Near glyph", "status.warning.strong", "surface.raised", "non-text"),
    ("same, selected row", "status.warning.strong", "surface.selected", "non-text"),
    ("Critical glyph and accent", "status.danger.strong", "surface.raised", "non-text"),
    ("same, selected row", "status.danger.strong", "surface.selected", "non-text"),
    ("environment pill border, LIVE", "env.live", "surface.raised", "non-text"),
    ("environment pill border, DEMO", "env.demo", "surface.raised", "non-text"),
    ("NO SL chip, lockout banner text", "text.primary", "status.danger.subtle", "text"),
    ("their glyph", "status.danger.strong", "status.danger.subtle", "non-text"),
    ("pending tag text", "text.primary", "status.info.subtle", "text"),
    ("pending glyph", "status.info.strong", "status.info.subtle", "non-text"),
    ("rejected line, desync banner text", "text.primary", "status.warning.subtle", "text"),
    ("their warning glyph", "status.warning.strong", "status.warning.subtle", "non-text"),
    ("focus ring on rows", "focus.ring", "surface.raised", "non-text"),
    ("focus ring, selected row", "focus.ring", "surface.selected", "non-text"),
    ("focus ring on the strip and toolbar", "focus.ring", "surface.canvas", "non-text"),
    ("focus ring on a warning fill", "focus.ring", "status.warning.subtle", "non-text"),
    ("focus ring on a danger fill", "focus.ring", "status.danger.subtle", "non-text"),
    ("SplitButton label", "text.primary", "action.secondary.default", "text"),
    ("stale row values", "data-confidence.stale.text", "data-confidence.stale.surface", "text"),
    ("focus ring on a SplitButton", "focus.ring", "action.secondary.default", "non-text"),
    ("active-tab rule", "border.selected", "surface.canvas", "non-text"),
    ("primary dialog button", "text.on-action", "action.primary.default", "text"),
    ("REJECTED coloured loss digits", "sell.default", "surface.raised", "rejected-text"),
    ("REJECTED profit digits, selected", "buy.default", "surface.selected", "rejected-text"),
    (
        "REJECTED danger.default glyph, selected",
        "status.danger.default",
        "surface.selected",
        "rejected-non-text",
    ),
    ("REJECTED tertiary text, selected row", "text.tertiary", "surface.selected", "rejected-text"),
    ("REJECTED disabled label (E09-D09 §2.2)", "text.disabled", "surface.raised", "rejected-text"),
    ("REJECTED selection fill alone", "surface.selected", "surface.raised", "rejected-non-text"),
    ("row separators", "border.subtle", "surface.raised", "decorative"),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failed = 0
    print("| Element | fg | bg | role | dark | light | hc | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for element, fg, bg, role in PAIRS:
        vals = [ratio(t, fg, bg) for t in THEMES]
        bar = BAR.get(role)
        bad = [THEMES[i] for i, v in enumerate(vals) if bar is not None and v < bar]
        verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
        if role.startswith("rejected") or bar is None:
            verdict = f"not gated ({verdict})" if bar else "decorative (not gated)"
        else:
            failed += int(bool(bad))
        cells = " | ".join(f"{v:.2f}" for v in vals)
        print(f"| {element} | `color.{fg}` | `color.{bg}` | {role} | {cells} | {verdict} |")
    stale = [T[t]["color.data-confidence.stale.surface"] for t in THEMES]
    print(f"\n`color.data-confidence.stale.surface` (dark, light, hc): {', '.join(stale)}")
    print(f"`color.overlay.stale` (CMP-078) present: {'color.overlay.stale' in T['dark']}")
    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
