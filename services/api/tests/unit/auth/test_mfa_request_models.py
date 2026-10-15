"""The request models that carry a TOTP code take only six ASCII digits (#2605).

`MfaEnrollConfirmRequest.code` was `min_length=6, max_length=32` with no pattern, so a string of
any script's digits reached `verify_code`; `MfaVerifyRequest.code` has always had an ASCII pattern.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from candleviewer.auth.models import MfaEnrollConfirmRequest, MfaMethodKind, MfaVerifyRequest

from .totp_code_cases import NON_ASCII_DIGIT_CODES

_METHOD_ID = uuid.UUID(int=1)


def test_enroll_confirm_request_accepts_six_ascii_digits() -> None:
    request = MfaEnrollConfirmRequest(method_id=_METHOD_ID, code="012345")
    assert request.code == "012345"


@pytest.mark.parametrize("code", NON_ASCII_DIGIT_CODES)
def test_enroll_confirm_request_rejects_non_ascii_digits(code: str) -> None:
    with pytest.raises(ValidationError):
        MfaEnrollConfirmRequest(method_id=_METHOD_ID, code=code)


@pytest.mark.parametrize(
    "code",
    [
        "",
        "12345",
        "1234567",
        "abcdef",
        " 12345",
        "123456 ",
        "123456\n",
        "12 456",
        "1" * 32,  # inside the old `max_length=32`, and not a TOTP code
    ],
)
def test_enroll_confirm_request_rejects_anything_but_exactly_six_digits(code: str) -> None:
    with pytest.raises(ValidationError):
        MfaEnrollConfirmRequest(method_id=_METHOD_ID, code=code)


@pytest.mark.parametrize("code", NON_ASCII_DIGIT_CODES)
def test_verify_request_keeps_rejecting_non_ascii_digits(code: str) -> None:
    """`POST /auth/mfa/verify` was never exposed to #2605: its pattern is ASCII only. Pin that."""
    with pytest.raises(ValidationError):
        MfaVerifyRequest(mfa_token="t", method=MfaMethodKind.TOTP, code=code)
