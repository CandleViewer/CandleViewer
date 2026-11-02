#!/usr/bin/env python3
"""E37-D04 (#949) audit: the accessibility design review of SCR-082's keyboard authoring strategy.

Standalone, offline, stdlib only; it runs no repo code and is run with `python3 -I`. It reads the
review and the pins file from the working tree, and every cited file AS TEXT with `git show`: the
plan docs, E37-D02, the design-spec rules, the keymap and E47-S03's keyboard core at the pinned
base (`BASE`); E37-D03 at #5448's head (`D03_REF`) until it merges (R6).
Default-deny: a gate that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-FINDING  §11's F rows in order; each severity from R-1's set; each closing "fix: A-n" with
             §12 carrying A-n, "accepted: ..." or "routed: ..."; no Blocking or Major without a
             fix; the counts in §11's heading equal the rows.
  G-MAP      the ticket's seventeen operations are K-01 ... K-17 in the ticket's order; every K
             row has a binding, an outline twin and an announcement.
  G-KEYMAP   every `X` (`rules.id`) binding in §4 equals the keymap's defaultBinding for that id
             at the base; no K row and no keymap rules.* row names an arm command.
  G-SCRIPT   every S row's quoted template stands on its cited line at its ref (`${x}` read as
             `{x}`).
  G-MOTION   the MOT anchors equal E37-D03 §7's motion rows and the rows with a reduce cell.
  G-AROW     every A-row's Old text or anchor stands exactly once across the parents it names.
  G-CITE     every cite in range and on a non-blank line at its ref, its content equal to the
             pins file's hash; the SHA anchors are the pinned refs.
  G-HYGIENE  no closing keyword, local path, URL or host, agent name, double-brace slot or
             public-text deny word in the review, this tool or the pins file; no unknown anchor.
  G-SCOPE    the diff against `git merge-base HEAD origin/main` touches only the review, this
             tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e37_d04_a11y_review_audit.py --check       (exit 1 on any FAIL)
  python3 -I docs/design/_tools/e37_d04_a11y_review_audit.py --json
  python3 -I docs/design/_tools/e37_d04_a11y_review_audit.py --self-test
  python3 -I docs/design/_tools/e37_d04_a11y_review_audit.py --repin-ruled
      (the pins file's only writer)
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
SPEC_REL = "docs/design/E37/E37-D04.md"
TOOL_REL = "docs/design/_tools/e37_d04_a11y_review_audit.py"
PINS_REL = "docs/design/_tools/e37_d04_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "67fe8b5265810d9d7928bdf4b56e4911f16fce54"  # origin/main when written
D03_REF = "fa8121d1b9601727a77d9c5013f4c5bbcfb87951"  # #5448's head (E37-D03 PR 2)
CORE = "apps/web/src/features/rule-builder-graph/a11y"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "D02": "docs/design/E37/E37-D02.md",
    "D03": "docs/design/E37/E37-D03.md",
    "DS": ".claude/rules/32-design-specs.md",
    "KEYMAP": "apps/web/src/keymap/keymap.json",
    "COPY": f"{CORE}/copy.ts",
    "PSEL": f"{CORE}/portSelection.ts",
    "TRAV": f"{CORE}/traversal.ts",
    "NUDGE": f"{CORE}/nudge.ts",
}
REF_OF = {"D03": D03_REF}
# the A-row headers name their parents in these words
PARENT_WORDS = {"E37-D02": "D02", "E37-D03": "D03", "`15`": "15", "`05`": "05", "`14`": "14"}
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
# the ticket's Scope list, in its order (T: "add node, delete node, ... simulate")
T_OPS = (
    "add node",
    "delete node",
    "rename",
    "connect",
    "disconnect",
    "select",
    "multi-select",
    "group",
    "auto-layout",
    "pan",
    "zoom",
    "open inspector",
    "jump to diagnostic",
    "switch editor",
    "save",
    "validate",
    "simulate",
)
DASH = "\u2013"  # the en dash of a cited range
KEYS = r"\d\d|D0[23]|DS|KEYMAP|COPY|PSEL|TRAV|NUDGE"
CITE = re.compile(rf"`({KEYS})`:(\d+(?:{DASH}\d+)?(?:, :\d+(?:{DASH}\d+)?)*)")
BINDING = re.compile(r"`([^`]+)` \(`(rules\.[a-z_]+)`\)")
ANCHOR = re.compile(r"`?([^\s<|(`]+)`?<!--=([A-Z]+:[A-Za-z0-9.]+)-->")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
ARM = re.compile(r"\brules\.arm|\bArm rule\b", re.IGNORECASE)
# assembled with an explicit +, so the formatter keeps the split and the tool never spells a word
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


@dataclass(frozen=True)
class Texts:
    spec: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        # git with fixed arguments and no shell; the only external program the audit runs
        r = subprocess.run(  # noqa: S603
            ["git", "-C", str(ROOT), *args],  # noqa: S607
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
    ref = REF_OF.get(key, BASE)
    text = show(t, ref, PATHS[key])
    if text is None:
        raise SystemExit(f"{PATHS[key]} does not resolve at {ref[:10]}; fetch #5448's head first")
    return text


def norm(s: str) -> str:
    return " ".join(s.split())


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(text: str, lead: str) -> list[list[str]]:
    return [cells(ln) for ln in text.split("\n") if re.match(rf"\| {lead}-\d+ ", ln)]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        return ""
    j = text.find("\n## ", i + 1)
    return text[i : j if j > 0 else len(text)]


def keymap(t: Texts) -> dict[str, str]:
    data = json.loads(at(t, "KEYMAP"))
    return {
        c["id"]: str(c.get("defaultBinding", ""))
        for c in data.get("commands", [])
        if str(c.get("id", "")).startswith("rules.")
    }


def motion_counts(t: Texts) -> tuple[int, int]:
    ms = rows(section(at(t, "D03"), "## 7. "), "M")
    return len(ms), sum(1 for r in ms if len(r) > 3 and r[3].strip())


def compute(t: Texts) -> dict[str, str]:
    v = {"SHA:BASE": BASE[:10], "SHA:D03": D03_REF[:10]}
    total, reduce = motion_counts(t)
    v["MOT:rows"], v["MOT:reduce"] = str(total), str(reduce)
    fs = rows(section(t.spec, "## 11."), "F")
    v["F:total"] = str(len(fs))
    for s in SEVERITIES:
        v[f"F:{s.lower()}"] = str(sum(r[1] == s for r in fs if len(r) > 1))
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
            bad.append(f"{label}: line {blank[0]} is blank at its ref")
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


def anchor_problems(t: Texts, vals: dict[str, str], prefix: str) -> list[str]:
    return [
        f"`{key}` reads {value}; the tool derives {vals[key]}"
        for value, key in ANCHOR.findall(t.spec)
        if key.startswith(prefix) and key in vals and vals[key] != value
    ]


def g_finding(t: Texts, vals: dict[str, str]) -> list[str]:
    fs = rows(section(t.spec, "## 11."), "F")
    arows = set(re.findall(r"\*\*(A-\d+) \u2192", section(t.spec, "## 12.")))
    bad = []
    if [r[0] for r in fs] != [f"F-{i:02d}" for i in range(1, len(fs) + 1)]:
        bad.append("§11's F rows are not F-01 ... F-n in order")
    for r in fs:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        fid, sev, _, _, closing, owner = r
        if sev not in SEVERITIES:
            bad.append(f"{fid}: severity {sev!r} is not one of {', '.join(SEVERITIES)}")
        fix = re.fullmatch(r"fix: (A-\d+)", closing)
        if fix and fix[1] not in arows:
            bad.append(f"{fid}: closes by {fix[1]}, which §12 does not carry")
        if not fix and not re.match(r"(accepted|routed): \S", closing):
            bad.append(
                f"{fid}: the closing {closing!r} is neither a fix, an acceptance nor a route"
            )
        if sev in ("Blocking", "Major") and not fix:
            bad.append(f"{fid}: a {sev} finding without a fix (R-2)")
        if not owner:
            bad.append(f"{fid}: no owner")
    return bad + anchor_problems(t, vals, "F:")


def g_map(t: Texts, vals: dict[str, str]) -> list[str]:
    ks = rows(section(t.spec, "## 4."), "K")
    bad = []
    if [r[0] for r in ks] != [f"K-{i:02d}" for i in range(1, len(ks) + 1)]:
        bad.append("§4's K rows are not K-01 ... K-n in order")
    for i, op in enumerate(T_OPS):
        if i >= len(ks) or len(ks[i]) < 2 or ks[i][1] != op:
            bad.append(f"K-{i + 1:02d} is not the ticket's operation {op!r}")
    for r in ks:
        if len(r) != 6:
            bad.append(f"{r[0]}: {len(r)} cells, not 6")
            continue
        for col, what in ((2, "binding"), (3, "outline twin"), (4, "announcement")):
            if not r[col].strip():
                bad.append(f"{r[0]}: no {what}")
    return bad


def g_keymap(t: Texts, vals: dict[str, str]) -> list[str]:
    km = keymap(t)
    bad = []
    for r in rows(section(t.spec, "## 4."), "K"):
        for chord, cid in BINDING.findall(" | ".join(r)):
            if cid not in km:
                bad.append(f"{r[0]}: `{cid}` is not a keymap command at the base")
            elif km[cid] != chord:
                bad.append(f"{r[0]}: `{cid}` binds {km[cid]!r} at the base, the map says {chord!r}")
        if ARM.search(" | ".join(r)):
            bad.append(f"{r[0]}: names an arm command (the editor's map has no arm key)")
    bad += [f"the keymap carries {cid}, an arm command" for cid in km if ARM.search(cid)]
    return bad


def g_script(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    for r in rows(section(t.spec, "## 5."), "S"):
        if len(r) != 5:
            bad.append(f"{r[0]}: {len(r)} cells, not 5")
            continue
        quote = re.fullmatch(r'"(.+)"', r[2])
        src = CITE.fullmatch(r[3])
        if not quote or not src:
            bad.append(f"{r[0]}: needs a quoted template and one cite")
            continue
        ls = at(t, src[1]).split("\n")
        n = int(src[2].split(DASH)[0])
        line = ls[n - 1].replace("${", "{") if 0 < n <= len(ls) else ""
        if quote[1] not in line:
            bad.append(f"{r[0]}: {quote[1][:40]!r} is not verbatim on {src[1]}:{n}")
    return bad


def g_motion(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = anchor_problems(t, vals, "MOT:")
    if vals["MOT:rows"] != vals["MOT:reduce"]:
        bad.append(
            f"D03 §7: {vals['MOT:rows']} motion rows, {vals['MOT:reduce']} with a reduce cell"
        )
    for key in ("MOT:rows", "MOT:reduce"):
        if f"<!--={key}-->" not in t.spec:
            bad.append(f"the review drops the {key} anchor")
    return bad


def g_arow(t: Texts, vals: dict[str, str]) -> list[str]:
    """Each A-row is copy-ready: its Old text or its anchor stands exactly once across the
    parents its header names, at their refs."""
    bad = []
    for ln in section(t.spec, "## 12.").split("\n"):
        m = re.match(r"- \*\*(A-\d+) \u2192 ([^*]+)\*\*", ln)
        if not m:
            continue
        aid = m[1]
        parents = [key for word, key in PARENT_WORDS.items() if word in m[2]]
        if not parents:
            bad.append(f"{aid}: names no parent")
            continue
        body = ln[m.end() :]
        anchors = re.findall(r'Old: "(.+?)"\. New:', body)
        anchors += re.findall(r'(?:[Aa]fter|[Bb]efore) "(.+?)"(?: \(its (?:row|line)\))? add', body)
        if not anchors:
            bad.append(f"{aid}: names neither an Old text nor an anchor")
        for a in anchors:
            n = sum(at(t, p).count(a) for p in parents)
            if n != 1:
                bad.append(f"{aid}: {a[:40]!r} stands {n} times across {', '.join(parents)}")
    return bad


def g_cite(t: Texts, vals: dict[str, str]) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its ref is not the pinned content")
    return bad + anchor_problems(t, vals, "SHA:")


def g_hygiene(t: Texts, vals: dict[str, str]) -> list[str]:
    bad = []
    checks = (
        (CLOSING, "a closing keyword (the closing line waits for the A-row PR)"),
        (LOCAL_PATH, "a local path"),
        (AGENT_NAME, "an agent name"),
        (URL_OR_HOST, "a URL or a host"),
    )
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
    for name, text in (("spec", t.spec), ("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY):
                bad.append(f"{name}:{i} carries a public-text deny word")
    for _, key in ANCHOR.findall(t.spec):
        if key not in vals:
            bad.append(f"an anchor `{key}` the tool does not compute")
    return bad


def g_scope(t: Texts, vals: dict[str, str]) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    return [
        f"{p} is touched; this ticket owns {', '.join(OWN_PATHS)}"
        for p in t.changed
        if p not in OWN_PATHS
    ]


GATES: dict[str, Callable[[Texts, dict[str, str]], list[str]]] = {
    "G-FINDING": g_finding,
    "G-MAP": g_map,
    "G-KEYMAP": g_keymap,
    "G-SCRIPT": g_script,
    "G-MOTION": g_motion,
    "G-AROW": g_arow,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene,
    "G-SCOPE": g_scope,
}


def audit(t: Texts) -> list[tuple[str, str]]:
    vals = compute(t)
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
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(
                f"self-test: the review carries {old[:50]!r} {t.spec.count(old)} times"
            )
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(row: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {row} "))
        c = cells(ls[i])
        c[col] = value
        ls[i] = "| " + " | ".join(c) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(row: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        return replace(
            t, spec="\n".join(x for x in t.spec.split("\n") if not x.startswith(f"| {row} "))
        )

    return f


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-FINDING", "a Major accepted with no fix", set_cell("F-03", 4, "accepted: browse mode")),
    (
        "G-FINDING",
        "a count typed by hand in §11's heading",
        sub("Major 7<!--=F:major-->", "Major 6<!--=F:major-->"),
    ),
    ("G-MAP", "the zoom row dropped", drop_row("K-11")),
    ("G-MAP", "K-15's announcement cell emptied", set_cell("K-15", 4, "")),
    (
        "G-KEYMAP",
        "K-09's chord retyped",
        sub("`Ctrl+L` (`rules.auto_layout`)", "`Ctrl+Shift+L` (`rules.auto_layout`)"),
    ),
    (
        "G-KEYMAP",
        "an arm command in K-17",
        set_cell("K-17", 2, "`Ctrl+Shift+A` arms the rule (rules.arm)"),
    ),
    (
        "G-SCRIPT",
        "one word changed in S-08's template",
        set_cell("S-08", 2, '"linked {A} output to {B} input {n}"'),
    ),
    (
        "G-MOTION",
        "the motion row count typed by hand",
        sub("19<!--=MOT:rows-->", "18<!--=MOT:rows-->"),
    ),
    (
        "G-AROW",
        "A-12's Old text off by one character",
        sub(
            'Old: "collapsed into the outline (the 24 px target stays)"',
            'Old: "collapsed into the outline (the 24px target stays)"',
        ),
    ),
    ("G-CITE", "a `D02` cite one line off its pinned content", sub("`D02`:282", "`D02`:283")),
    (
        "G-HYGIENE",
        "a closing keyword against #949",
        sub("nothing here claims it.", "nothing here claims it. Closes #949."),
    ),
    (
        "G-HYGIENE",
        "a deny word in the tool's own text",
        lambda t: replace(t, tool=t.tool + "\n# " + "fl" + "ood\n"),
    ),
    (
        "G-SCOPE",
        "a parent file in the diff",
        lambda t: replace(t, changed=[*OWN_PATHS, PATHS["D02"]]),
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
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    seen = {g for g, _, _ in MUTATIONS}
    missing = [g for g in GATES if g not in seen]
    ok &= not missing
    if missing:
        out.append(f"FAIL no mutation for {', '.join(missing)}")
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E37-D04 a11y review audit")
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
            "# E37-D04 cite pins: the cite, a hash of its cited line(s) at its ref."
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
                    "d03": D03_REF,
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
