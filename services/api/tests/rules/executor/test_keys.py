"""E35-T09 (#5000) slice 2c: the fire key (24 §11.9 "The fire key"), pure functions.

`dedupe_key` is the sha256 of the six fields written as one canonical JSON array, `client_ref` its
`uuid5` under the rules module's fixed namespace, and `request_sha256` the fingerprint of an
action's canonical request, built once per action and account and sent unchanged by a retry.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.accounts.trade_groups import TradeGroupDraft, group_values
from candleviewer.audit.writer import KEYED_ACTIONS
from candleviewer.rules.executor.engine import _status
from candleviewer.rules.executor.keys import (
    RULE_ACTION_NAMESPACE,
    client_ref,
    dedupe_key,
    request_sha256,
)
from candleviewer.rules.executor.results import OUTCOMES, ActionResult, Outcome
from tests.unit.accounts.test_trade_groups import _DRAFT_BASE

RULE = uuid.UUID("5f0c8a52-3a4e-4c1b-9d6e-2b7f1a9c0e41")
RUN = uuid.UUID("9a3d1c7e-52b4-4f08-8e61-3c2b5a4d6f70")
ACCOUNT = uuid.UUID("0b8f6c1e-7d2a-4e5f-a3b9-c4d5e6f70812")
FIRE: dict[str, Any] = {
    "rule_id": RULE, "version": 3, "scope_instance": f"BTCUSDT@{ACCOUNT}", "node_id": "a2",
    "run_id": RUN, "account_id": ACCOUNT,
}  # fmt: skip
#: `tg_ref_fmt` (0039_trade_groups), the format the anchor and the group's ref keep.
_ANCHOR_FMT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _sha(fields: Sequence[str | None]) -> str:
    text = json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_dedupe_key_is_stable_for_the_same_fire_and_action() -> None:
    """Scenario: The fire key is stable and specific (edge case). The same fire and action give
    the same key, and its `client_ref` is a canonical UUID; the per-field differences are below."""
    first, again = dedupe_key(**FIRE), dedupe_key(**FIRE)
    assert first == again and re.fullmatch(r"[0-9a-f]{64}", first)
    assert client_ref(first) == client_ref(again) == str(uuid.UUID(client_ref(first)))


def test_dedupe_key_differs_per_node_account_run_and_version() -> None:
    first = dedupe_key(**FIRE)
    others = {
        "node_id": "a3", "account_id": uuid.UUID(int=9), "run_id": uuid.UUID(int=10),
        "version": 4, "scope_instance": "ETHUSDT@*", "rule_id": uuid.UUID(int=11),
    }  # fmt: skip
    keys = {field: dedupe_key(**(FIRE | {field: value})) for field, value in others.items()}
    assert first not in keys.values() and len(set(keys.values())) == len(keys)
    assert dedupe_key(**(FIRE | {"account_id": None})) != first  # an action that names none


def test_dedupe_key_is_the_contracts_canonical_json() -> None:
    """Six strings in order, ids lower-case hyphenated, `version` in decimal, a missing account
    the JSON `null`, UTF-8 with no whitespace (24 §11.9)."""
    fields = [str(RULE), "3", f"BTCUSDT@{ACCOUNT}", "a2", str(RUN), str(ACCOUNT)]
    assert dedupe_key(**FIRE) == _sha(fields)
    upper = FIRE | {"rule_id": str(RULE).upper(), "node_id": "nœud"}
    assert dedupe_key(**upper) == _sha([*fields[:3], "nœud", *fields[4:]])
    assert dedupe_key(**(FIRE | {"account_id": None})) == _sha([*fields[:5], None])
    for bad, error in ((("version", True), TypeError), (("rule_id", "r1"), ValueError)):
        with pytest.raises(error):
            dedupe_key(**(FIRE | dict([bad])))
    with pytest.raises(ValueError):
        dedupe_key(**(FIRE | {"node_id": ""}))


def test_client_ref_is_a_canonical_uuid_the_anchor_admits() -> None:
    """`str(UUID(ref)) == ref`; the trade-group draft takes it as its `client_group_ref`, written
    as `tg_ref_fmt` requires (24 §9.5 "Rule-originated groups")."""
    ref = client_ref(dedupe_key(**FIRE))
    assert str(uuid.UUID(ref)) == ref and _ANCHOR_FMT.fullmatch(ref)
    assert uuid.UUID(ref).version == 5
    rule_origin = {"origin": "rule", "rule_id": RULE, "rule_run_id": RUN}
    draft = TradeGroupDraft.model_validate(_DRAFT_BASE | rule_origin | {"client_group_ref": ref})
    assert group_values(draft).client_group_ref == ref
    for bad in ("", "0" * 63, "G" * 64, "0" * 64 + "\n"):
        with pytest.raises(ValueError):
            client_ref(bad)


def test_the_rule_action_namespace_is_fixed_for_good() -> None:
    """A new namespace would give every in-flight fire a second `client_ref`, so a retry across
    the change would meet the anchor as a new request."""
    assert RULE_ACTION_NAMESPACE == uuid.UUID("b07bbaaa-85e2-433b-885a-2620f013fa9e")
    assert RULE_ACTION_NAMESPACE.version == 4
    assert RULE_ACTION_NAMESPACE not in KEYED_ACTIONS.values()
    assert client_ref("0" * 64) == "d6dfc42b-bba4-5b32-869a-2138735c1e54"


def test_request_sha256_changes_with_every_field_and_never_with_key_order() -> None:
    request: dict[str, Any] = {
        "symbol": "BTCUSDT", "side": "buy", "qty": Decimal("0.010"), "reduce_only": False,
        "stop": {"trigger": Decimal("62000"), "mode": "absolute"}, "tags": ["a", None, 3],
        "account": ACCOUNT,
    }  # fmt: skip
    digest = request_sha256(request)
    reordered = {k: request[k] for k in reversed(request)} | {
        "stop": {"mode": "absolute", "trigger": Decimal("62000.00")}
    }
    assert request_sha256(reordered) == digest
    text = json.dumps(
        {**request, "qty": "0.01", "stop": {"mode": "absolute", "trigger": "62000"},
         "account": str(ACCOUNT)},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )  # fmt: skip
    assert digest == hashlib.sha256(text.encode("utf-8")).hexdigest()  # an id in canonical form
    changed = {
        "symbol": "ETHUSDT", "side": "sell", "qty": Decimal("0.011"), "reduce_only": True,
        "stop": {"trigger": Decimal("62001"), "mode": "absolute"}, "tags": ["a", None, 4],
        "account": uuid.UUID(int=9),
    }  # fmt: skip
    for field, value in changed.items():
        assert request_sha256(request | {field: value}) != digest, field
    assert request_sha256(request | {"extra": None}) != digest
    unhashable: tuple[Any, ...] = ({"qty": 0.01}, {"n": {"qty": 1.5}}, {"t": object()}, {1: "x"})
    for bad in unhashable:
        with pytest.raises(TypeError):
            request_sha256(bad)


#: The six fields of a fire key, any value each may hold.
_FIRE_FIELDS = st.fixed_dictionaries(
    {
        "rule_id": st.uuids(),
        "version": st.integers(min_value=1, max_value=10**6),
        "scope_instance": st.text(min_size=1, max_size=24),
        "node_id": st.text(min_size=1, max_size=12),
        "run_id": st.uuids(),
        "account_id": st.none() | st.uuids(),
    }
)


def _result(outcome: Outcome) -> ActionResult:
    """A result with `outcome`, its `blocked_by` as the model admits it."""
    return ActionResult(
        node_id="a1", action_type="place_order", account_id=None, resolved_accounts=(),
        outcome=outcome, blocked_by="cap" if outcome == "blocked" else None,
        dedupe_key="0" * 64, duration_us=0,
    )  # fmt: skip


@settings(max_examples=150, deadline=None)
@given(
    fire=_FIRE_FIELDS,
    other=_FIRE_FIELDS,
    qty=st.decimals(min_value="0.001", max_value="1000", places=3),
    outcomes=st.lists(st.sampled_from(OUTCOMES), min_size=1, max_size=6),
    order=st.randoms(use_true_random=False),
)
def test_the_fire_key_the_fingerprint_and_the_close_hold_for_any_fire(
    fire: dict[str, Any],
    other: dict[str, Any],
    qty: Decimal,
    outcomes: list[Outcome],
    order: random.Random,
) -> None:
    """For any fire (24 §11.9, BQ-9): the fire key is a function of its six fields, and each field
    changes it, the resolved account too (E35-T10 keys each account); the fingerprint holds the
    request's value, never its spelling (key order, a decimal's trailing zeros), and changes with
    the value; and the run row's close is `error` once any result failed or is unknown, else `ok`
    when each took effect or was simulated, else `aborted`, whatever the results' order."""
    key = dedupe_key(**fire)
    assert key == dedupe_key(**dict(fire)) and len(key) == 64
    for name, value in other.items():
        if value != fire[name]:
            assert dedupe_key(**(fire | {name: value})) != key, name
    request = {"symbol": "BTCUSDT", "qty": qty, "account": fire["account_id"]}
    digest = request_sha256(request)
    spelt = {"account": fire["account_id"], "qty": Decimal(f"{qty}000"), "symbol": "BTCUSDT"}
    assert request_sha256(spelt) == digest
    assert request_sha256(request | {"qty": qty + Decimal("0.001")}) != digest
    results = [_result(outcome) for outcome in outcomes]
    shuffled = list(results)
    order.shuffle(shuffled)
    close = _status(results)
    assert _status(shuffled) == close
    seen = set(outcomes)
    if seen & {"failed", "unknown"}:
        assert close == "error"
    elif seen <= {"ok", "simulated"}:
        assert close == "ok"
    else:
        assert close == "aborted"
