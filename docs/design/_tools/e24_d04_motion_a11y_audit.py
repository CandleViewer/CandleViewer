#!/usr/bin/env python3
"""E24-D04 (#662) audit: the motion spec and accessibility review of the derivatives panel (SCR-054).

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
spec and the pins file from the working tree, and every cited file AS TEXT with `git show` at the
pinned base (`BASE`), except E47-D08, read at #5444's head (`E47D08_REF`) until it merges. Default-deny: a gate that cannot read its input FAILs. Shaped like E12-D10's
sibling tool (#245).

Gates (each FAIL led by its name):
  G-MOMENT   §2's rows M-01 ... M-07, in order, each complete: a property, a token or "a cut" in
             Duration and Easing, a reduce cell, a carrier, a cadence, a source.
  G-TOKEN    every `motion.*` name the spec writes resolves in `primitives.tokens.json` at the
             base; every DUR anchor is that token's value; no prose duration as a bare ms figure.
  G-BUDGET   every BUD anchor derived from the cited texts and the tokens, or ruled (the ticket's
             two numbers and the PROPOSED cascade threshold are named constants); the threshold's
             sentence says "PROPOSED to the owner".
  G-CADENCE  a §2 row whose Duration is a token and whose Cadence is "<n> ms" lasts no longer than
             n (nothing animates longer than the data's own period).
  G-LIVE     §9.2's rows LR-1 ... LR-8: a politeness of polite, assertive or off; a trigger and a
             throttle; LR-1 and LR-2 at 300000 and 60000 ms; LR-4 at most 1 per 5000 ms; an `off`
             row never triggers.
  G-ANNOT    §10's rows A-01 ...: a role, a name and a tab number each; panel stops nest under
             D02 §13's groups (0)-(5) as (g) or (g).n (BQ-18: extend, never renumber); P1 ... and
             K1 ... run without a gap ("—" for a non-stop); each row's T2 ids equal D03 §8's and
             the T2 paragraph names them (BQ-20).
  G-CITE     every cite in range and on a non-blank line at its base, and its content equal to the
             pins file's hash (a moved or edited line FAILs until re-pointed by content and
             `--repin-ruled` re-pins it); the SHA anchor is the pinned base.
  G-HYGIENE  no closing keyword, local path, URL or host, agent name, double-brace slot or
             public-text deny word in the spec; no deny word in this tool's text or the pins file;
             no unknown anchor key.
  G-SCOPE    the diff against `git merge-base HEAD origin/main` touches only the spec, this tool
             and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e24_d04_motion_a11y_audit.py --check      (exit 1 on any FAIL)
  python3 -I docs/design/_tools/e24_d04_motion_a11y_audit.py --json       (values and findings)
  python3 -I docs/design/_tools/e24_d04_motion_a11y_audit.py --self-test  (one mutation per gate, at least)
  python3 -I docs/design/_tools/e24_d04_motion_a11y_audit.py --repin-ruled (the pins file's only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E24/E24-D04.md"
TOOL_REL = "docs/design/_tools/e24_d04_motion_a11y_audit.py"
PINS_REL = "docs/design/_tools/e24_d04_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "e5b286ed50d3a320d80b24df5030fb09dd405a4a"  # origin/main when written (re-pinned by content)
E47D08_REF = "307dffee24811c9fd7a99d7753c427573e858b13"  # #5444's head; re-pinned to main at its merge
TOK_REL = "packages/ui/tokens/primitives.tokens.json"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "D02": "docs/design/E24/E24-D02.md",
    "D03": "docs/design/E24/E24-D03.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E11D06": "docs/design/E11/E11-D06.md",
    "E47D08": "docs/design/E47/E47-D08.md",
}
REF_OF = {"E47D08": E47D08_REF}  # every other key is read at BASE
T_FLASH_MAX_MS = 120  # T Scope: "value-change flash on OI/funding (<=120 ms ...)"
T_THROTTLE_MS = (
    5000  # T AC "Cascade announcements": "at most one summary every 5 seconds"
)
CASCADE_THRESHOLD = 10  # PROPOSED here (§5, G-1): prints/s over the last 1 000 ms
CITE = re.compile(
    r"`(\d\d|D0[23]|E05D03|E11D06|E47D08)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE
)
LOCAL_PATH = re.compile(
    "/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b"
)  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
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
)  # each entry an explicit `+` join, so the tool's own text carries none of the words
POLITENESS = ("polite", "assertive", "off")
PROSE_MS = re.compile(
    r"\b(?:lasts|for|over)\s+\d[\d ]*\s?ms\b"
)  # a duration as a bare figure (BQ-22)
# BQ-20: each annotation row's T2 ids, and a word its D03 §8 control cell must carry (`D03`:240-247)
T2_EXPECTED: dict[str, tuple[tuple[str, str], ...]] = {
    "A-03": (("T2-8", "table toggle"),),
    "A-07": (("T2-6", "basis"),),
    "A-08": (("T2-5", "mode toggles"),),
    "A-09": (("T2-6", "collapse chevron"),),
    "A-13": (("T2-8", "Retry"), ("T2-3", "Recording settings")),
    "A-16": (("T2-5", "mode toggles"), ("T2-6", "collapse chevron")),
    "A-17": (("T2-8", "Pause"),),
    "A-19": (("T2-8", "Retry"), ("T2-3", "Recording settings")),
    "A-20": (("T2-5", "mode toggles"), ("T2-6", "collapse chevron"), ("T2-8", "Retry")),
    "A-21": (("T2-6", "Restore"),),
    "A-22": (("T2-4", "display rows"),),
    "A-23": (("T2-1", "Estimated zones"),),
    "A-24": (("T2-2", "Alert me"),),
    "A-25": (("T2-7", "notional"),),
    "A-26": (("T2-4", "Reset to defaults"),),
    "A-27": (("T2-8", "Cancel"),),
}


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False
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
    ref = REF_OF.get(key, BASE)
    text = show(t, ref, PATHS[key])
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {ref[:10]}; fetch first")
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
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


# ---------------------------------------------------------------------------- values


def find(t: Texts, key: str, rx: str) -> str:
    m = re.search(rx, at(t, key))
    if not m:
        raise LookupError(f"`{key}` no longer carries /{rx}/ at its base")
    return m[1]


def durations(t: Texts) -> dict[str, int]:
    raw = show(t, BASE, TOK_REL)
    if raw is None:
        raise SystemExit(f"{TOK_REL} does not resolve at the base")
    out = {}
    for k, v in json.loads(raw).items():
        if k.startswith("motion.duration.") and isinstance(v, dict):
            out[k.split(".")[-1]] = int(str(v["$value"]).removesuffix("ms"))
    return out


def tokens(t: Texts) -> set[str]:
    raw = show(t, BASE, TOK_REL) or "{}"
    return {k for k in json.loads(raw) if k.startswith("motion.")}


def compute(t: Texts) -> dict[str, str]:
    v: dict[str, str] = {"SHA:BASE": BASE[:10], "SHA:E47D08": E47D08_REF[:9]}
    dur = durations(t)
    for k, ms in dur.items():
        v[f"DUR:{k}"] = str(ms)
    timer_s = int(find(t, "D02", r"one shared (\d+) s timer"))
    data_hz = int(find(t, "14", r"arrive at low frequency \(<=(\d+) Hz\)"))
    bucket = int(find(t, "14", r"coalesced into (\d+) ms buckets"))
    script = int(find(t, "14", r"exceed (\d+) ms scripting per frame"))
    rate = int(find(t, "14", r"target: (\d+) prints/s"))
    secs = int(find(t, "14", r"sustained for (\d+) s"))
    hs1 = int(find(t, "E05D03", r"At least (\d+) ms between flash starts"))
    fr5 = re.search(r"\| FR-5 +\|[^|]+\| (\d+) per ([\d ]+) ms", at(t, "E47D08"))
    fr3 = re.search(r"\| FR-3 +\|[^|]+\| (\d+) +\|", at(t, "E47D08"))
    if not fr5 or not fr3:
        raise LookupError("`E47D08` no longer carries FR-3 / FR-5 at its ref")
    data_ms = 1000 // data_hz
    v.update({
        "BUD:countdown.ms": str(timer_s * 1000), "BUD:data.ms": str(data_ms),
        "BUD:flash.max.ms": str(T_FLASH_MAX_MS), "BUD:flash.room.ms": str(T_FLASH_MAX_MS - dur["fast"]),
        "BUD:hs1.ms": str(hs1), "BUD:flash.per.s": str(1000 // max(data_ms, hs1)),
        "BUD:bucket.ms": str(bucket), "BUD:bucket.cap.starts": str(2 * (1000 // bucket)),
        "BUD:fr5.starts": fr5[1], "BUD:fr5.ms": fr5[2].replace(" ", ""), "BUD:fr3.starts": fr3[1],
        "BUD:cascade.threshold": str(CASCADE_THRESHOLD),
        "BUD:cascade.rate": str(rate), "BUD:cascade.s": str(secs), "BUD:script.ms": str(script),
        "BUD:throttle.ms": str(T_THROTTLE_MS),
        "BUD:cascade.summaries": str(math.ceil(secs * 1000 / T_THROTTLE_MS)),
        "BUD:cascade.prints": str(rate * secs),
    })  # fmt: skip
    return v


# ---------------------------------------------------------------------------- cites


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition("–")
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec):
        label = f"{key}:{a}" if a == b else f"{key}:{a}–{b}"
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
        joined = norm(ls[a - 1]) + "\n" + norm(ls[b - 1])
        hashes[label] = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


# ---------------------------------------------------------------------------- gates


def moment_rows(t: Texts) -> list[list[str]]:
    return table_rows(section(t.spec, "## 2."), "M-0")


def g_moment(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = moment_rows(t)
    bad = []
    if [r[0] for r in rows] != [f"M-0{i}" for i in range(1, 8)]:
        bad.append(f"§2's rows are {[r[0] for r in rows]}, not M-01 ... M-07 in order")
    for r in rows:
        if len(r) != 9:
            bad.append(f"{r[0]}: {len(r)} cells, not 9")
            continue
        _, _, prop, d, e, red, carrier, cadence, src = r
        if not prop:
            bad.append(f"{r[0]}: no property")
        if d != "a cut" and not re.fullmatch(r"`motion\.duration\.[a-z]+`", d):
            bad.append(f"{r[0]}: Duration {d!r} is neither a token nor 'a cut'")
        if e != "a cut" and not re.fullmatch(r"`motion\.easing\.[a-z]+`", e):
            bad.append(f"{r[0]}: Easing {e!r} is neither a token nor 'a cut'")
        for cell, what in ((red, "reduced-motion equivalent"), (carrier, "carrier"),
                           (cadence, "cadence"), (src, "source")):  # fmt: skip
            if not cell:
                bad.append(f"{r[0]}: no {what}")
    return bad


def g_token(t: Texts, vals: dict[str, str]) -> list[str]:
    known = tokens(t)
    names = sorted(set(re.findall(r"`(motion\.[a-z.]+[a-z])`", t.spec)))
    bad = [f"`{n}` does not resolve in {TOK_REL}" for n in names if n not in known]
    bad += anchor_problems(t, vals, "DUR:")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if PROSE_MS.search(ln):
            bad.append(
                f"spec:{i} writes a duration as a bare ms figure; use the token (BQ-22)"
            )
    return bad


def g_budget(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = anchor_problems(t, vals, "BUD:")
    for ln in t.spec.split("\n"):
        if "BUD:cascade.threshold" in ln and "PROPOSED to the owner" not in ln:
            bad.append(
                "the cascade threshold is not marked PROPOSED to the owner (BQ-10)"
            )
    return bad


def g_cadence(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for r in moment_rows(t):
        if len(r) != 9:
            continue
        m = re.fullmatch(r"`motion\.duration\.([a-z]+)`", r[3])
        c = re.fullmatch(r"(\d+) ms", r[7])
        if m and c:
            ms = int(vals.get(f"DUR:{m[1]}", "-1"))
            if ms < 0 or ms > int(c[1]):
                bad.append(f"{r[0]}: {m[1]} ({ms} ms) outlasts its {c[1]} ms cadence")
    return bad


def g_live(t: Texts, vals: dict[str, str]) -> list[str]:
    rows = table_rows(section(t.spec, "### 9.2"), "LR-")
    bad = []
    if [r[0] for r in rows] != [f"LR-{i}" for i in range(1, 9)]:
        bad.append(f"§9.2's rows are {[r[0] for r in rows]}, not LR-1 ... LR-8")
    by = {r[0]: r for r in rows}
    for r in rows:
        if len(r) != 7:
            bad.append(f"{r[0]}: {len(r)} cells, not 7")
            continue
        _, _, pol, trig, thr, _, _ = r
        if pol not in POLITENESS:
            bad.append(f"{r[0]}: politeness {pol!r} is not polite, assertive or off")
        if not trig or not thr:
            bad.append(f"{r[0]}: no trigger or no throttle")
        if pol == "off" and not trig.startswith("never"):
            bad.append(f"{r[0]}: an `off` row that triggers")
        if pol != "off" and trig.startswith("never"):
            bad.append(f"{r[0]}: a {pol} row that never triggers")
    for lr, ms in (("LR-1", "300000 ms"), ("LR-2", "60000 ms")):
        if lr in by and ms not in by[lr][3]:
            bad.append(f"{lr}: the trigger does not name {ms}")
    if "LR-4" in by and f"at most 1 per {T_THROTTLE_MS} ms" not in by["LR-4"][4]:
        bad.append(f"LR-4: the throttle is not 'at most 1 per {T_THROTTLE_MS} ms'")
    return bad


PANEL_TAB = re.compile(r"\((\d)\)(?:\.(\d+))?")


def g_annot(t: Texts, vals: dict[str, str]) -> list[str]:
    """Panel stops nest under D02's groups (0)-(5) as (g) or (g).n, a range written (g).a … (g).b;
    the groups never go back, every group appears, and each group's n run 1.. without a gap.
    The popover and dialog run P1 ... and K1 ... (BQ-18)."""
    rows = table_rows(section(t.spec, "## 10."), "A-")
    bad: list[str] = []
    if not rows:
        return ["§10 has no annotation rows"]
    d03_t2 = {r[0]: r[1] for r in table_rows(at(t, "D03"), "T2-") if len(r) > 1}
    par = re.search(r"\*\*T2 rows \(BQ-20[^\n]*", section(t.spec, "## 10."))
    if not par:
        bad.append("§10 has no T2 paragraph (BQ-20)")
    t2_par = par[0] if par else ""
    groups: list[int] = []
    subs: dict[int, list[int]] = {}
    seqs: dict[str, list[int]] = {}
    for r in rows:
        if len(r) != 8:
            bad.append(f"{r[0]}: {len(r)} cells, not 8")
            continue
        _, _, role, name, tab, _, _, t2 = r
        want = T2_EXPECTED.get(r[0], ())
        got = re.findall(r"T2-\d", t2)
        if sorted(got) != sorted(i for i, _ in want):
            bad.append(f"{r[0]}: T2 {got} is not D03 §8's {[i for i, _ in want]}")
        for t2id, word in want:
            if word not in d03_t2.get(t2id, ""):
                bad.append(f"{r[0]}: D03 §8's {t2id} does not name {word!r}")
        if want and r[0] not in t2_par:
            bad.append(f"{r[0]}: a T2 row the T2 paragraph does not name")
        if not role:
            bad.append(f"{r[0]}: no role")
        if not name:
            bad.append(f"{r[0]}: no accessible name")
        pk = re.findall(r"([PK])(\d+)(?: … [PK](\d+))?", tab)
        hits = PANEL_TAB.findall(tab)
        if tab == "—":
            continue
        if pk:
            for pre, a, b in pk:
                seqs.setdefault(pre, []).extend(range(int(a), int(b or a) + 1))
        elif hits and PANEL_TAB.sub("", tab).strip(" …") == "":
            g = {int(h[0]) for h in hits}
            if len(g) != 1:
                bad.append(f"{r[0]}: tab {tab!r} spans two groups")
                continue
            grp = g.pop()
            groups.append(grp)
            ns = [int(h[1]) for h in hits if h[1]]
            if len(ns) == 2:
                ns = list(range(ns[0], ns[1] + 1))
            subs.setdefault(grp, []).extend(ns)
        else:
            bad.append(f"{r[0]}: tab number {tab!r} is not (g), (g).n, Pn or Kn")
    if groups != sorted(groups) or sorted(set(groups)) != list(range(6)):
        bad.append(f"the panel groups run {groups}, not (0) ... (5) in order")
    for grp, ns in subs.items():
        if ns != list(range(1, len(ns) + 1)):
            bad.append(f"group ({grp}) runs {ns}: a gap or out of order")
    for pre, ns in seqs.items():
        if sorted(ns) != list(range(1, max(ns) + 1)):
            bad.append(f"the {pre} tab sequence {ns} has a gap or runs out of order")
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(
                f"cite {label} is unpinned: verify it by content, then --repin-ruled"
            )
        elif pinned[label] != h:
            bad.append(
                f"cite {label}: the line at its base is not the pinned content (moved or edited)"
            )
    bad += anchor_problems(t, vals, "SHA:")
    return bad


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #662)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
        if any(d in ln.lower() for d in DENY):
            bad.append(f"spec:{i} carries a public-text deny word")
    for label, text in (("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{label}:{i} carries a public-text deny word")
    for _, key in ANCHOR.findall(t.spec):
        if key not in vals:
            bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = ", ".join(OWN_PATHS)
    return [
        f"{p} is touched; this ticket owns {own}"
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
    "G-MOMENT": g_moment, "G-TOKEN": g_token, "G-BUDGET": g_budget, "G-CADENCE": g_cadence,
    "G-LIVE": g_live, "G-ANNOT": g_annot, "G-CITE": g_cite, "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}  # fmt: skip


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
    pins = (
        (ROOT / PINS_REL).read_text(encoding="utf-8")
        if (ROOT / PINS_REL).exists()
        else ""
    )
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(
                f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times"
            )
        return replace(t, spec=t.spec.replace(old, new))

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


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-MOMENT", "blank M-03's reduce cell", set_cell("M-03", 5, "")),
    ("G-TOKEN", "misspell a duration token", set_cell("M-05", 3, "`motion.duration.normel`")),
    ("G-BUDGET", "type 4 for the bucket cap's starts", sub("8<!--=BUD:bucket.cap.starts-->", "4<!--=BUD:bucket.cap.starts-->")),
    ("G-CADENCE", "give M-04 the slow token against its 250 ms cadence", set_cell("M-04", 3, "`motion.duration.slow`")),
    ("G-LIVE", "make LR-3 polite", set_cell("LR-3", 2, "polite")),
    ("G-ANNOT", "remove A-09's tab number", set_cell("A-09", 4, "")),
    ("G-CITE", "re-point a `D03` cite to an unpinned line", sub("`E11D06`:94; `D03`:459", "`E11D06`:94; `D03`:465")),
    ("G-HYGIENE", "write a closing keyword against #662", sub("carries the closing line.", "carries the closing line. Closes #662.")),
    ("G-SCOPE", "touch `16` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["16"]])),
    ("G-TOKEN", "write a prose duration as a bare figure", sub("The emphasis lasts `motion.duration.fast`,", "The emphasis lasts 150 ms,")),
    ("G-ANNOT", "drop the T2 paragraph", lambda t: replace(t, spec=re.sub(r"\n\*\*T2 rows \(BQ-20[^\n]*\n", "\n", t.spec))),
    ("G-ANNOT", "mark A-13 as T2-6", set_cell("A-13", 7, "T2-6")),
    ("G-BUDGET", "drop PROPOSED from the cascade threshold", sub("**The cascade threshold (PROPOSED to the owner, G-1).**", "**The cascade threshold (G-1).**")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[6] + "\n")),
)  # fmt: skip


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = base.spec
    found = audit(base)
    out = [f"self-test: baseline {len(found)} FAIL"] + [
        f"  baseline {g}: {m}" for g, m in found
    ]
    ok = not found
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
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
    ap = argparse.ArgumentParser(description="E24-D04 motion and accessibility audit")
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
        head = "# E24-D04 cite pins: the cite, a hash of its cited line(s) at its base. Written by --repin-ruled only.\n"
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    if a.json:
        doc = {
            "base": BASE,
            "values": compute(t),
            "findings": [{"gate": g, "msg": m} for g, m in found],
        }
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for gate, msg in found:
            print(f"FAIL {gate}: {msg}")
        print(f"{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
