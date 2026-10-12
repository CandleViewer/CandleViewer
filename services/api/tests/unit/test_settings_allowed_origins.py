"""#2239 (SR-042): `CV_ALLOWED_ORIGINS` entries must be serialised origins, checked at startup.

Both REST and the WS upgrade (`23-ws-protocol.md` §2.5) compare browser `Origin` headers
exactly, so an entry spelled any other way would silently never match; it fails startup.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings, get_settings, is_serialised_origin

_VALID = [
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "https://candleviewer.tail1234.ts.net",
    "https://app.example:8443",
    "http://[::1]:5173",
    "app://candleviewer",
    "https://xn--bcher-kva.example",
]

_INVALID = [
    "",  # an entry that is empty once its trailing `/` is dropped (e.g. "/")
    "null",
    "*",
    "https://*.ts.net",
    "app.example",  # no scheme
    "HTTPS://app.example",
    "https://App.example",
    "https://app.example:443",  # default port
    "http://app.example:80",
    "https://app.example:08443",  # not how a browser spells the port
    "https://app.example:0",
    "https://app.example:99999",
    "https://app.example/path",
    "https://app.example?x=1",
    "https://app.example#frag",
    "https://user@app.example",
    "https://bücher.example",  # non-ASCII host: use the punycode form
    "https://app .example",
    "http://[0:0::1]:5173",  # IPv6 not in canonical (browser) form
    "file://",
]


@pytest.mark.parametrize("entry", _VALID)
def test_is_serialised_origin_accepts_browser_spelled_origins(entry: str) -> None:
    assert is_serialised_origin(entry)


@pytest.mark.parametrize("entry", _INVALID)
def test_is_serialised_origin_rejects_anything_a_browser_never_sends(entry: str) -> None:
    assert not is_serialised_origin(entry)


def test_settings_accepts_valid_list_trailing_slash_and_blank_segments() -> None:
    s = Settings(allowed_origins=" http://a.example/ ,,http://b.example, app://candleviewer ,")
    assert s.allowed_origin_set == frozenset(
        {"http://a.example", "http://b.example", "app://candleviewer"}
    )
    assert Settings(allowed_origins="").allowed_origin_set == frozenset()


@pytest.mark.parametrize(
    "value",
    ["/", "http://a.example,null", "*", "https://App.example", "https://a.example:443"],
)
def test_settings_refuses_a_bad_entry_naming_it(value: str) -> None:
    with pytest.raises(ValidationError, match="CV_ALLOWED_ORIGINS entry"):
        Settings(allowed_origins=value)


def test_bad_cv_allowed_origins_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_ALLOWED_ORIGINS", "https://app.example/ui")
    with pytest.raises(ValidationError, match="not a serialised origin"):
        get_settings()
