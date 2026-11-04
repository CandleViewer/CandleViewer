"""E40-X01 Part B (#5696): the five alert writes that read a body bound it before any work.

Gherkin "an alert write is bounded before any work": over the byte cap is the declared 413, nested
past the depth cap or past the value bound the declared 422, decided before the body is decoded
(depth) or validated (values), with nothing stored or recorded. Inputs come from the constants of
`api/alert_body.py`, on the rule routes' template (#4197); `target` serves the other #5696 tests.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from candleviewer.alerts.compiler import MAX_DEPTH, AlertCompiler
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.api import alert_body
from candleviewer.api.alert_body import MAX_ALERT_BODY_BYTES, MAX_ALERT_JSON_DEPTH, MAX_ALERT_VALUES
from candleviewer.rules.compiler.common import count_values
from candleviewer.rules.vocabulary import default_registry
from tests.alerts._alert_api_env import PRICE_CROSS, USER_B
from tests.alerts._alert_api_env import Env as AlertsEnv
from tests.alerts._deliveries_env import Env as DeliveriesEnv

OUTCOME = {"outcome": "shown", "permission": "granted"}
#: 22's "256 KiB (262,144 bytes)" as a literal: a test sized from the constant would follow it.
CAP = 256 * 1024
BODY_ROUTES = ("create", "update", "enabled", "snooze", "desktop")
_BY_ID = {"update": "", "delete": "", "enabled": "/enabled", "snooze": "/snooze"}
_BODY: dict[str, Any] = {"update": PRICE_CROSS | {"name": "renamed"}, "delete": None,
                         "enabled": {"enabled": False}, "snooze": {"until": None}}  # fmt: skip


@dataclass
class Target:
    """One alert write on its own app (`env`), and the state a refusal leaves as it was."""

    env: Any
    method: str
    path: str
    body: Any
    ok: int
    state: Callable[[], Any]

    def send(self, content: bytes) -> httpx.Response:
        r: httpx.Response = self.env.c.request(self.method, self.path, content=content)
        return r

    def write(self) -> httpx.Response:
        r: httpx.Response = self.env.c.request(self.method, self.path, json=self.body)
        return r

    def snapshot(self) -> tuple[Any, int, list[str | None]]:
        """The rows, the records written and the compiles run."""
        return self.state(), len(self.env.audit.calls), list(getattr(self.env, "compiles", []))


def target(op: str, **env_kw: Any) -> Target:
    """*op*'s write as the env's first user, on a row of theirs made first (by-id writes)."""
    if op == "desktop":
        d = DeliveriesEnv(**env_kw)
        did = d.store.add(channel="desktop", status="queued").id
        path = f"/alerts/deliveries/{did}/desktop-outcome"
        return Target(d, "POST", path, OUTCOME, 204, lambda: dict(d.store.rows))
    e = AlertsEnv(**env_kw)

    def state() -> Any:
        return dict(e.repo.rows), set(e.repo.deleted)

    if op == "create":
        return Target(e, "POST", "/alerts", PRICE_CROSS, 201, state)
    path, ok = f"/alerts/{e.create()['id']}{_BY_ID[op]}", 204 if op == "delete" else 200
    return Target(e, "DELETE" if op == "delete" else "PUT", path, _BODY[op], ok, state)


async def asgi(t: Target, content: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    """*content* (an async stream) sent as is: the transport pulls a chunk only when it is read."""
    transport = httpx.ASGITransport(app=t.env.c.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(t.method, t.path, content=content, headers=headers)


def padded(body: Any, size: int) -> bytes:
    """*body* as JSON, padded with whitespace to exactly *size* bytes."""
    text = json.dumps(body)
    return (text[:-1] + " " * (size - len(text)) + text[-1]).encode()


def deep(levels: int) -> bytes:
    """A body whose deepest array sits *levels* deep, the body's own object included."""
    return ('{"pad":' + "[" * (levels - 1) + "]" * (levels - 1) + "}").encode()


