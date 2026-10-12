#!/usr/bin/env python3
"""`pr-metadata` required check (CONSTITUTION C-9.1 #20): PR size, title, body, rule refs.

Reads the GitHub `pull_request` event payload (JSON file) and a `git diff --numstat` of the PR.
No network. Rules:
  1. C-4.8  changed LOC (excl. `linguist-generated` paths in .gitattributes and lockfiles):
            warn > 400, FAIL > 800 unless label `large-pr-approved` is present.
            Limitation: the check only sees that the label is present; the event payload does
            not prove a CODEOWNER applied it. Label-write rights and the written-justification
            comment are enforced by repo permissions and review, not by this script.
  2. C-4.10 title is `type(scope)[!]: subject` with type/scope allowed by commitlint.config.cjs
            (the single source for both lists - they are parsed, never restated here).
  3. C-4.7  body contains `Closes #N`, `Fixes #N` or `Refs #N`.
  4. C-16.4 every `C-x.y` cited in title/body is declared in CONSTITUTION.md. The declaration
            loader and id regex are reused from scripts/check_rule_refs.py (GOV-002, which
            scans tracked files only, not PR text) - C-16.5, no second implementation.

Usage:
  python tools/ci/check_pr_metadata.py --event "$GITHUB_EVENT_PATH" --repo-root . \
      [--numstat-file F | --base SHA --head SHA]
Exit 0 ok (warnings allowed), 1 violations.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

WARN_LOC = 400
FAIL_LOC = 800
LABEL = "large-pr-approved"
LOCKFILES = frozenset(
    {"pnpm-lock.yaml", "package-lock.json", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock"}
)
TITLE_RE = re.compile(r"^(?P<type>[a-z]+)\((?P<scope>[^)\s]+)\)(?P<bang>!)?: (?P<subject>\S.*)$")
LINK_RE = re.compile(r"\b(?:Closes|Fixes|Refs)\s+#\d+\b", re.IGNORECASE)


def _load_rule_refs(repo_root: Path):
    path = repo_root / "scripts" / "check_rule_refs.py"
    spec = importlib.util.spec_from_file_location("_cv_check_rule_refs", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_commitlint(text: str) -> tuple[set[str], set[str]]:
    """Return (types, scopes) parsed from commitlint.config.cjs."""
    scopes: set[str] = set()
    for name in ("AREA_SCOPES", "COMPONENT_SCOPES", "PACKAGE_SCOPES"):
        m = re.search(rf"const {name}\s*=\s*\[(.*?)\];", text, re.S)
        if m:
            scopes |= set(re.findall(r'"([^"]+)"', m.group(1)))
    t = re.search(r'"type-enum"\s*:\s*\[\s*\d+\s*,\s*"always"\s*,\s*\[(.*?)\]', text, re.S)
    types = set(re.findall(r'"([^"]+)"', t.group(1))) if t else set()
    return types, scopes


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
    return re.compile(("^" if anchored else r"^(?:.*/)?") + out + "$")


def generated_patterns(gitattributes: str) -> list[re.Pattern[str]]:
    pats = []
    for line in gitattributes.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if "linguist-generated=true" in parts[1:] or "linguist-generated" in parts[1:]:
            pats.append(_glob_re(parts[0]))
    return pats


def count_loc(numstat: str, gen: list[re.Pattern[str]]) -> tuple[int, int]:
    """Return (counted LOC, excluded LOC). Binary files (`-`) count 0."""
    counted = excluded = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add, dele, path = parts[0], parts[1], parts[-1]
        if "=>" in path:  # rename: use the new path
            path = re.sub(r"\{.*? => (.*?)\}", r"\1", path).replace("//", "/")
            path = path.split(" => ")[-1]
        n = (int(add) if add.isdigit() else 0) + (int(dele) if dele.isdigit() else 0)
        if path.rsplit("/", 1)[-1] in LOCKFILES or any(p.match(path) for p in gen):
            excluded += n
        else:
            counted += n
    return counted, excluded


def check(
    event: dict,
    numstat: str,
    gitattributes: str,
    commitlint: str,
    declared: set[str],
    rule_id_re: re.Pattern[str],
) -> tuple[list[str], list[str]]:
    pr = event.get("pull_request") or {}
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    labels = {lab.get("name") for lab in pr.get("labels") or []}
    errors: list[str] = []
    warnings: list[str] = []

    loc, excl = count_loc(numstat, generated_patterns(gitattributes))
    info = f"{loc} changed LOC ({excl} excluded: generated/lockfiles)"
    if loc > FAIL_LOC and LABEL not in labels:
        errors.append(
            f"PR-SIZE-001 C-4.8: {info} exceeds {FAIL_LOC}; split it or have a CODEOWNER apply "
            f"`{LABEL}` with a written justification"
        )
    elif loc > FAIL_LOC:
        warnings.append(f"C-4.8: {info} > {FAIL_LOC} allowed by `{LABEL}` (applier not verifiable)")
    elif loc > WARN_LOC:
        warnings.append(f"C-4.8: {info} exceeds preferred {WARN_LOC}; add a why-not-split note")

    types, scopes = parse_commitlint(commitlint)
    m = TITLE_RE.match(title)
    if not m:
        errors.append(f"PR-TITLE-001 C-4.10: title {title!r} is not `type(scope): subject`")
    else:
        if m["type"] not in types:
            errors.append(f"PR-TITLE-002 C-4.10: type {m['type']!r} not in {sorted(types)}")
        if m["scope"] not in scopes:
            errors.append(f"PR-TITLE-003 C-4.10: scope {m['scope']!r} not an allowed scope")

    if not LINK_RE.search(body):
        errors.append("PR-BODY-001 C-4.7: body needs `Closes #N` (or `Fixes`/`Refs #N`)")

    for rid in sorted(set(rule_id_re.findall(f"{title}\n{body}")) - declared):
        errors.append(f"PR-RULE-001 C-16.4: {rid} is cited but not declared in CONSTITUTION.md")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--event", type=Path, required=True)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--numstat-file", type=Path)
    ap.add_argument("--base")
    ap.add_argument("--head")
    a = ap.parse_args(argv)
    root = a.repo_root.resolve()
    event = json.loads(a.event.read_text(encoding="utf-8"))
    if a.numstat_file:
        numstat = a.numstat_file.read_text(encoding="utf-8")
    else:
        pr = event.get("pull_request") or {}
        base = a.base or (pr.get("base") or {}).get("sha")
        head = a.head or (pr.get("head") or {}).get("sha")
        numstat = subprocess.run(
            ["git", "diff", "--numstat", f"{base}...{head}"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
    rr = _load_rule_refs(root)
    errors, warnings = check(
        event,
        numstat,
        (root / ".gitattributes").read_text(encoding="utf-8"),
        (root / "commitlint.config.cjs").read_text(encoding="utf-8"),
        rr.load_declared_ids(str(root)),
        rr.RULE_ID_RE,
    )
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
