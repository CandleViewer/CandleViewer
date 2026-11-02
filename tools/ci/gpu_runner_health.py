#!/usr/bin/env python3
"""GPU bench runner routing and health (E03-T14, CI-BEN-003, CI-BEN-004).

``route`` (the bench job's first step) picks the runner for ``engine-bench``; ``check`` (the hourly
``gpu-runner-health.yml``, the only job holding the token) reports whether the runner is fit and
whether it was busy; ``streak`` (a later job with no secret) counts consecutive busy checks.

``route`` holds no secret and makes no API call: merge-group and pull-request lanes receive no
repository secret (ADR-0013 rule 6, pinned by test_pr_yml_merge_group.py), so it applies the event
policy and the variable only. Health is the hourly ``check``'s job; an unfit runner is raised as an
issue and the owner re-routes by unsetting the variable (docs/ci-runbook.md, CI-BEN-003).

Policy (docs/plan/spikes/E03-K01.md section 5, P4): the GPU runner is selected ONLY for
``merge_group``, ``schedule`` and ``workflow_dispatch`` on ``main``. A ``pull_request`` (a fork
included) and every other event or ref take the hosted fallback (headless Chromium, SwiftShader),
which is the ACTIVE path until the owner registers a runner. Nothing here pretends a GPU exists.

The runner label is the repository variable ``CV_GPU_BENCH_RUNNER``, a JSON array of labels.
Unset: the hosted fallback, CI-BEN-004, no alert (an unprovisioned runner is not an incident).
The fallback is taken only when the variable is unset or malformed (a malformed one also alerts,
CI-BEN-003) or the event policy says so. Set and well formed: ``route`` selects the
runner and trusts the variable, so a busy, offline or missing runner QUEUES the bench job (nothing
re-routes it; the owner unsets the variable). The hourly ``check`` judges health: offline, no match,
unreadable (API error) or no token configured is reported as CI-BEN-003 and alerts. A busy runner is
normal (a bench job keeps it busy), so one busy check does not alert; ``next_state`` counts
consecutive busy checks in a tiny state file the workflow carries between runs (``actions/cache``,
restored only by the secret-free ``streak`` job, never by ``check``) and alerts at ``BUSY_ALERT_STREAK`` in a row (CI-BEN-003: jobs are
queueing behind a stuck or overloaded runner).

The only network call is :func:`fetch_runners`; :func:`decide` is pure. Token:
``CV_RUNNER_HEALTH_TOKEN`` (read-only Administration, lists the repository's runners). It is never
printed. Stdlib only.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

BUSY_ALERT_STREAK = 3
STATE_KEY = "busy_streak"
STATE_MAX_BYTES = 1024
STATE_STREAK_CAP = 1000
NO_TOKEN = "token not configured: health unknown (no CV_RUNNER_HEALTH_TOKEN)"
FALLBACK_RUNS_ON = '"ubuntu-latest"'
NO_RUNNER = "no GPU runner registered: fallback active"
GPU_EVENTS = frozenset({"merge_group", "schedule", "workflow_dispatch"})
MAIN_REF = "refs/heads/main"
QUEUE_REF_PREFIX = "refs/heads/gh-readonly-queue/main/"
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
API = "https://api.github.com"
TIMEOUT_S = 15


class HealthUnavailable(Exception):
    """The runner list could not be read (no access, HTTP error, bad payload)."""


def parse_labels(runner_var: str | None) -> list[str] | None:
    """The labels of ``CV_GPU_BENCH_RUNNER``; None when unset or blank; ValueError when malformed."""
    if runner_var is None or not runner_var.strip():
        return None
    try:
        labels = json.loads(runner_var)
    except ValueError as exc:
        raise ValueError("CV_GPU_BENCH_RUNNER is not valid JSON") from exc
    if not isinstance(labels, list) or not labels:
        raise ValueError("CV_GPU_BENCH_RUNNER is not a non-empty JSON array of labels")
    if not all(isinstance(x, str) and LABEL_RE.match(x) for x in labels):
        raise ValueError(
            "CV_GPU_BENCH_RUNNER holds a label that is not a plain label name"
        )
    return labels


def _result(
    mode: str, runs_on: str, code: str | None, reason: str, alert: bool, now: datetime
) -> dict[str, Any]:
    return {
        "mode": mode,
        "runs_on": runs_on,
        "code": code,
        "reason": reason,
        "alert": alert,
        "checked_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _plain(text: str) -> str:
    """Printable ASCII only: an event or ref reaches a log line and GITHUB_OUTPUT."""
    return re.sub(r"[^\x20-\x7e]", "?", text)[:120]


def gpu_eligible(event: str, ref: str) -> bool:
    """K01 policy P4: only these events, only on main (or a merge queue entry for main)."""
    if event == "merge_group":
        return ref.startswith(QUEUE_REF_PREFIX)
    return event in GPU_EVENTS and ref == MAIN_REF


def decide(
    event: str,
    ref: str,
    runner_var: str | None,
    runners: Sequence[Mapping[str, Any]] | None,
    token_present: bool,
    now: datetime,
    assess_health: bool = True,
) -> dict[str, Any]:
    """Pick ``gpu`` or ``fallback``. ``runners`` is the API's runner list, None when unreadable.

    ``assess_health`` False (the lane's ``route``, which has no token) trusts the variable.
    """

    def fallback(code: str | None, reason: str, alert: bool = False) -> dict[str, Any]:
        return _result("fallback", FALLBACK_RUNS_ON, code, reason, alert, now)

    try:
        labels = parse_labels(runner_var)
    except ValueError as exc:
        return fallback("CI-BEN-003", f"GPU runner unavailable: {exc}", alert=True)
    if labels is None:
        return fallback("CI-BEN-004", NO_RUNNER)
    if not gpu_eligible(event, ref):
        # Policy, not a fault: no alert, no code. A pull_request never reaches the runner.
        where = f"{_plain(event) or 'unknown'} on {_plain(ref) or 'unknown ref'}"
        return fallback(
            None, f"event {where} never uses the GPU runner (K01 P4): hosted fallback"
        )
    if not assess_health:
        return _result(
            "gpu",
            json.dumps(labels),
            None,
            "GPU runner selected (health: hourly check)",
            False,
            now,
        )
    if runners is not None and not _well_formed(runners):
        runners = None
    if not token_present or runners is None:
        reason = (
            NO_TOKEN if not token_present else "runner list unreadable: health unknown"
        )
        return fallback("CI-BEN-003", reason, True)
    wanted = set(labels)
    matching = [
        r for r in runners if wanted <= {x.get("name") for x in r.get("labels", [])}
    ]
    if not matching:
        return fallback(
            "CI-BEN-003",
            "GPU runner unavailable: no registered runner has the labels",
            True,
        )
    online = [r for r in matching if r.get("status") == "online"]
    if not online:
        return fallback("CI-BEN-003", "GPU runner unavailable: offline", True)
    if all(r.get("busy") for r in online):
        busy = _result(
            "gpu",
            json.dumps(labels),
            "CI-BEN-003",
            "GPU runner busy: a bench job queues until it is free (no fallback)",
            False,
            now,
        )
        return busy | {"busy": True}
    return _result(
        "gpu", json.dumps(labels), None, "GPU runner online and idle", False, now
    )


def next_state(prev: Any, busy: bool) -> tuple[dict[str, int], bool]:
    """The busy streak after one more hourly check, and whether it has reached the alert level.

    ``prev`` is whatever the state file held (None, corrupt or hostile content counts as zero). A
    check that is not busy resets the streak."""
    streak = 0
    if isinstance(prev, dict):
        value = prev.get(STATE_KEY)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= STATE_STREAK_CAP
        ):
            streak = value
    streak = min(streak + 1, STATE_STREAK_CAP) if busy else 0
    return {STATE_KEY: streak}, streak >= BUSY_ALERT_STREAK


def load_state(path: str) -> Any:
    """The state file's JSON, or None when it is missing, too large, unreadable or not JSON."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(STATE_MAX_BYTES + 1)
        if len(raw) > STATE_MAX_BYTES:
            return None
        return json.loads(raw)
    except (OSError, ValueError):
        return None


def _well_formed(runners: Any) -> bool:
    """A runner list of dicts whose ``labels`` (when present) is a list of dicts."""
    if not isinstance(runners, list):
        return False
    for runner in runners:
        if not isinstance(runner, dict):
            return False
        labels = runner.get("labels", [])
        if not isinstance(labels, list) or not all(isinstance(x, dict) for x in labels):
            return False
    return True


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """The token must never follow a redirect to another host: a 3xx is a failure."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        raise urllib.error.HTTPError(
            req.full_url, code, "redirect refused", headers, fp
        )


def _open_no_redirect(request: urllib.request.Request, timeout: int) -> Any:
    return urllib.request.build_opener(_RefuseRedirect).open(request, timeout=timeout)


def fetch_runners(
    repo: str,
    token: str,
    opener: Callable[..., Any] = _open_no_redirect,
) -> list[dict[str, Any]]:
    """The repository's self-hosted runners (the one network call; isolated for tests)."""
    request = urllib.request.Request(
        f"{API}/repos/{repo}/actions/runners?per_page=100",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=TIMEOUT_S) as response:
            payload = json.load(response)
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        OSError,
        ValueError,
    ) as exc:
        # Never echo the exception text: a URLError can carry the request. Name the class only.
        raise HealthUnavailable(type(exc).__name__) from None
    runners = payload.get("runners") if isinstance(payload, dict) else None
    if not _well_formed(runners):
        raise HealthUnavailable("unexpected payload")
    return runners