def sized(body: Any, shape: str, n: int) -> Any:
    """*body* holding exactly *n* values (`count_values`, the bound's count), the rest in a
    metric's `params`, a comparison's `set_values` or a top-level `pad` list."""
    doc = json.loads(json.dumps(body))
    if shape == "padding":
        fill: Any = doc.setdefault("pad", [])
    elif shape == "params":
        fill = doc["condition_ir"]["conditions"]["left"].setdefault("params", {})
    else:
        fill = []
        doc["condition_ir"]["conditions"] = {
            "node_id": "c1", "op": "in_set", "left": {"metric": "price"}, "set_values": fill
        }  # fmt: skip
    missing = n - count_values(doc)
    if shape == "params":
        fill.update({f"p{i}": 0 for i in range(missing)})
    else:
        fill.extend(["v"] * missing)
    assert count_values(doc) == n
    return doc


def rules(r: httpx.Response) -> list[str]:
    return [e["rule"] for e in r.json().get("errors") or []]


def too_large(r: httpx.Response) -> None:
    assert (r.status_code, r.headers["content-type"]) == (413, "application/problem+json")
    detail = f"The request body exceeds {CAP} bytes."
    assert r.json() == {"type": "https://candleviewer.local/errors/payload_too_large",
                        "title": "Request body or batch exceeds the operation's size ceiling",
                        "status": 413, "code": "payload_too_large", "detail": detail}  # fmt: skip


def _chained(levels: int) -> dict[str, Any]:
    """A condition whose variable is an arithmetic chain *levels* walker levels deep, ending in
    a metric with `params`: at `MAX_DEPTH`, the deepest JSON the alert compiler takes."""
    node: dict[str, Any] = {"metric": "price", "params": {}}
    for i in range(levels - 1):
        node = {"node_id": f"a{i}", "op": "add", "operands": [node, {"const": 1}]}
    ir: dict[str, Any] = {**PRICE_CROSS["condition_ir"], "variables": {"v": node}}
    return ir


def _depth(v: Any) -> int:
    kids = list(v.values()) if isinstance(v, dict) else v if isinstance(v, list) else None
    return 0 if kids is None else 1 + max((_depth(k) for k in kids), default=0)


class _NoDecode:
    @staticmethod
    def loads(_text: str) -> Any:
        raise AssertionError("the body was decoded before its depth was checked")


ROUTES = pytest.mark.parametrize("op", BODY_ROUTES)


@ROUTES
def test_alert_body_at_the_cap_is_read_and_one_byte_over_is_413(op: str) -> None:
    """Gherkin "a body over the byte cap": the declared 413, nothing stored or recorded, counted;
    a body at the cap is read (SR-E40-17)."""
    at, over = target(op), target(op)
    assert at.send(padded(at.body, CAP)).status_code == at.ok
    before = over.snapshot()
    too_large(over.send(padded(over.body, CAP + 1)))
    assert (over.snapshot(), over.env.refused) == (before, ["body_too_large"])


@ROUTES
async def test_alert_body_declared_length_over_the_cap_is_413_unread(op: str) -> None:
    """Gherkin "before parsing the body": a declared length over the cap is refused before any
    byte is read (SR-E40-17)."""
    t, pulled = target(op), []

    async def chunks() -> AsyncIterator[bytes]:
        pulled.append(1)
        yield json.dumps(t.body).encode()

    too_large(await asgi(t, chunks(), {"content-length": str(MAX_ALERT_BODY_BYTES + 1)}))
    assert pulled == [] and t.env.refused == ["body_too_large"]


