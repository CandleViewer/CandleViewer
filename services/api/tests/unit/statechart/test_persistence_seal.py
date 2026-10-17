"""The statechart snapshot seal binds the machine identity (CV-C53, C-2.11; #3082).

`seal`/`open_sealed` authenticate the chart, the blob, `machine_hash`, `version` and the
`MachineKey` (kind, entity, env) behind a layout marker, `SEAL_LAYOUT_V`, that is independent of
`SNAPSHOT_V` (the library snapshot floor, CV-C52). An envelope opens only for the key it was sealed
for, and a tag sealed under an earlier input layout never verifies.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from candleviewer.statechart.config import SNAPSHOT_V
from candleviewer.statechart.persistence import (
    SEAL_LAYOUT_V,
    MachineKey,
    Seal,
    SealedSnapshot,
    _mac_input,
    open_sealed,
    seal,
)
from candleviewer.statechart.schema import canonical_json

CHART: dict[str, Any] = {"id": "gold"}
BLOB: dict[str, Any] = {"version": 3}
MACHINE_HASH = "ab" * 32
KEY = MachineKey("gold", "00000000-0000-0000-0000-000000000001", "demo")

#: The v2 input, one length-prefixed part each, in order: layout label, chart, blob,
#: machine_hash, version, then the machine key (kind, entity, env).
GOLDEN_PARTS = [
    b"cv-snapshot-seal-v2",
    b'{"id":"gold"}',
    b'{"version":3}',
    MACHINE_HASH.encode(),
    b"3",
    b"gold",
    b"00000000-0000-0000-0000-000000000001",
    b"demo",
]
#: What each seal layout produces for the fixed inputs above: (sha256 of the framed MAC input,
#: tag under the fixed test key), keyed by `SEAL_LAYOUT_V`. A layout that changes but keeps its
#: number fails on the stale digest; a bumped number without a new entry fails with a KeyError.
GOLDEN: dict[int, tuple[str, str]] = {
    2: (
        "4184b04fd71794ac95fb7b7b49af3ff42bd8c8af2e1fc9457de1258d5e1f439a",
        "3195aa06d3470573f3e1868f192615b24e7e2549ff45e8db61d4b9267b61ccb6",
    ),
}
#: The same fixed inputs sealed by the pre-binding `seal()` (no layout part, no machine key).
LEGACY_TAG = "0180d5fa935f3188aa10585fce9676f36e08e1a8f410b5e355b97f7902eae606"

ONE_PART_DIFFERS = pytest.mark.parametrize(
    "other",
    [
        dataclasses.replace(KEY, env="live"),
        dataclasses.replace(KEY, entity_id="00000000-0000-0000-0000-000000000002"),
        dataclasses.replace(KEY, machine_kind="other"),
    ],
    ids=["env", "entity_id", "machine_kind"],
)


class FakeKeys:
    """`HmacKeys` over fixed test keys, never a real one."""

    def __init__(self) -> None:
        self._ring = {"k1": bytes(range(32))}

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return self._ring[key_id]


def _sealed_for(key: MachineKey, *, claims: MachineKey | None = None) -> SealedSnapshot:
    """An envelope whose tag is sealed for `key` and whose own `key` field says `claims or key`."""
    tag = seal(FakeKeys(), CHART, BLOB, MACHINE_HASH, SNAPSHOT_V, key=key)
    return SealedSnapshot(
        key=claims or key,
        version=SNAPSHOT_V,
        machine_hash=MACHINE_HASH,
        snapshot=BLOB,
        seal=tag,
    )


def _open(envelope: SealedSnapshot, key: MachineKey) -> dict[str, Any]:
    return open_sealed(FakeKeys(), CHART, envelope, key=key, expected_machine_hash=MACHINE_HASH)


def _input(key: MachineKey) -> bytes:
    return _mac_input(key, CHART, BLOB, MACHINE_HASH, 3)


def _unframe(data: bytes) -> list[bytes]:
    """Split 8-byte big-endian length-prefixed parts, independently of `_mac_input`."""
    parts, at = [], 0
    while at < len(data):
        size = int.from_bytes(data[at : at + 8], "big")
        parts.append(data[at + 8 : at + 8 + size])
        at += 8 + size
    assert at == len(data)
    return parts


def _legacy_tag(keys: FakeKeys) -> str:
    """The pre-binding seal: four length-prefixed parts, no layout marker, no machine key."""
    parts = [canonical_json(CHART), canonical_json(BLOB), MACHINE_HASH.encode(), b"3"]
    data = b"".join(len(p).to_bytes(8, "big") + p for p in parts)
    return hmac.new(keys.key("k1"), data, hashlib.sha256).hexdigest()


def test_open_sealed_same_key_returns_the_blob() -> None:
    assert _open(_sealed_for(KEY), KEY) == BLOB


@ONE_PART_DIFFERS
def test_open_sealed_other_key_is_refused_naming_the_seal(other: MachineKey) -> None:
    with pytest.raises(ValueError, match=r"seal .*another machine key.*CV-C53"):
        _open(_sealed_for(KEY), other)


@ONE_PART_DIFFERS
def test_open_sealed_envelope_claiming_other_key_is_refused_although_the_tag_verifies(
    other: MachineKey,
) -> None:
    # The tag verifies for the requested key: only the envelope's own claim differs.
    with pytest.raises(ValueError, match="another machine key"):
        _open(_sealed_for(KEY, claims=other), KEY)


@ONE_PART_DIFFERS
def test_open_sealed_tag_sealed_for_other_key_fails_the_mac(other: MachineKey) -> None:
    # The envelope claims the requested key, so only the MAC can tell it carries another tag.
    relabelled = dataclasses.replace(_sealed_for(other), key=KEY)
    with pytest.raises(ValueError, match="bad HMAC"):
        _open(relabelled, KEY)


def test_legacy_tag_helper_matches_the_pre_binding_seal() -> None:
    assert _legacy_tag(FakeKeys()) == LEGACY_TAG


def test_open_sealed_old_input_layout_is_refused() -> None:
    old = dataclasses.replace(_sealed_for(KEY), seal=Seal(key_id="k1", tag=_legacy_tag(FakeKeys())))
    with pytest.raises(ValueError, match="bad HMAC"):
        _open(old, KEY)


def test_seal_layout_version_matches_the_golden_value() -> None:
    assert SEAL_LAYOUT_V in GOLDEN
    assert GOLDEN_PARTS[0] == f"cv-snapshot-seal-v{SEAL_LAYOUT_V}".encode()


def test_mac_input_parts_match_the_golden_layout() -> None:
    assert _unframe(_input(KEY)) == GOLDEN_PARTS


def test_mac_input_bytes_match_the_golden_digest() -> None:
    digest, _ = GOLDEN[SEAL_LAYOUT_V]
    assert hashlib.sha256(_input(KEY)).hexdigest() == digest


def test_seal_tag_matches_the_golden_value() -> None:
    _, tag = GOLDEN[SEAL_LAYOUT_V]
    sealed = seal(FakeKeys(), CHART, BLOB, MACHINE_HASH, 3, key=KEY)
    assert sealed == Seal(key_id="k1", tag=tag)


def _text(key: MachineKey) -> str:
    return key.machine_kind + key.entity_id + key.env


def _tag(key: MachineKey) -> str:
    return seal(FakeKeys(), CHART, BLOB, MACHINE_HASH, 3, key=key).tag


BYTE_SHIFTED_BETWEEN_PARTS = pytest.mark.parametrize(
    ("a", "b"),
    [
        (MachineKey("a", "bc", "demo"), MachineKey("ab", "c", "demo")),
        (MachineKey("kind", "a", "bc"), MachineKey("kind", "ab", "c")),
    ],
    ids=["kind|entity", "entity|env"],
)


@BYTE_SHIFTED_BETWEEN_PARTS
def test_mac_input_byte_shifted_between_key_parts_differs(a: MachineKey, b: MachineKey) -> None:
    assert _text(a) == _text(b)
    assert _input(a) != _input(b)


@BYTE_SHIFTED_BETWEEN_PARTS
def test_seal_tag_byte_shifted_between_key_parts_differs(a: MachineKey, b: MachineKey) -> None:
    assert _text(a) == _text(b)
    assert _tag(a) != _tag(b)


@st.composite
def _two_splits_of_one_string(draw: st.DrawFn) -> tuple[MachineKey, MachineKey]:
    """Two different (kind, entity, env) keys whose parts concatenate to one and the same string."""
    text = draw(st.text(min_size=1, max_size=8))
    cut = st.integers(min_value=0, max_value=len(text))

    def split() -> MachineKey:
        first, second = sorted((draw(cut), draw(cut)))
        return MachineKey(text[:first], text[first:second], text[second:])

    a, b = split(), split()
    assume(a != b)
    return a, b


@given(_two_splits_of_one_string())
def test_seal_tag_two_splits_of_one_string_differ(keys: tuple[MachineKey, MachineKey]) -> None:
    a, b = keys
    assert _text(a) == _text(b)
    assert _tag(a) != _tag(b)
