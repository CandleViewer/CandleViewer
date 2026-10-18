"""E42-T03: the `evidence_url` rules of a flag write and the form the `flags.change` audit records:
an `https` URL with a host, printable, at most 2048 characters, without a credential; a refused
credential, a refused URL holding an `@` or a `%40`, or an unparseable URL never reaches the
record raw."""

from __future__ import annotations

import re

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

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
        # A userinfo URL joins its scheme at run time: no secret scanner flags it here (#3482).
        "https" + "://user:secret@github.com/x",
        "https://user@github.com/x",
        "https://github.com/x?tab=1&access_token=secret",
        "https://bucket.s3.amazonaws.com/pt.pdf?X-Amz-Signature=secret",
        "https://github.com/x#token=secret",
        "https://github.com/x?tab=1#access_token=secret",  # a query, then a fragment credential
        "https://idp.example/cb?Code=secret",
        "https://github.com/x?a=1;token=secret",  # `;` separates parameters too
        "https://idp.example/#/cb?code=secret",  # a query nested in the fragment
        "https://idp.example/#!/cb?pwd=secret",
        "https://idp.example/#/cb#code=secret",  # a second `#`
        "https://github.com/x?a=1?sig=secret",  # a second `?`
        "https://h.example/app;jsessionid=secret?x=1",  # a path-matrix parameter (Java)
        "http" + "://user:secret@github.com/" + "a" * 3000,  # before the scheme and the length
    ],
)
def test_a_credential_is_refused_and_recorded_redacted(url: str) -> None:
    assert check_evidence_url(url) == ("credential_in_url", REDACTED_CREDENTIAL)


def test_a_path_parameter_that_names_no_credential_is_accepted_as_is() -> None:
    url = "https://h.example/code=1;v=1"  # only what follows a `;` is a parameter
    assert check_evidence_url(url) == (None, url)


@pytest.mark.parametrize(
    "url",
    [
        "https:user:secret@github.com/x",  # userinfo that `urlsplit` does not see in the netloc
        "https:/user:secret@github.com/x",
        "https:\\\\user:secret@github.com",
        "user:secret@github.com/x",
    ],
)
def test_a_refused_url_holding_an_at_is_recorded_redacted(url: str) -> None:
    assert check_evidence_url(url) == ("https_required", REDACTED_CREDENTIAL)


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        ("https%3A%2F%2Fu%3Asecret%40h.example%2Fx", "https_required"),  # a copied `?next=` value
        ("https://u:" + "s" * 2100 + "%40h.example/x", "string_too_long"),  # past the head
    ],
)
def test_a_refused_url_holding_a_pct40_is_recorded_redacted(url: str, rule: str) -> None:
    assert check_evidence_url(url) == (rule, REDACTED_CREDENTIAL)


def _at(index: int) -> str:
    """A URL whose userinfo password runs up to an `@` at exactly `index`."""
    url = "https://u:" + "s" * (index - len("https://u:")) + "@h.example/x"
    assert url.index("@") == index
    return url


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        pytest.param(_at(EVIDENCE_URL_MAX), "credential_in_url", id="last-of-head"),
        pytest.param(_at(EVIDENCE_URL_MAX + 1), "string_too_long", id="first-past-head"),
        pytest.param(_at(2100), "string_too_long", id="password-too-long-to-parse"),
        pytest.param(_at(100_000), "string_too_long", id="far-past-head"),
        pytest.param("https://github.com/@x/" + "a" * 2100, "string_too_long", id="path-at"),
    ],
)
def test_a_refused_url_is_recorded_redacted_wherever_its_at_lies(url: str, rule: str) -> None:
    assert check_evidence_url(url) == (rule, REDACTED_CREDENTIAL)


_URL_PARTS = ["https", "http", "HTTPS", ":", "/", "//", "\\", "@", "?", "#", "&", "=", ";", "%40"]
_URL_PARTS += [".", "[", "]", " ", "\t", "user", "secret", "token", "sig", "host.example", "x"]


@settings(max_examples=500, deadline=None, derandomize=True)
@example("https://www.npmjs.com/package/@scope/pkg")  # an accepted path `@` is kept
@given(st.lists(st.sampled_from(_URL_PARTS), max_size=14).map("".join))
def test_a_refused_url_is_never_recorded_with_an_at_and_an_accepted_one_is_kept(url: str) -> None:
    rule, audited = check_evidence_url(url)
    assert (audited == url) if rule is None else not re.search("@|%40", audited or "")


_DENIED = ["sig", "code", "auth", "pass", "pwd", "passwd", "pw", "pswd", "sas", "x_amz_credential"]
_SPELLED = ["X-Amz-Credential", "X-Goog-Credential", "AWSAccessKeyId", "tempauth", "rlkey"]
_SPELLED += ["JSESSIONID", "PHPSESSID", "SAMLResponse", "assertion"]


# Names are compared in lower case with letters and digits only, so real spellings match too.
@pytest.mark.parametrize("name", [*_DENIED, *_SPELLED])
def test_every_deny_listed_parameter_name_is_a_credential(name: str) -> None:
    assert re.sub(r"[^a-z0-9]", "", name.lower()) in TOKEN_PARAMS
    assert check_evidence_url(f"https://h.example/x?{name}=secret")[0] == "credential_in_url"


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        ("https://[::1/issues", "https_required"),
        ("https://[::1/x?token=secret", "credential_in_url"),
        ("https://[::1/x#access_token=secret", "credential_in_url"),
        ("https://[::1/user:secret@x", "credential_in_url"),
        ("https://[::1" + "a" * 2100 + "@h.example/x", "credential_in_url"),  # @ past the head
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
