#!/usr/bin/env python3
"""Shared gates for the per-spec design audit tools in `docs/design/_tools/`.

A per-spec tool keeps only its own rows (its pins, its section names, its gates over its own
tables) and imports the shared machinery from here:

* git: `Repo` (show a path at a rev, merge-base with origin/main that survives a simulated merge,
  changed paths and numstat against it); every subprocess runs with encoding="utf-8".
* markdown: `section`, `table_rows`, `all_tables`, `cells`, `unquote`, `strip_fences`.
* cites and pins: `Docs` (documents by key at their pinned rev), `cite_regex`, `extract_cites`,
  `check_cites`, `KeyCite` + `check_key_cites` + `repin_key_cites` (file:line:text pins),
  `bq_bullets`, `bq_hash_pins` / `check_hash_pins`, `verbatim_pins` / `check_verbatim_pins`,
  `write_pins`, `check_ruling`.
* G-T2 (`.claude/rules/32-design-specs.md`, E09-D09 sections 2.1, 3.1, 3.2): `t2_markers`,
  `d09_keys`, `d09_verbs`, `t2_reason_keys`, `t2_verbs`, `t2_reason_string`, `one_notice`,
  `no_disabled_tokens`.
* hygiene: `closing_keywords` (no closing keyword followed by #N; no "What this ... fixes"
  heading), `whitespace_hygiene` (CR, trailing blanks, final newline, invisible characters).
* public text: `scan_public` (URLs, local paths, user, hosts, lane and persona names; the deny
  list is assembled from fragments), `comment_findings` (HTML comments; DOTALL everywhere).
* R7 (Penpot references: page name and page id only, never a host, team or file reference):
  `r7_findings`.
* tokens and boards: `token_file`, `resolve_theme`, `token_names`, `check_token_refs`,
  `load_module` (the repo's measuring modules, by path), `board_cap` (<= 10 boards, light twins
  <= a third, PENDING titles, the "not drawn" paragraph).
* G-UNTOUCHED: `untouched` (only allowed paths changed vs the merge-base; exact line budgets).
* runner: `Gate`, `Result`, `run_gates`, `report`; mutations: `Tree`, `Mutation`,
  `apply_mutation`, `self_test`, `mutation_table`, `check_mutlist`, `lint_comment_regexes`;
  `cli` (the --check / --self-test / --repin-ruled / --fill switch).

Stdlib only; Python 3.12. `python3 -I -B spec_audit_lib.py --self-test` runs the module's own
self-test on in-memory fixtures (add `--git-scratch DIR` to also exercise the git helpers in a
throw-away repository created under DIR).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType

Named = Iterable[tuple[str, str]]  # (label, text) pairs a gate scans


class AuditError(Exception):
    """A setup failure (a missing commit, an anchor a mutation needs): never a silent PASS."""


# ---------- git -----------------------------------------------------------------------------------
class Repo:
    """Read-only git access at `root`; `show` is cached per (rev, path)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._shown: dict[tuple[str, str], str | None] = {}

    def run(self, *args: str) -> tuple[int, str, str]:
        res = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return res.returncode, res.stdout, res.stderr

    def git(self, *args: str) -> str:
        code, out, err = self.run(*args)
        if code != 0:
            raise AuditError(f"git {' '.join(args)} failed: {err.strip()}")
        return out

    def git_ok(self, *args: str) -> str | None:
        code, out, _ = self.run(*args)
        return out if code == 0 else None

    def show(self, rev: str, rel: str) -> str | None:
        key = (rev, rel)
        if key not in self._shown:
            self._shown[key] = self.git_ok("show", f"{rev}:{rel}")
        return self._shown[key]

    def lines_at(self, rev: str, rel: str) -> tuple[str, ...] | None:
        text = self.show(rev, rel)
        return None if text is None else tuple(text.split("\n"))

    def plan_doc(self, rev: str, nn: str, folder: str = "docs/plan/") -> str | None:
        """The `docs/plan/NN-*.md|.yaml` path at `rev` (the `NN` of a backtick cite)."""
        out = self.git_ok("ls-tree", "--name-only", rev, folder) or ""
        for line in out.splitlines():
            name = line.rsplit("/", 1)[-1]
            if name.startswith(nn + "-") and name.endswith((".md", ".yaml")):
                return line
        return None

    def _rev(self, ref: str) -> str | None:
        out = self.git_ok("rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
        return out.strip() if out and out.strip() else None

    def _is_ancestor(self, a: str, b: str) -> bool:
        return self.run("merge-base", "--is-ancestor", a, b)[0] == 0

    def diff_base(self, fallback: str, upstream: str = "origin/main") -> str:
        """What this branch diffs against: the merge-base with `upstream`, `fallback` without one.

        Simulated-merge friendly: during an uncommitted merge (MERGE_HEAD present) both sides'
        merge-bases with `upstream` are candidates and the newest wins, so the main side of the
        merge is the base whichever side HEAD is on and main's own changes are not reported.
        """
        cands: list[str] = []
        for ref in ("HEAD", "MERGE_HEAD"):
            if self._rev(ref) is None:
                continue
            mb = self.git_ok("merge-base", ref, upstream)
            if mb and mb.strip():
                cands.append(mb.strip())
        if not cands:
            return fallback
        best = cands[0]
        for c in cands[1:]:
            if c != best and self._is_ancestor(best, c):
                best = c
        return best

    def changed_paths(self, base: str) -> tuple[str, ...]:
        """Paths that differ from `base` in the working tree, plus untracked, unignored files."""
        tracked = self.git("diff", "--name-only", base, "--")
        untracked = self.git("ls-files", "--others", "--exclude-standard")
        return tuple(sorted({p for p in (tracked + untracked).splitlines() if p}))

    def numstat(self, base: str, rel: str) -> tuple[int, int] | None:
        """(added, deleted) lines of `rel` vs `base`; None when unchanged or binary."""
        out = self.git("diff", "--numstat", base, "--", rel).split()
        if len(out) < 2 or not (out[0].isdigit() and out[1].isdigit()):
            return None
        return int(out[0]), int(out[1])


# ---------- markdown ------------------------------------------------------------------------------
_RULE_ROW = re.compile(r"^\|[\s:|-]+\|$")


def section(text: str, prefix: str) -> str:
    """The body under the first heading line starting with `prefix`, up to the next heading of
    the same or a higher level (the heading line itself excluded)."""
    level = len(prefix) - len(prefix.lstrip("#"))
    out: list[str] = []
    inside = False
    for line in text.split("\n"):
        if not inside:
            inside = line.startswith(prefix)
            continue
        if re.match(rf"^#{{1,{level}}} ", line):
            break
        out.append(line)
    return "\n".join(out)


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table_rows(block: str) -> list[list[str]]:
    """The body rows of the first table in `block` (after its |---| rule)."""
    out: list[list[str]] = []
    seen_rule = False
    for line in block.split("\n"):
        if not line.startswith("|"):
            if seen_rule and out:
                break
            continue
        if _RULE_ROW.match(line.strip()):
            seen_rule = True
            continue
        if seen_rule:
            out.append(cells(line))
    return out


def all_tables(block: str) -> list[list[list[str]]]:
    """Every table in `block`, header row dropped."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in block.split("\n") + [""]:
        if line.startswith("|"):
            if not _RULE_ROW.match(line.strip()):
                current.append(cells(line))
        elif current:
            tables.append(current[1:])
            current = []
    return tables


def unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == '"' and s[-1] == '"' else s


_FENCE = re.compile(r"^```.*?^```[ \t]*$", re.DOTALL | re.MULTILINE)


def strip_fences(text: str) -> str:
    return _FENCE.sub("", text)


# ---------- documents and cites -------------------------------------------------------------------
@dataclass(frozen=True)
class DocRef:
    rel: str
    rev: str


class Docs:
    """Cited documents by key: a two-digit `NN` is a plan document at `base` (from `plan` when
    given, else found with ls-tree); any other key comes from `keyed` at its own pinned rev.
    `overrides` (key -> lines) lets a mutation drift a source in memory."""

    def __init__(
        self,
        repo: Repo,
        base: str,
        keyed: Mapping[str, DocRef],
        plan: Mapping[str, str] | None = None,
        overrides: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.repo, self.base, self.keyed, self.plan = repo, base, keyed, plan
        self.overrides = dict(overrides or {})

    def ref(self, key: str) -> DocRef | None:
        if key in self.keyed:
            return self.keyed[key]
        if re.fullmatch(r"\d\d", key):
            rel = (
                self.plan.get(key) if self.plan is not None else self.repo.plan_doc(self.base, key)
            )
            return DocRef(rel, self.base) if rel else None
        return None

    def lines(self, key: str) -> tuple[str, ...] | None:
        if key in self.overrides:
            return self.overrides[key]
        ref = self.ref(key)
        return None if ref is None else self.repo.lines_at(ref.rev, ref.rel)

    def line(self, key: str, n: int) -> str | None:
        text = self.lines(key)
        return text[n - 1] if text is not None and 1 <= n <= len(text) else None

    def drifted(self, key: str, lines: tuple[str, ...]) -> Docs:
        return Docs(self.repo, self.base, self.keyed, self.plan, {**self.overrides, key: lines})


@dataclass(frozen=True)
class Cite:
    doc: str
    lo: int
    hi: int
    raw: str


def cite_regex(keys: Iterable[str], ranges: bool = False, spaced: bool = False) -> re.Pattern[str]:
    """`NN`:line (backticked plan doc) or KEY:line. `ranges` adds `:a–b` and the `, :n` tail;
    `spaced` allows one space before the colon."""
    alts = "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True)) or r"(?!)"
    doc = rf"(?:`(?P<nn>\d\d)`|(?<![A-Za-z0-9-])(?P<named>{alts}))"
    colon = " ?:" if spaced else ":"
    if not ranges:
        return re.compile(rf"{doc}{colon}(?P<first>\d+)")
    return re.compile(
        rf"{doc}{colon}(?P<first>\d+)(?:–(?P<firstend>\d+))?(?P<more>(?:, :\d+(?:–\d+)?)*)"
    )


_MORE = re.compile(r":(\d+)(?:–(\d+))?")


def extract_cites(text: str, regex: re.Pattern[str]) -> list[Cite]:
    out: list[Cite] = []
    for m in regex.finditer(text):
        gd = m.groupdict()
        doc = gd.get("nn") or gd.get("named") or ""
        lo = int(m.group("first"))
        out.append(Cite(doc, lo, int(gd.get("firstend") or lo), m.group(0)))
        for a, b in _MORE.findall(gd.get("more") or ""):
            out.append(Cite(doc, int(a), int(b or a), m.group(0)))
    return out


def check_cites(
    cites: Sequence[Cite], docs: Docs, nonblank: bool = True, min_count: int = 0
) -> list[str]:
    """Every cite resolves inside its document at its pin (and, with `nonblank`, every cited line
    has text). `min_count` guards against a broken grammar that parses nothing."""
    bad: list[str] = []
    for c in cites:
        lines = docs.lines(c.doc)
        if lines is None:
            bad.append(f"{c.raw} (document not readable at its pin)")
        elif not 1 <= c.lo <= c.hi <= len(lines):
            bad.append(f"{c.raw} (outside {c.doc}'s {len(lines)} lines)")
        elif nonblank and not all(lines[i - 1].strip() for i in range(c.lo, c.hi + 1)):
            bad.append(f"{c.raw} (a blank line)")
    if len(cites) < min_count:
        bad.append(f"only {len(cites)} cites parsed; the cite grammar is broken")
    return sorted(set(bad))


@dataclass(frozen=True)
class KeyCite:
    """A ruled pin: `needle` must stand on line `line` of document `doc` at its pinned rev."""

    doc: str
    line: int
    needle: str


def check_key_cites(pins: Iterable[KeyCite], docs: Docs) -> list[str]:
    bad: list[str] = []
    for p in pins:
        text = docs.line(p.doc, p.line)
        if text is None or p.needle not in text:
            bad.append(f"{p.doc}:{p.line} no longer carries {p.needle!r} (re-pin the cite)")
    return bad


def repin_key_cites(pins: Iterable[KeyCite], docs: Docs) -> list[tuple[KeyCite, int | None]]:
    """For each pin, the nearest line now carrying its needle (None: gone from the document)."""
    out: list[tuple[KeyCite, int | None]] = []
    for p in pins:
        lines = docs.lines(p.doc) or ()
        hits = [i + 1 for i, ln in enumerate(lines) if p.needle in ln]
        out.append((p, min(hits, key=lambda n: (abs(n - p.line), n)) if hits else None))
    return out


# ---------- the ruled BQ section ------------------------------------------------------------------
BQ_HEADING = "## The questions BQ-0"
_BQ_ID = re.compile(r"- \*\*(BQ-\d+)")


def bq_bullets(spec: str, heading: str = BQ_HEADING) -> list[str]:
    return [ln for ln in section(spec, heading).split("\n") if ln.startswith("- **BQ-")]


def bq_hash_pins(spec: str, heading: str = BQ_HEADING, width: int = 16) -> list[str]:
    """`BQ-n <sha256[:width]>` per bullet: the hashed pin style."""
    out: list[str] = []
    for ln in bq_bullets(spec, heading):
        m = _BQ_ID.match(ln)
        if m:
            out.append(f"{m.group(1)} {hashlib.sha256(ln.encode('utf-8')).hexdigest()[:width]}")
    return out


def pin_rows(pins_text: str) -> list[str]:
    """The non-comment, non-blank rows of a pins file."""
    return [ln for ln in pins_text.split("\n") if ln and not ln.startswith("#")]


def check_hash_pins(spec: str, pins_text: str, heading: str = BQ_HEADING) -> list[str]:
    want, got = pin_rows(pins_text), bq_hash_pins(spec, heading)
    if want == got:
        return []
    return [
        f"BQ lines differ from the pins: {sorted({d.split()[0] for d in set(want) ^ set(got)})}"
    ]


def verbatim_pins(spec: str, header: Sequence[str], heading: str = BQ_HEADING) -> str:
    """The verbatim pin style: comment header, the BQ heading line, the section body."""
    head = next((ln for ln in spec.split("\n") if ln.startswith(heading)), "")
    body = section(spec, heading).strip("\n")
    return "\n".join([*header, head, body]) + "\n"


def check_verbatim_pins(
    spec: str, pins_text: str, header: Sequence[str], heading: str = BQ_HEADING
) -> list[str]:
    if not any(ln.startswith(heading) for ln in spec.split("\n")):
        return ["no BQ section to pin"]
    if pins_text != verbatim_pins(spec, header, heading):
        return ["the pins differ from the spec's BQ section (run --repin-ruled after a ruling)"]
    return []


def write_pins(path: Path, text: str) -> None:
    """The only pin writer (`--repin-ruled`): LF endings, UTF-8, a final newline."""
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")


def check_ruling(
    spec: str,
    *,
    heading_line: str,
    list_ref: str,
    count: int,
    verdict: Callable[[int], str],
    need: Sequence[str] = (),
    forbid: Sequence[str] = (),
    heading: str = BQ_HEADING,
) -> list[str]:
    """The RULED BQ section: the exact heading line, the BQ list cited, BQ-0 ... BQ-(count-1) in
    order, each bullet carrying `verdict(n)` and every `need`, and none of `forbid`."""
    bad = [] if heading_line in spec.split("\n") else ["heading"]
    if list_ref not in section(spec, heading):
        bad.append("the BQ list id")
    bullets = bq_bullets(spec, heading)
    ids = [m.group(1) for b in bullets if (m := _BQ_ID.match(b))]
    if ids != [f"BQ-{n}" for n in range(count)]:
        bad.append(f"ids {ids}")
    for n, (b, bid) in enumerate(zip(bullets, ids)):
        if verdict(n) not in b or any(x not in b for x in need) or any(x in b for x in forbid):
            bad.append(bid)
    return bad


# ---------- G-T2 ----------------------------------------------------------------------------------
T2_STANDARD: tuple[str, ...] = (
    "G-T2.1a",
    "G-T2.1b",
    "G-T2.1c",
    "G-T2.1d",
    "G-T2.2",
    "G-T2.3",
    "G-T2.4",
    "G-T2.5",
    'aria-disabled="true"',
    "never `disabled`",
    "aria-describedby",
    "CMP-079",
    "CMP-019",
    "never `opacity.disabled`",
)


def t2_markers(block: str, required: Sequence[str] = T2_STANDARD) -> list[str]:
    """The T2 statement (the spec's R-n bullet or section) names every required marker."""
    return [m for m in required if m not in block]


def d09_keys(d09: str) -> dict[str, str]:
    """E09-D09 section 3.1: reason key -> string."""
    out: dict[str, str] = {}
    for r in table_rows(section(d09, "### 3.1")):
        m = re.fullmatch(r"`([a-z_]+\.[a-z_.]+)`", r[0])
        if m and len(r) > 1:
            out[m.group(1)] = unquote(r[1])
    return out


def d09_verbs(d09: str) -> dict[str, str]:
    """E09-D09 section 3.2: permission code -> {verb}."""
    body = section(d09, "### 3.2")
    return {c: v for c, v in re.findall(r'`([a-z_]+:[a-z_]+)` → "([^"]+)"', body)}


def t2_reason_keys(
    text: str,
    keys: Iterable[str],
    registered: Mapping[str, str] | None = None,
    key_re: str = r"`(rbac\.[a-z_]+)`",
) -> list[str]:
    """Every reason key named is a section 3.1 key, or a registered state key whose owner is
    named on the same line (`registered`: key -> owner)."""
    known, reg = set(keys), dict(registered or {})
    bad: list[str] = []
    for line in text.split("\n"):
        for k in re.findall(key_re, line):
            if k in known:
                continue
            owner = reg.get(k)
            if owner is None:
                bad.append(f"{k} is not an E09-D09 section 3.1 key")
            elif owner not in line:
                bad.append(f"{k} does not name its vocabulary owner {owner}")
    return bad


def t2_verbs(text: str, verbs: Mapping[str, str], code: str | None = None) -> list[str]:
    """Every `verb "x"` is section 3.2's verb (for `code` when given)."""
    allowed = {verbs[code]} if code is not None and code in verbs else set(verbs.values())
    if code is not None and code not in verbs:
        return [f"{code} is not in E09-D09 section 3.2"]
    return [
        f"verb {v!r} is not section 3.2's"
        for v in re.findall(r'verb "([^"]+)"', text)
        if v not in allowed
    ]


def t2_reason_string(s: str, name_re: re.Pattern[str] | None = None) -> str | None:
    """G-T2.4: one sentence, at most 60 characters, a full stop, no figure, no name."""
    if len(s) > 60 or not s.endswith(".") or ". " in s or re.search(r"\d", s):
        return f"{len(s)} chars, or not one sentence, or a figure"
    if name_re is not None and name_re.search(s):
        return "names a screen, ticket or data"
    return None


def one_notice(text: str, notice: str) -> list[str]:
    """G-T2.5: a read-only surface carries exactly one notice."""
    n = text.count(notice)
    return [] if n == 1 else [f"{n} notices {notice!r}; want exactly one"]


_DISABLED_TOKEN = re.compile(r"`(?:opacity\.disabled|color\.text\.disabled)`")


def no_disabled_tokens(text: str, window: int = 12) -> list[str]:
    """G-T2.2: `opacity.disabled` / `color.text.disabled` appear only as a ban ("never", "not",
    "no" within `window` characters before) or a measured rejection ("REJECTED")."""
    bad: list[str] = []
    for m in _DISABLED_TOKEN.finditer(text):
        before = text[max(0, m.start() - window) : m.start()].lower()
        end = text.find("\n", m.end())
        line = text[text.rfind("\n", 0, m.start()) + 1 : end if end >= 0 else len(text)]
        if not re.search(r"\b(never|not|no)\b", before) and "REJECTED" not in line:
            bad.append(f"{m.group(0)} used as a treatment")
    return bad


# ---------- closing keywords, hygiene -------------------------------------------------------------
# Assembled from fragments so this module never matches its own scan.
_KW = "|".join(("clo" + "se[sd]?", "fi" + "x(?:e[sd])?", "reso" + "lve[sd]?"))
CLOSING_RE = re.compile(rf"\b(?:{_KW}):?\s*#\d+", re.IGNORECASE)
WHAT_FIXES_RE = re.compile(
    r"^#+\s*" + "Wh" + r"at this\b[^\n]*\b" + "fi" + "xes", re.IGNORECASE | re.MULTILINE
)


def closing_keywords(texts: Named) -> list[str]:
    bad: list[str] = []
    for label, text in texts:
        bad += [f"{label}: {m.group(0)}" for m in CLOSING_RE.finditer(text)]
        bad += [f"{label}: heading" for _ in WHAT_FIXES_RE.finditer(text)]
    return bad


_INVISIBLE = re.compile("[\\u00ad\\u200b-\\u200d\\u2060\\ufeff]")


def whitespace_hygiene(texts: Named) -> list[str]:
    """No CR, no trailing blanks, a final newline, no invisible characters."""
    bad: list[str] = []
    for label, text in texts:
        if "\r" in text:
            bad.append(f"{label}: a CR (CRLF or bare CR)")
        trailing = [i + 1 for i, ln in enumerate(text.split("\n")) if ln != ln.rstrip(" \t")]
        if trailing:
            bad.append(f"{label}: trailing whitespace on lines {trailing[:5]}")
        if text and not text.endswith("\n"):
            bad.append(f"{label}: no final newline")
        if _INVISIBLE.search(text):
            bad.append(f"{label}: an invisible character")
    return bad


# ---------- public text, comments, R7 -------------------------------------------------------------
# Every fragment is split so no lane, persona, user, host or path is spelled in this file.
DENY_FRAGMENTS: dict[str, str] = {
    "url": "http" + r"s?://",
    "www": r"\bwww" + r"\.",
    "home": "/" + "home/",
    "tmp": "/" + "tmp/",
    "local": r"\.lo" + r"cal\b",
    "scratch": "scr" + "atch-",
    "user": "bas" + "iltt",
    "lane-a": r"\bhc" + "l-",
    "lane-b": r"\bhp" + "e-",
    "lane-role": r"\bwor" + r"ker\b",
    "persona": r"\bAn" + r"vil\b",
    "design-host": "pen" + r"pot\.can" + "dle",
    "relay-host": "rel" + r"ay\.can" + "dle",
}


def public_re(omit: Iterable[str] = (), extra: Iterable[str] = ()) -> re.Pattern[str]:
    parts = [v for k, v in DENY_FRAGMENTS.items() if k not in set(omit)] + list(extra)
    return re.compile("|".join(parts), re.IGNORECASE)


_PUBLIC = public_re()


def scan_public(texts: Named, regex: re.Pattern[str] = _PUBLIC) -> list[str]:
    return [f"{label}: {m.group(0)}" for label, text in texts for m in regex.finditer(text)]


COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
COMMENT_OPEN_RE = re.compile(r"<!--(?!.*?-->)", re.DOTALL)
ANCHOR_RE = re.compile(r"^ audit:([a-z_0-9]+)=([0-9a-f]+) $", re.DOTALL)


def comment_findings(texts: Named, allow: re.Pattern[str] | None = None) -> list[str]:
    """HTML comments hide text from a reviewer: none, or only bodies `allow` fully matches."""
    bad: list[str] = []
    for label, text in texts:
        for m in COMMENT_RE.finditer(text):
            if allow is None or not allow.fullmatch(m.group(1)):
                bad.append(f"{label}: stray comment {m.group(0)[:20]}")
        if COMMENT_OPEN_RE.search(COMMENT_RE.sub("", text)):
            bad.append(f"{label}: an unterminated comment")
    return bad


PENPOT_RE = re.compile(
    "|".join(
        (
            "pen" + r"pot\.[a-z]",
            "file" + r"[-_]id\s*=?",
            "team" + r"[-_]id\s*=?",
            "page" + r"-id=",
            r"#/" + "work" + "space",
            "work" + r"space\?",
            r"#/" + "view",
            "/" + "view/",
        )
    ),
    re.IGNORECASE,
)


def r7_findings(
    texts: Named, required: Sequence[str] = (), spec: str = "", regex: re.Pattern[str] = PENPOT_RE
) -> list[str]:
    """R7: Penpot is referenced by page name and page id only; never a host, team, file or
    workspace reference (split literals included). `required` phrases must stand in `spec`."""
    bad = [f"lacks {r!r} (R7)" for r in required if r not in spec]
    bad += [f"{label}: {m.group(0)}" for label, text in texts for m in regex.finditer(text)]
    return bad


# ---------- tokens and boards ---------------------------------------------------------------------
TOKENS_DIR = "packages/ui/tokens/"
THEME_PARTS: dict[str, tuple[str, ...]] = {
    "dark": ("semantic-dark",),
    "light": ("semantic-dark", "semantic-light"),
    "high-contrast": ("semantic-dark", "semantic-hc"),
}
TOKEN_REF_RE = re.compile(
    r"`((?:color|space|size|type|font|opacity|border)\.[A-Za-z0-9.*\-]+?)(\.\.\d+)?(\[\])?`"
)


def token_file(repo: Repo, rev: str, name: str) -> dict[str, dict[str, object]]:
    """One `<name>.tokens.json` at `rev`, `$`-keys dropped."""
    text = repo.show(rev, f"{TOKENS_DIR}{name}.tokens.json")
    if text is None:
        raise AuditError(f"{TOKENS_DIR}{name}.tokens.json not readable at {rev}")
    raw = json.loads(text)
    return {k: v for k, v in raw.items() if not k.startswith("$") and isinstance(v, dict)}


def resolve_theme(repo: Repo, rev: str, theme: str) -> dict[str, str]:
    """Token -> resolved `$value` for a theme (primitives, then its parts; `{ref}` followed)."""
    allt = dict(token_file(repo, rev, "primitives"))
    for part in THEME_PARTS[theme]:
        allt.update(token_file(repo, rev, part))

    def res(value: object, seen: frozenset[str]) -> object:
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            ref = value[1:-1]
            if ref in seen or ref not in allt:
                return None
            return res(allt[ref].get("$value"), seen | {ref})
        return value

    out: dict[str, str] = {}
    for key, tok in allt.items():
        val = res(tok.get("$value"), frozenset({key}))
        out[key] = val if isinstance(val, str) else ""
    return out


def token_names(repo: Repo, rev: str) -> frozenset[str]:
    names: set[str] = set()
    for part in ("primitives", "semantic-dark", "semantic-light", "semantic-hc"):
        names |= set(token_file(repo, rev, part))
    return frozenset(names)


def check_token_refs(
    text: str, names: frozenset[str], regex: re.Pattern[str] = TOKEN_REF_RE
) -> list[str]:
    """Every backticked token is shipped: exact, `a.b.*` (some child), `a.1..5` (each step);
    a `name[]` ramp is skipped (an unshipped name quoted for an A-row)."""
    bad: list[str] = []
    for m in regex.finditer(text):
        name, rng, ramp = m.group(1), m.group(2), m.group(3)
        if ramp:
            continue
        if name.endswith(".*"):
            ok = any(n.startswith(name[:-1]) for n in names)
        elif rng:
            stem, first = name.rsplit(".", 1)
            span = range(int(first), int(rng[2:]) + 1) if first.isdigit() else range(0)
            ok = bool(span) and all(f"{stem}.{i}" in names for i in span)
        else:
            ok = name in names
        if not ok:
            bad.append(name + (rng or ""))
    return sorted(set(bad))


def load_module(root: Path, rel: str, name: str) -> ModuleType:
    """Run a repo measuring module (contrast_check, cvd_simulate) loaded by path."""
    spec = importlib.util.spec_from_file_location(name, root / rel)
    if spec is None or spec.loader is None:
        raise AuditError(f"cannot load {rel}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def board_cap(
    rows: Sequence[Sequence[str]],
    ticket: str,
    spec: str,
    cap: int = 10,
    twin_col: int = 3,
    status_col: int = 4,
    status: str = "PENDING",
) -> list[str]:
    """The board-cap rule: 1..cap boards, light twins at most a third, each titled
    `<ticket> / NN ...` with `status`, and the "not drawn" paragraph present."""
    bad: list[str] = []
    twins = sum(1 for r in rows if len(r) > twin_col and "light" in r[twin_col])
    if not 0 < len(rows) <= cap:
        bad.append(f"{len(rows)} boards")
    if twins * 3 > len(rows):
        bad.append(f"{twins} light twins of {len(rows)}")
    for r in rows:
        if (
            len(r) <= status_col
            or r[status_col] != status
            or not r[1].startswith(f"`{ticket} / {r[0]} ")
        ):
            bad.append(f"board {r[0] if r else '?'}")
    if "**Not drawn — the text is binding**" not in spec:
        bad.append("not-drawn paragraph")
    return bad


# ---------- G-UNTOUCHED ---------------------------------------------------------------------------
def untouched(
    changed: Iterable[str],
    own: Iterable[str],
    allowed_globs: Iterable[str] = (),
    budgets: Mapping[str, tuple[int, int]] | None = None,
    numstat: Mapping[str, tuple[int, int] | None] | None = None,
    owner_prefixes: Iterable[str] = (),
) -> list[str]:
    """Only the ticket's paths changed vs the merge-base: `own` paths, `allowed_globs`, and
    `budgets` paths whose (added, deleted) equals the budget exactly; an `owner_prefixes` path is
    never writable unless it is listed in `own` or `budgets`."""
    own_s, bud, ns = set(own), dict(budgets or {}), dict(numstat or {})
    globs, owners = tuple(allowed_globs), tuple(owner_prefixes)
    bad: list[str] = []
    for p in changed:
        if p in bud:
            got = ns.get(p)
            if got != bud[p]:
                bad.append(f"{p} is {got} (added, deleted), not {bud[p]}")
        elif p in own_s:
            continue
        elif p.startswith(owners) or not any(fnmatch.fnmatchcase(p, g) for g in globs):
            bad.append(p)
    return bad


# ---------- gates and the runner ------------------------------------------------------------------
@dataclass(frozen=True)
class Tree:
    """What gates read: `files` (label -> text: the spec, pins, hand-off, ...), the changed paths
    and their numstat. Mutations rewrite a copy, never the disk."""

    files: Mapping[str, str]
    changed: tuple[str, ...] = ()
    numstat: Mapping[str, tuple[int, int] | None] = field(default_factory=dict)

    def text(self, label: str) -> str:
        return self.files.get(label, "")

    def named(self, *labels: str) -> list[tuple[str, str]]:
        return [(lb, self.text(lb)) for lb in labels]


GateFn = Callable[[Tree], list[str]]


@dataclass(frozen=True)
class Gate:
    name: str
    fn: GateFn
    doc: str = ""


@dataclass(frozen=True)
class Result:
    gate: str
    ok: bool
    detail: tuple[str, ...]


def run_gates(gates: Sequence[Gate], tree: Tree) -> list[Result]:
    """Default-deny: a gate that raises FAILs with the exception named."""
    out: list[Result] = []
    for g in gates:
        try:
            detail = tuple(g.fn(tree))
        except (AuditError, IndexError, KeyError, ValueError, TypeError, AttributeError) as exc:
            detail = (f"gate raised {type(exc).__name__}: {exc}",)
        out.append(Result(g.name, not detail, detail))
    return out


def ascii_out(s: str) -> str:
    return s.encode("ascii", "backslashreplace").decode("ascii")


def report(results: Sequence[Result], out: Callable[[str], None] = print) -> int:
    """PASS / FAIL line per gate in gate order, then `FAIL n`; exit 1 on any FAIL."""
    fails = 0
    for r in results:
        if r.ok:
            out(f"PASS {r.gate}")
        else:
            fails += 1
            out(ascii_out(f"FAIL {r.gate}: {'; '.join(r.detail)}"))
    out(f"FAIL {fails}")
    return 1 if fails else 0


# ---------- mutations -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Mutation:
    """One planted defect. `path` is a `Tree.files` label (find -> replace, first hit; `regex`
    for re.subn), "@changed" (add `replace` to the changed paths) or "@numstat:<rel>" (set the
    numstat of <rel> to `replace`, "added deleted", and mark it changed). `fn` overrides all."""

    mid: str
    gate: str
    what: str
    path: str = "spec"
    find: str = ""
    replace: str = ""
    regex: bool = False
    fn: Callable[[Tree], Tree] | None = None


def apply_mutation(tree: Tree, m: Mutation) -> Tree:
    if m.fn is not None:
        return m.fn(tree)
    if m.path == "@changed":
        return replace(tree, changed=tuple(sorted({*tree.changed, m.replace})))
    if m.path.startswith("@numstat:"):
        rel = m.path.split(":", 1)[1]
        a, d = (int(x) for x in m.replace.split())
        return replace(
            tree,
            changed=tuple(sorted({*tree.changed, rel})),
            numstat={**tree.numstat, rel: (a, d)},
        )
    text = tree.text(m.path)
    if m.regex:
        new, n = re.subn(m.find, m.replace, text, count=1)
    else:
        n, new = text.count(m.find), text.replace(m.find, m.replace, 1)
    if n < 1 or not m.find:
        raise AuditError(f"{m.mid}: anchor not found in {m.path}")
    return replace(tree, files={**tree.files, m.path: new})


def _digest(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes() if p.exists() else b"\0missing")
    return h.hexdigest()


def lint_comment_regexes(namespace: Mapping[str, object]) -> list[str]:
    """Every compiled pattern in a tool's globals that matches HTML comments uses re.DOTALL."""
    return [
        f"{name} lacks re.DOTALL"
        for name, v in namespace.items()
        if isinstance(v, re.Pattern) and "<!--" in str(v.pattern) and not v.flags & re.DOTALL
    ]


def self_test(
    tree: Tree,
    gates: Sequence[Gate],
    mutations: Sequence[Mutation],
    disk: Sequence[Path] = (),
    namespace: Mapping[str, object] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """The clean tree must pass every gate; then each mutation must FAIL exactly its own gate
    (and no other); the files on disk are byte-identical afterwards."""
    before = _digest(disk)
    lint = lint_comment_regexes(namespace or {})
    if lint:
        out(f"self-test: {'; '.join(lint)}")
        return 1
    base = [r for r in run_gates(gates, tree) if not r.ok]
    if base:
        out(ascii_out(f"self-test: baseline not clean: {[(r.gate, r.detail) for r in base]}"))
        return 1
    names = {g.name for g in gates}
    bad = 0
    for m in mutations:
        try:
            failed = [r.gate for r in run_gates(gates, apply_mutation(tree, m)) if not r.ok]
        except AuditError as exc:
            failed = [f"setup: {exc}"]
        ok = failed == [m.gate] and m.gate in names
        bad += 0 if ok else 1
        out(ascii_out(f"{'ok ' if ok else 'BAD'} {m.mid} {m.gate}: {m.what} -> {failed}"))
    if _digest(disk) != before:
        out("self-test: files on disk changed")
        return 1
    out(f"self-test: {len(mutations) - bad} of {len(mutations)} mutations caught by their gate")
    return 1 if bad else 0


def mutation_table(
    mutations: Sequence[Mutation], widths: tuple[int, int, int] = (4, 11, 44)
) -> str:
    """The spec's mutation table (M, Gate, Mutation), padded for prettier."""
    a, b, c = widths
    head = f"| {'M':<{a}} | {'Gate':<{b}} | {'Mutation':<{c}} |\n"
    head += f"| {'-' * a} | {'-' * b} | {'-' * c} |\n"
    return head + "\n".join(f"| {m.mid:<{a}} | {m.gate:<{b}} | {m.what:<{c}} |" for m in mutations)


def check_mutlist(spec: str, heading: str, mutations: Sequence[Mutation]) -> list[str]:
    """G-MUTLIST: the spec's table under `heading` lists exactly the tool's mutations."""
    want = [[m.mid, m.gate, m.what] for m in mutations]
    return (
        [] if table_rows(section(spec, heading)) == want else [f"{heading} differs from the tool"]
    )


def cli(argv: Sequence[str], modes: Mapping[str, Callable[[], int]], doc: str | None) -> int:
    """`--<mode>` switch, exactly one required (check, self-test, repin-ruled, fill ...)."""
    ap = argparse.ArgumentParser(description=(doc or "").split("\n")[0] or None)
    grp = ap.add_mutually_exclusive_group(required=True)
    for name in modes:
        grp.add_argument(f"--{name}", action="store_true")
    args = vars(ap.parse_args(list(argv)))
    for name, fn in modes.items():
        if args[name.replace("-", "_")]:
            return fn()
    return 2


# ---------- the module's own self-test ------------------------------------------------------------
_SPEC = """# X-D01 spec

## 0. Status

Penpot: page `X-D01`, page id only.

- **R-3 The T2 rule.** G-T2.1a G-T2.1b G-T2.1c G-T2.1d G-T2.2 G-T2.3 G-T2.4 G-T2.5 \
`aria-disabled="true"`, never `disabled`; aria-describedby; CMP-079; CMP-019 lock; \
never `color.text.disabled`, never `opacity.disabled`. Reason `rbac.owner_only` with verb "record \
sessions"; state `lockout` (owner E30-D02). One notice: READ-ONLY NOTICE.

Cites: `05`:2 and D:3–4, :1.

## The questions BQ-0 … BQ-1 — RULED (comment 22)

The list is comment 11 on #1.

- **BQ-0 — a.** RULED: ACCEPT. Built as: x.
- **BQ-1 — b.** RULED: ACCEPT. Built as: y.

## 9. Mutations

"""

_D09 = """### 3.1 The keys

| Key | String |
| --- | --- |
| `rbac.owner_only` | "Only the owner can {verb}." |
| `rbac.view_as` | "Read-only while viewing as {user}." |

### 3.2 The verb table

| Domain | code |
| --- | --- |
| rec | `recording:write` → "record sessions" · `recording:read` → "see recordings" |
"""


class _MemRepo(Repo):
    """No git: every document comes from `Docs.overrides`."""

    def __init__(self) -> None:
        super().__init__(Path("."))

    def show(self, rev: str, rel: str) -> str | None:
        return None


_FIX_HEAD = ["# pins: verbatim"]


def _hash_pins(spec: str) -> str:
    return "# hashed\n" + "\n".join(bq_hash_pins(spec)) + "\n"


def _repinned(find: str, repl: str) -> Callable[[Tree], Tree]:
    """Edit the spec's BQ section and re-pin both pin styles (a ruling change done right)."""

    def fn(t: Tree) -> Tree:
        spec = t.text("spec")
        if find not in spec:
            raise AuditError(f"anchor {find!r} missing")
        spec = spec.replace(find, repl, 1)
        files = {**t.files, "spec": spec, "pins": verbatim_pins(spec, _FIX_HEAD)}
        return replace(t, files={**files, "hpins": _hash_pins(spec)})

    return fn


def _selftest_tree() -> tuple[Tree, list[Gate], list[Mutation]]:
    docs = Docs(
        _MemRepo(),
        "base",
        {"D": DocRef("d.md", "base")},
        plan={"05": "05.md"},
        overrides={
            "05": ("a", "b", "c"),
            "D": ("x", "y", "z", "w"),
            "D09": tuple(_D09.split("\n")),
        },
    )
    head = _FIX_HEAD

    def g_cite(t: Tree) -> list[str]:
        cites = extract_cites(t.text("spec"), cite_regex(["D"], ranges=True))
        return check_cites(cites, docs, min_count=3)

    def g_t2(t: Tree) -> list[str]:
        r3 = next((ln for ln in t.text("spec").split("\n\n") if "**R-3 " in ln), "")
        d09 = "\n".join(docs.lines("D09") or ())
        return (
            t2_markers(r3)
            + t2_reason_keys(
                r3, d09_keys(d09), {"lockout": "E30-D02"}, r"`(rbac\.[a-z_]+|lockout)`"
            )
            + t2_verbs(r3, d09_verbs(d09), "recording:write")
            + one_notice(t.text("spec"), "READ-ONLY NOTICE")
            + no_disabled_tokens(t.text("spec"))
        )

    gates = [
        Gate("G-CITE", g_cite),
        Gate(
            "G-RULING",
            lambda t: check_ruling(
                t.text("spec"),
                heading_line="## The questions BQ-0 … BQ-1 — RULED (comment 22)",
                list_ref="comment 11",
                count=2,
                verdict=lambda n: "RULED: ACCEPT.",
                need=("Built as:",),
            ),
        ),
        Gate("G-RULED", lambda t: check_verbatim_pins(t.text("spec"), t.text("pins"), head)),
        Gate("G-HASHPIN", lambda t: check_hash_pins(t.text("spec"), t.text("hpins"))),
        Gate("G-T2", g_t2),
        Gate("G-NOCLOSE", lambda t: closing_keywords(t.named("spec", "notes"))),
        Gate("G-HYGIENE", lambda t: whitespace_hygiene(t.named("spec", "notes"))),
        Gate(
            "G-PUBLIC",
            lambda t: scan_public(t.named("spec")) + comment_findings(t.named("spec"), ANCHOR_RE),
        ),
        Gate("G-PENPOT", lambda t: r7_findings(t.named("spec"), ("page `X-D01`",), t.text("spec"))),
        Gate(
            "G-UNTOUCHED",
            lambda t: untouched(
                t.changed,
                ("spec.md", "pins.txt"),
                ("img/X-D01-*.png",),
                {"cat.md": (1, 0)},
                t.numstat,
                ("docs/plan/",),
            ),
        ),
    ]
    k, x = "Clo" + "ses #", "/" + "ho" + "me/"
    muts = [
        Mutation("M-1", "G-CITE", "a cite past the end", "spec", "`05`:2", "`05`:9"),
        Mutation("M-2", "G-CITE", "a range end past the end", "spec", "D:3–4", "D:3–5"),
        Mutation("M-3", "G-CITE", "a tail cite on nothing", "spec", "–4, :1", "–4, :7"),
        Mutation(
            "M-4",
            "G-RULING",
            "a verdict changed, re-pinned",
            fn=_repinned("a.** RULED: ACCEPT", "a.** RULED: OVER"),
        ),
        Mutation("M-5", "G-RULED", "pins edited", "pins", "## The", "## the"),
        Mutation("M-6", "G-HASHPIN", "hash pin edited", "hpins", "BQ-1 ", "BQ-1 0"),
        Mutation("M-7", "G-T2", "a marker dropped", "spec", "G-T2.1c ", ""),
        Mutation("M-8", "G-T2", "an unknown key", "spec", "rbac.owner_only", "rbac.owner"),
        Mutation("M-9", "G-T2", "an off-table verb", "spec", '"record sessions"', '"rec"'),
        Mutation("M-10", "G-T2", "the owner not named", "spec", "(owner E30-D02)", "(owner)"),
        Mutation("M-11", "G-T2", "two notices", "spec", "Cites:", "READ-ONLY NOTICE\n\nCites:"),
        Mutation(
            "M-12",
            "G-T2",
            "a disabled token used",
            "spec",
            "Cites:",
            "Uses `opacity.disabled`.\n\nCites:",
        ),
        Mutation("M-13", "G-NOCLOSE", "a closing keyword", "spec", "Cites:", k + "1\n\nCites:"),
        Mutation("M-14", "G-NOCLOSE", "a no-space keyword", "notes", "notes", "Fix" + "es#2"),
        Mutation("M-15", "G-HYGIENE", "a CRLF", "spec", "## 0. Status\n", "## 0. Status\r\n"),
        Mutation(
            "M-16", "G-HYGIENE", "a trailing blank", "spec", "## 0. Status\n", "## 0. Status \n"
        ),
        Mutation("M-17", "G-PUBLIC", "a local path", "spec", "Cites:", x + "a\n\nCites:"),
        Mutation(
            "M-18", "G-PUBLIC", "a stray comment", "spec", "Cites:", "<!-- a\nb -->\n\nCites:"
        ),
        Mutation("M-19", "G-PENPOT", "a file id", "spec", "page id only", "file" + "-id=3"),
        Mutation("M-20", "G-UNTOUCHED", "an owner doc", "@changed", "", "docs/plan/05.md"),
        Mutation("M-21", "G-UNTOUCHED", "over budget", "@numstat:cat.md", "", "2 0"),
        Mutation("M-22", "G-UNTOUCHED", "a stray png", "@changed", "", "img/Y-D01-01.png"),
    ]
    muts.append(Mutation("M-23", "G-MUTLIST", "the list drifts", "spec", "| M-1  |", "| M-01 |"))
    spec = _SPEC + mutation_table(muts) + "\n"
    tree = Tree(
        files={
            "spec": spec,
            "pins": verbatim_pins(spec, head),
            "hpins": _hash_pins(spec),
            "notes": "notes\n",
        },
        changed=("cat.md", "img/X-D01-01.png", "spec.md"),
        numstat={"cat.md": (1, 0)},
    )
    gates.append(Gate("G-MUTLIST", lambda t: check_mutlist(t.text("spec"), "## 9.", muts)))
    return tree, gates, muts


def _unit_checks() -> list[str]:
    bad: list[str] = []
    fx = Docs(_MemRepo(), "b", {}, overrides={"K": ("one", "", "needle here", "x", "needle")})
    pins = [KeyCite("K", 3, "needle"), KeyCite("K", 2, "needle")]
    if check_key_cites(pins, fx) != ["K:2 no longer carries 'needle' (re-pin the cite)"]:
        bad.append("check_key_cites")
    if [n for _, n in repin_key_cites([*pins, KeyCite("K", 1, "gone")], fx)] != [3, 3, None]:
        bad.append("repin_key_cites")
    if check_cites(extract_cites("K:2", cite_regex(["K"])), fx) == []:
        bad.append("a blank cited line passed")
    if t2_reason_string("Only the owner can record sessions.") is not None:
        bad.append("t2_reason_string rejected a good string")
    if t2_reason_string("Two. Sentences.") is None or t2_reason_string("x" * 61 + ".") is None:
        bad.append("t2_reason_string accepted a bad string")
    if not CLOSING_RE.search("reso" + "lved: #12") or CLOSING_RE.search("fixed in #12"):
        bad.append("CLOSING_RE")
    if COMMENT_RE.flags & re.DOTALL == 0 or COMMENT_OPEN_RE.flags & re.DOTALL == 0:
        bad.append("comment regexes lack DOTALL")
    if lint_comment_regexes({"X": re.compile("<!" + "-- marker")}) != ["X lacks re.DOTALL"]:
        bad.append("lint_comment_regexes")
    if not comment_findings([("s", "a <!-- open")]):
        bad.append("an unterminated comment passed")
    if comment_findings([("s", "<!-- audit:base=abc12 -->")], ANCHOR_RE):
        bad.append("an allowed audit anchor failed")
    own = [("lib", _own_text())]
    if scan_public([("tool", __doc__ or "")]) or closing_keywords(own) or whitespace_hygiene(own):
        bad.append("the module trips its own scan")
    if untouched(["a/b.png"], [], ["a/*.png"]) or not untouched(["a/b.txt"], [], ["a/*.png"]):
        bad.append("untouched globs")
    t = Tree(files={"s": "abc"})
    try:
        apply_mutation(t, Mutation("M-0", "G", "x", "s", "zzz", "y"))
        bad.append("a missing anchor did not raise")
    except AuditError:
        pass
    return bad


def _own_text() -> str:
    return Path(__file__).read_text(encoding="utf-8")


def _git_checks(scratch: Path) -> list[str]:
    """diff_base and changed paths in a throw-away repository under `scratch`."""
    bad: list[str] = []
    with tempfile.TemporaryDirectory(dir=scratch) as d:
        root = Path(d)
        repo = Repo(root)
        for args in (
            ("init", "-q", "-b", "main"),
            ("config", "user.email", "t@example.invalid"),
            ("config", "user.name", "t"),
            ("config", "commit.gpgsign", "false"),
        ):
            repo.git(*args)

        def commit(name: str, body: str) -> str:
            (root / name).write_text(body, encoding="utf-8")
            repo.git("add", name)
            repo.git("commit", "-q", "-m", name)
            return repo.git("rev-parse", "HEAD").strip()

        c0 = commit("a.md", "a\n")
        repo.git("checkout", "-q", "-b", "topic")
        commit("spec.md", "s\n")
        repo.git("checkout", "-q", "main")
        c2 = commit("main.md", "m\n")
        repo.git("update-ref", "refs/remotes/origin/main", c2)
        repo.git("checkout", "-q", "topic")
        if repo.diff_base("FALLBACK") != c0:
            bad.append("diff_base on the branch")
        if repo.changed_paths(c0) != ("spec.md",):
            bad.append("changed_paths")
        repo.git("merge", "-q", "--no-commit", "--no-ff", "origin/main")
        if repo.diff_base("FALLBACK") != c2:
            bad.append("diff_base during a simulated merge (branch side)")
        elif repo.changed_paths(c2) != ("spec.md",):
            bad.append("changed_paths during a simulated merge")
        repo.git("merge", "--abort")
        repo.git("checkout", "-q", "--detach", c2)
        repo.git("merge", "-q", "--no-commit", "--no-ff", "topic")
        if repo.diff_base("FALLBACK") != c2:
            bad.append("diff_base during a simulated merge (main side)")
        repo.git("merge", "--abort")
        if repo.show(c0, "a.md") != "a\n" or repo.show(c0, "nope.md") is not None:
            bad.append("show")
        if repo.numstat(c0, "a.md") is not None:
            bad.append("numstat of an unchanged file")
        repo.git("update-ref", "-d", "refs/remotes/origin/main")
        if repo.diff_base("FALLBACK") != "FALLBACK":
            bad.append("diff_base fallback")
    return bad


def _self_test(git_scratch: Path | None) -> int:
    bad = _unit_checks()
    for b in bad:
        print(f"BAD unit: {b}")
    tree, gates, muts = _selftest_tree()
    code = self_test(tree, gates, muts, namespace=globals())
    if git_scratch is not None:
        gbad = _git_checks(git_scratch)
        for b in gbad:
            print(f"BAD git: {b}")
        print(f"git checks: {'ok' if not gbad else f'{len(gbad)} failed'}")
        bad += gbad
    print(f"unit checks: {'ok' if not bad else f'{len(bad)} failed'}")
    return 1 if bad or code else 0


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="spec_audit_lib self-test")
    ap.add_argument("--self-test", action="store_true", required=True)
    ap.add_argument("--git-scratch", type=Path, default=None)
    args = ap.parse_args(list(argv))
    return _self_test(args.git_scratch)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
