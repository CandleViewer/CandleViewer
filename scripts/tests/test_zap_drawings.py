"""E14-X03 (#549, AC4): `security/zap/drawings_isolation.py`, the Owner's drawing seeded before the
ZAP drawings scan, written to by the Manager and checked after it. A stand-in API for the logic, a
stand-in connection for the requests (the loopback only), no ZAP and no stack."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / ".zap/e14-drawings-seed.json"
OP = json.loads(FIXTURE.read_text(encoding="utf-8"))["operations"][0]
ID = OP["id"]
COMPONENTS = yaml.safe_load((ROOT / "docs/plan/22-api-openapi.yaml").read_text(encoding="utf-8"))[
    "components"
]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"zap_{name}", ROOT / f"security/zap/{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


iso, mint = _load("drawings_isolation"), _load("mint_sessions")
OWNER, MANAGER = {"Authorization": "Bearer owner-t"}, {"Authorization": "Bearer manager-t"}
#: The Owner's row as the stack answers the seed (22-api `Drawing`), its defaults filled in.
ROW = {
    "id": ID,
    "owner_user_id": "0193f2bb-0000-7000-8000-0000000000a1",
    **OP["drawing"],
    **{"layout_id": None, "style": {}, "locked": False, "visible": True, "z_index": 0},
    **{"created_at": "2026-10-24T03:57:01.123456Z", "updated_at": "2026-10-24T03:57:02.654321Z"},
}
SEEDED = {"created": [ROW]}
URL = "http://127.0.0.1:1"
CONFLICT = {"code": "conflict", "errors": [{"field": "operations.0", "rule": "target_unavailable"}]}
#: The contract's refusal of each write of the Manager's to the Owner's row (DR20, DR21).
REFUSED = {
    "batch update": (409, CONFLICT),
    "batch delete": (409, CONFLICT),
    "PUT": (404, {"code": "not_found"}),
    "DELETE": (404, {"code": "not_found"}),
}


def _api(
    owner: list[dict[str, Any]],
    manager: list[dict[str, Any]],
    writes: dict[str, tuple[int, Any]] | None = None,
) -> iso.Send:
    """GET /drawings as each session: its rows, on one page. A write, the Manager's: the contract's
    refusal, or the answer `writes` names for that probe."""
    answers = {**REFUSED, **(writes or {})}

    def send(method: str, target: str, path: str, body: Any, headers: dict[str, str]) -> Any:
        if method == "GET":
            assert path == "/drawings?symbol=BTCUSDT&limit=500"
            rows = owner if headers["Authorization"] == OWNER["Authorization"] else manager
            return 200, {"items": rows, "meta": {"next_cursor": None}}
        assert headers["Authorization"] == MANAGER["Authorization"]  # every write is the Manager's
        return answers[f"batch {body['operations'][0]['op']}" if method == "POST" else method]

    return send


def _problems(
    owner: list[dict[str, Any]],
    manager: list[dict[str, Any]],
    writes: dict[str, tuple[int, Any]] | None = None,
) -> list[str]:
    return iso.verify(_api(owner, manager, writes), URL, OWNER, MANAGER, SEEDED)


def _row(**change: Any) -> dict[str, Any]:
    return {**SEEDED["created"][0], **change}


def _valid(body: Any, schema: str) -> None:
    jsonschema.validate(body, {"$ref": f"#/components/schemas/{schema}", "components": COMPONENTS})


def test_the_unchanged_row_and_a_manager_with_none_of_the_owners_pass() -> None:
    _valid(ROW, "Drawing")
    assert _problems([_row()], [_row(id="m", owner_user_id="m")]) == []


def test_the_manager_writes_to_the_owners_row_first_with_bodies_only_the_owner_check_refuses() -> (
    None
):
    """The batch while the seed's token is still the row's, then the PUT and the DELETE; each body
    passes the contract's validation (22-api), so nothing but the owner check can refuse it."""
    sent: list[tuple[str, str, Any, dict[str, str]]] = []
    api = _api([_row()], [])

    def send(method: str, target: str, path: str, body: Any, headers: dict[str, str]) -> Any:
        sent.append((method, path, body, headers))
        return api(method, target, path, body, headers)

    assert iso.verify(send, URL, OWNER, MANAGER, SEEDED) == []
    assert [method for method, *_ in sent] == ["POST", "POST", "PUT", "DELETE", "GET", "GET"]
    assert all(headers == MANAGER for *_, headers in sent[:4])
    drawing = {  # the row's input, no id, owner or token; only the label differs
        **OP["drawing"],
        **{"layout_id": None, "style": {}, "locked": False, "visible": True, "z_index": 0},
        "label": iso.PROBE_LABEL,
    }
    token = ROW["updated_at"]
    update = {"operations": [{"op": "update", "id": ID, "if_match": token, "drawing": drawing}]}
    delete = {"operations": [{"op": "delete", "id": ID, "if_match": token}]}
    path = f"/drawings/{ID}"
    assert [call[1:3] for call in sent[:4]] == [
        ("/drawings/batch", update),
        ("/drawings/batch", delete),
        (path, drawing),
        (path, None),
    ]
    _valid(update, "DrawingBatchRequest")
    _valid(delete, "DrawingBatchRequest")
    _valid(drawing, "DrawingInput")


