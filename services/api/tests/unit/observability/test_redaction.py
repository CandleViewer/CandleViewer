"""Redaction matrix — unit tests for `candleviewer.observability.redaction`.

E04-T01 acceptance criterion: "Canary secrets never reach the output". Each
test below plants a unique canary string and asserts it never survives
`_redact_mapping`/`_redact_value`.
"""

from __future__ import annotations

from candleviewer.observability.redaction import _redact_mapping, _redact_value


def test_redacts_api_key_by_exact_name() -> None:
    out = _redact_mapping({"api_key": "CANARY-KEY-1"})
    assert out["api_key"] == "[redacted:key-name]"


def test_redacts_api_secret_by_exact_name() -> None:
    out = _redact_mapping({"api_secret": "CANARY-SECRET-1"})
    redacted_value = out["api_secret"]
    assert redacted_value == "[redacted:key-name]"


def test_redacts_access_token_and_token_by_exact_name() -> None:
    out = _redact_mapping({"access_token": "short-1", "token": "short-2"})
    assert out == {"access_token": "[redacted:key-name]", "token": "[redacted:key-name]"}


def test_redacts_generic_secret_key() -> None:
    out = _redact_mapping({"secret": "CANARY-2"})
    assert "CANARY-2" not in str(out)


def test_redacts_password_key() -> None:
    out = _redact_mapping({"password": "hunter2-CANARY"})
    assert "CANARY" not in str(out)


def test_redacts_cookie_key() -> None:
    out = _redact_mapping({"cookie": "sessid=CANARY-3"})
    assert "CANARY-3" not in str(out)


def test_redacts_set_cookie_key() -> None:
    out = _redact_mapping({"set-cookie": "sessid=CANARY-4"})
    assert "CANARY-4" not in str(out)


def test_redacts_authorization_key() -> None:
    out = _redact_mapping({"authorization": "Bearer CANARY-5"})
    assert "CANARY-5" not in str(out)


def test_redacts_x_bapi_sign_key() -> None:
    out = _redact_mapping({"x-bapi-sign": "CANARY-6"})
    assert "CANARY-6" not in str(out)


def test_redacts_x_bapi_api_key_key() -> None:
    out = _redact_mapping({"x-bapi-api-key": "CANARY-7"})
    assert "CANARY-7" not in str(out)


def test_redacts_totp_key() -> None:
    out = _redact_mapping({"totp": "123456"})
    assert out["totp"] == "[redacted:key-name]"


def test_redacts_recovery_code_key() -> None:
    out = _redact_mapping({"recovery_code": "CANARY-8"})
    assert "CANARY-8" not in str(out)


def test_redacts_session_key() -> None:
    out = _redact_mapping({"session": "CANARY-9"})
    assert "CANARY-9" not in str(out)


def test_redacts_csrf_key() -> None:
    out = _redact_mapping({"csrf": "CANARY-10"})
    assert "CANARY-10" not in str(out)


def test_key_match_is_case_insensitive() -> None:
    out = _redact_mapping({"API_KEY": "CANARY-11", "Api-Secret": "CANARY-12"})
    assert "CANARY-11" not in str(out)


def test_non_secret_keys_are_left_untouched() -> None:
    out = _redact_mapping({"symbol": "BTCUSDT", "latency_ms": 12})
    assert out == {"symbol": "BTCUSDT", "latency_ms": 12}


def test_redacts_secret_nested_inside_a_dict() -> None:
    out = _redact_mapping({"headers": {"authorization": "Bearer CANARY-13"}})
    assert "CANARY-13" not in str(out)


def test_redacts_secret_inside_a_list_of_dicts() -> None:
    out = _redact_mapping({"events": [{"api_key": "CANARY-14"}, {"symbol": "ETHUSDT"}]})
    assert "CANARY-14" not in str(out)
    assert out["events"][1] == {"symbol": "ETHUSDT"}


def test_redacts_secret_inside_a_list_under_a_secret_shaped_key() -> None:
    # When the *key* is secret-shaped, the whole list value is replaced by name.
    out = _redact_mapping({"secret": ["CANARY-16"]})
    assert "CANARY-16" not in str(out)


def test_depth_limited_recursion_marks_deep_structures_redacted() -> None:
    nested: dict[str, object] = {"api_secret": "CANARY-17"}
    deep: dict[str, object] = nested
    for _ in range(10):
        deep = {"child": deep}
    out = _redact_mapping(deep)
    # Either the secret is redacted by key on the way down, or the branch is
    # cut off by the depth guard — either way the canary must not survive.
    assert "CANARY-17" not in str(out)


def test_oversize_string_value_is_truncated_before_scanning() -> None:
    huge = "x" * 10_000
    out = _redact_value(huge, depth=0)
    assert len(out) < 10_000
    assert "truncated" in out or out == huge[:4096] + "...[truncated:oversize]"


def test_jwt_shaped_value_is_redacted() -> None:
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.CANARYPAYLOAD1234567.SIGNATURECANARY12345"
    out = _redact_value(fake_jwt, depth=0)
    assert "CANARYPAYLOAD1234567" not in out
    assert out.startswith("[redacted:")


def test_bybit_key_shaped_value_is_redacted() -> None:
    fake_key = "CANARYBYBITKEY0123456789ABCDEF"
    out = _redact_value(fake_key, depth=0)
    assert fake_key not in out
    assert out == "[redacted:key-shape]"


def test_six_digit_totp_shaped_value_is_redacted() -> None:
    out = _redact_value("totp code: 654321", depth=0)
    assert "654321" not in out


def test_traceback_like_string_with_secret_is_redacted() -> None:
    traceback_text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "    raise ValueError('CANARYBYBITKEY0123456789ABCDEF')\n"
        "ValueError: CANARYBYBITKEY0123456789ABCDEF"
    )
    out = _redact_value(traceback_text, depth=0)
    assert "CANARYBYBITKEY0123456789ABCDEF" not in out


def test_third_party_style_record_dict_is_redacted() -> None:
    # Shape resembling an httpx/websockets/sqlalchemy log record dict.
    record = {"url": "https://api.bybit.com/x", "headers": {"Authorization": "Bearer CANARY-18"}}
    out = _redact_mapping(record)
    assert "CANARY-18" not in str(out)


def test_invite_token_in_url_path_is_redacted() -> None:
    import secrets

    from candleviewer.observability.redaction import _redact_str_value

    token = secrets.token_urlsafe(32)
    out = _redact_str_value(f"POST /invites/{token}/confirm 200")
    assert token not in out
