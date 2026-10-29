"""E05-D03 (#162) audit: the motion table, the rules, the value flash, the override, the rows.

Stdlib only, offline (`python3 -I -B`). It reads the spec from the working tree; every cited file,
the shipped precedence test and `16` / `15` (for the A-row pre-images) AS TEXT at the pinned base
with `git show`; and the token JSON through `packages/ui/tokens/tests/verify_tokens.py`'s loader,
resolver and `over()` (dark = primitives + semantic-dark, light = + semantic-light, hc = +
semantic-hc), so the numbers agree with E08-D11's. Seven gate groups, ten gates, each FAIL led by
its code:

- [G1-TABLE] section 2 holds recipes 1 to 7, every cell filled, every reduce cell `none` literally.
- [G2-PROPERTY] the Property column names only `opacity`, `transform` or `none`.
- [G2-TOKEN] every dotted token name in the spec exists in the token JSON (the declined requests
  only on a line that says "declined"); every timing cell is a `motion.duration.*` and a
  `motion.easing.*` (or the CSS keyword `linear`).
- [G3-RULES] MR-1 over every repeating row (starts in any half-open 1 000 ms window <= 3; the hot
  surface's interval gives <= 2; the ticket's 333 ms is shown to admit 4); MR-2 (period x runs <=
  5 000 ms unless request-bound, the period equal to its duration token x the multiplier); MR-3 (a
  carrier on every row); row 3 carries A23's rate cap, cell cap and the 10 s stop; the MR texts and
  A23's acceptance text verbatim.
- [G4-FLASH] section 5's numbers recomputed unrounded from the tokens and compared at the printed
  precision (truncated, never rounded), and every verdict re-derived.
- [G5-AROW] each A-row's pre-image stands byte for byte on its cited line of `16` / `15` at the base
  under the heading it names, and each post text equals the pinned copy.
- [G5-CITE] every `KEY`:line cite resolves to a declared key and an existing range at the base, and
  each pinned cite still carries its words.
- [G6-PRECEDENCE] section 6's 4 x 3 table equals the shipped test's 18 rows (twin `false` and absent
  folded, asserted equal).
- [G7-HYGIENE] no local path, host, closing keyword, "approval pending", or a word on the lane's
  public-text list (kept rot13-encoded here so the list itself passes the same scan).
- [G7-BOARDS] section 9: 8 boards + 1 light twin, at most 10, twins at most a third, names and
  exports in the ruled pattern, every board PENDING until PR 2.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL (0 FAIL, 0 WARN is the bar);
`--self-test` applies one mutation per gate (MUTATIONS) and the paraphrase probes (PROBES) to an
in-memory copy of the spec and passes only when each adds exactly one new FAIL with its gate's
code, a re-run on the unmutated text reproduces the base result and no file on disk changed.

Usage: python3 -I -B docs/design/_tools/e05_d03_motion_audit.py [--check] [--json] [--self-test]
"""

from __future__ import annotations

