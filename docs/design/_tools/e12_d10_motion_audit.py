#!/usr/bin/env python3
"""E12-D10 (#245) audit: the motion spec for the bar-mode switch, the bar close, rebuild progress
and the LOD change.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
spec and the pins file from the working tree, and every cited file AS TEXT with `git show` at the
pinned base (`BASE`), except E47-D08, read at #5444's merge (`E47_REF`). PR 2
applies the A-rows (§15) to `16` and `14`; G-APPLIED reads those two from the working tree and their
merge-base. Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-MOMENT   §2's rows M-01 ... M-08, in order, each complete: a property, a token or "a cut" in
             Duration and Easing, a reduce cell, a carrier, a budget in ms, a source; the four
             moments (a) ... (d) present; M-06's and M-08's carriers name their view-as T2
             (BQ-15).
  G-TOKEN    every `motion.*` name the spec writes resolves in `primitives.tokens.json` at the
             base; every DUR anchor is that token's value.
  G-BUDGET   every BUD anchor re-derived from the cited texts and the tokens (the switch room, the
             close budget, the progress period and slack, the dead-band edges, the frame times).
  G-CITE     every cite in range and on a non-blank line at its base, and its content equal to the
             pins file's hash (a moved or edited line FAILs until re-pointed by content and
             `--repin-ruled` re-pins it); the SHA anchors are the pinned refs.
  G-HYGIENE  no closing keyword, local path, URL or host, agent name, double-brace slot or
             public-text deny word in the spec; no hard-coded `16` block number "§7.3" (BQ-18:
             numbered at PR 2's rebase); no unknown anchor key.
  G-APPLIED  the A-rows as applied (PR 2): `16` equals its merge-base text with one block inserted
             after the last §7 block, numbered one past it (§15 records the number); its table is
             §2 rendered row for row (Moment, Enter, Reduce, Source), its rules name R-2 ... R-7 by
             their §1.3 titles; `14` equals its merge-base text with A-2's line added once, last in
             the SCR-030 entry.
  G-SCOPE    the diff against `git merge-base HEAD origin/main` touches only the spec, this tool,
             the pins file, `14` and `16`.

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d10_motion_audit.py --check      (exit 1 on any FAIL)
  python3 -I docs/design/_tools/e12_d10_motion_audit.py --json       (values and findings)
  python3 -I docs/design/_tools/e12_d10_motion_audit.py --self-test
      (one mutation per gate, at least)
  python3 -I docs/design/_tools/e12_d10_motion_audit.py --repin-ruled (the pins file's only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E12/E12-D10.md"
TOOL_REL = "docs/design/_tools/e12_d10_motion_audit.py"
PINS_REL = "docs/design/_tools/e12_d10_ruled_pins.txt"
# origin/main at PR 2's rebase; every cite re-pinned there by content
BASE = "3619e95c5b0c9ea7ff73d0a088930e15cbec756f"
TOK_REL = "packages/ui/tokens/primitives.tokens.json"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D08": "docs/design/E12/E12-D08.md",
    "D09": "docs/design/E12/E12-D09.md",
    "D11": "docs/design/E12/E12-D11.md",
    "D12": "docs/design/E12/E12-D12.md",
    "D13": "docs/design/E12/E12-D13.md",
    "E11D06": "docs/design/E11/E11-D06.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E08D11": "docs/design/E08/E08-D11.md",
    "E47D08": "docs/design/E47/E47-D08.md",
    "ADR33": "docs/plan/27-adrs/ADR-0033-renko-brick-sizing-and-series-rebuild.md",
}
A_PATHS = (PATHS["16"], PATHS["14"])  # the A-rows' targets (§15), applied in PR 2
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL, *A_PATHS)
E47_REF = (
    "1c5320c49fe521725ae9bb4814c2b49b49ef067c"  # #5444's merge; same blobs as its head e60fe7baa5
)
REF_OF = {"E47D08": E47_REF}  # every other key is read at BASE (D08 since #5425 merged)
DASH = "\u2013"  # the en dash of a cited range
CITE = re.compile(
    r"`(\d\d|D0[2-9]|D1[0-3]|E11D06|E05D03|E08D11|E47D08|ADR33)`:"
    r"(\d+(?:\u2013\d+)?(?:, :\d+(?:\u2013\d+)?)*)"
)
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
# assembled, so the list never spells the words it refuses
DENY = (
    "le" + "ak",
    "expo" + "sed",
    "by" + "pass",
    "ex" + "ploit",
    "att" + "ack",
    "ora" + "cle",
    "rev" + "eal",
    "unbou" + "nded",
    "flo" + "od",
    "st" + "all",
    "d" + "os",
    "advi" + "sory",
    "gh" + "sa",
    "pre-" + "auth",
)
MS_LITERAL = re.compile(r"(?<![\w.>])\d[\d.,]*\s?ms\b")  # an anchored value ends "-->" before " ms"
MOMENTS = ("(a)", "(b)", "(c)", "(d)")
T2_ROWS = ("M-06", "M-08")  # BQ-15: the rows that show `Retry` / `Cancel` under view-as
BLOCK_HEAD = re.compile(
    r"### 7\.(\d+) Chart bar-band motion \(E12-D10; PROPOSED until the owner's run\)"
)
BLOCK_LEAD = (
    "Spec: `docs/design/E12/E12-D10.md` (the moments table §2, the reduced-motion walk §7, the"
    " budgets and the drop rule §8). Tokens used by name, none added:"
    " `motion.duration.{instant,normal}` and `motion.easing.standard`. Every canvas moment is a"
    " one-frame cut (E11-D06 D14); the one tween is CMP-023's fill in the DOM strip, never on"
    " the canvas."
)
BLOCK_COLS = ["Moment", "Enter", "Reduce", "Source"]
DOC_NAME = {
    "E11D06": "E11-D06",
    "E05D03": "E05-D03",
    "E08D11": "E08-D11",
    "E47D08": "E47-D08",
}


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    changed: list[str] | None
    memo: dict[str, str | None]
    tree: dict[str, str | None]  # the A-rows' targets in the working tree
    mb: dict[str, str | None]  # ... and at the merge-base


def git(*args: str) -> str | None:
    try:
        # git with fixed arguments and no shell; the only external program the audit runs
        r = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rev: str, rel: str) -> str | None:
    key = f"{rev}:{rel}"
    if key not in t.memo:
        t.memo[key] = git("show", key)
    return t.memo[key]


def at(t: Texts, key: str) -> str:
    text = show(t, REF_OF.get(key, BASE), PATHS[key])
    if text is None:
        raise SystemExit(
            f"{PATHS[key]} does not resolve at {REF_OF.get(key, BASE)[:10]}; fetch first"
        )
    return text


def norm(s: str) -> str:
    return " ".join(s.split())


def table_rows(text: str, lead: str) -> list[list[str]]:
    out = []
    for ln in text.split("\n"):
        if ln.startswith("| " + lead):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return out


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    j = text.find("\n## ", i + 1)
    return text[i : j if j > 0 else len(text)]


# ---------------------------------------------------------------------------- values


def num(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


def find(t: Texts, key: str, rx: str) -> str:
    m = re.search(rx, at(t, key))
    if not m:
        raise LookupError(f"`{key}` no longer carries /{rx}/ at its base")
    return m[1]


def durations(t: Texts) -> dict[str, int]:
    raw = show(t, BASE, TOK_REL)
    if raw is None:
        raise SystemExit(f"{TOK_REL} does not resolve at the base")
    d = json.loads(raw)
    out = {}
    for k, v in d.items():
        if k.startswith("motion.duration.") and isinstance(v, dict):
            out[k.split(".")[-1]] = int(str(v["$value"]).removesuffix("ms"))
    return out


def tokens(t: Texts) -> set[str]:
    raw = show(t, BASE, TOK_REL) or "{}"
    return {k for k in json.loads(raw) if k.startswith("motion.")}


def compute(t: Texts) -> dict[str, str]:
    v: dict[str, str] = {
        "SHA:BASE": BASE[:10],
        "SHA:E47D08": E47_REF[:10],
    }
    nxt = next_block(t.mb.get(PATHS["16"]))
    if nxt is not None:
        v["APP:block"] = f"§7.{nxt}"
    dur = durations(t)
    for k, ms in dur.items():
        v[f"DUR:{k}"] = str(ms)
    sw = int(find(t, "11", r"switch ≤(\d+) ms from cache"))
    ty = int(find(t, "11", r"type switch ≤(\d+) ms"))
    hz = int(find(t, "D08", r"update at (\d+)<!--=RULED:cadence\.hz--> Hz"))
    band = int(find(t, "26", r"±(\d+) % dead band")) / 100
    l0 = float(find(t, "26", r"`barSpacing ≥ (\d+(?:\.\d+)?) px` → L0"))
    l1 = float(find(t, "26", r"`≥ (\d+(?:\.\d+)?) px` → L1"))
    frame = find(t, "26", r"budget = (\d+(?:\.\d+)?) ms")
    fps = int(find(t, "14", r"\u2265(\d+) fps at 2560\u00d71440"))
    rows = table_rows(section(t.spec, "## 2."), "M-0")
    m05 = next((r for r in rows if r[0] == "M-05"), None)
    v.update({
        "BUD:fade.ms": str(dur["normal"]), "BUD:switch.ms": str(sw), "BUD:type.ms": str(ty),
        "BUD:switch.room": str(sw - dur["normal"]),
        "BUD:close.ms": (
            str(dur["instant"]) if m05 and m05[3] == "`motion.duration.instant`" else "?"
        ),
        "BUD:close.min.s": "1",  # T Scope (b): "on intervals as short as 1 s"
        "BUD:close.fast.pct": num(dur["fast"] / 1000 * 100),
        "BUD:progress.hz": str(hz), "BUD:progress.period.ms": num(1000 / hz),
        "BUD:progress.slack.ms": num(1000 / hz - dur["normal"]),
        "BUD:lod.l0.down": num(l0 * (1 - band)), "BUD:lod.l0.up": num(l0 * (1 + band)),
        "BUD:lod.l1.down": num(l1 * (1 - band)), "BUD:lod.l1.up": num(l1 * (1 + band)),
        "BUD:frame.ms": frame, "BUD:fps58.ms": f"{int(1000 / fps * 100) / 100:.2f}",
        "BUD:flash.starts": str(sum("flash" in r[2].lower() for r in rows)),
    })  # fmt: skip
    return v


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition(DASH)
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec):
        label = f"{key}:{a}" if a == b else f"{key}:{a}{DASH}{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its base")
            continue
        hashes[label] = hashlib.sha256(
            (norm(ls[a - 1]) + "\n" + norm(ls[b - 1])).encode()
        ).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def g_moment(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.spec, "## 2."), "M-0")
    bad = []
    if [r[0] for r in rows] != [f"M-0{i}" for i in range(1, 9)]:
        bad.append(f"§2's rows are {[r[0] for r in rows]}, not M-01 ... M-08 in order")
    for r in rows:
        if len(r) != 9:
            bad.append(f"{r[0]}: {len(r)} cells, not 9")
            continue
        _, _moment, prop, d, e, red, carrier, budget, src = r
        if not prop:
            bad.append(f"{r[0]}: no property")
        if not re.fullmatch(r"`motion\.duration\.[a-z]+`", d):
            bad.append(
                f"{r[0]}: Duration {d!r} is not a token (a cut is `motion.duration.instant`)"
            )
        if e != "a cut" and not re.fullmatch(r"`motion\.easing\.[a-z]+`", e):
            bad.append(f"{r[0]}: Easing {e!r} is neither a token nor 'a cut'")
        if not red:
            bad.append(f"{r[0]}: no reduced-motion equivalent")
        if not carrier:
            bad.append(f"{r[0]}: no carrier")
        if not re.search(r"\d+(?:<!--=[A-Z]+:[a-z.]+-->)? ms", budget):
            bad.append(f"{r[0]}: no budget in ms")
        if not src:
            bad.append(f"{r[0]}: no source")
    for r in rows:
        if r[0] in T2_ROWS and len(r) > 6 and "view-as T2" not in r[6]:
            bad.append(f"{r[0]}: its carrier does not name the view-as T2 (BQ-15)")
    got = " ".join(r[1] for r in rows if len(r) > 1)
    for mo in MOMENTS:
        if mo not in got:
            bad.append(f"moment {mo} has no row in §2")
    return bad


def g_token(t: Texts, vals: dict[str, str]) -> list[str]:
    known = tokens(t)
    bad = [
        f"`{n}` does not resolve in {TOK_REL}"
        for n in sorted(set(re.findall(r"`(motion\.[a-z.]+[a-z])`", t.spec)))
        if n not in known
    ]
    bad += anchor_problems(t, vals, "DUR:")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for m in MS_LITERAL.finditer(ln):
            bad.append(
                f"spec:{i} writes {m[0]!r}: a millisecond value only as a derived or"
                " anchored value (BQ-14)"
            )
    return bad


def g_budget(t: Texts, vals: dict[str, str]) -> list[str]:
    return anchor_problems(t, vals, "BUD:")


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(
                f"cite {label}: the line at its base is not the pinned content (moved or edited)"
            )
    bad += anchor_problems(t, vals, "SHA:")
    return bad


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        low = ln.lower()
        checks = (
            (CLOSING, "a closing keyword (PR 2 alone closes #245)"),
            (LOCAL_PATH, "a local path"),
            (AGENT_NAME, "an agent name"),
            (URL_OR_HOST, "a URL or a host"),
        )
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
        if "§7.3" in ln:
            bad.append(f"spec:{i} hard-codes the `16` block as §7.3 (BQ-18)")
        hit = next((d for d in DENY if d in low), None)
        if hit:
            bad.append(f"spec:{i} carries a public-text deny word")
    for _, key in ANCHOR.findall(t.spec):
        if key not in vals:
            bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


# ---------------------------------------------------------------------------- A-rows (PR 2)


def next_block(mb16: str | None) -> int | None:
    if mb16 is None:
        return None
    nums = [int(n) for n in re.findall(r"^### 7\.(\d+) ", mb16, re.MULTILINE)]
    return max(nums, default=0) + 1


def spec_rules(spec: str) -> dict[int, str]:
    return {
        int(n): title
        for n, title in re.findall(r"^- \*\*R-(\d) ([^*]+?)\.\*\*", spec, re.MULTILINE)
    }


def source_names(cell: str) -> list[str]:
    out: list[str] = []
    for m in CITE.finditer(cell):
        k = m[1]
        name = DOC_NAME.get(k) or (f"E12-{k}" if k.startswith("D") else f"`{k}`")
        if name not in out:
            out.append(name)
    return out


def block_rows(spec: str) -> list[list[str]]:
    """§2 condensed to Moment · Enter · Reduce · Source (A-1)."""
    out = []
    for r in table_rows(section(spec, "## 2."), "M-0"):
        if len(r) != 9:
            continue
        mid, moment, prop, d, e, red, _carrier, _budget, src = r
        if d == "`motion.duration.instant`":
            enter = "a cut: " + prop.removeprefix("none: ")
        else:
            short = (d.strip("`").split(".")[-1], e.strip("`").split(".")[-1])
            enter = f"{prop} over `{short[0]}` / `{short[1]}`"
        reduce_ = "identical" if red == "identical, both modes" else red
        source = "; ".join([f"E12-D10 {mid}", *source_names(src)])
        out.append([f"{mid} {moment}", enter, reduce_, source])
    return out


def rules_line(spec: str) -> list[str]:
    return [
        f"**R-{n}** {title[0].lower()}{title[1:]}"
        for n, title in sorted(spec_rules(spec).items())
        if n >= 2
    ]


def pointer_line(spec: str) -> str | None:
    m = re.search(r'one pointer line, "Motion: ([^"]+)"', spec)
    return f"- **Motion:** {m[1]}" if m else None


def split_block(text: str) -> tuple[int, int, int, list[str]] | None:
    """The block's heading line, its end, its §7 number and the lines."""
    ls = text.split("\n")
    heads = [(i, m) for i, ln in enumerate(ls) if (m := BLOCK_HEAD.fullmatch(ln))]
    if len(heads) != 1:
        return None
    i, m = heads[0]
    j = next(
        (k for k in range(i + 1, len(ls)) if ls[k] == "---" or ls[k].startswith("## ")),
        len(ls),
    )
    return i, j, int(m[1]), ls


