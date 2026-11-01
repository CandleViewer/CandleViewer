"""#452 (E12-X02): the bars abuse k6 battery's host guard and its MANUAL status, read without k6.

`tests/load/k6/bars_abuse.js` refuses any target outside loopback before a request is built
(security notes of the ticket: never against staging or live). These pin it statically: the guard's
pattern is the sibling scripts', it is evaluated against loopback and non-loopback targets here
(the pattern uses no syntax Python's `re` reads differently), the refusal comes before the first
request and the session file, no other host is written into the script, and no workflow runs it.
k6 is never executed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
K6 = ROOT / "tests" / "load" / "k6"
SCRIPT = K6 / "bars_abuse.js"
GUARD = re.compile(r"^const LOOPBACK = /(?P<pattern>.+)/;$", re.M)


def _text(path: Path = SCRIPT) -> str:
    return path.read_text(encoding="utf-8")


def _guard(path: Path = SCRIPT) -> re.Pattern[str]:
    found = GUARD.search(_text(path))
    assert found, f"no LOOPBACK guard in {path.name}"
    return re.compile(found["pattern"])


def _base(url: str) -> str:
    """BASE as the script derives it: one trailing slash dropped."""
    return url[:-1] if url.endswith("/") else url


def test_bars_abuse_guard_is_the_sibling_scripts_guard() -> None:
    assert _guard().pattern == _guard(K6 / "ingestion_rest.js").pattern
    assert _guard().pattern == _guard(K6 / "recorder_api.js").pattern


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1", "http://127.0.0.1:8000", "http://localhost:8000/"]
)
def test_bars_abuse_guard_admits_loopback(url: str) -> None:
    assert _guard().fullmatch(_base(url))


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000",
        "http://127.0.0.1.example.com",
        "http://localhost.example.com:80",
        "http://127.0.0.2:8000",
        "http://10.0.0.1:8000",
        "http://[::1]:8000",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000/market",
        "http://staging.internal:8000",
        "",
    ],
)
def test_bars_abuse_guard_refuses_anything_else(url: str) -> None:
    assert not _guard().fullmatch(_base(url))


def test_bars_abuse_refuses_before_any_request_or_secret_is_read() -> None:
    text = _text()
    refusal = text.index("fail(`refusing non-loopback target ${BASE}`)")
    assert text.index("if (!LOOPBACK.test(BASE))") < refusal
    for later in ("open(__ENV.SESSION)", "http.get(", "export const options"):
        assert refusal < text.index(later), later
    assert 'const BASE = (__ENV.BASE_URL || "http://127.0.0.1:8000")' in text


def test_bars_abuse_names_no_other_host_and_prints_no_session() -> None:
    text = _text()
    hosts = set(re.findall(r"https?://[\w.\-\[\]:]+", text))
    assert hosts <= {"http://127.0.0.1:8000"}, hosts
    assert "console." not in text  # the session header value is never logged


def test_bars_abuse_is_manual_no_workflow_runs_it() -> None:
    workflows = (ROOT / ".github" / "workflows").glob("*.yml")
    assert not [w.name for w in workflows if "bars_abuse" in w.read_text(encoding="utf-8")]
