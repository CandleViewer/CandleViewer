#!/usr/bin/env python3
"""E09-X03: prove every auth Semgrep rule on a positive and a negative fixture,
and police in-file suppressions.

Fixture contract (same as tools/ci/check_semgrep_rule_tests.py):
    `# ruleid: <id>` / `// ruleid: <id>`  -> rule MUST fire on that line
    `# ok: <id>`     / `// ok: <id>`      -> rule MUST NOT fire on that line
A rule lacking either a positive or a negative annotation fails the job.

Suppressions (`# nosem`, `# nosec`, `# noqa: S...`) inside the auth packages
must carry `reason=`, `owner=` and an unexpired `review=YYYY-MM-DD`.

Usage: python tools/ci/check_auth_semgrep.py [--root DIR] [--skip-semgrep]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tools.ci.suppressions import field_problems

ANNOT_RE = re.compile(r"(?:#|//)\s*(ruleid|ok):\s*([\w-]+)\s*$")
SUPPRESS_RE = re.compile(r"(#\s*(?:nosem|nosec)\b.*|#\s*noqa:\s*S\d+.*)$")
AUTH_PKGS = ("auth", "accounts", "secrets", "api")


def load_rule_ids(rules_dir: Path) -> dict[str, dict[str, Any]]:
    rules: dict[str, dict[str, Any]] = {}
    for f in sorted(rules_dir.glob("*.yml")):
        for r in yaml.safe_load(f.read_text(encoding="utf-8"))["rules"]:
            rules[r["id"]] = {"file": f, "sr": (r.get("metadata") or {}).get("sr", "?")}
    return rules


def parse_fixtures(
    fx_dir: Path,
) -> tuple[dict[str, set[tuple[Path, int]]], dict[str, set[tuple[Path, int]]]]:
    pos: dict[str, set[tuple[Path, int]]] = {}
    neg: dict[str, set[tuple[Path, int]]] = {}
    for fx in sorted(p for p in fx_dir.rglob("*") if p.is_file()):  # nested: fixtures/api/csrf.py
        for n, line in enumerate(fx.read_text(encoding="utf-8").splitlines(), start=1):
            m = ANNOT_RE.search(line)
            if m:
                (pos if m.group(1) == "ruleid" else neg).setdefault(m.group(2), set()).add((fx, n))
    return pos, neg


def run_semgrep(rules_dir: Path, fx_dir: Path) -> dict[str, set[tuple[Path, int]]]:
    proc = subprocess.run(
        [
            "semgrep",
            "scan",
            "--config",
            str(rules_dir),
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            str(fx_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"semgrep failed ({proc.returncode}): {proc.stderr}")
    hits: dict[str, set[tuple[Path, int]]] = {}
    for r in json.loads(proc.stdout or "{}").get("results", []):
        rid = r["check_id"].split(".")[-1]
        hits.setdefault(rid, set()).add((Path(r["path"]).resolve(), r["start"]["line"]))
    return hits


def check_rules(rules_dir: Path, fx_dir: Path, skip_semgrep: bool = False) -> list[str]:
    rules = load_rule_ids(rules_dir)
    pos, neg = parse_fixtures(fx_dir)
    errors: list[str] = []
    hits = {} if skip_semgrep else run_semgrep(rules_dir, fx_dir)
    for rid, meta in rules.items():
        if not pos.get(rid):
            errors.append(f"{rid} ({meta['sr']}): no positive fixture")
        if not neg.get(rid):
            errors.append(f"{rid} ({meta['sr']}): no negative fixture")
        if skip_semgrep:
            continue
        fired = hits.get(rid, set())
        for fx, n in sorted(pos.get(rid, ())):
            if (fx.resolve(), n) not in fired:
                errors.append(f"{rid} ({meta['sr']}): did not fire on {fx.name}:{n}")
        for fx, n in sorted(neg.get(rid, ())):
            if (fx.resolve(), n) in fired:
                errors.append(f"{rid} ({meta['sr']}): false positive on {fx.name}:{n}")
    for rid in set(pos) | set(neg):
        if rid not in rules:
            errors.append(f"fixture references unknown rule {rid}")
    return errors


def check_suppressions(root: Path, today: date | None = None) -> list[str]:
    """Grammar and review-date cap are shared with CI-SEC-006 (tools/ci/suppressions.py)."""
    today = today or datetime.now(UTC).date()
    errors: list[str] = []
    for pkg in AUTH_PKGS:
        base = root / "services" / "api" / "candleviewer" / pkg
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.py")):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
                m = SUPPRESS_RE.search(line)
                if not m:
                    continue
                loc = f"{f.relative_to(root).as_posix()}:{n}"
                errors.extend(f"{loc}: {p}" for p in field_problems(m.group(1), today))
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--skip-semgrep", action="store_true")
    a = ap.parse_args(argv)
    base = a.root / "security" / "semgrep" / "auth"
    errors = check_rules(base, base / "fixtures", a.skip_semgrep) + check_suppressions(a.root)
    for e in errors:
        print(f"security-auth: {e}", file=sys.stderr)
    if not errors:
        print("security-auth: all auth rules proven; suppressions clean")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
