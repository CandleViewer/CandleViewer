#!/usr/bin/env python3
"""E41-D01 (#1017) audit: the journal research memo, its session protocol and the 17 journey.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads
the plan documents AS TEXT at the pinned base (`git show BASE:<path>`) and the memo, the protocol,
`17` and `14` from the working tree. Default-deny: a cite, a component id, a URL or a frame the
tool does not know FAILs.

Gates (each prints `FAIL G-NAME: ...`):
  G-CITE     every `NN`:line cite is registered in CITES and its needle stands at that line;
             a cite in another shape (a space, an ASCII hyphen range) FAILs as malformed
  G-RULE     every C-x.y rule id exists in CONSTITUTION.md at the base
  G-AC       the AC trace carries AC1..AC3 and six DoD rows, each with a known status word
  G-FIND     5-8 findings F-1..F-n, each `(heuristic)`, each -> an existing WD; every WD reached
  G-WD       each WD names a listed frame, a Given/then check and an owner ticket; all 4 SCRs
  G-STATES   the frame list covers `14`'s States lines, the checklist states, no-match and error
  G-COMP     every CMP id the memo names is a heading in `15` at the base
  G-ADVICE   the copy deck exists; no imperative or evaluative word in it (AC3)
  G-HEUR     no participant count, observation or quote is claimed
  G-PUBLIC   no host, local path, uuid, workspace name or secret-shaped string; URLs allow-listed
  G-BQ       the BQ heading is RULED with the ruling comment, the body names the BQ list comment,
             the ruling's terms are folded (Partial memo PR, boards PR closes, interim rulings);
             BQ-1..BQ-16 each have a row
  G-BOARDS   the boards table exists; at most ten boards, each PENDING or drawn
  G-WALK     the owner walkthrough has at most ten items
  G-COMMENT  no HTML comment in the memo or the protocol
  G-17       `17` carries the section 1.6 journey; `14` carries no E41-D01 pointer (an A-row)
  G-SCOPE    only this PR's files differ from `git merge-base HEAD origin/main`; the ruling keeps
             `12`, `13`, `14` and `24` unedited (their changes are A-rows)

Usage: python3 -I docs/design/_tools/e41_d01_audit.py --check
       python3 -I docs/design/_tools/e41_d01_audit.py --self-test
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "46e6acd2ddf3835580a801ac9b143d32f4478090"
MEMO = "docs/design/research/e41-journal-review.md"
PROTOCOL = "docs/design/research/e41-d01-session-protocol.md"
UX17 = "docs/plan/17-ux-diagrams.md"
SCR14 = "docs/plan/14-screens-catalogue.md"
TOOL = "docs/design/_tools/e41_d01_audit.py"
ALLOWED_CHANGES = {MEMO, PROTOCOL, UX17, TOOL}
BQ_COMMENT = "6563728342"
RULING_COMMENT = "6563817618"
RULING_TERMS = (
    "`Refs #1017` + `Partial:`",
    "the research-boards PR closes #1017",
    "becomes an interim ruling on the orchestrator's design approval",
    "the owner can reverse by one line",
    "is an A-row (§8), not an edit",
)

KEYS: dict[str, str] = {
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "10": "docs/plan/10-personas.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "13": "docs/plan/13-user-flows.md",
    "14": SCR14,
    "15": "docs/plan/15-component-catalogue.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
}

# `KEY`:LINE (or `KEY`:A-B) -> a needle that must stand on that line (or inside the range).
CITES: dict[str, str] = {
    "04:81": "| A-12 | Journal & analytics",
    "04:350": "Journal exports contain account identifiers",
    "04:976": "| SR-098 | Exports (journal, analytics, audit) MUST be role-scoped",
    "05:17": "## 2. Principles mapped to trading UI (POUR)",
    "05:90": "### 3.4 Focus management in dense layouts",
    "05:105": "## 4. Colour-independence",
    "05:114": "P&L: colour + explicit `+`/`-` sign",
    "05:156": "### 6.3 Layer 3 — Data-table alternative",
    "10:16": "| P3 | **Viewer / analyst**",
    "10:101": "**Post-mortem (evening):** filters the journal",
    "10:112": "**P2b Swing manager**",
    "10:164": "journal tables, analytics",
    "10:168": "**Quarterly review:** filters the journal by date",
    "11:4628": "NFR: tags are per user",
    "11:4644": "I may remove an auto tag",
    "11:4664": "the trade is still journaled",
    "11:4680": "marked as bar-derived",
    "11:4697": "live, paper and replay results are never mixed",
    "11:4700": "explicit low-sample caveat",
    "11:4737": "visually marked as low-confidence",
    "11:4754": "offers bar-level replay if bars remain",
    "11:4774": "the export contains only my own trades",
    "11:4780": "no secrets or API identifiers are ever included",
    "12:86": "| R-181 | `/journal/:tradeId`",
    "12:223": "| M-019 | Drawer | Journal trade quick-note | Journal list row",
    "12:229": "| M-025 | Modal | Export journal/analytics",
    "13:388": "M-019 Journal trade quick-note drawer",
    "13:398": "Not enough closed trades for this view yet",
    "13:406": "are the only modal/drawer surfaces in this flow",
    "14:2154": "**Route:** `/journal`. **RBAC:** all (scoped to accessible accounts)",
    "14:2169": '**States:** loading · empty ("No trades in this range")',
    "14:2175": "DEMO and LIVE trades are visibly separated and never aggregated",
    "14:2179": "**Type:** Page/Drawer. Everything about one trade",
    "14:2195": "CMP-169 TagEditor",
    "14:2197": "'context not recorded' state",
    "14:2198": "`journal.screenshot_exported`",
    "14:2199": "[ ] 'context not recorded' state",
    "14:2201": "### SCR-095 — Journal analytics dashboard",
    "14:2205": "Fewer than 20 trades — statistics are noisy",
    "14:2206": "every chart has a table alternative and text summary",
    "14:2211": "'12 trades - not statistically meaningful'",
    "14:2215": "by regime at entry",
    "14:2216": "tag names unique, ≤24 chars",
    "14:2222": "[ ] empty state",
    "15:2098": "### CMP-166 JournalEntryRow",
    "15:2127": "### CMP-167 JournalEquityCurveChart",
    "15:2129": "may use the same series primitive (CMP-181) in a minimal pane",
    "15:2136": "### CMP-168 JournalStatsSummaryCard",
    "15:2147": "`readOnlyTags?: string[]` (rule-auto-tags, non-removable by hand",
    "21:3307": "plus one aggregate row with `is_aggregate = true`",
    "21:3315": "is_aggregate         boolean",
    "21:3318-3319": "is_paper             boolean",
    "21:3379": "CREATE UNIQUE INDEX ux_jtag_name ON journal_tags (lower(name))",
    "22:9657": "items: { type: string, maxLength: 40 }",
    "22:9840": "name: { type: string, minLength: 1, maxLength: 40 }",
    "22:9864": "breakdowns by symbol, tag, session hour",
    "22:9877": "enum: [symbol, tag, hour_of_day, day_of_week, side, account, setup]",
    "22:22310": "JournalTrade:",
}

URL_HOSTS = {"help.tradervue.com", "edgewonk.zendesk.com", "tradersync.com"}
ADVICE_RE = re.compile(
    r"\b(should|must|consider|try|avoid|improve|better|worse|best|worst|good|bad|great|poor"
    r"|recommend(ed)?|needs?|ought|you|your|edge|winning|losing streak|stop trading|don't|do not)\b",
    re.IGNORECASE,
)
HEUR_BANNED = (
    r"\bparticipants? (said|reported|told|preferred|chose|found|struggled)",
    r"\b(\d+|one|two|three) of (\d+|two|three) (participants|sessions)",
    r"\bin (the|our) sessions?,? (we|participants|users) (saw|observed|found)",
    r"\btook (\d+|about \d+) ?(s|sec|seconds|min|minutes) to\b",
    r"\bP[1-4]\w* said\b",
)
PUBLIC_BANNED = (
    r"/home/|\blocalhost\b|\b\d{1,3}(\.\d{1,3}){3}\b",
    r"(?i:\bpenpot\.[a-z]|\brelay\.[a-z])|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-",
    r"\b(ghp_|gho_|sk-|AKIA)[A-Za-z0-9]{8,}|(?i:\b(api[_-]?key|secret|password)\s*[:=])",
    r"(?i:-worker-\d|\bscratch-[a-z]|\brelayroom\b)",
)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
CITE_RE = re.compile(r"`(\d{2})`:(\d+)(?:–(\d+))?")
LOOSE_CITE_RE = re.compile(r"`\d{2}`\s*:\s*\d+(?:[-–]\d+)?")
RULE_RE = re.compile(r"\bC-\d+\.\d+\b")
URL_RE = re.compile(r"https?://([^/\s`)]+)[^\s`)]*")
FRAME_RE = re.compile(r"\b(SCR-09[3-6])/([a-z-]+)")
STATUS_WORDS = ("done", "heuristic-only", "substituted", "open")
POINTER = "- **UX research (E41-D01):** [e41-journal-review.md]"


@dataclasses.dataclass
class Docs:
    memo: str
    protocol: str
    ux17: str
    scr14: str
    changed: list[str]


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


@cache
def base_text(path: str) -> str:
    return git("show", f"{BASE}:{path}")


def section(text: str, prefix: str) -> str:
    """The body of the first `## ` or `### ` section whose heading starts with prefix."""
    m = re.search(rf"^#{{2,3}} {re.escape(prefix)}.*?$", text, re.MULTILINE)
    if not m:
        return ""
    level = text[m.start() :].split(" ", 1)[0]
    rest = text[m.end() :]
    stop = re.search(rf"^#{{2,{len(level)}}} ", rest, re.MULTILINE)
    return rest[: stop.start()] if stop else rest


def rows(body: str) -> list[list[str]]:
    """Table body rows (header and separator dropped) as stripped cells."""
    out: list[list[str]] = []
    for line in body.splitlines():
        if not line.startswith("|") or re.match(r"^\|[\s|:-]+\|$", line):
            continue
        out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:] if out else out


def g_cite(d: Docs) -> list[str]:
    fails = []
    for doc in (d.memo, d.protocol):
        fails += [
            f"malformed cite {m.group(0)!r}"
            for m in LOOSE_CITE_RE.finditer(doc)
            if not CITE_RE.fullmatch(m.group(0))
        ]
        for m in CITE_RE.finditer(doc):
            key, a, b = m.group(1), int(m.group(2)), m.group(3)
            tag = f"{key}:{a}" + (f"-{b}" if b else "")
            if key not in KEYS:
                fails.append(f"unknown cite key `{key}`")
                continue
            needle = CITES.get(tag)
            if needle is None:
                fails.append(f"unregistered cite `{key}`:{a}{'–' + b if b else ''}")
                continue
            lines = base_text(KEYS[key]).splitlines()
            span = "\n".join(lines[a - 1 : int(b) if b else a])
            if needle not in span:
                fails.append(f"needle not at `{key}`:{a}: {needle!r}")
    return fails


def g_rule(d: Docs) -> list[str]:
    const = base_text("CONSTITUTION.md")
    ids = set(RULE_RE.findall(d.memo + d.protocol))
    return [f"rule id {r} not in CONSTITUTION.md" for r in sorted(ids) if f"**{r}" not in const]


def g_ac(d: Docs) -> list[str]:
    trace = rows(section(d.memo, "Acceptance-criteria trace"))
    fails = [
        f"AC trace lacks {k}"
        for k in ("AC1", "AC2", "AC3")
        if not any(r[0].startswith(k) for r in trace)
    ]
    if sum(r[0].startswith("DoD") for r in trace) != 6:
        fails.append("AC trace must carry the six DoD rows")
    for r in trace:
        if len(r) < 3 or not r[2].startswith(STATUS_WORDS):
            fails.append(f"AC row without a status word: {r[0][:40]}")
    return fails


def wd_ids(d: Docs) -> dict[str, list[str]]:
    return {
        r[0]: r for r in rows(section(d.memo, "6. Wireframe decisions")) if r[0].startswith("WD-")
    }


def g_find(d: Docs) -> list[str]:
    finds = [r for r in rows(section(d.memo, "5. Findings")) if r[0].startswith("F-")]
    wds = wd_ids(d)
    fails = []
    if not 5 <= len(finds) <= 8:
        fails.append(f"{len(finds)} findings; the ticket asks for 5-8")
    if [r[0] for r in finds] != [f"F-{i}" for i in range(1, len(finds) + 1)]:
        fails.append("findings are not numbered F-1..F-n")
    reached: set[str] = set()
    for r in finds:
        if "(heuristic)" not in r[1]:
            fails.append(f"{r[0]} is not marked (heuristic)")
        targets = re.findall(r"WD-\d+", r[-1])
        if not targets or any(t not in wds for t in targets):
            fails.append(f"{r[0]} maps to no existing WD")
        reached.update(targets)
    fails += [f"{w} is reached by no finding" for w in wds if w not in reached]
    return fails


def frames(d: Docs) -> set[str]:
    out: set[str] = set()
    for r in rows(section(d.memo, "7. Frames per screen")):
        out.update(f"{r[0]}/{f.strip()}" for f in r[1].split("·"))
    return out


def g_wd(d: Docs) -> list[str]:
    fails, screens, listed = [], set(), frames(d)
    for wid, r in wd_ids(d).items():
        m = FRAME_RE.search(r[2]) if len(r) > 4 else None
        if not m or f"{m.group(1)}/{m.group(2)}" not in listed:
            fails.append(f"{wid} names no listed frame")
        else:
            screens.add(m.group(1))
        if len(r) < 5 or "Given" not in r[3] or "then" not in r[3]:
            fails.append(f"{wid} has no Given/then check")
        if len(r) < 5 or not re.search(r"#\d{3,5}", r[4]):
            fails.append(f"{wid} names no owner ticket")
    fails += [
        f"no WD on {s}" for s in ("SCR-093", "SCR-094", "SCR-095", "SCR-096") if s not in screens
    ]
    return fails


def states_14(scr: str) -> set[str]:
    block = base_text(SCR14).split(f"### {scr} ")[1].split("\n### ")[0]
    m = re.search(r"^- \*\*States:\*\* (.*)$", block, re.MULTILINE)
    if not m:
        return set()
    names = (re.sub(r"\s*\(.*", "", s).strip(" .") for s in m.group(1).split(" · "))
    return {re.sub(r"\s+", "-", n.lower()) for n in names}


def g_states(d: Docs) -> list[str]:
    need = {f"SCR-093/{s}" for s in states_14("SCR-093")} | {
        f"SCR-095/{s}" for s in states_14("SCR-095")
    }
    if len(need) != 7:
        return [f"`14` States lines parsed to {len(need)} states, expected 7"]
    need |= {
        "SCR-094/context-not-recorded",
        "SCR-096/empty",
        "SCR-093/no-match",
        "SCR-095/no-match",
    }
    need |= {f"SCR-09{i}/error" for i in (3, 4, 5, 6)}
    return [f"frame list lacks {f}" for f in sorted(need - frames(d))]


def g_comp(d: Docs) -> list[str]:
    known = set(re.findall(r"^### (CMP-\d{3}) ", base_text(KEYS["15"]), re.MULTILINE))
    used = set(re.findall(r"\bCMP-\d{3}\b", d.memo))
    return [f"{c} is not in `15`" for c in sorted(used - known)]


def g_advice(d: Docs) -> list[str]:
    deck = rows(section(d.memo, "7.1 Copy deck"))
    fails = [] if deck else ["no copy deck rows"]
    for r in deck:
        fails += [f"copy {r[0]} uses {m.group(0)!r}" for m in ADVICE_RE.finditer(r[-1])]
    return fails


def g_heur(d: Docs) -> list[str]:
    text = d.memo + d.protocol + section(d.ux17, "1.6 ")
    return [
        f"claims an observation: /{p}/" for p in HEUR_BANNED if re.search(p, text, re.IGNORECASE)
    ]


def g_public(d: Docs) -> list[str]:
    text = "\n".join((d.memo, d.protocol, section(d.ux17, "1.6 ")))
    fails = [f"URL host {h} not allow-listed" for h in URL_RE.findall(text) if h not in URL_HOSTS]
    fails += [f"public-repo pattern /{p}/" for p in PUBLIC_BANNED if re.search(p, text)]
    hexes = set(re.findall(r"\b[0-9a-f]{32,}\b", text)) - {BASE}
    return fails + [f"long hex string {h[:8]}..." for h in sorted(hexes)]


def g_bq(d: Docs) -> list[str]:
    ok = re.search(
        rf"^## BQ list — RULED \(comment {RULING_COMMENT}\)$",
        d.memo,
        re.MULTILINE,
    )
    fails = [] if ok else [f"BQ heading must be RULED (comment {RULING_COMMENT})"]
    body = section(d.memo, "BQ list")
    if f"comment {BQ_COMMENT}" not in body:
        fails.append(f"BQ section must name the BQ list comment {BQ_COMMENT}")
    fails += [f"ruling term missing: {term!r}" for term in RULING_TERMS if term not in body]
    if "later push of this PR" in d.memo:
        fails.append("the boards are drawn in the research-boards PR, not this PR")
    have = {r[0] for r in rows(body)}
    return fails + [f"BQ-{i} has no row" for i in range(1, 17) if f"BQ-{i}" not in have]


def g_boards(d: Docs) -> list[str]:
    boards = rows(section(d.memo, "0. Wireframe boards"))
    if not boards:
        return ["no Wireframe boards table"]
    fails = [f"{len(boards)} boards; the cap is ten"] if len(boards) > 10 else []
    return fails + [
        f"board {r[0]} is neither PENDING nor drawn"
        for r in boards
        if r[-1] not in ("PENDING", "drawn")
    ]


def g_walk(d: Docs) -> list[str]:
    items = re.findall(r"^(\d+)\. ", section(d.memo, "10. Owner session protocol"), re.MULTILINE)
    if not items or len(items) > 10 or items != [str(i) for i in range(1, len(items) + 1)]:
        return [f"walkthrough has {len(items)} items (1..10, in order)"]
    return []


def g_comment(d: Docs) -> list[str]:
    return [
        f"HTML comment in {n}"
        for n, t in (("memo", d.memo), ("protocol", d.protocol))
        if COMMENT_RE.search(t)
    ]


def g_17(d: Docs) -> list[str]:
    body = section(d.ux17, "1.6 Review journey")
    fails = [] if "```mermaid\njourney" in body else ["`17` lacks the section 1.6 journey"]
    if any(ln.startswith(POINTER) for ln in d.scr14.splitlines()):
        fails.append("`14` must carry no E41-D01 pointer line (ruled: an A-row, not an edit)")
    return fails


def g_scope(d: Docs) -> list[str]:
    return [f"out-of-scope change: {p}" for p in sorted(set(d.changed) - ALLOWED_CHANGES)]


GATES: dict[str, Callable[[Docs], list[str]]] = {
    "G-" + fn.__name__[2:].upper(): fn
    for fn in (g_cite, g_rule, g_ac, g_find, g_wd, g_states, g_comp, g_advice, g_heur, g_public)
    + (g_bq, g_boards, g_walk, g_comment, g_17, g_scope)
}


def load() -> Docs:
    def read(p: str) -> str:
        return (ROOT / p).read_text(encoding="utf-8")

    mb = git("merge-base", "HEAD", "origin/main").strip()
    changed = (
        git("diff", "--name-only", mb).split()
        + git("ls-files", "--others", "--exclude-standard").split()
    )
    return Docs(read(MEMO), read(PROTOCOL), read(UX17), read(SCR14), changed)


def run(d: Docs) -> list[tuple[str, str]]:
    out = []
    for name, gate in GATES.items():
        try:
            out += [(name, msg) for msg in gate(d)]
        except (RuntimeError, IndexError) as exc:
            out.append((name, f"gate error: {exc}"))
    return out


# (gate, document, anchor, replacement): each must add FAILs from exactly that gate.
MUTATIONS: list[tuple[str, str, str, str]] = [
    ("G-CITE", "memo", "(`11`:4628)", "(`11`:4629)"),
    ("G-CITE", "memo", "(`11`:4628)", "(`11` :4628)"),
    ("G-RULE", "memo", "(C-1.2)", "(C-1.99)"),
    ("G-AC", "memo", "| AC3 —", "| AX3 —"),
    ("G-FIND", "memo", "double-counts (heuristic)", "double-counts"),
    ("G-WD", "memo", "| SCR-095/low-bucket ", "| SCR-095/low-confidence "),
    ("G-STATES", "memo", "partial · reconciling ·", "partial ·"),
    ("G-COMP", "memo", "CMP-075,", "CMP-999,"),
    ("G-ADVICE", "memo", "| No trades in this range ", "| No trades yet, you should trade "),
    ("G-ADVICE", "memo", "### 7.1 Copy deck", "### 7.1 Copy list"),
    (
        "G-HEUR",
        "protocol",
        "## 5. Recording",
        "Two of three participants said so.\n\n## 5. Recording",
    ),
    (
        "G-PUBLIC",
        "memo",
        "## 11. Security",
        "See `https://penpot.example.org/f`.\n\n## 11. Security",
    ),
    ("G-PUBLIC", "protocol", "## 5. Recording", "Notes sit in a scratch-dir.\n\n## 5. Recording"),
    ("G-BQ", "memo", "RULED (comment 6563817618)", "defaults built; ruling pending"),
    ("G-BQ", "memo", "the owner can reverse by one line", "the owner may reverse it"),
    ("G-BQ", "memo", "## 11. Security", "Drawn in a later push of this PR.\n\n## 11. Security"),
    ("G-BOARDS", "memo", "| 10  | keyboard", "| 11  | extra | PENDING |\n| 10  | keyboard"),
    ("G-BOARDS", "memo", "## 0. Wireframe boards", "## 0. Boards"),
    ("G-WALK", "memo", "10. Rule OQ-1", "11. Rule OQ-1"),
    ("G-COMMENT", "protocol", "## 1. Purpose", "<!--\nnote\n-->\n\n## 1. Purpose"),
    ("G-17", "ux17", "### 1.6 Review journey", "### 1.6 Review map"),
    ("G-17", "scr14", "### SCR-094 —", POINTER + "(x)\n\n### SCR-094 —"),
    ("G-SCOPE", "changed", "", "docs/plan/22-api-openapi.yaml"),
    ("G-SCOPE", "changed", "", SCR14),
]


def mutate(d: Docs, field: str, old: str, new: str) -> Docs:
    if field == "changed":
        return dataclasses.replace(d, changed=[*d.changed, new])
    text = getattr(d, field)
    if old not in text:
        raise ValueError(f"mutation anchor missing in {field}: {old!r}")
    return dataclasses.replace(d, **{field: text.replace(old, new, 1)})


def self_test(d: Docs) -> int:
    if run(d):
        print("self-test: the baseline is not clean; run --check first")
        return 1
    bad = 0
    for i, (gate, field, old, new) in enumerate(MUTATIONS, 1):
        hit = {name for name, _ in run(mutate(d, field, old, new))}
        ok = hit == {gate}
        bad += not ok
        print(
            f"M-{i:<2} {gate:<10} {'ok' if ok else 'BAD -> ' + (','.join(sorted(hit)) or 'none')}"
        )
    missing = set(GATES) - {m[0] for m in MUTATIONS}
    if missing:
        print(f"self-test: gates without a mutation: {sorted(missing)}")
        bad += 1
    print(f"self-test {'ok' if not bad else 'FAILED'} ({len(MUTATIONS)} mutations)")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv not in (["--check"], ["--self-test"]):
        print(__doc__)
        return 2
    docs = load()
    if argv == ["--self-test"]:
        return self_test(docs)
    fails = run(docs)
    for name, msg in fails:
        print(f"FAIL {name}: {msg}")
    print(f"e41_d01_audit: {len(GATES)} gates, FAIL {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
