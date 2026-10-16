"""E04-T05 review fixes: quiet-hours rendering, notification template, drill URL guard (no network)."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]
INFRA = HERE.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = _load("render_config")
drill = _load("alert_drill")
TEMPLATE = (HERE / "alertmanager.yml").read_text(encoding="utf-8")


def _cfg(spec: str) -> dict[str, Any]:
    out: dict[str, Any] = yaml.safe_load(rc.render(TEMPLATE, spec))
    return out


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _muted(cfg: dict[str, Any], labels: dict[str, str], at: time) -> bool:
    """Evaluate Alertmanager semantics for our tree: first matching child route + its mute intervals."""
    route = next(
        r
        for r in cfg["route"]["routes"]
        if all(
            labels.get(k) == v
            for k, v in (
                re.fullmatch(r'(\w+) = "(.*)"', m).groups() for m in r["matchers"]
            )  # type: ignore[union-attr]  # pattern always matches our matchers
        )
    )
    names = set(route.get("mute_time_intervals", []))
    minute = at.hour * 60 + at.minute
    for ti in cfg["time_intervals"]:
        if ti["name"] in names:
            for spec in ti["time_intervals"]:
                for t in spec["times"]:
                    if _hm(t["start_time"]) <= minute < _hm(t["end_time"]):
                        return True
    return False


PAGE = {"severity": "page", "component": "oms"}
SECURITY_PAGE = {"severity": "page", "component": "audit"}
EVENT_PAGE = {"severity": "page", "component": "auth_recovery", "resolves": "window"}  # #2931
TICKET = {"severity": "ticket", "component": "auth"}


def test_render_default_equals_committed_config() -> None:
    assert rc.render(TEMPLATE, rc.DEFAULT) == TEMPLATE


@pytest.mark.parametrize("spec", ["22:00-07:00", "01:00-05:30", "23:30-00:00"])
def test_quiet_hours_mute_ticket_never_page(spec: str) -> None:
    cfg = _cfg(spec)
    inside = time(*map(int, spec.split("-")[0].split(":")))
    assert _muted(cfg, TICKET, inside)
    assert not _muted(cfg, PAGE, inside)
    assert not _muted(cfg, SECURITY_PAGE, inside)
    assert not _muted(cfg, EVENT_PAGE, inside)


def test_quiet_hours_window_bounds_honour_env() -> None:
    cfg = _cfg("01:00-05:30")
    assert not _muted(cfg, TICKET, time(0, 59))
    assert _muted(cfg, TICKET, time(5, 29))
    assert not _muted(cfg, TICKET, time(5, 30))
    assert not _muted(cfg, TICKET, time(22, 30))


def test_default_window_wraps_midnight() -> None:
    cfg = _cfg(rc.DEFAULT)
    assert _muted(cfg, TICKET, time(23, 0)) and _muted(cfg, TICKET, time(3, 0))
    assert not _muted(cfg, TICKET, time(12, 0))


@pytest.mark.parametrize(
    "bad", ["", "22:00", "25:00-07:00", "22:00-07:60", "07:00-07:00", "x-y"]
)
def test_malformed_quiet_hours_rejected(bad: str) -> None:
    with pytest.raises(rc.QuietHoursError):
        rc.parse(bad)


def test_render_cli_fails_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_ALERT_QUIET_HOURS", "nope")
    assert rc.main([str(HERE / "alertmanager.yml"), str(tmp_path / "o.yml")]) == 1
    assert not (tmp_path / "o.yml").exists()


def test_compose_renders_via_init_container_not_sed() -> None:
    dc = yaml.safe_load(
        (INFRA / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    init, am = dc["services"]["alertmanager-config"], dc["services"]["alertmanager"]
    assert "render_config.py" in " ".join(init["command"])
    assert "CV_ALERT_QUIET_HOURS" in init["environment"]
    assert (
        am["depends_on"]["alertmanager-config"]["condition"]
        == "service_completed_successfully"
    )
    assert "sed" not in str(am) and "entrypoint" not in am
    assert re.search(r"@sha256:[0-9a-f]{64}$", init["image"])


TMPL = (HERE / "templates" / "cv.tmpl").read_text(encoding="utf-8")
FIXTURE = json.loads(
    (HERE / "tests" / "data" / "grouped_page.json").read_text(encoding="utf-8")
)


def test_page_template_has_required_fields_and_occurrence_count() -> None:
    body = TMPL[TMPL.index('{{ define "cv.body" }}') :]
    # Every interpolated field is piped through reReplaceAll redaction (E04-X02 AC5).
    for field in (
        "Alert: {{ .GroupLabels.alertname | reReplaceAll",
        "Component: {{ .GroupLabels.component | reReplaceAll",
        "Env: {{ .GroupLabels.env | reReplaceAll",
        "Runbook: {{ .CommonAnnotations.runbook_url | reReplaceAll",
        "Occurrences: {{ len .Alerts }}",
    ):
        assert field in body
    title = TMPL[
        TMPL.index('{{ define "cv.title" }}') : TMPL.index('{{ define "cv.body" }}')
    ]
    assert (
        "PAGE" in title and "TICKET" in title
    )  # severity visible in the notification itself


def test_render_fixture_is_a_grouped_page_with_three_occurrences() -> None:
    # CI renders cv.tmpl against this fixture with amtool and greps "Occurrences: 3".
    assert len(FIXTURE["alerts"]) == 3
    assert FIXTURE["commonLabels"]["severity"] == "page"
    assert set(FIXTURE["groupLabels"]) == {"alertname", "component", "env"}
    assert FIXTURE["commonAnnotations"]["runbook_url"].startswith(
        "docs/plan/07-release-and-prr.md#"
    )


def test_ci_asserts_rendered_notification_fields() -> None:
    ci = (INFRA.parent / ".github" / "workflows" / "_job-py.yml").read_text(
        encoding="utf-8"
    )
    assert "template render" in ci and "grouped_page.json" in ci
    for want in (
        "Occurrences: 3",
        "Component: oms",
        "Env: dev",
        "Runbook: ",
        "Alert: OmsUnknownOrders",
    ):
        assert want in ci


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9091",
        "http://localhost:9091",
        "https://localhost",
        "http://[::1]:9091",
        "http://172.28.0.5:9091",
        "http://10.1.2.3",
        "http://192.168.1.10:9091",
        "http://100.101.102.103:9091",
    ],
)
def test_drill_accepts_private_hosts(url: str) -> None:
    assert drill.is_private_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost.attacker.tld",
        "http://127.0.0.1.attacker.tld:9091",
        "http://172.28.evil.com",
        "http://user@127.0.0.1:9091",
        "http://127.0.0.1@evil.com",
        "ftp://127.0.0.1",
        "file:///etc/passwd",
        "http://8.8.8.8",
        "http://100.128.0.1",
        "http://127.0.0.1:notaport",
        "http://",
    ],
)
def test_drill_rejects_bypass_urls(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert not drill.is_private_url(url)
    monkeypatch.setenv("CV_ALERT_DRILL_PUSH_URL", url)
    assert drill.main(["fire"]) == 2
