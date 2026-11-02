"""Unit tests for tools/ci/gpu_runner_health.py (E03-T14). Fixture payloads; no network."""

from __future__ import annotations

import http.client
import io
import json
import sys
import urllib.error
import urllib.request
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
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))[
        "runners"
    ]


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
def test_decide_online_idle_runner_on_an_eligible_event_is_gpu(
    event: str, ref: str
) -> None:
    out = decide(event, ref, LABELS, payload("online_idle"))
    assert (out["mode"], out["code"], out["alert"]) == ("gpu", None, False)
    assert json.loads(out["runs_on"]) == ["self-hosted", "Linux", "X64", "gpu-bench"]


@pytest.mark.parametrize("event", ["pull_request", "push", "pull_request_target", ""])
def test_decide_never_routes_a_non_queue_event_to_the_gpu_even_when_it_is_online(
    event: str,
) -> None:
    out = decide(event, "refs/pull/9/merge", LABELS, payload("online_idle"))
    assert (out["mode"], out["runs_on"], out["alert"]) == (
        "fallback",
        '"ubuntu-latest"',
        False,
    )
    assert "K01 P4" in out["reason"]


@pytest.mark.parametrize(
    "ref", ["refs/heads/feat/x", "refs/heads/train/1", "refs/tags/v1", ""]
)
def test_decide_dispatch_off_main_takes_the_fallback(ref: str) -> None:
    assert (
        decide("workflow_dispatch", ref, LABELS, payload("online_idle"))["mode"]
        == "fallback"
    )
    assert decide("schedule", ref, LABELS, payload("online_idle"))["mode"] == "fallback"


def test_decide_a_merge_group_for_another_base_takes_the_fallback() -> None:
    ref = "refs/heads/gh-readonly-queue/dev/pr-1-abc"
    assert (
        decide("merge_group", ref, LABELS, payload("online_idle"))["mode"] == "fallback"
    )


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


def test_decide_all_busy_queues_the_job_so_it_is_not_a_fallback_and_not_an_alert() -> (
    None
):
    out = decide("merge_group", QUEUE, LABELS, payload("online_busy"))
    assert (out["mode"], out["code"], out["alert"], out["busy"]) == (
        "gpu",
        "CI-BEN-003",
        False,
        True,
    )
    assert "queues" in out["reason"] and "fallback" in out["reason"]


def test_decide_one_idle_runner_among_busy_ones_is_enough() -> None:
    assert (
        decide("merge_group", QUEUE, LABELS, payload("two_one_idle"))["mode"] == "gpu"
    )


def test_decide_missing_token_is_unknown_health_so_fallback_and_alert() -> None:
    out = decide("merge_group", QUEUE, LABELS, None, token=False)
    assert (out["mode"], out["code"], out["alert"]) == ("fallback", "CI-BEN-003", True)
    assert out["reason"] == health.NO_TOKEN
    assert (
        out["reason"]
        == "token not configured: health unknown (no CV_RUNNER_HEALTH_TOKEN)"
    )


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
    assert (
        decide("merge_group", QUEUE, None, None)["checked_at"] == "2026-11-02T12:00:00Z"
    )


def test_decide_strips_control_characters_from_an_event_or_ref_it_echoes() -> None:
    out = decide("pull_request", "refs/heads/a\n::error::x", LABELS, None)
    assert "\n" not in out["reason"]


Response = io.BytesIO


def test_fetch_runners_returns_the_runner_list_and_sends_the_token_as_a_bearer() -> (
    None
):
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


@pytest.mark.parametrize(
    "error",
    [
        http.client.IncompleteRead(b"x"),
        http.client.RemoteDisconnected("gone"),
        ConnectionResetError("reset"),
        TimeoutError("slow"),
    ],
)
def test_fetch_runners_transport_failures_are_unavailable(error: Exception) -> None:
    def opener(request: Any, timeout: int) -> io.BytesIO:
        raise error

    with pytest.raises(health.HealthUnavailable):
        health.fetch_runners("o/r", "t", opener)


@pytest.mark.parametrize(
    "body",
    [
        b'{"runners": ["x"]}',
        b'{"runners": [{"labels": "x"}]}',
        b'{"runners": [{"labels": ["x"]}]}',
        b'{"runners": {"a": 1}}',
        b"\xff\xfe",
    ],
)
def test_fetch_runners_malformed_entries_are_unavailable(body: bytes) -> None:
    with pytest.raises(health.HealthUnavailable):
        health.fetch_runners("o/r", "t", lambda request, timeout: Response(body))


