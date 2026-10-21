#!/usr/bin/env python3
"""E40-D01: WCAG contrast of the alert-surface token pairs in dark, light and high-contrast.

Standalone, offline, no network. Resolves ``packages/ui/tokens/*.tokens.json`` layered per
``themes.json`` (later sets override earlier ones, ``{token.path}`` references followed) and applies
the formula of ``contrast_check.py`` (imported, not copied) to every pair the alert surfaces use
(``docs/design/a11y/e40-alerts-a11y-review.md`` §6). A pair is judged at 4.5:1 for text, 3:1 for
non-text UI, and 7:1 for text in the high-contrast theme (05 §5.6). A token missing in a theme is
reported as MISSING (a design-system change request), never guessed.

Usage: python3 -I docs/design/_tools/e40_d01_alert_contrast.py [--md] [--hex]
  --md   print the Markdown table used in the review; --hex also prints the resolved values.
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

# (label, foreground token, background token, bar, kind)
PAIRS: list[tuple[str, str, str, float, str]] = [
    ("toast title", "color.text.primary", "color.surface.overlay", 4.5, "text"),
    ("toast body", "color.text.secondary", "color.surface.overlay", 4.5, "text"),
    ("toast timestamp", "color.text.tertiary", "color.surface.overlay", 4.5, "text"),
    ("toast action link", "color.text.link", "color.surface.overlay", 4.5, "text"),
    ("info glyph on toast", "color.status.info.strong", "color.surface.overlay", 3.0, "non-text"),
    (
        "warning glyph on toast",
        "color.status.warning.strong",
        "color.surface.overlay",
        3.0,
        "non-text",
    ),
    (
        "danger glyph on toast",
        "color.status.danger.strong",
        "color.surface.overlay",
        3.0,
        "non-text",
    ),
    (
        "success glyph on toast",
        "color.status.success.strong",
        "color.surface.overlay",
        3.0,
        "non-text",
    ),
    (
        "danger edge on toast",
        "color.status.danger.default",
        "color.surface.overlay",
        3.0,
        "non-text",
    ),
    (
        "warning edge on toast",
        "color.status.warning.default",
        "color.surface.overlay",
        3.0,
        "non-text",
    ),
    ("info edge on toast", "color.status.info.default", "color.surface.overlay", 3.0, "non-text"),
    (
        "success edge on toast",
        "color.status.success.default",
        "color.surface.overlay",
        3.0,
        "non-text",
    ),
    ("centre row title", "color.text.primary", "color.surface.raised", 4.5, "text"),
    ("centre row body", "color.text.secondary", "color.surface.raised", 4.5, "text"),
    ("centre row timestamp", "color.text.tertiary", "color.surface.raised", 4.5, "text"),
    ("centre row link", "color.text.link", "color.surface.raised", 4.5, "text"),
    ("disabled row text", "color.text.disabled", "color.surface.raised", 4.5, "text"),
    ("failed glyph on row", "color.status.danger.strong", "color.surface.raised", 3.0, "non-text"),
    ("failed chip border", "color.status.danger.default", "color.surface.raised", 3.0, "non-text"),
    (
        "snoozed glyph on row",
        "color.status.warning.strong",
        "color.surface.raised",
        3.0,
        "non-text",
    ),
    ("selected row title", "color.text.primary", "color.surface.selected", 4.5, "text"),
    ("hovered row title", "color.text.primary", "color.surface.hover", 4.5, "text"),
    ("critical banner title", "color.text.primary", "color.status.danger.subtle", 4.5, "text"),
    ("critical banner body", "color.text.secondary", "color.status.danger.subtle", 4.5, "text"),
    (
        "critical banner glyph",
        "color.status.danger.strong",
        "color.status.danger.subtle",
        3.0,
        "non-text",
    ),
    ("warning banner title", "color.text.primary", "color.status.warning.subtle", 4.5, "text"),
    ("warning banner body", "color.text.secondary", "color.status.warning.subtle", 4.5, "text"),
    ("storm summary title", "color.text.primary", "color.status.info.subtle", 4.5, "text"),
    ("matrix header", "color.text.primary", "color.surface.canvas", 4.5, "text"),
    ("matrix cell label", "color.text.secondary", "color.surface.canvas", 4.5, "text"),
    ("button label", "color.text.on-action", "color.action.primary.default", 4.5, "text"),
    ("focus ring on overlay", "color.focus.ring", "color.surface.overlay", 3.0, "non-text"),
    ("focus ring on raised", "color.focus.ring", "color.surface.raised", 3.0, "non-text"),
    ("focus ring on canvas", "color.focus.ring", "color.surface.canvas", 3.0, "non-text"),
    ("focus ring on app", "color.focus.ring", "color.surface.app", 3.0, "non-text"),
    ("focus ring on selected", "color.focus.ring", "color.surface.selected", 3.0, "non-text"),
    (
        "focus ring on danger subtle",
        "color.focus.ring",
        "color.status.danger.subtle",
        3.0,
        "non-text",
    ),
    (
        "focus ring on primary button",
        "color.focus.ring",
        "color.action.primary.default",
        3.0,
        "non-text",
    ),
    (
        "checkbox boundary (border.strong)",
        "color.border.strong",
        "color.surface.canvas",
        3.0,
        "non-text",
    ),
    (
        "checkbox boundary (text.tertiary)",
        "color.text.tertiary",
        "color.surface.canvas",
        3.0,
        "non-text",
    ),
    (
        "row separator (border.default)",
        "color.border.default",
        "color.surface.raised",
        3.0,
        "non-text",
    ),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
