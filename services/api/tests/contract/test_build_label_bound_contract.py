"""#306 (E10-S04), contract first for slice 10b: the build label is bounded as the client keeps it.

The web client keeps a `welcome.server_version` of 1 to 32 printable ASCII characters with no space
at either end and refuses any other (slice 10a), so another label would turn SCR-157 off without a
trace. `23` §13.3's `welcome.server_version` and `22`'s `BuildInfo.version` and
`HealthReport.version`, which carry the same `CV_VERSION`, now state that predicate;
`hello.client_version` has the same 32-character bound. The server refuses to start with a
`CV_VERSION` outside it (`Settings.version`), so its bound runs the same rows.

A label that ends in a line feed is refused by the client and by every carrier that reads the
pattern whole: the generated models (pydantic's Rust regex) and the server's bound (`fullmatch`).
The harness's `_validator` applies `pattern` with Python's `re.search`, whose `$` also matches
before a final line feed, so it cannot see this class: the `welcome` rows read the pattern with
`re.fullmatch` instead, as `ws/test_ws_trailing_newline.py` asserts apart from the harness."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.api._generated.openapi_models import BuildInfo, HealthReport
from candleviewer.settings import _BUILD_LABEL_MAX_LENGTH, _BUILD_LABEL_RE, Settings
from candleviewer.ws.lifecycle import welcome_payload
from tests.contract.ws._harness import SCHEMAS, _validator

BOUND = 32
BUILT_AT = datetime(2026, 10, 29, tzinfo=UTC)
#: Labels the client keeps: printable ASCII, 1 to 32 characters, no space at either end.
KEPT = [
    pytest.param("0.1.0", id="default"),
    pytest.param("1.4.3-rc.2+build.5", id="semver-build"),
    pytest.param("v" * BOUND, id="exactly-the-bound"),
    pytest.param("1 0", id="inner-space"),
    pytest.param("~", id="one-character"),
    pytest.param("! ~~", id="class-edges-first-and-inside"),
    pytest.param("~ !", id="class-edges-last"),
]
#: Labels the client refuses, so the contract refuses them too.
REFUSED = [
    pytest.param("v" * (BOUND + 1), id="over-the-bound"),
    pytest.param("", id="empty"),
    pytest.param(" 1.0", id="leading-space"),
    pytest.param("1.0 ", id="trailing-space"),
    pytest.param("1.\x1f0", id="control-inside"),
    pytest.param("1.0\x7f", id="delete-at-the-end"),
    pytest.param("1.\x7f0", id="delete-inside"),
    pytest.param("1.0-é", id="not-ascii"),
]
#: Refused by the client and every carrier that reads the pattern whole; `_validator` admits them.
LINE_FEED = [
    pytest.param("1.0\n", id="line-feed-last"),
    pytest.param("1\n", id="one-character-and-a-line-feed"),
]
WELCOME_LABEL = SCHEMAS["cv://ws/v1/welcome.schema.json"]["properties"]["server_version"]


def _welcome_errors(server_version: str) -> list[str]:
    payload: dict[str, Any] = welcome_payload(
        encoding="json",
        server_version=server_version,
        connection_id="ws_1",
        server_time_ms=1,
        client_clock_ms=None,
        features={},
    )
    return [e.message for e in _validator("cv://ws/v1/welcome.schema.json").iter_errors(payload)]


def test_contract_welcome_server_version_has_the_hello_client_version_bound() -> None:
    welcome = SCHEMAS["cv://ws/v1/welcome.schema.json"]["properties"]
    hello = SCHEMAS["cv://ws/v1/hello.schema.json"]["properties"]
    assert welcome["server_version"]["maxLength"] == hello["client_version"]["maxLength"] == BOUND


@pytest.mark.parametrize("label", KEPT)
def test_contract_welcome_with_a_label_the_client_keeps_validates(label: str) -> None:
    assert _welcome_errors(label) == []


@pytest.mark.parametrize("label", REFUSED)
def test_contract_welcome_with_a_label_the_client_refuses_fails_validation(label: str) -> None:
    assert _welcome_errors(label)


@pytest.mark.parametrize("label", KEPT)
def test_contract_build_info_version_admits_a_label_the_client_keeps(label: str) -> None:
    assert BuildInfo(version=label, commit="c", built_at=BUILT_AT).version == label


@pytest.mark.parametrize("label", LINE_FEED)
def test_contract_welcome_pattern_read_whole_refuses_a_label_ending_in_a_line_feed(
    label: str,
) -> None:
    assert re.fullmatch(WELCOME_LABEL["pattern"], label) is None


@pytest.mark.parametrize("label", [*REFUSED, *LINE_FEED])
def test_contract_build_info_version_refuses_a_label_the_client_refuses(label: str) -> None:
    with pytest.raises(ValidationError):
        BuildInfo(version=label, commit="c", built_at=BUILT_AT)


@pytest.mark.parametrize("label", KEPT)
def test_contract_health_report_version_admits_a_label_the_client_keeps(label: str) -> None:
    assert HealthReport(version=label).version == label


@pytest.mark.parametrize("label", [*REFUSED, *LINE_FEED])
def test_contract_health_report_version_refuses_a_label_the_client_refuses(label: str) -> None:
    with pytest.raises(ValidationError):
        HealthReport(version=label)


def test_contract_health_report_version_stays_optional() -> None:
    assert HealthReport().version is None


def test_contract_server_bound_is_the_welcome_pattern_and_length() -> None:
    assert (_BUILD_LABEL_RE.pattern, _BUILD_LABEL_MAX_LENGTH) == (
        WELCOME_LABEL["pattern"],
        WELCOME_LABEL["maxLength"],
    )


@pytest.mark.parametrize("label", KEPT)
def test_contract_server_bound_admits_a_label_the_client_keeps(label: str) -> None:
    assert Settings(version=label).version == label


@pytest.mark.parametrize("label", [*REFUSED, *LINE_FEED])
def test_contract_server_bound_refuses_a_label_the_client_refuses(label: str) -> None:
    with pytest.raises(ValidationError) as refused:
        Settings(version=label)
    assert [e["loc"] for e in refused.value.errors()] == [("version",)]