import argparse
import codecs
import colorsys
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs" / "design" / "E05" / "E05-D03.md"
TOKENS = ROOT / "packages" / "ui" / "tokens"
BASE = "9c9742ed2c"  # origin/main when the spec was written; every cite is read here
THEMES = ("dark", "light", "high-contrast")
UI, WEB = "packages/ui/src/", "apps/web/src/"
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "E08-D06": "docs/design/E08/E08-D06.md",
    "E08-D11": "docs/design/E08/E08-D11.md",
    "E09-D08": "docs/design/E09/E09-D08.md",
    "E10-D03": "docs/design/E10/E10-D03.md",
    "E10-D04": "docs/design/E10/E10-D04.md",
    "E10-D04-handoff": "docs/design/E10/E10-D04-handoff.md",
    "E11-D06": "docs/design/E11/E11-D06.md",
    "E25-D03": "docs/design/E25/E25-D03.md",
    "E29-D04-handoff": "docs/design/E29/E29-D04-handoff.md",
    "E33-D04-handoff": "docs/design/E33/E33-D04-handoff.md",
    "theme.css": UI + "theme/theme.css",
    "store.ts": UI + "theme/store.ts",
    "dialog.css": UI + "components/dialog.css",
    "drawer.css": UI + "components/drawer.css",
    "select.css": UI + "components/select.css",
    "toast.css": UI + "components/toast.css",
    "skeleton.css": UI + "components/skeleton.css",
    "spinner.css": UI + "components/spinner.css",
    "motion-css.test.ts": "packages/ui/test/theme/motion-css.test.ts",
    "themeFromSettings.ts": WEB + "shell/bootstrap/themeFromSettings.ts",
    "model.ts": WEB + "features/a11y-preferences/model.ts",
    "AccessibilitySettingsScreen.tsx": WEB
    + "features/a11y-preferences/AccessibilitySettingsScreen.tsx",
    "KeymapHost.tsx": WEB + "keymap/KeymapHost.tsx",
    "a11y-preferences-theme.test.tsx": "apps/web/test/features/a11y-preferences-theme.test.tsx",
}
# key|line|words that must stand on that line at the base (the load-bearing cites)
CITE_PINS = """\
05|78|Session override;05|208|No content flashes more than 3 times per second
11|5182|chart inertia are disabled;14|2406|### SCR-117;15|188|pulses opacity 1 ↔ 0.8
15|196|stopped at 5 s;16|139|wins over `prefers-reduced-motion` in both directions
16|184|Node-graph edge draw;16|219|over `normal` / `accelerate`;16|232|Until E05-D03 lands
E08-D11|71|**0.25**;E08-D11|72|**≥ 500 ms between starts per cell**;E08-D11|367|A-1 `16` §7
E08-D11|368|motion.hold;E09-D08|461|**800 ms PROPOSED**;E10-D04|138|T-06;E10-D04|140|T-08
E10-D04-handoff|42|A-03;E10-D04-handoff|45|A-06;E10-D04-handoff|46|A-07
E10-D04-handoff|88|Ctrl+Shift+M;E10-D03|809|motion.toast;E10-D03|810|motion.drawer
E11-D06|255|Last-price pill;theme.css|48|--cv-motion-scale: 1;theme.css|69|prefers-reduced-motion
dialog.css|29|prefers-reduced-motion: no-preference;drawer.css|118|no-preference
select.css|106|no-preference;toast.css|56|no-preference;skeleton.css|34|linear 4
spinner.css|29|linear infinite;store.ts|172|os.reduceMotion;themeFromSettings.ts|87|flag === true
model.ts|60|flashOnTick: !calm;14|2411|disable flash-on-update;14|2412|frame budget
KeymapHost.tsx|71|Locked;E33-D04-handoff|135|C.8"""
RULE_TEXT = {
    "MR-1": "no element starts more than 3 flashes in any 1 000 ms window",
    "MR-2": "an animation whose `animation-iteration-count` × `animation-duration` exceeds "
    "5 000 ms, or is `infinite`, ships a pause control or stops itself by 5 s; the only "
    "exception is a request- or job-bound busy indicator with its in-flight label",
    "MR-3": "every row names a non-motion carrier (text, glyph, sign, ARIA state) present in "
    "the reduce end state; the reduce snapshot's accessibility tree equals the safe end state's",
    "A23": "The light-theme flash is **accepted as designed**: at ≤ 2 starts per second per cell "
    "with the fast-market stop it passes WCAG 2.3.1 by rate (and 2.3.2's three-per-second bar), "
    "the emphasised area is small and capped, and reduce mode removes it entirely; the light "
    "alpha stays 0.25 (PROPOSED within E08-D11's 0.15–0.35 as a _tuning_, not a gate) for the "
    "owner's later prototype run.",
}
AROW_SHA = "0e2ff0bd3ca5"  # sha256 prefix over every A-row's id, line, heading, pre and post
# A-7 as R162 BQ-16 rules it (the list's ASCII arrow written as `16`'s, with `16`'s full stop)
A7_POST = (
    "- Node-graph connection made: `fast` `opacity` fade, never a line-draw (a stroke-dash draw "
    "reads as direction); stagger 0; no pulse on the connecting port; reduce → instant (E37-D03 "
    "BQ-08, RULED on #876)."
)
DECLINED = (
    "motion.hold",
    "motion.spin",
    "motion.toast",
    "motion.drawer",
    "motion.slide",
    "motion.shimmer",
    "motion.toggle",
)
FLASH_ALPHA, HOT_MS, WINDOW_MS, CEILING = 0.25, 500, 1000, 3
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy QbF nqivfbel TUFN "
    "cer-nhgu"
)
BANNED = codecs.decode(BANNED_ROT13, "rot13").split()


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VT = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")


