"""`create_app` refuses to boot with a flag that gates a security control (#3438; E42 threat model
AC-ADM-13, AD-E03, SR-E42-07; C-4.14).

`FlagSpec` refuses a denied gate category when it is built, so a catalogue cannot declare one by
accident; the registry rechecks every definition at startup (`test_flag_registry.py`). These tests
pin that recheck where it matters: a definition smuggled past its own check into the catalogue the
app composes still stops `create_app`, so no app starts with a flag that could switch a control off.
"""

from __future__ import annotations

import dataclasses

import pytest

from candleviewer.admin.flags import (
    Category,
    FlagKind,
    FlagSpec,
    UnsafeFlagDefinitionError,
    Visibility,
    catalogue,
)
from candleviewer.admin.flags.registry import DENIED
from candleviewer.app import create_app

_DENIED = [member for member in Category if member in DENIED]


def _smuggled(gates: Category) -> FlagSpec:
    """A copy of a valid definition whose `gates` were set after `FlagSpec`'s own check ran."""
    valid = FlagSpec(
        "ui.sneaky", FlagKind.BOOLEAN, "d", Category.UI_SURFACE, False, Visibility.ALL_ROLES
    )
    spec = object.__new__(FlagSpec)
    for field in dataclasses.fields(FlagSpec):  # every field, so a new one never leaves this stale
        object.__setattr__(spec, field.name, getattr(valid, field.name))
    object.__setattr__(spec, "gates", gates)
    return spec


def test_every_security_category_is_denied() -> None:
    """The eight categories past `KILL_SWITCH` are the ones no flag may gate."""
    assert [str(member.name) for member in _DENIED] == [
        "AUTH",
        "RBAC",
        "AUDIT",
        "NATIVE_STOP_LOSS",
        "RISK_LIMITS",
        "WITHDRAWAL_CHECK",
        "RATE_LIMIT_RESERVE",
        "ENVIRONMENT_ISOLATION",
    ]


@pytest.mark.parametrize("gates", _DENIED, ids=lambda member: str(member.name).lower())
def test_create_app_refuses_a_denied_flag(monkeypatch: pytest.MonkeyPatch, gates: Category) -> None:
    monkeypatch.setattr(catalogue, "FLAGS", (*catalogue.FLAGS, _smuggled(gates)))
    category = str(gates.name).lower()
    with pytest.raises(UnsafeFlagDefinitionError, match=rf"'ui\.sneaky'.*'{category}'.*C-4\.14"):
        create_app()


def test_the_same_definition_with_an_allowed_category_boots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control case: only the denied category stops the app, not the smuggling itself."""
    monkeypatch.setattr(catalogue, "FLAGS", (*catalogue.FLAGS, _smuggled(Category.UI_SURFACE)))
    assert "ui.sneaky" in create_app().state.feature_flags.registry
