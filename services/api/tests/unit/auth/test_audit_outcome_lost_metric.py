"""#2914 item 5: `auth_audit_outcome_lost_total`, outcome audit records lost after the action was
taken (04-security-program.md section 8.3 rule 2).

The action label is a closed set of registered audit actions; every series is bound at import, so
the first loss after a restart is a visible increase (as for `auth_csrf_refused_total`); and the
series is served on the scraped registry, since one on the default registry is never scraped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from prometheus_client import generate_latest

from candleviewer.app import create_app
from candleviewer.audit.actions import validate_action
from candleviewer.auth import metrics
from candleviewer.auth.metrics import (
    AUDIT_OUTCOME_ACTIONS,
    AUTH_EXPORTED_NAMES,
    normalise_outcome_action,
)
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

NAME = "auth_audit_outcome_lost_total"
_SPEC = next(s for s in CATALOGUE if s.name == NAME)
_API_ROOT = Path(__file__).resolve().parents[3]
_VALUES = (*AUDIT_OUTCOME_ACTIONS, "other")
_FRESH_PROBE = """
import json
from prometheus_client import REGISTRY
from candleviewer.auth import metrics

print(json.dumps({v: REGISTRY.get_sample_value("auth_audit_outcome_lost_total", {"action": v})
                  for v in (*metrics.AUDIT_OUTCOME_ACTIONS, "other")}))
"""


def test_catalogue_declares_the_series_live_exported_and_bounded() -> None:
    assert (_SPEC.kind, _SPEC.status, _SPEC.exported) == ("counter", "live", True)
    assert (_SPEC.labels, _SPEC.owner_epic) == (("action",), "E09")
    assert NAME in AUTH_EXPORTED_NAMES  # served on the scraped registry, not only the default one
    assert len(_VALUES) <= _SPEC.max_series


def test_the_label_is_a_closed_set_of_registered_audit_actions() -> None:
    for action in AUDIT_OUTCOME_ACTIONS:
        validate_action(action)  # a typo would be a series nothing ever increments
        assert normalise_outcome_action(action) == action
    for hostile in ("", "auth.logout ", "AUTH.SESSION_REVOKED", "x" * 500, "../etc/passwd"):
        assert normalise_outcome_action(hostile) == "other", hostile


def test_the_backstop_labels_a_member_of_the_closed_set() -> None:
    """The backstop port labels the counter directly (not through `normalise_outcome_action`), so
    its action must be in the closed set, or a lost backstop record would count on no series."""
    from candleviewer.api.session_backstop_audit import ACTION

    assert ACTION in AUDIT_OUTCOME_ACTIONS
    assert normalise_outcome_action(ACTION) == ACTION


def test_a_fresh_process_has_every_action_series_at_zero() -> None:
    """What Prometheus's first scrape sees. (Another test in this process may already have
    created a series, so only a fresh interpreter proves they exist from the start.)"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter, a literal probe (#2914)
        [sys.executable, "-c", _FRESH_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {v: 0.0 for v in _VALUES}


def test_create_app_serves_the_series_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    text = generate_latest(app.state.app_context.metrics).decode()
    samples = [ln for ln in text.splitlines() if ln.startswith(f"{NAME}{{")]
    assert len(samples) == len(_VALUES) and all('env="demo"' in ln for ln in samples)


def test_a_lost_password_change_outcome_counts_under_its_own_label() -> None:
    """#5270: `PUT /auth/password`'s outcome rows count per action, not under `other`."""
    assert normalise_outcome_action("auth.password_change") == "auth.password_change"
    child = metrics.auth_audit_outcome_lost_total.labels(action="auth.password_change")
    other = metrics.auth_audit_outcome_lost_total.labels(action="other")
    before, before_other = child._value.get(), other._value.get()
    child.inc()
    assert (child._value.get(), other._value.get()) == (before + 1, before_other)