def _emit(path: str | None, lines: list[str]) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def _write_state(path: str, state: Mapping[str, int]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except OSError:
        pass  # the streak restarts next hour; a state write must never fail the check


def _render(outcome: dict[str, Any], event: str, ref: str, note: str = "") -> str:
    code = outcome["code"] or "none"
    return (
        "## engine-bench runner\n\n"
        f"- mode: **{outcome['mode']}**\n- code: {code}\n- why: {outcome['reason']}\n"
        f"- event: {_plain(event) or 'unknown'}, ref: {_plain(ref) or 'unknown'}\n{note}"
    )


def run(
    command: str,
    env: Mapping[str, str],
    fetch: Callable[[str, str], list[dict[str, Any]]] = fetch_runners,
    now: datetime | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """CLI body: ``route`` for the bench job, ``check`` for the hourly workflow. Returns 0."""
    event = env.get("GITHUB_EVENT_NAME", "")
    ref = env.get("GITHUB_REF", "")
    if (
        command == "check"
    ):  # the schedule's view: the runner is judged as the queue would see it
        event, ref = "schedule", MAIN_REF
    # `route` never reads the token: a lane holds no secret (ADR-0013 rule 6).
    token = env.get("CV_RUNNER_HEALTH_TOKEN", "") if command == "check" else ""
    runner_var = env.get("CV_GPU_BENCH_RUNNER")
    runners: list[dict[str, Any]] | None = None
    if command == "check" and token and runner_var and runner_var.strip():
        try:
            runners = fetch(env.get("GITHUB_REPOSITORY", ""), token)
        except HealthUnavailable:
            runners = None
    outcome = decide(
        event,
        ref,
        runner_var,
        runners,
        bool(token),
        now or datetime.now(UTC),
        command == "check",
    )
    note = ""
    if command == "check" and not token and not (runner_var and runner_var.strip()):
        note = "- token: not configured (CV_RUNNER_HEALTH_TOKEN)\n"
    summary = _render(outcome, event, ref, note)
    level = "warning" if outcome["alert"] else "notice"
    title = f"engine-bench {outcome['mode']}"
    code = f"{outcome['code']}: " if outcome["code"] else ""
    out(f"::{level} title={title}::{code}{outcome['reason']}")
    _emit(env.get("GITHUB_STEP_SUMMARY"), [summary])
    fields = {
        "mode": outcome["mode"],
        "runs_on": outcome["runs_on"],
        "code": outcome["code"] or "",
        "reason": outcome["reason"],
        "alert": "true" if outcome["alert"] else "false",
        "busy": "true" if outcome.get("busy") else "false",
    }
    _emit(env.get("GITHUB_OUTPUT"), [f"{k}={v}" for k, v in fields.items()])
    return 0


def run_streak(
    env: Mapping[str, str],
    out: Callable[[str], None] = print,
) -> int:
    """The secret-free ``streak`` step: ``CV_GPU_BUSY`` ("true" or anything else) is the check's
    observation, ``CV_GPU_BUSY_STATE_FILE`` the cached state. Never reads a token. Returns 0.
    """
    state_path = env.get("CV_GPU_BUSY_STATE_FILE", "")
    busy = env.get("CV_GPU_BUSY", "") == "true"
    prev = load_state(state_path) if state_path else None
    state, alert = next_state(prev, busy)
    if state_path:
        _write_state(state_path, state)
    count = state[STATE_KEY]
    reason = (
        f"GPU runner busy on {count} consecutive hourly checks: jobs queue"
        if alert
        else ""
    )
    level = "warning" if alert else "notice"
    out(f"::{level} title=engine-bench busy streak::consecutive busy checks: {count}")
    _emit(
        env.get("GITHUB_STEP_SUMMARY"),
        [f"## engine-bench busy streak\n\n- consecutive busy checks: {count}"],
    )
    fields = {
        "alert": "true" if alert else "false",
        "code": "CI-BEN-003" if alert else "",
        "reason": reason,
        "streak": str(count),
    }
    _emit(env.get("GITHUB_OUTPUT"), [f"{k}={v}" for k, v in fields.items()])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("route", "check", "streak"))
    args = parser.parse_args(argv)
    if args.command == "streak":
        return run_streak(os.environ)
    return run(args.command, os.environ)


if __name__ == "__main__":
    sys.exit(main())
