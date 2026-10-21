"""Done-gate: fail when a ticket's DoD evidence artefacts are absent (cluster dod-evidence-gap, #1859).

Usage: python docs/plan/backlog/_tools/done_gate.py <KEY> <issue#> [--json]
Exit 0 = every required evidence kind present (or specifically waived), 1 = gaps (named), 2 = usage/lookup error.

Evidence rules (C-11.2, docs/design/README.md, C-10.4):
  qa        every ticket: a `QA verification ... VERDICT: PASS` comment (latest verdict wins)
  design    label type/design: owner `approved` comment or merged PR, Penpot page reference
            (workspace link, or a labelled page id since 2026-10-21; the name is not
            checked), PNG exports
  perf      label perf / DoD lines naming a measurement: a number+unit near the metric in PR/issue text
  security  security label: `Security review ... VERDICT: APPROVE` on the PR
  a11y      UI tickets: axe report / Storybook link
  dod       an unchecked `- [ ]` DoD line fails only if no evidence maps to it (QA PASS table row, linked
            PR body, issue comment: explicit `DoD#n` or >=2 shared content words) and no waiver names it
`--json` lists each DoD item as ticked / evidenced-by / waived-by / GAP; `AC n` and `DoD n` waivers are
separate namespaces.
Waivers: an OWNER comment matching `exception|waived` + `#1778` waives only the item it names
(`DoD 4`, `AC 2`, `item 3`, `evidence:perf`, or a quoted fragment of the DoD line). Blanket waivers are ignored.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "CandleViewer/CandleViewer"
OWNER = "basiltt"
WAIVER_REF = "#1778"
PR_SEARCH_LIMIT = 100  # PRs read per `gh pr list --search` (one GraphQL page)
GhFn = Callable[[list[str]], Any]

PENPOT_RE = re.compile(
    r"https://design\.penpot\.app/#/workspace\?[^\s)]*file-id=[^\s)]+", re.IGNORECASE
)
# Self-hosted Penpot (2026-10-21): design PRs name their page by name + page id, no
# workspace URL. The label is `page id` / `page_id` / `pageid` / `page-id` / `pageId` /
# `page ids`, or a backticked name then `id` as in "Page `E42-D02` · id" (up to 3
# blanks before the name; up to 6 of space, dot, colon, comma, parenthesis, dash after
# it). A UUID must follow the label directly: at most 12 blanks or punctuation marks,
# never a letter, digit, underscore or line break (CR, VT, FF, NEL, U+2028 included).
# The page name is not checked. So "page id `<uuid>`" and "page-id=<uuid>" count; "page
# id pending (file `<uuid>`)", "homepage id <uuid>", "file id <uuid>", a bare UUID or a
# page name alone do not.
PENPOT_PAGE_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])page"
    r"(?:[ \t_-]?ids?\b"
    r"|:?[ \t]{0,3}[*_]*`[^`\n]{1,60}`[*_]*[ \u00b7:,(\u2014\u2013-]{0,6}\bids?\b)"
    r"(?:[ \t]|[^\w\s]){0,12}"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
PNG_RE = re.compile(r"\.png\b", re.IGNORECASE)
QA_RE = re.compile(
    r"QA (?:re-)?verification[^\n]*VERDICT:\s*(PASS|FAIL)", re.IGNORECASE
)
SEC_RE = re.compile(
    r"Security (?:re-)?review\b.{0,160}?VERDICT:\s*(APPROVE|REQUEST_CHANGES|BLOCK)",
    re.IGNORECASE | re.DOTALL,
)
A11Y_RE = re.compile(r"\baxe\b|storybook|a11y (?:report|evidence)", re.IGNORECASE)
WAIVER_LINE_RE = re.compile(r"exception|waived", re.IGNORECASE)
NOT_APPROVED_RE = re.compile(
    r"\b(?:not|never|un)[\s-]*(?:yet\s+)?approv|n't\s+approv", re.IGNORECASE
)
APPROVED_RE = re.compile(r"\bapproved?\b", re.IGNORECASE)
UNIT = r"(?:ms|µs|us|ns|fps|hz|mb|kb|gb|%|s|/s|msg/s|ops/s|bytes?)"
NUM_RE = re.compile(rf"\d[\d.,]*\s*{UNIT}(?!\w)", re.IGNORECASE)
# Explicit perf keywords (word-boundary matched), used when the ticket has no perf label.
PERF_STRICT = [
    "p50",
    "p95",
    "p99",
    "fps",
    "latency",
    "throughput",
    "benchmark",
    "frame time",
]
# Wider metric words, considered only when the ticket carries a perf label.
PERF_LABELLED = [
    *PERF_STRICT,
    "memory",
    "heap",
    "rss",
    "cpu",
    "jitter",
    "overhead",
    "duration",
]
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "per",
        "that",
        "the",
        "this",
        "to",
        "with",
        "without",
        "all",
        "any",
        "each",
        "every",
        "no",
        "not",
        "only",
        "via",
        "when",
        "where",
        "which",
        "will",
        "must",
        "should",
        "can",
        "into",
        "than",
        "then",
        "there",
        "their",
        "them",
        "they",
        "these",
        "those",
        "was",
        "were",
        "been",
        "being",
        "also",
        "if",
        "else",
        "both",
        "done",
        "ticket",
        "pr",
        "issue",
        "test",
        "tests",
    ]
)
UI_AREAS = ("area/charting-ui", "area/design-system", "area/frontend-platform")


def gh_json(args: list[str]) -> Any:
    r = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout or "null")


def load_ticket(key: str) -> dict[str, Any]:
    path = os.path.join(HERE, "..", "all-tickets.json")
    with open(path, encoding="utf-8") as fh:
        for t in json.load(fh):
            if t["key"] == key:
                return dict(t)
    raise KeyError(key)


def dod_lines(body: str) -> list[tuple[int, bool, str]]:
    """(1-based index, checked, text) for checklist lines of the Definition of Done section."""
    m = re.search(
        r"^##\s+Definition of Done\s*$(.*?)(?=^##\s|\Z)",
        body or "",
        re.MULTILINE | re.DOTALL,
    )
    out: list[tuple[int, bool, str]] = []
    for ln in (m.group(1) if m else "").splitlines():
        c = re.match(r"\s*[-*]\s*\[( |x|X)\]\s*(.+)", ln)
        if c:
            out.append((len(out) + 1, c.group(1) != " ", c.group(2).strip()))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _words(s: str) -> set[str]:
    out: set[str] = set()
    for w in _norm(s).split():
        if len(w) > 4:
            w = re.sub(r"(?:ing|ed|es|s)$", "", w)
        if len(w) >= 2 and w not in STOPWORDS:
            out.add(w)
    return out


def _kw_re(words: list[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(w) for w in words)
    return re.compile(rf"(?<![\w-])(?:{alt})(?![\w-])", re.IGNORECASE)


PERF_STRICT_RE = _kw_re(PERF_STRICT)
PERF_LABELLED_RE = _kw_re(PERF_LABELLED)


def parse_waivers(
    comments: list[dict[str, Any]], dod: list[tuple[int, bool, str]], owner: str = OWNER
) -> tuple[dict[int, str], set[int], set[str], list[str]]:
    """Return (DoD index -> waiving comment excerpt, waived AC numbers, waived kinds, blanket notes).

    `DoD n`/`item n` and `AC n` are separate namespaces. Only OWNER comments citing #1778 count.
    """
    items: dict[int, str] = {}
    acs: set[int] = set()
    kinds: set[str] = set()
    blanket: list[str] = []
    for c in comments:
        body = c.get("body") or ""
        author = (c.get("author") or {}).get("login", "")
        if (
            author != owner
            or WAIVER_REF not in body
            or not re.search(r"exception|waived", body, re.IGNORECASE)
        ):
            continue
        ref = body.strip().splitlines()[0][:60] if body.strip() else ""
        blk = re.search(r"exception:\s*\n?(.*)", body, re.IGNORECASE | re.DOTALL)
        segs = (blk.group(1) if blk else body).splitlines()
        hit = False
        for seg in segs:
            for n in re.findall(r"\b(?:DoD|item)\s*#?(\d+)", seg, re.IGNORECASE):
                items[int(n)] = ref
                hit = True
            for n in re.findall(r"\bAC\s*#?(\d+)", seg, re.IGNORECASE):
                acs.add(int(n))
                hit = True
            for k in re.findall(r"evidence:(\w+)", seg, re.IGNORECASE):
                kinds.add(k.lower())
                hit = True
            for q in re.findall(r"[\"`“]([^\"`”]{8,})[\"`”]", seg):
                for idx, _, text in dod:
                    if _norm(q) in _norm(text):
                        items[idx] = ref
                        hit = True
        if not hit:
            blanket.append(ref)
    return items, acs, kinds, blanket


def _text_of(issue: dict[str, Any], prs: list[dict[str, Any]]) -> str:
    parts = [issue.get("body") or ""]
    parts += [c.get("body") or "" for c in issue.get("comments", [])]
    for p in prs:
        parts.append(p.get("body") or "")
        parts += [c.get("body") or "" for c in p.get("comments", [])]
        parts += [r.get("body") or "" for r in p.get("reviews", [])]
    return "\n".join(parts)


def has_penpot_reference(text: str) -> bool:
    """A Penpot workspace link or a page-id reference: the design evidence.

    Shared by the design check in `evaluate` and by merge_ready.py's `--design` gate.
    """
    return bool(PENPOT_RE.search(text) or PENPOT_PAGE_ID_RE.search(text))


def has_measurement(line: str, text: str, rx: re.Pattern[str]) -> bool:
    if not rx.search(line):
        return bool(NUM_RE.search(text))
    return any(
        NUM_RE.search(text[max(0, m.start() - 80) : m.end() + 80])
        for m in rx.finditer(text)
    )


def evidence_lines(
    comments: list[dict[str, Any]], prs: list[dict[str, Any]], qa_pass_ts: str
) -> list[tuple[str, str]]:
    """(source, line) pairs from the QA PASS comment, issue comments and linked PR bodies.

    The issue body (which holds the DoD list itself) is deliberately excluded.
    """
    out: list[tuple[str, str]] = []
    for c in comments:
        body = c.get("body") or ""
        is_qa = c.get("createdAt", "") == qa_pass_ts and bool(QA_RE.search(body))
        src = "QA PASS comment" if is_qa else "issue comment"
        out += [
            (src, ln)
            for ln in body.splitlines()
            if ln.strip() and not WAIVER_LINE_RE.search(ln)
        ]
    for p in prs:
        src = f"PR #{p.get('number', '?')} body"
        out += [(src, ln) for ln in (p.get("body") or "").splitlines() if ln.strip()]
    return out


MERGE_RE = re.compile(r"\bmerge[ds]?\b|merge queue", re.IGNORECASE)
REVIEW_RE = re.compile(r"^\W*review(?:ed)?\b", re.IGNORECASE)


def structural_evidence(text: str, prs: list[dict[str, Any]]) -> str | None:
    """PR-state evidence for process items: a merged linked PR, or an APPROVE review on one."""
    merged = [p for p in prs if p.get("mergedAt")]
    if merged and MERGE_RE.search(text):
        return f"PR #{merged[0].get('number', '?')} merged"
    if REVIEW_RE.search(text):
        for p in prs:
            if any(
                re.search(r"VERDICT:\s*APPROVE", r.get("body") or "", re.IGNORECASE)
                for r in p.get("reviews", [])
            ):
                return f"PR #{p.get('number', '?')} APPROVE review"
    return None


def map_dod_item(idx: int, text: str, ev: list[tuple[str, str]]) -> str | None:
    """Evidencing source or None: explicit `DoD#n` reference, else >=2 shared content words."""
    ref = re.compile(rf"\bDoD\s*#?\s*{idx}\b", re.IGNORECASE)
    for src, ln in ev:
        if ref.search(ln):
            return src
    want = _words(text)
    need_n = min(2, len(want))
    for src, ln in ev:
        if need_n and len(want & _words(ln)) >= need_n:
            return src
    return None


def _latest_security_verdicts(prs: list[dict[str, Any]]) -> list[str]:
    """Latest security verdict per (PR, reviewer).

    Keyed per PR, not per reviewer alone: agent reviewers share one login, and a
    multi-PR ticket must block if ANY part's latest verdict is REQUEST CHANGES — a later
    APPROVE on another part must never mask it.
    """
    latest: dict[tuple[int, str], tuple[tuple[str, int], str]] = {}
    seq = 0
    for p in prs:
        pr_no = int(p.get("number") or 0)
        for r in [*p.get("reviews", []), *p.get("comments", [])]:
            seq += 1
            m = SEC_RE.search(r.get("body") or "")
            if not m:
                continue
            who = (r.get("author") or {}).get("login", "?")
            key = (r.get("submittedAt") or r.get("createdAt") or "", seq)
            k = (pr_no, who)
            if k not in latest or key >= latest[k][0]:
                latest[k] = (key, m.group(1).upper())
    return [v for _, v in latest.values()]


def evaluate(
    ticket: dict[str, Any],
    issue: dict[str, Any],
    prs: list[dict[str, Any]],
    owner: str = OWNER,
) -> dict[str, Any]:
    labels = set(ticket.get("labels", [])) | {
        x["name"] for x in issue.get("labels", [])
    }
    body = issue.get("body") or ticket.get("body") or ""
    dod = dod_lines(body) or dod_lines(ticket.get("body", ""))
    comments = issue.get("comments", [])
    w_items, w_acs, w_kinds, blanket = parse_waivers(comments, dod, owner)
    text = _text_of(issue, prs)
    fails: list[dict[str, Any]] = []
    waived: list[str] = []

    def need(kind: str, ok: bool, detail: str, item: int | None = None) -> None:
        if ok:
            return
        if kind in w_kinds or (item is not None and item in w_items):
            waived.append(f"{kind}" + (f" DoD#{item}" if item else ""))
            return
        fails.append({"rule": kind, "item": item, "detail": detail})

    verdicts = sorted(
        (c.get("createdAt", ""), m.group(1).upper())
        for c in comments
        for m in [QA_RE.search(c.get("body") or "")]
        if m
    )
    qa_ok = bool(verdicts) and verdicts[-1][1] == "PASS"
    need("qa", qa_ok, "no `QA verification — VERDICT: PASS` comment")

    if "type/design" in labels or ticket.get("kind") == "Design":
        merged = any(p.get("mergedAt") for p in prs)
        appr = any(
            (c.get("author") or {}).get("login") == owner
            and APPROVED_RE.search(c.get("body") or "")
            and not NOT_APPROVED_RE.search(c.get("body") or "")
            for c in comments
        )
        need(
            "design", appr or merged, "no owner `approved` comment or merged design PR"
        )
        need(
            "design",
            has_penpot_reference(text),
            "no Penpot page reference (workspace link, or page name + page id)"
            " — docs/design/README.md",
        )
        pngs = bool(PNG_RE.search(text)) or any(
            PNG_RE.search(f.get("path", "")) for p in prs for f in p.get("files", [])
        )
        need("design", pngs, "no PNG exports committed/embedded")

    has_perf_label = any(x in ("perf", "type/perf") for x in labels)
    prx = PERF_LABELLED_RE if has_perf_label else PERF_STRICT_RE
    for i, _, t in dod:
        if prx.search(t) or (has_perf_label and NUM_RE.search(t)):
            need(
                "perf",
                has_measurement(t, text, prx),
                f"no numeric measurement for: {t[:70]}",
                i,
            )

    if any("security" in x for x in labels):
        verd = _latest_security_verdicts(prs)
        need(
            "security",
            bool(verd) and all(v == "APPROVE" for v in verd),
            "no `Security review … VERDICT: APPROVE` on the PR (latest verdict per reviewer)",
        )

    if "a11y" in labels or any(x in labels for x in UI_AREAS):
        need("a11y", bool(A11Y_RE.search(text)), "no axe report / Storybook link")

    ev = evidence_lines(comments, prs, verdicts[-1][0] if qa_ok else "")
    items: list[dict[str, Any]] = []
    for i, checked, t in dod:
        src = (
            None if checked else (map_dod_item(i, t, ev) or structural_evidence(t, prs))
        )
        if checked:
            items.append({"item": i, "status": "ticked"})
        elif src is not None:
            items.append({"item": i, "status": f"evidenced-by: {src}"})
        elif i in w_items:
            items.append({"item": i, "status": f"waived-by: {w_items[i]}"})
            waived.append(f"dod DoD#{i}")
        else:
            items.append({"item": i, "status": "GAP"})
            fails.append(
                {
                    "rule": "dod",
                    "item": i,
                    "detail": f"no evidence maps to DoD item: {t[:80]}",
                }
            )

    return {
        "ok": not fails,
        "failures": fails,
        "waived": waived,
        "waived_acs": sorted(w_acs),
        "dod_items": items,
        "blanket_waivers_ignored": blanket,
    }


def search_prs(gh: GhFn, query: str) -> list[dict[str, Any]]:
    """Up to PR_SEARCH_LIMIT PRs (any state) for `query`, in gh's best-match order."""
    found = gh(
        [
            "pr",
            "list",
            "-R",
            REPO,
            "--state",
            "all",
            "--search",
            query,
            "--limit",
            str(PR_SEARCH_LIMIT),
            "--json",
            "number,body,files,reviews,comments,mergedAt",
        ]
    )
    return found or []


