"""E29-X02 (#982), Gherkin 5 and AC-15 (SR-E29-08 item 4, OM-I05; C-2.7, C-12.6): no credential
reaches storage. A Hypothesis run seeds credentials where a venue's answer to an order create
carries them, and runs each through the whole write path of `test_duplicate_link_id`'s world: the
adapter's port (`BybitTradingPort` over a replay of `rest/trading-create-reply.json` or
`rest/trading-error-110017.json`, the seed placed on that shape), B1's step and the fake store.
Each event the step hands the store is also bound as the Postgres store binds it
(`orders_sqlalchemy._event_values`). None of the seeds may appear in a stored event, its reads (the
`include_events` body and the diagnostics' exchange calls), an audit record or a log line.

Where each seed is put, and the control that keeps it out on its own:

- `headers`: the call's key, signature and receive window, and the seed, echoed as response
  headers: the adapter's allow-listed record, which reads no header;
- `unknown_fields`: the seed under result fields the record does not name (a key name, a
  message name, an `auth` frame, a symbol-shaped value): the record's allow-list;
- `own_key_in_message`: the call's own key id echoed in `retMsg`: the REST client's reply masking
  (the key id, split by separators, passes the store's redactor);
- `own_signature_in_message`: the call's own signature echoed in `retMsg`: the masking, and the
  redactor behind it;
- `key_in_message` and `signed_url_in_message`: a letters-only fixture key, alone or as a signed
  URL's query, in `retMsg`, which the record keeps as the venue's text: the store's fail-closed
  redactor.

Its negative controls are here, as no OMS world of this suite is up in this module (B1's ports are
one per process, C-2.11): each control removed in turn, the case it alone holds turns red (NC-2,
the store's redaction call; NC-3, the REST client's reply masking), and what the record alone keeps
out stays out without the redactor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import string
from collections.abc import Callable
from typing import Any, Final

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.api.oms_reads import event_document
from candleviewer.api.order_diagnostics import exchange_calls
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.storage.repositories import exchange_payload, orders_sqlalchemy
from candleviewer.storage.repositories.orders_sqlalchemy import _event_values
from tests._corpus import rest
from tests.security.oms.test_duplicate_link_id import _CREATE, _oms, _sent
from tests.unit.exchange.bybit._trading import SIGNER_ID, Venue, with_result
from tests.unit.oms import command_rig as cr

PLACES: Final = (
    "headers", "unknown_fields", "own_key_in_message", "own_signature_in_message",
    "key_in_message", "signed_url_in_message",
)  # fmt: skip
#: A letters-only fixture key: no digit, so outside a message the store's redactor passes it.
SEEDS: Final = st.text(alphabet=string.ascii_letters, min_size=18, max_size=32)
_ACCEPTED, _REFUSED = rest("rest/trading-create-reply.json"), rest("rest/trading-error-110017.json")


class Echo(Venue):
    """The venue's create answer, carrying the seed where `place` says; the call's own key id and
    signature are read off the request, as a venue echoing its input would."""

    def __init__(self, place: str, seed: str) -> None:
        super().__init__()
        self.place, self.seed = place, seed

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        assert request.url.path == _CREATE, request.url.path  # one create, nothing else
        seed, msg = self.seed, _REFUSED["retMsg"]
        ours = with_result(_ACCEPTED, orderLinkId=json.loads(request.content)["orderLinkId"])
        if self.place == "headers":
            sent = {k: v for k, v in request.headers.items() if k.lower().startswith("x-bapi-")}
            return httpx.Response(200, json=ours, headers=sent | {"X-Echo": seed})
        if self.place == "unknown_fields":
            extra = {"apiKey": seed, "rejectMsg": seed, "retExtInfo": {"op": "auth",
                     "args": [seed, 1, seed]}, "echo": f"{seed.upper()}USDT"}  # fmt: skip
            return httpx.Response(200, json=with_result(ours, **extra))
        text = {
            "own_key_in_message": f"{msg}: {request.headers['X-BAPI-API-KEY']}",
            "own_signature_in_message": f"{msg}: {request.headers['X-BAPI-SIGN']}",
            "key_in_message": f"{msg}: {seed}",
            "signed_url_in_message": f"{msg}: https://venue.invalid/v5/order/create"
                                     f"?api_key={seed}&sign={seed}",
        }[self.place]  # fmt: skip
        return httpx.Response(200, json=_REFUSED | {"retMsg": text})

    def seeds(self) -> set[str]:
        """Every credential this venue saw or planted: the seed, our key id, each signature."""
        return {self.seed, SIGNER_ID, *(r.headers["X-BAPI-SIGN"] for r in self.sent)}


async def _written(venue: Echo, mp: pytest.MonkeyPatch) -> tuple[list[str], list[Any]]:
    """One create through the world: what it stored, as text (each event, each event bound as
    Postgres binds it, each audit record), and the events, for their reads."""
    handed: list[Any] = []
    real = InMemoryOrderStore._event

    def event(store: InMemoryOrderStore, order: Any, new: Any, states: Any) -> Any:
        handed.append(new)
        return real(store, order, new, states)

    mp.setattr(InMemoryOrderStore, "_event", event)
    order = cr.new_order()
    async with _oms(venue, mp) as placed:
        row = await _sent(placed, order)
        events = await placed.rig.store.list_for_order(cr.ACCOUNT, order.id)
    assert row.lifecycle_state in ("submitted", "rejected"), row.lifecycle_state
    assert any("record" in e.payload for e in events), "no step stored the call's record"
    texts = [repr(e) for e in events] + [repr(_event_values(new)) for new in handed]
    return texts + [repr(record) for record, _ in placed.rig.audits.written], list(events)


def leaked(seeds: set[str], text: str) -> list[str]:
    return sorted(s for s in seeds if s in text)


def assert_nothing_stored(place: str, seed: str, caplog: pytest.LogCaptureFixture) -> None:
    """One run of `place`: no seed in what it stored or logged, then none in the stored events'
    reads, which serve every record (the diagnostics' checks refuse none)."""
    venue = Echo(place, seed)
    caplog.clear()
    with pytest.MonkeyPatch.context() as mp, capture_logs() as logs:
        texts, events = asyncio.run(_written(venue, mp))
    seeds = venue.seeds()
    assert len(seeds) >= 3, seeds  # the seed, our key id and the call's signature
    stored = "\n".join([*texts, json.dumps(logs, default=str), caplog.text])
    assert not leaked(seeds, stored), f"a seeded credential reached storage ({place})"
    reads = [event_document(e) for e in events], exchange_calls(events)
    assert not leaked(seeds, json.dumps(reads, default=str)), f"a read served one ({place})"


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(seed=SEEDS, place=st.sampled_from(PLACES))
def test_g5_no_seeded_credential_reaches_an_event_its_reads_an_audit_record_or_a_log(
    seed: str, place: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    assert_nothing_stored(place, seed, caplog)


@pytest.mark.parametrize("place", PLACES)
def test_g5_each_place_carries_its_seed_to_the_venues_answer_and_none_is_stored(
    place: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The run is not vacuous: each place's answer carries the seed (or our own key id), and the
    store still holds the call's record (`_written` asserts it)."""
    seed = string.ascii_letters[:20]
    request = httpx.Request(
        "POST",
        f"https://venue.invalid{_CREATE}",
        json={"orderLinkId": "x"},
        headers={"X-BAPI-API-KEY": SIGNER_ID, "X-BAPI-SIGN": "a1" * 32},
    )
    answer = Echo(place, seed).handler(request)
    planted = {"own_key_in_message": SIGNER_ID, "own_signature_in_message": "a1" * 32}.get(
        place, seed
    )
    assert planted in answer.text + json.dumps(dict(answer.headers))
    caplog.set_level(logging.DEBUG)
    assert_nothing_stored(place, seed, caplog)


def _no_store_redaction(mp: pytest.MonkeyPatch) -> None:
    """Both stores bind the exchange's payload and text as they came: JSON-safe, nothing taken."""
    for module in (exchange_payload, orders_sqlalchemy):
        mp.setattr(module, "redact_exchange_payload", lambda raw: json.loads(json.dumps(raw)))
        mp.setattr(module, "redact_exchange_text", lambda text, **_kw: text)


def _no_reply_masking(mp: pytest.MonkeyPatch) -> None:
    mp.setattr("candleviewer.exchange.bybit.rest._mask", lambda body, _secrets: body)


_STORED: Final[list[tuple[Callable[[pytest.MonkeyPatch], None], str]]] = [
    (_no_store_redaction, "key_in_message"),
    (_no_store_redaction, "signed_url_in_message"),
    (_no_reply_masking, "own_key_in_message"),
]


@pytest.mark.parametrize(
    ("remove", "place"), _STORED, ids=[f"{r.__name__}-{p}" for r, p in _STORED]
)
def test_negative_control_a_seeded_credential_is_stored_without_its_control(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    remove: Callable[[pytest.MonkeyPatch], None],
    place: str,
) -> None:
    remove(monkeypatch)
    with pytest.raises(AssertionError, match=re.escape(f"reached storage ({place})")):
        assert_nothing_stored(place, string.ascii_letters[:20], caplog)


@pytest.mark.parametrize("place", ["headers", "unknown_fields"])
def test_negative_control_the_record_alone_keeps_headers_and_unknown_fields_out(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, place: str
) -> None:
    """NC-2 targets what only the redactor stops: with it removed, these stay out by the record."""
    _no_store_redaction(monkeypatch)
    assert_nothing_stored(place, string.ascii_letters[:20], caplog)
