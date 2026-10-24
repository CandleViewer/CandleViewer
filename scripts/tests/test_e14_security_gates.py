"""E14-X03 (#549): the drawings persistence rules. Each names its DR and SR ids, is scoped to the
drawings files and has a section in docs/plan/security/ci-gates-e14.md. On the production tree they
are quiet, and without `nosemgrep` fire on exactly the four reviewed exceptions, so a fifth unscoped
statement must be annotated and listed here. The scans skip when `semgrep` is absent (as
test_e12_security_gates.py); the fixtures are proven by tools/ci/check_semgrep_rule_tests.py."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "plan" / "security" / "ci-gates-e14.md"
RULES = (
    "cv-drawings-query-missing-owner-filter",
    "cv-drawings-owner-from-body",
    "cv-drawings-unbounded-geometry",
    "cv-drawings-batch-unvalidated-ids",
    "cv-drawings-pixel-geometry",
)
needs_semgrep = pytest.mark.skipif(not shutil.which("semgrep"), reason="semgrep not installed")


@pytest.mark.parametrize("rule", RULES)
def test_rule_names_its_threat_rows_doc_section_and_scope(rule: str) -> None:
    (loaded,) = yaml.safe_load((ROOT / ".semgrep" / f"{rule}.yml").read_text("utf-8"))["rules"]
    meta = loaded["metadata"]
    assert loaded["id"] == meta["rule-id"] == rule
    assert loaded["severity"] == "ERROR"
    assert meta["dr"] and all(str(row).startswith("DR") for row in meta["dr"])
    assert str(meta["sr"]).startswith("SR-") and meta["references"]
    assert f"ci-gates-e14.md#{rule}" in loaded["message"]
    assert f"## {rule}\n" in DOC.read_text("utf-8")
    assert all(p.startswith("services/api/candleviewer/") for p in loaded["paths"]["include"])


def _scan(*extra: str) -> list[dict[str, object]]:
    configs = [arg for r in RULES for arg in ("--config", str(ROOT / ".semgrep" / f"{r}.yml"))]
    # A generous --timeout: on a loaded host a slow parse of a big file must not read as a failure.
    proc = subprocess.run(
        ["semgrep", "scan", "--metrics=off", "--quiet", "--json", "--timeout", "120", *extra,
         *configs, str(ROOT / "services" / "api" / "candleviewer")],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )  # fmt: skip
    assert proc.returncode in (0, 1), proc.stderr
    data = json.loads(proc.stdout)
    assert not data["errors"], data["errors"]
    return list(data["results"])


@needs_semgrep
def test_the_reviewed_exceptions_are_exactly_the_four_unscoped_statements() -> None:
    fired = sorted(
        (Path(str(r["path"])).name, str(r["check_id"]).rsplit(".", 1)[-1])
        for r in _scan("--disable-nosem")
    )
    rule = "cv-drawings-query-missing-owner-filter"
    assert fired == [("drawings_sqlalchemy.py", rule)] * 3 + [("workspaces_sqlalchemy.py", rule)]
