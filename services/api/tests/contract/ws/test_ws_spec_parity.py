"""`runtime_spec_parity` for the WS surface (#572, 23-ws-protocol.md section 16.5).

The first comparison of the running gateway with the document: `welcome.limits` (advertised
against enforced against documented), the limits summary of 16.2, the error catalogue's scope and
`retryable`, the close codes, the binary layout of 3.4, the frame types of 3.1, the `CV_WS_*`
settings and the subprotocols. The topic catalogue is `test_ws_topic_registry_as_built.py`'s
(#2823), extended there. The document is the source of truth (C-6.1): a drift here means the code
moves to match, in the same PR that moves either.

A mismatch found while a test is added is marked `xfail(strict=True)` with a reason that names it,
so it is neither a red build nor a silent one; the fix removes the mark."""

from __future__ import annotations

import dataclasses
import functools
from typing import Any

import pytest

from candleviewer.ws import lifecycle, limits
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.topics import FAMILIES
from tests.contract.ws import _doc, _harness
from tests.contract.ws import _spec_parity as sp
from tests.contract.ws._harness import World, connect

JSON = ["cv.v1.json"]


def handshake_limits() -> dict[str, int]:
    """`welcome.limits` of a real `hello` to the harness's gateway, wired as production is."""
    with connect(World(), JSON) as client:
        welcome = client.seen[0]
        assert welcome["t"] == "welcome"
        limits_: dict[str, int] = welcome["p"]["limits"]
        return limits_


# --- welcome.limits -----------------------------------------------------------------------------


def test_welcome_limits_are_the_documented_ones() -> None:
    drifts = sp.limits_drifts(handshake_limits())
    assert not drifts, sp.render(drifts)


def test_the_4_2_table_its_example_and_16_2_state_the_six_limits_alike() -> None:
    drifts = sp.limit_renderings_drifts()
    assert not drifts, sp.render(drifts)


def test_advertised_limits_are_the_constants_that_enforce_them() -> None:
    def where(key: str) -> str:
        return f"candleviewer.ws.{sp.LIMIT_KEYS[key][1]}"

    drifts = sp.diff("welcome.limits", sp.enforced_limits(), handshake_limits(), where)
    assert not drifts, sp.render(drifts)


def test_the_advertised_inbound_cap_is_the_one_the_gateway_enforces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lowered = 2048  # what `Settings.ws_max_inbound_frame_bytes` hands `make_ws_router`
    monkeypatch.setattr(
        _harness, "make_ws_router", functools.partial(make_ws_router, max_frame_bytes=lowered)
    )
    assert handshake_limits()["max_inbound_frame_bytes"] == lowered


def test_max_subscriptions_300_without_a_doc_change_fails_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(lifecycle.LIMITS_BLOCK, "max_subscriptions", 300)
    drifts = sp.limits_drifts(handshake_limits())
    assert [d.key for d in drifts] == ["max_subscriptions"]
    text = sp.render(drifts)
    assert "welcome.limits.max_subscriptions: runtime 300" in text
    assert "23-ws-protocol.md section 4.2 (line" in text and ") says 200" in text
    assert "section 16.2 row 'Max subscriptions / connection' (line" in text
    assert "The document is the source of truth (C-6.1)" in text