@pytest.mark.parametrize(
    "runners", ["x", {"a": 1}, ["x"], [{"labels": "x"}], [{"labels": [1]}]]
)
def test_decide_malformed_runner_list_falls_back_with_an_alert(runners: Any) -> None:
    out = decide("schedule", "refs/heads/main", LABELS, runners)
    assert out["mode"] == "fallback"
    assert out["alert"] is True
    assert out["code"] == "CI-BEN-003"


def test_default_opener_refuses_redirects_so_the_token_never_changes_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Redirecting(urllib.request.BaseHandler):
        handler_order = 100

        def https_open(self, req: Any) -> Any:
            return self.parent.error(
                "http",
                req,
                io.BytesIO(b""),
                302,
                "Found",
                {"Location": "https://evil.example/x"},
            )

    real = urllib.request.build_opener
    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *handlers: real(Redirecting(), *handlers)
    )
    request = urllib.request.Request(
        "https://api.github.com/x", headers={"Authorization": "Bearer t"}
    )
    with pytest.raises(urllib.error.HTTPError) as raised:
        health._open_no_redirect(request, 1)
    assert raised.value.code == 302
    with pytest.raises(health.HealthUnavailable):
        health.fetch_runners("o/r", "t", health._open_no_redirect)


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
    fields = dict(
        x.split("=", 1) for x in output.read_text(encoding="utf-8").splitlines()
    )
    fields["calls"] = str(len(calls))
    return fields, summary.read_text(encoding="utf-8"), lines


def test_route_with_no_variable_writes_the_fallback_and_never_calls_the_api(
    tmp_path: Path,
) -> None:
    env = {
        "GITHUB_EVENT_NAME": "merge_group",
        "GITHUB_REF": QUEUE,
        "CV_RUNNER_HEALTH_TOKEN": "t",
    }
    fields, summary, lines = cli(tmp_path, "route", env)
    assert (fields["mode"], fields["runs_on"], fields["alert"], fields["calls"]) == (
        "fallback",
        '"ubuntu-latest"',
        "false",
        "0",
    )
    assert lines == [
        "::notice title=engine-bench fallback::CI-BEN-004: " + health.NO_RUNNER
    ]
    assert "mode: **fallback**" in summary


def test_route_on_a_pull_request_never_calls_the_api_even_with_a_token(
    tmp_path: Path,
) -> None:
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REF": "refs/pull/1/merge",
        "CV_GPU_BENCH_RUNNER": LABELS,
        "CV_RUNNER_HEALTH_TOKEN": "t",
    }
    fields, _, _ = cli(tmp_path, "route", env, payload("online_idle"))
    assert (fields["mode"], fields["calls"]) == ("fallback", "0")


def test_route_selects_the_labels_on_a_merge_group_without_a_token_or_an_api_call(
    tmp_path: Path,
) -> None:
    # A lane holds no secret (ADR-0013 rule 6): route trusts the variable; the hourly check judges.
    env = {
        "GITHUB_EVENT_NAME": "merge_group",
        "GITHUB_REF": QUEUE,
        "GITHUB_REPOSITORY": "o/r",
        "CV_GPU_BENCH_RUNNER": LABELS,
        "CV_RUNNER_HEALTH_TOKEN": "t",
    }
    fields, _, lines = cli(tmp_path, "route", env, payload("offline"))
    assert fields["mode"] == "gpu"
    assert json.loads(fields["runs_on"]) == json.loads(LABELS)
    assert fields["calls"] == "0"
    assert lines[0].startswith("::notice title=engine-bench gpu::")


def test_route_with_a_malformed_variable_falls_back_with_a_warning(
    tmp_path: Path,
) -> None:
    env = {
        "GITHUB_EVENT_NAME": "merge_group",
        "GITHUB_REF": QUEUE,
        "CV_GPU_BENCH_RUNNER": "nope",
    }
    fields, _, lines = cli(tmp_path, "route", env)
    assert (fields["mode"], fields["code"], fields["alert"]) == (
        "fallback",
        "CI-BEN-003",
        "true",
    )
    assert lines[0].startswith("::warning ")


def test_decide_without_health_assessment_trusts_the_variable_but_keeps_the_event_policy() -> (
    None
):
    out = health.decide(
        "merge_group", QUEUE, LABELS, None, False, NOW, assess_health=False
    )
    assert out["mode"] == "gpu"
    out = health.decide(
        "pull_request", "refs/pull/1/merge", LABELS, None, False, NOW, False
    )
    assert out["mode"] == "fallback"


def test_check_judges_as_the_schedule_and_raises_the_alert_signal_when_offline(
    tmp_path: Path,
) -> None:
    env = {
        "CV_GPU_BENCH_RUNNER": LABELS,
        "CV_RUNNER_HEALTH_TOKEN": "t",
        "GITHUB_REPOSITORY": "o/r",
    }
    fields, _, lines = cli(tmp_path, "check", env, payload("offline"))
    assert (fields["mode"], fields["code"], fields["alert"]) == (
        "fallback",
        "CI-BEN-003",
        "true",
    )
    assert "\n" not in fields["reason"]
    assert lines[0].startswith("::warning title=engine-bench fallback::CI-BEN-003:")


