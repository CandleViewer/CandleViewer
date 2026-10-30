"""#306 (E10-S04): `CV_VERSION`, the build label `/healthz`, `/readyz` and every `welcome` carry.

A label the web client refuses would turn SCR-157 off without a trace, so a `CV_VERSION` outside
the bound of `22` (`BuildInfo.version`) and `23` §13.3 refuses startup before any module starts:
1 to 32 printable ASCII characters with no space at either end, read whole, so a label that ends
in a line feed is refused too. It is refused, never cut or cleaned. The refusal names the variable
and the rule, never the label. The contract's rows run through the bound in
`tests/contract/test_build_label_bound_contract.py`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings

_ENV = "CV_VERSION"
#: Over the bound, with an escape sequence and a final line feed: what must never reach a log.
_ODD = "cv-306-" + "x" * 40 + "\x1b[2J\n"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.chdir(tmp_path)  # no developer `.env` in the cwd reaches `Settings()`


def test_settings_version_unset_defaults_to_the_package_label() -> None:
    assert Settings().version == "0.1.0"


def test_settings_version_within_the_bound_is_kept_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "1.4.3-rc.2+build.5")

    assert Settings().version == "1.4.3-rc.2+build.5"


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("1.0\n", id="line-feed-last"),
        pytest.param("v" * 33, id="over-the-bound"),
        pytest.param("", id="empty"),
        pytest.param("1.0 ", id="trailing-space"),
    ],
)
def test_settings_version_outside_the_bound_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    monkeypatch.setenv(_ENV, label)

    with pytest.raises(ValidationError) as refused:
        Settings()
    assert [e["loc"] for e in refused.value.errors()] == [("version",)]


def test_settings_version_refusal_names_the_rule_and_never_the_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`hide_input_in_errors` keeps the input out of `str()`, which a startup traceback prints,
    and the message is fixed text: a long or odd label is never echoed into the logs."""
    monkeypatch.setenv(_ENV, _ODD)

    with pytest.raises(ValidationError) as refused:
        Settings()
    rendered = str(refused.value)
    assert "CV_VERSION must be 1 to 32 printable ASCII characters" in rendered
    assert "cv-306-" not in rendered
    assert "\x1b" not in rendered
    assert all("cv-306-" not in e["msg"] for e in refused.value.errors())
