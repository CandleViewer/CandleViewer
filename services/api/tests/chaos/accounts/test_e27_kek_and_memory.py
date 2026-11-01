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
  no object holding the marker secret (a fixture marker, made at run time; never a real key). A
  core-dump scan stays an owner-run item on the dev host.

The rule check is a Python evaluation of the rule's own expression against the metric (no promtool
binary in the PR lane); the generated promtool cases in `infra/prometheus/tests/` stay the CI gate.
"""

from __future__ import annotations

import gc
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from prometheus_client import REGISTRY

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.errors import KekUnavailable
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import SecretsService, mint_borrower, mint_candidate_keys
from tests.unit.credentials_m2._service_fakes import _borrow, _ctx, _Src, _store_one, _svc
from tests.unit.credentials_m2._vectors import ACCOUNT, KEK_V1, SNAPSHOT
from tests.unit.credentials_m2.test_candidate_keys import run, signing

RULES = Path(__file__).resolve().parents[5] / "infra/prometheus/alerts/system_page.yml"
GAUGE = "cv_kek_degraded_state"
#: The one expression shape this evaluator reads; any other shape fails the test, never passes it.
_EXPR = re.compile(r"max by \((\w+)\) \((\w+)\) == (\d+)")
#: Fixture-only marker: a fixed prefix and random hex made per run, so no copy sits in the source.
MARK_PREFIX = "e27q03-marker-"


@pytest.fixture(autouse=True)
def _gauge_restored() -> Iterator[None]:
    """C-13.7: the process-wide gauge goes back to what it read before the test."""
    before = m.kek_degraded_state._value.get()
    yield
    m.kek_degraded_state.set(before)


def _kek_page() -> dict[str, Any]:
    doc = yaml.safe_load(RULES.read_text("utf-8"))
    rules = [r for g in doc["groups"] for r in g["rules"] if r.get("alert") == "KekUnavailable"]
    assert len(rules) == 1
    return dict(rules[0])


def _fires(rule: dict[str, Any], value: float | None) -> bool:
    """`max by (label) (metric) == n` over the one series this process exports, as Prometheus
    evaluates it at `for: 0m`: an absent series is an empty vector, which fires nothing."""
    shape = _EXPR.fullmatch(str(rule["expr"]))
    assert shape is not None, "the KekUnavailable expression changed shape: update this evaluator"
    assert shape.group(2) == GAUGE and str(rule.get("for", "0m")) in ("0m", "0s")
    return value is not None and value == float(shape.group(3))


def _sample() -> float | None:
    return REGISTRY.get_sample_value(GAUGE)


async def test_kek_refused_at_start_refuses_key_operations_and_fires_the_page() -> None:
    svc, ctx = _svc(_Src(None, 1)), _ctx()
    await svc.start(ctx)

    assert svc.health().status is HealthStatus.DEGRADED
    assert ctx.oms_read_only_gate.is_read_only
    with pytest.raises(KekUnavailable):  # add: key import holds no candidate
        await run(mint_candidate_keys(svc), signing(SNAPSHOT))
    with pytest.raises(KekUnavailable):  # rotate: the KEK re-wrap
        await svc.rewrap_deks(2, environment="demo", actor_user_id=ACCOUNT.hex, actor_role="owner")
    with pytest.raises(KekUnavailable):  # verify: a self-check signs, and cannot
        await _borrow(svc, ACCOUNT)
    rule = _kek_page()
    assert rule["labels"]["severity"] == "page" and rule["labels"]["component"] == "secrets"
    assert _sample() == 1 and _fires(rule, _sample())


async def test_kek_refused_after_start_signing_goes_on_from_memory() -> None:
    source = _Src(KEK_V1, 1)
    svc = _svc(source)
    await svc.start(_ctx())
    meta = await _store_one(svc)
    loads = len(source.handed)

    source.raw = None  # the source now refuses: a load would raise `KekLoadError`

    assert await _borrow(svc, meta.key_id) == "ABCD1234"  # the key id M2 hands back, signed
    assert await _borrow(svc, meta.key_id) == "ABCD1234"
    assert len(source.handed) == loads  # signed from the KEK in memory: the source is not read


def test_the_page_rule_evaluator_fires_only_on_the_degraded_value() -> None:
    rule = _kek_page()
    assert [_fires(rule, v) for v in (1.0, 0.0, None)] == [True, False, False]
    with pytest.raises(AssertionError, match="changed shape"):
        _fires({**rule, "expr": f"{GAUGE} > 0"}, 1.0)


def _marked() -> tuple[str, Secret[str]]:
    """The needle and the secret, as two distinct objects of equal text: the walk skips the needle
    by identity only, so a reference to the secret's own object is never hidden."""
    text = MARK_PREFIX + os.urandom(12).hex()
    return "".join(list(text)), Secret(text)


def _holders(needle: str) -> list[str]:
    """Type names of live objects holding `needle`'s text in a str, bytes or bytearray. Starts at
    every object the collector tracks and descends into the containers it does not track (a dict
    or tuple of strings only), so a string is found wherever a reachable container holds it."""
    raw = needle.encode()
    found: list[str] = []
    seen: set[int] = set()
    stack: list[Any] = gc.get_objects()
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        for ref in gc.get_referents(obj):
            if ref is needle or ref is raw:
                continue
            if isinstance(ref, str):
                hit = needle in ref
            elif isinstance(ref, bytes | bytearray):
                hit = raw in ref
            else:
                hit = False
                if not gc.is_tracked(ref) and isinstance(ref, dict | tuple | list | frozenset):
                    stack.append(ref)
            if hit:
                found.append(type(obj).__name__)
    return found


def test_the_walk_finds_a_marker_held_in_an_untracked_container() -> None:
    needle, kept = _marked()
    holder = {"held": "".join(list(needle))}  # a dict of strings only: not tracked by gc
    box = [holder]  # a tracked list, as any live structure that keeps such a dict is
    assert not gc.is_tracked(holder) and gc.is_tracked(box)
    assert "dict" in _holders(needle)
    del box, holder, kept


async def test_no_live_object_holds_the_marker_secret_after_signing() -> None:
    svc: SecretsService = _svc(_Src(KEK_V1, 1))
    await svc.start(_ctx())
    needle, secret = _marked()
    broker = svc._require()
    meta = await broker.store("demo", ACCOUNT, "m", Secret("ABCD1234"), secret, SNAPSHOT)
    broker._store.activate(meta.key_id)  # type: ignore[attr-defined]  # in-memory fake helper
    del secret

    signed = await mint_borrower(svc, "exchange_adapter").sign(
        meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest"
    )
    assert signed.signature  # the call returned a MAC
    gc.collect()

    assert _holders(needle) == []
