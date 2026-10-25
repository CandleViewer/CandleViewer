"""Unit (#4535): `redact()` keeps `kek_version` (which KEK enrolled, loaded or re-wrapped) while
every name that can hold KEK or DEK material stays masked. The exemption is a reviewed metadata
name holding a version number only: any other value under it is still replaced, and the set
itself is pinned so adding a name stays a reviewed edit."""

from __future__ import annotations

import json
from typing import Any

import pytest

import candleviewer.audit.redact as redact_module
from candleviewer.audit.redact import REDACTION_MARKER, redact


@pytest.mark.parametrize("key", ["kek_version", "kekVersion", "KEK-VERSION"])
@pytest.mark.parametrize("version", ["1", "12", 1, 7])
def test_kek_version_is_kept_at_the_top_and_nested(key: str, version: Any) -> None:
    state = {"env": "demo", key: version, "nested": {key: version}, "listed": [{key: version}]}
    assert redact(state) == state


@pytest.mark.parametrize(
    "key", ["kek", "kek_handle", "dek", "wrapped_kek", "kek_material", "dek_ref", "kekversions"]
)
def test_kek_and_dek_names_are_still_masked(key: str) -> None:
    assert redact({key: "1"}) == {key: REDACTION_MARKER}


@pytest.mark.parametrize(
    "value",
    ["0", "01", "-1", "1.0", " 1", "1\n", "v1", "deadbeef" * 4, 0, -1, True, 1.0, None,
     {"v": 1}, [1], "1" * 10],
    ids=["zero", "leading-zero", "negative", "float-str", "leading", "newline", "prefixed",
         "material", "int-zero", "int-negative", "bool", "float", "none", "dict", "list", "long"],
)  # fmt: skip
def test_any_other_value_under_kek_version_is_masked(value: Any) -> None:
    assert redact({"kek_version": value}) == {"kek_version": REDACTION_MARKER}


class _Int(int):
    pass


class _Str(str):
    __slots__ = ()


@pytest.mark.parametrize("value", [_Int(3), _Str("3")], ids=["int-subclass", "str-subclass"])
def test_a_subclass_carrying_a_version_is_masked(value: Any) -> None:
    """A wrapper type could carry material; only the exact `int` and `str` types pass."""
    assert redact({"kek_version": value}) == {"kek_version": REDACTION_MARKER}


def test_an_embedded_json_body_keeps_the_version_and_masks_the_key() -> None:
    body = json.dumps({"kek_version": "2", "kek": "material"})
    redacted = redact({"body": body})
    assert redacted is not None
    assert json.loads(redacted["body"]) == {"kek_version": "2", "kek": REDACTION_MARKER}


def test_the_enrolment_fields_keep_the_version_and_the_check_value() -> None:
    """The shape `secrets/_rotation.py` passes with `security.kek_enrolled`."""
    fields = {"actor_kind": "system", "actor_role": "system", "env": "demo"}
    fields |= {"kek_version": "1", "kcv": "a1b2c3"}
    assert redact(fields) == fields


def test_pin_the_metadata_name_set_and_the_version_shape() -> None:
    """A review tripwire: a new name or a wider value shape is a security-reviewed edit."""
    assert redact_module._METADATA_VERSION_NAMES == frozenset({"kekversion"})
    assert redact_module._VERSION_RE.pattern == "[1-9][0-9]{0,8}"
