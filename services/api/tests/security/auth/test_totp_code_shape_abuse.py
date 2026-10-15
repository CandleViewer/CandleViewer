"""E09 abuse case for #2605: a TOTP code written in non-ASCII digits, at each HTTP entry point that
takes an unvalidated one, through the real `create_app()` routers and services.

`str.isdigit()` admits other scripts' digits and `hmac.compare_digest(str, str)` raises `TypeError`
on non-ASCII text, so these routes answered 500 (the harness client does not re-raise server
exceptions). The refusal must be the one any wrong code gets: same response, attempt counted.
"""

from __future__ import annotations

from candleviewer.auth.generated_permissions import Permission
from tests.unit.auth.totp_code_cases import ARABIC_INDIC_CODE

from ._stack import PW, Stack
from .test_invite_http_abuse import _begin, _invite, _owner, _seed


def _wrong_ascii_code(stack: Stack, seed: bytes) -> str:
    """Six ASCII digits that are none of the codes the authenticator can show right now."""
    valid = {stack.code(seed, offset) for offset in (-1, 0, 1)}
    return next(code for code in (f"{n:06d}" for n in range(len(valid) + 1)) if code not in valid)


def test_invite_confirm_refuses_a_non_ascii_digit_code_like_any_wrong_code(stack: Stack) -> None:
    token = _invite(stack, _owner(stack))
    start = _begin(stack, token)
    seed, method_id = _seed(start), start.json()["method_id"]
    url = f"/invites/{token}/confirm"

    wrong = stack.client.post(
        url, json={"method_id": method_id, "code": _wrong_ascii_code(stack, seed)}
    )
    odd = stack.client.post(url, json={"method_id": method_id, "code": ARABIC_INDIC_CODE})

    assert (wrong.status_code, wrong.json()["code"]) == (422, "invalid_code"), wrong.text
    assert (odd.status_code, odd.json()) == (wrong.status_code, wrong.json())  # no oracle
    rejected = stack.audit.of("users.invite_rejected")
    assert [r["reason"] for r in rejected] == ["enrollment_invalid"] * 2
    # Nothing was consumed or confirmed by either refusal: the real code still activates.
    done = stack.client.post(url, json={"method_id": method_id, "code": stack.code(seed)})
    assert (done.status_code, done.json()["status"]) == (200, "active"), done.text


def test_invite_confirm_counts_non_ascii_digit_codes_toward_the_address_limit(stack: Stack) -> None:
    token = _invite(stack, _owner(stack))
    start = _begin(stack, token)
    url = f"/invites/{token}/confirm"
    body = {"method_id": start.json()["method_id"], "code": ARABIC_INDIC_CODE}

    statuses = [stack.client.post(url, json=body).status_code for _ in range(10)]

    assert set(statuses) == {422}
    assert stack.client.post(url, json=body).status_code == 429  # the tenth failure tripped it


def test_step_up_refuses_a_non_ascii_digit_code_like_a_wrong_one_and_counts_a_strike(
    stack: Stack,
) -> None:
    headers, _ = stack.principal("owner", "owner", Permission.USERS_WRITE)
    body = {"code": ARABIC_INDIC_CODE, "password": PW, "action_class": "users"}

    refused = stack.client.post("/auth/step-up", headers=headers, json=body)

    assert (refused.status_code, refused.json()["code"]) == (401, "mfa_invalid"), refused.text
    assert refused.json()["failures_remaining"] == 2  # one strike of three, as for a wrong code
