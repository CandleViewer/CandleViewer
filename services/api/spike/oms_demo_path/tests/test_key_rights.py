# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The key-rights preflight (#843 A4 fold 3; the coordinator's ruling of 2026-10-25 11:46Z): before
a run is armed, the key's rights, read through the adapter's own signed key-info read, against what
M2's import admitted it with (C-2.8). A mismatch refuses the run and nothing is touched (ruling
R1C-02 (a)). The accounts pack's key-info replies drive it (`packages/fixtures/accounts`, E27-Q01,
through its own resolver): one compliant, one per refusal; the pack has no read-only reply, so that
one is the compliant reply with its flag patched (`offline.patched` refuses a key the shape lacks).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from candleviewer.exchange.bybit.key_info import parse_key_info
from spike.oms_demo_path import report, run, safety
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.offline import (
    Corpus,
    CorpusVenue,
    default_corpus,
    key_info_reply,
    patched,
)
from spike.oms_demo_path.tests.test_cycles import _every_output
from spike.oms_demo_path.tests.test_modes import _Rig
from spike.oms_demo_path.tests.test_scope import _failed_run, _refused_and_untouched
from tests._account_fixtures import load

#: The accounts pack's reference `now` (its README).
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
KEY_INFO = "/v5/user/query-api"
FOREIGN = Decimal("0.003")
#: Each refusal, by the pack's scenario, and the words its reason carries.
REFUSALS = [
    ("withdraw_enabled", "withdrawal or transfer right"),
    ("transfer_enabled", "withdrawal or transfer right"),
    ("ip_missing", "no IP allow-list"),
    ("read_only", "read-only"),
    ("missing_trade_scope", "lacks a trade right"),
    ("ip_wildcard", "a wildcard or a range"),
    ("fiat_p2p_enabled", "allow-list refuses"),
    ("extra_scope_spot", "allow-list refuses"),
]


def _reply(scenario: str) -> dict[str, Any]:
    """`GET /v5/user/query-api` as the pack's resolver answers it for `scenario`."""
    if scenario == "read_only":
        compliant = _reply("compliant")
        return patched(compliant, result=patched(compliant["result"], readOnly=1))
    body: dict[str, Any] = load(scenario, now=NOW).reply("GET", KEY_INFO).body
    return body


def _venue(scenario: str = "compliant") -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()), key_info=_reply(scenario))


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 1, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


@pytest.mark.parametrize(("scenario", "reason"), [("compliant", None), *REFUSALS])
def test_each_corpus_reply_is_judged_as_the_import_judged_it(
    scenario: str, reason: str | None
) -> None:
    mismatch = safety.key_mismatch(parse_key_info(_reply(scenario)))
    assert mismatch is None if reason is None else reason in str(mismatch)


def test_the_offline_default_is_the_packs_compliant_reply() -> None:
    """The venue's default, read from the pack's `compliant` manifest without the resolver (the
    image carries no dev-only code), holds the rights and the allow-list the resolver answers."""
    default, resolved = key_info_reply()["result"], _reply("compliant")["result"]
    for name in ("permissions", "readOnly", "ips", "uta", "userID"):
        assert default[name] == resolved[name], name
    assert safety.key_mismatch(parse_key_info(key_info_reply())) is None


def test_rights_the_shared_rule_cannot_judge_are_refused() -> None:
    body = _reply("compliant")
    unreadable = patched(body["result"], permissions={"ContractTrade": ["Order", float("nan")]})
    facts = parse_key_info(patched(body, result=unreadable))
    assert "withdrawal or transfer right" in str(safety.key_mismatch(facts))


