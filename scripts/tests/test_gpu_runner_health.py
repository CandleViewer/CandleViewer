"""Unit tests for tools/ci/gpu_runner_health.py (E03-T14). Fixture payloads; no network."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import gpu_runner_health as health

FIXTURES = Path(__file__).parent / "fixtures" / "gpu_runner"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
LABELS = '["self-hosted", "Linux", "X64", "gpu-bench"]'
QUEUE = "refs/heads/gh-readonly-queue/main/pr-1-abc"


def payload(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["runners"]


def decide(
    event: str, ref: str, var: str | None, runners: Any, token: bool = True
) -> dict[str, Any]:
    return health.decide(event, ref, var, runners, token, NOW)


@pytest.mark.parametrize(
    ("event", "ref"),
    [
        ("merge_group", QUEUE),
        ("schedule", "refs/heads/main"),
        ("workflow_dispatch", "refs/heads/main"),
    ],
)
def test_decide_online_idle_runner_on_an_eligible_event_is_gpu(event: str, ref: str) -> None:
    out = decide(event, ref, LABELS, payload("online_idle"))
    assert (out["mode"], out["code"], out["alert"]) == ("gpu", None, False)
    assert json.loads(out["runs_on"]) == ["self-hosted", "Linux", "X64", "gpu-bench"]


@pytest.mark.parametrize("event", ["pull_request", "push", "pull_request_target", ""])
def test_decide_never_routes_a_non_queue_event_to_the_gpu_even_when_it_is_online(
    event: str,
) -> None:
    out = decide(event, "refs/pull/9/merge", LABELS, payload("online_idle"))
    assert (out["mode"], out["runs_on"], out["alert"]) == ("fallback", '"ubuntu-latest"', False)
    assert "K01 P4" in out["reason"]


@pytest.mark.parametrize("ref", ["refs/heads/feat/x", "refs/heads/train/1", "refs/tags/v1", ""])
def test_decide_dispatch_off_main_takes_the_fallback(ref: str) -> None:
    assert decide("workflow_dispatch", ref, LABELS, payload("online_idle"))["mode"] == "fallback"
    assert decide("schedule", ref, LABELS, payload("online_idle"))["mode"] == "fallback"


def test_decide_a_merge_group_for_another_base_takes_the_fallback() -> None:
    ref = "refs/heads/gh-readonly-queue/dev/pr-1-abc"
    assert decide("merge_group", ref, LABELS, payload("online_idle"))["mode"] == "fallback"


@pytest.mark.parametrize("var", [None, "", "   "])
def test_decide_unset_variable_is_the_plain_no_runner_fallback_without_an_alert(
    var: str | None,
) -> None:
    out = decide("merge_group", QUEUE, var, None, token=False)
    assert (out["mode"], out["code"], out["alert"]) == ("fallback", "CI-BEN-004", False)
    assert out["reason"] == "no GPU runner registered: fallback active"


@pytest.mark.parametrize(
    ("fixture", "reason"),
    [
        ("offline", "offline"),
        ("empty", "no registered runner"),
        ("label_missing", "no registered runner"),
    ],
)
def test_decide_offline_or_missing_runner_falls_back_with_an_alert(
    fixture: str, reason: str
) -> None:
    out = decide("merge_group", QUEUE, LABELS, payload(fixture))
    assert (out["mode"], out["code"], out["alert"]) == ("fallback", "CI-BEN-003", True)
    assert reason in out["reason"]


def test_decide_all_busy_falls_back_for_this_run_without_an_alert() -> None:
    out = decide("merge_group", QUEUE, LABELS, payload("online_busy"))
    assert (out["mode"], out["code"], out["alert"]) == ("fallback", "CI-BEN-003", False)
    assert "busy" in out["reason"]


def test_decide_one_idle_runner_among_busy_ones_is_enough() -> None:
    assert decide("merge_group", QUEUE, LABELS, payload("two_one_idle"))["mode"] == "gpu"


def test_decide_missing_token_is_unknown_health_so_fallback_and_alert() -> None:
    out = decide("merge_group", QUEUE, LABELS, None, token=False)
    assert (out["mode"], out["code"], out["alert"]) == ("fallback", "CI-BEN-003", True)
    assert "health unknown" in out["reason"]
    assert "CV_RUNNER_HEALTH_TOKEN" in out["reason"]


def test_decide_unreadable_runner_list_is_unknown_health() -> None:
    out = decide("schedule", "refs/heads/main", LABELS, None)
    assert (out["mode"], out["alert"]) == ("fallback", True)
    assert "unreadable" in out["reason"]


@pytest.mark.parametrize(
    "var", ["not json", "{}", "[]", '["ok", 3]', '["a b"]', '["x;rm -rf /"]', '"gpu"']
)
def test_decide_malformed_variable_falls_back_with_an_alert(var: str) -> None:
    out = decide("merge_group", QUEUE, var, payload("online_idle"))
    assert (out["mode"], out["code"], out["alert"]) == ("fallback", "CI-BEN-003", True)


def test_decide_reports_the_time_it_was_made() -> None:
    assert decide("merge_group", QUEUE, None, None)["checked_at"] == "2026-11-02T12:00:00Z"


def test_decide_strips_control_characters_from_an_event_or_ref_it_echoes() -> None:
    out = decide("pull_request", "refs/heads/a\n::error::x", LABELS, None)
    assert "\n" not in out["reason"]


Response = io.BytesIO


def test_fetch_runners_returns_the_runner_list_and_sends_the_token_as_a_bearer() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Any, timeout: int) -> io.BytesIO:
        seen["auth"] = request.get_header("Authorization")
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return Response((FIXTURES / "online_idle.json").read_bytes())

    assert health.fetch_runners("o/r", "tok", opener) == payload("online_idle")
    assert seen["auth"] == "Bearer tok"
    assert seen["url"].startswith("https://api.github.com/repos/o/r/actions/runners")
    assert seen["timeout"] == health.TIMEOUT_S


def test_fetch_runners_http_error_is_unavailable_and_never_echoes_the_token() -> None:
    def opener(request: Any, timeout: int) -> io.BytesIO:
        raise urllib.error.HTTPError(request.full_url, 403, "tok-secret", {}, None)  # type: ignore[arg-type]

    with pytest.raises(health.HealthUnavailable) as raised:
        health.fetch_runners("o/r", "tok-secret", opener)
    assert "tok-secret" not in str(raised.value)


@pytest.mark.parametrize("body", [b"not json", b'{"runners": "x"}', b"[]"])
def test_fetch_runners_bad_payload_is_unavailable(body: bytes) -> None:
    with pytest.raises(health.HealthUnavailable):
        health.fetch_runners("o/r", "t", lambda request, timeout: Response(body))


def cli(
    tmp_path: Path, command: str, env: dict[str, str], runners: Any = None
) -> tuple[dict[str, str], str, list[str]]:
    output, summary = tmp_path / "out", tmp_path / "sum"
    lines: list[str] = []
    calls: list[tuple[str, str]] = []

    def fetch(repo: str, token: str) -> list[dict[str, Any]]:
        calls.append((repo, token))
        if runners is None:
            raise health.HealthUnavailable("down")
        return runners

    base = {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}
    assert health.run(command, base | env, fetch, NOW, lines.append) == 0
    fields = dict(x.split("=", 1) for x in output.read_text(encoding="utf-8").splitlines())
    fields["calls"] = str(len(calls))
    return fields, summary.read_text(encoding="utf-8"), lines


def test_route_with_no_variable_writes_the_fallback_and_never_calls_the_api(tmp_path: Path) -> None:
    env = {"GITHUB_EVENT_NAME": "merge_group", "GITHUB_REF": QUEUE, "CV_RUNNER_HEALTH_TOKEN": "t"}
    fields, summary, lines = cli(tmp_path, "route", env)
    assert (fields["mode"], fields["runs_on"], fields["alert"], fields["calls"]) == (
        "fallback",
        '"ubuntu-latest"',
        "false",
        "0",
    )
    assert lines == ["::notice title=engine-bench fallback::CI-BEN-004: " + health.NO_RUNNER]
    assert "mode: **fallback**" in summary


def test_route_on_a_pull_request_never_calls_the_api_even_with_a_token(tmp_path: Path) -> None:
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REF": "refs/pull/1/merge",
        "CV_GPU_BENCH_RUNNER": LABELS,
        "CV_RUNNER_HEALTH_TOKEN": "t",
    }
    fields, _, _ = cli(tmp_path, "route", env, payload("online_idle"))
    assert (fields["mode"], fields["calls"]) == ("fallback", "0")


def test_route_on_a_merge_group_with_an_idle_runner_selects_the_labels(tmp_path: Path) -> None:
    env = {
        "GITHUB_EVENT_NAME": "merge_group",
        "GITHUB_REF": QUEUE,
        "GITHUB_REPOSITORY": "o/r",
        "CV_GPU_BENCH_RUNNER": LABELS,
        "CV_RUNNER_HEALTH_TOKEN": "t",
    }
    fields, _, lines = cli(tmp_path, "route", env, payload("online_idle"))
    assert fields["mode"] == "gpu"
    assert json.loads(fields["runs_on"]) == json.loads(LABELS)
    assert fields["calls"] == "1"
    assert lines[0].startswith("::notice title=engine-bench gpu::")


def test_check_judges_as_the_schedule_and_raises_the_alert_signal_when_offline(
    tmp_path: Path,
) -> None:
    env = {"CV_GPU_BENCH_RUNNER": LABELS, "CV_RUNNER_HEALTH_TOKEN": "t", "GITHUB_REPOSITORY": "o/r"}
    fields, _, lines = cli(tmp_path, "check", env, payload("offline"))
    assert (fields["mode"], fields["code"], fields["alert"]) == ("fallback", "CI-BEN-003", "true")
    assert "\n" not in fields["reason"]
    assert lines[0].startswith("::warning title=engine-bench fallback::CI-BEN-003:")


def test_check_with_no_runner_registered_raises_no_alert(tmp_path: Path) -> None:
    fields, _, _ = cli(tmp_path, "check", {})
    assert (fields["code"], fields["alert"], fields["reason"]) == (
        "CI-BEN-004",
        "false",
        health.NO_RUNNER,
    )


def test_check_with_the_variable_set_and_the_api_down_raises_the_alert(tmp_path: Path) -> None:
    env = {"CV_GPU_BENCH_RUNNER": LABELS, "CV_RUNNER_HEALTH_TOKEN": "t"}
    fields, _, _ = cli(tmp_path, "check", env, None)
    assert (fields["alert"], fields["calls"]) == ("true", "1")


def test_check_with_the_variable_set_and_no_token_raises_the_alert(tmp_path: Path) -> None:
    fields, _, _ = cli(tmp_path, "check", {"CV_GPU_BENCH_RUNNER": LABELS})
    assert (fields["alert"], fields["calls"]) == ("true", "0")


def test_main_runs_the_subcommand_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))
    monkeypatch.delenv("CV_GPU_BENCH_RUNNER", raising=False)
    assert health.main(["route"]) == 0
    assert "CI-BEN-004" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        health.main(["bogus"])
