"""Tests for tools/ci/check_auth_semgrep.py and the E09-X03 gitleaks token rules."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import check_auth_semgrep as chk

AUTH = ROOT / "security" / "semgrep" / "auth"
EXPECTED_RULES = {
    "no-raw-account-id",
    "no-adhoc-authz",
    "no-target-user-on-self-service",
    "stepup-required",
    "no-secret-logging",
    "no-jwt-in-browser-storage",
    "cookie-flags",
    "argon2-params",
    "audit-write-required",
}


def test_all_nine_rules_present() -> None:
    assert EXPECTED_RULES <= set(chk.load_rule_ids(AUTH))


def test_every_rule_has_positive_and_negative_fixture() -> None:
    assert chk.check_rules(AUTH, AUTH / "fixtures", skip_semgrep=True) == []


def test_rule_without_fixture_fails(tmp_path: Path) -> None:
    (tmp_path / "r.yml").write_text(
        "rules:\n  - id: lonely\n    languages: [python]\n    severity: ERROR\n"
        "    message: m\n    pattern: foo()\n    metadata: {sr: SR-1}\n",
        encoding="utf-8",
    )
    (tmp_path / "fx").mkdir()
    errs = chk.check_rules(tmp_path, tmp_path / "fx", skip_semgrep=True)
    assert any("no positive fixture" in e for e in errs)
    assert any("no negative fixture" in e for e in errs)


def test_nested_fixture_files_are_parsed(tmp_path: Path) -> None:
    # The decoy fixtures/api/csrf.py pins the anchored writer exclusion only if it is read.
    (tmp_path / "top.py").write_text("x = 1  # ruleid: r1\n", encoding="utf-8")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "csrf.py").write_text(
        "y = 2  # ruleid: r2\nz = 3  # ok: r2\n", encoding="utf-8"
    )
    pos, neg = chk.parse_fixtures(tmp_path)
    assert set(pos) == {"r1", "r2"}
    assert set(neg) == {"r2"}


@pytest.mark.skipif(
    not __import__("shutil").which("semgrep"), reason="semgrep not installed"
)
def test_rules_fire_on_positive_and_not_on_negative() -> None:
    assert chk.check_rules(AUTH, AUTH / "fixtures") == []


def _pkg(tmp_path: Path, line: str) -> Path:
    d = tmp_path / "services" / "api" / "candleviewer" / "auth"
    d.mkdir(parents=True)
    (d / "x.py").write_text(line + "\n", encoding="utf-8")
    return tmp_path


def test_blanket_suppression_fails(tmp_path: Path) -> None:
    errs = chk.check_suppressions(_pkg(tmp_path, "x = 1  # nosec"))
    assert errs and "missing reason, owner, review" in errs[0]


def test_expired_suppression_fails(tmp_path: Path) -> None:
    line = "x = 1  # nosec reason=fp owner=@sec review=2020-01-01"
    errs = chk.check_suppressions(_pkg(tmp_path, line), today=date(2026, 1, 1))
    assert errs and "expired" in errs[0]


def test_justified_suppression_passes(tmp_path: Path) -> None:
    line = "x = 1  # nosec reason=fp owner=@sec review=2026-03-01"
    assert chk.check_suppressions(_pkg(tmp_path, line), today=date(2026, 1, 1)) == []


def test_repo_suppressions_clean() -> None:
    assert chk.check_suppressions(ROOT) == []


def _gitleaks_rules() -> dict[str, re.Pattern[str]]:
    cfg = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    return {
        r["id"]: re.compile(r["regex"])
        for r in cfg["rules"]
        if r["id"].startswith("cv-")
    }


def test_gitleaks_detects_our_token_shapes() -> None:
    rules = _gitleaks_rules()
    body = "A" * 43  # built at runtime: no token-shaped literal is committed
    assert rules["cv-session-token"].search("cvs_" + body)
    assert rules["cv-refresh-token"].search("cvr_" + body)
    assert rules["cv-invite-token"].search("cvi_" + body)
    assert rules["cv-recovery-code"].search("recovery_code = 'ABCDE-" + "FGHIJ'")
    first, second = "ABCDE-" + "FGHIJ", "KLMNO-" + "PQRST"
    m = rules["cv-recovery-code"].search(f"recovery_codes = ['{first}', '{second}']")
    assert m and first in m.group(0) and second in m.group(0)  # every code, not just the first
    assert rules["cv-totp-secret"].search("totp_secret = '" + "JBSWY3DPEHPK3PXP" + "'")


def test_gitleaks_ignores_benign_text() -> None:
    rules = _gitleaks_rules()
    assert not rules["cv-session-token"].search("cvs_short")
    assert not rules["cv-totp-secret"].search("totp_secret = settings.secret")


# --- ZAP liveness gate (security/zap/check_liveness.py) --------------------
sys.path.insert(0, str(ROOT / "security" / "zap"))
import check_liveness as live  # noqa: E402 -- path set just above

_OK_LOG = "Job requestor started\nJob requestor finished\n" * 2
_REPORT = '{"site": []}'


def test_liveness_both_requestors_ok_passes() -> None:
    assert live.check(_OK_LOG, _REPORT) == []


def test_liveness_requestor_401_fails() -> None:
    log = _OK_LOG + "Job requestor error: response code 401 does not match 200\n"
    assert any("requestor failure" in e for e in live.check(log, _REPORT))


def test_liveness_missing_post_scan_check_fails() -> None:
    log = "Job requestor started\nJob requestor finished\n"
    assert live.check(log, _REPORT)


def test_liveness_report_missing_or_not_zap_fails() -> None:
    assert live.check(_OK_LOG, None)
    assert live.check(_OK_LOG, "{}")
