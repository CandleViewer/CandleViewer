"""SR-188 (#3125): `cv_ws_system_frames_withheld_total{reason}` counts the `system` frames a socket
is not given for a reason other than its role's cut (`23-ws-protocol.md` §15.9): a `kind` outside
§15.9, which reaches nobody, and a kill switch without its state, which only the Owner receives (so
a producer that sends either shows up here), a socket with no principal, and a principal with none
of the three roles. A field cut from a frame, and a frame its role is not meant to receive (a
`feature_flags` frame with no key a Manager or Viewer may learn, E42-T03), are the contract and
count nothing.

`push_system` runs on a bare `_Connection`. The counter is module-global, so each test reads the
difference it made, never a total. That its series exist from process start is pinned in
`test_alerted_series_bound.py`, which asks a fresh interpreter."""

from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import WebSocket
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.metrics import WITHHELD_REASONS, cv_ws_system_frames_withheld_total
from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws.system_filter import FlagVisible, system_view, withheld_reason
from tests.unit.ws.test_system_filter import (
    _FLAG_FRAME,
    BODIES,
    DENY_ALL,
    MANAGER,
    OWNER,
    SAMPLES,
    VIEWER,
    _visible,
)

NAME = "cv_ws_system_frames_withheld_total"
ARCH = Path(__file__).resolve().parents[5] / "docs" / "plan" / "20-architecture.md"
NOTICE, FLAGS = SAMPLES["notice"][0], SAMPLES["feature_flags"][0]
NO_STATE = {"kind": "kill_switch", "severity": "critical"}  # a kill switch frame is its state
NO_STATES = [
    NO_STATE,
    {"kind": "kill_switch", "kill_switch": None},
    {"kind": "kill_switch", "kill_switch": []},
]
TICK = {"kind": "tick", "message": "not a kind of §15.9"}
WHOS = [None, OWNER, MANAGER, VIEWER, DENY_ALL]
_KEYS: tuple[Any, ...] = ({"ui.mgr": 1}, {"ops.owner": 1}, {7: 1}, {}, ["ui.both"], None)
#: `feature_flags` frames (§15.9, E42-T03): keys each role may learn, a key for Managers alone, and
#: no key a Manager or Viewer may learn, down to no flag map at all.
FLAG_FRAMES = [
    _FLAG_FRAME,
    *({"kind": "feature_flags", "feature_flags": keys} for keys in _KEYS),
    {"kind": "feature_flags"},
]


def _conn(who: PrincipalSnapshot | None, flag_visible: FlagVisible | None = None) -> _Connection:
    conn = _Connection(
        cast(WebSocket, None),  # `push_system` queues the frame; the writer is not running
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: 0,
        auth_timeout_s=10.0,
        flag_visible=flag_visible,
    )
    conn.authz = None if who is None else ConnectionAuthz(who)
    return conn


def _counts() -> dict[str, float]:
    (family,) = cv_ws_system_frames_withheld_total.collect()
    return {s.labels["reason"]: s.value for s in family.samples if s.name == NAME}


def _since(before: dict[str, float]) -> dict[str, float]:
    after = _counts()
    return {
        reason: n - before.get(reason, 0) for reason, n in after.items() if n != before.get(reason)
    }


@pytest.mark.parametrize(
    ("body", "who", "reason"),
    [
        (TICK, OWNER, "unknown_kind"),  # nobody receives it, the Owner included
        (TICK, None, "unknown_kind"),  # the frame is judged before the socket
        ({"kind": 7}, VIEWER, "unknown_kind"),
        ({"message": "no kind"}, MANAGER, "unknown_kind"),
        (["notice"], DENY_ALL, "unknown_kind"),
        *((state, who, "invalid_body") for state in NO_STATES for who in (MANAGER, VIEWER, None)),
        (NO_STATE, DENY_ALL, "invalid_body"),  # the frame is judged before the socket
        (NOTICE, None, "no_principal"),
        (NOTICE, DENY_ALL, "no_role"),
        (FLAGS, DENY_ALL, "no_role"),
    ],
)
def test_withheld_reason_names_the_frame_fault_or_the_socket_that_gets_nothing(
    body: Any, who: PrincipalSnapshot | None, reason: str
) -> None:
    assert withheld_reason(body, who) == reason


def _not_meant(body: Any, who: PrincipalSnapshot | None, visible: FlagVisible | None) -> bool:
    """A flag frame with no key a Manager or Viewer may learn (§15.9, E42-T03), worked out here
    apart from the filter."""
    if who is None or who not in (MANAGER, VIEWER) or not isinstance(body, dict):
        return False
    if body.get("kind") != "feature_flags":
        return False
    flags = body.get("feature_flags")
    if visible is None or not isinstance(flags, dict):
        return True  # no predicate (none wired) or no flag map: no key to learn
    return not any(isinstance(key, str) and visible(key, who.roles) for key in flags)


def _agree(body: Any, who: PrincipalSnapshot | None, visible: FlagVisible | None) -> None:
    """The two decide apart, so a new way to give nothing must come with its reason: a frame the
    socket is given has none, and one it is not given has one, unless its role is not meant to
    receive it (`_not_meant`): then it is given nothing and has no reason either."""
    view = system_view(body, who, flag_visible=visible)
    reason, case = withheld_reason(body, who), (body, WHOS.index(who), visible is None)
    if _not_meant(body, who, visible):
        assert (view, reason) == (None, None), case
    else:
        assert (view is None) == (reason is not None), (*case, reason)


