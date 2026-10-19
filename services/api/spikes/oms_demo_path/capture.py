"""Recording for the E29-K01 harness: REST round trips, reply shapes, fixture staging.

`RestRecorder` is the `GuardedTransport` callback. It keeps one `RestSample` per HTTP exchange
(the round-trip data) and the first reply per `(path, retCode, HTTP status)`, scrubbed as it is
recorded: those are the fixture captures. The key-info reply is never kept. `FixtureSink` writes
the captures and the scrubbed private-stream frames in the `packages/fixtures/bybit/<date>/`
layout (`rest/*.json`, `ws/*.jsonl`, manifest entries, README lines) under a staging directory;
the owner reviews them before anything moves into `packages/fixtures`.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx
import structlog

from .safety import DEMO_REST_HOST, DEMO_WS_URL
from .scrub import LeakError, Scrubber

#: The harness operation a request belongs to (`create`, `amend`, `skew`, `burst`, ...).
OP: ContextVar[str] = ContextVar("op", default="read")
_NOT_KEPT: Final = frozenset({"/v5/user/query-api"})
_HEADERS: Final = (
    "x-bapi-limit",
    "x-bapi-limit-status",
    "x-bapi-limit-reset-timestamp",
    "retry-after",
)
_MAX_SAMPLES: Final = 200_000
_MAX_WS_LINES: Final = 50_000
_MAX_TEXT: Final = 4096
SOURCE: Final = "services/api/spikes/oms_demo_path (E29-K01, #843)"


def _log() -> Any:
    return structlog.get_logger(__name__)


@contextlib.contextmanager
def labelled(op: str) -> Iterator[None]:
    token = OP.set(op)
    try:
        yield
    finally:
        OP.reset(token)


@dataclass(frozen=True, slots=True)
class RestSample:
    t_ms: int
    op: str
    method: str
    path: str
    status: int
    ret_code: int | None
    rtt_ms: float


@dataclass(frozen=True, slots=True)
class Capture:
    """One reply shape, already scrubbed: a JSON value, or the text of a non-JSON reply."""

    op: str
    method: str
    path: str
    status: int
    ret_code: int | None
    ret_msg: str
    headers: dict[str, str]
    body: Any
    is_json: bool


class RestRecorder:
    def __init__(self, scrubber: Scrubber) -> None:
        self._scrubber = scrubber
        self.samples: list[RestSample] = []
        self.captures: dict[tuple[str, int | None, int], Capture] = {}

    def __call__(
        self, request: httpx.Request, status: int, headers: httpx.Headers, raw: bytes, rtt_s: float
    ) -> None:
        try:
            body, is_json = json.loads(raw), True
        except ValueError:
            body, is_json = raw[:_MAX_TEXT].decode("utf-8", "replace"), False
        code = body.get("retCode") if isinstance(body, dict) else None
        ret_code = code if isinstance(code, int) and not isinstance(code, bool) else None
        path, op = request.url.path, OP.get()
        if len(self.samples) < _MAX_SAMPLES:
            now_ms = int(time.time() * 1e3)
            sample = RestSample(now_ms, op, request.method, path, status, ret_code, rtt_s * 1e3)
            self.samples.append(sample)
        key = (path, ret_code, status)
        if path in _NOT_KEPT or key in self.captures:
            return
        with contextlib.suppress(ValueError):  # the request's ids first, for a retMsg echoing one
            self._scrubber.scrub(json.loads(request.content or b"{}"))
        scrubbed = self._scrubber.scrub(body)
        ret_msg = scrubbed.get("retMsg") if isinstance(scrubbed, dict) else None
        kept = {name: headers[name] for name in _HEADERS if name in headers}
        self.captures[key] = Capture(
            op, request.method, path, status, ret_code, str(ret_msg or ""), kept, scrubbed, is_json
        )


def _cap(size: int) -> int:
    return max(4000, (size * 5 // 4 // 1000 + 1) * 1000)


class FixtureSink:
    """Scrubbed captures in the corpus layout; a leak withholds a file, it never writes it."""

    def __init__(
        self, root: Path, *, symbol: str, mode: str, date: str, scrubber: Scrubber
    ) -> None:
        self.dir = root / "bybit" / date
        self._symbol, self._mode, self._date, self._scrubber = symbol, mode, date, scrubber
        self._ws_lines: list[str] = []
        self.ws_withheld: list[str] = []

    def ws_frame(self, frame: dict[str, Any]) -> None:
        if self.ws_withheld or len(self._ws_lines) >= _MAX_WS_LINES:
            return
        try:
            self._ws_lines.append(self._scrubber.dumps(frame))
        except LeakError as exc:
            self.ws_withheld = exc.patterns
            _log().warning("ws_capture_withheld", patterns=exc.patterns)

    def write(self, captures: dict[tuple[str, int | None, int], Capture]) -> list[dict[str, Any]]:
        """Write every capture and the stream lines; returns the manifest entries."""
        entries: list[dict[str, Any]] = []
        for c in captures.values():
            code = c.ret_code if c.ret_code is not None else f"http{c.status}"
            stem = f"rest/{c.path.removeprefix('/v5/').replace('/', '_')}_{code}"
            text = json.dumps(c.body, ensure_ascii=False, indent=2) if c.is_json else c.body
            try:
                self._scrubber.check(text)
            except LeakError as exc:
                _log().warning("rest_capture_withheld", path=c.path, patterns=exc.patterns)
                continue
            name = stem + (".json" if c.is_json else ".txt")
            event = f"{c.op}: retCode {c.ret_code}, HTTP {c.status}"
            entry = self._put(name, text + "\n", f"{c.method} {c.path}", event, c.status)
            entries.append({**entry, "headers": c.headers} if c.headers else entry)
        if self._ws_lines and not self.ws_withheld:
            name = f"ws/private_{self._mode}_{self._symbol}.jsonl"
            event = f"{len(self._ws_lines)} private frames in receipt order (auth, subscribe, data)"
            entries.append(self._put(name, "\n".join(self._ws_lines) + "\n", "private", event, 101))
        self._index(entries)
        return entries

    def _put(self, name: str, text: str, stream: str, event: str, status: int) -> dict[str, Any]:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        host = DEMO_REST_HOST if stream != "private" else DEMO_WS_URL.split("/")[2]
        return {
            "path": name,
            "symbol": self._symbol,
            "stream": stream,
            "host": host,
            "capture_date": self._date,
            "source": SOURCE,
            "notable_event": event,
            "http_status": status,
            "size_cap_bytes": _cap(len(text.encode())),
        }

    def _index(self, entries: list[dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        manifest = json.dumps({"capture_date": self._date, "fixtures": entries}, indent=2)
        (self.dir / "manifest.json").write_text(manifest + "\n", encoding="utf-8")
        lines = [
            f"`{e['path']}`: recorded by `{SOURCE}` on {self._date} from `{e['host']}` "
            f"({e['stream']}), env=demo, symbol {self._symbol}. Redaction: credential fields "
            "masked; UIDs and account, connection, message, cursor and order ids replaced by "
            "stable stand-ins; leak-checked. Owner review pending."
            for e in entries
        ]
        readme = "# E29-K01 demo order-path captures\n\n" + "\n\n".join(lines) + "\n"
        (self.dir / "README.e29-k01.md").write_text(readme, encoding="utf-8")
