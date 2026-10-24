"""E14-X03 (#549, AC4): `security/zap/drawings_isolation.py`, the Owner's drawing seeded before the
ZAP drawings scan and checked after it. A stand-in API for the logic, a local HTTP server for the
requests (the loopback only), no ZAP and no stack."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / ".zap/e14-drawings-seed.json"
ID = json.loads(FIXTURE.read_text(encoding="utf-8"))["operations"][0]["id"]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"zap_{name}", ROOT / f"security/zap/{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


iso, mint = _load("drawings_isolation"), _load("mint_sessions")
OWNER, MANAGER = {"Authorization": "Bearer owner-t"}, {"Authorization": "Bearer manager-t"}
SEEDED = {"created": [{"id": ID, "owner_user_id": "o", "symbol": "BTCUSDT", "label": "a", "v": 1}]}
URL = "http://127.0.0.1:1"


def _api(owner: list[dict[str, Any]], manager: list[dict[str, Any]]) -> iso.Send:
    """GET /drawings as each session: its rows."""

    def send(method: str, target: str, path: str, body: Any, headers: dict[str, str]) -> Any:
        assert (method, path) == ("GET", "/drawings?symbol=BTCUSDT&limit=500")
        rows = owner if headers["Authorization"] == OWNER["Authorization"] else manager
        return 200, {"items": rows, "meta": {"next_cursor": None}}

    return send


def _problems(owner: list[dict[str, Any]], manager: list[dict[str, Any]]) -> list[str]:
    return iso.verify(_api(owner, manager), URL, OWNER, MANAGER, SEEDED)


def _row(**change: Any) -> dict[str, Any]:
    return {**SEEDED["created"][0], **change}


def test_the_unchanged_row_and_a_manager_with_none_of_the_owners_pass() -> None:
    assert _problems([_row()], [_row(id="m", owner_user_id="m")]) == []


@pytest.mark.parametrize(
    ("owner", "text"),
    [
        ([_row(label="zap probe")], "changed (label)"),  # a PUT
        ([_row(v=2)], "changed (v)"),  # any field, the concurrency token among them
        ([], "is gone: a cross-owner delete"),
        ([_row(), _row(id="x")], "drawing x the seed did not make appeared"),
    ],
)
def test_an_owner_row_that_changed_went_or_appeared_fails_naming_it(
    owner: list[dict[str, Any]], text: str
) -> None:
    assert any(text in problem for problem in _problems(owner, []))


@pytest.mark.parametrize("leak", [_row(owner_user_id="m"), _row(id="y")])  # by id, by owner
def test_a_manager_list_holding_an_owner_row_fails_as_a_cross_owner_read(
    leak: dict[str, Any],
) -> None:
    (problem,) = _problems([_row()], [leak])
    assert "the Manager lists the Owner's drawing" in problem


@pytest.mark.parametrize(
    "answer",
    [
        (503, {"items": []}),
        (200, None),
        (200, {"items": "x"}),
        (200, {"items": [], "meta": {"next_cursor": "c"}}),
    ],
)
def test_a_list_that_is_no_page_or_is_longer_than_one_fails_closed(answer: tuple[int, Any]) -> None:
    with pytest.raises(iso.Refused, match="GET /drawings"):
        iso.listing(lambda *a: answer, URL, MANAGER, "BTCUSDT")


def test_the_seed_posts_the_fixture_whole_and_a_batch_that_made_other_rows_fails() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sent: list[Any] = []

    def send(method: str, target: str, path: str, body: Any, headers: dict[str, str]) -> Any:
        sent.append((method, path, body))
        return 200, {"created": [{"id": ID}]}

    assert iso.seed(send, URL, OWNER, fixture) == {"created": [{"id": ID}]}
    assert sent == [("POST", "/drawings/batch", fixture)]
    for answer in [
        (409, {}),
        (200, {"created": []}),
        (200, {"created": [{"id": "x"}]}),
        (200, None),
    ]:
        with pytest.raises(iso.Refused, match="not every fixture row was created"):
            iso.seed(lambda *a, answer=answer: answer, URL, OWNER, fixture)


@pytest.mark.parametrize(
    "target",
    [
        "https://127.0.0.1:8000",
        "http://evil.example:8000",
        "http://127.0.0.1.evil.example",
        "http://127.0.0.1:8000/x",
        "http://u@127.0.0.1:8000",
    ],
)
def test_the_loopback_is_the_only_target_as_for_the_session_mint(target: str) -> None:
    for check, refused in ((iso.check_target, iso.Refused), (mint.check_target, mint.MintFailed)):
        assert check("http://localhost:18000/") == "http://localhost:18000"
        with pytest.raises(refused):
            check(target)


def test_a_session_file_becomes_the_headers_a_browser_sends_and_one_without_is_refused(
    tmp_path: Path,
) -> None:
    session = tmp_path / "s.env"
    session.write_text("ZAP_AUTH_TOKEN=bear\nZAP_CSRF_TOKEN=csrf\n", encoding="ascii")
    assert iso.session_headers(session) == {
        "Authorization": "Bearer bear",
        "X-CSRF-Token": "csrf",
        "Cookie": "__Host-cv_csrf=csrf",
    }
    session.write_text("ZAP_AUTH_TOKEN=bear\n", encoding="ascii")
    with pytest.raises(iso.Refused, match=r"s\.env holds no session") as refused:
        iso.session_headers(session)
    assert "bear" not in str(refused.value)


class _Connection:
    """`http.client.HTTPConnection` that records the request and answers `answer`."""

    sent: ClassVar[list[tuple[Any, ...]]] = []
    answer: ClassVar[tuple[int, bytes]] = (200, b'{"ok": true}')

    def __init__(self, host: str, port: int | None, timeout: float) -> None:
        self.sent.append((host, port))

    def request(self, method: str, path: str, body: bytes | None, headers: dict[str, str]) -> None:
        self.sent.append((method, path, body, headers))

    def getresponse(self) -> Any:
        return SimpleNamespace(status=self.answer[0], read=lambda size: self.answer[1])

    def close(self) -> None:
        pass


def test_exchange_sends_the_session_and_the_body_and_reads_only_a_json_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(iso.http.client, "HTTPConnection", _Connection)
    session = {"Authorization": "Bearer b", "X-CSRF-Token": "c", "Cookie": "__Host-cv_csrf=c"}
    assert iso.exchange("POST", URL, "/drawings/batch", {"a": 1}, session) == (200, {"ok": True})
    host, request = _Connection.sent
    assert host == ("127.0.0.1", 1) and request[:3] == ("POST", "/drawings/batch", b'{"a": 1}')
    assert request[3] == {"Content-Type": "application/json", **session}
    for raw in (b"<html>", b"\xff\xfa", b""):
        _Connection.answer = (502, raw)
        assert iso.exchange("POST", URL, "/x", None, {}) == (502, None)


def test_main_seeds_to_a_file_and_verifies_from_it_and_prints_no_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("owner", "manager"):
        (tmp_path / f"{name}.env").write_text(f"ZAP_AUTH_TOKEN={name}-t\nZAP_CSRF_TOKEN=c\n")
    out, row, owner = tmp_path / "rows.json", SEEDED["created"], str(tmp_path / "owner.env")
    seeding: iso.Send = lambda *a: (200, {"created": row})  # noqa: E731 - a stand-in
    seed = ["seed", "--target", URL, "--session", owner, "--fixture", str(FIXTURE)]
    assert iso.main([*seed, "--out", str(out)], seeding) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"created": row}
    check = ["verify", "--target", URL, "--seeded", str(out), "--owner-session", owner]
    check += ["--manager-session", str(tmp_path / "manager.env")]
    assert iso.main(check, _api(row, [])) == 0
    assert iso.main(check, _api([], row)) == 1  # the row gone, and listed for the Manager
    seen = capsys.readouterr().out
    assert "owner-t" not in seen and "manager-t" not in seen
    assert "is gone" in seen and "the Manager lists" in seen
    remote: iso.Send = lambda *a: pytest.fail("a call to a remote target")  # noqa: E731
    away = ["seed", "--target", "https://staging.example", "--session", owner]
    assert iso.main([*away, "--fixture", str(FIXTURE), "--out", str(out)], remote) == 1
