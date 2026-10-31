#!/usr/bin/env python3
"""E04-D02 contrast audit: every token pair the observability / health surfaces draw.

Standalone, offline, stdlib only. Covers CMP-076 ConnectionStatus, CMP-077 ReconnectOverlay (the
connection region), CMP-092 DegradedModeBanner, CMP-178 SystemHealthTile, CMP-207 BuildFooter and
CMP-208 / CMP-210 (status bar latency / health chips). Pairs come from the `Tokens` lines of
`docs/plan/15-component-catalogue.md` and from the built styles in
`apps/web/src/features/app-shell/{ConnectionStatus,ConnectionRegion,StatusBar}.tsx` and
`apps/web/src/features/system-states/DegradedModeBanner.tsx`; each row says whether the surface is
built or spec-level. The table is regenerated on every run, never hand-typed (BQ-21).

Themes resolve as `packages/ui/tokens/themes.json` declares and as `loadResolvedThemes()` in
`packages/ui/scripts/build-tokens.mjs` layers them: dark = primitives + semantic-dark, light =
dark + semantic-light, high-contrast = dark + the hc overlay (semantic-hc). The ratio is the WCAG
2.x one of `tools/contrast/color-math.mjs` (6-digit hex, any alpha digits ignored, unrounded
ratio compared with `>=`, as `tools/contrast/generate.mjs` does). Bars: text 4.5, large text 3,
non-text 3. The hc column also reports the informational 7:1 bar of `05-accessibility-standard.md`
section 5 (the gate stays at the use bar). Registration is a textual scan of
`tools/contrast/pairs.mjs`. The "distinct ink per severity" table lists the resolved hex of each
`color.status.*.strong` per theme and flags severities that share one ink (a colour identity).

#5134 cross-reference: four light-theme pairs fell under their bar at da578081 (text 3.85 / 4.11 /
4.34, and the non-text 2.78 glyph); #5140 (370eac31) fixed them. The guard pins those four pairs at
their post-#5140 values (text 6.33 / 4.90 / 5.30, non-text 3.84). Failures are findings, not script
errors; `--check` only guards that those four ratios are still what the table computes, so it
proves the table was regenerated against the current tokens and cannot pass as typed.

Usage: python3 -I docs/design/_tools/e04_d02_contrast_audit.py           (Markdown)
       python3 -I docs/design/_tools/e04_d02_contrast_audit.py --json    (JSON)
       python3 -I docs/design/_tools/e04_d02_contrast_audit.py --check   (exit 1 on drift)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PAIRS_MJS = ROOT / "tools" / "contrast" / "pairs.mjs"
PRIM, DARK, LIGHT, HC = (
    "primitives.tokens.json",
    "semantic-dark.tokens.json",
    "semantic-light.tokens.json",
    "semantic-hc.tokens.json",
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": (PRIM, DARK),
    "light": (PRIM, DARK, LIGHT),
    "high-contrast": (PRIM, DARK, HC),
}
BAR = {"text": 4.5, "large": 3.0, "non-text": 3.0}
HC_BAR = 7.0
HEX = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
SEVERITIES = ("success", "info", "warning", "danger")

CONN = "ConnectionStatus.tsx"
REGION = "ConnectionRegion.tsx"
BAR_TSX = "StatusBar.tsx"
BANNER = "DegradedModeBanner.tsx"

# fg | bg | use | surface | built-or-spec   (rows with the same fg/bg/use are merged)
PAIRS_TABLE = """
color.text.primary | color.surface.raised | text | CMP-076 chip word, live/stale | built ConnectionStatus
color.data-confidence.live.indicator | color.surface.raised | non-text | CMP-076 live glyph | built ConnectionStatus
color.data-confidence.stale.indicator | color.surface.raised | non-text | CMP-076 stale glyph; CMP-178 stale | built ConnectionStatus; spec CMP-178
color.text.primary | color.status.info.subtle | text | CMP-076 delayed chip word | built ConnectionStatus
color.status.info.default | color.status.info.subtle | non-text | CMP-076 delayed glyph | built ConnectionStatus
color.text.primary | color.status.warning.subtle | text | CMP-076 stale T2 chip word | built ConnectionStatus
color.status.warning.strong | color.status.warning.subtle | non-text | CMP-076 T2 glyph; CMP-077 read-only border and glyph; CMP-092 warning glyph | built ConnectionStatus; built ConnectionRegion; built DegradedModeBanner
color.text.primary | color.status.danger.subtle | text | CMP-076 offline / reconnecting word; CMP-077 title | built ConnectionStatus; built ConnectionRegion
color.status.danger.strong | color.status.danger.subtle | non-text | CMP-076 glyph; CMP-077 border and glyph; CMP-092 danger glyph | built ConnectionStatus; built ConnectionRegion; spec DegradedModeBanner
color.status.danger.strong | color.status.danger.subtle | text | CMP-077 age line from 30 s; CMP-092 danger tone label | built ConnectionRegion; built DegradedModeBanner
color.text.secondary | color.status.danger.subtle | text | CMP-077 body lines | built ConnectionRegion
color.text.primary | color.status.warning.subtle | text | CMP-077 read-only title; CMP-092 warning message | built ConnectionRegion; built DegradedModeBanner
color.text.secondary | color.status.warning.subtle | text | CMP-077 read-only body; CMP-092 stillWorks | built ConnectionRegion; built DegradedModeBanner
color.status.warning.strong | color.status.warning.subtle | text | CMP-092 warning tone label | built DegradedModeBanner
color.text.inverse | color.status.danger.strong | text | CMP-077 long-outage title and body | built ConnectionRegion
color.text.inverse | color.status.danger.strong | non-text | CMP-077 long-outage border and glyph | built ConnectionRegion
color.text.primary | color.status.info.subtle | text | CMP-092 info message | built DegradedModeBanner
color.text.secondary | color.status.info.subtle | text | CMP-092 info stillWorks | built DegradedModeBanner
color.status.info.strong | color.status.info.subtle | text | CMP-092 info tone label | built DegradedModeBanner
color.status.info.strong | color.status.info.subtle | non-text | CMP-092 info glyph | built DegradedModeBanner
color.text.primary | color.status.danger.subtle | text | CMP-092 danger message | built DegradedModeBanner
color.text.secondary | color.status.danger.subtle | text | CMP-092 danger stillWorks | built DegradedModeBanner
color.focus.ring | color.status.danger.subtle | non-text | CMP-077 / CMP-092 focus ring | spec ConnectionRegion; spec DegradedModeBanner
color.focus.ring | color.status.warning.subtle | non-text | CMP-092 dismiss focus ring | spec DegradedModeBanner
color.focus.ring | color.surface.raised | non-text | CMP-076 chip focus ring | spec ConnectionStatus
color.text.primary | color.surface.hover | text | CMP-076 chip hover | spec ConnectionStatus
color.border.default | color.surface.raised | non-text | CMP-076 chip hairline border | built ConnectionStatus
color.text.primary | color.surface.sunken | text | CMP-208 bar text; CMP-210 chip word | built StatusBar
color.text.secondary | color.surface.sunken | text | CMP-208 latency value; CMP-210 none-tone ink | built StatusBar
color.text.tertiary | color.surface.sunken | text | CMP-208 tertiary items | built StatusBar
color.status.success.strong | color.surface.sunken | non-text | CMP-210 ok glyph | built StatusBar
color.status.warning.strong | color.surface.sunken | non-text | CMP-210 warn glyph | built StatusBar
color.status.danger.strong | color.surface.sunken | non-text | CMP-210 error glyph | built StatusBar
color.text.secondary | color.surface.sunken | non-text | CMP-210 none-tone glyph | built StatusBar
color.text.primary | color.surface.raised | text | CMP-178 tile value | spec CMP-178
color.text.secondary | color.surface.raised | text | CMP-178 label | spec CMP-178
color.text.tertiary | color.surface.raised | text | CMP-178 caption | spec CMP-178
color.status.success.strong | color.surface.raised | non-text | CMP-178 ok mark | spec CMP-178
color.status.warning.strong | color.surface.raised | non-text | CMP-178 warn mark | spec CMP-178
color.status.danger.strong | color.surface.raised | non-text | CMP-178 error mark | spec CMP-178
color.neutral.default | color.surface.raised | non-text | CMP-178 neutral mark | spec CMP-178
color.text.secondary | color.surface.app | text | CMP-207 build footer text | spec CMP-207
"""


class Row(TypedDict):
    fg: str
    bg: str
    use: str
    threshold: float
    surface: str
    ratios: dict[str, float | None]
    verdicts: dict[str, str]
    hc_7: str
    registered: str


Tokens = dict[str, dict[str, object]]


def load(name: str) -> Tokens:
    return cast(Tokens, json.loads((TOKENS / name).read_text(encoding="utf-8")))


def merged(files: tuple[str, ...]) -> Tokens:
    out: Tokens = {}
    for f in files:
        out.update(load(f))
    return out


def resolve(value: object, tokens: Tokens, seen: frozenset[str] = frozenset()) -> object:
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in seen or ref not in tokens:
            raise KeyError(f"unresolved or circular alias: {ref}")
        return resolve(tokens[ref]["$value"], tokens, seen | {ref})
    return value


def hex_of(name: str, tokens: Tokens) -> str | None:
    if name not in tokens:
        return None
    value = resolve(tokens[name]["$value"], tokens)
    return value if isinstance(value, str) and HEX.match(value) else None


def luminance(h: str) -> float:
    def chan(c: int) -> float:
        x = c / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def registered() -> dict[tuple[str, str], list[str]]:
    """Textual scan of pairs.mjs: (fg, bg) -> the threshold identifiers it is registered at."""
    text = PAIRS_MJS.read_text(encoding="utf-8")
    out: dict[tuple[str, str], list[str]] = {}
    for fg, bg, th in re.findall(
        r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)",\s*threshold:\s*THRESHOLD\.(\w+)', text
    ):
        out.setdefault((fg, bg), []).append(th)
    return out


def pair_specs() -> list[tuple[str, str, str, str]]:
    merged_rows: dict[tuple[str, str, str], list[str]] = {}
    for ln in PAIRS_TABLE.strip().splitlines():
        fg, bg, use, what, state = (c.strip() for c in ln.split(" | "))
        parts = [s.strip() for s in state.split(";")]
        merged_rows.setdefault((fg, bg, use), []).append(f"{what} [{', '.join(parts)}]")
    return [(fg, bg, use, " / ".join(w)) for (fg, bg, use), w in merged_rows.items()]


def measure(themes: dict[str, Tokens]) -> list[Row]:
    reg = registered()
    out: list[Row] = []
    for fg, bg, use, surface in pair_specs():
        bar = BAR[use]
        ratios: dict[str, float | None] = {}
        verdicts: dict[str, str] = {}
        for t, tokens in themes.items():
            a, b = hex_of(fg, tokens), hex_of(bg, tokens)
            r = contrast(a, b) if a and b else None
            ratios[t] = r
            verdicts[t] = "MISSING" if r is None else ("PASS" if r >= bar else "FAIL")
        hc = ratios["high-contrast"]
        ths = reg.get((fg, bg))
        out.append(
            {
                "fg": fg,
                "bg": bg,
                "use": use,
                "threshold": bar,
                "surface": surface,
                "ratios": ratios,
                "verdicts": verdicts,
                "hc_7": "n/a" if hc is None else ("yes" if hc >= HC_BAR else "no"),
                "registered": "no" if not ths else "yes (" + ",".join(sorted(set(ths))) + ")",
            }
        )
    return out


def inks(themes: dict[str, Tokens]) -> dict[str, dict[str, str | None]]:
    return {
        t: {s: hex_of(f"color.status.{s}.strong", tokens) for s in SEVERITIES}
        for t, tokens in themes.items()
    }


def identities(ink: dict[str, dict[str, str | None]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for t, by in ink.items():
        groups: dict[str, list[str]] = {}
        for s, h in by.items():
            if h:
                groups.setdefault(h.upper(), []).append(s)
        out += [{"theme": t, "hex": h, "severities": s} for h, s in groups.items() if len(s) > 1]
    return out


def summary(rows: list[Row], ids: list[dict[str, object]]) -> dict[str, int]:
    def failing(uses: tuple[str, ...]) -> int:
        return sum(1 for r in rows if r["use"] in uses and "FAIL" in r["verdicts"].values())

    return {
        "pairs": len(rows),
        "fail-text": failing(("text", "large")),
        "fail-nontext": failing(("non-text",)),
        "unregistered": sum(1 for r in rows if r["registered"] == "no"),
        "ink-identities": len(ids),
    }


#: The #5134 pairs, light theme, pinned at their post-#5140 values (fixed by #5140 at 370eac31;
#: pre-fix 3.85 / 4.11 / 4.34 / 2.78): (fg, bg, use) -> expected ratio, rounded to the hundredth.
GUARD: dict[tuple[str, str, str], float] = {
    ("color.status.danger.strong", "color.status.danger.subtle", "text"): 6.33,
    ("color.status.warning.strong", "color.status.warning.subtle", "text"): 4.90,
    ("color.status.info.strong", "color.status.info.subtle", "text"): 5.30,
    ("color.status.success.strong", "color.surface.sunken", "non-text"): 3.84,
}


def check(rows: list[Row]) -> list[str]:
    bad: list[str] = []
    for (fg, bg, use), want in GUARD.items():
        hit = [r for r in rows if (r["fg"], r["bg"], r["use"]) == (fg, bg, use)]
        got = hit[0]["ratios"]["light"] if hit else None
        if got is None or round(got, 2) != want:
            bad.append(f"{fg} on {bg} ({use}, light): expected {want}, got {got}")
    return bad


def fmt(r: float | None) -> str:
    return "MISSING" if r is None else f"{r:.2f}"


def markdown(rows: list[Row], ink: dict[str, dict[str, str | None]], s: dict[str, int]) -> str:
    ln = [
        (
            "| fg | bg | use | threshold | dark | light | hc | hc>=7:1 (info) | verdict "
            "(dark / light / hc) | in pairs.mjs | surface |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        rt, v = r["ratios"], r["verdicts"]
        ln.append(
            f"| `{r['fg']}` | `{r['bg']}` | {r['use']} | {r['threshold']:g} | {fmt(rt['dark'])} "
            f"| {fmt(rt['light'])} | {fmt(rt['high-contrast'])} | {r['hc_7']} | "
            f"{v['dark']} / {v['light']} / {v['high-contrast']} | {r['registered']} "
            f"| {r['surface']} |"
        )
    ln += ["", "Distinct ink per severity (`color.status.*.strong`):", ""]
    ln += ["| theme | " + " | ".join(SEVERITIES) + " | identities |", "|---|---|---|---|---|---|"]
    for t, by in ink.items():
        shared = [x for x in identities({t: by})]
        flag = "; ".join(f"{'=='.join(cast(list[str], x['severities']))}" for x in shared)
        ln.append(
            f"| {t} | " + " | ".join(f"`{by[x]}`" for x in SEVERITIES) + f" | {flag or '-'} |"
        )
    ln += [
        "",
        "pairs {pairs}; fail-text {fail-text}; fail-nontext {fail-nontext}; "
        "unregistered {unregistered}; ink-identities {ink-identities}".format(**s),
    ]
    return "\n".join(ln)


def main(argv: list[str]) -> int:
    themes = {t: merged(files) for t, files in THEMES.items()}
    rows = measure(themes)
    ink = inks(themes)
    ids = identities(ink)
    s = summary(rows, ids)
    if "--check" in argv:
        bad = check(rows)
        print("\n".join(bad) if bad else "check: the four #5134 ratios match the computed table")
        return 1 if bad else 0
    if "--json" in argv:
        print(json.dumps({"rows": rows, "inks": ink, "identities": ids, "summary": s}, indent=2))
        return 0
    print(markdown(rows, ink, s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
