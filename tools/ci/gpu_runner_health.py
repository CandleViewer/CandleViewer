#!/usr/bin/env python3
"""GPU bench runner routing and health (E03-T14, CI-BEN-003, CI-BEN-004).

``route`` (the bench job's first step) picks the runner for ``engine-bench``; ``check`` (the hourly
``gpu-runner-health.yml``) reports whether the runner is fit and whether to raise an alert.

Policy (docs/plan/spikes/E03-K01.md section 5, P4): the GPU runner is selected ONLY for
``merge_group``, ``schedule`` and ``workflow_dispatch`` on ``main``. A ``pull_request`` (a fork
included) and every other event or ref take the hosted fallback (headless Chromium, SwiftShader),
which is the ACTIVE path until the owner registers a runner. Nothing here pretends a GPU exists.

The runner label is the repository variable ``CV_GPU_BENCH_RUNNER``, a JSON array of labels.
Unset: fallback, CI-BEN-004, no alert (an unprovisioned runner is not an incident). Set but the
runner is offline, has no match, or its health cannot be read (no token, API error): fallback,
CI-BEN-003, alert. Set and all matching runners busy: fallback for this run, CI-BEN-003, no alert (a
bench job legitimately keeps the runner busy; a stateless check cannot tell for how long).

The only network call is :func:`fetch_runners`; :func:`decide` is pure. Token:
``CV_RUNNER_HEALTH_TOKEN`` (read-only Administration, lists the repository's runners). It is never
printed. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

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
        raise ValueError("CV_GPU_BENCH_RUNNER holds a label that is not a plain label name")
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
) -> dict[str, Any]:
    """Pick ``gpu`` or ``fallback``. ``runners`` is the API's runner list, None when unreadable."""

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
        return fallback(None, f"event {where} never uses the GPU runner (K01 P4): hosted fallback")
    if not token_present or runners is None:
        why = "no CV_RUNNER_HEALTH_TOKEN" if not token_present else "runner list unreadable"
        return fallback("CI-BEN-003", f"GPU runner health unknown ({why}): fallback active", True)
    wanted = set(labels)
    matching = [r for r in runners if wanted <= {x.get("name") for x in r.get("labels", [])}]
    if not matching:
        return fallback(
            "CI-BEN-003", "GPU runner unavailable: no registered runner has the labels", True
        )
    online = [r for r in matching if r.get("status") == "online"]
    if not online:
        return fallback("CI-BEN-003", "GPU runner unavailable: offline", True)
    if all(r.get("busy") for r in online):
        return fallback("CI-BEN-003", "GPU runner busy: fallback for this run")
    return _result("gpu", json.dumps(labels), None, "GPU runner online and idle", False, now)


def fetch_runners(
    repo: str,
    token: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
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
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Never echo the exception text: a URLError can carry the request. Name the class only.
        raise HealthUnavailable(type(exc).__name__) from None
    runners = payload.get("runners") if isinstance(payload, dict) else None
    if not isinstance(runners, list):
        raise HealthUnavailable("unexpected payload")
    return runners


def _emit(path: str | None, lines: list[str]) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def _render(outcome: dict[str, Any], event: str, ref: str) -> str:
    code = outcome["code"] or "none"
    return (
        "## engine-bench runner\n\n"
        f"- mode: **{outcome['mode']}**\n- code: {code}\n- why: {outcome['reason']}\n"
        f"- event: {_plain(event) or 'unknown'}, ref: {_plain(ref) or 'unknown'}\n"
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
    if command == "check":  # the schedule's view: the runner is judged as the queue would see it
        event, ref = "schedule", MAIN_REF
    token = env.get("CV_RUNNER_HEALTH_TOKEN", "")
    runner_var = env.get("CV_GPU_BENCH_RUNNER")
    runners: list[dict[str, Any]] | None = None
    if token and runner_var and runner_var.strip() and gpu_eligible(event, ref):
        try:
            runners = fetch(env.get("GITHUB_REPOSITORY", ""), token)
        except HealthUnavailable:
            runners = None
    outcome = decide(event, ref, runner_var, runners, bool(token), now or datetime.now(UTC))
    summary = _render(outcome, event, ref)
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
    }
    _emit(env.get("GITHUB_OUTPUT"), [f"{k}={v}" for k, v in fields.items()])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("route", "check"))
    args = parser.parse_args(argv)
    return run(args.command, os.environ)


if __name__ == "__main__":
    sys.exit(main())
