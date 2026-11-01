"""E27-Q03 (#892) E27-C5 and the credential-memory criterion, in process: no stack, no network.

BQ-06 and BQ-14 RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109). Each test is a
narrowing written into qa/plans/e27/chaos.md (section 0 and E27-C5, E27-M1, E27-A1):

- KEK refused at start (plan TC-120), on M2's own service with a fake source: M2 degrades, key
  add, rotate and verify refuse with `KekUnavailable`, and the page rule `KekUnavailable` (read from
  `infra/prometheus/alerts/system_page.yml`) fires on the gauge M2 sets.
- KEK refused after start: the control CLI has no KEK command, so the refusal is the fake source's
  own, flipped after `start()`. Only what matches the ruling is asserted: signing goes on from the
  KEK in memory, the source unread. The ruled refusals of add, rotate and verify and the critical
  alert are not what the code does today; they are finding rows in the plan, not assertions here.
- Memory: after a signing call returns, a walk of every live object the collector reaches finds
  no object holding the marker secret (a fixture marker, made at run time; never a real key). The
  walk runs in a fresh interpreter (`_e27_memory_probe.py`), so its cost is bounded by what that
  module imports, never by what the lane ran before it. A core-dump scan stays an owner-run item
  on the dev host.

The rule check is a Python evaluation of the rule's own expression against the metric (no promtool
binary in the PR lane); the generated promtool cases in `infra/prometheus/tests/` stay the CI gate.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from prometheus_client import REGISTRY, CollectorRegistry

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.errors import KekUnavailable
from candleviewer.secrets.metrics import export_secrets_metrics
from candleviewer.secrets.service import SecretsService, mint_borrower, mint_candidate_keys
from tests.unit.credentials_m2._service_fakes import _borrow, _ctx, _Src, _store_one, _svc
from tests.unit.credentials_m2._vectors import ACCOUNT, KEK_V1, SNAPSHOT
from tests.unit.credentials_m2.test_candidate_keys import run, signing

# A bound well inside the lane's 30-minute job cap: every case here runs in process in well under
# a second, or waits on the probe, which `PROBE_TIMEOUT_S` bounds (security read 6556583904 item 2).
pytestmark = pytest.mark.timeout(90)

RULES = Path(__file__).resolve().parents[5] / "infra/prometheus/alerts/system_page.yml"
API_ROOT = Path(__file__).resolve().parents[3]  # services/api: the probe runs as a module from here
PROBE = "tests.chaos.accounts._e27_memory_probe"
PROBE_TIMEOUT_S = 60.0
GAUGE = "cv_kek_degraded_state"
#: The label the page groups by: M2's exporter adds it to every served series (secrets/metrics.py).
BY = "env"
#: The one expression shape this evaluator reads; any other shape fails the test, never passes it.
_EXPR = re.compile(r"max by \((\w+)\) \((\w+)\) == (\d+)")


@pytest.fixture(autouse=True)
def _gauge_restored() -> Iterator[None]:
    """C-13.7: the process-wide gauge goes back to what it read before the test."""
    before = m.kek_degraded_state._value.get()
    yield
    m.kek_degraded_state.set(before)


@pytest.fixture
async def started() -> AsyncIterator[list[SecretsService]]:
    """C-13.7: every service a case starts is stopped in teardown, so none outlives its case."""
    services: list[SecretsService] = []
    yield services
    for svc in services:
        await svc.stop(0)


def _kek_page() -> dict[str, Any]:
    doc = yaml.safe_load(RULES.read_text("utf-8"))
    rules = [r for g in doc["groups"] for r in g["rules"] if r.get("alert") == "KekUnavailable"]
    assert len(rules) == 1
    return dict(rules[0])


def _fires(rule: dict[str, Any], served: tuple[float | None, dict[str, str]]) -> bool:
    """`max by (label) (metric) == n` over the one series this process serves, as Prometheus
    evaluates it at `for: 0m`: an absent series, or one without the grouping label, is an empty
    group, which fires nothing."""
    value, labels = served
    shape = _EXPR.fullmatch(str(rule["expr"]))
    assert shape is not None, "the KekUnavailable expression changed shape: update this evaluator"
    assert shape.group(1) == BY, "the page groups by `env`: one page per environment"
    assert shape.group(2) == GAUGE and str(rule.get("for", "0m")) in ("0m", "0s")
    return value is not None and BY in labels and value == float(shape.group(3))


def _sample() -> float | None:
    return REGISTRY.get_sample_value(GAUGE)


def _served() -> tuple[float | None, dict[str, str]]:
    """The gauge as a scrape serves it: through M2's exporter, with its `env` constant label."""
    registry = CollectorRegistry()
    export_secrets_metrics(registry, env="demo")
    for family in registry.collect():
        for sample in family.samples:
            if sample.name == GAUGE:
                return sample.value, dict(sample.labels)
    return None, {}


