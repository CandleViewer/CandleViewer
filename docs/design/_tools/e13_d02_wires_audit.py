"""E13-D02 indicator-wireframe audit: WCAG contrast matrix over the real token JSON.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly
as `packages/ui/tokens/tests/verify_tokens.py` does (same loader, alias resolution and theme
layering from `themes.json`) and measures every foreground/background pair the greyscale
wireframes of `docs/design/E13/E13-D02.md` (SCR-034 / SCR-035 / SCR-036, CMP-199 / CMP-224) bind.
The contrast formula is `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported,
not re-implemented), so the numbers agree with E11-D02's, E30-D01's and E09-D03's.

The wireframes are greyscale, so there is no hue to simulate: no CVD section (the spec's §14 says
which states must stay non-colour when E13-D03 adds hue). The only non-neutral tokens measured are
the ones D03 inherits unchanged (`color.focus.ring`, the status `subtle`/`strong` pairs), reported
with their bar but not gated (`d03-*` roles), so D03 starts from measured numbers.

Usage: python3 -I docs/design/_tools/e13_d02_wires_audit.py   (prints Markdown; exit 1 on a FAIL)
Stdout is forced to UTF-8 (the tables carry `≥` and `—`), so it also runs on a cp1252 console.

Roles and bars (`05-accessibility-standard.md` §5): `text` 4.5:1, `non-text` 3:1, `hc-text` 7:1
(gated on the high-contrast column only), `decorative` (carries no meaning on its own; reported,
never gated), `rejected-*` (pairs the spec considered and designed around; reported with the
verdict they would get, never gated), `d03-*` (inherited by E13-D03; reported, never gated).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")

THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {
    "text": 4.5,
    "non-text": 3.0,
    "hc-text": 7.0,
    "decorative": None,
    "rejected-text": 4.5,
    "rejected-non-text": 3.0,
    "d03-text": 4.5,
    "d03-non-text": 3.0,
}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg))


def resolve_theme(name: str) -> dict[str, str]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    colours = {k: v for k, v in allt.items() if v.get("$type") == "color"}
    return {k: verify.resolve(v["$value"], allt) for k, v in colours.items()}


T = {n: resolve_theme(n) for n in THEMES}

# Short names for the tokens the wireframes bind (the spec's §13 lists the same map).
TOK = {
    "app": "color.surface.app",
    "canvas": "color.surface.canvas",
    "raised": "color.surface.raised",
    "overlay": "color.surface.overlay",
    "sunken": "color.surface.sunken",
    "hover": "color.surface.hover",
    "selected": "color.surface.selected",
    "b.subtle": "color.border.subtle",
    "b.default": "color.border.default",
    "b.strong": "color.border.strong",
    "t.primary": "color.text.primary",
    "t.secondary": "color.text.secondary",
    "t.tertiary": "color.text.tertiary",
    "t.disabled": "color.text.disabled",
    "focus": "color.focus.ring",
    "danger.subtle": "color.status.danger.subtle",
    "danger.strong": "color.status.danger.strong",
    "warning.subtle": "color.status.warning.subtle",
    "warning.strong": "color.status.warning.strong",
}


def col(theme: str, short: str) -> str:
    return T[theme][TOK[short]]


# (element, fg, bg, role) — fg/bg are the short names above.
PAIRS: list[tuple[str, str, str, str]] = [
    # --- text on the dialog / drawer surface (CMP-043, CMP-046: color.surface.overlay) ---
    ("dialog / drawer title, labels, values, validation text", "t.primary", "overlay", "text"),
    ("dialog / drawer primary text — hc AAA target", "t.primary", "overlay", "hc-text"),
    ("hints, descriptions, pane target, empty-state body", "t.secondary", "overlay", "text"),
    ("kickers, footers, 'store pending' notes, group counts", "t.tertiary", "overlay", "text"),
    ("disabled label — REJECTED (exempt)", "t.disabled", "overlay", "rejected-text"),
    # --- text on list rows, cards, chips, kbd (color.surface.raised) ---
    ("catalogue entry name, tree item label, card title", "t.primary", "raised", "text"),
    ("catalogue entry text — hc AAA target", "t.primary", "raised", "hc-text"),
    ("entry secondary text and tags ('On chart' …)", "t.secondary", "raised", "text"),
    ("kbd caps, count chip (CMP-224) text", "t.primary", "raised", "text"),
    # --- hovered, selected, header rows ---
    ("hovered row text", "t.primary", "hover", "text"),
    ("hovered row secondary text / tag", "t.secondary", "hover", "text"),
    ("tree group header, bulk-action bar, table header text", "t.primary", "hover", "text"),
    ("selected row / selected tab text", "t.primary", "selected", "text"),
    ("selected row secondary text", "t.secondary", "selected", "text"),
    # --- preview tile (CMP-228: color.surface.sunken) ---
    ("preview caption ('Preview: last 200 bars, display-only')", "t.secondary", "sunken", "text"),
    ("preview axis labels", "t.tertiary", "sunken", "text"),
    # --- legend rows on the chart canvas (CMP-199, E11-D02 D12) ---
    ("legend label, pane label", "t.primary", "canvas", "text"),
    ("legend label — hc AAA target", "t.primary", "canvas", "hc-text"),
    ("legend value, '34 more bars needed', 'computing…'", "t.secondary", "canvas", "text"),
    ("hidden legend row label (E11-D02 D12)", "t.tertiary", "canvas", "text"),
    # --- non-text: control boundaries ---
    ("field / control border as drawn (wires)", "t.tertiary", "overlay", "non-text"),
    ("field border — REJECTED color.border.default", "b.default", "overlay", "rejected-non-text"),
    ("field border — REJECTED color.border.strong", "b.strong", "overlay", "rejected-non-text"),
    ("tree selection outline, bulk bar edge", "t.tertiary", "overlay", "non-text"),
    # --- non-text: icon-only controls (eye, lock, rename, menu, delete, star, clear, close) ---
    ("icon glyph on the dialog / drawer surface", "t.secondary", "overlay", "non-text"),
    ("icon glyph on a raised row", "t.secondary", "raised", "non-text"),
    ("icon glyph on a hovered row", "t.secondary", "hover", "non-text"),
    ("drag-handle grip, disclosure chevron", "t.tertiary", "overlay", "non-text"),
    ("selected-tab underline, pressed check glyph", "t.primary", "selected", "non-text"),
    # --- non-text: focus ring (greyscale stand-in; the real token is D03's) ---
    ("focus ring stand-in (2 px t.primary) on overlay", "t.primary", "overlay", "non-text"),
    ("focus ring stand-in on a raised row", "t.primary", "raised", "non-text"),
    ("focus ring stand-in on the canvas (legend row)", "t.primary", "canvas", "non-text"),
    ("D03 inherits: color.focus.ring on overlay", "focus", "overlay", "d03-non-text"),
    ("D03 inherits: color.focus.ring on raised", "focus", "raised", "d03-non-text"),
    ("D03 inherits: color.focus.ring on canvas", "focus", "canvas", "d03-non-text"),
    ("D03 inherits: color.focus.ring on selected", "focus", "selected", "d03-non-text"),
    # --- non-text: preview tile marks ---
    ("preview primary series line", "t.secondary", "sunken", "non-text"),
    ("preview secondary output (dashed line, histogram)", "t.tertiary", "sunken", "non-text"),
    ("first-valid-bar marker (dashed vertical)", "t.secondary", "sunken", "non-text"),
    ("legend swatch shape (line / bar / glyph)", "t.secondary", "canvas", "non-text"),
    ("hidden legend swatch", "t.tertiary", "canvas", "non-text"),
    # --- decorative (carry no meaning on their own; the text or shape beside them does) ---
    ("selection fill vs raised row (aria-selected carries it)", "selected", "raised", "decorative"),
    ("hover fill vs raised row", "hover", "raised", "decorative"),
    ("group separators, indent guides", "b.default", "overlay", "decorative"),
    ("card outline", "b.default", "raised", "decorative"),
    ("dialog edge vs the app shell", "b.strong", "app", "decorative"),
    ("warm-up zone hatch in the preview (labelled)", "b.strong", "sunken", "decorative"),
    ("skeleton blocks", "hover", "overlay", "decorative"),
    # --- D03 inherits: the status pairs the validation and 'used by rules' states will take ---
    ("D03 inherits: inline error band text", "t.primary", "danger.subtle", "d03-text"),
    ("D03 inherits: error icon on overlay", "danger.strong", "overlay", "d03-non-text"),
    ("D03 inherits: 'used by rules' callout text", "t.primary", "warning.subtle", "d03-text"),
    ("D03 inherits: callout icon on overlay", "warning.strong", "overlay", "d03-non-text"),
]


def verdict_for(role: str, vals: list[float]) -> tuple[str, bool]:
    """The verdict cell and whether the row counts as a gated failure."""
    bar = BAR[role]
    if bar is None:
        return "decorative (not gated)", False
    if role == "hc-text":
        bad = ["high-contrast"] if vals[2] < bar else []
    else:
        bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
    verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
    if role.startswith("rejected"):
        if bad:
            return "rejected by design — would " + verdict, False
        return "rejected by design (passes; unused)", False
    if role.startswith("d03"):
        return "D03 inherits — " + verdict + " (not gated here)", False
    return verdict, bool(bad)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the reference machine's console is cp1252
    failed = 0
    print("## A. Contrast matrix (ratio per theme; bar per role)\n")
    print("| Element | fg | bg | role | dark | light | hc | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for element, fg, bg, role in PAIRS:
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        verdict, bad = verdict_for(role, vals)
        failed += int(bad)
        cells = f"{vals[0]:.2f} | {vals[1]:.2f} | {vals[2]:.2f}"
        print(f"| {element} | `{TOK[fg]}` | `{TOK[bg]}` | {role} | {cells} | {verdict} |")

    print("\n## B. Resolved values used above\n")
    print("| token | dark | light | hc |")
    print("|---|---|---|---|")
    seen: list[str] = []
    for _, fg, bg, _ in PAIRS:
        for short in (fg, bg):
            if short not in seen:
                seen.append(short)
    for short in seen:
        values = " | ".join(col(t, short) for t in THEMES)
        print(f"| `{TOK[short]}` | {values} |")

    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
