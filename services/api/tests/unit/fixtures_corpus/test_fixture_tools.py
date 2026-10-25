"""E08-T05 tooling tests: redactor self-test with planted secrets, capture tool
(fake transport — never the network), drift check (planted field change), and
corpus-builder determinism. All synthetic test vectors; none is a real secret.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[5]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.fixtures import build_corpus, capture_fixture, drift_check, gen_orderbook  # noqa: E402
from tools.fixtures.redact import REDACTED, find_leaks, redact  # noqa: E402

# Obviously synthetic vectors (repeated letters / DUMMYKEY_), shaped like the real thing.
_FAKE_KEY = "DUMMYKEY_aaaaaaaaaaaaaaaa"
_FAKE_SIG = "ab" * 32  # 64 hex chars: HMAC-SHA256 shape
_PLANTED = [
    f'{{"api_key":"{_FAKE_KEY}","p":"1.0"}}',
    f'{{"sign":"{_FAKE_SIG}"}}',
    '{"uid":123456789,"accountId":"acct-fake-0001","userId":"u-fake"}',
    f"X-BAPI-API-KEY: {_FAKE_KEY}",
    f'{{"headers":{{"X-BAPI-SIGN":"{_FAKE_SIG}","Authorization":"Bearer fakefakefakefakefake"}}}}',
    f"GET /v5/x?api_key={_FAKE_KEY}&sign={_FAKE_SIG}",
    "-----BEGIN RSA PRIVATE KEY-----\nZmFrZQ==\n-----END RSA PRIVATE KEY-----",
    f"trailing signature {_FAKE_SIG} in free text",
]


@pytest.mark.parametrize("planted", _PLANTED)
def test_redactor_removes_planted_secrets(planted: str) -> None:
    assert find_leaks(planted), "self-test vector must be detectable before redaction"
    clean = redact(planted)
    assert find_leaks(clean) == []
    assert _FAKE_KEY not in clean and _FAKE_SIG not in clean and "fakefakefake" not in clean
    assert "123456789" not in clean and "acct-fake-0001" not in clean
    assert REDACTED in clean


def test_redactor_leaves_market_data_untouched() -> None:
    frame = (corpus_dir() / "ws" / "publicTrade_BTCUSDT.jsonl").read_text(encoding="utf-8")
    assert redact(frame) == frame


def test_committed_corpus_is_secret_free() -> None:
    for path in corpus_dir().rglob("*.json*"):
        assert find_leaks(path.read_text(encoding="utf-8")) == [], path.name


def corpus_dir() -> Path:
    return Path(build_corpus.ROOT)


class _FakeSocket:
    def __init__(self, inbox: list[str]) -> None:
        self.inbox, self.closed = list(inbox), False
        self.sent: list[str] = []

    async def send(self, frame: str) -> None:
        self.sent.append(frame)

    async def recv(self) -> str:
        return self.inbox.pop(0)

    async def close(self) -> None:
        self.closed = True


_T = "publicTrade.BTCUSDT"
_LEAKY = (
    f'{{"topic":"{_T}","type":"snapshot","ts":1700000000100,"uid":42,'
    f'"data":[{{"s":"BTCUSDT","sign":"{_FAKE_SIG}"}}]}}'
)


def _connector(sock: _FakeSocket) -> capture_fixture.Connector:
    async def connect(url: str) -> _FakeSocket:
        assert url == capture_fixture.PUBLIC_URL
        return sock

    return connect


async def test_capture_records_redacted_frames_and_manifest(tmp_path: Path) -> None:
    ack = '{"success":true,"op":"subscribe"}'
    sock = _FakeSocket([ack, _LEAKY, '{"op":"pong"}', _LEAKY.replace("100", "900")])
    out = tmp_path / "ws" / "cap.jsonl"
    res = await capture_fixture.capture(
        _T, out, max_frames=2, connect=_connector(sock),
        now=lambda: datetime(2026, 10, 5, tzinfo=UTC),
    )  # fmt: skip
    assert sock.closed and json.loads(sock.sent[0]) == {"op": "subscribe", "args": [_T]}
    text = out.read_text(encoding="utf-8")
    assert res.frames == 2 and _FAKE_SIG not in text and '"uid":"REDACTED"' in text
    manifest = json.loads((tmp_path / "ws" / "cap.jsonl.manifest.json").read_text("utf-8"))
    assert manifest["window_ms"] == [1700000000100, 1700000000900]
    assert manifest["capture_date"] == "2026-10-05" and manifest["stream"] == _T


async def test_capture_enforces_size_cap_and_frame_count(tmp_path: Path) -> None:
    with pytest.raises(capture_fixture.CaptureError, match="cap"):
        await capture_fixture.capture(_T, tmp_path / "x.jsonl", max_frames=5,
                                      connect=_connector(_FakeSocket([_LEAKY] * 5)),
                                      size_cap=50)  # fmt: skip
    with pytest.raises(ValueError, match="max_frames"):
        await capture_fixture.capture(_T, tmp_path / "x.jsonl", max_frames=0,
                                      connect=_connector(_FakeSocket([])))  # fmt: skip


async def test_capture_aborts_when_a_frame_still_leaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_fixture, "redact", lambda s: s)  # simulate a redactor regression
    sock = _FakeSocket([_LEAKY])
    with pytest.raises(capture_fixture.CaptureError, match="secret patterns"):
        await capture_fixture.capture(_T, tmp_path / "x.jsonl", max_frames=1,
                                      connect=_connector(sock))  # fmt: skip
    assert sock.closed and not (tmp_path / "x.jsonl").exists()


def test_capture_cli_main_uses_injected_transport(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "c.jsonl"
    argv = ["--topic", _T, "--frames", "1", "--out", str(out)]
    ok = capture_fixture.main(argv, connect=_connector(_FakeSocket([_LEAKY])))
    bad = capture_fixture.main(
        [*argv, "--size-cap", "10"], connect=_connector(_FakeSocket([_LEAKY]))
    )
    assert (ok, bad) == (0, 1)
    assert "capture aborted" in capsys.readouterr().err


_RL_REPLY = (
    '{"retCode":0,"retMsg":"OK","result":{"category":"linear","list":[{"id":1,'
    f'"symbol":"BTCUSDT","sign":"{_FAKE_SIG}"}}],"nextPageCursor":""}},"time":1700000000000}}'
)


async def test_capture_rest_records_one_redacted_public_reply(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    async def get(url: str, params: Mapping[str, str]) -> tuple[int, str]:
        calls.append((url, dict(params)))
        return 200, _RL_REPLY + "\n"

    out = tmp_path / "rest" / "risk_limit_BTCUSDT.json"
    res = await capture_fixture.capture_rest(
        "/v5/market/risk-limit", {"category": "linear", "symbol": "BTCUSDT"}, out, get=get,
        now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
    )  # fmt: skip
    assert calls == [("https://api.bybit.com/v5/market/risk-limit",
                      {"category": "linear", "symbol": "BTCUSDT"})]  # fmt: skip
    text = out.read_text(encoding="utf-8")
    assert res.frames == 1 and _FAKE_SIG not in text and '"sign":"REDACTED"' in text
    manifest = json.loads((tmp_path / "rest" / f"{out.name}.manifest.json").read_text("utf-8"))
    assert manifest["stream"] == "GET /v5/market/risk-limit" and manifest["symbol"] == "BTCUSDT"
    assert manifest["host"] == "api.bybit.com" and manifest["capture_date"] == "2026-10-25"
    for bad in (
        "/v5/position/list",
        "/v5/market/../account/info",
    ):  # never a private route
        with pytest.raises(capture_fixture.CaptureError, match="public"):
            await capture_fixture.capture_rest(bad, {}, out, get=get)
    with pytest.raises(capture_fixture.CaptureError, match="cap"):
        await capture_fixture.capture_rest("/v5/market/risk-limit", {}, out, get=get, size_cap=10)


def test_capture_cli_rest_mode_uses_injected_getter(tmp_path: Path) -> None:
    async def get(url: str, params: Mapping[str, str]) -> tuple[int, str]:
        return 200, _RL_REPLY

    out = tmp_path / "r.json"
    argv = [
        "--rest-path",
        "/v5/market/risk-limit",
        "--param",
        "symbol=BTCUSDT",
        "--out",
        str(out),
    ]
    assert capture_fixture.main(argv, get=get) == 0 and out.exists()


def _sample(tmp_path: Path, frames: list[dict[str, object]]) -> Path:
    d = tmp_path / "sample"
    d.mkdir(exist_ok=True)
    (d / "fresh.jsonl").write_text("\n".join(json.dumps(f) for f in frames), encoding="utf-8")
    return d


def _trade_frame() -> dict[str, object]:
    line = (corpus_dir() / "ws" / "publicTrade_BTCUSDT.jsonl").read_text("utf-8").splitlines()[0]
    frame: dict[str, object] = json.loads(line)
    return frame


def test_drift_check_passes_on_a_value_only_change(tmp_path: Path) -> None:
    f = _trade_frame()
    f["ts"] = 1800000000000
    assert drift_check.main(["--sample", str(_sample(tmp_path, [f]))]) == 0


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.__setitem__("newField", "x"), "publicTrade: added field data[].newField"),
        (lambda d: d.pop("BT"), "publicTrade: removed field data[].BT"),
        (lambda d: d.__setitem__("p", 63120.5), "publicTrade: retyped field data[].p string"),
    ],
)
def test_drift_check_names_stream_and_field_for_planted_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutate: object, expected: str
) -> None:
    f = _trade_frame()
    for row in f["data"]:  # type: ignore[attr-defined]  # recorded shape: list of dicts
        mutate(row)  # type: ignore[operator]  # parametrized callable
    report = tmp_path / "drift.txt"
    rc = drift_check.main(["--sample", str(_sample(tmp_path, [f])), "--report", str(report)])
    assert rc == 1
    assert expected in capsys.readouterr().err
    assert expected in report.read_text(encoding="utf-8")


def test_drift_check_flags_unknown_stream_and_empty_sample(tmp_path: Path) -> None:
    unknown = _sample(tmp_path, [{"topic": "liquidation.BTCUSDT", "data": {}}])
    assert drift_check.main(["--sample", str(unknown)]) == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert drift_check.main(["--sample", str(empty)]) == 2
    with pytest.raises(SystemExit):
        drift_check.main([])


def test_drift_expectations_are_current_and_rest_streams_load(tmp_path: Path) -> None:
    out = tmp_path / "exp.json"
    assert drift_check.main(["--write-expectations", "--expectations", str(out)]) == 0
    assert out.read_bytes() == drift_check.EXPECTATIONS.read_bytes()
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["rest.error"]["retCode"]["required"] is False  # the 5xx body has no envelope
    assert drift_check.json_type(None) == "null" and drift_check.stream_of([], "x") == "x"


def test_corpus_builder_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    committed = {p.name: p.read_bytes() for p in corpus_dir().rglob("*") if p.is_file()}
    monkeypatch.setattr(build_corpus, "ROOT", tmp_path)
    (tmp_path / "manifest.json").parent.mkdir(exist_ok=True)
    build_corpus.main()
    rebuilt = {p.name: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert rebuilt
    for name, data in rebuilt.items():
        assert data == committed[name], name


def test_orderbook_generator_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gen = importlib.reload(gen_orderbook)  # fresh seeded RNG
    monkeypatch.setattr(gen, "_OUT", tmp_path / "ob.jsonl")
    gen.main()
    committed = corpus_dir() / "ws" / "orderbook_BTCUSDT.jsonl"
    assert (tmp_path / "ob.jsonl").read_bytes() == committed.read_bytes()