@pytest.mark.parametrize("key", sorted(sp.LIMIT_KEYS))
def test_every_limit_change_fails_parity(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    change = 1
    if (
        key == "max_inbound_frame_bytes"
    ):  # advertised from the gateway's own cap, which a setting lowers
        cap = functools.partial(make_ws_router, max_frame_bytes=limits.MAX_INBOUND_FRAME_BYTES - 1)
        monkeypatch.setattr(_harness, "make_ws_router", cap)
        change = -1
    else:
        monkeypatch.setitem(lifecycle.LIMITS_BLOCK, key, lifecycle.LIMITS_BLOCK[key] + 1)
    drifts = sp.limits_drifts(handshake_limits())
    assert [(d.key, d.runtime - d.doc) for d in drifts] == [(key, change)]


def test_a_limits_key_with_no_doc_row_fails_parity() -> None:
    drifts = sp.limits_drifts({**handshake_limits(), "max_new_things": 5})
    assert [(d.key, d.doc, d.runtime) for d in drifts] == [("max_new_things", "absent", 5)]


# --- 16.2 and 3.6 -------------------------------------------------------------------------------


def test_16_2_rows_are_the_constants_that_enforce_them() -> None:
    drifts = sp.table_drifts(sp.section_16_2(), sp.LIMIT_ROWS, "section 16.2")
    assert not drifts, sp.render(drifts)


def test_every_16_2_row_is_mapped_or_contract_only() -> None:
    assert sp.rows_without_a_registry_entry() == []


def test_a_16_2_row_marked_contract_only_has_no_code_yet() -> None:
    assert sp.contract_only_rows_that_landed() == []


def test_a_row_left_contract_only_after_its_code_landed_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last such row was the machines' terminal retention: #3966 built it, the probe fired."""
    row = ("E17-T08 (#414)", sp._probe("machines", "RETENTION"))
    monkeypatch.setitem(sp.CONTRACT_ONLY_ROWS, "Terminal machine retention", row)
    assert sp.contract_only_rows_that_landed() == ["Terminal machine retention"]


def test_every_limits_constant_has_a_row_or_a_reason() -> None:
    assert sp.limits_without_a_doc_row() == []


def test_a_new_limits_constant_with_no_doc_row_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "MAX_NEW_THINGS", 5, raising=False)
    assert sp.limits_without_a_doc_row() == ["MAX_NEW_THINGS"]


def test_a_changed_16_2_constant_fails_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "MAX_BARS_SUBSCRIPTIONS", 17)
    drifts = sp.table_drifts(sp.section_16_2(), sp.LIMIT_ROWS, "section 16.2")
    assert [(d.key, d.doc, d.runtime) for d in drifts] == [
        ("Max `bars.*` / connection", [16], [17])
    ]


def test_a_changed_indicator_cap_fails_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    from candleviewer.orderflow.indicators import limits as caps

    monkeypatch.setattr(caps, "INSTANCE_CAP_PER_USER", 9)
    drifts = sp.table_drifts(sp.section_16_2(), sp.LIMIT_ROWS, "section 16.2")
    assert [(d.key, d.doc, d.runtime) for d in drifts] == [
        ("`indicators` server instances", [8, 8, 32, 128], [8, 9, 32, 128])
    ]


def test_a_marker_under_a_served_family_is_a_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = f"\n- **`bars` (a test).**\n  - {sp.CONTRACT_ONLY_WORDS} A served family, marked.\n"
    monkeypatch.setattr(_doc, "DOC", _doc.DOC + extra)
    assert "bars" in sp.families_marked_contract_only()
    drifts = [d for d in sp.contract_only_drifts(FAMILIES) if d.key == "bars"]
    assert [(d.doc, d.runtime) for d in drifts] == [("contract only", "served=True")]


def test_a_marker_under_no_family_is_a_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = f"\n- **`nosuch` (a test).**\n  - {sp.CONTRACT_ONLY_WORDS} Not a family.\n"
    monkeypatch.setattr(_doc, "DOC", _doc.DOC + extra)
    drifts = [d for d in sp.contract_only_drifts(FAMILIES) if d.key == "nosuch"]
    assert [(d.doc, d.runtime) for d in drifts] == [("a contract-only marker", "no such family")]