async def test_a_compliant_key_is_read_through_the_adapters_signed_path_then_the_run_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, out = _venue(), tmp_path / "out"
    seen: list[httpx.Request] = []
    handle = venue.handle

    async def recorded(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return await handle(request)

    monkeypatch.setattr(venue, "handle", recorded)
    assert await run.run(_cfg(out), venue=venue) == 0
    s = dict(run.summary_of(out))
    assert s["outcome"] == "completed" and s["key_check"]["verdict"] == "compliant"
    assert s["key_check"]["reason"] is None and s["key_check"]["ip_allow_list_entries"] == 1
    first = seen[0]  # the run's first signed call, before the flat check's reads
    assert (first.method, first.url.path) == ("GET", KEY_INFO)
    assert "X-BAPI-API-KEY" in first.headers and "X-BAPI-SIGN" in first.headers  # M2-signed
    assert [r.url.path for r in seen].count(KEY_INFO) == 1  # read once; never a write
    assert s["signing_ms"]["key_verify"]["n"] == 1 and s["rtt_ms"]["key_info"]["n"] == 1
    assert not list((out / "fixtures").glob("rest_key_info*"))  # the reply is never kept
    text, result = _every_output(out), _reply("compliant")["result"]
    for value in (str(result["userID"]), *result["ips"]):
        assert re.search(rf"(?<![\d.]){re.escape(value)}(?![\d.])", text) is None, value


@pytest.mark.parametrize(("scenario", "reason"), REFUSALS)
async def test_a_key_the_import_would_refuse_refuses_the_run_and_touches_nothing(
    tmp_path: Path, scenario: str, reason: str
) -> None:
    venue = _venue(scenario)
    venue.hold_foreign_position(FOREIGN)
    order = venue.rest_foreign_order()
    out = tmp_path / "out"
    assert await run.run(_cfg(out), venue=venue) == 2
    s = _refused_and_untouched(out, venue, reason)
    assert venue.paths == [KEY_INFO]  # the key's rights first: nothing else was read
    assert (order.status, order.filled, venue.size) == ("New", Decimal(0), FOREIGN)
    assert s["key_check"]["verdict"] == "refused" and reason in s["key_check"]["reason"]
    assert f"Refused, nothing touched: {s['refused']}" in report.render(out)


async def test_a_key_info_read_the_venue_refuses_refuses_the_run(tmp_path: Path) -> None:
    venue = _venue("live_key_on_demo")  # every signed call answers 10003 (the pack's)
    out = tmp_path / "out"
    assert await run.run(_cfg(out), venue=venue) == 2
    s = _refused_and_untouched(out, venue, "an error before the run was armed: AuthError")
    assert s["key_check"] is None and s["error_codes"] == {"10003": 1}
    assert "10003" not in s["error_shapes"]  # the key-info reply is never kept whole


async def test_no_key_info_read_wired_refuses_before_anything_is_signed(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    h = rig.harness
    h.port.limits, _ = safety.QtyLimits.of(await h.public.instrument(), multiple=2, max_multiple=2)
    h.key_info = None
    with pytest.raises(safety.Refused, match="no key-info read"):
        await h.preflight()
    assert rig.venue.paths == [] and not h.armed


async def test_the_uid_and_addresses_the_read_shows_are_scrubbed_wherever_echoed(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path, _venue())
    h = rig.harness
    await h.check_key()
    result = _reply("compliant")["result"]
    uid, address = str(result["userID"]), result["ips"][0]
    h.outputs.event("echo", note=f"the venue said uid {uid} from {address}")
    h.outputs.close()
    written = (tmp_path / "out" / "events.jsonl").read_text(encoding="utf-8")
    assert uid not in written and address not in written and "<redacted>" in written


async def test_flatten_refuses_a_key_that_lost_its_ip_binding_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, account = _venue(), uuid4()
    failed = await _failed_run(tmp_path, venue, account, monkeypatch)
    venue.key_info = _reply("ip_missing")
    venue.paths.clear()
    venue.creates.clear()
    out = tmp_path / "flatten"
    cfg = RunConfig(mode="flatten", out=out, run_dir=failed, account_id=account)
    assert await run.run(cfg, venue=venue) == 2
    _refused_and_untouched(out, venue, "no IP allow-list")
    assert venue.paths == [KEY_INFO] and venue.size == Decimal("0.001")
    assert [o.status for o in venue.orders.values()] == ["PartiallyFilled"]