def g_applied(t: Texts, vals: dict[str, str]) -> list[str]:
    bad: list[str] = []
    t16, m16 = t.tree.get(PATHS["16"]), t.mb.get(PATHS["16"])
    t14, m14 = t.tree.get(PATHS["14"]), t.mb.get(PATHS["14"])
    if t16 is None or m16 is None or t14 is None or m14 is None:
        return ["cannot read `16` or `14` in the working tree or at the merge-base"]
    got = split_block(t16)
    if got is None:
        return ["A-1: `16` does not carry exactly one 'Chart bar-band motion (E12-D10; ...)' block"]
    i, j, n, ls = got
    if ls[:i] + ls[j:] != m16.split("\n"):
        bad.append(
            "A-1: `16` differs from its merge-base outside the block,"
            " or the block is not after the last §7 block"
        )
    if f"§7.{n}" != vals.get("APP:block"):
        bad.append(
            f"A-1: the block is §7.{n}; the next free number at the merge-base"
            f" is {vals.get('APP:block')}"
        )
    body = ls[i + 1 : j]
    if BLOCK_LEAD not in body:
        bad.append("A-1: the block's Spec / Tokens line is not the tool's")
    rows = [
        [c.strip() for c in ln.strip().strip("|").split("|")] for ln in body if ln.startswith("| ")
    ]
    want = [BLOCK_COLS, *block_rows(t.spec)]
    have = [r for r in rows if not all(set(c) <= {"-", ":"} for c in r)]
    for k in range(max(len(want), len(have))):
        w = want[k] if k < len(want) else None
        h = have[k] if k < len(have) else None
        if w != h:
            bad.append(f"A-1: table row {k} reads {h}, §2 renders {w}")
    rules = next((ln for ln in body if ln.startswith("Rules (E12-D10 §1.3")), "")
    for r in rules_line(t.spec):
        if r not in rules:
            bad.append(f"A-1: the block's rules do not name {r!r}")
    bad += anchor_problems(t, vals, "APP:")
    ptr = pointer_line(t.spec)
    m14l, t14l = m14.split("\n"), t14.split("\n")
    if ptr is None:
        bad.append("A-2: §15 carries no pointer line")
    else:
        a = next((k for k, ln in enumerate(m14l) if ln.startswith("### SCR-030 ")), None)
        b = next((k for k, ln in enumerate(m14l) if ln.startswith("### SCR-031 ")), None)
        if a is None or b is None:
            bad.append("A-2: the SCR-030 entry is not found at the merge-base")
        else:
            last = max(k for k in range(a, b) if m14l[k].strip())
            if t14l != [*m14l[: last + 1], ptr, *m14l[last + 1 :]]:
                bad.append(
                    "A-2: `14` is not its merge-base text with the pointer added once,"
                    " last in SCR-030"
                )
    return bad


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    return [
        f"{p} is touched; this ticket owns {', '.join(OWN_PATHS)}"
        for p in t.changed
        if p not in OWN_PATHS
    ]


