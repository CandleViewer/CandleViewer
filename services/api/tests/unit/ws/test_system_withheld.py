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
from typing import Any, cast

import pytest
from fastapi import WebSocket

from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.metrics import WITHHELD_REASONS, cv_ws_system_frames_withheld_total
from candleviewer.ws.permissions import ConnectionAuthz
from candleviewer.ws.system_filter import FlagVisible, system_view, withheld_reason
from tests.unit.ws.test_system_filter import (
    _FLAG_FRAME,
    DENY_ALL,
    MANAGER,
    OWNER,
    SAMPLES,
    VIEWER,
    _visible,
)

NAME = "cv_ws_system_frames_withheld_total"
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


def _conn(who: PrincipalSnapshot | None) -> _Connection:
    conn = _Connection(
        cast(WebSocket, None),  # `push_system` queues the frame; the writer is not running
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: 0,
        auth_timeout_s=10.0,
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


def test_system_view_and_withheld_reason_agree_on_what_is_withheld() -> None:
    """The two decide apart, so a new way to give nothing must come with its reason: a frame the
    socket is given has none, and one it is not given has one, unless its role is not meant to
    receive it (`_not_meant`): then it is given nothing and has no reason either."""
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
        view = system_view(body, who, flag_visible=visible)
        reason, case = withheld_reason(body, who), (body, WHOS.index(who), visible is None)
        if _not_meant(body, who, visible):
            assert (view, reason) == (None, None), case
        else:
            assert (view is None) == (reason is not None), (*case, reason)


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
