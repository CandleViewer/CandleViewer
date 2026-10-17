"""#2893 S6: the plan section 9.6 request log never holds a signature or a secret (C-12.6).

Each pack key's requests are signed as `BybitSigner` does (HMAC-SHA256 over timestamp + key id +
recv window + payload, with the pack's derived secret), logged as the guards will, and the file is
searched for the MAC, the derived secret and the signature header. The clock is injected and fixed;
every file lives under `tmp_path`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from candleviewer.observability.redaction import redact_structure
from candleviewer.settings import Environment
from cvdev.account_fixture import requestlog
from cvdev.account_fixture.requestlog import (
    FILE_NAME,
    MAX_LINE_BYTES,
    OrderFields,
    RequestLog,
    RequestLogFieldError,
    RequestLogFileError,
)
from tests._account_fixtures import OVERLAY, manifest, scenario_names


def _order(**fields: Any) -> OrderFields:
    return OrderFields(**fields)


NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
ORDER_CREATE = "/v5/order/create"
TRADING_STOP = "/v5/position/trading-stop"
KEY_IDS = {
    name: str(manifest(name)["tester_inputs"]["key_id"])
    for name in scenario_names()
    if manifest(name).get("origin") != OVERLAY and "rotation" not in manifest(name)
}
#: Key-shaped and derived here, never a credential: a key outside the pack.
NON_FIXTURE_KEY = "".join(chr(65 + b % 26) for b in hashlib.sha256(b"cv-2893-s6").digest()[:18])
OMS_LINK = "cvd-0" + "a" * 21 + "-0001-00en"  # the OMS order-link shape (domain.order_link)
#: A signed key-info call the guards passed and the stub answered; `_served` adds the key.
SERVED: dict[str, Any] = dict(transport="rest", host="api-demo.bybit.com", host_env="demo")
SERVED |= dict(method="GET", path="/v5/user/query-api", key_class="fixture", verified=True)
SERVED |= dict(status=200, ret_code=0, code_unconfirmed=False, outcome="served")
#: Plan section 9.7: BTCUSDT 10 % under the last trade (63110.00) on the 0.10 tick, SL 300 ticks.
ORDER: dict[str, Any] = dict(order_link_id=OMS_LINK, symbol="BTCUSDT", side="Buy")
ORDER |= dict(order_type="Limit", qty="0.001", price="56799.0", reduce_only=False)
ORDER |= dict(stop_loss="56769.0", sl_trigger_by="MarkPrice")
REFERENCE_ORDER = _order(
    **{k: Decimal(v) if k in ("qty", "price", "stop_loss") else v for k, v in ORDER.items()}
)


def _secret(scenario: str) -> str:
    """The pack README's derived secret, computed here and never stored in a file."""
    return f"fixture-{scenario}-secret-not-real"


def _mac(scenario: str, payload: str = "") -> str:
    """What `BybitSigner` sends: HMAC-SHA256 of timestamp + key id + recv window + payload."""
    message = f"1792141200000{KEY_IDS[scenario]}5000{payload}".encode()
    return hmac.new(_secret(scenario).encode(), message, hashlib.sha256).hexdigest()


def _open(
    log_dir: str | Path | None, clock: Callable[[], datetime] = lambda: NOW, **opts: Any
) -> RequestLog:
    return RequestLog(
        log_dir, process_env=Environment.DEMO, clock=clock, pack_key_ids=KEY_IDS.values(), **opts
    )


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    (tmp_path / "fixture").mkdir()
    return tmp_path / "fixture"


@pytest.fixture
def log(log_dir: Path) -> Iterator[RequestLog]:
    with _open(log_dir) as opened:
        yield opened


def _served(log: RequestLog, key: str = "compliant", /, **fields: Any) -> None:
    keyed = {"signing_key_id": KEY_IDS[key], "scenario": key, "stored_under": key}
    log.write(**(SERVED | keyed | fields))


