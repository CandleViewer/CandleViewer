#!/usr/bin/env python3
"""E09-X03: fail the ZAP job if the scan was not authenticated end to end.

Evidence checked (all must hold):
  * every requestor job of the plan ran and finished: by default the two `/v1/auth/me` jobs
    (before + after the scan); a plan with more requestors passes their count (`--requestors`),
    so another requestor cannot stand in for a `/me` job that never ran;
  * no requestor error/warning: a wrong status is logged as `Job requestor warning` and
    `response code N does not match` (older ZAP), or as `Difference in response code values for
    message ... Expected : N Received : M` (ZAP 2.17, which repeats it under `Automation plan
    warnings:`, so it is reported once). ZAP's own exit code also turns on a plan warning; this
    names the loss of the session;
  * ZAP did not report automation-plan failures;
  * the JSON report exists, parses and is a ZAP report (has `site`).

Usage: check_liveness.py [--requestors N] <zap-run.log> <zap.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUESTORS = 2  # the /me pair: before and after the scan
_STARTED = re.compile(r"Job requestor started", re.I)
_FINISHED = re.compile(r"Job requestor finished", re.I)
_REQ_FAIL = re.compile(
    r"Job requestor (?:error|warning)|response code \d+ (?:does not|didn.t) match"
    r"|Difference in response code values[^\n]*",
    re.I,
)
_PLAN_FAIL = re.compile(r"Automation plan (failures|failed)", re.I)


def check(log_text: str, report_text: str | None, requestors: int = REQUESTORS) -> list[str]:
    errors: list[str] = []
    started = len(_STARTED.findall(log_text))
    finished = len(_FINISHED.findall(log_text))
    if started < requestors or finished < requestors:
        errors.append(
            f"requestors (the /v1/auth/me liveness checks among them) ran {started}/{requestors},"
            f" finished {finished}"
        )
    failures = dict.fromkeys(match.group(0).strip() for match in _REQ_FAIL.finditer(log_text))
    errors += [f"requestor failure: {failure}" for failure in failures]  # once per message
    if _PLAN_FAIL.search(log_text):
        errors.append("ZAP reported automation plan failures")
    if report_text is None:
        errors.append("zap-report/zap.json missing")
    else:
        try:
            report = json.loads(report_text)
        except json.JSONDecodeError as exc:
            errors.append(f"zap.json unparseable: {exc}")
        else:
            if not isinstance(report, dict) or "site" not in report:
                errors.append("zap.json is not a ZAP traditional-json report")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fail a ZAP run that lost its session.")
    parser.add_argument("log", type=Path, help="the ZAP run's console log")
    parser.add_argument("report", type=Path, help="its JSON report")
    parser.add_argument(
        "--requestors",
        type=int,
        default=REQUESTORS,
        help="the plan's requestor jobs, each of which must run and finish (default: the /me pair)",
    )
    args = parser.parse_args(argv[1:])
    log_path, report_path = args.log, args.report
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    errors = check(log_text, report, args.requestors)
    for e in errors:
        print(f"::error title=zap-auth lost authentication::{e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