def test_check_with_no_runner_registered_raises_no_alert(tmp_path: Path) -> None:
    fields, _, _ = cli(tmp_path, "check", {})
    assert (fields["code"], fields["alert"], fields["reason"]) == (
        "CI-BEN-004",
        "false",
        health.NO_RUNNER,
    )


def test_check_with_the_variable_set_and_the_api_down_raises_the_alert(
    tmp_path: Path,
) -> None:
    env = {"CV_GPU_BENCH_RUNNER": LABELS, "CV_RUNNER_HEALTH_TOKEN": "t"}
    fields, _, _ = cli(tmp_path, "check", env, None)
    assert (fields["alert"], fields["calls"]) == ("true", "1")


def test_check_with_the_variable_set_and_no_token_raises_the_alert(
    tmp_path: Path,
) -> None:
    fields, _, _ = cli(tmp_path, "check", {"CV_GPU_BENCH_RUNNER": LABELS})
    assert (fields["alert"], fields["calls"]) == ("true", "0")
    assert fields["reason"] == health.NO_TOKEN


def test_check_with_no_variable_and_no_token_says_so_plainly_without_an_alert(
    tmp_path: Path,
) -> None:
    fields, summary, _ = cli(tmp_path, "check", {})
    assert fields["alert"] == "false"
    assert "token: not configured (CV_RUNNER_HEALTH_TOKEN)" in summary
    (tmp_path / "again").mkdir()
    _, with_token, _ = cli(tmp_path / "again", "check", {"CV_RUNNER_HEALTH_TOKEN": "t"})
    assert "token: not configured" not in with_token


@pytest.mark.parametrize(
    ("prev", "busy", "streak", "alert"),
    [
        (None, True, 1, False),
        ({"busy_streak": 1}, True, 2, False),
        ({"busy_streak": 2}, True, 3, True),
        ({"busy_streak": 3}, True, 4, True),
        ({"busy_streak": 2}, False, 0, False),
        ({"busy_streak": 5}, False, 0, False),
        (None, False, 0, False),
        ("garbage", True, 1, False),
        ([1, 2], True, 1, False),
        ({"busy_streak": "9"}, True, 1, False),
        ({"busy_streak": True}, True, 1, False),
        ({"busy_streak": -4}, True, 1, False),
        ({"busy_streak": 10**9}, True, 1, False),
        ({"busy_streak": 1000}, True, 1000, True),
    ],
)
def test_next_state_counts_consecutive_busy_checks_and_alerts_at_three(
    prev: Any, busy: bool, streak: int, alert: bool
) -> None:
    assert health.next_state(prev, busy) == ({"busy_streak": streak}, alert)


@pytest.mark.parametrize(
    "content", [None, b"", b"{not json", b'"x"', b"\xff\xfe", b"9" * 5000]
)
def test_load_state_treats_a_missing_or_corrupt_file_as_no_state(
    tmp_path: Path, content: bytes | None
) -> None:
    path = tmp_path / "state.json"
    if content is not None:
        path.write_bytes(content)
    prev = health.load_state(str(path))
    assert health.next_state(prev, True) == ({"busy_streak": 1}, False)


def streak_step(tmp_path: Path, busy: str) -> dict[str, str]:
    env = {"CV_GPU_BUSY": busy, "CV_GPU_BUSY_STATE_FILE": str(tmp_path / "state.json")}
    output = tmp_path / "streak-out"
    output.unlink(missing_ok=True)
    lines: list[str] = []
    assert health.run_streak(env | {"GITHUB_OUTPUT": str(output)}, lines.append) == 0
    assert lines and lines[0].startswith("::")
    return dict(
        x.split("=", 1) for x in output.read_text(encoding="utf-8").splitlines()
    )


def test_check_reports_the_busy_observation_and_never_touches_the_state(
    tmp_path: Path,
) -> None:
    env = {
        "CV_GPU_BENCH_RUNNER": LABELS,
        "CV_RUNNER_HEALTH_TOKEN": "t",
        "CV_GPU_BUSY_STATE_FILE": str(tmp_path / "state.json"),
    }
    assert cli(tmp_path, "check", env, payload("online_busy"))[0]["busy"] == "true"
    assert not (tmp_path / "state.json").exists()
    (tmp_path / "again").mkdir()
    assert (
        cli(tmp_path / "again", "check", env, payload("online_idle"))[0]["busy"]
        == "false"
    )
    (tmp_path / "off").mkdir()
    assert cli(tmp_path / "off", "check", env, payload("offline"))[0]["busy"] == "false"


