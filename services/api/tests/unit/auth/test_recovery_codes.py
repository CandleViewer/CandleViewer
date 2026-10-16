"""Unit tests for `candleviewer.auth.recovery_codes`, E09-S02.

PR #1618 security review, blocking 1: >=128-bit codes + keyed (HMAC) hash.
"""

from __future__ import annotations

import hashlib
import math
import re

import pytest

from candleviewer.auth import recovery_codes as recovery_codes_module
from candleviewer.auth.recovery_codes import (
    CODE_LENGTH,
    ENTROPY_BITS,
    RECOVERY_CODE_COUNT,
    generate_recovery_code,
    generate_recovery_codes,
    hash_recovery_code,
    normalize_recovery_code,
    recovery_code_matches,
)

_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_RE = re.compile(rf"^[{_ALPHABET}]{{4}}(-[{_ALPHABET}]{{4}}){{6}}$")
_KEY = b"k" * 32
_OTHER_KEY = b"o" * 32


def test_generate_recovery_code_matches_grouped_unambiguous_shape() -> None:
    code = generate_recovery_code()
    assert _CODE_RE.match(code)
    for banned in "0O1L":
        assert banned not in code


def test_recovery_code_entropy_is_at_least_128_bits() -> None:
    assert len(_ALPHABET) ** CODE_LENGTH >= 2**128
    assert ENTROPY_BITS >= 128
    assert math.isclose(ENTROPY_BITS, CODE_LENGTH * math.log2(31))
    assert len(normalize_recovery_code(generate_recovery_code())) == CODE_LENGTH


def test_generate_recovery_codes_returns_ten_unique_codes_by_default() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == RECOVERY_CODE_COUNT == 10
    assert len(set(codes)) == len(codes)


def test_generate_recovery_codes_respects_count() -> None:
    assert len(generate_recovery_codes(count=3)) == 3


def test_normalize_recovery_code_is_case_and_separator_insensitive() -> None:
    assert normalize_recovery_code("7F2A-91BC-4DE0") == "7F2A91BC4DE0"
    assert normalize_recovery_code("7f2a 91bc 4de0") == "7F2A91BC4DE0"


def test_hash_recovery_code_is_stable_across_equivalent_input_forms() -> None:
    code = generate_recovery_code()
    assert hash_recovery_code(code, key=_KEY) == hash_recovery_code(
        code.lower().replace("-", " "), key=_KEY
    )


def test_hash_recovery_code_is_not_plain_sha256() -> None:
    code = generate_recovery_code()
    stored = hash_recovery_code(code, key=_KEY)
    assert len(stored) == 64
    assert stored != hashlib.sha256(normalize_recovery_code(code).encode()).hexdigest()
    assert stored != hashlib.sha256(code.encode()).hexdigest()


def test_hash_recovery_code_depends_on_key() -> None:
    code = generate_recovery_code()
    assert hash_recovery_code(code, key=_KEY) != hash_recovery_code(code, key=_OTHER_KEY)


def test_hash_recovery_code_rejects_short_key() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        hash_recovery_code("AAAA", key=b"short")


def test_recovery_code_matches_accepts_right_code_rejects_wrong() -> None:
    code, other = generate_recovery_codes(count=2)
    stored = hash_recovery_code(code, key=_KEY)
    assert recovery_code_matches(code, stored, key=_KEY) is True
    assert recovery_code_matches(other, stored, key=_KEY) is False


def test_recovery_code_cannot_be_verified_without_the_key() -> None:
    code = generate_recovery_code()
    stored = hash_recovery_code(code, key=_KEY)
    assert recovery_code_matches(code, stored, key=_OTHER_KEY) is False


def test_recovery_codes_module_defines_no_remaining_codes_threshold() -> None:
    """#2296: re-enrolment after a recovery sign-in is unconditional (E09-S02
    "Recovery code use forces re-enrolment", US-ONB-003), so this module must
    not carry a "low codes" threshold that reads like a gate nothing enforces."""
    assert not hasattr(recovery_codes_module, "LOW_CODE_THRESHOLD")