@pytest.mark.parametrize(
    "bullets",
    [
        "- **`book` depth is in the topic name, not the options**, a test.\n",  # names a family
        "- **`footprint` (a test).**\n- **An explanatory bullet, a test.**\n",  # follows a family
    ],
)
def test_a_marker_under_an_explanatory_bullet_is_not_attributed_to_a_family(
    bullets: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    extra = f"\n{bullets}  - {sp.CONTRACT_ONLY_WORDS} Nested under a bullet that is no family's.\n"
    monkeypatch.setattr(_doc, "DOC", _doc.DOC + extra)
    assert not {"book", "footprint"} & sp.families_marked_contract_only()
    drifts = sp.contract_only_drifts(FAMILIES)
    assert [(d.doc, d.runtime) for d in drifts] == [("a contract-only marker", "no such family")]


def test_3_6_json_bounds_and_sr_185_msgpack_bounds_are_the_codecs() -> None:
    drifts = sp.table_drifts(sp.section_3_6_rows(), sp.SECTION_3_6_ROWS, "section 3.6")
    drifts += sp.msgpack_bound_drifts()
    assert not drifts, sp.render(drifts)


# --- 10.2 error catalogue -----------------------------------------------------------------------


def test_10_2_retryable_is_the_registrys() -> None:
    drifts = sp.error_drifts("retryable")
    assert not drifts, sp.render(drifts)


def test_10_2_rest_column_is_the_registrys() -> None:
    drifts = sp.error_drifts("rest")
    assert not drifts, sp.render(drifts)


def test_10_2_scope_is_the_registrys() -> None:
    drifts = sp.error_drifts("scope")
    assert not drifts, sp.render(drifts)


# --- 4.4 close codes ----------------------------------------------------------------------------


def test_4_4_codes_are_the_gateways_the_bye_enum_and_the_hosts_1012() -> None:
    drifts = sp.close_code_drifts()
    assert not drifts, sp.render(drifts)


def test_every_close_reason_maps_to_a_close_code_of_4_4() -> None:
    codes = {int(c) for c, _ in lifecycle.CLOSE_REASONS.values()}
    assert codes <= {int(c) for c in lifecycle.CloseCode}


def test_every_bye_builder_answers_a_reason_alike() -> None:
    hub, disagreements = RevocationHub(), []
    for reason in ("session_revoked", "user_disabled"):
        sent = hub.close_for(reason)[0]["p"]
        built = lifecycle.bye_frame(reason)["p"]
        for key in ("code", "reconnect"):
            if sent[key] != built[key]:
                disagreements.append(f"{reason}.{key}: bye_frame {built[key]}, the hub {sent[key]}")
    assert disagreements == []


# --- 3.4 layout, 3.1 frame types, 4.3 settings, 2.2 subprotocols --------------------------------


def test_3_4_tables_and_sizes_are_the_declared_layout() -> None:
    drifts = sp.layout_drifts()
    assert not drifts, sp.render(drifts)


def test_3_1_frame_types_are_the_envelope_enum_and_each_has_a_handler_or_a_builder() -> None:
    drifts = sp.frame_type_drifts()
    assert not drifts, sp.render(drifts)


def test_4_3_settings_are_the_defaults_and_bounds_of_settings() -> None:
    names = set(sp.documented_settings())
    assert {"AUTH_TIMEOUT_S", "MAX_INBOUND_FRAME_BYTES", "QUEUE_BYTES", "QUEUE_FRAMES"} <= names
    assert len(names) == 9, names  # a reworded paragraph must not parse as fewer settings
    drifts = sp.settings_drifts()
    assert not drifts, sp.render(drifts)


def test_2_2_subprotocols_are_the_servers_in_its_order() -> None:
    drifts = sp.subprotocol_drifts()
    assert not drifts, sp.render(drifts)


def test_a_changed_setting_default_fails_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    from candleviewer.settings import Settings

    field: Any = Settings.model_fields["ws_queue_frames"]
    monkeypatch.setattr(field, "default", 1999)
    assert [(d.key, d.doc, d.runtime) for d in sp.settings_drifts()] == [
        ("QUEUE_FRAMES.default", 2000, 1999)
    ]


# --- 6 topic catalogue: a topic is registered together with its row (C-6.1) ---------------------


def _topic_tables() -> tuple[list[list[str]], list[list[str]], str]:
    public = _doc.between(*sp.PUBLIC_6_1)
    private = _doc.between(*sp.PRIVATE_6_2)
    return _doc.table(public), _doc.table(private), _doc.paragraph(public, "**As built (#2823).**")


def _new_topic_row(public: list[list[str]]) -> list[str]:
    trades = next(r for r in public if r[0] == "`trades.{symbol}`")
    return ["`fills.{symbol}`", *trades[1:]]


def test_a_new_topic_with_its_doc_row_passes_parity() -> None:
    public, private, as_built = _topic_tables()
    families = {**FAMILIES, "fills": dataclasses.replace(FAMILIES["trades"], family="fills")}
    problems = sp.topic_table_problems(
        [*public, _new_topic_row(public)], private, families, as_built
    )
    assert problems == []


def test_a_new_topic_without_its_doc_row_fails_parity() -> None:
    public, private, as_built = _topic_tables()
    families = {**FAMILIES, "fills": dataclasses.replace(FAMILIES["trades"], family="fills")}
    problems = sp.topic_table_problems(public, private, families, as_built)
    assert problems == ["fills.{symbol}: not in the doc tables"]


def test_a_doc_row_with_no_registry_row_fails_parity() -> None:
    public, private, as_built = _topic_tables()
    problems = sp.topic_table_problems(
        [*public, _new_topic_row(public)], private, FAMILIES, as_built
    )
    assert problems == ["fills.{symbol}: not in the registry"]
