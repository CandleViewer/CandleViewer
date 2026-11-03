#!/usr/bin/env python3
"""E37-Q01 (#1066) check: the node-graph editor's black-box test plan against its sources.

Standalone, offline, stdlib only; it runs under `python3 -I`, executes no repo code and starts no
process. It reads AS TEXT the plan (`qa/plans/e37-node-editor-test-plan.md`), `11` section 20, the
Gherkin of `E37.json`, the copy deck (`docs/design/E37/E37-D05-copy-deck.jsonl`) and the files of
`tests/fixtures/e37/`; cases, quotes and derived tables are re-computed on every run.

Gates (mutations in `--self-test`, each caught by its own gate only):
  G-TRACE    the 64 scenario titles equal the sources', each has a case; Cases and Auto equal
             what the case rows derive.
  G-CASE     case rows: eight cells, contiguous ids, numbered steps, evidence; K-01 to K-25.
  G-COPY     every quote equals the deck's text and letter; frozen strings quoted; the connect grid.
  G-MATRIX   13 states x 4 roles with a code and a case; a denial says 403, no state change, audit.
  G-FIX      handles defined and used; owed toggles and fixtures in Needs; fixture files exist.
  G-TAG      Auto uses the closed vocabulary; E37-Q02's ten specs each map to a case.
  G-EVENT    every event a case names is in the events table.
  G-HYGIENE  no placeholder, local path, agent name, URL, closing keyword or avoided word in the
             plan, the fixtures' README and this file.

Usage (from the repo root):
  python3 -I qa/plans/_tools/e37_q01_plan_check.py --check [--json]
  python3 -I qa/plans/_tools/e37_q01_plan_check.py --self-test
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN_REL = "qa/plans/e37-node-editor-test-plan.md"
DECK_REL = "docs/design/E37/E37-D05-copy-deck.jsonl"
FIX_REL = "tests/fixtures/e37"
TRUNCATED = "corrupt_ir_truncated.json"
LETTER = {"merged": "M", "RULED": "R", "PROPOSED": "P"}
CASE = re.compile(r"^(E37-TC-([A-G])(\d\d))(?: (\[R\]))? (\S.*)$")
CODE = re.compile(r"\b(U[1-6]\.\d|S0[1-5]\.\d|T02\.\d)\b")
QUOTE = re.compile(r'"([^"]*)" \[([a-z0-9_.]+)(?: · ([MRP]))?\]')
EVIDENCE = re.compile(r"(?:\b(?:HAR|SS|A11Y|AUD|MET|ANA|T)\b(?:, )?)+\.$")
AUTO = re.compile(r"Q02-(?:10|[1-9])|Q02\+|Q03|Q04|Q05|X02|man")
HANDLE = re.compile(
    r"\b(?:OWNER|MGR-(?:A|B|SIM)|VIEWER-1|ACC-\d|SYM-(?:NO)?REC|RC-\d\d"
    r"|(?<!US-)(?:RULE|FX)-[A-Z0-9]+(?:-[A-Z0-9]+)*|FT-[A-Z]+)\b"
)
EVENT = re.compile(r"\b(?:rule\.[a-z_]+|rbac\.denied|rule_graph_[a-z_]+)\b")
DENIED = "403 · no state change · one `rbac.denied` audit row"
_AVOID = (
    "previous" + "ly",
    "le" + "ak",
    "cou" + "ld",
    "by" + "pass",
    "expo" + "sed",
    "allo" + "wed",
)
HYGIENE = (
    ("a placeholder", re.compile("TO" + "DO|T" + "BD|FIX" + "ME|XX" + "X|" + r"\{" + r"\{")),
    ("a local path", re.compile("/ho" + "me/|/tm" + "p/|/mn" + "t/")),
    ("an agent name", re.compile(r"\b[a-z]{2,4}-wor" + r"ker-\d\b|virta" + "rix")),
    ("a URL", re.compile("https?:" + "//")),
    ("a closing keyword", re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.I)),
    ("a word the public text avoids", re.compile("|".join(_AVOID), re.I)),
)


@dataclass(frozen=True)
class Texts:
    plan: str
    deck: str
    us: str
    e37: str
    files: dict[str, str]
    tool: str


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    num: int
    flagged: bool
    cells: tuple[str, ...]


# ------------------------------------------------------------------------------------- parsing


def table(text: str) -> list[list[str]]:
    rows = [
        [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip())[1:-1]] for ln in text.split("\n")
    ]
    return [r for r in rows if r and not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]


def section(text: str, head: str) -> str:
    """The table lines under the heading that starts with `head`, up to the next heading."""
    lines = text.split("\n")
    level = len(head) - len(head.lstrip("#"))
    start = next((i for i, ln in enumerate(lines) if ln.startswith(head)), len(lines))
    stop = next(
        (j for j in range(start + 1, len(lines)) if re.match("#{1," + str(level) + "} ", lines[j])),
        len(lines),
    )
    return "\n".join(x for x in lines[start + 1 : stop] if x.startswith("|"))


def parse_cases(plan: str) -> list[Case]:
    found = [
        (CASE.match(r[0]), r) for r in table("\n".join(x for x in plan.split("\n") if x[:1] == "|"))
    ]
    return [Case(m[1], m[2], int(m[3]), bool(m[4]), tuple(r)) for m, r in found if m]


def scenarios(t: Texts) -> list[tuple[str, str, str]]:
    sec = t.us.split("## 20. RULE", 1)[1].split("\n## 21.", 1)[0]
    out: list[tuple[str, str, str]] = []
    for sid, code in (("001", "U1"), ("002", "U2"), ("003", "U3"), ("005", "U5"), ("006", "U6")):
        m = re.search(rf"(?ms)^#### US-RULE-{sid} .*?(?=^#### US-RULE-|\Z)", sec)
        found = re.findall(r"(?m)^Scenario: (.+)$", m[0]) if m else []
        out += [(f"{code}.{i}", f"US-RULE-{sid}", x) for i, x in enumerate(found, 1)]
    bodies = {str(x["key"]): str(x["body"]) for x in json.loads(t.e37)}
    for key in [f"E37-S0{n}" for n in range(1, 6)] + ["E37-T02"]:
        ac = bodies[key].split("## Acceptance criteria", 1)[1].split("\n## ", 1)[0]
        found = re.findall(r"(?m)^Scenario: (.+)$", ac)
        out += [(f"{key[4:].replace('-', '')}.{i}", key, x) for i, x in enumerate(found, 1)]
    return out


def deck_rows(t: Texts) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """key -> (text, status letter or ""), and the keys the plan must quote (the frozen strings)."""
    deck: dict[str, tuple[str, str]] = {}
    must: set[str] = set()
    for r in [json.loads(x) for x in t.deck.split("\n") if x.strip()][1:]:
        where = str(r.get("where", ""))
        m = re.search(r"string (merged|RULED|PROPOSED)", where)
        letter = LETTER[r["status"]] if r.get("list") == "rows" else LETTER[m[1]] if m else ""
        deck[r["key"]] = (r["text"], letter)
        if r.get("frozen") or "frozen by E36-D05" in where:
            must.add(r["key"])
    return deck, must


def derive(cases: list[Case]) -> dict[str, tuple[list[str], list[str]]]:
    got: dict[str, tuple[list[str], list[str]]] = {}
    for c in cases:
        for code in dict.fromkeys(CODE.findall(c.cells[1])):
            ids, autos = got.setdefault(code, ([], []))
            ids.append(c.id)
            autos += [a for a in re.split(r", *", c.cells[6]) if a and a not in autos]
    return got


# --------------------------------------------------------------------------------------- gates


def g_trace(t: Texts) -> list[str]:
    cases, want = parse_cases(t.plan), scenarios(t)
    rows = table(section(t.plan, "## 14. "))
    trace = [r for r in rows if CODE.fullmatch(r[0])]
    got = derive(cases)
    problems = (
        [] if [r[0] for r in trace] == [w[0] for w in want] else ["the scenario codes differ"]
    )
    for r, (code, src, title) in zip(trace, want, strict=False):
        ids, autos = got.get(code, ([], []))
        if r[1:3] != [src, title]:
            problems.append(f"{code}: source or title differs from {src}")
        if not ids:
            problems.append(f"{code} has no case")
        elif r[3:5] != [", ".join(ids), ", ".join(autos)]:
            problems.append(f"{code}: Cases or Auto differ from the case rows")
    return problems


def g_case(t: Texts) -> list[str]:
    cases = parse_cases(t.plan)
    ids = {c.id for c in cases}
    problems = []
    for g in "ABCDEFG":
        nums = [c.num for c in cases if c.group == g]
        if not nums or nums != list(range(1, len(nums) + 1)):
            problems.append(f"group {g}: ids are not 01..n in order")
    for c in cases:
        steps = [int(n) for n in re.findall(r"(?:^|(?<=\s))(\d{1,2})\. (?=[A-Z`\"(])", c.cells[3])]
        if len(c.cells) != 8 or not all(c.cells) or steps != list(range(1, len(steps) + 1)):
            problems.append(f"{c.id}: not eight filled cells or steps not numbered 1..n")
        elif not EVIDENCE.search(c.cells[4]):
            problems.append(f"{c.id}: Expected does not end in evidence codes")
    keys = [r for r in table(section(t.plan, "## 11. ")) if re.fullmatch(r"K-\d\d", r[0])]
    if [r[0] for r in keys] != [f"K-{n:02d}" for n in range(1, 26)]:
        problems.append("the keyboard inventory is not K-01..K-25")
    for r in keys:
        cited = set(re.findall(r"E37-TC-[A-G]\d\d", r[5]))
        if len(r) != 7 or r[6] or not cited or not cited <= ids:
            problems.append(f"{r[0]}: seven cells, an empty Result and existing cases are expected")
    return problems


def g_copy(t: Texts) -> list[str]:
    deck, must = deck_rows(t)
    plan = t.plan.replace("\\|", "|")
    quotes = QUOTE.findall(plan)
    problems = [f"{k}: unknown key, or the quote or status differs" for x, k, p in quotes
                if deck.get(k) != (x, p)]  # fmt: skip
    problems += [f"{k} is never quoted" for k in sorted(must - {q[1] for q in quotes})]
    rows = table(section(plan, "## 10. "))
    cells = [
        (r[0].strip("*"), to, c)
        for r in rows[1:]
        for to, c in zip(rows[0][1:], r[1:], strict=False)
    ]
    problems += [f"grid {a} to {b} differs" for a, b, c in cells
                 if deck.get(f"rules.graph.connect.{a}.{b}", ("", ""))[0] != c]  # fmt: skip
    return problems + ([] if len(cells) == 36 else [f"the grid holds {len(cells)} cells, not 36"])


def g_matrix(t: Texts) -> list[str]:
    ids = {c.id for c in parse_cases(t.plan)}
    rows = [r for r in table(section(t.plan, "## 8. ")) if r[0].isdigit()]
    problems = [] if [r[0] for r in rows] == [str(n) for n in range(1, 14)] else ["not 13 states"]
    for r in rows:
        for role, cell in zip(("OWNER", "MGR-A", "MGR-SIM", "VIEWER-1"), r[2:], strict=False):
            where = f"state {r[0]} {role}"
            if len(r) != 6 or not re.match(r"(?:W|Ws|RO|NR) · ", cell):
                problems.append(f"{where}: a code is expected")
            if not set(re.findall(r"E37-TC-[A-G]\d\d", cell)) & ids:
                problems.append(f"{where}: no existing case")
            if (role == "VIEWER-1" or "403" in cell) and DENIED not in cell:
                problems.append(f"{where}: a denial says '{DENIED}'")
            if role == "VIEWER-1" and "E37-TC-G05" not in cell:
                problems.append(f"{where}: cite E37-TC-G05")
    return problems


def g_fix(t: Texts) -> list[str]:
    sec = section(t.plan, "## 13. ")
    status = {
        h: "exists" if h[:3] == "RC-" else r[-1] for r in table(sec) for h in HANDLE.findall(r[0])
    }
    use = [(c, " ".join(c.cells[2:5])) for c in parse_cases(t.plan)]
    used = {h for c, body in use for h in HANDLE.findall(f"{body} {c.cells[7]}")}
    problems = [f"{h} is used but not defined in section 13" for h in sorted(used - set(status))]
    problems += [f"{h} is defined but unused" for h in sorted(set(status) - used) if h[:3] != "RC-"]
    for c, body in use:
        for h in HANDLE.findall(body):
            before = h in HANDLE.findall(c.cells[2])
            needs = h[:3] == "FT-" or (before and h[:3] in ("FX-", "RUL"))
            if status.get(h, "").startswith("owed") and needs and h not in c.cells[7]:
                problems.append(f"{c.id}: {h} is owed and missing from Needs")
    for n in sorted(set(re.findall(rf"{FIX_REL}/([\w.]+)", sec))):
        if n not in t.files:
            problems.append(f"{FIX_REL}/{n} is missing")
        elif n.endswith(".json"):
            try:
                json.loads(t.files[n])
                parses = True
            except json.JSONDecodeError:
                parses = False
            if parses == (n == TRUNCATED):
                problems.append(f"{n} {'must not parse' if parses else 'does not parse'}")
    return problems


def g_tag(t: Texts) -> list[str]:
    cases = parse_cases(t.plan)
    problems = [f"{c.id}: Auto '{c.cells[6]}' is outside the vocabulary" for c in cases
                if not all(AUTO.fullmatch(a) for a in re.split(r", *", c.cells[6]))]  # fmt: skip
    have = {r[0]: r[2] for r in table(section(t.plan, "## 14. ")) if re.fullmatch(r"Q02-\w+", r[0])}
    for n in range(1, 11):
        ids = ", ".join(c.id for c in cases if re.search(rf"\bQ02-{n}\b(?!\d)", c.cells[6]))
        problems += (
            [] if ids and have.get(f"Q02-{n}") == ids else [f"Q02-{n}: no case, or table 2 differs"]
        )
    return problems


def g_event(t: Texts) -> list[str]:
    known = {e for r in table(section(t.plan, "## 12. ")) for e in EVENT.findall(r[0])}
    return [f"{c.id}: {e} is not in section 12" for c in parse_cases(t.plan)
            for e in EVENT.findall(c.cells[5]) if e not in known]  # fmt: skip


def g_hygiene(t: Texts) -> list[str]:
    texts = (("plan", t.plan), ("README", t.files.get("README.md", "")), ("tool", t.tool))
    found = [
        f"{n}: {what} {m[0]!r}" for n, x in texts for what, rx in HYGIENE for m in rx.finditer(x)
    ]
    return found[:20]


GATES: tuple[tuple[str, Callable[[Texts], list[str]]], ...] = (
    ("G-TRACE", g_trace),
    ("G-CASE", g_case),
    ("G-COPY", g_copy),
    ("G-MATRIX", g_matrix),
    ("G-FIX", g_fix),
    ("G-TAG", g_tag),
    ("G-EVENT", g_event),
    ("G-HYGIENE", g_hygiene),
)


def run(t: Texts) -> list[tuple[str, str]]:
    return [(name, msg) for name, gate in GATES for msg in gate(t)]


def counts(t: Texts) -> str:
    cases = parse_cases(t.plan)
    by = " ".join(f"{g}{sum(c.group == g for c in cases)}" for g in "ABCDEFG")
    q = QUOTE.findall(t.plan.replace("\\|", "|"))
    p, m = sum(x[2] == "P" for x in q), sum(len(r) == 6 for r in table(section(t.plan, "## 8. ")))
    return (
        f"counts: cases {len(cases)} ({by}); regression {sum(c.flagged for c in cases)}; "
        f"matrix cells {4 * (m - 1)}; scenarios {len(scenarios(t))}; quotes {len(q)} (P {p}, "
        f"{len({x[1] for x in q})} deck keys)"
    )


# -------------------------------------------------------------------------------- self-test


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def sub(gate: str, what: str, old: str, new: str, every: bool = False) -> Mutation:
    def f(t: Texts) -> Texts:
        if old not in t.plan:
            raise SystemExit(f"self-test: the plan lacks {old[:70]!r}")
        return replace(t, plan=t.plan.replace(old, new, -1 if every else 1))

    return Mutation(gate, what, f)


def file_text(gate: str, what: str, name: str, text: str) -> Mutation:
    return Mutation(gate, what, lambda t: replace(t, files={**t.files, name: text}))


# fmt: off
MUTATIONS = (
    sub("G-TRACE", "a title drifts", "001 | Round trip |", "001 | Round trips |"),
    sub("G-CASE", "no evidence codes", "available · P]. A11Y.", "available · P]."),
    sub("G-CASE", "a key row is renumbered", "| K-07 |", "| K-70 |"),
    sub("G-COPY", "a quote loses a letter", '"Start from a trigger" [', '"Start from a trigge" ['),
    sub("G-COPY", "a grid cell is reworded", "number can't run an action.", "number can't run it."),
    sub("G-MATRIX", "a denial drops its 403", "write: 403 · no state", "write: no state"),
    sub("G-FIX", "an undefined handle",
        "| OWNER; an empty draft; the", "| OWNER; FX-NOPE; an empty draft; the"),
    sub("G-FIX", "a toggle leaves Needs", "| Q02-9 | FT-VOCAB |", "| Q02-9 | none |"),
    file_text("G-FIX", "the truncated file parses", TRUNCATED, "{}"),
    sub("G-TAG", "a tag leaves the vocabulary", "Q02-10", "Q02-11", every=True),
    sub("G-EVENT", "an unknown event", "rejected` | Q02-5", "nope` | Q02-5"),
    sub("G-HYGIENE", "an avoided word", "# E37 node-graph", "# E37 le" + "ak node-graph"),
)
# fmt: on


def selftest(base: Texts) -> tuple[bool, list[str]]:
    t0 = time.perf_counter()
    fails = run(base)
    out = [f"self-test: baseline {len(fails)} FAIL"] + [
        f"  baseline {g}: {m}" for g, m in fails[:5]
    ]
    ok, hit = not fails, set()
    for i, m in enumerate(MUTATIONS, 1):
        got = sorted({g for g, _ in run(m.apply(base))})
        ok &= got == [m.gate]
        hit |= {m.gate} if got == [m.gate] else set()
        mark = "ok  " if got == [m.gate] else "FAIL"
        out.append(f"{mark} M-{i} {m.gate}: {m.what} -> {', '.join(got) or 'none'}")
    missed = sorted({n for n, _ in GATES} - hit)
    ok &= not missed
    n = f"{len(MUTATIONS)} mutations over {len(GATES)} gates"
    out.append(f"self-test: {n}, missed {', '.join(missed) or 'none'}; texts restored: yes")
    out.append(f"self-test: {'PASS' if ok else 'FAIL'} in {time.perf_counter() - t0:.1f} s")
    return ok, out


def load() -> Texts:
    def read(rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    files = {p.name: p.read_text(encoding="utf-8") for p in sorted((ROOT / FIX_REL).glob("*"))}
    tool = Path(__file__).resolve().read_text(encoding="utf-8")
    us, e37 = read("docs/plan/11-user-stories.md"), read("docs/plan/backlog/E37.json")
    return Texts(read(PLAN_REL), read(DECK_REL), us, e37, files, tool)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="the default mode")
    mode.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", action="store_true", help="--check's dump")
    a = ap.parse_args(argv)
    t = load()
    if a.self_test:
        ok, lines = selftest(t)
        print("\n".join(lines))
        return 0 if ok else 1
    found = run(t)
    if a.json:
        print(json.dumps([{"gate": g, "msg": m} for g, m in found], ensure_ascii=False, indent=2))
    else:
        print("\n".join(f"FAIL {g}: {m}" for g, m in found))
        print(f"{counts(t)}\n{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