def test_streak_alerts_on_the_third_consecutive_busy_hour_and_a_free_hour_resets(
    tmp_path: Path,
) -> None:
    assert streak_step(tmp_path, "true")["alert"] == "false"
    assert streak_step(tmp_path, "true")["alert"] == "false"
    fields = streak_step(tmp_path, "true")
    assert (fields["alert"], fields["code"], fields["streak"]) == (
        "true",
        "CI-BEN-003",
        "3",
    )
    assert "3 consecutive hourly checks" in fields["reason"]
    assert streak_step(tmp_path, "false")["alert"] == "false"
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {
        "busy_streak": 0
    }
    assert streak_step(tmp_path, "true")["alert"] == "false"


def test_streak_treats_anything_but_true_as_not_busy(tmp_path: Path) -> None:
    streak_step(tmp_path, "true")
    assert streak_step(tmp_path, "")["streak"] == "0"
    assert streak_step(tmp_path, "TRUE")["streak"] == "0"


def test_streak_with_a_corrupt_state_file_starts_from_zero_and_rewrites_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "state.json").write_text("{{{", encoding="utf-8")
    assert streak_step(tmp_path, "true")["alert"] == "false"
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {
        "busy_streak": 1
    }


def test_streak_survives_an_unwritable_state_path_and_a_missing_one() -> None:
    lines: list[str] = []
    env = {
        "CV_GPU_BUSY": "true",
        "CV_GPU_BUSY_STATE_FILE": "/nonexistent-dir/state.json",
    }
    assert health.run_streak(env, lines.append) == 0
    assert health.run_streak({"CV_GPU_BUSY": "true"}, lines.append) == 0
    assert len(lines) == 2


def test_streak_never_reads_a_token_or_calls_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(health, "fetch_runners", boom)
    env = {"CV_GPU_BUSY": "true", "CV_RUNNER_HEALTH_TOKEN": "t"}
    assert health.run_streak(env, lambda _: None) == 0


def test_the_check_job_holds_the_token_and_no_cache_and_the_streak_job_holds_no_secret() -> (
    None
):
    import yaml

    path = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "gpu-runner-health.yml"
    )
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    check = jobs["check"]
    assert not [s for s in check["steps"] if "actions/cache" in s.get("uses", "")]
    assert "restore-keys" not in yaml.safe_dump(check)
    assert "secrets.CV_RUNNER_HEALTH_TOKEN" in yaml.safe_dump(check)
    streak = jobs["streak"]
    text = yaml.safe_dump(streak)
    assert "secrets" not in text and "TOKEN" not in text.upper()
    assert streak["needs"] == "check" and streak["permissions"] == {"contents": "read"}
    assert any("actions/cache/restore" in s.get("uses", "") for s in streak["steps"])
    assert any("actions/cache/save" in s.get("uses", "") for s in streak["steps"])
    raw = path.read_text(encoding="utf-8")
    for step in (
        streak["steps"] + check["steps"]
    ):  # outputs reach scripts through env only
        assert "needs." not in step.get("run", "") and "steps." not in step.get(
            "run", ""
        )
    assert "secrets." not in raw.split("  streak:")[1].split("  alert:")[0]


def test_the_alert_job_fires_on_check_alert_streak_alert_or_a_failed_check() -> None:
    import yaml

    path = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "gpu-runner-health.yml"
    )
    alert = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["alert"]
    assert alert["needs"] == ["check", "streak"]
    condition = alert["if"]
    for part in (
        "always()",
        "needs.check.result == 'failure'",
        "needs.check.outputs.alert == 'true'",
        "needs.streak.outputs.alert == 'true'",
    ):
        assert part in condition
    assert alert["permissions"] == {"issues": "write"}


def test_route_never_reads_or_writes_the_busy_state(tmp_path: Path) -> None:
    env = {
        "GITHUB_EVENT_NAME": "merge_group",
        "GITHUB_REF": QUEUE,
        "CV_GPU_BENCH_RUNNER": LABELS,
        "CV_GPU_BUSY_STATE_FILE": str(tmp_path / "state.json"),
    }
    cli(tmp_path, "route", env)
    assert not (tmp_path / "state.json").exists()


def test_main_runs_the_subcommand_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))
    monkeypatch.delenv("CV_GPU_BENCH_RUNNER", raising=False)
    assert health.main(["route"]) == 0
    assert "CI-BEN-004" in capsys.readouterr().out
    monkeypatch.setenv("CV_GPU_BUSY", "true")
    monkeypatch.delenv("CV_GPU_BUSY_STATE_FILE", raising=False)
    assert health.main(["streak"]) == 0
    assert "busy streak" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        health.main(["bogus"])
