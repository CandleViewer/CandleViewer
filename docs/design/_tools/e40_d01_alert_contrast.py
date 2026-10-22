#!/usr/bin/env python3
"""E40-D01: WCAG contrast of the alert-surface token pairs in dark, light and high-contrast.

Standalone, offline, no network. Resolves ``packages/ui/tokens/*.tokens.json`` layered per
``themes.json`` (later sets override earlier ones, ``{token.path}`` references followed) and applies
the formula of ``contrast_check.py`` (imported, not copied) to every pair the alert surfaces use
(``docs/design/a11y/e40-alerts-a11y-review.md`` §6). A pair is judged at 4.5:1 for text, 3:1 for
non-text UI, and 7:1 for text in the high-contrast theme (05 §5.6). A token missing in a theme is
reported as MISSING (a design-system change request), never guessed.

Usage: python3 -I docs/design/_tools/e40_d01_alert_contrast.py [--md] [--hex] [--candidates]
  --md   print the Markdown table used in the review; --hex also prints the resolved values;
  --candidates prints every blue primitive and ``palette.white`` against the high-contrast
  overlay / raised surfaces (DS-CR-1: which step, if any, reaches 7:1).
Exit 0 always: the review records the failing pairs as design-system change requests.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages/ui/tokens"
HC_TEXT_BAR = 7.0

_T, _S, _ST = "color.text.", "color.surface.", "color.status."
OVER, RAISED, CANVAS = _S + "overlay", _S + "raised", _S + "canvas"
FOCUS, ACTION = "color.focus.ring", "color.action.primary.default"
# (label, foreground token, background token, bar, kind) — one line per pair, in review order
PAIRS: list[tuple[str, str, str, float, str]] = [
    ("toast title", _T + "primary", OVER, 4.5, "text"),
    ("toast body", _T + "secondary", OVER, 4.5, "text"),
    ("toast timestamp", _T + "tertiary", OVER, 4.5, "text"),
    ("toast action link", _T + "link", OVER, 4.5, "text"),
    ("info glyph on toast", _ST + "info.strong", OVER, 3.0, "non-text"),
    ("warning glyph on toast", _ST + "warning.strong", OVER, 3.0, "non-text"),
    ("danger glyph on toast", _ST + "danger.strong", OVER, 3.0, "non-text"),
    ("success glyph on toast", _ST + "success.strong", OVER, 3.0, "non-text"),
    ("danger edge on toast", _ST + "danger.default", OVER, 3.0, "non-text"),
    ("warning edge on toast", _ST + "warning.default", OVER, 3.0, "non-text"),
    ("info edge on toast", _ST + "info.default", OVER, 3.0, "non-text"),
    ("success edge on toast", _ST + "success.default", OVER, 3.0, "non-text"),
    ("centre row title", _T + "primary", RAISED, 4.5, "text"),
    ("centre row body", _T + "secondary", RAISED, 4.5, "text"),
    ("centre row timestamp", _T + "tertiary", RAISED, 4.5, "text"),
    ("centre row link", _T + "link", RAISED, 4.5, "text"),
    ("disabled row text", _T + "disabled", RAISED, 4.5, "text"),
    ("failed glyph on row", _ST + "danger.strong", RAISED, 3.0, "non-text"),
    ("failed chip border", _ST + "danger.default", RAISED, 3.0, "non-text"),
    ("snoozed glyph on row", _ST + "warning.strong", RAISED, 3.0, "non-text"),
    ("selected row title", _T + "primary", _S + "selected", 4.5, "text"),
    ("hovered row title", _T + "primary", _S + "hover", 4.5, "text"),
    ("critical banner title", _T + "primary", _ST + "danger.subtle", 4.5, "text"),
    ("critical banner body", _T + "secondary", _ST + "danger.subtle", 4.5, "text"),
    ("critical banner glyph", _ST + "danger.strong", _ST + "danger.subtle", 3.0, "non-text"),
    ("warning banner title", _T + "primary", _ST + "warning.subtle", 4.5, "text"),
    ("warning banner body", _T + "secondary", _ST + "warning.subtle", 4.5, "text"),
    ("storm summary title", _T + "primary", _ST + "info.subtle", 4.5, "text"),
    ("matrix header", _T + "primary", CANVAS, 4.5, "text"),
    ("matrix cell label", _T + "secondary", CANVAS, 4.5, "text"),
    ("button label", _T + "on-action", ACTION, 4.5, "text"),
    ("focus ring on overlay", FOCUS, OVER, 3.0, "non-text"),
    ("focus ring on raised", FOCUS, RAISED, 3.0, "non-text"),
    ("focus ring on canvas", FOCUS, CANVAS, 3.0, "non-text"),
    ("focus ring on app", FOCUS, _S + "app", 3.0, "non-text"),
    ("focus ring on selected", FOCUS, _S + "selected", 3.0, "non-text"),
    ("focus ring on danger subtle", FOCUS, _ST + "danger.subtle", 3.0, "non-text"),
    ("focus ring on primary button", FOCUS, ACTION, 3.0, "non-text"),
    ("checkbox boundary (border.strong)", "color.border.strong", CANVAS, 3.0, "non-text"),
    ("checkbox boundary (text.tertiary)", _T + "tertiary", CANVAS, 3.0, "non-text"),
    ("row separator (border.default)", "color.border.default", RAISED, 3.0, "non-text"),
]


def load_contrast_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "contrast_check", Path(__file__).with_name("contrast_check.py")
    )
    if spec is None or spec.loader is None:
        raise SystemExit("contrast_check.py not found beside this tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_theme(theme: str) -> dict[str, str | None]:
    themes = json.loads((TOKENS / "themes.json").read_text(encoding="utf-8"))
    sets = next(t["sets"] for t in themes["themes"] if t["name"] == theme)
    merged: dict[str, dict[str, object]] = {}
    for name in sets:
        merged.update(json.loads((TOKENS / f"{name}.tokens.json").read_text(encoding="utf-8")))

    def value(token: str, depth: int = 0) -> str | None:
        entry = merged.get(token)
        if entry is None or depth > 12:
            return None
        raw = entry.get("$value")
        if isinstance(raw, str) and raw.startswith("{") and raw.endswith("}"):
            return value(raw[1:-1], depth + 1)
        return raw if isinstance(raw, str) else None

    return {k: value(k) for k in merged if k.startswith("color.")}


def hex_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def candidates(tool: object, hc: dict[str, str | None]) -> None:
    """DS-CR-1: every blue primitive and `palette.white` on the hc overlay / raised surfaces."""
    prim = json.loads((TOKENS / "primitives.tokens.json").read_text(encoding="utf-8"))
    names = sorted(k for k in prim if k.startswith("palette.blue.") or k == "palette.white")
    over, raised = hc.get(OVER), hc.get(RAISED)
    print("\n| Primitive | hex | on `surface.overlay` | on `surface.raised` | 7:1 |")
    print("| --- | --- | --- | --- | --- |")
    for name in names:
        value = prim[name].get("$value")
        if not isinstance(value, str) or not over or not raised:
            continue
        ratio = tool.contrast_ratio  # type: ignore[attr-defined]
        ratios = [ratio(hex_rgb(value), hex_rgb(bg)) for bg in (over, raised)]
        verdict = "pass" if min(ratios) >= HC_TEXT_BAR else "FAIL"
        print(f"| `{name}` | `{value}` | {ratios[0]:.2f} | {ratios[1]:.2f} | {verdict} |")


def main(argv: list[str]) -> int:
    tool = load_contrast_module()
    md, show_hex = "--md" in argv, "--hex" in argv
    themes = {t: resolve_theme(t) for t in ("dark", "light", "high-contrast")}
    if md:
        print("| Pair | fg → bg | dark | light | high-contrast | bar |")
        print("| --- | --- | --- | --- | --- | --- |")
    failures = 0
    for label, fg, bg, bar, kind in PAIRS:
        cells: list[str] = []
        for theme, tokens in themes.items():
            f, b = tokens.get(fg), tokens.get(bg)
            if not f or not b:
                cells.append("MISSING")
                failures += 1
                continue
            # contrast_check.py is loaded by path (it is a script, not a package), so mypy cannot
            # see its functions; the attribute exists (docs/design/_tools/contrast_check.py).
            ratio = tool.contrast_ratio(hex_rgb(f), hex_rgb(b))  # type: ignore[attr-defined]
            need = HC_TEXT_BAR if theme == "high-contrast" and kind == "text" else bar
            ok = ratio >= need
            failures += 0 if ok else 1
            cells.append(f"{ratio:.2f}" + ("" if ok else " FAIL"))
        if md:
            hc = " (7:1 hc)" if kind == "text" else ""
            print(
                f"| {label} | `{fg}` → `{bg}` | {cells[0]} | {cells[1]} | {cells[2]} | "
                f"{bar:g}:1 {kind}{hc} |"
            )
        else:
            print(f"{label:36s} {fg:30s} on {bg:30s} " + "  ".join(f"{c:>10s}" for c in cells))
    if show_hex:
        used = sorted({t for _, f, b, _, _ in PAIRS for t in (f, b)})
        print("\n| Token | dark | light | high-contrast |\n| --- | --- | --- | --- |")
        for token in used:
            print(f"| `{token}` | " + " | ".join(str(themes[t].get(token)) for t in themes) + " |")
    if not md:
        print("resolved tokens: " + ", ".join(f"{t}={len(v)}" for t, v in themes.items()))
        print(f"cells below their bar or missing: {failures}")
    if "--candidates" in argv:
        candidates(tool, themes["high-contrast"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
