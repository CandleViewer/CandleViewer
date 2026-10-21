"""Drift check of Bybit's documented key-info reply against the owner's recorded captures (#2240).

`tests/fixtures/key_verification/key_info_docs_example.json` is the Response Example of the "Get
API Key Information" page, transcribed with four recorded redactions (`source: docs-transcribed`,
`stream: GET /v5/user/query-api` in `recorded/manifest.json`; provenance in the README there). It
stands in for a recording: agents never hold a key, and the owner's demo capture is queued
(#2701). Once a capture is listed in that manifest, its field paths and JSON types must agree with
the transcription's, or this test fails naming each difference. `disagreements` keeps the
semantics of G-8's order-path drift check (#2877): recorded only, transcribed only or retyped, and
an empty list shows none of its items. Each capture also runs through the key gates: a `trade` key
passes them, a `fund_rights` key is refused. Until one lands, the README's owed marker is asserted
instead, so nothing is skipped.
"""

from __future__ import annotations

import copy
import importlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.accounts import _permissions as m13
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import PermissionSnapshot
from candleviewer.accounts.verification import FUND_GROUPS
from candleviewer.exchange.bybit.key_info import ApiKeyFacts, parse_key_info
from candleviewer.secrets import _permissions as m2
from candleviewer.secrets.errors import WithdrawPermissionRejected
from tests.unit.accounts._permission_cases import (
    DOCS_REPLY,
    DOCS_TRADE_ONLY,
    KEY_INFO,
    TRANSCRIBED,
    captures,
    manifest,
    reply,
)

_REPO = Path(__file__).resolve().parents[6]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
find_leaks: Callable[[str], list[str]] = importlib.import_module("tools.fixtures.redact").find_leaks

STREAM = "GET /v5/user/query-api"
OWED = "Recorded capture: owed (owner, #2701)"
NOW = datetime(2026, 10, 21, tzinfo=UTC)


def _paths(value: Any, prefix: str = "") -> dict[str, set[str]]:
    """Every field path of `value` with its JSON types (`[]` marks array items)."""
    out: dict[str, set[str]] = {}

    def walk(node: Any, path: str) -> None:
        kind = (
            "null" if node is None else "boolean" if isinstance(node, bool)
            else "number" if isinstance(node, int | float) else "string" if isinstance(node, str)
            else "array" if isinstance(node, list) else "object"
        )  # fmt: skip
        out.setdefault(path, set()).add(kind)
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for child in node:
                walk(child, f"{path}[]")

    walk(value, prefix)
    return out


def disagreements(transcribed: Any, recorded: Any) -> list[str]:
    """Where a recording of the transcription's route and return code differs from it."""
    want, got = _paths(transcribed), _paths(recorded)
    out = [f"recorded only: {p}" for p in sorted(set(got) - set(want))]
    for path in sorted(set(want) - set(got)):
        if "[]" in path and path[: path.rindex("[]") + 2] not in got:
            continue  # an empty array in the recording: it shows none of its items
        parent = path.rsplit(".", 1)[0] if "." in path else ""
        if not parent or any(p.startswith(parent + ".") for p in got):
            out.append(f"transcribed only: {path}")  # the recording shows that object
    out += [
        f"retyped: {p} {sorted(want[p])} -> {sorted(got[p])}"
        for p in sorted(set(want) & set(got))
        if not got[p] <= want[p] and "null" not in got[p] | want[p]
    ]
    return out


def _each(kind: str | None = None) -> pytest.MarkDecorator:
    """Every capture (of `kind`), or `None` while there is none: never an empty parametrization,
    which would skip silently."""
    found: list[dict[str, Any] | None] = [
        e for e in captures() if kind is None or e["kind"] == kind
    ]
    ids = [Path(e["path"]).stem for e in found if e is not None] or ["none-recorded-yet"]
    return pytest.mark.parametrize("capture", found or [None], ids=ids)


def _owed() -> None:
    assert OWED in (KEY_INFO / "README.md").read_text(encoding="utf-8")


def test_the_transcription_names_its_route_and_its_docs_source() -> None:
    [entry] = [e for e in manifest() if e["source"] == TRANSCRIBED]
    assert (entry["stream"], entry["http_status"]) == (STREAM, None)
    assert entry["source_ref"].endswith(":docs/v5/user/apikey-info.mdx")


def test_the_docs_example_parses_into_key_facts() -> None:
    """The documented key is IP-bound, with `expiredAt` at the Unix epoch and `deadlineDay` -2,
    which the parser reads as no expiry."""
    assert parse_key_info(DOCS_REPLY) == ApiKeyFacts(
        uid="1000001",
        uta=True,
        read_only=True,
        permissions=DOCS_REPLY["result"]["permissions"],
        ip_whitelist=("203.0.113.7", "203.0.113.8", "203.0.113.9"),
        expires_at=None,
    )


def test_every_docs_example_group_holds_a_list_of_strings() -> None:
    """The value-in-group shape: rights are strings in a group's list, and there is no top-level
    `Withdraw` group (the shape E27-T01 assumed)."""
    groups = DOCS_REPLY["result"]["permissions"]
    assert groups and "Withdraw" not in groups
    assert all(isinstance(v, list) and all(isinstance(r, str) for r in v) for v in groups.values())


