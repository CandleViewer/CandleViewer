"""E42-T03: the `evidence_url` rules of a flag write and the form the `flags.change` audit records:
an `https` URL with a host, printable, at most 2048 characters, without a credential; a refused
credential or an unparseable URL never reaches the record raw."""

from __future__ import annotations

import pytest

from candleviewer.admin.flags.evidence import (
    EVIDENCE_URL_MAX,
    REDACTED_CREDENTIAL,
    REDACTED_UNPARSEABLE,
    TOKEN_PARAMS,
    check_evidence_url,
)


@pytest.mark.parametrize("url", [None, ""])
def test_an_absent_url_breaks_no_rule_and_is_recorded_as_is(url: str | None) -> None:
    assert check_evidence_url(url) == (None, url)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://github.com/basiltt/CandleViewer/issues/412",
        "https:///issues/412",
        "https://github.com/a b",
        "https://github.com/a\x07b",  # not printable
    ],
)
def test_a_url_that_is_not_printable_https_with_a_host_is_refused(url: str) -> None:
    assert check_evidence_url(url) == ("https_required", url)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@github.com/x",
        "https://user@github.com/x",
        "https://github.com/x?tab=1&access_token=secret",
        "https://bucket.s3.amazonaws.com/pt.pdf?X-Amz-Signature=secret",
        "https://github.com/x#token=secret",
        "https://idp.example/cb?Code=secret",
        "https://github.com/x?a=1;token=secret",  # `;` separates parameters too
        "https://idp.example/#/cb?code=secret",  # a query nested in the fragment
        "https://idp.example/#!/cb?pwd=secret",
        "https://idp.example/#/cb#code=secret",  # a second `#`
        "https://github.com/x?a=1?sig=secret",  # a second `?`
        "http://user:secret@github.com/" + "a" * 3000,  # before the scheme and the length
    ],
)
def test_a_credential_is_refused_and_recorded_redacted(url: str) -> None:
    assert check_evidence_url(url) == ("credential_in_url", REDACTED_CREDENTIAL)


@pytest.mark.parametrize(
    "name",
    ["sig", "code", "auth", "pass", "pwd", "passwd", "pw", "pswd", "sas", "x_amz_credential"],
)
def test_every_deny_listed_parameter_name_is_a_credential(name: str) -> None:
    assert name in TOKEN_PARAMS
    assert check_evidence_url(f"https://h.example/x?{name}=secret")[0] == "credential_in_url"


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        ("https://[::1/issues", "https_required"),
        ("https://[::1/x?token=secret", "credential_in_url"),
        ("https://[::1/x#access_token=secret", "credential_in_url"),
        ("https://[::1/user:secret@x", "credential_in_url"),
        ("https://user:secret\uff20host.example/x", "https_required"),  # fails NFKC
        ("https://u\uff20host.example/x?token=secret", "credential_in_url"),
        ("https://u\uff20host.example/x#token=secret", "credential_in_url"),
    ],
)
def test_an_unparseable_url_is_refused_and_never_recorded_raw(url: str, rule: str) -> None:
    assert check_evidence_url(url) == (rule, REDACTED_UNPARSEABLE)


def test_a_url_of_2048_characters_is_valid_and_recorded_as_is() -> None:
    url = "https://github.com/" + "a" * 2029
    assert len(url) == EVIDENCE_URL_MAX and check_evidence_url(url) == (None, url)


def test_only_the_head_of_a_longer_url_is_parsed_and_recorded() -> None:
    url = "https://github.com/" + "a" * 2030 + "?token=secret" + "&p=1" * 100_000
    assert check_evidence_url(url) == ("string_too_long", url[:EVIDENCE_URL_MAX])