async def test_kek_refused_at_start_refuses_key_operations_and_fires_the_page(
    started: list[SecretsService],
) -> None:
    svc, ctx = _svc(_Src(None, 1)), _ctx()
    await svc.start(ctx)
    started.append(svc)

    assert svc.health().status is HealthStatus.DEGRADED
    assert ctx.oms_read_only_gate.is_read_only
    with pytest.raises(KekUnavailable):  # add: key import holds no candidate
        await run(mint_candidate_keys(svc), signing(SNAPSHOT))
    with pytest.raises(KekUnavailable):  # rotate: the KEK re-wrap
        await svc.rewrap_deks(2, environment="demo", actor_user_id=ACCOUNT.hex, actor_role="owner")
    with pytest.raises(KekUnavailable):  # verify: signs as the self-check does (key_verify.py)
        await mint_borrower(svc, "exchange_adapter").sign(
            ACCOUNT, (KEY_ID_SLOT,), purpose="key_verify"
        )
    rule = _kek_page()
    assert rule["labels"]["severity"] == "page" and rule["labels"]["component"] == "secrets"
    assert _sample() == 1 and _served() == (1.0, {BY: "demo"}) and _fires(rule, _served())


async def test_kek_refused_after_start_signing_goes_on_from_memory(
    started: list[SecretsService],
) -> None:
    source = _Src(KEK_V1, 1)
    svc = _svc(source)
    await svc.start(_ctx())
    started.append(svc)
    meta = await _store_one(svc)
    loads = len(source.handed)

    source.raw = None  # the source now refuses: a load would raise `KekLoadError`

    assert await _borrow(svc, meta.key_id) == "ABCD1234"  # the key id M2 hands back, signed
    assert await _borrow(svc, meta.key_id) == "ABCD1234"
    assert len(source.handed) == loads  # signed from the KEK in memory: the source is not read


def test_the_page_rule_evaluator_fires_only_on_the_degraded_value() -> None:
    rule = _kek_page()
    served = [(v, {BY: "demo"}) for v in (1.0, 0.0, None)]
    assert [_fires(rule, s) for s in served] == [True, False, False]
    assert not _fires(rule, (1.0, {})), "a series without the `env` label is no page group"
    with pytest.raises(AssertionError, match="changed shape"):
        _fires({**rule, "expr": f"{GAUGE} > 0"}, (1.0, {BY: "demo"}))
    with pytest.raises(AssertionError, match="groups by `env`"):
        _fires({**rule, "expr": f"max by (foo) ({GAUGE}) == 1"}, (1.0, {BY: "demo"}))


def _tail(out: str | bytes | None) -> str:
    """The last 4000 characters of a child's output; a timeout hands it back as raw bytes."""
    text = out.decode(errors="replace") if isinstance(out, bytes) else (out or "")
    return text[-4000:]


def _probe(mode: str) -> list[str]:
    """The probe's verdict: the type names of objects holding its marker, from a fresh process.
    A child still alive at `PROBE_TIMEOUT_S` fails the test with what it wrote: the threads alive
    when it returned and, from its `faulthandler` timer, every thread's stack."""
    try:
        done = subprocess.run(  # noqa: S603 - this interpreter and constant arguments only
            [sys.executable, "-m", PROBE, mode],
            cwd=API_ROOT, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"the memory probe `{mode}` did not exit within {PROBE_TIMEOUT_S} s\n"
            f"stdout: {_tail(exc.stdout)}\nstderr: {_tail(exc.stderr)}",
            pytrace=False,
        )
    assert done.returncode == 0, f"the memory probe exited {done.returncode}: {_tail(done.stderr)}"
    return list(json.loads(done.stdout.splitlines()[-1]))


def test_the_walk_finds_a_marker_held_in_an_untracked_container() -> None:
    assert "dict" in _probe("control")


def test_no_live_object_holds_the_marker_secret_after_signing() -> None:
    assert _probe("signing") == []
