"""Shared helpers of the alert write bounds tests (E40-X01 Part B, #5696): each alert write on its
own app with the state a refusal must leave as it was, bodies sized by the bounds, and a write
bucket on a fake monotonic clock (no test sleeps)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from candleviewer.api.alerts import ALERT_WRITE_BURST, ALERT_WRITES_PER_MINUTE
from candleviewer.api.drawings_limiter import DrawingsWriteLimiter
from candleviewer.rules.compiler.common import count_values
from tests.alerts._alert_api_env import PRICE_CROSS
from tests.alerts._alert_api_env import Env as AlertsEnv
from tests.alerts._deliveries_env import Env as DeliveriesEnv

OUTCOME = {"outcome": "shown", "permission": "granted"}
#: The five alert writes that read a body.
BODY_ROUTES = ("create", "update", "enabled", "snooze", "desktop")
#: An alert id no test creates (a fixed one keeps the tests seeded).
NO_ALERT = "00000000-0000-4000-8000-0000000000ee"
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


class Clock:
    """A fake monotonic clock: it moves only when a test moves it."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def bucket(clock: Clock) -> DrawingsWriteLimiter:
    """The alert writes' bucket (its numbers), on *clock*."""
    return DrawingsWriteLimiter(
        per_minute=ALERT_WRITES_PER_MINUTE, burst=ALERT_WRITE_BURST, clock=clock
    )


def limited(op: str, clock: Clock) -> Target:
    """*op* on an app whose bucket runs on *clock*, full again once the setup's create is done."""
    t = target(op, limiter=bucket(clock))
    clock.t += 60.0
    return t


def spend(t: Target) -> None:
    """The burst: each write takes a token, whatever it answers."""
    assert all(t.write().status_code != 429 for _ in range(ALERT_WRITE_BURST))