def fetch(issue_no: str, gh: GhFn) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issue = gh(
        ["issue", "view", issue_no, "-R", REPO, "--json", "body,comments,labels,state"]
    )
    prs = search_prs(gh, f"#{issue_no} in:body")
    if len(prs) >= PR_SEARCH_LIMIT:
        # Saturated: other PRs' review records cite the issue too, and best-match
        # order can push the linked PR past the limit. Also search for the closing
        # phrase and merge by number, keeping the first query's results first.
        seen = {p.get("number") for p in prs}
        closers = search_prs(gh, f'"closes #{issue_no}" in:body')
        prs = prs + [p for p in closers if p.get("number") not in seen]
    # The linked PR carries `Closes|Fixes|Resolves #N` in its body (C-4.7). Multi-PR tickets
    # (parts land with `Refs #N` and QA closes the ticket, e.g. E17-T02) also count — but only
    # PRs that are already MERGED, so an open `Refs` PR can never satisfy the security gate.
    closing = re.compile(rf"(?:closes|fixes|resolves)\s+#{issue_no}\b", re.IGNORECASE)
    # `Refs #N` must start a line (footer style); an in-prose mention never links.
    refs = re.compile(rf"^\s*refs?\s+#{issue_no}\b", re.IGNORECASE | re.MULTILINE)
    linked = [
        p
        for p in prs
        if closing.search(p.get("body") or "")
        or (refs.search(p.get("body") or "") and p.get("mergedAt"))
    ]
    return issue, linked


def run_gate(
    key: str, issue_no: str, gh: GhFn = gh_json, owner: str = OWNER
) -> dict[str, Any]:
    issue, prs = fetch(issue_no, gh)
    res = evaluate(load_ticket(key), issue, prs, owner)
    res.update(key=key, issue=int(issue_no))
    return res


def render(res: dict[str, Any]) -> str:
    head = f"{res['key']} #{res['issue']}: {'PASS' if res['ok'] else 'FAIL'}"
    lines = [head]
    lines += [
        f"  - [{f['rule']}]{' DoD#' + str(f['item']) if f['item'] else ''} {f['detail']}"
        for f in res["failures"]
    ]
    lines += [f"  ~ waived (#1778): {w}" for w in res["waived"]]
    lines += [
        f"  ! blanket waiver ignored: {b}" for b in res["blanket_waivers_ignored"]
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 2
    try:
        res = run_gate(args[0], args[1])
    except (KeyError, RuntimeError, ValueError) as e:
        print(f"done_gate error: {e}", file=sys.stderr)
        return 2
    print(
        json.dumps(res, indent=2, ensure_ascii=False)
        if "--json" in argv
        else render(res)
    )
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
