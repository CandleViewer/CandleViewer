"""E12-D03 SCR-042 menu audit: contrast, CVD, parity with the shipped bounds, and copy rules.

Standalone, offline, stdlib only. Resolves the `dark`, `light` and `high-contrast` themes as
`packages/ui/tokens/tests/verify_tokens.py` does (same loader, alias resolution and layering),
measures every pair `docs/design/E12/E12-D03.md` binds (the ratio is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py`) and simulates CVD with `docs/research/_tools/cvd_simulate.py`.
It then reads `services/api/candleviewer/bars/limits.py` and `bars/spec.py` as syntax trees (never
importing them) and the spec's own text, and checks the per-mode table, the messages, the descriptions
and the custom-interval rule against both, so a drift in the code or the spec fails the run. Section G
checks that the spec's §9 table lists exactly the pairs measured here, each with the same kind.

Usage: python3 -I docs/design/_tools/e12_d03_menu_audit.py   (prints Markdown; exit 1 on a FAIL)

Bars (05 §5 items 1, 2 and 6): `text` 4.5:1 and `non-text` 3:1 in every theme; `hc-text` 7:1 in the
high-contrast theme only; `light-text` 4.5:1 in light only (a fill the other themes do not use there).
`rejected-*` and `decorative` rows are reported, never gated. `CR:` names a design-system change request,
measured on the existing token it would alias.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
BARS = ROOT / "services" / "api" / "candleviewer" / "bars"
SPEC_MD = ROOT / "docs" / "design" / "E12" / "E12-D03.md"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "light-text": 4.5, "decorative": None,
       "rejected-text": 4.5, "rejected-non-text": 3.0, "rejected-hc-text": 7.0}
CR = {"CR:color.border.input": "color.text.tertiary"}  # E30-D02 CR-1, shared, not re-requested


def resolve_theme(name: str) -> dict[str, str]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"}


T = {n: resolve_theme(n) for n in THEMES}


def col(theme: str, token: str) -> str:
    return T[theme][CR.get(token, token)]


def ratio(fg: str, bg: str) -> float:
    rgb = [tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) for h in (fg, bg)]
    return contrast_check.contrast_ratio(rgb[0], rgb[1])


OV, SEL, HOV, RAI, APP = (f"color.surface.{s}" for s in ("overlay", "selected", "hover", "raised", "app"))
ACT, SEC = "color.action.selected", "color.action.secondary.default"
P, S, TT = "color.text.primary", "color.text.secondary", "color.text.tertiary"
FILLS = (OV, HOV, ACT, SEL, RAI)  # rest, hover or focus, checked, expanded or light hover, toolbar or panel
# (element, fg, backgrounds, role): one matrix row per background.
PAIRS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("labels, chips, ◉ / ○, the trigger", P, FILLS, "text"),
    ("line 2, parameters, reasons, ⊘, Kbd digits", S, FILLS, "text"),
    ("headers, depth line, helper, unit; the T2 label and lock (CMP-079)", TT, (OV, HOV, ACT, RAI, APP), "text"),
    ("field value", P, (APP,), "text"),
    ("Apply, Change…, the route button", P, (SEC,), "text"),
    ("Save (CMP-001 primary)", "color.text.on-action", ("color.action.primary.default",), "text"),
    ("HC: labels and buttons", P, FILLS + (APP, SEC), "hc-text"),
    ("HC: line 2", S, FILLS, "hc-text"),
    ("HC: headers, helper, unit, the T2 label", TT, (OV, HOV, ACT, RAI, APP), "hc-text"),
    ("focus ring", "color.focus.ring", FILLS + (APP,), "non-text"),
    ("checked outline vs its fill, the surface", "color.border.selected", (ACT, OV), "non-text"),
    ("field boundary (CR) vs the panel, the field", "CR:color.border.input", (RAI, APP), "non-text"),
    ("✕ glyph and invalid boundary", "color.status.danger.strong", (RAI, APP), "non-text"),
    ("⚠ glyph", "color.status.warning.strong", (RAI,), "non-text"),
    ("ⓘ glyph", "color.status.info.strong", (RAI,), "non-text"),
    ("Save fill vs the surface", "color.action.primary.default", (OV,), "non-text"),
    ("the T2 label on the light hover until DS-5 (dark 3.98 unused)", TT, (SEL,), "light-text"),
    ("text.disabled for the greyed state: never used", "color.text.disabled", (OV,), "rejected-text"),
    ("border.default as a field boundary", "color.border.default", (OV,), "rejected-non-text"),
    ("border.strong as a field boundary", "color.border.strong", (OV,), "rejected-non-text"),
    ("text.link for the route: a button instead (H-8)", "color.text.link", (RAI,), "rejected-hc-text"),
    ("hover fill vs the surface (1.00 in light)", HOV, (OV,), "decorative"),
    ("checked fill vs the surface (the outline and ◉ carry it)", ACT, (OV,), "decorative"),
    ("editor panel vs the surface", RAI, (OV,), "decorative"),
    ("separator", "color.border.subtle", (OV,), "decorative"),
]
CVD_PAIRS = [
    ("checked outline vs focus ring (position also differs)", "color.border.selected", "color.focus.ring"),
    ("✕ vs ⚠ glyph (shapes, words)", "color.status.danger.strong", "color.status.warning.strong"),
    ("ⓘ vs ⚠ glyph", "color.status.info.strong", "color.status.warning.strong"),
    ("checked fill vs hover fill", ACT, HOV),
]
MISSING = [
    ("color.border.input", "E30-D02 CR-1", "color.text.tertiary, 1 px"),
    ("color.surface.hover (light value)", "E08-D05's request", "color.surface.selected in light"),
    ("color.text.error", "E11-D03 D03-CR-4", "color.text.primary + a status glyph"),
    ("a thick focus-ring width", "SCR-117 thick_focus_ring", "two border.focus strokes, pending"),
    ("font.mono", "CMP-007, 008, 022, 220 Tokens lines", "font.family.mono / type.num.*"),
    ("elevation.3, radius.md", "CMP-017, CMP-041 Tokens lines", "elevation.popover, radius.card"),
]

# The spec's per-mode table (E12-D03 §2) and its messages (§5), checked against the code below.
SPEC = {"TICK_PARAM_RANGE": (100, 1_000_000), "RANGE_TICKS_RANGE": (2, 100_000),
        "RENKO_TICKS_RANGE": (2, 100_000), "QTY_PARAM_MAX": 10**12, "QTY_PARAM_MIN_STEPS": 10,
        "MAX_BRICKS_PER_TRADE": 1_000, "MAX_WINDOW_BARS": 250_000, "PARAM_MAX_LEN": 24,
        "TIME_CODES": ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D")}
MESSAGES = {"tick": "Enter 100 to 1,000,000 trades.", "range": "Enter 2 to 100,000 ticks.",
            "ceiling": "Enter at most 1,000,000,000,000 BTC.",
            "atr": "ATR bricks are not available yet. Enter a brick size in ticks."}
DESCRIPTIONS = ["One bar per clock interval.",
                "Bars close on trade count, so busy periods make more bars.",
                "Bars close on traded volume; one big trade can close several.",
                "Bars close on a fixed high-low range; quiet markets add few.",
                "Bars close once net buying or selling reaches the size.",
                "Equal bricks; reversals need two bricks, hiding small swings."]
LADDER_MIN = {1, 3, 5, 15, 30, 60, 120, 240, 360, 720, 1440}
CUSTOM_CASES = {"7m": "custom 7", "90": "custom 90", "2h": "ladder 120", "60m": "ladder 60",
                "1D": "ladder 1440", "24h": "ladder 1440", "3 H": "custom 180", "0m": "C-13",
                "3x": "C-13", "25h": "C-13", "1.5h": "C-13", "2d": "C-13", "7M": "C-13", "": "C-13",
                "15s": "C-14", "1w": "C-14"}


def custom_interval(raw: str) -> str:
    """E12-D03 §6.2: whole minutes or hours, 1m to 24h; `1d` is 1D; `s` and `w` are post-GA."""
    s = raw.replace(" ", "")
    if re.fullmatch(r"[0-9]+[sSwW]", s):
        return "C-14"
    m = re.fullmatch(r"([0-9]+)([mhHdD]?)", s)
    if not m or m.group(2) in ("d", "D") and m.group(1) != "1":
        return "C-13"
    minutes = int(m.group(1)) * {"": 1, "m": 1, "h": 60, "H": 60, "d": 1440, "D": 1440}[m.group(2)]
    if not 1 <= minutes <= 1440:
        return "C-13"
    return f"ladder {minutes}" if minutes in LADDER_MIN else f"custom {minutes}"


def constants(path: Path) -> dict[str, object]:
    """Module-level constants of a source file, from its syntax tree (literals and simple maths)."""
    out: dict[str, object] = {}

    def ev(node: ast.AST) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(ev(e) for e in node.elts)
        if isinstance(node, ast.Name) and node.id in out:
            return out[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Pow, ast.Add)):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Mult):
                return a * b
            return a**b if isinstance(node.op, ast.Pow) else a + b
        if isinstance(node, ast.Dict):  # TIME_INTERVALS: the comprehension's codes, then D and W
            codes = [c.value for n in ast.walk(node) if isinstance(n, ast.Tuple)
                     for c in n.elts if isinstance(c, ast.Constant)]
            return tuple(codes) + tuple(k.value for k in node.keys if isinstance(k, ast.Constant))
        raise ValueError("not a literal")

    for stmt in ast.parse(read_text(path)).body:
        target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
            stmt.targets[0] if isinstance(stmt, ast.Assign) else None)
        if isinstance(target, ast.Name) and stmt.value is not None:
            try:
                out[target.id] = ev(stmt.value)
            except (ValueError, TypeError):
                pass
    return out


def section9(md: str) -> dict[tuple[str, str], str]:
    """The (fg, bg) pairs of the spec's §9 table, each with its kind (gated, rejected or decorative)."""
    out: dict[tuple[str, str], str] = {}
    for line in md.split("\n## 9.", 1)[1].split("\n## ", 1)[0].splitlines():
        if not line.startswith("| `"):
            continue
        cell = line.split("|")[1]
        left, right = re.split(r" (?:on|vs) ", cell, maxsplit=1)
        fgs = (["CR:color.border.input"] if "CR `border.input`" in left
               else [f"color.{n}" for n in re.findall(r"`([a-z.-]+)`", left)])
        kind = "rejected" if "rejected" in cell else "decorative" if "decorative" in cell else "gated"
        for fg in fgs:
            for bg in re.findall(r"`([a-z.-]+)`", right):
                out[(fg, f"color.{bg}")] = kind
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the reference machine's console is cp1252
    failed = 0
    print("## A. Contrast matrix (ratio per theme; bar per role)\n")
    print("| Element | fg | bg | role | dark | light | hc | verdict |\n|---|---|---|---|---|---|---|---|")
    for element, fg, bgs, role in PAIRS:
        for bg in bgs:
            vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
            gated = [2] if role.endswith("hc-text") else [1] if role == "light-text" else [0, 1, 2]
            bar = BAR[role]
            bad = [THEMES[i] for i in gated if bar is not None and vals[i] < bar]
            verdict = "decorative" if bar is None else ("PASS" if not bad else "FAIL: " + ", ".join(bad))
            if role.startswith("rejected"):
                verdict = "rejected by design (" + ("fails " + ", ".join(bad) if bad else "passes") + ")"
            elif bad:
                failed += 1
            cells = " | ".join(f"{v:.2f}" for v in vals)
            print(f"| {element} | `{fg}` | `{bg}` | {role} | {cells} | {verdict} |")
    print("\n## B. Resolved values\n\n| token | dark | light | hc |\n|---|---|---|---|")
    for tok in sorted({t for _, fg, bgs, _ in PAIRS for t in (fg, *bgs)}):
        print(f"| `{tok}` | " + " | ".join(col(t, tok) for t in THEMES) + " |")
    print("\n## C. CVD (ΔE76 per deficiency; floor 5.0)\n")
    print("| Pair | theme | normal | protan | deutan | tritan | verdict |\n|---|---|---|---|---|---|---|")
    for name, a, b in CVD_PAIRS:
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            d = [cvd.delta_e76(ha, hb)] + [cvd.delta_e76(cvd.simulate(ha, k), cvd.simulate(hb, k))
                                           for k in ("protanopia", "deuteranopia", "tritanopia")]
            verdict = "distinct" if min(d) >= 5.0 else "COLLAPSES (shape or words carry it)"
            print(f"| {name} | {t} | " + " | ".join(f"{x:.1f}" for x in d) + f" | {verdict} |")
    print("\n## D. Missing tokens (requested, never invented)\n")
    print("| Name | Cited by | Bound meanwhile |\n|---|---|---|")
    for name, where, meanwhile in MISSING:
        print(f"| `{name}` | {where} | {meanwhile} |")

    code = {**constants(BARS / "limits.py"), **constants(BARS / "spec.py")}
    code["TIME_CODES"] = tuple(c for c in code.get("TIME_INTERVALS", ()) if c != "W")
    print("\n## E. Per-mode parity: E12-D03 §2 vs the shipped code\n")
    print("| constant | spec | code | verdict |\n|---|---|---|---|")
    for name, want in SPEC.items():
        got = code.get(name)
        ok = got == want
        failed += 0 if ok else 1
        print(f"| `{name}` | {want} | {got} | {'PASS' if ok else 'FAIL'} |")
    atr_ok = MESSAGES["atr"] == code.get("RENKO_ATR_DEFERRED")
    failed += 0 if atr_ok else 1
    print(f"| `RENKO_ATR_DEFERRED` | C-12 | verbatim | {'PASS' if atr_ok else 'FAIL'} |")

    print("\n## F. Copy rules\n\n| rule | verdict |\n|---|---|")
    def names(key: str, *nums: int) -> bool:
        return all(f"{n:,}" in MESSAGES[key] for n in nums)

    checks = [
        ("C-7 names the tick bounds", names("tick", *code["TICK_PARAM_RANGE"])),
        ("C-11 names the range and Renko bounds", names("range", *code["RANGE_TICKS_RANGE"])),
        ("C-10 names the volume and delta ceiling", names("ceiling", code["QTY_PARAM_MAX"])),
        ("descriptions fit one line at 400 px (61 characters or fewer)",
         all(len(d) <= 61 for d in DESCRIPTIONS)),
        ("the longest canonical param fits PARAM_MAX_LEN",
         len(str(code["QTY_PARAM_MAX"])) <= code["PARAM_MAX_LEN"]),
    ]
    checks += [(f"custom `{raw}` → {want}", custom_interval(raw) == want)
               for raw, want in CUSTOM_CASES.items()]
    spec_md = read_text(SPEC_MD)  # the strings and bound cells this audit checks must be the spec's own
    checks += [(f"spec §5 holds the {key} message verbatim", msg.replace("BTC", "{BTC}") in spec_md)
               for key, msg in MESSAGES.items()]
    checks += [(f"spec §5 holds C-{i} verbatim", d in spec_md) for i, d in enumerate(DESCRIPTIONS, 1)]
    lo, hi = code["TICK_PARAM_RANGE"], code["RANGE_TICKS_RANGE"]
    cells = (f"{lo[0]:,} to {lo[1]:,}", f"{hi[0]:,} to {hi[1]:,}", f"{code['QTY_PARAM_MAX']:,}")
    checks += [(f"spec §2 bound cell `{cell}` (from the code)", cell in spec_md) for cell in cells]
    for rule, ok in checks:
        failed += 0 if ok else 1
        print(f"| {rule} | {'PASS' if ok else 'FAIL'} |")

    measured: dict[tuple[str, str], str] = {}
    for _, fg, bgs, role in PAIRS:
        kind = "rejected" if role.startswith("rejected") else "decorative" if role == "decorative" else "gated"
        for bg in bgs:
            measured.setdefault((fg, bg), kind)
    table = section9(spec_md)
    diffs = sorted(set(measured.items()) ^ set(table.items()))
    print("\n## G. §9 parity: the spec's table lists exactly the pairs measured here\n")
    for (fg, bg), kind in diffs:
        where = "measured, not in §9" if measured.get((fg, bg)) == kind else "in §9, not measured"
        print(f"- FAIL: `{fg}` on `{bg}` ({kind}): {where}")
    failed += len(diffs)
    print(f"{len(measured)} pairs measured, {len(table)} in §9: {'PASS' if not diffs else 'FAIL'}")
    print(f"\nFAIL count (gated rows, parity, copy and §9 rules): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