def _lines(log_dir: Path, name: str = FILE_NAME) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (log_dir / name).read_text().splitlines()]


def _empty(log_dir: Path) -> bool:
    return (log_dir / FILE_NAME).read_bytes() == b""


def test_line_has_the_plan_9_6_fields(log: RequestLog, log_dir: Path) -> None:
    _served(log, overlays=("working_orders_2",))
    expected = SERVED | {"ts": "2026-10-16T09:00:00.000Z", "process_env": "demo", "order": None}
    expected |= {"signing_key_id": "fixture-compliant-0001", "overlays": ["working_orders_2"]}
    assert _lines(log_dir) == [expected | {"scenario": "compliant", "stored_under": "compliant"}]


@pytest.mark.parametrize("scenario", sorted(KEY_IDS))
def test_never_writes_signature_secret_or_auth_header(
    log: RequestLog, log_dir: Path, scenario: str
) -> None:
    body = json.dumps({"category": "linear", "symbol": "BTCUSDT", "orderLinkId": OMS_LINK})
    _served(log, scenario)
    _served(log, scenario, method="POST", path=ORDER_CREATE, order=REFERENCE_ORDER)
    text = (log_dir / FILE_NAME).read_text().lower()
    assert KEY_IDS[scenario] in text
    for needle in (_mac(scenario), _mac(scenario, body), _secret(scenario), "x-bapi-sign"):
        assert needle not in text


_SLOTS: dict[str, Callable[[str], dict[str, Any]]] = {
    "host": lambda value: {"host": f"{value}.example"},
    "method": lambda value: {"method": value},
    "path": lambda value: {"path": f"/v5/{value}"},
    "signing_key_id": lambda value: {"signing_key_id": value},
    "scenario": lambda value: {"scenario": value},
    "stored_under": lambda value: {"stored_under": value},
    "overlays": lambda value: {"overlays": (value,)},
    "order_link_id": lambda value: {"path": ORDER_CREATE, "order": _order(order_link_id=value)},
    "symbol": lambda value: {"path": ORDER_CREATE, "order": _order(symbol=value)},
    "host_env": lambda value: {"host_env": value},  # a choice refusal echoes no value either
    "overlays_text": lambda value: {"overlays": value},
}


@pytest.mark.parametrize("slot", sorted(_SLOTS))
@pytest.mark.parametrize(
    "value", [_mac("compliant"), _mac("compliant").upper(), _secret("x")], ids=["mac", "MAC", "sec"]
)
def test_signature_or_secret_in_any_field_is_refused(
    log: RequestLog, log_dir: Path, slot: str, value: str
) -> None:
    with pytest.raises(RequestLogFieldError) as refused:
        _served(log, **_SLOTS[slot](value))
    assert value not in str(refused.value)
    assert _empty(log_dir)


def test_non_fixture_key_logged_as_class_only(log: RequestLog, log_dir: Path) -> None:
    with pytest.raises(RequestLogFieldError) as refused:
        _served(log, signing_key_id=NON_FIXTURE_KEY, outcome="refused_key")
    _served(log, signing_key_id=None, key_class="non_fixture", verified=None, outcome="refused_key")
    (line,) = _lines(log_dir)
    assert (line["signing_key_id"], line["key_class"], line["verified"]) == (
        None,
        "non_fixture",
        None,
    )
    text = (log_dir / FILE_NAME).read_text() + str(refused.value)
    windows = {NON_FIXTURE_KEY[i : i + 4] for i in range(len(NON_FIXTURE_KEY) - 3)}
    assert [window for window in windows if window in text] == []


def test_pack_shaped_key_outside_the_pack_is_refused(log: RequestLog, log_dir: Path) -> None:
    with pytest.raises(RequestLogFieldError, match="signing_key_id"):
        _served(log, signing_key_id="fixture-not_in_the_pack-9999")
    assert _empty(log_dir)