@pytest.mark.parametrize(
    ("probe", "answer", "threat"),
    [
        ("batch update", (200, {"updated": [ID]}), "DR12, DR21"),
        ("batch delete", (200, {"deleted": [ID]}), "DR12, DR21"),
        ("PUT", (200, {}), "DR12, DR20"),
        ("DELETE", (204, None), "DR12, DR20"),
    ],
)
def test_a_cross_owner_write_the_api_let_through_fails_naming_it(
    probe: str, answer: tuple[int, Any], threat: str
) -> None:
    name = f"the Manager's {probe} of the Owner's drawing {ID}"
    wanted = f"{name} answered HTTP {answer[0]}: a cross-owner write ({threat})"
    assert _problems([_row()], [], {probe: answer}) == [wanted]


@pytest.mark.parametrize(
    ("probe", "answer", "said"),
    [
        (
            "PUT",
            (422, {"code": "validation_failed", "errors": [{"rule": "target_unavailable"}]}),
            "HTTP 422 validation_failed, not 404 not_found",  # a rule counts only in a conflict
        ),
        ("DELETE", (404, {"detail": "Not Found"}), "HTTP 404 (no code), not 404 not_found"),
        ("DELETE", (403, None), "HTTP 403 (no code), not 404 not_found"),
        (
            "batch delete",
            (409, {"code": "conflict", "errors": []}),
            "HTTP 409 conflict, not 409 target_unavailable",
        ),
        (
            "batch update",
            (409, {"code": "conflict", "errors": ["target_unavailable"]}),
            "HTTP 409 (no code), not 409 target_unavailable",
        ),
        (
            "batch delete",
            (422, {"code": "validation_failed"}),
            "HTTP 422 validation_failed, not 409 target_unavailable",
        ),
    ],
)
def test_a_write_refused_before_the_owner_check_fails_as_a_probe_that_proved_nothing(
    probe: str, answer: tuple[int, Any], said: str
) -> None:
    (problem,) = _problems([_row()], [], {probe: answer})
    assert problem == (
        f"the Manager's {probe} of the Owner's drawing {ID} answered {said}:"
        " the probe never reached the owner check"
    )


@pytest.mark.parametrize(
    ("owner", "text"),
    [
        ([_row(label="zap probe")], "changed (label)"),  # a PUT
        ([_row(updated_at="2026-10-24T04:00:00.000000Z")], "changed (updated_at)"),  # the token too
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
        (503, {"items": [], "meta": {}}),
        (200, None),
        (200, {"items": "x", "meta": {}}),
        (200, {"items": []}),  # no meta, so no word on a next page
        (200, {"items": [], "meta": None}),
        (200, {"items": ["x"], "meta": {}}),
        (200, {"items": [{"id": "x"}], "meta": {}}),  # no owner to judge it by
        (200, {"items": [{"owner_user_id": "m"}], "meta": {}}),
    ],
)
def test_a_list_that_is_no_page_of_drawings_fails_closed(answer: tuple[int, Any]) -> None:
    with pytest.raises(iso.Refused, match="GET /drawings"):
        iso.listing(lambda *a: answer, URL, MANAGER, "BTCUSDT")


def test_a_next_cursor_that_is_no_string_fails_closed_before_another_call() -> None:
    calls: list[str] = []

    def send(method: str, target: str, path: str, body: Any, headers: dict[str, str]) -> Any:
        calls.append(path)
        return 200, {"items": [], "meta": {"next_cursor": 5}}

    with pytest.raises(iso.Refused, match="GET /drawings: a next_cursor that is no string"):
        iso.listing(send, URL, MANAGER, "BTCUSDT")
    assert calls == ["/drawings?symbol=BTCUSDT&limit=500"]


def test_the_list_is_read_to_its_last_page_and_more_than_twenty_pages_fail_closed() -> None:
    """A scan's rows can fill pages; the walk reads them all, up to `MAX_PAGES` (cursors live an
    hour, 22-api), its cursor sent encoded."""
    pages = {"": ("a", "c1"), "c1": ("b", "c+/="), "c+/=": ("c", None)}
    paths: list[str] = []

    def send(method: str, target: str, path: str, body: Any, headers: dict[str, str]) -> Any:
        paths.append(path)
        item, cursor = pages[parse_qs(urlsplit(path).query).get("cursor", [""])[0]]
        return 200, {"items": [{"id": item, "owner_user_id": "m"}], "meta": {"next_cursor": cursor}}

    assert [row["id"] for row in iso.listing(send, URL, MANAGER, "BTCUSDT")] == ["a", "b", "c"]
    first = "/drawings?symbol=BTCUSDT&limit=500"
    assert paths == [first, f"{first}&cursor=c1", f"{first}&cursor=c%2B%2F%3D"]
    calls: list[str] = []

    def endless(method: str, target: str, path: str, body: Any, headers: dict[str, str]) -> Any:
        calls.append(path)
        return 200, {"items": [], "meta": {"next_cursor": "c"}}

    with pytest.raises(iso.Refused, match="GET /drawings: over 20 pages"):
        iso.listing(endless, URL, MANAGER, "BTCUSDT")
    assert len(calls) == iso.MAX_PAGES == 20


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
        (201, {"created": [{"id": ID}]}),  # only the batch's 200 is its success
        (200, {"created": []}),
        (200, {"created": [{"id": "x"}]}),
        (200, None),
    ]:
        with pytest.raises(iso.Refused, match="not every fixture row was created"):
            iso.seed(lambda *a, answer=answer: answer, URL, OWNER, fixture)


