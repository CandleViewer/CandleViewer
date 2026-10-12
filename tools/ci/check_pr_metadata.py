#!/usr/bin/env python3
"""`pr-metadata` required check (CONSTITUTION C-9.1 #20): PR size, title, body, rule refs.

Reads the LIVE PR (title, body, labels, label events, comments) from the GitHub API using
GH_TOKEN / GITHUB_REPOSITORY / PR_NUMBER from the environment, so edits and label changes are seen
even on a manual re-run (never the stale event payload). Nothing else touches the network.

Rules
  C-4.8  changed LOC, excluding lockfiles and paths `linguist-generated` in the BASE commit's
         .gitattributes (the PR under test cannot widen its own exclusions; last match wins and
         `-attr` / `=false` are honoured). Warn > 400, FAIL > 800 without `large-pr-approved`.
         PR-SIZE-002: the PR changes linguist-generated/diff/binary attribute lines -> needs the label
         (the LOC that would be newly excluded is printed). PR-SIZE-003: too many non-image binary
         files (binary rows are invisible to numstat LOC). PR-SIZE-004/005: the label must have been
         applied by an owner and a written justification comment from an owner must exist. Owners =
         the repo owner plus `@user` entries of the BASE CODEOWNERS matching the changed paths.
         Limitation: `@org/team` owners cannot be resolved with a read-only GITHUB_TOKEN.
  C-4.10 title is `type(scope)[!]: subject`; type/scope sets are parsed from commitlint.config.cjs
         (never restated); scope is required iff commitlint's `scope-empty` is `never`.
  C-4.7  body (HTML comments and code spans stripped) contains `Closes #N` or `Fixes #N`.
         INTERPRETATION pending a C-4.7 amendment: `Refs #N` is accepted (with a WARN) only when
         the body also has a line `Partial: <reason>` (stack slice, contract-first, scaffold), so
         partial work is not pushed into `Closes` (which auto-closes the issue). Neither -> PR-BODY-001.
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
import urllib.request
from collections.abc import Callable
from pathlib import Path

WARN_LOC = 400
FAIL_LOC = 800
MAX_OTHER_BINARY = 3
LABEL = "large-pr-approved"
LOCKFILES = frozenset({"pnpm-lock.yaml", "services/api/uv.lock"})
BINARY_OK_RE = re.compile(r"\.(png|jpe?g|gif|webp|ico|svg|woff2?|ttf|otf|eot)$", re.IGNORECASE)
ATTRS = ("linguist-generated", "diff", "binary")
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
    anchored = "/" in pattern.strip("/")
    tail = "(?:/.*)?" if pattern.endswith("/") else ""
    return re.compile(("^" if anchored else r"^(?:.*/)?") + out.rstrip("/") + tail + "$")


def attr_rules(gitattributes: str, attr: str) -> list[tuple[re.Pattern[str], bool | None]]:
    """Ordered (pattern, state) for one attribute: True set, False unset/false, None `!attr`."""
    rules: list[tuple[re.Pattern[str], bool | None]] = []
    for line in gitattributes.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) < 2:
            continue
        for tok in parts[1:]:
            state: bool | None
            if tok in (attr, f"{attr}=true"):
                state = True
            elif tok in (f"-{attr}", f"{attr}=false"):
                state = False
            elif tok == f"!{attr}":
                state = None
            else:
                continue
            rules.append((_glob_re(parts[0]), state))
    return rules


def is_generated(path: str, rules: list[tuple[re.Pattern[str], bool | None]]) -> bool:
    state: bool | None = None
    for pat, st in rules:  # last match wins
        if pat.match(path):
            state = st
    return bool(state)


def parse_numstat_z(raw: str) -> list[tuple[str, str, str]]:
    rows = []
    for rec in raw.split("\0"):
        parts = rec.split("\t", 2)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def count_loc(rows: list[tuple[str, str, str]], gen_rules) -> tuple[int, int, list[str]]:
    """Return (counted LOC, excluded LOC, binary paths not on the image/font allowlist)."""
    counted = excluded = 0
    binary: list[str] = []
    for add, dele, path in rows:
        if add == "-" or dele == "-":
            if not BINARY_OK_RE.search(path):
                binary.append(path)
            continue
        n = int(add) + int(dele)
        if path in LOCKFILES or is_generated(path, gen_rules):
            excluded += n
        else:
            counted += n
    return counted, excluded, binary


def attr_lines(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip()
        if s and any(a in tok for tok in s.split()[1:] for a in ATTRS):
            out.add(" ".join(s.split()))
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
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", body)


def check_label_provenance(events, comments, allowed: set[str]) -> list[str]:
    errs = []
    actors = [
        (e.get("actor") or {}).get("login", "")
        for e in events
        if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == LABEL
    ]
    if not actors or actors[-1].lower() not in allowed:
        errs.append(
            f"PR-SIZE-004 C-4.8: `{LABEL}` must be applied by a CODEOWNER; last applied by "
            f"{actors[-1] if actors else 'unknown'!r}, allowed: {sorted(allowed)}"
        )
    if not any(
        (c.get("user") or {}).get("login", "").lower() in allowed
        and LABEL in (c.get("body") or "").lower()
        and len((c.get("body") or "").strip()) >= 40
        for c in comments
    ):
        errs.append(
            f"PR-SIZE-005 C-4.8: no written justification (comment >=40 chars mentioning "
            f"`{LABEL}`) from an owner"
        )
    return errs


def check(
    pr: dict,
    rows: list[tuple[str, str, str]],
    base_attrs: str,
    head_attrs: str,
    commitlint: str,
    declared: set[str],
    rule_id_re: re.Pattern[str],
    events=(),
    comments=(),
    base_codeowners: str = "",
    repo_owner: str = "",
) -> tuple[list[str], list[str]]:
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    has_label = LABEL in {lab.get("name") for lab in pr.get("labels") or []}
    errors: list[str] = []
    warnings: list[str] = []
    needs_approval: list[str] = []

    gen = attr_rules(base_attrs, "linguist-generated")
    loc, excl, binary = count_loc(rows, gen)
    info = f"{loc} changed LOC ({excl} excluded: generated/lockfiles)"
    if loc > FAIL_LOC:
        needs_approval.append(f"PR-SIZE-001 C-4.8: {info} exceeds {FAIL_LOC}")
    elif loc > WARN_LOC:
        warnings.append(f"C-4.8: {info} exceeds preferred {WARN_LOC}; add a why-not-split note")
    if len(binary) > MAX_OTHER_BINARY:
        needs_approval.append(
            f"PR-SIZE-003 C-4.8: {len(binary)} binary files outside images/fonts (LOC unseen): "
            f"{binary[:5]}"
        )
    changed = [r[2] for r in rows]
    nested = [p for p in changed if p.rsplit("/", 1)[-1] == ".gitattributes" and p != ".gitattributes"]
    if attr_lines(base_attrs) != attr_lines(head_attrs) or nested:
        newly = count_loc(rows, attr_rules(head_attrs, "linguist-generated"))[1] - excl
        needs_approval.append(
            f"PR-SIZE-002 C-4.8: PR changes linguist-generated/diff/binary attributes "
            f"({newly} LOC would be newly excluded; nested .gitattributes: {nested})"
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
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise ConfigError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def _show(root: Path, rev: str, path: str) -> str:
    r = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def make_api_fetch(repo: str, token: str) -> Fetch:
    def fetch(path: str) -> object:
        out: list = []
        for page in range(1, 11):
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
                break
        return out

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
        raw = _git(root, "--attr-source=" + base, "diff", "--numstat", "-z", "--no-renames",
                   f"{base}...{head}")
        rr = _load_rule_refs(root)
        errors, warnings = check(
            pr,
            parse_numstat_z(raw),
            _show(root, base, ".gitattributes"),
            _show(root, head, ".gitattributes"),
            (root / "commitlint.config.cjs").read_text(encoding="utf-8"),
            rr.load_declared_ids(str(root)),
            rr.RULE_ID_RE,
            events=fetch(f"/issues/{num}/events"),
            comments=fetch(f"/issues/{num}/comments"),
            base_codeowners=_show(root, base, ".github/CODEOWNERS"),
            repo_owner=repo.split("/")[0],
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
