"""The v1 frame codec of the backup sidecar's socket, server side (`24-internal-schemas.md` §15.8).

Pure functions, no I/O. A frame is `<len>\\n<body>\\n`: `len` the decimal byte length of `body`, 1
to 5 digits with no sign and no leading zero; `body` canonical JSON (members sorted, no whitespace,
ASCII only, no duplicate member, no floating-point number but `pct`) of at most `MAX_FRAME` bytes.
Canonical means byte-equal to `dumps` of what it decodes to, so one encoding exists per value.

The client half is `candleviewer/admin/backups/sidecar_wire.py`; neither imports the other (the
`independence-backup-sidecar` contract), and the golden frames in
`tests/fixtures/backup_sidecar/frames_v1.jsonl` keep the two equal.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

VERSION: Final = 1
MAX_FRAME: Final = 16384
MAX_HEADER: Final = 5  # digits
#: The id an answer carries when the request's own `id` cannot be read (§15.8).
NIL_ID: Final = "00000000-0000-0000-0000-000000000000"
OPS: Final = ("plan", "run", "verify", "remove", "restore")
ERROR_CODES: Final = (
    "bad_frame", "unsupported_version", "bad_request",
    "kind_not_supported", "recipient_mismatch",
    "runs_capped", "busy",
    "unknown_backup", "location_mismatch",
    "newest_artefact",
    "artefact_missing", "header_malformed", "digest_mismatch",
    "volume_unavailable", "database_unavailable", "tool_failed",
    "ledger_unreadable", "deadline", "restore_not_available", "internal_error",
)  # fmt: skip
#: Each op's `args` members, exactly.
ARGS: Final[Mapping[str, frozenset[str]]] = {
    "plan": frozenset({"kind"}),
    "run": frozenset({"backup_id", "kind", "location"}),
    "verify": frozenset({"backup_id", "location"}),
    "remove": frozenset({"backup_id", "location"}),
    "restore": frozenset({"job_id", "backup_id", "location", "digest"}),
}
_ENVELOPE: Final = frozenset({"v", "id", "op", "deadline_s", "args"})
MAX_DEADLINE_S: Final = 86400
MAX_LOCATION: Final = 512
_KIND: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_NAME: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.age"
)
_PATH_CHARS: Final = re.compile(r"[A-Za-z0-9._/-]+")


class ProtocolError(Exception):
    """A request refused before anything runs: `code` (`bad_frame`, `unsupported_version` or
    `bad_request`) and the request's `id` when it could be read. Never any of its text."""

    def __init__(self, code: str, request_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class Request:
    id: str
    op: str
    deadline_s: int
    args: Mapping[str, str]


def dumps(value: object) -> bytes:
    """The canonical body of `value`."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)  # fmt: skip
    return text.encode("ascii")


def frame(value: object) -> bytes:
    body = dumps(value)
    if len(body) > MAX_FRAME:
        raise ValueError("a frame body is at most MAX_FRAME bytes")
    return b"%d\n%s\n" % (len(body), body)


def parse_length(header: bytes) -> int:
    """The body length a header (without its newline) names, else `bad_frame`."""
    if not (1 <= len(header) <= MAX_HEADER and header.isdigit() and header.isascii()):
        raise ProtocolError("bad_frame")
    if header.startswith(b"0"):
        raise ProtocolError("bad_frame")
    length = int(header)
    if length > MAX_FRAME:
        raise ProtocolError("bad_frame")
    return length


class _Refused(ValueError):
    pass


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    members: dict[str, object] = {}
    for name, value in pairs:
        if name in members:
            raise _Refused
        members[name] = value
    return members


def _refuse(_: str) -> object:
    raise _Refused


def loads(body: bytes, *, floats: bool = False) -> object:
    """A canonical body's value, else `bad_frame`. `floats` admits numbers with a fraction."""
    if not (0 < len(body) <= MAX_FRAME and body.isascii()):
        raise ProtocolError("bad_frame")
    try:
        value: object = json.loads(
            body.decode("ascii"), object_pairs_hook=_unique, parse_constant=_refuse,
            parse_float=float if floats else _refuse,
        )  # fmt: skip
        canonical = dumps(value) == body
    except (ValueError, RecursionError):  # `_Refused`, a malformed body, a huge integer
        canonical = False
    if not canonical:
        raise ProtocolError("bad_frame")
    return value


def is_uuid(value: object) -> bool:
    """A UUID in its canonical lower-case form."""
    if not (isinstance(value, str) and len(value) == 36):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def is_digest(value: object) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def is_kind(value: object) -> bool:
    return isinstance(value, str) and _KIND.fullmatch(value) is not None


def is_location(value: object) -> bool:
    """`<root>/<kind>/<uuid4>.age` in shape: absolute, canonical, at most `MAX_LOCATION` bytes,
    no `..`, `//`, `://` or `@`, and no component that starts with `.`, so never one in the
    quarantine or the run record. The sidecar compares the root depth and the kind itself
    (`paths.Root.artefact`)."""
    if not (isinstance(value, str) and 0 < len(value) <= MAX_LOCATION):
        return False
    if _PATH_CHARS.fullmatch(value) is None or not value.startswith("/") or ".." in value:
        return False
    parts = value.split("/")[1:]
    if len(parts) < 3 or any(p == "" or p.startswith(".") for p in parts):
        return False
    return is_kind(parts[-2]) and _NAME.fullmatch(parts[-1]) is not None


_FIELDS: Final = {
    "kind": is_kind,
    "backup_id": is_uuid,
    "job_id": is_uuid,
    "location": is_location,
    "digest": is_digest,
}


def parse_request(body: bytes) -> Request:
    """A request frame's body, strictly: else `ProtocolError` with its code."""
    value = loads(body)
    if not isinstance(value, dict):
        raise ProtocolError("bad_request")
    request_id = value.get("id") if is_uuid(value.get("id")) else None
    if "v" not in value:
        raise ProtocolError("bad_request", request_id)
    version = value["v"]
    if type(version) is not int or version != VERSION:
        raise ProtocolError("unsupported_version", request_id)
    op, deadline, args = value.get("op"), value.get("deadline_s"), value.get("args")
    if set(value) != _ENVELOPE or request_id is None or op not in OPS:
        raise ProtocolError("bad_request", request_id)
    if type(deadline) is not int or not 1 <= deadline <= MAX_DEADLINE_S:
        raise ProtocolError("bad_request", request_id)
    if not isinstance(args, dict) or set(args) != ARGS[str(op)]:
        raise ProtocolError("bad_request", request_id)
    if not all(_FIELDS[name](member) for name, member in args.items()):
        raise ProtocolError("bad_request", request_id)
    return Request(request_id, str(op), deadline, {k: str(v) for k, v in args.items()})


def progress(request_id: str, pct: float) -> bytes:
    return frame({"v": VERSION, "id": request_id, "t": "progress", "pct": float(pct)})


def ok(request_id: str, result: Mapping[str, object]) -> bytes:
    return frame({"v": VERSION, "id": request_id, "t": "ok", "result": dict(result)})


def error(request_id: str, code: str) -> bytes:
    if code not in ERROR_CODES:
        code = "internal_error"
    return frame({"v": VERSION, "id": request_id, "t": "error", "code": code})