def test_order_subset_carries_the_stop_loss(log: RequestLog, log_dir: Path) -> None:
    amend = OrderFields(order_link_id=OMS_LINK, stop_loss=Decimal("56759.0"))
    _served(log, method="POST", path=ORDER_CREATE, order=REFERENCE_ORDER)
    _served(log, method="POST", path="/v5/order/amend", order=amend)
    create, amended = (line["order"] for line in _lines(log_dir))
    assert create == ORDER
    assert (create["stop_loss"], amended["stop_loss"]) == ("56769.0", "56759.0")


def test_trading_stop_logs_the_sl_it_sets_or_clears(log: RequestLog, log_dir: Path) -> None:
    sl: dict[str, Any] = dict(symbol="BTCUSDT", sl_trigger_by="MarkPrice")
    for stop_loss in (Decimal("56769.0"), Decimal(0)):  # 0 clears the native SL (TC-316, TC-410)
        _served(log, method="POST", path=TRADING_STOP, order=_order(**sl, stop_loss=stop_loss))
    expected = [dict.fromkeys(ORDER) | sl | {"stop_loss": px} for px in ("56769.0", "0")]
    assert [line["order"] for line in _lines(log_dir)] == expected


@pytest.mark.parametrize("name", ["signature", "headers", "body", "request", "api_key", "secret"])
def test_writer_rejects_unknown_fields(log: RequestLog, log_dir: Path, name: str) -> None:
    with pytest.raises(TypeError, match=name):
        _served(log, **{name: "x"})
    with pytest.raises(TypeError, match=name):
        _order(**{name: "x"})
    assert _empty(log_dir)


def test_field_names_avoid_the_redaction_deny_list(log: RequestLog, log_dir: Path) -> None:
    _served(log, method="POST", path=ORDER_CREATE, order=REFERENCE_ORDER)
    (line,) = _lines(log_dir)
    names = {name: "x" for name in [*line, *line["order"]]}
    assert redact_structure(names) == names


@pytest.mark.parametrize(
    "fields",
    [
        {"key_class": "non_fixture", "signing_key_id": None, "verified": None},
        {"verified": False},
        {"verified": None, "outcome": "unstubbed"},
        {"signing_key_id": None},
        {"key_class": "unsigned", "signing_key_id": None},
        {"outcome": "signature_mismatch"},
        {"transport": None},
        {"key_class": None, "signing_key_id": None, "verified": None},
        {"order": _order(symbol="BTCUSDT", stop_loss=Decimal("56769.0"))},  # on query-api
        {"path": TRADING_STOP, "order": REFERENCE_ORDER},
    ],
)
def test_line_no_guard_may_produce_is_refused(
    log: RequestLog, log_dir: Path, fields: dict[str, Any]
) -> None:
    with pytest.raises(RequestLogFieldError):
        _served(log, **fields)
    assert _empty(log_dir)


@pytest.mark.parametrize(
    "fields",
    [
        {"key_class": "unsigned", "signing_key_id": None, "verified": None, "scenario": None},
        {"verified": False, "status": 401, "ret_code": 10004, "outcome": "signature_mismatch"},
        {"host": "api.bybit.com", "host_env": "live", "status": None, "outcome": "refused_host"},
        {"method": "POST", "path": "/v5/asset/transfer", "outcome": "refused_fund_path"},
        {"transport": None, "method": None, "path": None, "host": None, "outcome": "switch"},
        {"transport": "ws", "method": "AUTH", "path": "/v5/private", "status": None},
        {"overlays": ["working_orders_2"] * 16},
    ],
)
def test_each_guard_outcome_is_logged(
    log: RequestLog, log_dir: Path, fields: dict[str, Any]
) -> None:
    _served(log, **fields)
    (line,) = _lines(log_dir)
    assert {name: line[name] for name in fields} == fields