def test_system_view_and_withheld_reason_agree_on_what_is_withheld() -> None:
    bodies: list[Any] = [
        *(body for body, _ in SAMPLES.values()),
        *NO_STATES,
        *FLAG_FRAMES,
        TICK,
        {"kind": 7},
        ["notice"],
        None,
    ]
    for body, who, visible in product(bodies, WHOS, (None, _visible)):
        _agree(body, who, visible)


@settings(max_examples=200, deadline=None)
@example(body={"kind": "health", "components": []}, who=MANAGER, visible=None)
@example(body={"kind": "degraded_data", "affected_symbols": []}, who=VIEWER, visible=None)
@example(body={"kind": "connection_quality", "applied": {}}, who=MANAGER, visible=None)
@example(body={"kind": "exchange_state", "exchange": {"uid": "1"}}, who=VIEWER, visible=None)
@example(body={"kind": "health", "components": [1]}, who=MANAGER, visible=None)
@example(body={"kind": "connection_quality", "applied": {"uid": "x"}}, who=VIEWER, visible=None)
@given(body=BODIES, who=st.sampled_from(WHOS), visible=st.sampled_from([None, _visible]))
def test_system_view_and_withheld_reason_agree_for_every_drawn_body(
    body: Any, who: PrincipalSnapshot | None, visible: FlagVisible | None
) -> None:
    """The same assertion over drawn bodies: a drawn shape that is given nothing, with no reason,
    fails. The draws reach a shape by chance, so the examples name what they reach on chance alone:
    an empty `components`, `affected_symbols` or `applied`, and an `exchange`, `components` or
    `applied` the cut leaves empty (it holds only what a Manager or Viewer may not learn)."""
    _agree(body, who, visible)


@pytest.mark.parametrize(
    ("body", "who", "reason"),
    [
        (TICK, OWNER, "unknown_kind"),
        (NO_STATE, MANAGER, "invalid_body"),
        (NOTICE, None, "no_principal"),
        (NOTICE, DENY_ALL, "no_role"),
    ],
)
def test_push_system_counts_a_frame_it_leaves_out_once_under_its_reason(
    body: Any, who: PrincipalSnapshot | None, reason: str
) -> None:
    before = _counts()
    _conn(who).push_system(body)
    assert _since(before) == {reason: 1}


@pytest.mark.parametrize(
    ("body", "who"), [(NOTICE, OWNER), (NOTICE, VIEWER), (FLAGS, MANAGER), (NO_STATE, OWNER)]
)
def test_push_system_counts_nothing_for_a_frame_it_queues_or_its_role_is_not_meant_to_get(
    body: Any, who: PrincipalSnapshot
) -> None:
    before = _counts()
    _conn(who).push_system(body)
    assert _since(before) == {}


@pytest.mark.parametrize("visible", [None, _visible], ids=["no-predicate", "predicate"])
@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
@pytest.mark.parametrize("body", [FLAGS, *FLAG_FRAMES])
def test_push_system_counts_no_flag_frame_with_the_predicate_wired_or_not(
    body: Any, who: PrincipalSnapshot, visible: FlagVisible | None
) -> None:
    """`app.py` always wires the registry's predicate: a flag frame is queued when the role may
    learn a key of it and left out when it may learn none, and neither is counted (E42-T03)."""
    conn, before = _conn(who, visible), _counts()
    conn.push_system(body)
    assert _since(before) == {}
    assert conn.outbound.qsize() == (0 if _not_meant(body, who, visible) else 1)


def test_the_label_never_carries_frame_content() -> None:
    conn = _conn(OWNER)
    for kind in ("x" * 5000, "kill_switch'; DROP", "ünï"):
        conn.push_system({"kind": kind, "message": "free text"})
    assert set(_counts()) == {"unknown_kind", "invalid_body", "no_principal", "no_role"}


def test_the_counter_is_catalogued_as_a_bounded_exported_counter() -> None:
    (spec,) = [s for s in CATALOGUE if s.name == NAME]
    assert (spec.kind, spec.labels, spec.status, spec.exported) == (
        "counter",
        ("reason",),
        "live",
        True,
    )
    assert spec.max_series == len(WITHHELD_REASONS)


def test_the_help_and_the_ops_row_say_a_flag_frame_left_with_no_key_is_not_counted() -> None:
    """What an operator reads: a Manager's or Viewer's `feature_flags` frame left with no key it
    may learn is the contract, not a fault to chase (E42-T03)."""
    (spec,) = [s for s in CATALOGUE if s.name == NAME]
    (row,) = [
        line
        for line in ARCH.read_text(encoding="utf-8").splitlines()
        if line.startswith("| Gateway |") and f"`{NAME}" in line
    ]
    for text in (spec.help, row.replace("`", "")):
        assert "Viewer's feature_flags frame left with no key it may learn is the contract" in text
        assert "and is not counted" in text


def test_section_15_9_names_the_counter_of_a_frame_it_leaves_out() -> None:
    assert f"`{NAME}` (20 §12.1)" in ARCH.with_name("23-ws-protocol.md").read_text(encoding="utf-8")