async def test_alert_body_streamed_past_the_cap_stops_one_chunk_past_it() -> None:
    """Gherkin "before parsing the body": with no length, the stream is read one chunk past the
    cap, never to its end (SR-E40-17)."""
    t, pulled = target("create"), []
    parts = [json.dumps(t.body)[:-1].encode(), *[b" " * (MAX_ALERT_BODY_BYTES // 16)] * 32, b"}"]

    async def chunks() -> AsyncIterator[bytes]:
        for part in parts:
            pulled.append(part)
            yield part

    r = await asgi(t, chunks())
    too_large(r)
    assert "content-length" not in r.request.headers
    assert len(pulled) <= 16 + 2 < len(parts) and t.state() == ({}, set())


@ROUTES
def test_alert_body_nested_past_the_bound_is_422_before_any_decode(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin "nested past the depth cap": the declared 422 "before parsing the body", nothing
    stored or recorded, counted; the bound itself passes the scan (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    with monkeypatch.context() as patch:
        patch.setattr(alert_body, "json", _NoDecode())
        r = t.send(deep(MAX_ALERT_JSON_DEPTH + 1))
    assert (r.status_code, rules(r)) == (422, ["json_too_deep"]), r.text[:300]
    assert (t.snapshot(), t.env.refused) == (before, ["json_too_deep"])
    assert "json_too_deep" not in t.send(deep(MAX_ALERT_JSON_DEPTH)).text


@ROUTES
def test_alert_body_nested_past_the_decoder_limit_is_422_never_500(op: str) -> None:
    """Gherkin "nested past the depth cap": the declared 422, never a 500, even past what the
    decoder can recurse (SR-E40-17)."""
    t = target(op)
    c = TestClient(t.env.c.app, raise_server_exceptions=False)
    r = c.request(t.method, t.path, content=deep(MAX_ALERT_BODY_BYTES // 2 - 16))
    assert (r.status_code, rules(r)) == (422, ["json_too_deep"]), r.text[:300]


def test_alert_reader_takes_the_deepest_condition_the_compiler_admits() -> None:
    """The depth cap refuses no alert the compiler takes: 67 levels, where the rule routes take
    66 (BQ-3, SR-E40-17); one walker level deeper is the compiler's own refusal."""
    body = PRICE_CROSS | {"condition_ir": _chained(MAX_DEPTH)}
    assert _depth(body) == MAX_ALERT_JSON_DEPTH
    assert target("create").send(json.dumps(body).encode()).status_code == 201
    with pytest.raises(AlertIrInvalid):
        AlertCompiler(default_registry()).compile(_chained(MAX_DEPTH + 1))


SHAPES = pytest.mark.parametrize(
    ("op", "shape"),
    [("create", "params"), ("create", "set_values"), ("create", "padding"), ("update", "params"),
     ("enabled", "padding"), ("snooze", "padding"), ("desktop", "padding")],
)  # fmt: skip


@SHAPES
def test_alert_body_over_the_value_bound_is_422_before_validation_or_compile(
    op: str, shape: str
) -> None:
    """One value past the bound (in `params`, `set_values` or anywhere): the declared 422 before
    validation or compile, nothing stored or recorded, counted (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    r = t.send(json.dumps(sized(t.body, shape, MAX_ALERT_VALUES + 1)).encode())
    assert (r.status_code, rules(r)) == (422, ["too_many_values"]), r.text[:300]
    assert (t.snapshot(), t.env.refused) == (before, ["too_many_values"])


@SHAPES
def test_alert_body_at_the_value_bound_reaches_validation(op: str, shape: str) -> None:
    """At the value bound the reader passes the body to the route's own checks (SR-E40-17)."""
    t = target(op)
    r = t.send(json.dumps(sized(t.body, shape, MAX_ALERT_VALUES)).encode())
    assert "too_many_values" not in r.text and t.env.refused == []


@ROUTES
def test_alert_body_not_utf8_is_the_routes_not_json_422(op: str) -> None:
    """A body in another encoding is the route's own 422 for one that is not JSON (RFC 8259
    section 8.1): nothing changed, nothing counted (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    r = t.send(json.dumps(t.body).encode("utf-16"))
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert (t.snapshot(), t.env.refused) == (before, [])


@ROUTES
def test_alert_bounds_answer_after_the_permission_and_ownership_checks(op: str) -> None:
    """C-12.4 first: without `alerts:write` a 403, on another user's alert or delivery a 404,
    before the body is read, so no bound is reached (SR-E40-17)."""
    t = target(op)
    over = padded(t.body, MAX_ALERT_BODY_BYTES + 1)
    t.env.perms = frozenset({"alerts:read"})
    assert t.send(over).status_code == 403 and t.env.refused == []
    if op != "create":
        theirs = target(op)
        theirs.env.user = USER_B
        assert theirs.send(over).status_code == 404 and theirs.env.refused == []