@pytest.mark.parametrize(
    ("probe", "answer", "said", "threat"),
    [
        ("PUT", (412, {"code": "version_conflict"}), "version_conflict", "DR12, DR20"),
        (
            "batch delete",
            (409, {**CONFLICT, "errors": [{"rule": "version_conflict"}]}),
            "version_conflict",
            "DR12, DR21",
        ),
        (
            "batch update",
            (422, {"code": "validation_failed", "errors": [{"rule": "immutable_field"}]}),
            "immutable_field",
            "DR12, DR21",
        ),
    ],
)
def test_a_write_refused_only_on_the_rows_own_terms_got_past_the_owner_check(
    probe: str, answer: tuple[int, Any], said: str, threat: str
) -> None:
    """The token and the immutable fields are checked after the owner: a probe meeting one
    reached the Owner's row, a cross-owner write the row's own terms alone refused."""
    (problem,) = _problems([_row()], [], {probe: answer})
    assert problem == (
        f"the Manager's {probe} of the Owner's drawing {ID} answered HTTP {answer[0]} {said}:"
        f" past the owner check, a cross-owner write refused only on the row's own terms ({threat})"
    )


@pytest.mark.parametrize(
    "target",
    [
        "https://127.0.0.1:8000",
        "http://evil.example:8000",
        "http://127.0.0.1.evil.example",
        "http://127.0.0.1:8000/x",
        "http://u@127.0.0.1:8000",
        "http://127.0.0.1:8000?x=1",
        "http://127.0.0.1:8000#x",
    ],
)
def test_the_loopback_is_the_only_target_as_for_the_session_mint(target: str) -> None:
    for check, refused in ((iso.check_target, iso.Refused), (mint.check_target, mint.MintFailed)):
        assert check("http://localhost:18000/") == "http://localhost:18000"
        with pytest.raises(refused):
            check(target)


@pytest.mark.parametrize("target", ["http://127.0.0.1:port", "http://127.0.0.1:65536"])
def test_a_target_whose_port_is_no_port_is_refused_before_any_call(target: str) -> None:
    with pytest.raises(iso.Refused, match=r"only http://127\.0\.0\.1:<port>"):
        iso.check_target(target)


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
    for half in ("ZAP_AUTH_TOKEN=bear\n", "ZAP_CSRF_TOKEN=csrf\n"):  # a bearer or a pair alone
        session.write_text(half, encoding="ascii")
        with pytest.raises(iso.Refused, match=r"s\.env holds no session") as refused:
            iso.session_headers(session)
        assert "bear" not in str(refused.value) and "csrf" not in str(refused.value)


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
    monkeypatch.setattr(_Connection, "sent", [])  # its own record, however often the test runs
    monkeypatch.setattr(_Connection, "answer", (200, b'{"ok": true}'))
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

    def seeding(*_: Any) -> tuple[int, Any]:
        return 200, {"created": row}

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

    def remote(*_: Any) -> tuple[int, Any]:
        pytest.fail("a call to a remote target")

    away = ["seed", "--target", "https://staging.example", "--session", owner]
    assert iso.main([*away, "--fixture", str(FIXTURE), "--out", str(out)], remote) == 1


@pytest.mark.parametrize(
    "seeded",
    [
        [],
        {"created": "x"},
        {"created": ["x"]},
        {"created": []},
        {"created": [{**ROW, "id": "not-a-uuid"}]},
        {"created": [{key: value for key, value in ROW.items() if key != "updated_at"}]},
    ],
)
def test_main_reports_a_seeded_file_that_holds_no_rows_as_an_error_line_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seeded: Any
) -> None:
    for name in ("owner", "manager"):
        (tmp_path / f"{name}.env").write_text(f"ZAP_AUTH_TOKEN={name}-t\nZAP_CSRF_TOKEN=c\n")
    (rows := tmp_path / "rows.json").write_text(json.dumps(seeded), encoding="utf-8")
    check = ["verify", "--target", URL, "--seeded", str(rows)]
    check += ["--owner-session", str(tmp_path / "owner.env")]
    check += ["--manager-session", str(tmp_path / "manager.env")]
    assert iso.main(check, _api([ROW], [])) == 1
    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("::error title=drawings_isolation::")