@pytest.mark.parametrize(
    "fields",
    [
        {"host": "API-DEMO.example.com"},
        {"path": "/v5/user/query-api?x=1"},
        {"method": "get"},
        {"host_env": "staging"},
        {"verified": "true"},
        {"status": True},
        {"overlays": "working_orders_2"},
        {"outcome": None},
        {"path": ORDER_CREATE, "order": {"stopLoss": "56769.0"}},
        {"path": ORDER_CREATE, "order": _order(qty=0.001)},
        {"path": ORDER_CREATE, "order": _order(qty=Decimal("1E+40"))},
        {"path": ORDER_CREATE, "order": _order(qty=Decimal("-0.001"))},
        {"path": ORDER_CREATE, "order": _order(price=Decimal("Infinity"))},
        {"path": ORDER_CREATE, "order": _order(stop_loss=Decimal("NaN"))},
        {"path": ORDER_CREATE, "order": _order(reduce_only="false")},
        {"code_unconfirmed": "false"},
        {"overlays": ("working_orders_2",) * 17},
    ],
)
def test_field_outside_its_rule_is_refused(
    log: RequestLog, log_dir: Path, fields: dict[str, Any]
) -> None:
    with pytest.raises(RequestLogFieldError):
        _served(log, **fields)
    assert _empty(log_dir)


