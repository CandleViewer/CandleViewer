"""tests/xstate_contract/test_factory.py — E50-T59 factory contract tests.

Lives under `tests/xstate_contract/` (the one test dir CV-LINT-IMPORT
allows to import `xstate_statemachine` directly, alongside `factory.py`
itself) because these tests assert on `Interpreter` attributes directly
to verify the FINAL mandatory config block (28-statechart-catalogue.md
§1.3c) was actually applied — not just that `build()` returned something.

Covers the ticket's four Gherkin acceptance criteria:
  1. every registered machine loads under the factory with
     strict=True / overflow_policy=refuse / the lane inbox bound;
  2. start() is bounded (CV-C56) — a hanging entry action times out;
  3. the sync engine is refused (MUSTNOT-06);
  4. no action coroutine is silently dropped (CV-C67) — asserted via the
     dedicated `bindings` unit tests plus `-W error::RuntimeWarning` here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from xstate_statemachine import Interpreter, OverflowPolicy, SimulatedClock

import candleviewer.statechart.factory as factory_mod
from candleviewer.statechart import build
from candleviewer.statechart.config import CV_INBOX_BOUND, CV_SERVICE_POOL, LANES
from candleviewer.statechart.factory import SyncInterpreterRefusedError
from candleviewer.statechart.registry import Registry

_FIXTURES = Path(__file__).resolve().parent / "factory_fixtures"

# Importing the fixture binding module registers "test.factory_min" with
# the bindings loader as a side effect (mirrors how a real
# `bindings/b<NN>_<name>.py` module self-registers on import).
from tests.xstate_contract.factory_fixtures import binding_min  # noqa: E402,F401


@pytest.fixture()
def factory_registry() -> Registry:
    return Registry(machines_dir=_FIXTURES)


@pytest.mark.parametrize("lane", LANES)
async def test_build_applies_mandatory_config_per_lane(
    factory_registry: Registry, lane: str
) -> None:
    result = await build(
        "test.factory_min",
        clock=SimulatedClock(),
        lane=lane,  # type: ignore[arg-type]
        registry=factory_registry,
    )
    interp = result.interpreter
    try:
        assert isinstance(interp, Interpreter)
        assert interp.strict is True
        assert interp._overflow_policy == OverflowPolicy.RAISE
        assert interp._max_queue_size == CV_INBOX_BOUND[lane]  # type: ignore[index]
        assert interp._service_pool_size == CV_SERVICE_POOL[lane]  # type: ignore[index]
        assert result.machine_hash == factory_registry.hash("test.factory_min")
    finally:
        await interp.stop()


async def test_start_is_bounded_by_cv_start_timeout(
    factory_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A binding whose entry never yields must trip `TimeoutError`
    (CV-C56) rather than hang forever."""
    monkeypatch.setattr(factory_mod, "CV_START_TIMEOUT", 0.05)

    async def _hang(self: Interpreter, **_kw: object) -> Interpreter:
        await asyncio.sleep(10)
        return self

    monkeypatch.setattr(Interpreter, "start", _hang)

    with pytest.raises(TimeoutError):
        await build(
            "test.factory_min",
            clock=SimulatedClock(),
            lane="platform",
            registry=factory_registry,
        )


async def test_sync_engine_is_refused(factory_registry: Registry) -> None:
    with pytest.raises(SyncInterpreterRefusedError):
        await build(
            "test.factory_min",
            clock=SimulatedClock(),
            lane="platform",
            registry=factory_registry,
            sync=True,
        )


# --- #1649: event_schemas must be callable validators (xstate 0.9.1) -------


async def test_event_schemas_validate_through_real_factory_path(
    factory_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registered schema accepts a canonical payload and rejects a
    malformed one via the real interpreter (no pass-through validators)."""
    from xstate_statemachine.exceptions import InvalidEventPayloadError

    from candleviewer.statechart import config as cfg

    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "additionalProperties": False,
    }
    monkeypatch.setitem(cfg.CV_EVENT_SCHEMAS, "test.factory_min", {"GO": schema})
    result = await build(
        "test.factory_min", clock=SimulatedClock(), lane="platform", registry=factory_registry
    )
    interp = result.interpreter
    try:
        with pytest.raises(InvalidEventPayloadError):
            await interp.send("GO", n="not-an-int")
        await interp.send("GO", n=1)
    finally:
        await interp.stop()


def test_every_registered_event_schema_compiles_to_working_validator() -> None:
    import candleviewer.statechart.bindings.b16_session  # noqa: F401
    from candleviewer.statechart.config import CV_EVENT_SCHEMAS
    from candleviewer.statechart.factory import _event_validators

    assert CV_EVENT_SCHEMAS["session"]
    for machine, schemas in CV_EVENT_SCHEMAS.items():
        validators = _event_validators(schemas)
        assert set(validators) == set(schemas)
        for name, validate in validators.items():
            assert validate.is_valid({}) or validate.iter_errors({}), (machine, name)
            assert not validate.is_valid("not-an-object"), (machine, name)


async def test_a_machine_gets_only_its_own_event_schemas(
    factory_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#847: another machine's schema for the same event name never applies."""
    from candleviewer.statechart import config as cfg

    closed = {"type": "object", "additionalProperties": False}
    monkeypatch.setitem(cfg.CV_EVENT_SCHEMAS, "test.another_machine", {"GO": closed})
    result = await build(
        "test.factory_min", clock=SimulatedClock(), lane="platform", registry=factory_registry
    )
    try:
        await result.interpreter.send("GO", n=1)
    finally:
        await result.interpreter.stop()
