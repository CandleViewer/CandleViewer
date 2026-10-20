"""E09-D09 RBAC permission-denied pattern audit: contrast matrix, CVD check, permission matrix.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly as
`packages/ui/tokens/tests/verify_tokens.py` does (same loader, alias resolution and theme layering
from `themes.json`), measures every foreground/background pair the pattern spec
(`docs/design/E09/E09-D09.md`) binds, simulates the three deficiencies with the projection of
`docs/research/_tools/cvd_simulate.py`, and reads the role -> permission lists out of the
`x-permissions` block of `docs/plan/22-api-openapi.yaml`, so the vocabulary's "owner-only" chooser
(spec section 3) is checked against the canonical registry rather than against memory. The contrast
formula is `contrast_ratio()` from `docs/design/_tools/contrast_check.py` (imported, not
re-implemented), so the numbers agree with E11-D02's, E30-D01's and E09-D03's.

Usage: python3 -I docs/design/_tools/e09_d09_rbac_audit.py   (prints Markdown; exit 1 on a FAIL)

Bars per role: `text` 4.5:1, `non-text` 3:1, `hc-text` 7:1 (`05-accessibility-standard.md` section 5
items 1, 2 and 6). `decorative` rows carry no meaning on their own (the glyph and the text carry it)
and are reported, never gated; `rejected` rows are text pairs the spec considered and designed
around. Data rows are `|`-separated lines in the string tables below, one row per line; token
columns use the short aliases of `TOK`.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
OPENAPI = ROOT / "docs" / "plan" / "22-api-openapi.yaml"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
BAR = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0, "decorative": None, "rejected": 4.5}
JND = 5.0
DEFS = ("protanopia", "deuteranopia", "tritanopia")
TOK = {
    "t1": "color.text.primary",
    "t2": "color.text.secondary",
    "t3": "color.text.tertiary",
    "td": "color.text.disabled",
    "link": "color.text.link",
    "app": "color.surface.app",
    "canvas": "color.surface.canvas",
    "raised": "color.surface.raised",
    "overlay": "color.surface.overlay",
    "bd": "color.border.default",
    "bs": "color.border.strong",
    "focus": "color.focus.ring",
    "warnS": "color.status.warning.subtle",
    "warnG": "color.status.warning.strong",
    "act": "color.action.primary.default",
}


def rows(table: str) -> list[list[str]]:
    return [[c.strip() for c in ln.split("|")] for ln in table.strip().splitlines()]


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg))


def resolve_theme(name: str) -> dict[str, str]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {
        k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"
    }


T = {n: resolve_theme(n) for n in THEMES}


def name(alias: str) -> str:
    """The full token name of an alias; `mix45:<fg>@<bg>` is spelled out."""
    if alias.startswith("mix45:"):
        fg, bg = alias[6:].split("@", 1)
        return f"{TOK[fg]} at opacity.disabled 0.45 over {TOK[bg]}"
    return TOK[alias]


def col(theme: str, alias: str) -> str:
    if alias.startswith("mix45:"):  # fg at opacity.disabled (0.45) composited over bg
        fg, bg = alias[6:].split("@", 1)
        f, b = hex_to_rgb(T[theme][TOK[fg]]), hex_to_rgb(T[theme][TOK[bg]])
        mixed = [round(0.45 * x + 0.55 * y) for x, y in zip(f, b, strict=True)]
        return "#" + "".join(f"{c:02X}" for c in mixed)
    return T[theme][TOK[alias]]


# element | fg | bg | role
PAIRS = rows("""
T2 label, adopted: tertiary on the control fill | t3 | raised | text
T2 label on a panel | t3 | canvas | text
T2 label on the app surface | t3 | app | text
T2 label, hc AAA target | t3 | raised | hc-text
T2 label, REJECTED: the DS text.disabled token on raised | td | raised | rejected
T2 label, REJECTED: text.disabled on canvas | td | canvas | rejected
T2 label, REJECTED: text.disabled on app | td | app | rejected
T2 label, REJECTED: primary at opacity.disabled over raised | mix45:t1@raised | raised | rejected
T2 reason text (inline) on a panel; 'No longer shown' placeholder | t2 | canvas | text
T2 reason text in the tooltip echo (CMP-016 overlay) | t2 | overlay | text
T2 reason text on app; SCR-154 body sentence | t2 | app | text
T2 reason text, hc AAA target | t2 | canvas | hc-text
T2 lock glyph on the control fill | t3 | raised | non-text
T2 lock glyph on a panel (menu item, checklist row) | t3 | canvas | non-text
T2 control fill vs panel (enabled fill removed; reinforcement) | raised | canvas | decorative
T2 control border (reinforcement; glyph + text carry) | bd | canvas | decorative
T2 control border, strong step (alternative reinforcement) | bs | canvas | decorative
focus ring on the T2 control (CMP-039) | focus | raised | non-text
focus ring on a panel | focus | canvas | non-text
access-changed / read-only banner text (CMP-028 warning) | t1 | warnS | text
banner glyph | warnG | warnS | non-text
banner text, hc AAA target | t1 | warnS | hc-text
SCR-154 / SCR-155 heading | t1 | app | text
SCR-154 / SCR-155 link (Back to your workspace) | link | app | text
SCR-154 correlation id (mono) | t3 | app | text
""")

# Colour pairs that must stay distinguishable without their text (deltaE76 >= the 5.0 JND floor).
CVD_PAIRS = rows("""
banner glyph vs banner text | warnG | t1
focus ring vs T2 border | focus | bd
enabled primary fill vs T2 fill | act | raised
SCR-154 link vs body text | link | t2
""")
SIM_TOKENS = ["t3", "t2", "focus", "warnG", "act"]


def role_permissions() -> tuple[dict[str, set[str]], set[str]]:
    """Role lists from the `x-permissions` block; the vocabulary from every `x-rbac` block."""
    text = OPENAPI.read_text(encoding="utf-8")
    block = text.split("\nx-permissions:\n", 1)[1].split("\npaths:\n", 1)[0]
    roles: dict[str, set[str]] = {}
    current = ""
    for line in block.splitlines():
        if re.match(r"^  \w+:$", line):
            current = line.strip()[:-1]
            roles[current] = set()
        elif line.startswith("    - "):
            roles[current].add(line.split("- ", 1)[1].strip().strip('"'))
    vocab: set[str] = set()
    for m in re.finditer(r"x-rbac: \{ permissions: \[([^\]]*)\]", text):
        vocab.update(p.strip() for p in m.group(1).split(",") if p.strip())
    return roles, vocab


def verdict_for(role: str, vals: list[float]) -> tuple[str, bool]:
    bar = BAR[role]
    if bar is None:
        return "decorative (not gated)", False
    if role == "hc-text":
        bad = ["high-contrast"] if vals[2] < bar else []
    else:
        bad = [THEMES[i] for i, v in enumerate(vals) if v < bar]
    text = "PASS" if not bad else "FAIL: " + ", ".join(bad)
    if role == "rejected":
        text = "rejected by design; would " + text if bad else "rejected by design (passes; unused)"
        return text, False
    return text, bool(bad)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failed = 0
    print("## A. Contrast matrix (ratio per theme; bar per role)\n")
    print("| Element | fg | bg | role | dark | light | hc | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for element, fg, bg, role in PAIRS:
        vals = [ratio(col(t, fg), col(t, bg)) for t in THEMES]
        verdict, gated_fail = verdict_for(role, vals)
        failed += int(gated_fail)
        nums = " | ".join(f"{v:.2f}" for v in vals)
        print(f"| {element} | `{name(fg)}` | `{name(bg)}` | {role} | {nums} | {verdict} |")

    print("\n## B. Resolved values used above\n")
    print("| token | dark | light | hc |")
    print("|---|---|---|---|")
    seen: list[str] = []
    for _, fg, bg, _ in PAIRS:
        for tok in (fg, bg):
            if tok not in seen:
                seen.append(tok)
    for tok in seen:
        vals = " | ".join(col(t, tok) for t in THEMES)
        print(f"| `{name(tok)}` | {vals} |")

    print("\n## C. CVD simulation (deltaE76 under each deficiency; JND floor 5.0)\n")
    print("| Pair | theme | normal | protan | deutan | tritan | verdict |")
    print("|---|---|---|---|---|---|---|")
    for label, a, b in CVD_PAIRS:
        for t in THEMES:
            ha, hb = col(t, a), col(t, b)
            d = [cvd.delta_e76(ha, hb)]
            d += [cvd.delta_e76(cvd.simulate(ha, k), cvd.simulate(hb, k)) for k in DEFS]
            verdict = "distinct" if min(d[1:]) >= JND else "COLLAPSES (text/shape carries it)"
            nums = " | ".join(f"{v:.1f}" for v in d)
            print(f"| {label} | {t} | {nums} | {verdict} |")

    print("\n## D. Pattern colours under simulation (hex), for the board annotations\n")
    print("| token | theme | normal | protan | deutan | tritan |")
    print("|---|---|---|---|---|---|")
    for tok in SIM_TOKENS:
        for t in THEMES:
            h = col(t, tok)
            sims = " | ".join(cvd.simulate(h, k) for k in DEFS)
            print(f"| `{name(tok)}` | {t} | {h} | {sims} |")

    roles, vocab = role_permissions()
    non_owner = set().union(*(v for k, v in roles.items() if k != "owner"))
    owner_only = sorted(vocab - non_owner)
    print("\n## E. Permission matrix read from 22-api-openapi.yaml (the owner-only chooser)\n")
    print(f"- permission codes in `x-rbac` blocks: {len(vocab)}")
    for role in sorted(roles):
        star = " (`*`)" if "*" in roles[role] else ""
        print(f"- `{role}`: {len(roles[role])} entries{star}")
    listed = ", ".join(f"`{p}`" for p in owner_only)
    print(f"- owner-only (held by no non-owner role): {len(owner_only)}: {listed}")
    print(f"\nFAIL count (gated rows only): {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
