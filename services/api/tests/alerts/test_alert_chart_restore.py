"""#1865: a B10 `alert` chart that `AlertCharts` built and drove survives a sealed snapshot
round-trip through `statechart.persistence`, and a forged envelope is refused (CV-C53, MUST-12).

These pin the chart against the real persistence API, with test HMAC keys only: `Persister`
seals the envelope and every restore goes through the public `statechart.factory.restore`
entry point (which delegates to `persistence.Restorer`). `AlertCharts` itself still rebuilds
from the `alerts` row: production restore needs the persistence bundle, which stays `None`
until an HMAC key provider exists (#2701).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from candleviewer.alerts.lifecycle import AlertCharts, _Refusals, leaf_of
from candleviewer.statechart import factory
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import Gateway
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    RestoreRefusedError,
    RestoreResult,
    SealedSnapshot,
    hmac_sealer,
)
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import Audit, Keys, Pager, Repo

ALERT = "00000000-0000-0000-0000-0000000000a1"
KEY = MachineKey("alert", ALERT, "demo")
_REG = Registry()


class _OtherKeys(Keys):
    """Same key id, other key bytes: an envelope sealed under the real key must not verify."""

    def key(self, key_id: str) -> bytes:
        return b"\x08" * 32


class _Pages:
    """A `persistence.Pager` that records each page's key, severity and message."""

    def __init__(self) -> None:
        self.pages: list[tuple[MachineKey, str, str]] = []

    async def page(self, key: MachineKey, severity: str, message: str) -> None:
        self.pages.append((key, severity, message))


async def _restore(
    envelope: SealedSnapshot,
    *,
    audit: Audit | None = None,
    pager: _Pages | None = None,
    keys: Keys | None = None,
) -> RestoreResult:
    restorer = Restorer(
        registry=_REG, keys=keys or Keys(), journal=InMemoryDrainJournal(),
        audit=audit or Audit(), pager=pager or _Pages(), latch=ChainTripLatch(),
        plugins=lambda _key: [], clock=default_clock(), lane="platform",
    )  # fmt: skip
    return await factory.restore(restorer, KEY, envelope)


async def _sealed(drive: str) -> tuple[SealedSnapshot, str, dict[str, Any]]:
    """Drive a chart through `AlertCharts` to a non-initial quiescent leaf, persist it, and
    return the envelope with the leaf and context it was taken at."""
    charts = AlertCharts()
    try:
        if drive == "delivered":
            await charts.fired(ALERT, [7, 8], ["in_app", "email"], owner=None)
        else:
            await charts.suppressed(ALERT, 1_700_000_000_000, owner=None)
        interp = charts._charts[ALERT]  # test-only: reach the live chart AlertCharts built
        leaf, context = leaf_of(interp), dict(interp.context)
        assert leaf == drive
        repo = Repo()
        await Persister(
            repo=repo, journal=InMemoryDrainJournal(), audit=Audit(),
            seal=hmac_sealer(Keys(), _REG.get("alert")), machine_hash_of=_REG.hash,
            pager=Pager(),
        ).persist(interp, key=KEY)  # fmt: skip
        envelope: SealedSnapshot = repo.rows[KEY]
        return envelope, leaf, context
    finally:
        await charts.stop()


async def _refused(envelope: SealedSnapshot, reason: str, *, keys: Keys | None = None) -> None:
    """The restore is refused for `reason`, quarantined once and paged P1 once, naming it."""
    audit, pager = Audit(), _Pages()
    with pytest.raises(RestoreRefusedError, match=reason):
        await _restore(envelope, audit=audit, pager=pager, keys=keys)
    assert len(audit.quarantined) == 1 and reason in audit.quarantined[0]
    assert len(pager.pages) == 1
    key, severity, message = pager.pages[0]
    assert (key, severity) == (KEY, "P1")
    assert message.startswith("snapshot refused: ") and reason in message


@pytest.mark.parametrize("drive", ["delivered", "suppressed"])
async def test_alert_chart_restore_round_trip_keeps_state_and_context(drive: str) -> None:
    envelope, leaf, context = await _sealed(drive)
    assert envelope.machine_hash == _REG.hash("alert")
    res = await _restore(envelope)
    try:
        assert leaf_of(res.interpreter) == leaf
        assert dict(res.interpreter.context) == context
        assert not res.degraded and res.replayed == 0
    finally:
        await res.interpreter.stop()


async def test_alert_chart_restored_delivered_chart_takes_the_next_event() -> None:
    envelope, _, _ = await _sealed("delivered")
    res = await _restore(envelope)
    gw = Gateway()
    # test-only: `_Refusals` is the refusal counter AlertCharts registers its charts with
    gw.register(ALERT, res.interpreter, kind="alert", lane="platform", metrics=_Refusals())
    try:
        await gw.send(ALERT, {"type": "ACK"}, wait=True)
        assert leaf_of(res.interpreter) == "acknowledged"
    finally:
        await res.interpreter.stop()


async def test_alert_chart_restore_refuses_another_machine_hash() -> None:
    envelope, _, _ = await _sealed("delivered")
    await _refused(dataclasses.replace(envelope, machine_hash="0" * 64), "machine_hash")


async def test_alert_chart_restore_refuses_a_tampered_hmac_tag() -> None:
    envelope, _, _ = await _sealed("delivered")
    tag = envelope.seal.tag
    forged = dataclasses.replace(
        envelope,
        seal=dataclasses.replace(envelope.seal, tag=("1" if tag[0] == "0" else "0") + tag[1:]),
    )
    await _refused(forged, "bad HMAC")


async def test_alert_chart_restore_refuses_a_tampered_context_under_a_valid_tag() -> None:
    envelope, _, _ = await _sealed("delivered")
    ctx = {**envelope.snapshot["context"], "delivered_channels": ["in_app", "email", "webhook"]}
    await _refused(
        dataclasses.replace(envelope, snapshot={**envelope.snapshot, "context": ctx}), "bad HMAC"
    )


async def test_alert_chart_restore_refuses_an_envelope_sealed_under_another_key() -> None:
    envelope, _, _ = await _sealed("delivered")
    await _refused(envelope, "bad HMAC", keys=_OtherKeys())
