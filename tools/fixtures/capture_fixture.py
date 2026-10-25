"""Capture tool (E08-T05): record raw Bybit public WS frames into the fixture corpus.

    python tools/fixtures/capture_fixture.py --topic publicTrade.BTCUSDT --frames 500 \
        --out packages/fixtures/bybit/<date>/ws/clean_publicTrade_BTCUSDT.jsonl

S-RL (#913): `--rest-path` records ONE public market REST reply instead (`GET` on
`api.bybit.com`, a `/v5/market/<name>` path only, query params from `--param k=v`):

    python tools/fixtures/capture_fixture.py --rest-path /v5/market/risk-limit \
        --param category=linear --param symbol=BTCUSDT \
        --out packages/fixtures/bybit/<date>/rest/risk_limit_BTCUSDT.json

There is no auth path in either mode: no header, key or signature is ever built or sent,
and a credential-shaped `--param` key is refused. Only an HTTP 200 reply with `retCode` 0 is
recorded; the reply is streamed and the capture aborts once it passes `--size-cap` bytes.
`--frames` belongs to the WS mode and is rejected with `--rest-path`.
Public data only (no credentials are ever read: private fixtures are E29).
Every frame is passed through `redact()` and re-checked with `find_leaks()`
before it is written; a frame that still leaks aborts the capture. Output is
newline-delimited raw frames plus a `<out>.manifest.json` entry in the corpus
manifest shape. NEVER run from tests/CI (C-13.5): tests inject a fake connector.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import re
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

if __package__ in (None, ""):  # pragma: no cover - script entry
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.fixtures.redact import _SENSITIVE_KEYS, find_leaks, redact

#: Mainnet public stream (demo has no public feed of its own, C-2.11).
PUBLIC_URL = "wss://stream.bybit.com/v5/public/linear"
HOST = "stream.bybit.com"
DEFAULT_SIZE_CAP = 512_000
#: Mainnet public REST (public market data has no demo feed of its own, C-2.11).
PUBLIC_REST_URL = "https://api.bybit.com"
REST_HOST = "api.bybit.com"
#: The only path prefix the REST mode will call: public market data, never a private route.
PUBLIC_REST_PREFIX = "/v5/market/"
#: Allowlist for the whole path: one lowercase segment under the prefix, nothing else.
_PUBLIC_REST_PATH = re.compile(r"/v5/market/[a-z0-9-]+")
#: Query keys that would only ever carry auth (the redactor's key list plus Bybit's signing inputs).
_CREDENTIAL_PARAM = re.compile(rf"(?:{_SENSITIVE_KEYS}|timestamp|recv_window|recvWindow)", re.I)
DEFAULT_FRAMES = 500


class Socket(Protocol):
    async def send(self, frame: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[Socket]]
#: `(url, params) -> (http_status, body text)`. Takes no headers, so no auth can be sent.
Getter = Callable[[str, Mapping[str, str]], Awaitable[tuple[int, str]]]


class CaptureError(RuntimeError):
    """Capture aborted: leak after redaction, size cap exceeded, or no data."""


@dataclass(frozen=True)
class CaptureResult:
    frames: int
    bytes_written: int
    manifest: dict[str, Any]


def _is_data_frame(frame: str, topic: str) -> bool:
    try:
        msg = json.loads(frame)
    except ValueError:
        return False
    return isinstance(msg, dict) and msg.get("topic") == topic


async def capture(
    topic: str,
    out: Path,
    *,
    max_frames: int,
    connect: Connector,
    notable_event: str = "clean window",
    size_cap: int = DEFAULT_SIZE_CAP,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CaptureResult:
    """Subscribe to `topic`, record `max_frames` redacted data frames, write file + manifest."""
    if max_frames <= 0:
        raise ValueError("max_frames must be > 0")
    sock = await connect(PUBLIC_URL)
    lines: list[str] = []
    size = 0
    first_ts: int | None = None
    last_ts: int | None = None
    try:
        await sock.send(json.dumps({"op": "subscribe", "args": [topic]}))
        while len(lines) < max_frames:
            raw = await sock.recv()
            if not _is_data_frame(raw, topic):
                continue  # subscribe acks / pongs are not part of the fixture
            clean = redact(raw)
            leaks = find_leaks(clean)
            if leaks:
                raise CaptureError(f"frame still matches secret patterns after redaction: {leaks}")
            size += len(clean.encode()) + 1
            if size > size_cap:
                raise CaptureError(f"capture exceeds the {size_cap}-byte cap; lower --frames")
            ts = json.loads(clean).get("ts")
            if isinstance(ts, int):
                first_ts = ts if first_ts is None else first_ts
                last_ts = ts
            lines.append(clean)
    finally:
        await sock.close()
    parts = topic.split(".")
    entry: dict[str, Any] = {
        "path": f"ws/{out.name}",
        "symbol": parts[-1],
        "stream": topic,
        "host": HOST,
        "capture_date": now().date().isoformat(),
        "source": "capture_fixture.py",
        "notable_event": notable_event,
        "window_ms": [first_ts, last_ts],
        "http_status": 200,
        "size_cap_bytes": size_cap,
    }
    await asyncio.to_thread(_write, out, lines, entry)
    return CaptureResult(frames=len(lines), bytes_written=size, manifest=entry)


def _write(out: Path, lines: list[str], entry: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    out.with_name(out.name + ".manifest.json").write_text(
        json.dumps(entry, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


async def capture_rest(
    path: str,
    params: Mapping[str, str],
    out: Path,
    *,
    get: Getter,
    notable_event: str = "recorded reply",
    size_cap: int = DEFAULT_SIZE_CAP,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CaptureResult:
    """GET one public market reply, redact and leak-check it, write file + manifest entry."""
    if not _PUBLIC_REST_PATH.fullmatch(path):
        raise CaptureError(f"only public {PUBLIC_REST_PREFIX}<name> paths are recorded: {path!r}")
    refused = sorted(k for k in params if _CREDENTIAL_PARAM.fullmatch(k))
    if refused:
        raise CaptureError(f"credential-shaped query keys are never sent: {refused}")
    status, body = await get(PUBLIC_REST_URL + path, dict(params))
    if status != 200:
        raise CaptureError(f"HTTP {status}: only a 200 reply is recorded")
    try:
        doc = json.loads(body)
    except ValueError as exc:
        raise CaptureError(f"HTTP {status}: the reply is not JSON") from exc
    if not isinstance(doc, dict) or doc.get("retCode") != 0:
        raise CaptureError("only a retCode 0 reply is recorded")
    clean = redact(body.strip())  # the body as received, never re-serialised
    leaks = find_leaks(clean)
    if leaks:
        raise CaptureError(f"reply still matches secret patterns after redaction: {leaks}")
    size = len(clean.encode()) + 1
    if size > size_cap:
        raise CaptureError(f"reply exceeds the {size_cap}-byte cap; narrow --param")
    entry: dict[str, Any] = {
        "path": f"rest/{out.name}",
        "symbol": params.get("symbol", "*"),
        "stream": f"GET {path}",
        "host": REST_HOST,
        "capture_date": now().date().isoformat(),
        "source": "capture_fixture.py --rest-path",
        "notable_event": notable_event,
        "http_status": status,
        "size_cap_bytes": size_cap,
    }
    await asyncio.to_thread(_write, out, [clean], entry)
    return CaptureResult(frames=1, bytes_written=size, manifest=entry)


async def _http_get(
    url: str, params: Mapping[str, str], *, max_bytes: int = DEFAULT_SIZE_CAP
) -> tuple[int, str]:  # pragma: no cover - real network, manual only
    """A bare public GET, no headers, no proxy/netrc from the environment. The body is
    streamed and the capture aborts once it passes `max_bytes`."""
    import httpx

    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", url, params=dict(params)) as resp:
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    raise CaptureError(f"reply exceeds the {max_bytes}-byte cap; narrow --param")
            return resp.status_code, buf.decode(resp.encoding or "utf-8")


async def _ws_connect(url: str) -> Socket:  # pragma: no cover - real network, manual only
    from websockets.asyncio.client import connect as ws_connect

    conn = await ws_connect(url, open_timeout=10, ping_interval=20)

    class _S:
        async def send(self, frame: str) -> None:
            await conn.send(frame)

        async def recv(self) -> str:
            msg = await asyncio.wait_for(conn.recv(), timeout=30)
            return msg if isinstance(msg, str) else msg.decode()

        async def close(self) -> None:
            await conn.close()

    return _S()


def _parse_params(p: argparse.ArgumentParser, items: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for kv in items:
        k, sep, v = kv.partition("=")
        if not sep or not k:
            p.error(f"--param must be k=v with a non-empty key: {kv!r}")
        if k in params:
            p.error(f"--param {k!r} given twice")
        params[k] = v
    return params


def main(
    argv: list[str] | None = None,
    *,
    connect: Connector = _ws_connect,
    get: Getter | None = None,
) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--topic")
    mode.add_argument("--rest-path")
    p.add_argument("--param", action="append", default=[], help="k=v query param (REST mode)")
    p.add_argument("--frames", type=int, help=f"WS mode only (default {DEFAULT_FRAMES})")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--event", default="clean window")
    p.add_argument("--size-cap", type=int, default=DEFAULT_SIZE_CAP)
    ns = p.parse_args(argv)
    if ns.rest_path and ns.frames is not None:
        p.error("--frames applies to --topic only")
    params = _parse_params(p, ns.param)
    getter: Getter = get or functools.partial(_http_get, max_bytes=ns.size_cap)
    frames = DEFAULT_FRAMES if ns.frames is None else ns.frames
    try:
        if ns.rest_path:
            job = capture_rest(
                ns.rest_path, params, ns.out, get=getter, notable_event=ns.event,
                size_cap=ns.size_cap,
            )  # fmt: skip
            res = asyncio.run(job)
        else:
            res = asyncio.run(capture(ns.topic, ns.out, max_frames=frames, connect=connect,
                                      notable_event=ns.event, size_cap=ns.size_cap))  # fmt: skip
    except CaptureError as exc:
        print(f"capture aborted: {exc}", file=sys.stderr)
        return 1
    print(f"captured {res.frames} frames ({res.bytes_written} bytes) -> {ns.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