def test_the_gates_spell_groups_and_rights_as_the_docs_print_them() -> None:
    """The M2 allow-list's rights and M13's fund groups are names the documented reply prints."""
    groups = DOCS_REPLY["result"]["permissions"]
    assert all(set(rights) <= set(groups[g]) for g, rights in m2.ALLOWED_RIGHTS.items())
    assert FUND_GROUPS <= set(groups)


def test_the_docs_example_holds_no_secret_shaped_content() -> None:
    """Redacted as the README records: a synthetic key id and UID, a masked key, an empty secret
    and RFC 5737 whitelist addresses. The leak scan flags those field names only."""
    result = DOCS_REPLY["result"]
    fields = (
        result["id"],
        result["apiKey"],
        result["secret"],
        result["userID"],
        result["parentUid"],
    )
    assert fields == ("1000", "***", "", 1000001, "0")
    assert all(ip_address(ip) in ip_network("203.0.113.0/24") for ip in result["ips"])
    text = (KEY_INFO / "key_info_docs_example.json").read_text(encoding="utf-8")
    assert set(find_leaks(text)) <= {"json-field"}


@_each()
def test_the_docs_example_and_every_recorded_capture_agree(capture: dict[str, Any] | None) -> None:
    if capture is None:
        _owed()
        return
    assert (capture["stream"], capture["kind"] in {"trade", "fund_rights"}) == (STREAM, True)
    assert disagreements(DOCS_REPLY, reply(capture)) == []


def test_a_planted_disagreement_fails_naming_each_difference() -> None:
    planted = copy.deepcopy(DOCS_REPLY)
    result = planted["result"]
    result["permissions"]["Wallet"] = "AccountTransfer"  # a group that is no list
    result["permissions"]["SpotV2"] = result["permissions"].pop("Spot")  # a renamed group
    result["newVenueField"] = "x"  # an added field
    result["readOnly"] = "1"  # a retyped field
    assert disagreements(DOCS_REPLY, planted) == [
        "recorded only: result.newVenueField",
        "recorded only: result.permissions.SpotV2",
        "recorded only: result.permissions.SpotV2[]",
        "transcribed only: result.permissions.Spot",
        "retyped: result.permissions.Wallet ['array'] -> ['string']",
        "retyped: result.readOnly ['number'] -> ['string']",
    ]


def _docs_trade_reply() -> dict[str, Any]:
    """The documented reply as a compliant trade key would answer: trade rights only, writable."""
    trade = copy.deepcopy(DOCS_REPLY)
    trade["result"].update(permissions=DOCS_TRADE_ONLY, readOnly=0, note="trade", id="2000")
    return trade


def test_a_trade_key_reply_with_empty_groups_agrees() -> None:
    """An empty group shows none of its rights, and values are never compared."""
    assert disagreements(DOCS_REPLY, _docs_trade_reply()) == []


def _passes_every_layer(raw: dict[str, Any]) -> None:
    """A trade key's reply: every gate admits it, and M2 derives `can_trade` from it."""
    facts = parse_key_info(raw)
    permissions = dict(facts.permissions)
    snapshot = {"fetched_at": NOW, "uid": facts.uid, "readOnly": 0, "permissions": permissions}
    assert not facts.read_only
    assert m2.trade_capable(m2.project_snapshot({**snapshot, "fetched_at": NOW.isoformat()}))
    m13.reject_withdraw(permissions)
    PermissionSnapshot.model_validate(snapshot)


def _is_refused_by_every_layer(raw: dict[str, Any]) -> None:
    """A reply holding a transfer or withdrawal right: every gate refuses it."""
    permissions = dict(parse_key_info(raw).permissions)
    for m2_line in (m2.require_allow_listed, m2.reject_withdraw):
        with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
            m2_line(permissions)
    with pytest.raises(WithdrawPermissionError):
        m13.reject_withdraw(permissions)
    with pytest.raises(ValidationError, match="key_withdraw_permission"):
        PermissionSnapshot.model_validate(
            {"fetched_at": NOW, "uid": "1", "permissions": permissions}
        )


def test_the_documented_reply_is_refused_by_every_layer_a_capture_meets() -> None:
    """The checks a fund-rights capture will meet run now, on the documented reply: its Wallet
    rights are refused everywhere, so the check is proved before any capture lands."""
    _is_refused_by_every_layer(DOCS_REPLY)


def test_its_trade_only_variant_passes_every_layer_a_capture_meets() -> None:
    """The checks a trade capture will meet run now, on the documented reply with trade rights
    only and write access: every layer admits it."""
    _passes_every_layer(_docs_trade_reply())


@_each("trade")
def test_every_recorded_trade_capture_passes_every_layer(capture: dict[str, Any] | None) -> None:
    if capture is None:
        _owed()
        return
    _passes_every_layer(reply(capture))


@_each("fund_rights")
def test_every_recorded_fund_rights_capture_is_refused_by_every_layer(
    capture: dict[str, Any] | None,
) -> None:
    if capture is None:
        _owed()
        return
    _is_refused_by_every_layer(reply(capture))
