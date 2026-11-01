#!/usr/bin/env python3
"""E21-D01 (#417) audit: the UX-research memo on how traders read a ladder and a liquidity trail.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show BASE:path`), every document the memo cites by key, the E21
ticket JSON (this ticket's body is the source of the scenario names and the probe wording) and the
published issue map; it reads the same paths at `origin/main` for G-VERSION; then the memo and
`14` from the working tree.

Default-deny: a cite key the tool does not declare, an id nobody defines, a section heading the
tool does not expect, an HTML comment, a URL outside the competitive review, a changed path outside
this PR's three files and a `14` edit other than the one SCR-050 pointer line all FAIL.

Gates:
  G-SECTIONS  the H2 headings, in order (the BQ heading in its pending or its RULED form).
  G-MARKER    no HTML comment and no `[//]: #` comment anywhere in the memo.
  G-CITE      every `KEY`:N or `KEY`:N-M cite names a declared key and resolves at BASE.
  G-VERSION   every cited range at BASE stands, contiguous, in the file at `origin/main`.
  G-QUOTE     every double-quoted string of QUOTE_MIN characters or more outside the
              competitive review is verbatim in a source its own line cites or in the ticket;
              every competitive row that quotes carries an https URL; quotes pair on each line.
  G-AC        the three scenario names stand verbatim in the AC trace and in the ticket.
  G-BQ        BQ-0..BQ-14, once each; the heading names the posted BQ comment.
  G-TESTABLE  AD-1..AD-10 in order; each row has a satisfies clause and a violates clause and
              no aesthetic-only word (LEXICON_AESTHETIC).
  G-HEURISTIC every F row is `(heuristic)`; no participant, count, timing or attributed quote.
  G-DEFAULTS  the centring, placement, axis, trail, tier and pulled rows carry the BQ list's
              ORCH-defaults, a persona rationale and the deciding probe.
  G-IDS       every id referenced is defined once (a table row's lead cell, or `Hn:`).
  G-OWNER     every `E21-Xnn #N` pair matches the published map; owner cells name a ticket or
              the owner, never an agent.
  G-KILL      every kill-list row has a number and a verdict; the heading names #1 and #14.
  G-FLAG      the flag state names both flags and routes the undefined one to a G row.
  G-BOARDS    at most eight research boards, each PENDING, named `E21-D01 / NN slug`.
  G-WALK      the owner walkthrough has one to ten items and ends on `approved` on #417.
  G-PUBLIC    no local path, host, worker name or secret-shaped string; no URL outside the
              competitive review; no image embed (no third-party screenshot).
  G-UNTOUCHED only the memo, this tool and `14` differ from the merge base; `14` gains exactly
              the SCR-050 pointer line after its DES-HEATMAP-01 line.

`--check` runs the gates on the working tree; `--self-test` first requires FAIL 0, then applies
every mutation in MUTATIONS in memory (texts, `origin/main` copies and the changed-path list) and
requires each to add at least one FAIL from the gate it names; the memo on disk is never written.
The report is ASCII, every line at most 100 characters.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "46e6acd2ddf3835580a801ac9b143d32f4478090"
MAIN_REF = "origin/main"
MEMO_REL = "docs/design/research/e21-dom-heatmap.md"
TOOL_REL = "docs/design/_tools/e21_d01_research_audit.py"
CAT_REL = "docs/plan/14-screens-catalogue.md"
TICKET_JSON = "docs/plan/backlog/E21.json"
PUBLISHED_JSON = "docs/plan/backlog/_tools/published.json"
TICKET_KEY = "E21-D01"
ISSUE = 417
BQ_COMMENT = "6563728077"
QUOTE_MIN = 12
ALLOWED_PATHS = frozenset({MEMO_REL, TOOL_REL, CAT_REL})

CITE_KEYS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "10": "docs/plan/10-personas.md",
    "11": "docs/plan/11-user-stories.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "30": "docs/plan/30-release-roadmap.md",
    "E21.json": TICKET_JSON,
    "ADR21": "docs/plan/27-adrs/ADR-0021-book-depth-tier-policy.md",
    "E17D03": "docs/design/E17/E17-D03.md",
    "E25D01": "docs/design/E25/E25-D01.md",
    "E15D12": "docs/design/E15/E15-D12.md",
    "E22R": "docs/design/research/e22-tape-reading.md",
    "tiers.py": "services/api/candleviewer/book/tiers.py",
    "FXR": "packages/fixtures/bybit/2026-10-05/README.trades.md",
    "README": "docs/design/README.md",
    "PRT": ".github/PULL_REQUEST_TEMPLATE.md",
}

H2_EXPECTED: tuple[str, ...] = (
    r"Acceptance-criteria trace \(E21-D01, issue #417\)",
    r"Deviations",
    r"BQ list — (?:defaults built; ruling pending|RULED) \(comment \d+\)",
    r"0\. Research boards \(Penpot\)(?: — PENDING)?",
    r"1\. Method note \(agent-delivery adaptation, owner decision 2026-09-25\)",
    r"2\. Research questions and pre-registered hypotheses",
    r"3\. Heuristic evaluation \(every finding `\(heuristic\)`\)",
    r"4\. Persona walkthrough",
    r"5\. Competitive review \(public documentation fetched \d{4}-\d{2}-\d{2}\)",
    r"6\. Recommended defaults, one per research question",
    r"7\. Adopted decisions AD-1\.\.AD-10 \(ranked; heuristic, PROPOSED\)",
    r"8\. Performance kill-list \(budgets #1 and #14; heuristic, PROPOSED\)",
    r"9\. Downstream feeds and flag state",
    r"10\. Owner session protocol \(ready to run; nothing below has been run\)",
    r"11\. Owner walkthrough checklist",
    r"12\. Contradictions, gaps and open questions",
    r"13\. References",
)

SCENARIOS: tuple[str, ...] = (
    "Every open question is answered with evidence",
    "Decisions are testable",
    "Conflicting participant preferences",
)

# The BQ list's ORCH-defaults (comment BQ_COMMENT): row lead -> words its default cell must hold.
DEFAULT_PINS: dict[str, tuple[str, ...]] = {
    "Centring mode": ("auto-follow", "edge-band", "free-scroll", "`Space`"),
    "Heatmap placement": ("beside the ladder",),
    "Price axis": ("locked", "`+`/`-`"),
    "Trail length": ("60 s",),
    "Depth tier": ("200", "cadence → trail → depth"),
    "Pulled liquidity": ("distinct from consumed", "(estimated)", "hue never"),
}

LEXICON_AESTHETIC: tuple[str, ...] = (
    "appealing",
    "attractive",
    "beautiful",
    "clean",
    "cleaner",
    "crisp",
    "delightful",
    "elegant",
    "gorgeous",
    "intuitive",
    "lovely",
    "modern",
    "nice",
    "nicer",
    "pleasing",
    "polished",
    "pretty",
    "sleek",
    "slick",
    "stylish",
)

PARTICIPANT_CLAIMS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:participants?|users?|traders?|P1|P2a?|P2b|the owner|managers?)\s+"
        r"(?:said|says|told|reported|preferred|chose|picked|stated|answered)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d+\s*(?:of|/)\s*\d+\s+(?:participants|sessions|traders|managers)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(?:sessions?|participants?)\s+(?:showed|found|confirmed|revealed)\b", re.IGNORECASE
    ),
    re.compile(r"\btook\s+\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds|min|minutes)\b", re.IGNORECASE),
    re.compile(r"\b(?:P1|P2a|P2b|S1|S2|S3)\s*[:—-]\s*\""),
)

PUBLIC_DENY: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("local path", re.compile(r"(?:/home/|/Users/|/tmp/|[A-Za-z]:\\\\)")),
    ("host", re.compile(r"\blocalhost\b|\b\d{1,3}(?:\.\d{1,3}){3}\b")),
    ("worker name", re.compile(r"\b[a-z]+-worker-\d+\b", re.IGNORECASE)),
    ("secret-shaped", re.compile(r"\b(?:ghp_|github_pat_|AKIA|sk-)[A-Za-z0-9_]{8,}")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
)
# A bare host name is allowed only in the competitive review, next to its quote.
HOST_RE = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|app|local|internal)\b", re.IGNORECASE
)

CITE_RE = re.compile(r"`([^`\s]+)`:(\d+)(?:[–-](\d+))?")
CITE_SPACED_RE = re.compile(r"`([^`\s]+)`\s+:\d+")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
COMMENT_OPEN_RE = re.compile(r"<!--", re.DOTALL)
LINK_COMMENT_RE = re.compile(r"^\[//\]: #", re.MULTILINE)
QUOTE_RE = re.compile(r'"([^"\n]*)"')
URL_RE = re.compile(r"https?://")
ID_RE = re.compile(r"(?<![\w-])(?:(F|AD|OQ|BQ)-(\d+)|(RQ|H|C|G|K|T|W)(\d+))(?![\w])")
PAIR_RE = re.compile(r"\b(E\d{2}-[DKQSTX]\d{2})\s+#(\d+)\b")
ISSUE_RE = re.compile(r"#(\d+)\b")
POINTER_RE = re.compile(
    r"^- \*\*UX research:\*\* \[e21-dom-heatmap\.md\]\(\.\./design/research/e21-dom-heatmap\.md\)"
    r" \(E21-D01; heuristic, owner approval pending; "
)
PRE_POINTER = "- **Design decision (DES-HEATMAP-01):**"


@dataclass(frozen=True)
class Finding:
    gate: str
    msg: str


@dataclass(frozen=True)
class Texts:
    memo: str
    base: dict[str, tuple[str, ...]]
    main: dict[str, str | None]
    ticket: str
    published: dict[str, int]
    changed: tuple[str, ...]
    git_ok: bool
    cat_base: str
    cat_work: str


# ---------------------------------------------------------------------------- git and loading


def git(*args: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return proc.returncode == 0, proc.stdout


def show(rev: str, rel: str) -> str | None:
    ok, out = git("show", f"{rev}:{rel}")
    return out if ok else None


def ticket_body(raw: str) -> str:
    data = json.loads(raw)
    items = data if isinstance(data, list) else data.get("tickets", [])
    for item in items:
        if isinstance(item, dict) and item.get("key") == TICKET_KEY:
            body = item.get("body", "")
            return body if isinstance(body, str) else ""
    return ""


def published_map(raw: str | None) -> dict[str, int]:
    if raw is None:
        return {}
    data = json.loads(raw)
    out: dict[str, int] = {}
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, int):
                out[key] = val
            elif isinstance(val, dict) and isinstance(val.get("number"), int):
                out[key] = int(val["number"])
    return out


def changed_paths() -> tuple[bool, tuple[str, ...], str]:
    ok, mb = git("merge-base", "HEAD", MAIN_REF)
    if not ok or not mb.strip():
        return False, (), ""
    base = mb.strip()
    ok1, diff = git("diff", "--name-only", base)
    ok2, untracked = git("ls-files", "--others", "--exclude-standard")
    if not (ok1 and ok2):
        return False, (), base
    paths = {p for p in (diff.splitlines() + untracked.splitlines()) if p.strip()}
    return True, tuple(sorted(paths)), base


def load() -> Texts:
    memo = (ROOT / MEMO_REL).read_text(encoding="utf-8")
    base: dict[str, tuple[str, ...]] = {}
    main: dict[str, str | None] = {}
    for key, rel in CITE_KEYS.items():
        text = show(BASE, rel)
        base[key] = tuple(text.split("\n")) if text is not None else ()
        main[key] = show(MAIN_REF, rel)
    raw_ticket = show(BASE, TICKET_JSON) or "[]"
    ok, paths, mb = changed_paths()
    cat_base = show(mb, CAT_REL) if mb else None
    return Texts(
        memo=memo,
        base=base,
        main=main,
        ticket=ticket_body(raw_ticket),
        published=published_map(show(BASE, PUBLISHED_JSON)),
        changed=paths,
        git_ok=ok and cat_base is not None,
        cat_base=cat_base or "",
        cat_work=(ROOT / CAT_REL).read_text(encoding="utf-8"),
    )


# ---------------------------------------------------------------------------- parsing helpers


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"')
    t = t.replace("”", '"').replace('\\"', '"').replace("\\n", " ")
    t = t.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", t).strip()


def h2_list(memo: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^## (.+)$", memo, re.MULTILINE)]


def section(memo: str, prefix: str) -> str:
    out: list[str] = []
    inside = False
    for line in memo.split("\n"):
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].startswith(prefix)
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def is_rule(line: str) -> bool:
    return re.fullmatch(r"\|[\s:|-]+\|", line.strip()) is not None


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def data_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("|") or is_rule(line):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_rule(nxt):
            continue  # header row
        rows.append(cells(line))
    return rows


def lead(row: list[str]) -> str:
    return row[0].replace("*", "").strip() if row else ""


def cite_ranges(line: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in CITE_RE.finditer(line):
        a = int(m.group(2))
        b = int(m.group(3)) if m.group(3) else a
        out.append((m.group(1), a, b))
    return out


def id_refs(text: str) -> list[str]:
    out: list[str] = []
    for m in ID_RE.finditer(text):
        if m.group(1):
            out.append(f"{m.group(1)}-{m.group(2)}")
        else:
            out.append(f"{m.group(3)}{m.group(4)}")
    return out


def ascii_clip(text: str, width: int = 60) -> str:
    t = text.encode("ascii", "backslashreplace").decode("ascii")
    return t if len(t) <= width else t[: width - 3] + "..."


# ---------------------------------------------------------------------------- gates


def g_sections(t: Texts) -> list[Finding]:
    got = h2_list(t.memo)
    out: list[Finding] = []
    if len(got) != len(H2_EXPECTED):
        out.append(Finding("G-SECTIONS", f"{len(got)} H2 headings, expected {len(H2_EXPECTED)}"))
    for i, head in enumerate(got):
        if i >= len(H2_EXPECTED) or not re.fullmatch(H2_EXPECTED[i], head):
            out.append(Finding("G-SECTIONS", f"unexpected H2 #{i + 1}: {ascii_clip(head)}"))
    if not t.memo.startswith("# E21-D01 — "):
        out.append(Finding("G-SECTIONS", "the H1 does not name E21-D01"))
    return out


def g_marker(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for m in COMMENT_RE.finditer(t.memo):
        out.append(Finding("G-MARKER", f"HTML comment: {ascii_clip(m.group(0))}"))
    if len(COMMENT_OPEN_RE.findall(t.memo)) != len(COMMENT_RE.findall(t.memo)):
        out.append(Finding("G-MARKER", "an unclosed HTML comment"))
    if LINK_COMMENT_RE.search(t.memo):
        out.append(Finding("G-MARKER", "a [//]: # comment"))
    return out


def g_cite(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for n, line in enumerate(t.memo.split("\n"), 1):
        for m in CITE_SPACED_RE.finditer(line):
            out.append(Finding("G-CITE", f"line {n}: malformed cite {ascii_clip(m.group(0))}"))
        for key, a, b in cite_ranges(line):
            if key not in CITE_KEYS:
                out.append(Finding("G-CITE", f"line {n}: undeclared cite key {ascii_clip(key)}"))
                continue
            size = len(t.base[key])
            if size == 0:
                out.append(Finding("G-CITE", f"line {n}: {key} unreadable at BASE"))
            elif not 1 <= a <= b <= size or b - a > 40:
                out.append(Finding("G-CITE", f"line {n}: {key}:{a}-{b} outside 1..{size}"))
    return out


def g_version(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for key, a, b in cite_ranges(t.memo):
        if key not in CITE_KEYS or (key, a, b) in seen:
            continue
        seen.add((key, a, b))
        lines = t.base[key]
        if not 1 <= a <= b <= len(lines):
            continue
        main = t.main.get(key)
        if main is None:
            out.append(Finding("G-VERSION", f"{key} unreadable at {MAIN_REF}"))
            continue
        if "\n" + "\n".join(lines[a - 1 : b]) + "\n" not in "\n" + main + "\n":
            out.append(Finding("G-VERSION", f"{key}:{a}-{b} changed between BASE and {MAIN_REF}"))
    return out


def line_sources(t: Texts, line: str) -> str:
    parts: list[str] = []
    for key, a, b in cite_ranges(line):
        lines = t.base.get(key, ())
        if 1 <= a <= b <= len(lines):
            parts.append(" ".join(lines[a - 1 : b]))
    return norm(" ".join(parts))


def g_quote(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    comp = section(t.memo, "5. Competitive")
    comp_lines = set(comp.split("\n"))
    ticket = norm(t.ticket)
    for n, line in enumerate(t.memo.split("\n"), 1):
        if line.count('"') % 2:
            out.append(Finding("G-QUOTE", f"line {n}: unpaired double quote"))
            continue
        quotes = [q for q in QUOTE_RE.findall(line) if len(q) >= QUOTE_MIN]
        if not quotes:
            continue
        if line in comp_lines and line.strip():
            if "<https://" not in line:
                out.append(Finding("G-QUOTE", f"line {n}: competitive quote without a URL"))
            for cell in cells(line):
                tail = cell.rsplit("<https://", 1)[-1].split(">", 1)[-1]
                if "<https://" in cell and any(len(q) >= QUOTE_MIN for q in QUOTE_RE.findall(tail)):
                    out.append(Finding("G-QUOTE", f"line {n}: a quote after its cell's last URL"))
            continue
        src = line_sources(t, line)
        for q in quotes:
            pieces = [norm(p) for p in q.split("…") if norm(p)]
            if not all(p in src or p in ticket for p in pieces):
                out.append(Finding("G-QUOTE", f"line {n}: not verbatim: {ascii_clip(q)}"))
    return out


def g_ac(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    ac = section(t.memo, "Acceptance-criteria trace")
    for name in SCENARIOS:
        if f'"{name}"' not in ac:
            out.append(Finding("G-AC", f"scenario name missing from the AC trace: {name}"))
        if f"Scenario: {name}" not in t.ticket:
            out.append(Finding("G-AC", f"scenario name not in the ticket: {name}"))
    statuses = {"done", "done (text)", "heuristic-only", "open", "not applicable"}
    for row in data_rows(ac):
        if len(row) < 3 or row[2].replace("*", "") not in statuses:
            out.append(Finding("G-AC", f"AC row without a known status: {ascii_clip(lead(row))}"))
    return out


def g_bq(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    heads = [h for h in h2_list(t.memo) if h.startswith("BQ list")]
    if len(heads) != 1 or f"(comment {BQ_COMMENT})" not in heads[0]:
        out.append(Finding("G-BQ", "the BQ heading does not name the posted BQ comment"))
    got = [lead(r) for r in data_rows(section(t.memo, "BQ list"))]
    want = [f"BQ-{i}" for i in range(15)]
    if got != want:
        out.append(Finding("G-BQ", f"BQ rows {','.join(got)[:60]} != BQ-0..BQ-14"))
    return out


def g_testable(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    rows = data_rows(section(t.memo, "7. Adopted decisions"))
    got = [lead(r) for r in rows]
    if got != [f"AD-{i}" for i in range(1, 11)]:
        out.append(Finding("G-TESTABLE", "the decisions are not AD-1..AD-10 in order"))
    for row in rows:
        sat = [c for c in row if c.lower().startswith("satisfies if")]
        vio = [c for c in row if c.lower().startswith("violates if")]
        if not sat or not vio or min(len(c.split()) for c in sat + vio) < 6:
            out.append(Finding("G-TESTABLE", f"{lead(row)}: no satisfies/violates clause pair"))
        words = set(re.findall(r"[a-z]+", " ".join(row).lower()))
        for word in LEXICON_AESTHETIC:
            if word in words:
                out.append(Finding("G-TESTABLE", f"{lead(row)}: aesthetic-only word '{word}'"))
        if len(row) < 7 or not re.search(r"\b(?:F-\d+|RQ\d+|W\d+)\b", row[5]):
            out.append(Finding("G-TESTABLE", f"{lead(row)}: no feeding finding"))
    return out


def g_heuristic(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    rows = data_rows(section(t.memo, "3. Heuristic evaluation"))
    if not rows:
        out.append(Finding("G-HEURISTIC", "no findings table"))
    for row in rows:
        if not re.fullmatch(r"F-\d+", lead(row)):
            out.append(Finding("G-HEURISTIC", f"finding row lead {ascii_clip(lead(row))}"))
        if "(heuristic)" not in " ".join(row[1:2]):
            out.append(Finding("G-HEURISTIC", f"{lead(row)} is not labelled (heuristic)"))
    for n, line in enumerate(t.memo.split("\n"), 1):
        for pat in PARTICIPANT_CLAIMS:
            m = pat.search(line)
            if m:
                out.append(Finding("G-HEURISTIC", f"line {n}: claim {ascii_clip(m.group(0))}"))
    return out


def g_defaults(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    rows = {lead(r): r for r in data_rows(section(t.memo, "6. Recommended defaults"))}
    if set(rows) != set(DEFAULT_PINS):
        out.append(Finding("G-DEFAULTS", f"default rows {sorted(rows)} != the six pinned rows"))
    for name, words in DEFAULT_PINS.items():
        row = rows.get(name)
        if row is None or len(row) < 6:
            continue
        for word in words:
            if word not in row[1]:
                out.append(Finding("G-DEFAULTS", f"{name}: default lacks '{ascii_clip(word)}'"))
        if not re.search(r"\bP(?:1|2a|2b)\b", row[2]) or "(heuristic)" not in t.memo:
            out.append(Finding("G-DEFAULTS", f"{name}: no persona rationale"))
        if not row[3].strip():
            out.append(Finding("G-DEFAULTS", f"{name}: the other position is not recorded"))
        if not re.search(r"\bT\d+\b", row[4]):
            out.append(Finding("G-DEFAULTS", f"{name}: no deciding probe"))
    return out


def defined_ids(memo: str) -> tuple[set[str], list[str]]:
    seen: list[str] = []
    if True:
        for row in data_rows(memo):
            cand = lead(row)
            if re.fullmatch(ID_RE.pattern, cand):
                seen.append(cand)
            for cell in row[1:]:
                for m in re.finditer(r"(?<![\w-])(H\d+):", cell):
                    seen.append(m.group(1))
    dups = sorted({i for i in seen if seen.count(i) > 1})
    return set(seen), dups


def g_ids(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    defined, dups = defined_ids(t.memo)
    for d in dups:
        out.append(Finding("G-IDS", f"{d} is defined more than once"))
    for ref in sorted(set(id_refs(t.memo)) - defined):
        out.append(Finding("G-IDS", f"{ref} is referenced but never defined"))
    return out


def g_owner(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    if not t.published:
        return [Finding("G-OWNER", "the published issue map is unreadable at BASE")]
    numbers = set(t.published.values())
    for m in PAIR_RE.finditer(t.memo):
        want = t.published.get(m.group(1))
        if want != int(m.group(2)):
            out.append(Finding("G-OWNER", f"{m.group(1)} #{m.group(2)} != published #{want}"))
    owner_cells: list[str] = [r[-1] for r in data_rows(section(t.memo, "7. Adopted"))]
    owner_cells += [r[-1] for r in data_rows(section(t.memo, "12. Contradictions"))]
    for cell in owner_cells:
        issues = [int(i) for i in ISSUE_RE.findall(cell)]
        if not any(i in numbers for i in issues) and "owner" not in cell.lower():
            out.append(Finding("G-OWNER", f"owner cell names no ticket: {ascii_clip(cell)}"))
        if re.search(r"\b(?:agent|orchestrator|worker)\b", cell, re.IGNORECASE):
            out.append(Finding("G-OWNER", f"an agent as an owner: {ascii_clip(cell)}"))
    return out


def g_kill(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    rows = data_rows(section(t.memo, "8. Performance kill-list"))
    if not rows:
        out.append(Finding("G-KILL", "no kill-list rows"))
    for row in rows:
        if not re.fullmatch(r"K\d+", lead(row)) or len(row) < 4:
            out.append(Finding("G-KILL", f"bad kill row {ascii_clip(lead(row))}"))
            continue
        if not re.search(r"\d", row[2]):
            out.append(Finding("G-KILL", f"{lead(row)}: no killing number"))
        if not re.match(r"(?:killed|not killed)\b", row[3]):
            out.append(Finding("G-KILL", f"{lead(row)}: verdict is not killed / not killed"))
    return out


def g_flag(t: Texts) -> list[Finding]:
    sec = section(t.memo, "9. Downstream")
    out: list[Finding] = []
    for flag in ("`heatmap_depth_500`", "`engine.heatmap_renderer`"):
        if flag not in sec:
            out.append(Finding("G-FLAG", f"flag state omits {flag}"))
    if not re.search(r"`engine\.heatmap_renderer` is named only[^\n]*?\(G\d+\)", sec):
        out.append(Finding("G-FLAG", "the undefined renderer flag is not routed to a G row"))
    return out


def g_boards(t: Texts) -> list[Finding]:
    rows = data_rows(section(t.memo, "0. Research boards"))
    out: list[Finding] = []
    if not 1 <= len(rows) <= 8:
        out.append(Finding("G-BOARDS", f"{len(rows)} boards; the research cap is 8"))
    for i, row in enumerate(rows, 1):
        if not re.fullmatch(rf"`E21-D01 / {i:02d} [a-z0-9-]+`", row[1] if len(row) > 1 else ""):
            out.append(Finding("G-BOARDS", f"board {i:02d} is not named E21-D01 / NN slug"))
        if row[-1] != "PENDING":
            out.append(Finding("G-BOARDS", f"board {i:02d} is not PENDING in the text PR"))
    return out


def g_walk(t: Texts) -> list[Finding]:
    items = re.findall(r"^(\d+)\. (.+)$", section(t.memo, "11. Owner walkthrough"), re.MULTILINE)
    out: list[Finding] = []
    if not 1 <= len(items) <= 10:
        out.append(Finding("G-WALK", f"{len(items)} walkthrough items; the cap is 10"))
    if [int(n) for n, _ in items] != list(range(1, len(items) + 1)):
        out.append(Finding("G-WALK", "walkthrough items are not numbered 1..n"))
    if items and not ("`approved`" in items[-1][1] and f"#{ISSUE}" in items[-1][1]):
        out.append(Finding("G-WALK", "the last item is not the `approved` comment on #417"))
    return out


def g_public(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    added = [ln for ln in t.cat_work.split("\n") if POINTER_RE.match(ln)]
    comp = set(section(t.memo, "5. Competitive").split("\n"))
    for n, line in enumerate(t.memo.split("\n") + added, 1):
        for name, pat in PUBLIC_DENY:
            m = pat.search(line)
            if m:
                out.append(Finding("G-PUBLIC", f"line {n}: {name} {ascii_clip(m.group(0), 30)}"))
        if (URL_RE.search(line) or HOST_RE.search(line)) and line not in comp:
            out.append(
                Finding("G-PUBLIC", f"line {n}: a URL or host outside the competitive review")
            )
        if "![" in line or "<img" in line.lower():
            out.append(Finding("G-PUBLIC", f"line {n}: an image embed (no screenshots here)"))
    return out


def g_untouched(t: Texts) -> list[Finding]:
    if not t.git_ok:
        return [Finding("G-UNTOUCHED", "git merge-base or diff failed; cannot prove the scope")]
    out: list[Finding] = []
    for path in t.changed:
        if path not in ALLOWED_PATHS:
            out.append(Finding("G-UNTOUCHED", f"out-of-scope change: {ascii_clip(path)}"))
    old, new = t.cat_base.split("\n"), t.cat_work.split("\n")
    ops = [op for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()]
    edits = [op for op in ops if op[0] != "equal"]
    if CAT_REL not in t.changed:
        out.append(Finding("G-UNTOUCHED", "the SCR-050 pointer line is missing from 14"))
        return out
    if len(edits) != 1 or edits[0][0] != "insert" or edits[0][4] - edits[0][3] != 1:
        out.append(Finding("G-UNTOUCHED", "14 differs by more than one inserted line"))
        return out
    j = edits[0][3]
    if not POINTER_RE.match(new[j]):
        out.append(Finding("G-UNTOUCHED", "the inserted 14 line is not the E21-D01 pointer"))
    if j == 0 or not new[j - 1].startswith(PRE_POINTER):
        out.append(Finding("G-UNTOUCHED", "the pointer is not after the DES-HEATMAP-01 line"))
    heads = [ln for ln in new[:j] if ln.startswith("### SCR-")]
    if not heads or not heads[-1].startswith("### SCR-050 "):
        out.append(Finding("G-UNTOUCHED", "the pointer is not inside SCR-050"))
    return out


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_sections,
    g_marker,
    g_cite,
    g_version,
    g_quote,
    g_ac,
    g_bq,
    g_testable,
    g_heuristic,
    g_defaults,
    g_ids,
    g_owner,
    g_kill,
    g_flag,
    g_boards,
    g_walk,
    g_public,
    g_untouched,
)
GATE_NAMES: tuple[str, ...] = (
    "G-SECTIONS",
    "G-MARKER",
    "G-CITE",
    "G-VERSION",
    "G-QUOTE",
    "G-AC",
    "G-BQ",
    "G-TESTABLE",
    "G-HEURISTIC",
    "G-DEFAULTS",
    "G-IDS",
    "G-OWNER",
    "G-KILL",
    "G-FLAG",
    "G-BOARDS",
    "G-WALK",
    "G-PUBLIC",
    "G-UNTOUCHED",
)


def run(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for gate in GATES:
        out.extend(gate(t))
    return out


# ---------------------------------------------------------------------------- mutations


def sub1(text: str, old: str, new: str) -> str:
    if old not in text:
        raise KeyError(old)
    return text.replace(old, new, 1)


def resub1(text: str, pat: str, new: str) -> str:
    out, n = re.subn(pat, new, text, count=1, flags=re.MULTILINE)
    if n != 1:
        raise KeyError(pat)
    return out


def memo_mut(fn: Callable[[str], str]) -> Callable[[Texts], Texts]:
    return lambda t: replace(t, memo=fn(t.memo))


def main_14_changed(t: Texts) -> Texts:
    lines = list(t.base["14"])
    lines[1191] = lines[1191] + " (edited on main)"
    main = dict(t.main)
    main["14"] = "\n".join(lines)
    return replace(t, main=main)


def pointer_twice(t: Texts) -> Texts:
    lines = t.cat_work.split("\n")
    idx = next(i for i, ln in enumerate(lines) if POINTER_RE.match(ln))
    lines.insert(idx, lines[idx])
    return replace(t, cat_work="\n".join(lines))


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "M1 drop (heuristic) from F-3",
        "G-HEURISTIC",
        memo_mut(lambda m: sub1(m, "`(heuristic)` When a trader", "When a trader")),
    ),
    (
        "M2 a participant claim",
        "G-HEURISTIC",
        memo_mut(
            lambda m: sub1(m, "## 5. Competitive", "P1 said it was fine.\n\n## 5. Competitive")
        ),
    ),
    (
        "M3 a count of participants",
        "G-HEURISTIC",
        memo_mut(
            lambda m: sub1(m, "## 5. Competitive", "2 of 3 participants.\n\n## 5. Competitive")
        ),
    ),
    (
        "M4 AD-3 loses its violates clause",
        "G-TESTABLE",
        memo_mut(lambda m: sub1(m, "violates if the default pins", "fails if the default pins")),
    ),
    (
        "M5 an aesthetic word in AD-1",
        "G-TESTABLE",
        memo_mut(
            lambda m: sub1(m, "beside the ladder; nothing is drawn", "beside, clean; nothing is")
        ),
    ),
    (
        "M6 a cite past the end of 14",
        "G-CITE",
        memo_mut(lambda m: sub1(m, "(`14`:1192)", "(`14`:99999)")),
    ),
    (
        "M7 an undeclared cite key",
        "G-CITE",
        memo_mut(lambda m: sub1(m, "(`11`:1982)", "(`99`:1982)")),
    ),
    (
        "M8 a malformed cite",
        "G-CITE",
        memo_mut(lambda m: sub1(m, "(`11`:2068)", "(`11` :2068)")),
    ),
    ("M9 a cited line edited on main", "G-VERSION", main_14_changed),
    (
        "M10 a repo quote paraphrased",
        "G-QUOTE",
        memo_mut(lambda m: sub1(m, 'without jitter on every tick" (`11`', 'with no jitter" (`11`')),
    ),
    (
        "M11 a competitive quote loses its URL",
        "G-QUOTE",
        memo_mut(
            lambda m: sub1(
                m, " <https://www.sierrachart.com/index.php?page=doc/ChartTrading.html>", ""
            )
        ),
    ),
    (
        "M11b a competitive quote after its cell's last URL",
        "G-QUOTE",
        memo_mut(
            lambda m: sub1(
                m,
                "ChartTrading.html>",
                'ChartTrading.html> · "an unsourced sentence added after the URL"',
            )
        ),
    ),
    (
        "M12 a scenario name drifts",
        "G-AC",
        memo_mut(lambda m: sub1(m, '"Decisions are testable"', '"Decisions are traceable"')),
    ),
    (
        "M13 the trail default row renamed",
        "G-DEFAULTS",
        memo_mut(lambda m: resub1(m, r"^\| Trail length\s+\|", "| Trail span |")),
    ),
    (
        "M14 the tier default drifts to 500",
        "G-DEFAULTS",
        memo_mut(lambda m: resub1(m, r"^(\| Depth tier\s+\| )200;", r"\g<1>500;")),
    ),
    (
        "M15 BQ-7 dropped",
        "G-BQ",
        memo_mut(lambda m: resub1(m, r"^\| BQ-7 .*\n", "")),
    ),
    (
        "M16 an unexpected section",
        "G-SECTIONS",
        memo_mut(lambda m: sub1(m, "## 13. References", "## 14. Extra\n\nx\n\n## 13. References")),
    ),
    (
        "M17 a multi-line HTML comment",
        "G-MARKER",
        memo_mut(lambda m: m + "\n<!-- a note\nover two lines -->\n"),
    ),
    (
        "M18 an undefined finding id",
        "G-IDS",
        memo_mut(lambda m: sub1(m, "(F-4, W1)", "(F-99, W1)")),
    ),
    (
        "M19 a ticket paired with the wrong issue",
        "G-OWNER",
        memo_mut(lambda m: sub1(m, "E21-D04 #504", "E21-D04 #505")),
    ),
    (
        "M20 an agent as an owner",
        "G-OWNER",
        memo_mut(lambda m: resub1(m, r"\| owner \(a recorder capture\)\s*\|", "| an agent |")),
    ),
    (
        "M21 an eleventh walkthrough item",
        "G-WALK",
        memo_mut(lambda m: resub1(m, r"^(10\. Comment .*)$", r"\g<1>\n11. One more item.")),
    ),
    (
        "M22 a local path",
        "G-PUBLIC",
        memo_mut(lambda m: m + "\nSee /home/someone/notes.\n"),
    ),
    (
        "M23 a URL outside the competitive review",
        "G-PUBLIC",
        memo_mut(
            lambda m: sub1(m, "## 2. Research", "See https://example.org/x.\n\n## 2. Research")
        ),
    ),
    (
        "M24 a screenshot embed",
        "G-PUBLIC",
        memo_mut(lambda m: m + "\n![shot](img/shot.png)\n"),
    ),
    (
        "M25 a kill verdict reworded",
        "G-KILL",
        memo_mut(lambda m: sub1(m, "| killed for SCR-050 (AD-2)", "| dropped for SCR-050 (AD-2)")),
    ),
    (
        "M26 the renderer flag loses its G row",
        "G-FLAG",
        memo_mut(lambda m: sub1(m, "and in no plan doc (G1)", "and in no plan doc")),
    ),
    (
        "M27 a board marked drawn",
        "G-BOARDS",
        memo_mut(lambda m: resub1(m, r"\| PENDING \|$", "| DRAWN |")),
    ),
    (
        "M28 an out-of-scope path",
        "G-UNTOUCHED",
        lambda t: replace(t, changed=tuple(sorted({*t.changed, "apps/web/src/x.ts"}))),
    ),
    ("M29 the 14 pointer twice", "G-UNTOUCHED", pointer_twice),
)


def self_test(t: Texts) -> tuple[bool, list[str]]:
    lines: list[str] = []
    disk = (ROOT / MEMO_REL).read_bytes()
    before = hashlib.sha256(disk).hexdigest()
    baseline = run(t)
    ok = not baseline
    lines.append(f"baseline: FAIL {len(baseline)}")
    for name, gate, mut in MUTATIONS:
        try:
            got = run(mut(t))
        except (KeyError, StopIteration) as exc:
            ok = False
            lines.append(f"FAIL {name}: anchor missing {ascii_clip(str(exc), 40)}")
            continue
        hit = [f for f in got if f.gate == gate]
        if hit:
            lines.append(f"ok   {name} -> {gate} x{len(hit)}")
        else:
            ok = False
            lines.append(f"FAIL {name}: {gate} did not fire")
    after = hashlib.sha256((ROOT / MEMO_REL).read_bytes()).hexdigest()
    if before != after:
        ok = False
        lines.append("FAIL the memo on disk changed during the self-test")
    lines.append(f"self-test {'ok' if ok else 'FAILED'} ({len(MUTATIONS)} mutations)")
    return ok, lines


def report(findings: list[Finding]) -> list[str]:
    lines: list[str] = []
    for name in GATE_NAMES:
        mine = [f for f in findings if f.gate == name]
        if not mine:
            lines.append(f"PASS {name}")
        for f in mine:
            lines.append(f"FAIL {name}: {f.msg}")
    lines.append(f"FAIL {len(findings)}")
    return [ascii_clip(ln, 100) for ln in lines]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    ap.add_argument("--check", action="store_true", help="run every gate (default)")
    ap.add_argument("--self-test", action="store_true", help="baseline FAIL 0, then mutations")
    args = ap.parse_args(argv)
    texts = load()
    if args.self_test:
        ok, lines = self_test(texts)
        print("\n".join(ascii_clip(ln, 100) for ln in lines))
        return 0 if ok else 1
    findings = run(texts)
    print("\n".join(report(findings)))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
