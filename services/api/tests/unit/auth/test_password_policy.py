"""SR-028 password policy (#2330, #2110 BQ-222 / BQ-223 / BQ-234; `04` Sec.6.3.1): the one module a
password change and invite redemption share. Pure functions: no I/O but the committed list."""

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.auth import password_policy as pp
from candleviewer.auth.errors import PasswordPolicyViolation
from candleviewer.auth.invite_service import check_password_policy

_USER, _EMAIL = "annie", "ann@example.com"
GOOD = "correct horse battery staple"
_LISTED = "passwordpassword"  # on the committed seed list


def _check(pw: str, breached: frozenset[str] | None = None) -> pp.PolicyVerdict | None:
    return pp.check(pw, username=_USER, email=_EMAIL, breached=breached)


def _rule(pw: str) -> pp.PolicyRule | None:
    verdict = _check(pw)
    return None if verdict is None else verdict.rule


def test_a_good_password_passes_every_rule() -> None:
    assert _check(GOOD) is None


@given(st.integers(min_value=0, max_value=pp.MIN_LENGTH - 1))
def test_fewer_than_14_code_points_is_password_policy_min_length(n: int) -> None:
    """#2330 ruling: `24`'s 14 is the contract, in code points (a combining mark counts)."""
    short = ("Zq7!kM2#" * 2)[:n]
    assert _check(short) == pp.PolicyVerdict(pp.PolicyCode.POLICY, pp.PolicyRule.MIN_LENGTH)


def test_length_is_counted_in_code_points_not_bytes() -> None:
    thirteen = "ü" * 6 + "Zq7!kM2"  # 13 code points, 19 UTF-8 bytes
    assert len(thirteen) == 13
    assert _rule(thirteen) is pp.PolicyRule.MIN_LENGTH
    assert _rule(thirteen + "w") is None


def test_over_512_code_points_is_max_length() -> None:
    assert _rule("Zq7!" * 129) is pp.PolicyRule.MAX_LENGTH


@pytest.mark.parametrize("variant", [_LISTED, _LISTED.upper(), "PassWordPassWord"])
def test_a_listed_password_is_breached_whatever_its_case(variant: str) -> None:
    assert _check(variant) == pp.PolicyVerdict(pp.PolicyCode.BREACHED, pp.PolicyRule.BREACHED)


def test_the_list_key_is_nfc_lower_cased_sha1() -> None:
    decomposed = unicodedata.normalize("NFD", "Ünïcødé-pässwörd")
    expected = hashlib.sha1(
        unicodedata.normalize("NFC", decomposed).lower().encode(), usedforsecurity=False
    ).hexdigest()
    assert pp.digest(decomposed) == expected == pp.digest("ünïcødé-pässwörd")
    assert _check(decomposed, breached=frozenset({expected})) is not None


def test_fewer_than_4_distinct_characters_is_a_simple_pattern() -> None:
    verdict = _check("abcabcabcabcabc")
    assert verdict == pp.PolicyVerdict(pp.PolicyCode.BREACHED, pp.PolicyRule.SIMPLE_PATTERN)


@pytest.mark.parametrize("pw", ["my-ANNIE-password-1", "secret-ann-x9-long!"])
def test_containing_the_username_or_email_local_part_is_password_policy(pw: str) -> None:
    verdict = _check(pw)
    assert verdict == pp.PolicyVerdict(pp.PolicyCode.POLICY, pp.PolicyRule.CONTAINS_IDENTITY)


def test_an_identity_part_in_decomposed_form_still_matches_the_normalised_password() -> None:
    """The identity parts are normalised as the password is (NFC, lower-cased)."""
    decomposed = "Jose\u0301"  # "José" with a combining acute accent
    verdict = pp.check("my-jos\u00e9-is-long-9", username=decomposed, email="x@example.com")
    assert verdict == pp.PolicyVerdict(pp.PolicyCode.POLICY, pp.PolicyRule.CONTAINS_IDENTITY)


def test_an_identity_part_shorter_than_3_is_not_looked_for() -> None:
    assert pp.check("xy-and-more-words-9", username="xy", email="xy@example.com") is None


def test_each_refusal_detail_is_the_04_sentence_and_names_no_value() -> None:
    doc = (Path(__file__).resolve().parents[5] / "docs/plan/04-security-program.md").read_text()
    section = doc.split("#### 6.3.1 ", 1)[1].split("\n### ", 1)[0]
    for rule in (pp.PolicyRule.MIN_LENGTH, pp.PolicyRule.CONTAINS_IDENTITY, pp.PolicyRule.BREACHED):
        assert pp.DETAILS[rule] in section, rule


def test_the_committed_list_parses_and_names_its_generator() -> None:
    text = pp.BREACHED_LIST_PATH.read_text(encoding="utf-8")
    assert "build_breached_passwords.py" in text
    assert pp.digest(_LISTED) in pp.breached_list()


@pytest.mark.parametrize("line", ["xyz", "A" * 40, "0" * 39])
def test_a_damaged_list_fails_loudly(line: str) -> None:
    with pytest.raises(ValueError, match="line 2"):
        pp.parse_breached_list(f"# header\n{line}\n")


@pytest.mark.parametrize(
    ("pw", "message"),
    [
        ("Zq7!kM2#aa", "Password must be at least 14 characters"),
        (_LISTED, "Password is too easy to guess"),
        ("annie-annie-annie", "Password must not contain your username or email"),
    ],
)
def test_invite_redemption_shares_the_module_with_its_own_messages(pw: str, message: str) -> None:
    """BQ-234: one implementation of the rules; invite keeps its `password_policy` messages."""
    with pytest.raises(PasswordPolicyViolation) as refused:
        check_password_policy(pw, username=_USER, email=_EMAIL)
    assert refused.value.reason == message
    check_password_policy(GOOD, username=_USER, email=_EMAIL)
