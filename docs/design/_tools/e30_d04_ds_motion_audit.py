"""E30-D04 audit: the trading-ticket design-system and motion spec (docs/design/E30/E30-D04.md).

Offline, stdlib only; every number the spec and its boards show is computed here, never typed:
(1) token existence for every token name the spec binds (an absent name must be a CR row in
section 3.2 or a cited C-row in section 29); (2) the WCAG matrix with `contrast_check`'s
`contrast_ratio()` over the token JSON resolved as `packages/ui/tokens/tests/verify_tokens.py`
resolves it, plus the disabled-look and rejected-M1 composites (reported, not gated) and the
highlight composite;
(3) CVD dE76 rows; (4) the flash audit; (5) the motion-table, one-treatment, disabled-look,
view-as and structure gates; (6) hygiene. E30-D02 section 15.1's pairs are reproduced exactly.

Usage: python3 -I docs/design/_tools/e30_d04_ds_motion_audit.py [--json] [--spec <path>]
Exit 1 only on a gated FAIL.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
E30 = ROOT / "docs" / "design" / "E30"
THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float | None] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "decorative": None}
BAR["reported"] = None
FAILS: list[str] = []
FILES = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")


def resolve_theme(name: str) -> dict[str, str]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {
        k: str(verify.resolve(v["$value"], allt))
        for k, v in allt.items()
        if v.get("$type") == "color"
    }


T = {n: resolve_theme(n) for n in THEMES}
RAW = {f: json.loads((TOKENS / f"{f}.tokens.json").read_text(encoding="utf-8")) for f in FILES}
ALL = {k for d in RAW.values() for k in d if not k.startswith("$")}
COUNTS = {f: len([k for k in d if not k.startswith("$")]) for f, d in RAW.items()}


def col(theme: str, short: str) -> str:
    return T[theme]["color." + short]


def rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def ratio(fg: str, bg: str) -> float:
    return float(contrast.contrast_ratio(rgb(fg), rgb(bg)))


def over(fg: str, bg: str, a: float) -> str:  # fg composited over bg at opacity a
    return "#" + "".join(
        f"{round(a * x + (1 - a) * y):02X}" for x, y in zip(rgb(fg), rgb(bg), strict=True)
    )


def grey(h: str) -> str:  # cvd_sim.py's to_greyscale: Rec. 601 luma, floored
    r, g, b = rgb(h)
    return "#" + f"{max(0, min(255, int(0.299 * r + 0.587 * g + 0.114 * b))):02X}" * 3


# ---- the matrix: element | fg | bg | role (token names without the `color.` prefix) ----
PAIRS = """\
ARMED pill text (D02 :474 reproduced)|text.primary|status.warning.subtle|text
LOCKED / UNKNOWN pill text (D02 :475)|text.primary|surface.raised|text
value-change highlight pair; CMP-158 note (D02 :481)|text.primary|status.info.subtle|text
BUY side / submit label (D02 D3)|text.inverse|buy.default|text
SELL side / submit label (D02 D3; O-A)|text.inverse|sell.default|text
BUY label AAA stretch (gated in hc only)|text.inverse|buy.default|hc-text
SELL label AAA stretch (gated in hc only)|text.inverse|sell.default|hc-text
T2 label + lock glyph on the control fill (E09-D09 :292)|text.tertiary|surface.raised|text
T2 label on the popover|text.tertiary|surface.overlay|text
T2 label on the panel|text.tertiary|surface.canvas|text
T2 label on the app surface|text.tertiary|surface.app|text
T2 label hc AAA target|text.tertiary|surface.raised|hc-text
T2 reason on the control fill|text.secondary|surface.raised|text
T2 reason on the popover|text.secondary|surface.overlay|text
T2 reason and the validity reason on the panel|text.secondary|surface.canvas|text
T2 reason on the app surface|text.secondary|surface.app|text
unprotected banner text|text.primary|status.danger.subtle|text
accepted banner text|text.primary|status.success.subtle|text
input value (mono) in the well|text.primary|surface.app|text
TIF option text in the open list|text.primary|surface.overlay|text
rounding caption, unit captions|text.secondary|surface.canvas|text
ARMED pill glyph + 1 px border (D02 :511)|status.warning.strong|status.warning.subtle|non-text
ARMED pill border on the panel|status.warning.strong|surface.canvas|non-text
LOCKED pill lock glyph (D02 :512)|text.secondary|surface.raised|non-text
UNKNOWN pill '?' glyph|status.warning.strong|surface.raised|non-text
unprotected glyph and hatch lines (D02 :514)|status.danger.strong|status.danger.subtle|non-text
unprotected banner fill vs the panel (not a boundary)|status.danger.subtle|surface.canvas|decorative
estimated badge outline + glyph (E25-D05)|status.info.default|status.info.subtle|non-text
T2 hairline on the panel|border.default|surface.canvas|decorative
input rest boundary, REJECTED pair (D02 :497), bound nowhere|border.strong|surface.canvas|reported
input rest boundary, bound: text.tertiary (CR-1 border.input)|text.tertiary|surface.canvas|non-text
invalid field boundary|status.danger.default|surface.canvas|non-text
field error glyph|status.danger.strong|surface.canvas|non-text
focus ring on the panel (double ring vs canvas)|focus.ring|surface.canvas|non-text
focus ring on raised chrome|focus.ring|surface.raised|non-text
LIVE border + dot on the neutral pill|env.live|surface.raised|non-text
DEMO border + dot on the neutral pill|env.demo|surface.raised|non-text
buy fill vs the panel|buy.default|surface.canvas|non-text
sell fill vs the panel|sell.default|surface.canvas|non-text
M1 progress strip on the BUY fill (non-text)|text.inverse|buy.default|non-text
M1 progress strip on the SELL fill (non-text)|text.inverse|sell.default|non-text
M5 reduce tick on the panel|status.info.default|surface.canvas|non-text
M5 reduce tick on raised|status.info.default|surface.raised|non-text
M5 reduce tick on the popover|status.info.default|surface.overlay|non-text
""".splitlines()
D02_REPRO = (
    {  # E30-D02 section 15.1 rows reproduced to the hundredth (:474 :475 :481 D3 :511 :512 :514)
        ("text.primary", "status.warning.subtle"): (9.86, 15.62, 11.16),
        ("text.primary", "surface.raised"): (14.35, 15.62, 16.25),
        ("text.primary", "status.info.subtle"): (10.74, 15.44, 12.16),
        ("text.inverse", "buy.default"): (7.87, 5.39, 10.51),
        ("text.inverse", "sell.default"): (4.94, 5.20, 8.02),
        ("status.warning.strong", "status.warning.subtle"): (7.56, 4.11, 7.56),
        ("text.secondary", "surface.raised"): (8.81, 8.98, 14.35),
        ("status.danger.strong", "status.danger.subtle"): (7.83, 3.85, 7.83),
    }
)
VALIDITY = (  # the whole control at opacity.disabled over the panel: label | fill | surface
    "BUY submit|text.inverse|buy.default|surface.canvas",
    "SELL submit|text.inverse|sell.default|surface.canvas",
    "primary action|text.on-action|action.primary.default|surface.canvas",
    "raised control (preset, segment, option)|text.primary|surface.raised|surface.canvas",
)
REJECTED_M1 = (  # the full-height tint at 0.6: the label over the side fill at 0.6 over the panel
    "BUY submit|text.inverse|buy.default|surface.canvas",
    "SELL submit|text.inverse|sell.default|surface.canvas",
)
CVD_PAIRS = (
    "BUY fill vs SELL fill (D02 15.3)|buy.default|sell.default",
    "env LIVE vs DEMO (D02 15.3)|env.live|env.demo",
    "ARMED glyph vs danger glyph (D02 15.3)|status.warning.strong|status.danger.strong",
    "ARMED pill fill vs unprotected fill|status.warning.subtle|status.danger.subtle",
    "env DEMO blue vs focus ring blue|env.demo|focus.ring",
    "highlight tint vs ARMED pill fill|status.info.subtle|status.warning.subtle",
    "LIVE accent vs SELL fill (same primitive, D02 F5)|env.live|sell.default",
)
GREY = ["surface.canvas", "surface.raised", "text.primary", "env.live", "env.demo"]
GREY += ["buy.default", "sell.default"]
RESOLVED = [  # the hexes spec section 23.2 quotes
    "surface.canvas",
    "surface.raised",
    "surface.overlay",
    "surface.app",
    "text.primary",
    "text.secondary",
    "text.tertiary",
    "text.inverse",
    "buy.default",
    "sell.default",
    "env.live",
    "env.demo",
    "status.warning.subtle",
    "status.warning.strong",
    "status.danger.subtle",
    "status.danger.default",
    "status.danger.strong",
    "status.info.subtle",
    "status.info.default",
    "status.success.subtle",
    "focus.ring",
    "border.default",
    "border.strong",
]
FLASH = (  # id | max luminance changes per second | loops | longest run ms | note
    "M1|1|request-bound|0|the fill advances once per request, no alternation (E09-D08 A-10)",
    "M2|1|no|200|one fill cross per arm",
    "M3|1|no|0|one cut per disarm; the countdown is a 1 Hz text swap, one colour",
    "M4|1|no|800|one sweep per hold; the percentage text <= 2 / s (E39-D03)",
    "M5|2|no|100|>= 500 ms between starts per cell => <= 2 / s; peak 0.25; reduce: tick cut at 1 s",
    "M6|1|no|200|one fade per open / close",
    "M7|1|no|0|1 Hz text swap, one colour",
    "M8|1|no|200|one clip + translate per toggle",
    "M9|1|no|200|one slide per open",
    "M10|0|no|0|non-visual (audio): no luminance change",
    "hatch|0|no|0|static texture",
)
VIEW_AS = ("100", "101", "102", "103", "105", "107", "119", "122", "229", "231")
ORDER = ["100", "101", "102", "103", "105", "107", "119", "121", "122", "130", "139", "158"]
ORDER += ["229", "231", "232"]
ROWS = (
    "Purpose delta|Props|Variants|States|Tokens|ARIA contract|Keyboard|Density|Motion pair|"
    "Do / Don't|Storybook|Tests"
)
GATE_WORDS = ("disabled", "read-only", "unavailable", "blocked", "gated")
TOKEN_RE = re.compile(
    r"`((?:color|space|size|radius|font|type|elevation|opacity|motion|border|pattern)"
    r"\.[A-Za-z0-9.{},*-]+)`"
)
CITED_ABSENT = {  # names the spec may cite only as absent (CR rows in 3.2 or C-rows in 29)
    "color.buy",
    "color.sell",
    "color.status.danger",
    "color.status.success",
    "color.status.warn",
    "color.text.buy",
    "color.text.sell",
    "color.text.neutral",
    "color.border.invalid",
    "color.border.input",
    "color.text.danger",
    "color.text.warning",
    "font.mono",
    "pattern.hatch",
    "space.list.row",
    "color.avatar.palette",
    "motion.duration.hold-confirm",
    "motion.spin",
    "motion.hold",
    "color.surface.scrim",
    "color.icon",
    "color.chip",
    "color.callout",
    "space.tabs",
    "motion.slide",
    "color.status.warning",
    "color.status.info",
}
COPY_KEYS = {"size.unit.stale", "type.emulated"}  # D02 section 14 copy keys sharing a token prefix
MJS_PATH = ROOT / "tools" / "contrast" / "pairs.mjs"
MJS = re.sub(r"\s+", " ", MJS_PATH.read_text(encoding="utf-8"))
REGISTERED = set(re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', MJS))
HOST_RE = re.compile(r"\bpenpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
CLOSE_RE = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b *#\d", re.IGNORECASE)


def section(md: str, start: str, end: str | None) -> str:
    i = md.find("\n" + start)
    if i < 0:
        return ""
    j = md.find("\n" + end, i + 1) if end else -1
    return md[i : j if j >= 0 else len(md)]


def rows(md: str) -> list[list[str]]:
    lines = [ln for ln in md.splitlines() if ln.startswith("|") and not re.match(r"^\|\s*-", ln)]
    return [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]


def expand(name: str) -> list[str]:
    m = re.search(r"\{([^}]*)\}", name)
    if m:
        return [x for a in m.group(1).split(",") for x in expand(name.replace(m.group(0), a, 1))]
    return [name]


def exists(name: str) -> bool:
    return any(k.startswith(name[:-1]) for k in ALL) if name.endswith(".*") else name in ALL


def token_gate(spec: str) -> dict[str, int]:
    allowed = section(spec, "### 3.2", "### 3.3") + section(spec, "## 29.", "## 30.")
    bound: set[str] = set()
    absent: set[str] = set()
    for raw in TOKEN_RE.findall(spec):
        for name in expand(raw.rstrip(".")):
            if name in COPY_KEYS:
                continue
            if exists(name):
                bound.add(name)
            elif name in CITED_ABSENT or name.rsplit(".", 1)[0] in CITED_ABSENT:
                absent.add(name)
                if f"`{raw}`" not in allowed:
                    FAILS.append(f"absent token cited outside 3.2 / 29: {name}")
            else:
                FAILS.append(f"unknown token name: {name}")
    for ln in spec.splitlines():
        if "color.text.disabled" in ln and "DS-1" not in ln:
            FAILS.append("color.text.disabled bound outside the DS-1 sentence")
        if "opacity.disabled" in ln and "validity" not in ln and "never" not in ln:
            FAILS.append("opacity.disabled outside the validity look / the T2 'never' sentence")
    return {"bound": len(bound), "absent_as_cr": len(absent)}


def treatment_gate(spec: str) -> dict[str, int]:
    out: dict[str, int] = {}
    heads = re.findall(r"\n### (2\.\d) ([^\n]*)", section(spec, "## 2.", "## 3."))
    for w in ("armed", "live", "unprotected", "estimated"):
        own = [n for n, t in heads if f"`{w}`" in t]
        if len(own) != 1:
            FAILS.append(f"treatment {w}: {len(own)} definition headings (want 1)")
            continue
        rest = spec.replace(section(spec, f"### {own[0]} ", "### "), "")
        ok = f"`{w}` (§{own[0]})"
        out[w] = rest.count(ok)
        for ln in rest.splitlines():
            n = len(re.findall(rf"`{w}`", ln)) - ln.count(ok)
            out[w] += n
            if n and not ln.startswith("|") and not ln.startswith("#"):
                FAILS.append(f"treatment {w}: prose reference without (§{own[0]}): {ln[:50]!r}")
    return out


def structure(spec: str) -> dict[str, object]:
    comps = re.findall(r"\n## (\d+)\. CMP-(\d{3})", spec)
    if [c for _, c in comps] != ORDER:
        FAILS.append(f"component sections {[c for _, c in comps]} != the ticket's order")
    looks: dict[str, str] = {}
    for r in rows(section(spec, "### 2.5", "## 3.")):
        if len(r) >= 3 and r[2] in ("validity", "T2"):
            if r[0] in looks:
                FAILS.append(f"decision table: {r[0]} appears twice")
            looks[r[0]] = r[2]
    stories = {
        r[0].strip("`"): len([s for s in r[1].split(",") if s.strip()])
        for r in rows(section(spec, "## 24.", "## 25."))
        if r[0].startswith("`") and "/" in r[0]
    }
    for num, cmp_id in comps:
        body = section(spec, f"## {num}. CMP-{cmp_id}", f"## {int(num) + 1}.")
        names = [r[0] for r in rows(body)]
        FAILS.extend(f"CMP-{cmp_id}: row {w!r} missing" for w in ROWS.split("|") if w not in names)
        for r in rows(body):
            for item in r[1].split("·") if r[0] == "States" else []:
                gated = any(w in item for w in GATE_WORDS)
                if gated and not any(k in item for k in ("validity", "T2", "loading")):
                    FAILS.append(f"CMP-{cmp_id}: gated state without a look: {item[:50]!r}")
        if cmp_id in VIEW_AS and "rbac.view_as" not in body:
            FAILS.append(f"CMP-{cmp_id}: no rbac.view_as leg")
    motion = [r for r in rows(section(spec, "## 19.", "## 20.")) if re.fullmatch(r"M\d+", r[0])]
    rate = {x.split("|")[0]: x.split("|")[1] for x in FLASH}
    twins = 0
    for r in motion:
        if len(r) < 9:
            FAILS.append(f"{r[0]}: short row")
            continue
        if re.sub(r"\s*/\s*s", "", r[8]) != rate.get(r[0]):
            FAILS.append(f"{r[0]}: section 19 flash {r[8]!r} != the audit table's {rate.get(r[0])}")
        if not any(w in r[3].lower() for w in ("opacity", "transform", "clip", "text", "none")):
            FAILS.append(f"{r[0]}: property {r[3]!r} not in the allowed set")
        twins += r[5] not in ("", "—")
        if r[5] in ("", "—"):
            FAILS.append(f"{r[0]}: no reduce twin")
        if "motion." not in r[6] and "by reference" not in r[6] and "none" not in r[6]:
            FAILS.append(f"{r[0]}: tokens cell names no motion token")
    ledger = [r for r in rows(section(spec, "### 1.4", "### 1.5")) if re.fullmatch(r"L\d+", r[0])]
    if len(ledger) != 32 or any(len(r) < 5 or r[3] in ("", "—") for r in ledger):
        FAILS.append(f"ledger: {len(ledger)} rows, each needs an answer cell")
    if "rbac.view_as" not in section(spec, "### 2.5", "## 3."):
        FAILS.append("2.5: no rbac.view_as leg")

    def ids(p: str, a: str, b: str) -> int:
        return len({r[0] for r in rows(section(spec, a, b)) if re.fullmatch(p + r"\d+", r[0])})

    boards = len([r for r in rows(section(spec, "## 0.", "## 1.")) if re.fullmatch(r"\d\d", r[0])])
    if boards != 12:
        FAILS.append(f"boards: {boards} != 12")
    st: dict[str, object] = {"components": len(comps), "boards": boards, "motion_rows": len(motion)}
    st.update(twins=twins, ledger=len(ledger), looks=looks, stories=stories)
    st.update(story_total=sum(stories.values()), decisions=ids("D", "### 1.5", "## 2."))
    st.update(A=ids("A", "## 28.", "## 29."), C=ids("C", "## 29.", "## 30."))
    st.update(G=ids("G", "## 30.", "## 31."), Q=ids("Q", "## 31.", "## 32."))
    return st


def hygiene(texts: dict[str, str]) -> None:
    for name, txt in texts.items():
        if ("/" + "home/") in txt:
            FAILS.append(f"{name}: a local path")
        if HOST_RE.search(txt):
            FAILS.append(f"{name}: a Penpot hostname")
        if CLOSE_RE.search(txt):
            FAILS.append(f"{name}: a closing keyword")
        if any(ord(c) >= 0x1F000 or (0x2600 <= ord(c) <= 0x27BF and c not in "✓✗⚠") for c in txt):
            FAILS.append(f"{name}: an emoji code point")
    blank = [
        ln for ln in texts["handoff"].splitlines() if ln.startswith("- [ ]") and "N/A" not in ln
    ]
    FAILS.extend(f"handoff: blank line {ln[:40]!r}" for ln in blank)


def main() -> int:
    args = sys.argv[1:]
    spec_path = Path(args[args.index("--spec") + 1]) if "--spec" in args else E30 / "E30-D04.md"
    out: list[str] = []
    p = out.append

    def md(*cells: object) -> None:
        p("| " + " | ".join(str(c) for c in cells) + " |")

    p("## 1. Tokens at the base: " + ", ".join(f"{k} {v}" for k, v in COUNTS.items()))
    p(
        "\n## 2. Measured matrix\n\n| element | fg | bg | role | dark | light | hc | verdict "
        "| pairs.mjs |\n|" + "---|" * 9
    )
    matrix: list[list[str]] = []
    fail_n = 0
    for line in PAIRS:
        el, fg, bg, role = line.split("|")
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        bar = BAR[role]
        if bar is None:
            verdict = f"{role} (not gated)"
        elif role == "hc-text":
            low = [THEMES[i] for i in (0, 1) if vals[i] < bar]
            verdict = "PASS" if vals[2] >= bar else "FAIL: high-contrast"
            verdict += f" (AAA stretch not met in {', '.join(low)})" if low else ""
        else:
            bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
            verdict = "PASS" if not bad else "FAIL: " + ", ".join(bad)
        fail_n += verdict.startswith("FAIL")
        if verdict.startswith("FAIL"):
            FAILS.append(f"pair below the bar: {el}")
        if (fg, bg) in D02_REPRO and tuple(round(v, 2) for v in vals) != D02_REPRO[(fg, bg)]:
            FAILS.append(f"D02 pair not reproduced: {fg} on {bg} -> {[round(v, 2) for v in vals]}")
        registered = ("color." + fg, "color." + bg) in REGISTERED
        status = "registered" if registered else "PROPOSED"
        matrix.append([el, fg, bg, role, *[f"{v:.2f}" for v in vals], verdict, status])
        md(el, f"`color.{fg}`", f"`color.{bg}`", role, *matrix[-1][4:])
    reg_n = sum(r[-1] == "registered" for r in matrix)
    p(
        f"\npairs {len(PAIRS)} x 3 themes; registered {reg_n}, PROPOSED {len(PAIRS) - reg_n}; "
        f"gated FAIL {fail_n}; D02 rows reproduced {len(D02_REPRO)}"
    )
    p("\n## 3. Disabled composites (reported, not gated) and the highlight composite (gated 4.5)\n")
    comp: dict[str, list[str]] = {}
    for line in VALIDITY:
        el, lab, fill, surf = line.split("|")
        v = [
            ratio(over(col(t, lab), col(t, surf), 0.45), over(col(t, fill), col(t, surf), 0.45))
            for t in THEMES
        ]
        comp["validity " + el] = [f"{x:.2f}" for x in v]
        p(
            f"- validity look, {el}: label and fill at 0.45 over the panel = "
            + " / ".join(comp["validity " + el])
        )
    for line in REJECTED_M1:
        el, lab, fill, surf = line.split("|")
        v = [ratio(col(t, lab), over(col(t, fill), col(t, surf), 0.6)) for t in THEMES]
        comp["rejected M1 " + el] = [f"{x:.2f}" for x in v]
        p(
            f"- rejected M1 model, {el}: the label over the side fill at 0.6 over the panel = "
            + " / ".join(comp["rejected M1 " + el])
        )
    for surf in ("surface.canvas", "surface.raised", "surface.overlay"):
        v = [
            ratio(col(t, "text.primary"), over(col(t, "status.info.subtle"), col(t, surf), 0.25))
            for t in THEMES
        ]
        comp["highlight on " + surf] = [f"{x:.2f}" for x in v]
        if min(v) < 4.5:
            FAILS.append(f"highlight composite below 4.5 on {surf}")
        p(
            f"- highlight: text.primary over info.subtle at 0.25 on {surf} = "
            + " / ".join(comp[f"highlight on {surf}"])
        )
    p("\n## 4. CVD (dE76; JND 5.0)\n")
    md("pair", "theme", "normal", "protan", "deutan", "tritan", "verdict")
    p("|" + "---|" * 7)
    cvd_rows: list[list[str]] = []
    for line in CVD_PAIRS:
        name, a, b = line.split("|")
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            sim = [
                (str(cvd.simulate(ha, k)), str(cvd.simulate(hb, k)))
                for k in ("protanopia", "deuteranopia", "tritanopia")
            ]
            d = [float(cvd.delta_e76(ha, hb))] + [float(cvd.delta_e76(x, y)) for x, y in sim]
            verdict = "distinct" if min(d) >= 5.0 else "COLLAPSES (word / glyph / shape carries it)"
            cvd_rows.append([name, t, *[f"{x:.1f}" for x in d], verdict])
            md(*cvd_rows[-1])
    greys = {k: (col("dark", k), grey(col("dark", k))) for k in GREY}
    p("\ngreys (dark): " + ", ".join(f"`color.{k}` {h} -> {g}" for k, (h, g) in greys.items()))
    lvl = {k: int(g[1:3], 16) for k, (_, g) in greys.items()}
    deltas = {"env.live vs env.demo": abs(lvl["env.live"] - lvl["env.demo"])}
    deltas["buy.default vs sell.default"] = abs(lvl["buy.default"] - lvl["sell.default"])
    p("grey levels apart: " + ", ".join(f"{k} {v}" for k, v in deltas.items()))
    resolved = {k: [T[t]["color." + k] for t in THEMES] for k in RESOLVED}
    p(
        "\nresolved (dark / light / hc): "
        + " · ".join(f"`color.{k}` " + " / ".join(v) for k, v in resolved.items())
    )
    p(
        "\n## 5. Flash audit\n\n| row | max luminance changes / s | loops | longest run | note |\n|"
        + "---|" * 5
    )
    flash: list[list[str]] = []
    for line in FLASH:
        rid, per_s, loop, run, note = line.split("|")
        if int(per_s) > 3 or (loop == "yes" and int(run) > 5000):
            FAILS.append(f"flash: {rid}")
        flash.append([rid, per_s, loop, run + " ms", note])
        md(*flash[-1])
    worst = max(int(x.split("|")[1]) for x in FLASH)
    p(f"\nflash: {len(FLASH)} candidates, worst {worst} / s, no loop")
    spec = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
    hand_path = E30 / "E30-D04-handoff.md"
    hand = hand_path.read_text(encoding="utf-8") if hand_path.exists() else ""
    if not spec:
        FAILS.append("spec missing")
    tok, treat, st = token_gate(spec), treatment_gate(spec), structure(spec)
    hygiene({"spec": spec, "handoff": hand, "tool": Path(__file__).read_text(encoding="utf-8")})
    p(f"\n## 6. Gates\n\ntokens: {tok}; treatments (references): {treat}")
    p(f"structure: {json.dumps(st)}")
    p(
        "hygiene OK"
        if not any(f.startswith(("spec:", "handoff:", "tool:")) for f in FAILS)
        else "hygiene FAIL"
    )
    p(f"\nFAIL count (gated rows only): {len(FAILS)}" + "".join("\n- " + f for f in FAILS))
    summary = {
        "counts": COUNTS,
        "matrix": matrix,
        "pairs": [len(PAIRS), reg_n, len(PAIRS) - reg_n, fail_n],
        "composites": comp,
    }
    summary.update(cvd=cvd_rows, greys=greys, grey_deltas=deltas, resolved=resolved, flash=flash)
    summary["tokens"] = tok
    summary.update(treatments=treat, structure=st)
    summary["fails"] = FAILS
    print(json.dumps(summary, ensure_ascii=False) if "--json" in args else "\n".join(out))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
