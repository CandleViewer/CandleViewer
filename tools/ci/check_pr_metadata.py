#!/usr/bin/env python3
"""`pr-metadata` required check (CONSTITUTION C-9.1 #20): PR size, title, body, rule refs.

Reads the LIVE PR (title, body, labels, label events, comments) from the GitHub API using
GH_TOKEN / GITHUB_REPOSITORY / PR_NUMBER from the environment, so edits and label changes are seen
even on a manual re-run (never the stale event payload). Nothing else touches the network.

Trust model. The workflow runs THIS file from a worktree of current origin/main (`python -I`,
see .github/workflows/pr-metadata.yml; the event's base.sha is never trusted, it is stale for any
PR opened before a merge), so a PR cannot rewrite the checker, its commitlint.config.cjs,
scripts/check_rule_refs.py, .gitattributes or CODEOWNERS that judge it. The PR's CONSTITUTION.md is
read through `git show` as data only. The workflow has a bootstrap branch (PR #2256 only, while the
checker has no history on main) that runs the PR copy; it must be deleted right after merge (#2280).
REMAINING GAPS (not fixable inside this script): under `pull_request` the workflow YAML itself is
PR-controlled, so editing pr-metadata.yml is still a bypass that only the C-10.2 workflow security
review catches; and every agent session currently acts as the repo owner account, so label
provenance (PR-SIZE-004/005) is not independent of the PR author until agents use a separate
machine user / GitHub App (follow-up issue). `@org/team` CODEOWNERS entries are not resolvable
with a read-only token (only `@user` entries and the repo owner count).

Rules
  C-4.8  changed LOC, excluding lockfiles and paths whose `linguist-generated` attribute is set in
         the BASE commit (evaluated by `git check-attr --source=<base>`, so git's own matching
         rules apply and the PR cannot widen its own exclusions). Warn > 400, FAIL > 800 without
         `large-pr-approved`.
         PR-SIZE-002: the PR changes linguist-generated/diff/binary attributes (vs the merge-base)
         -> needs the label; the LOC that would be newly excluded is printed.
         PR-SIZE-003: LOC of binary-classified files is counted from a `-U0 --text` patch (NUL bytes / `-diff` cannot hide lines).
         Files git still classes as binary are reviewer-invisible: images/fonts are allowlisted,
         paths generated in base are excluded; every other one gets a ::warning with its size and
         needs the label (allowlist, not denylist: .so/.node/.wasm, extensionless, hooks).
         PR-SIZE-006: changing the gate's own files needs the label.
         PR-SIZE-004/005: the label must have been applied by an owner, and that same owner must
         have posted a justification comment (>= 40 chars) at or after the labelling.
  C-4.10 title is `type(scope)[!]: subject`; type/scope sets are parsed from commitlint.config.cjs
         (never restated); scope is required iff commitlint's `scope-empty` is `never`.
  C-4.7  body (HTML comments, code fences/blocks and code spans stripped) contains `Closes #N` or
         `Fixes #N`. INTERPRETATION pending a C-4.7 amendment (#2261): `Refs #N` is accepted (WARN)
         only with a line `Partial: <reason>` (stack slice, contract-first, scaffold), so partial
         work is not pushed into `Closes` (which auto-closes the issue). Else PR-BODY-001/002.
  C-16.4 every `C-x.y` cited in title/body is declared in CONSTITUTION.md. The declaration loader
         is reused from scripts/check_rule_refs.py (GOV-002; scans tracked files, not PR text) -
         C-16.5, no second implementation.
Not covered yet (C-9.1 #20 also lists them): branch-name pattern, changed-files-vs-labels sanity,
duplicated-single-source-list check (the latter is scripts/check_sot_duplication.py in `governance`).

Exit 0 ok (warnings allowed), 1 violations, 2 internal/config error.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

WARN_LOC = 400
FAIL_LOC = 800
GATE_FILES = frozenset({
    ".github/workflows/pr-metadata.yml",
    "tools/ci/check_pr_metadata.py",
    "scripts/check_rule_refs.py",
    "commitlint.config.cjs",
})
LABEL = "large-pr-approved"
LOCKFILES = frozenset({"pnpm-lock.yaml", "services/api/uv.lock"})
BINARY_OK_RE = re.compile(r"\.(png|jpe?g|gif|webp|ico|woff2?|ttf|otf|eot)$", re.IGNORECASE)
ATTRS = ("linguist-generated", "diff", "binary")
MAX_PAGES = 10
LINK_RE = re.compile(r"\b(?:Closes|Fixes)\s+#\d+\b", re.IGNORECASE)
REFS_RE = re.compile(r"\bRefs\s+#\d+\b", re.IGNORECASE)
PARTIAL_RE = re.compile(r"^[ \t]*Partial:[ \t]*\S", re.MULTILINE)
Fetch = Callable[[str], object]


class ConfigError(Exception):
    pass


def _load_rule_refs(repo_root: Path):
    path = repo_root / "scripts" / "check_rule_refs.py"
    spec = importlib.util.spec_from_file_location("_cv_check_rule_refs", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_commitlint(text: str) -> tuple[set[str], set[str], bool]:
    """Return (types, scopes, scope_required); raises ConfigError if either set is empty."""
    scopes: set[str] = set()
    for name in ("AREA_SCOPES", "COMPONENT_SCOPES", "PACKAGE_SCOPES"):
        m = re.search(rf"const {name}\s*=\s*\[(.*?)\];", text, re.S)
        if m:
            scopes |= set(re.findall(r'"([^"]+)"', m.group(1)))
    t = re.search(r'"type-enum"\s*:\s*\[\s*\d+\s*,\s*"always"\s*,\s*\[(.*?)\]', text, re.S)
    types = set(re.findall(r'"([^"]+)"', t.group(1))) if t else set()
    if not types or not scopes:
        raise ConfigError(
            f"PR-CONFIG-001: parsed {len(types)} types / {len(scopes)} scopes from "
            "commitlint.config.cjs; the file layout changed, update parse_commitlint"
        )
    required = bool(re.search(r'"scope-empty"\s*:\s*\[\s*2\s*,\s*"never"', text))
    return types, scopes, required


def _glob_re(pattern: str) -> re.Pattern[str]:
    """CODEOWNERS-style glob (attributes are evaluated by git itself, see attr_state)."""
    pat = pattern.lstrip("/")
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**", i):
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pat[i])
            i += 1
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    tail = "(?:/.*)?" if pattern.endswith("/") else ""
    return re.compile(("^" if anchored else r"^(?:.*/)?") + out.rstrip("/") + tail + "$")


AttrState = dict[str, tuple[str, str, str]]


def attr_state(root: Path, source: str, paths: list[str]) -> AttrState:
    """linguist-generated / diff / binary per path as evaluated by git at commit `source`."""
    if not paths:
        return {}
    r = subprocess.run(
        ["git", "check-attr", f"--source={source}", "-z", "--stdin", *ATTRS],
        cwd=root, input="\0".join(paths) + "\0", capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise ConfigError(f"git check-attr failed: {r.stderr.strip()}")
    f = r.stdout.split("\0")
    out: dict[str, dict[str, str]] = {}
    for i in range(0, len(f) - 2, 3):
        out.setdefault(f[i], {})[f[i + 1]] = f[i + 2]
    return {p: tuple(out.get(p, {}).get(a, "unspecified") for a in ATTRS) for p in paths}  # type: ignore[misc]


def _generated(state: tuple[str, str, str] | None) -> bool:
    return bool(state) and state[0] in ("set", "true")


def parse_numstat_z(raw: str) -> list[tuple[str, str, str]]:
    rows = []
    for rec in raw.split("\0"):
        parts = rec.split("\t", 2)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def text_loc(patch: str) -> int:
    """+/- line count of a `git diff --text -U0` patch for ONE path (headers excluded)."""
    n = 0
    for line in patch.split("\n"):
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            n += 1
    return n


def count_loc(
    rows: list[tuple[str, str, str]], base_state: AttrState, binary_paths: frozenset[str] = frozenset()
) -> tuple[int, int, list[str]]:
    """Return (counted LOC, excluded LOC, binary paths needing approval).

    `rows` carry real +/- counts even for files git classes as binary (see text_loc), so a NUL
    byte or a `-diff` attribute never hides lines. `binary_paths` (rows git reports as binary WITHOUT --text) are only used for reviewer
    visibility: allowlisted images/fonts count 0 LOC; linguist-generated (in base) paths are
    excluded; every other binary path is counted AND flagged (allowlist, not denylist).
    """
    counted = excluded = 0
    flagged: list[str] = []
    for add, dele, path in rows:
        n = int(add) + int(dele)
        generated = path in LOCKFILES or _generated(base_state.get(path))
        if path in binary_paths and not generated:
            if BINARY_OK_RE.search(path):
                continue
            flagged.append(path)
        if generated:
            excluded += n
        else:
            counted += n
    return counted, excluded, flagged


def attr_lines(text: str) -> list[str]:
    """Normalised attribute lines mentioning linguist-generated/diff/binary (`#` only at line start)."""
    out = []  # ordered: git is last-match-wins, so reordering changes the result
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and any(a in tok for tok in s.split()[1:] for a in ATTRS):
            out.append(" ".join(s.split()))
    return out


def owners_for(codeowners: str, paths: list[str]) -> set[str]:
    owners: set[str] = set()
    rules = []
    for line in codeowners.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2:
            rules.append((_glob_re(parts[0]), parts[1:]))
    for path in paths:
        hit: list[str] = []
        for pat, own in rules:  # last match wins
            if pat.match(path):
                hit = own
        owners |= {o[1:].lower() for o in hit if o.startswith("@") and "/" not in o}
    return owners


def strip_markup(body: str) -> str:
    """Remove what GitHub does not parse as closing references (unclosed ones run to the end)."""
    body = re.sub(r"<!--.*?(?:-->|\Z)", "", body, flags=re.S)
    body = re.sub(r"(```|~~~).*?(?:\1|\Z)", "", body, flags=re.S)
    body = re.sub(r"^(?: {4}|\t).*$", "", body, flags=re.M)
    return re.sub(r"`[^`\n]*`", "", body)


def check_label_provenance(events, comments, allowed: set[str]) -> list[str]:
    errs = []
    labelled = [
        e for e in events
        if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == LABEL
    ]
    last = labelled[-1] if labelled else {}
    actor = ((last.get("actor") or {}).get("login") or "").lower()
    when = last.get("created_at") or ""
    if not actor or actor not in allowed:
        errs.append(
            f"PR-SIZE-004 C-4.8: `{LABEL}` must be applied by a CODEOWNER; last applied by "
            f"{actor or 'unknown'!r}, allowed: {sorted(allowed)}"
        )
    if not any(
        ((c.get("user") or {}).get("login") or "").lower() == actor
        and (c.get("created_at") or "") >= when
        and LABEL in (c.get("body") or "").lower()
        and len((c.get("body") or "").strip()) >= 40
        for c in comments
    ):
        errs.append(
            f"PR-SIZE-005 C-4.8: no written justification (comment >=40 chars mentioning "
            f"`{LABEL}`) by the labelling owner at/after the label was applied"
        )
    return errs


def check(
    pr: dict,
    rows: list[tuple[str, str, str]],
    base_state: AttrState,
    head_state: AttrState,
    base_attrs: str,
    head_attrs: str,
    commitlint: str,
    declared: set[str],
    rule_id_re: re.Pattern[str],
    events=(),
    comments=(),
    base_codeowners: str = "",
    repo_owner: str = "",
    binary_sizes: dict[str, str] | None = None,
    binary_paths: frozenset[str] = frozenset(),
    merge_base_state: AttrState | None = None,
) -> tuple[list[str], list[str]]:
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    has_label = LABEL in {lab.get("name") for lab in pr.get("labels") or []}
    errors: list[str] = []
    warnings: list[str] = []
    needs_approval: list[str] = []

    loc, excl, binary = count_loc(rows, base_state, binary_paths)
    info = f"{loc} changed LOC ({excl} excluded: generated/lockfiles)"
    if loc > FAIL_LOC:
        needs_approval.append(f"PR-SIZE-001 C-4.8: {info} exceeds {FAIL_LOC}")
    elif loc > WARN_LOC:
        warnings.append(f"C-4.8: {info} exceeds preferred {WARN_LOC}; add a why-not-split note")
    for path in binary:
        size = (binary_sizes or {}).get(path, "deleted")
        warnings.append(f"C-4.8: binary-classified file {path!r} ({size} bytes) is hidden from reviewers")
    if binary:
        needs_approval.append(
            f"PR-SIZE-003 C-4.8: {len(binary)} binary file(s) that are neither images/fonts nor "
            f"generated in base: {binary[:5]}"
        )
    changed = [r[2] for r in rows]
    nested = [p for p in changed if p.rsplit("/", 1)[-1] == ".gitattributes" and p != ".gitattributes"]
    before = merge_base_state if merge_base_state is not None else base_state
    drift = [p for p in changed if before.get(p) != head_state.get(p)]
    touched_gate = sorted(set(changed) & GATE_FILES)
    if touched_gate:
        needs_approval.append(
            f"PR-SIZE-006 C-4.8/C-10.2: PR changes the gate's own files {touched_gate}"
        )
    if attr_lines(base_attrs) != attr_lines(head_attrs) or nested or drift:
        newly = sum(
            int(a) + int(d)
            for a, d, p in rows
            if _generated(head_state.get(p)) and not _generated(before.get(p))
            and p not in LOCKFILES
        )
        needs_approval.append(
            f"PR-SIZE-002 C-4.8: PR changes linguist-generated/diff/binary attributes "
            f"({newly} LOC would be newly excluded; nested .gitattributes: {nested}; "
            f"changed-path attribute drift: {drift[:5]})"
        )
    if needs_approval:
        if not has_label:
            errors += [f"{m}; split it or have a CODEOWNER apply `{LABEL}`" for m in needs_approval]
        else:
            allowed = owners_for(base_codeowners, changed) | ({repo_owner.lower()} - {""})
            errors += check_label_provenance(events, comments, allowed)
            warnings += [f"{m} (approved by label)" for m in needs_approval]

    types, scopes, scope_required = parse_commitlint(commitlint)
    m = re.match(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)\s]+)\))?(?P<bang>!)?: (?P<subj>\S.*)$", title)
    if not m or (scope_required and not m["scope"]):
        errors.append(f"PR-TITLE-001 C-4.10: title {title!r} is not `type(scope): subject`")
    else:
        if m["type"] not in types:
            errors.append(f"PR-TITLE-002 C-4.10: type {m['type']!r} not in {sorted(types)}")
        if m["scope"] and m["scope"] not in scopes:
            errors.append(f"PR-TITLE-003 C-4.10: scope {m['scope']!r} not an allowed scope")

    clean = strip_markup(body)
    if LINK_RE.search(clean):
        pass
    elif REFS_RE.search(clean) and PARTIAL_RE.search(clean):
        warnings.append("C-4.7: `Refs #N` + `Partial:` accepted as a partial/stacked PR (interpretation)")
    elif REFS_RE.search(clean):
        errors.append("PR-BODY-002 C-4.7: `Refs #N` needs a `Partial: <reason>` line (else use `Closes #N`)")
    else:
        errors.append("PR-BODY-001 C-4.7: body needs `Closes #N` (or `Fixes #N`) outside code/comments")

    for rid in sorted(set(rule_id_re.findall(f"{title}\n{body}")) - declared):
        errors.append(f"PR-RULE-001 C-16.4: {rid} is cited but not declared in CONSTITUTION.md")
    return errors, warnings


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise ConfigError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def _show(root: Path, rev: str, path: str, required: bool = False) -> str:
    r = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True)
    if r.returncode != 0 and required:
        raise ConfigError(f"git show {rev}:{path} failed: {r.stderr.strip()}")
    return r.stdout if r.returncode == 0 else ""


def make_api_fetch(repo: str, token: str) -> Fetch:
    def fetch(path: str) -> object:
        out: list = []
        for page in range(1, MAX_PAGES + 1):
            sep = "&" if "?" in path else "?"
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}{path}{sep}per_page=100&page={page}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
                data = json.load(resp)
            if isinstance(data, dict):
                return data
            out += data
            if len(data) < 100:
                return out
        raise ConfigError(f"{path}: more than {MAX_PAGES * 100} records; cannot verify, failing closed")

    return fetch


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    root = a.repo_root.resolve()
    try:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        num = os.environ.get("PR_NUMBER", "")
        if fetch is None:
            token = os.environ.get("GH_TOKEN", "")
            if not (repo and num and token):
                raise ConfigError("GITHUB_REPOSITORY, PR_NUMBER and GH_TOKEN are required")
            fetch = make_api_fetch(repo, token)
        pr = fetch(f"/pulls/{num}")
        assert isinstance(pr, dict)
        base, head = pr["base"]["sha"], pr["head"]["sha"]
        merge_base = _git(root, "merge-base", base, head).strip()
        diff = ["--attr-source=" + base, "diff", "--numstat", "-z", "--no-renames", f"{base}...{head}"]
        rows = parse_numstat_z(_git(root, *diff))
        binary_paths = frozenset(r[2] for r in rows if r[0] == "-")
        fixed = []
        for add, dele, path in rows:
            if path in binary_paths and not BINARY_OK_RE.search(path):  # numstat shows `-`; recount from a forced-text patch
                patch = _git(root, "--attr-source=" + base, "diff", "--text", "-U0", "--no-renames",
                             f"{base}...{head}", "--", path)
                add, dele = str(text_loc(patch)), "0"
            elif path in binary_paths:  # allowlisted image/font: counts no LOC
                add, dele = "0", "0"
            fixed.append((add, dele, path))
        rows = fixed
        paths = [r[2] for r in rows]
        sizes = {}
        for path in sorted(binary_paths):
            if subprocess.run(["git", "cat-file", "-e", f"{head}:{path}"], cwd=root,
                              capture_output=True).returncode == 0:
                sizes[path] = _git(root, "cat-file", "-s", f"{head}:{path}").strip()
        rr = _load_rule_refs(root)  # root is the BASE worktree in CI
        with tempfile.TemporaryDirectory() as tmp:  # head CONSTITUTION: data only, never executed
            (Path(tmp) / "CONSTITUTION.md").write_text(
                _show(root, head, "CONSTITUTION.md", required=True), encoding="utf-8"
            )
            declared = rr.load_declared_ids(tmp)
        errors, warnings = check(
            pr,
            rows,
            attr_state(root, base, paths),
            attr_state(root, head, paths),
            _show(root, merge_base, ".gitattributes"),
            _show(root, head, ".gitattributes"),
            (root / "commitlint.config.cjs").read_text(encoding="utf-8"),
            declared,
            rr.RULE_ID_RE,
            events=fetch(f"/issues/{num}/events"),
            comments=fetch(f"/issues/{num}/comments"),
            base_codeowners=_show(root, base, ".github/CODEOWNERS"),
            repo_owner=repo.split("/")[0],
            binary_sizes=sizes,
            binary_paths=binary_paths,
            merge_base_state=attr_state(root, merge_base, paths),
        )
    except ConfigError as exc:
        print(f"::error title=pr-metadata::{exc}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"::warning title=pr-metadata::{w}")
    for e in errors:
        print(f"::error title=pr-metadata::{e}", file=sys.stderr)
    if errors:
        return 1
    print("pr-metadata: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
