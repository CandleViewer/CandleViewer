"""SR-041 token codec (#2090): unit + Hypothesis property tests. Pure, no I/O."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.auth.csrf import (
    MAX_TOKEN_LEN,
    NONCE_BYTES,
    CsrfCodec,
    CsrfVerdict,
    tokens_equal,
)

K1 = b"\x01" * 32
K2 = b"\x02" * 32
sids = st.text(min_size=1, max_size=64)
nonces = st.binary(min_size=NONCE_BYTES, max_size=NONCE_BYTES)


def _fixed(nonce: bytes, key: bytes = K1) -> CsrfCodec:
    """Codec whose nonce source is pinned (the construction-time test seam)."""
    return CsrfCodec(key, token_bytes=lambda n: nonce[:n])


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_token_shape_and_mac_definition_match_the_contract() -> None:
    nonce = bytes(range(32))
    token = _fixed(nonce).issue("sid-1")
    n, m = token.split(".")
    assert n == _b64(nonce)
    msg = struct.pack(">I", 5) + b"sid-1" + nonce  # len(sid) || sid || nonce
    assert m == _b64(hmac.new(K1, msg, hashlib.sha256).digest())
    assert len(token) <= MAX_TOKEN_LEN


def test_fresh_nonces_are_256_bit_and_unique() -> None:
    codec = CsrfCodec(K1)
    tokens = {codec.issue("s") for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(base64.urlsafe_b64decode(t.split(".")[0] + "=")) == 32 for t in tokens)


def test_short_keys_empty_sid_and_bad_nonce_are_rejected() -> None:
    with pytest.raises(ValueError):
        CsrfCodec(b"short")
    with pytest.raises(ValueError):
        CsrfCodec(K1, (b"short",))
    with pytest.raises(ValueError):
        CsrfCodec(K1).issue("")
    with pytest.raises(ValueError):
        CsrfCodec(K1, token_bytes=lambda _n: b"x").issue("s")
    assert CsrfCodec(K1).verify(CsrfCodec(K1).issue("s"), "") is CsrfVerdict.BAD_MAC


def test_key_rotation_previous_key_verifies_but_never_mints() -> None:
    old = CsrfCodec(K1).issue("s")
    rotated = CsrfCodec(K2, (K1,))
    assert rotated.verify(old, "s") is CsrfVerdict.OK
    assert CsrfCodec(K2).verify(old, "s") is CsrfVerdict.WRONG_SESSION  # retired
    assert CsrfCodec(K1).verify(rotated.issue("s"), "s") is CsrfVerdict.WRONG_SESSION


def test_tokens_equal_is_exact_and_rejects_non_ascii() -> None:
    assert tokens_equal("a.b", "a.b")
    assert not tokens_equal("a.b", "a.c")
    assert not tokens_equal("é", "é")


@given(sid=sids, nonce=nonces)
def test_roundtrip_verifies_for_its_own_session(sid: str, nonce: bytes) -> None:
    assert CsrfCodec(K1).verify(_fixed(nonce).issue(sid), sid) is CsrfVerdict.OK


@given(a=sids, b=sids, nonce=nonces)
def test_token_never_verifies_for_another_session(a: str, b: str, nonce: bytes) -> None:
    if a == b:
        return
    token = _fixed(nonce).issue(a)
    assert CsrfCodec(K1).verify(token, b) is CsrfVerdict.WRONG_SESSION


@given(prefix=st.text(min_size=1, max_size=8), rest=st.text(min_size=1, max_size=8), nonce=nonces)
def test_length_prefix_prevents_resplitting_sid_and_nonce(
    prefix: str, rest: str, nonce: bytes
) -> None:
    """(sid=prefix+rest, nonce) and (sid=prefix, nonce'=rest||nonce[..]) never share a MAC."""
    t1 = _fixed(nonce).issue(prefix + rest)
    shifted = (rest.encode() + nonce)[:NONCE_BYTES]
    t2 = _fixed(shifted).issue(prefix)
    assert t1.split(".")[1] != t2.split(".")[1]


@given(sid=sids, nonce=nonces, pos=st.integers(min_value=0), ch=st.sampled_from("AQgw-_09"))
def test_any_single_character_change_is_refused(sid: str, nonce: bytes, pos: int, ch: str) -> None:
    token = _fixed(nonce).issue(sid)
    i = pos % len(token)
    if token[i] in (ch, "."):
        return
    mutated = token[:i] + ch + token[i + 1 :]
    assert CsrfCodec(K1).verify(mutated, sid) is not CsrfVerdict.OK


@given(junk=st.text(max_size=400), sid=sids)
def test_arbitrary_input_never_verifies_and_never_raises(junk: str, sid: str) -> None:
    assert CsrfCodec(K1).verify(junk, sid) is not CsrfVerdict.OK


@given(sid=sids, nonce=nonces)
def test_non_canonical_base64_is_bad_mac(sid: str, nonce: bytes) -> None:
    token = _fixed(nonce).issue(sid)
    assert CsrfCodec(K1).verify(token + "=", sid) is CsrfVerdict.BAD_MAC
    assert CsrfCodec(K1).verify(token.replace(".", ".."), sid) is CsrfVerdict.BAD_MAC


def test_issue_takes_no_caller_chosen_nonce() -> None:
    """Security review #2238: the nonce source is fixed at construction (CSPRNG
    by default); `issue()` has no per-call nonce parameter."""
    import inspect

    assert list(inspect.signature(CsrfCodec.issue).parameters) == ["self", "session_id"]
    import secrets

    default = inspect.signature(CsrfCodec.__init__).parameters["token_bytes"].default
    assert default is secrets.token_bytes