def test_line_over_the_line_bound_is_refused(
    log: RequestLog, log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(requestlog, "MAX_LINE_BYTES", 100)
    with pytest.raises(RequestLogFieldError, match="fit"):
        _served(log)
    assert _empty(log_dir)


def test_ts_comes_from_the_injected_clock(log_dir: Path) -> None:
    ticks = iter([NOW, NOW + timedelta(seconds=1.5), NOW.replace(tzinfo=None)])
    with _open(log_dir, clock=lambda: next(ticks)) as log:
        _served(log)
        _served(log)
        with pytest.raises(RequestLogFieldError, match="timezone"):
            _served(log)
    stamps = [line["ts"] for line in _lines(log_dir)]
    assert stamps == ["2026-10-16T09:00:00.000Z", "2026-10-16T09:00:01.500Z"]


def test_ts_is_utc_whatever_the_clock_offset(log_dir: Path) -> None:
    with _open(log_dir, clock=lambda: NOW.astimezone(timezone(timedelta(hours=2)))) as log:
        _served(log)
    assert _lines(log_dir)[0]["ts"] == "2026-10-16T09:00:00.000Z"  # not 11:00:00.000+02:00


def test_log_file_is_created_0600_and_an_existing_one_narrowed(log_dir: Path) -> None:
    (log_dir / FILE_NAME).write_text("earlier\n")
    (log_dir / FILE_NAME).chmod(0o644)
    previous = os.umask(0)
    try:
        with _open(log_dir) as log:
            _served(log)
    finally:
        os.umask(previous)
    assert stat.S_IMODE((log_dir / FILE_NAME).stat().st_mode) == 0o600
    assert (log_dir / FILE_NAME).read_text().startswith("earlier\n")


def test_log_refuses_a_symlinked_file_and_leaves_its_target(log_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "elsewhere").write_text("untouched\n")
    (log_dir / FILE_NAME).symlink_to(tmp_path / "elsewhere")
    with pytest.raises(RequestLogFileError, match="symlink"):
        _open(log_dir)
    assert (tmp_path / "elsewhere").read_text() == "untouched\n"


@pytest.mark.parametrize("suffix", ["", "/", "//", "/.", "/./", "/.."])
def test_log_refuses_a_symlinked_directory(log_dir: Path, tmp_path: Path, suffix: str) -> None:
    (tmp_path / "link").symlink_to(log_dir, target_is_directory=True)
    with pytest.raises(RequestLogFileError, match="CV_ACCOUNT_FIXTURE_DIR"):
        _open(f"{tmp_path / 'link'}{suffix}")  # a trailing / or /. made the kernel follow it
    assert list(log_dir.iterdir()) == [] == list(tmp_path.glob(f"{FILE_NAME}*"))


def test_log_opens_its_directory_however_spelled(log_dir: Path) -> None:
    for spelled in (f"{log_dir}//", f"{log_dir}/./"):  # Settings lets a trailing / through
        with _open(spelled) as log:
            _served(log)
    assert len(_lines(log_dir)) == 2


def test_log_refuses_a_hard_linked_file_and_leaves_its_other_name(
    log_dir: Path, tmp_path: Path
) -> None:
    (tmp_path / "elsewhere").write_text("untouched\n")
    (tmp_path / "elsewhere").chmod(0o644)
    (log_dir / FILE_NAME).hardlink_to(tmp_path / "elsewhere")
    with pytest.raises(RequestLogFileError, match="one link"):
        _open(log_dir)
    assert stat.S_IMODE((tmp_path / "elsewhere").stat().st_mode) == 0o644


def test_log_refuses_a_file_that_is_not_regular(log_dir: Path) -> None:
    os.mkfifo(log_dir / FILE_NAME, 0o600)
    reader = os.open(log_dir / FILE_NAME, os.O_RDONLY | os.O_NONBLOCK)
    try:
        with pytest.raises(RequestLogFileError, match="regular file"):
            _open(log_dir)
    finally:
        os.close(reader)


def test_log_refuses_a_file_another_user_owns(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (log_dir / FILE_NAME).write_text("")
    monkeypatch.setattr(os, "geteuid", lambda: (log_dir / FILE_NAME).stat().st_uid + 1)
    with pytest.raises(RequestLogFileError, match="owned"):
        _open(log_dir)


def test_log_rotates_at_the_size_cap_and_drops_the_oldest(log_dir: Path) -> None:
    ticks = (NOW + timedelta(seconds=n) for n in range(60))
    with _open(log_dir, clock=lambda: next(ticks), max_bytes=MAX_LINE_BYTES, backups=2) as log:
        for _ in range(60):
            _served(log)
    files = sorted(log_dir.iterdir())
    assert [f.name for f in files] == [FILE_NAME, f"{FILE_NAME}.1", f"{FILE_NAME}.2"]
    assert all(f.stat().st_size <= MAX_LINE_BYTES for f in files)
    assert all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files)
    kept = [line["ts"] for name in reversed(files) for line in _lines(log_dir, name.name)]
    assert kept == sorted(kept)
    assert kept[-1] == "2026-10-16T09:00:59.000Z"
    assert "2026-10-16T09:00:00.000Z" not in kept


def test_failed_rotation_closes_the_log(log_dir: Path) -> None:
    (log_dir / f"{FILE_NAME}.1").mkdir()
    (log_dir / f"{FILE_NAME}.1" / "planted").write_text("")
    with _open(log_dir, max_bytes=MAX_LINE_BYTES, backups=1) as log:
        with pytest.raises(RequestLogFileError, match="rotat"):
            for _ in range(20):
                _served(log)
        with pytest.raises(RequestLogFileError, match="closed"):
            _served(log)


@pytest.mark.parametrize(
    "opts",
    [
        {"pack_key_ids": [NON_FIXTURE_KEY]},
        {"pack_key_ids": []},
        {"max_bytes": MAX_LINE_BYTES - 1},
        {"backups": 0},
        {"backups": 10},
        {"process_env": "demo"},
    ],
)
def test_log_refuses_unsafe_options(log_dir: Path, opts: dict[str, Any]) -> None:
    options: dict[str, Any] = {"process_env": Environment.DEMO, "pack_key_ids": KEY_IDS.values()}
    with pytest.raises(ValueError, match="must"):
        RequestLog(log_dir, clock=lambda: NOW, **(options | opts))
    assert list(log_dir.iterdir()) == []


@pytest.mark.parametrize("directory", [None, "", "."])
def test_log_needs_cv_account_fixture_dir(
    directory: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # "" and "." would name the working directory
    with pytest.raises(RequestLogFileError, match="CV_ACCOUNT_FIXTURE_DIR"):
        _open(directory)
    assert list(tmp_path.iterdir()) == []