def git_show(rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{BASE}:{rel}"], capture_output=True, check=False
    )
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def all_tokens() -> dict[str, Any]:
    toks: dict[str, Any] = dict(VT.load(VT.PRIMITIVES))
    for files in VT.THEMES.values():
        toks.update(VT.merged_set(files))
    return toks


def theme_colours(name: str) -> dict[str, str]:
    toks: dict[str, Any] = dict(VT.load(VT.PRIMITIVES))
    toks.update(VT.merged_set(VT.THEMES[name]))
    return {k: VT.resolve(v["$value"], toks) for k, v in toks.items() if v.get("$type") == "color"}


class Ctx(NamedTuple):
    """The texts the gates read; the self-test swaps `spec` for a mutated copy."""

    spec: str
    base: dict[str, str]
    tokens: dict[str, Any]
    colours: dict[str, dict[str, str]]


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx() -> Ctx:
    base = {k: git_show(p) for k, p in KEYS.items()}
    colours = {t: theme_colours(t) for t in THEMES}
    return Ctx(SPEC.read_text(encoding="utf-8"), base, all_tokens(), colours)


def section(spec: str, num: int) -> str:
    """Section `num` of the spec: from its `## n.` heading to the next one outside a fence."""
    out: list[str] = []
    fenced = inside = False
    for line in spec.splitlines(keepends=True):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and re.match(r"## \d+\. ", line):
            inside = line.startswith(f"## {num}. ")
        if inside:
            out.append(line)
    return "".join(out)


def flat(text: str) -> str:
    return " ".join(text.split())


def rows(sec: str) -> list[list[str]]:
    out = []
    for line in sec.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:]  # drop the header


def trunc(x: float, places: int) -> str:
    """Truncated toward zero, so a failing 4.4999 never prints as the 4.5 it misses."""
    return f"{math.trunc(x * 10**places) / 10**places:.{places}f}"


# --- G1, G2: the table ------------------------------------------------------------------------
COLS = (
    "#",
    "recipe",
    "element",
    "property",
    "from",
    "enter",
    "exit",
    "repeat",
    "reduce",
    "carrier",
    "source",
)


def table(ctx: Ctx) -> list[dict[str, str]]:
    return [dict(zip(COLS, r, strict=False)) for r in rows(section(ctx.spec, 2))]


def gate_table(ctx: Ctx, r: Result) -> None:
    rs, recipes = table(ctx), set()
    for row in rs:
        if len(row) != len(COLS) or any(not v for v in row.values()):
            r.fail("G1-TABLE", f"row {row.get('#')}: {len(row)} cells or a blank cell")
            continue
        recipes.add(row["#"][0])
        if not row["reduce"].startswith("`none`"):
            r.fail("G1-TABLE", f"row {row['#']}: the reduce cell does not open with `none`")
    if recipes != set("1234567"):
        r.fail("G1-TABLE", f"recipes {sorted(recipes)} != 1..7")
    r.numbers["rows"], r.numbers["recipes"] = len(rs), len(recipes)


