"""`ProfilesChanged` (E28-T02, #906 D3a; 24 Sec.9.2): what a committed profile write announces,
its rows and their versions, never a value."""

from __future__ import annotations

import itertools
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from candleviewer.accounts.profile_changes import (
    ANNOUNCE_TIMEOUT_S,
    ProfilesChanged,
    ProfileVersion,
)

_ACCOUNT, _A, _B = uuid4(), uuid4(), uuid4()
_TS = 1_792_486_805_000_000
_ONE = ({"profile_id": _A, "version": 4},)


def _event(**changes: Any) -> ProfilesChanged:
    data = {"exchange_account_id": _ACCOUNT, "change": "updated", "profiles": _ONE, "ts_event": _TS}
    return ProfilesChanged.model_validate({**data, **changes})


def test_a_change_names_rows_and_versions_and_nothing_else() -> None:
    event = _event()
    assert event.model_dump() == {
        "exchange_account_id": _ACCOUNT, "change": "updated", "profiles": _ONE,
        "binding_version": None, "ts_event": _TS,
    }  # fmt: skip
    assert set(ProfileVersion.model_fields) == {"profile_id", "version"}
    for refused in (
        {"name": "Risk 1%"},  # an extra member, a value above all
        {"profiles": ({"profile_id": _A, "version": 4, "leverage": "5"},)},
        {"profiles": ({"profile_id": _A, "version": 0},)},  # a row's version is at least 1
        {"profiles": ()},
        {"change": "relaxed"},
        {"change": "default_moved", "binding_version": 0},  # a binding's version too
    ):
        with pytest.raises(ValidationError):
            _event(**refused)
    with pytest.raises(ValidationError):
        event.change = "deleted"  # frozen, which the test proves
    with pytest.raises(ValidationError):
        event.profiles[0].version = 5  # frozen too
    assert ANNOUNCE_TIMEOUT_S == 0.5


@pytest.mark.parametrize(
    ("change", "rows", "binding"),
    list(
        itertools.product(("created", "updated", "deleted", "default_moved"), (1, 2, 3), (None, 7))
    ),
)
def test_only_a_move_names_two_rows_and_the_bindings_version(
    change: str, rows: int, binding: int | None
) -> None:
    """A move names the binding's new version, and the demoted default before the new one when it
    replaced one; every other write names its one row and no binding."""
    named = tuple({"profile_id": p, "version": 3} for p in (_B, _A, uuid4())[:rows])
    moved = change == "default_moved"
    if moved == (binding is not None) and (rows == 1 or (moved and rows == 2)):
        event = _event(change=change, profiles=named, binding_version=binding)
        assert [p.profile_id for p in event.profiles] == [_B, _A][:rows]  # in the order given
        assert event.binding_version == binding
    else:
        with pytest.raises(ValidationError):
            _event(change=change, profiles=named, binding_version=binding)