def anchor_problems(t: Texts, vals: dict[str, str], prefix: str) -> list[str]:
    bad = []
    for value, key in ANCHOR.findall(t.spec):
        if key.startswith(prefix) and key in vals and vals[key] != value:
            bad.append(f"`{key}` reads {value}; the tool derives {vals[key]}")
    return bad


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-MOMENT": g_moment,
    "G-TOKEN": g_token,
    "G-BUDGET": g_budget,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene,
    "G-APPLIED": g_applied,
    "G-SCOPE": g_scope,
}


def audit(t: Texts) -> list[tuple[str, str]]:
    try:
        vals = compute(t)
    except LookupError as e:
        return [("G-BUDGET", str(e))]
    return [(g, msg) for g, fn in GATES.items() for msg in fn(t, vals)]


# ---------------------------------------------------------------------------- load, self-test


def changed_paths() -> list[str] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if not mb:
        return None
    a = git("diff", "--name-only", mb.strip())
    b = git("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    out |= {ln[3:].split(" -> ")[-1].strip('"') for ln in b.split("\n") if len(ln) > 3}
    return sorted(out)


def load() -> Texts:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    pins = (ROOT / PINS_REL).read_text(encoding="utf-8") if (ROOT / PINS_REL).exists() else ""
    mb = (git("merge-base", "HEAD", "origin/main") or "").strip()
    tree = {
        p: (ROOT / p).read_text(encoding="utf-8") if (ROOT / p).exists() else None for p in A_PATHS
    }
    base = {p: (git("show", f"{mb}:{p}") if mb else None) for p in A_PATHS}
    return Texts(spec, pins, changed_paths(), {}, tree, base)


def tree_sub(rel: str, old: str, new: str, count: int = 1) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = t.tree.get(rel) or ""
        if text.count(old) != count:
            raise SystemExit(f"self-test: {rel} carries {old[:50]!r} {text.count(old)} times")
        return replace(t, tree={**t.tree, rel: text.replace(old, new)})

    return f


def drop_tree_line(rel: str, lead: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = (t.tree.get(rel) or "").split("\n")
        return replace(
            t,
            tree={**t.tree, rel: "\n".join(ln for ln in ls if not ln.startswith(lead))},
        )

    return f


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times")
        return replace(t, spec=t.spec.replace(old, new))

    return f


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        return replace(
            t,
            spec="\n".join(ln for ln in t.spec.split("\n") if not ln.startswith(lead)),
        )

    return f


def set_cell(row: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
        cells = [c.strip() for c in ls[i].strip().strip("|").split("|")]
        cells[col] = value
        ls[i] = "| " + " | ".join(cells) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def blank_cell(row: str, col: int) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
        cells = [c.strip() for c in ls[i].strip().strip("|").split("|")]
        cells[col] = ""
        ls[i] = "| " + " | ".join(cells) + " |"
        return replace(t, spec="\n".join(ls))

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-MOMENT+G-APPLIED", "blank M-05's reduce cell", blank_cell("M-05", 5)),
    ("G-MOMENT+G-APPLIED", "drop moment (d)'s row", drop_row("| M-02 ")),
    (
        "G-TOKEN+G-APPLIED",
        "misspell a duration token",
        set_cell("M-07", 3, "`motion.duration.normel`"),
    ),
    (
        "G-BUDGET",
        "type 400 for the progress slack",
        sub("300<!--=BUD:progress.slack.ms-->", "400<!--=BUD:progress.slack.ms-->"),
    ),
    (
        "G-CITE",
        "re-point a `D08` cite one line off its pinned content",
        sub("(`D08`:258)", "(`D08`:257)"),
    ),
    (
        "G-CITE",
        "point a cite past the end of `14`",
        sub("(`14`:1121, SCR-046)", "(`14`:99999, SCR-046)"),
    ),
    (
        "G-TOKEN",
        "type a millisecond literal",
        sub(
            "0<!--=DUR:instant--> ms of engine frame time (§8)",
            "0 ms of engine frame time (§8)",
        ),
    ),
    (
        "G-HYGIENE",
        "write a closing keyword against #245",
        sub("carries the closing line;", "carries the closing line, Closes #245;"),
    ),
    (
        "G-SCOPE",
        "touch `15` in the diff",
        lambda t: replace(t, changed=[*OWN_PATHS, PATHS["15"]]),
    ),
    (
        "G-HYGIENE",
        "hard-code the `16` block as §7.3",
        sub("a `16` §7.n block, numbered at PR 2's rebase,", "a `16` §7.3 block,"),
    ),
    (
        "G-MOMENT",
        "drop M-06's view-as T2 naming",
        sub(
            "; its `Retry` under view-as T2 (§11); its `Cancel` is a read",
            "; its `Cancel` is a read",
        ),
    ),
    (
        "G-APPLIED",
        "edit M-07's Reduce cell in `16`",
        tree_sub(PATHS["16"], "steps: the fill jumps per sample", "a fade per sample"),
    ),
    (
        "G-APPLIED",
        "number the block one past the next free one",
        lambda t: tree_sub(
            PATHS["16"],
            f"### 7.{next_block(t.mb[PATHS['16']])} Chart bar-band",
            f"### 7.{(next_block(t.mb[PATHS['16']]) or 0) + 1} Chart bar-band",
        )(t),
    ),
    (
        "G-APPLIED",
        "record another number in §15",
        lambda t: replace(
            t, spec=re.sub(r"§7\.\d+<!--=APP:block-->", "§7.9<!--=APP:block-->", t.spec)
        ),
    ),
    (
        "G-APPLIED",
        "drop R-5 from the block's rules",
        tree_sub(PATHS["16"], "**R-5** dropped, never queued", "dropped, never queued"),
    ),
    (
        "G-APPLIED",
        "drop the SCR-030 pointer",
        drop_tree_line(PATHS["14"], "- **Motion:** `docs/design/E12/E12-D10.md`"),
    ),
    (
        "G-APPLIED",
        "add the pointer twice",
        lambda t: tree_sub(
            PATHS["14"],
            pointer_line(t.spec) or "?",
            (pointer_line(t.spec) or "?") + "\n" + (pointer_line(t.spec) or "?"),
        )(t),
    ),
    (
        "G-APPLIED",
        "edit a `16` line outside the block",
        tree_sub(PATHS["16"], "### 7.3 Node-graph motion", "### 7.3 Node graph motion"),
    ),
    (
        "G-APPLIED",
        "drop M-08's row from the block",
        drop_tree_line(PATHS["16"], "| M-08 "),
    ),
)


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = base.spec
    found = audit(base)
    out = [f"self-test: baseline {len(found)} FAIL"] + [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == sorted(gate.split("+"))  # a §2 edit also desyncs `16`'s rendered block
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E12-D10 motion audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = (
            "# E12-D10 cite pins: the cite, a hash of its cited line(s) at its base."
            " Written by --repin-ruled only.\n"
        )
        (ROOT / PINS_REL).write_text(
            head + "".join(f"{k}\t{h}\n" for k, h in hashes.items()), encoding="utf-8"
        )
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        print(
            json.dumps(
                {
                    "base": BASE,
                    "e47d08": E47_REF,
                    "values": compute(t),
                    "findings": [{"gate": g, "msg": m} for g, m in found],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for gate, msg in found:
            print(f"FAIL {gate}: {msg}")
        print(f"{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