def gate_property(ctx: Ctx, r: Result) -> None:
    for row in table(ctx):
        words = re.findall(r"`([^`]+)`", row.get("property", ""))
        bare = re.sub(r"`[^`]+`|[,\s]|and", "", row.get("property", ""))
        if not words or bare or set(words) - {"opacity", "transform", "none"}:
            r.fail("G2-PROPERTY", f"row {row.get('#')}: property {row.get('property')!r}")


def gate_token(ctx: Ctx, r: Result) -> None:
    names = 0
    for line in ctx.spec.splitlines():
        for name in re.findall(r"`((?:motion|opacity|color|space|size)\.[a-z0-9.-]+)`", line):
            names += 1
            if name.startswith(DECLINED):
                if "declined" not in line:
                    r.fail("G2-TOKEN", f"{name} outside a declined row")
            elif name not in ctx.tokens:
                r.fail("G2-TOKEN", f"`{name}` is not in the token JSON")
    for row in table(ctx):
        for col in ("enter", "exit"):
            cell = row.get(col, "")
            if cell.startswith(("—", "a cut")):
                continue
            ok = re.search(r"`motion\.duration\.\w+`", cell) and (
                re.search(r"`motion\.easing\.\w+`", cell) or "`linear`" in cell
            )
            if not ok:
                r.fail("G2-TOKEN", f"row {row.get('#')} {col}: no duration and easing pair")
    r.numbers["token_names"] = names


