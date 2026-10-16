"""#2264: the closed reason set of `auth_csrf_refused_total`, and the alert rules that read it.

A reason series created only at its first event gives `increase()` nothing to subtract (the
pinned Prometheus ingests no created timestamp), so the first event after every restart never
alerts: every reason is bound at import. The CSRF alert expressions are tied here to the code's
own list of audit-bookkeeping reasons, so adding one without deciding how it is alerted fails
this test instead of silently inflating (or hiding) an alert.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from candleviewer.api.csrf import CsrfRefusal
from candleviewer.auth.metrics import CSRF_AUDIT_REASONS, CSRF_REFUSAL_REASONS
from candleviewer.observability.metrics_catalogue import CATALOGUE

_API_ROOT = Path(__file__).resolve().parents[3]
_RULES_FILE = _API_ROOT.parents[1] / "infra" / "prometheus" / "alerts" / "auth_csrf.yml"
#: `reason<op>"<value>"` inside a PromQL selector; `op` is one of `=`, `!=`, `=~`, `!~`.
_MATCHER = re.compile(r'reason\s*(=~|!~|!=|=)\s*"([^"]*)"')
#: Bookkeeping that is deliberate flood control, not a fault: over a per-session or per-IP
#: budget the guard skips the audit write on purpose (C-12.8), so nothing alerts on it.
_NOT_ALERTED = frozenset({"audit_throttled"})
_FRESH_PROBE = """
import json
from prometheus_client import REGISTRY
from candleviewer.auth import metrics

reasons = (*metrics.CSRF_REFUSAL_REASONS, *metrics.CSRF_AUDIT_REASONS)
samples = {}
for r in reasons:
    samples[r] = REGISTRY.get_sample_value("auth_csrf_refused_total", {"reason": r})
print(json.dumps(samples))
"""


def _rules() -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(_RULES_FILE.read_text(encoding="utf-8"))
    return {r["alert"]: r for g in doc["groups"] for r in g["rules"] if "alert" in r}


def _reason_matcher(alert: str) -> tuple[str, frozenset[str]]:
    """The single `reason` matcher of `alert`'s expression: (operator, alternatives)."""
    found = _MATCHER.findall(str(_rules()[alert]["expr"]))
    assert len(found) == 1, (alert, found)
    return found[0][0], frozenset(found[0][1].split("|"))


def test_refusal_enum_is_the_refusal_half_of_the_reason_set_and_fits_the_catalogue() -> None:
    assert {r.value for r in CsrfRefusal} == set(CSRF_REFUSAL_REASONS)
    assert not set(CSRF_REFUSAL_REASONS) & set(CSRF_AUDIT_REASONS)
    spec = next(s for s in CATALOGUE if s.name == "auth_csrf_refused_total")
    assert len(CSRF_REFUSAL_REASONS) + len(CSRF_AUDIT_REASONS) <= spec.max_series


def test_a_fresh_process_has_every_reason_series_at_zero() -> None:
    """What Prometheus's first scrape sees. (In this process another test may already have
    created a series, so only a fresh interpreter proves they exist from the start.)"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and a literal probe
        [sys.executable, "-c", _FRESH_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {r: 0.0 for r in (*CSRF_REFUSAL_REASONS, *CSRF_AUDIT_REASONS)}


def test_csrf_refusals_high_excludes_exactly_the_audit_bookkeeping_reasons() -> None:
    """Each refusal counts under why it was refused and, if its audit record was not written
    normally, once more under a bookkeeping reason: the refusal alert must exclude every one
    of those (with `!~`, not `=~`) or it would count such a refusal twice."""
    assert _reason_matcher("CsrfRefusalsHigh") == ("!~", frozenset(CSRF_AUDIT_REASONS))


def test_every_bookkeeping_reason_is_alerted_or_named_as_deliberate_flood_control() -> None:
    unavailable = _reason_matcher("CsrfRefusalAuditUnavailable")
    degraded = _reason_matcher("CsrfRefusalAuditDegraded")
    assert unavailable == ("=", frozenset({"audit_unavailable"}))
    assert degraded == ("=~", frozenset({"audit_slow", "audit_saturated"}))
    assert unavailable[1] | degraded[1] | _NOT_ALERTED == set(CSRF_AUDIT_REASONS)
