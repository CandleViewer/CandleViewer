"""Tests for infra/scripts/obs_security_checks.py (E04-X02)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import obs_security_checks as o

#: A label that holds one of these is a UID, or an account, order, key or session identity, or the
#: size half of AC5's symbol-plus-size, however it is spelled (user_id, order_link_id, key_id, qty).
BANNED_FRAGMENTS = (
    "uid", "user", "account", "order", "key", "secret", "signature",
    "token", "session", "password", "size", "qty", "notional",
)  # fmt: skip


def test_repo_passes_all_checks() -> None:
    assert o.main([]) == 0


def test_gitleaks_allowlist_exempting_infra_is_flagged() -> None:
    cfg = "[extend]\nuseDefault = true\npaths = [\n  '''infra/alertmanager/.*''',\n]\n"
    assert any("infra/alertmanager" in v for v in o.check_gitleaks_covers_infra(cfg))


def test_gitleaks_without_default_ruleset_is_flagged() -> None:
    assert o.check_gitleaks_covers_infra("title = 'x'\n")


def test_committed_webhook_token_is_detected(tmp_path: Path) -> None:
    am = tmp_path / "infra" / "alertmanager"
    am.mkdir(parents=True)
    (am / "a.yml").write_text(
        "url: https://hooks.slack.com/services/T0000/B0000/abcdEFGH1234\n", encoding="utf-8"
    )
    assert o.check_alertmanager_webhook_literals(tmp_path / "infra")


def test_runtime_secret_reference_is_clean(tmp_path: Path) -> None:
    am = tmp_path / "infra" / "alertmanager"
    am.mkdir(parents=True)
    (am / "a.yml").write_text("url_file: /run/secrets/alert_webhook\n", encoding="utf-8")
    assert o.check_alertmanager_webhook_literals(tmp_path / "infra") == []


def test_workflow_uploading_logs_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "w.yml").write_text(
        "steps:\n  - uses: actions/upload-artifact@v4\n    with:\n      name: x\n      path: logs/\n",
        encoding="utf-8",
    )
    assert o.check_workflows_no_log_artifacts(tmp_path)


def test_workflow_uploading_reports_is_clean(tmp_path: Path) -> None:
    (tmp_path / "w.yml").write_text(
        "steps:\n  - uses: actions/upload-artifact@v4\n    with:\n      name: x\n      path: reports/\n",
        encoding="utf-8",
    )
    assert o.check_workflows_no_log_artifacts(tmp_path) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_loose_permissions_are_flagged(tmp_path: Path) -> None:
    d = tmp_path / "logs"
    d.mkdir()
    f = d / "a.log"
    f.write_text("x", encoding="utf-8")
    os.chmod(d, 0o700)
    os.chmod(f, 0o644)
    assert o.check_modes(d)
    os.chmod(f, 0o600)
    assert o.check_modes(d) == []


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
def test_gitleaks_catches_deliberate_infra_secret(tmp_path: Path) -> None:
    """Deliberate-commit AC: a fake secret under infra/ must be detected by the repo config."""
    repo = tmp_path / "r"
    (repo / "infra" / "alertmanager").mkdir(parents=True)
    # Assembled at runtime so this source file itself holds no secret-shaped literal.
    fake = "AKIA" + "IOSFODNN7" + "EXAMPLQ"
    (repo / "infra" / "alertmanager" / "leak.yml").write_text(
        f"aws_access_key_id: {fake}\naws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    cfg = o.REPO / ".gitleaks.toml"
    res = subprocess.run(
        ["gitleaks", "detect", "--no-git", "--source", str(repo), "--config", str(cfg), "--redact"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0, "gitleaks did not flag a deliberate infra secret"


def test_loose_log_permissions_flagged_logic_is_posix_only_documented() -> None:
    # Windows has no POSIX modes: the check is a documented no-op there, never a false pass in CI.
    assert o.check_modes(Path("/definitely/not/here")) == []


def test_webhook_secret_committed_to_alertmanager_config_is_caught(tmp_path: Path) -> None:
    """AC3 (executed): a deliberate token in an Alertmanager config fails the in-repo check."""
    infra = tmp_path / "infra"
    (infra / "alertmanager").mkdir(parents=True)
    token = "T" + "0123456789" + "ABCDEFGHIJKLMNOPQRS"  # assembled: no secret-shaped literal
    (infra / "alertmanager" / "alertmanager.yml").write_text(
        f"receivers:\n  - name: page\n    slack_configs:\n      - api_url: https://hooks.slack.com/services/T0/B0/{token}\n",
        encoding="utf-8",
    )
    assert o.check_alertmanager_webhook_literals(infra)


def test_page_alert_payload_carries_no_ids_or_key_material() -> None:
    """AC5 (executed): the Page template + rules expose only allow-listed fields."""
    import json
    import re

    tmpl = (o.REPO / "infra/alertmanager/templates/cv.tmpl").read_text(encoding="utf-8")
    fields = set(re.findall(r"\.(?:Group|Common)(?:Labels|Annotations)\.(\w+)", tmpl))
    assert fields <= {"alertname", "component", "env", "severity", "summary", "runbook_url"}
    assert "Alerts.Labels" not in tmpl and ".Labels." not in tmpl.replace(".CommonLabels.", "").replace(
        ".GroupLabels.", ""
    )
    fixture = json.loads(
        (o.REPO / "infra/alertmanager/tests/data/grouped_page.json").read_text(encoding="utf-8")
    )
    blob = json.dumps(fixture).lower()
    for banned in ("order_id", "orderlinkid", "account_id", "api_key", "secret", "signature"):
        assert banned not in blob
    # #4361: infra/prometheus/alerts/ingestion.yml (E08-T06, a day after this test) names these
    # bounded market-data dimensions: `scope` is public|account, never a UID; `reason`, `stream`
    # and `class` are closed enums; a topic, symbol or endpoint class names a feed, an instrument
    # or a rate limit (docs/plan/24-internal-schemas.md). Page alerts use only `symbol`.
    market_data = {"topic", "symbol", "stream", "reason", "scope", "endpoint_class", "class"}
    allowed = {"env", "component", "instance", "job", "alertname", "severity"} | market_data
    # An annotation never interpolates a UID, or an account, order or key identity (RSK-013, AC5),
    # so the allow-list must not admit one, whatever else it grows to hold: by name, or by any
    # fragment of BANNED_FRAGMENTS.
    identity = {"uid", "account_id", "order_id", "orderlinkid"}
    key_material = {"key", "api_key", "secret", "signature"}
    banned_labels = identity | key_material

    def banned(label: str) -> bool:
        return label in banned_labels or any(part in label for part in BANNED_FRAGMENTS)

    admitted = sorted(filter(banned, allowed))
    assert not admitted, f"the allow-list admits {admitted}"
    for rule in (o.REPO / "infra/prometheus/alerts").glob("*.yml"):
        text = rule.read_text(encoding="utf-8")
        for m in re.finditer(r"\$labels\.(\w+)", text):
            label = m.group(1)
            assert not banned(label), f"{rule.name}: annotation interpolates banned ${label}"
            assert label in allowed, f"{rule.name}: annotation interpolates ${label}"
        # AC5 also bars a symbol-plus-size: a rule that prints a symbol never prints its value.
        for group in yaml.safe_load(text).get("groups") or []:
            for alert in group.get("rules") or []:
                shown = json.dumps([alert.get("labels"), alert.get("annotations")])
                assert not (re.search(r"\$labels\.symbol\b", shown) and "$value" in shown), (
                    f"{rule.name}: {alert.get('alert')} prints a symbol with its value"
                )


def test_gitleaks_allowlist_violation_does_not_echo_matched_line() -> None:
    secret_line = "paths = ['''infra/grafana/ZZSECRETVALUE123''']"
    out = o.check_gitleaks_covers_infra("useDefault = true\n" + secret_line)
    assert out
    assert all("ZZSECRETVALUE123" not in v for v in out)