# --- G3: the rules ----------------------------------------------------------------------------
def max_starts(interval_ms: float, span_ms: float = 10_000) -> int:
    starts = [k * interval_ms for k in range(int(span_ms // interval_ms) + 1)]
    return max(sum(1 for u in starts if t <= u < t + WINDOW_MS) for t in starts)


def duration_ms(ctx: Ctx, cell: str) -> float:
    m = re.search(r"`(motion\.duration\.\w+)`", cell)
    val = str(ctx.tokens[m.group(1)]["$value"]) if m and m.group(1) in ctx.tokens else "0ms"
    mult = re.search(r"` × (\d+)", cell)
    return float(val.removesuffix("ms")) * (int(mult.group(1)) if mult else 1)


def gate_rules(ctx: Ctx, r: Result) -> None:
    rules = section(ctx.spec, 4)
    for rid, text in RULE_TEXT.items():
        where = section(ctx.spec, 5) if rid == "A23" else rules
        if flat(text) not in flat(where):
            r.fail("G3-RULES", f"{rid}'s ruled text is not verbatim in its section")
    n = {"hot": max_starts(HOT_MS), "ticket_333": max_starts(333), "ceiling_334": max_starts(334)}
    for row in table(ctx):
        rep, rid = row.get("repeat", ""), row.get("#", "?")
        if row.get("carrier", "—") in ("", "—"):
            r.fail("G3-RULES", f"row {rid}: MR-3 no carrier")
        cap = re.search(r"≥ (\d+) ms between starts", rep)
        loop = re.search(r"([\d ]+) ms × (\d+|request)", rep)
        if cap:
            starts = max_starts(float(cap.group(1)))
            n[f"row{rid}_starts"] = starts
            if starts > CEILING or (int(cap.group(1)) < HOT_MS):
                r.fail("G3-RULES", f"row {rid}: MR-1 {starts} starts per 1 000 ms")
            if not ("≤ 20" in rep and "10 s" in rep and "latest wins" in rep):
                r.fail("G3-RULES", f"row {rid}: A23's cell cap, latest-wins or 10 s stop missing")
        elif loop:
            period = float(loop.group(1).replace(" ", ""))
            if period != duration_ms(ctx, row.get("enter", "")):
                r.fail("G3-RULES", f"row {rid}: period {period:g} != its token x multiplier")
            if max_starts(period) > CEILING:
                r.fail("G3-RULES", f"row {rid}: MR-1 over the ceiling")
            bound = loop.group(2) == "request"
            if bound and "in-flight label" not in row.get("reduce", ""):
                r.fail("G3-RULES", f"row {rid}: MR-2 request-bound without the in-flight label")
            if not bound and period * int(loop.group(2)) > 5000:
                r.fail("G3-RULES", f"row {rid}: MR-2 runs past 5 000 ms")
        elif not rep.startswith("one-shot"):
            r.fail("G3-RULES", f"row {rid}: repeat cell {rep!r} is not a ruled form")
        if row.get("recipe", "").startswith("Value flash") and not (
            cap and re.search(r"≥ 1 Hz for 10 s", rep)
        ):
            r.fail("G3-RULES", f"row {rid}: A23 needs the per-cell cap and the 1 Hz-for-10 s stop")
        if rid == "7" and (
            "static glyph" not in row.get("reduce", "") or "puls" in rep + row.get("reduce", "")
        ):
            r.fail("G3-RULES", "row 7: the reduce state must be the static glyph, no pulse (BQ-05)")
    hs1 = re.search(r"\*\*HS-1 .*?At least (\d+) ms between flash starts", rules, re.DOTALL)
    if not hs1 or int(hs1.group(1)) != HOT_MS:
        r.fail("G3-RULES", f"HS-1's prose interval is not {HOT_MS} ms")
    said = re.search(r"333 ms admits (\d+)", rules)
    hot = re.search(r"at 500 ms a cell starts at most (\d+)", rules)
    if (
        not said
        or int(said.group(1)) != n["ticket_333"]
        or not hot
        or int(hot.group(1)) != n["hot"]
    ):
        r.fail("G3-RULES", "section 4's start counts differ from the computed ones")
    r.numbers["mr1"] = n


# --- G4: the value flash ----------------------------------------------------------------------
def flash(ctx: Ctx, theme: str, surface: str, side: str) -> dict[str, float]:
    c = ctx.colours[theme]
    lum, rgb = VT.relative_luminance, VT.hex_to_rgb
    bg, d = c[f"color.surface.{surface}"], c[f"color.{side}.default"]
    peak = VT.over(d, bg, FLASH_ALPHA)
    r_, g_, b_ = rgb(peak)
    return {
        "hue": colorsys.rgb_to_hsv(r_ / 255, g_ / 255, b_ / 255)[0] * 360,
        "dl": lum(rgb(peak)) - lum(rgb(bg)),
        "dark_l": min(lum(rgb(peak)), lum(rgb(bg))),
        "digits": VT.contrast_ratio(c["color.text.primary"], peak),
        "dir_peak": VT.contrast_ratio(d, peak),
        "dir_surface": VT.contrast_ratio(d, bg),
        "red": r_ / (r_ + g_ + b_),
    }


def gate_flash(ctx: Ctx, r: Result) -> None:
    sec, seen = section(ctx.spec, 5), 0
    out: dict[str, dict[str, float]] = {}
    for row in rows(sec):
        if len(row) != 11 or row[0] not in ("dark", "light", "hc"):
            continue
        theme = "high-contrast" if row[0] == "hc" else row[0]
        surface, side = row[1].strip("`").removeprefix("color.surface."), row[2]
        f = flash(ctx, theme, surface, "buy" if side == "up" else "sell")
        out[f"{row[0]} {surface} {side}"] = f
        want = [
            trunc(f["hue"], 1),
            trunc(f["dl"], 3),
            trunc(f["digits"], 2),
            trunc(f["dir_peak"], 2),
            trunc(f["dir_surface"], 2),
        ]
        text_bar = 7.0 if theme == "high-contrast" else 4.5
        general = abs(f["dl"]) >= 0.1 and f["dark_l"] < 0.8
        verdict = ("flash" if general else "no flash") + (", red" if f["red"] >= 0.8 else "")
        gl = "pass" if f["dir_peak"] >= 3 and f["dir_surface"] >= 3 else "FAIL"
        dg = "pass" if f["digits"] >= text_bar else "FAIL"
        exp = [*want, dg, gl, verdict]
        got = [row[3].removesuffix("°"), row[4], row[5], row[6], row[7], row[8], row[9], row[10]]
        if got != exp:
            r.fail("G4-FLASH", f"{row[0]} {surface} {side}: spec {got} != computed {exp}")
        seen += 1
        hue_ok = 90 <= f["hue"] <= 180 if side == "up" else (f["hue"] >= 330 or f["hue"] <= 30)
        if not hue_ok:
            r.fail("G4-FLASH", f"{row[0]} {surface} {side}: hue {f['hue']:.1f} outside its family")
    if seen != 12:
        r.fail("G4-FLASH", f"{seen} flash rows, expected 12 (3 themes x 2 surfaces x 2 sides)")
    for row in rows(sec):
        if len(row) == 3 and row[0] in ("dark", "light", "hc"):
            th = "high-contrast" if row[0] == "hc" else row[0]
            s = row[1].strip("`").removeprefix("color.surface.")
            c = ctx.colours[th]
            up = VT.over(c["color.buy.default"], c[f"color.surface.{s}"], FLASH_ALPHA)
            down = VT.over(c["color.sell.default"], c[f"color.surface.{s}"], FLASH_ALPHA)
            if row[2] != trunc(VT.contrast_ratio(up, down), 2):
                r.fail("G4-FLASH", f"{row[0]} {s}: up vs down {row[2]} is not the computed ratio")
    r.numbers["flash"] = {k: {m: round(v, 4) for m, v in f.items()} for k, f in out.items()}


# --- G5: the A-rows and the cites -------------------------------------------------------------
AROW = re.compile(
    r"^#### (A-\d+) — `(15|16)`:(\d+), under `([^`]+)`[^\n]*\n\n"
    r"Pre-image:\n\n```text\n(.*?)\n```\n\n"
    r"Post:\n\n```text\n(.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def heading_of(text: str, line: int) -> str:
    for ln in reversed(text.splitlines()[:line]):
        if ln.startswith("#"):
            return ln
    return ""


def gate_arow(ctx: Ctx, r: Result) -> None:
    found = AROW.findall(section(ctx.spec, 8))
    digest = hashlib.sha256()
    for aid, key, line, head, pre, post in found:
        lines = ctx.base[key].splitlines()
        n = int(line)
        if not 0 < n <= len(lines) or pre not in lines[n - 1]:
            r.fail("G5-AROW", f"{aid}: the pre-image is not on `{key}`:{n} at the base")
        if heading_of(ctx.base[key], n) != head:
            r.fail("G5-AROW", f"{aid}: the heading above `{key}`:{n} is not {head!r}")
        digest.update(f"{aid}|{key}|{line}|{head}|{pre}|{post}\n".encode())
        if aid == "A-7" and post != A7_POST:
            r.fail("G5-AROW", "A-7's post is not R162's ruled text")
    r.numbers["arows"], r.numbers["arow_sha"] = len(found), digest.hexdigest()[:12]
    if len(found) != 11:
        r.fail("G5-AROW", f"{len(found)} A-rows, expected 11 (8 + pointer + tail + `15`:188)")
    if digest.hexdigest()[:12] != AROW_SHA:
        r.fail("G5-AROW", f"A-row text {digest.hexdigest()[:12]} differs from the pinned copy")


CITE = re.compile(r"`([A-Za-z0-9.-]+)`((?::\d+(?:-\d+)?)(?:, :\d+(?:-\d+)?)*)")


def gate_cite(ctx: Ctx, r: Result) -> None:
    cited: list[tuple[str, int, int]] = []
    body = re.sub(r"```.*?```", "", ctx.spec, flags=re.DOTALL)
    for key, spans in CITE.findall(body):
        if key not in KEYS:
            r.fail("G5-CITE", f"`{key}`{spans}: an undeclared key")
            continue
        size = len(ctx.base[key].splitlines())
        for a, b in re.findall(r":(\d+)(?:-(\d+))?", spans):
            cited.append((key, int(a), int(b or a)))
            if not 0 < int(a) <= int(b or a) <= size:
                r.fail("G5-CITE", f"`{key}`:{a}{'-' + b if b else ''} is outside the file")
    for pin in CITE_PINS.replace("\n", ";").split(";"):
        key, line, words = pin.split("|", 2)
        lines = ctx.base[key].splitlines()
        if int(line) > len(lines) or words not in lines[int(line) - 1]:
            r.fail("G5-CITE", f"`{key}`:{line} no longer carries {words!r}")
        if not any(k == key and a <= int(line) <= b for k, a, b in cited):
            r.fail("G5-CITE", f"the pinned cite `{key}`:{line} is not in the spec")
    r.numbers["cites"] = len(cited)


# --- G6: precedence ---------------------------------------------------------------------------
def shipped_rows(ctx: Ctx) -> dict[tuple[str, str, bool], str]:
    test = ctx.base["a11y-preferences-theme.test.tsx"]
    got: dict[tuple[str, str, bool], str] = {}
    for tri, twin, os_, motion in re.findall(
        r'\["(system|on|off)", (true|false|undefined), (true|false), "(safe|reduce)"\]', test
    ):
        key = (tri, "true" if twin == "true" else "false/absent", os_ == "true")
        if got.setdefault(key, motion) != motion:
            got[key] = "CONFLICT"
    return got


def gate_precedence(ctx: Ctx, r: Result) -> None:
    shipped, cells = shipped_rows(ctx), 0
    for row in rows(section(ctx.spec, 6)):
        m = re.match(r"twin (true|false/absent), OS (reduce|no-preference)", row[0])
        if not m or len(row) != 4:
            continue
        for tri, cell in zip(("system", "on", "off"), row[1:], strict=True):
            cells += 1
            want = shipped.get((tri, m.group(1), m.group(2) == "reduce"))
            if f"`{want}`" != cell.split()[0]:
                r.fail("G6-PRECEDENCE", f"{row[0]} / {tri}: spec {cell!r}, shipped {want!r}")
    if cells != 12 or len(shipped) != 12 or "CONFLICT" in shipped.values():
        r.fail("G6-PRECEDENCE", f"{cells} cells, {len(shipped)} shipped cases (12 each, folded)")
    r.numbers["precedence_cells"] = cells


# --- G7: hygiene and boards -------------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for word in BANNED:
        flags = 0 if word[0].isupper() and not word.isupper() else re.IGNORECASE
        if re.search(rf"\b{re.escape(word)}\b", ctx.spec, flags):
            r.fail("G7-HYGIENE", f"a word from the lane's public-text list: {word!r}")
    for pat, what in (
        (r"/home/|/tmp/|[A-Z]:\\\\", "a local path"),
        (r"https?://", "a host"),
        (r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d", "a closing keyword"),
        (r"approval pending", "approval pending (BQ-20)"),
    ):
        if re.search(pat, ctx.spec, re.IGNORECASE):
            r.fail("G7-HYGIENE", what)


def gate_boards(ctx: Ctx, r: Result) -> None:
    bs = rows(section(ctx.spec, 9))
    twins = [b for b in bs if len(b) > 3 and b[3] == "light"]
    for b in bs:
        m = re.fullmatch(r"`E05-D03 / (\d\d(?:-light)?) ([a-z0-9-]+)`", b[1] if len(b) > 1 else "")
        exp = f"`docs/design/E05/img/E05-D03-{m.group(1)}-{m.group(2)}.png`" if m else ""
        if not m or b[2] != exp or b[0] != m.group(1) or b[-1] != "PENDING (PR 2)":
            r.fail("G7-BOARDS", f"board row {b[:2]}: name, export or status off the pattern")
    if len(bs) > 10 or len(twins) * 3 > len(bs) or (len(bs), len(twins)) != (9, 1):
        r.fail("G7-BOARDS", f"{len(bs)} boards, {len(twins)} twins (ruled 8 + 1, cap 10, ⅓)")
    r.numbers["boards"], r.numbers["twins"] = len(bs), len(twins)


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-TABLE", gate_table),
    ("G2-PROPERTY", gate_property),
    ("G2-TOKEN", gate_token),
    ("G3-RULES", gate_rules),
    ("G4-FLASH", gate_flash),
    ("G5-AROW", gate_arow),
    ("G5-CITE", gate_cite),
    ("G6-PRECEDENCE", gate_precedence),
    ("G7-HYGIENE", gate_hygiene),
    ("G7-BOARDS", gate_boards),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test --------------------------------------------------------------------------------
def sub(old: str, new: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(spec=ctx.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(
        spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE)
    )


MUTATIONS: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G1-TABLE", sub("| `none` — a static glyph", "| a static glyph")),
    ("G2-PROPERTY", regex(r"\| `transform`( +\| `rotate\(0\)`)", r"| `rotate`\1")),
    ("G2-TOKEN", sub("scrim 0 → `opacity.scrim`", "scrim 0 → `opacity.scrims`")),
    ("G3-RULES", sub("1 200 ms × 4", "1 200 ms × 5")),
    ("G4-FLASH", regex(r"\| 9\.07( +)\|", r"| 9.08\1|")),
    ("G5-AROW", sub("T-08; SCR-015).", "T-08; SCR-014).")),
    ("G5-CITE", sub("`16`:219", "`16`:2190")),
    ("G6-PRECEDENCE", regex(r"(\| twin true, OS no-preference +\| )`reduce`", r"\1`safe`  ")),
    ("G7-HYGIENE", sub("(BQ-20, RULED", "(BQ-20, owner approval pending, RULED")),
    ("G7-BOARDS", sub("`E05-D03 / 08 rules-card`", "`E05-D03 / 08 Rules-card`")),
)

# Paraphrase probes (lens round 1): edits a weaker gate would let through; each must add one FAIL.
PROBES: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G3-RULES", regex(r"≥ 500 ms between starts per cell, ≤ 20[^|]*", "one-shot, once per tick ")),
    ("G3-RULES", sub("a cell at ≥ 1 Hz for 10 s stops", "a cell at ≥ 9 Hz for 10 s stops")),
    ("G3-RULES", sub("| `none` — a static glyph", "| `none` — an opacity pulse, a static glyph")),
    (
        "G3-RULES",
        sub("At least 500 ms between flash starts", "At least 400 ms between flash starts"),
    ),
)


def digests() -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (SPEC, Path(__file__))}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before, spec_sha = digests(), hashlib.sha256(ctx.spec.encode()).hexdigest()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in (*MUTATIONS, *PROBES):
        mutated = fn(ctx)
        if mutated.spec == ctx.spec:
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if hashlib.sha256(ctx.spec.encode()).hexdigest() != spec_sha:
        bad.append("self-test: the spec text in memory changed")
    if again.fails != base.fails or again.numbers != base.numbers:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    args = ap.parse_args(argv)
    ctx = load_ctx()
    if not all(ctx.base.values()):
        missing = [k for k, v in ctx.base.items() if not v]
        print(f"FAIL [G5-CITE] cannot read {missing} at {BASE} (fetch origin first)")
        return 1
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {"numbers": res.numbers, "fails": res.fails}
        payload["warns"] = res.warns
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        n = res.numbers
        out.append(
            f"rows {n.get('rows')} (recipes {n.get('recipes')}); cites {n.get('cites')}; "
            f"A-rows {n.get('arows')}; precedence cells {n.get('precedence_cells')}; "
            f"boards {n.get('boards')} (twins {n.get('twins')})"
        )
        out.append(f"gates: {len(GATE_FNS)}; FAIL {len(res.fails)}, WARN {len(res.warns)}")
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per "
                f"gate) and {len(PROBES)} probes, each one new FAIL; a re-run reproduces the base "
                "result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
