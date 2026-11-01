"""#399: the bars flag's removal. `CV_BARS_ENABLED` is refused at load, so no deployment believes
it turned the bar builders off (C-4.13); the refusal carries no value (C-12.6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.settings import BARS_ENABLED_FLAG_REMOVED, Settings

_MARKER = "cv-399-marker-not-a-secret"


@pytest.mark.parametrize("value", ["true", "false", "1", ""], ids=["true", "false", "one", "empty"])
def test_the_removed_bars_flag_is_refused_with_what_to_do(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("CV_BYBIT_API_KEY", _MARKER)
    monkeypatch.setenv("CV_BARS_ENABLED", value)

    with pytest.raises(ValidationError) as refused:
        Settings()

    (error,) = refused.value.errors()
    assert (error["loc"], error["type"]) == (("bars_enabled",), "value_error")
    assert str(refused.value).count(BARS_ENABLED_FLAG_REMOVED) == 1
    assert "delete the line" in str(refused.value)
    assert _MARKER not in str(refused.value)


def test_the_removed_bars_flag_in_a_dotenv_file_is_refused(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("CV_BARS_ENABLED=false\n", encoding="utf-8")

    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=dotenv)

    assert BARS_ENABLED_FLAG_REMOVED in str(refused.value)


def test_the_removed_bars_flag_holds_no_value_and_is_never_dumped() -> None:
    settings = Settings()

    assert settings.bars_enabled is None
    assert "bars_enabled" not in settings.model_dump()
