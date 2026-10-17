"""#2893 S6: the test plan section 9.6 request log of the account fixture transport.

One JSON line per answer or refusal in `<CV_ACCOUNT_FIXTURE_DIR>/requests.jsonl`: the `LOG` evidence
of the E27 cases (host isolation, signing key, call counts, the plan 9.7 order and its native SL).
It never holds a signature or a secret (C-12.6). `RequestLog.write` takes allow-listed keyword
scalars only, never a request, a header map or a body; an unknown keyword is a `TypeError`.
`signing_key_id` is a pack key id or null: any other key is logged as `key_class="non_fixture"` with
no character of it. Text values match their field's rule and, but for the order-link id and the
symbol (exact shapes), carry no run of 18 or more letters and digits (a key, or a hex MAC) and not
the word "secret", which every derived pack secret holds. A line no guard may produce is refused. A
refusal names the field, never the value, and writes nothing; no field name is on the redaction
deny-list.

Neither the directory, however it is spelled, nor the file is opened through a symlink
(`O_NOFOLLOW`; Settings refuses one above the directory). The file is a regular file of this user
with one link, mode 0600, rotated at `max_bytes` into `backups` older files. The log needs
`CV_ACCOUNT_FIXTURE_DIR` (fail closed). Writes are synchronous: one short append per answer, on a
dev-only path that is not hot. Nothing here imports `candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Final, Literal, get_args

from candleviewer.domain.order_link import OUR_ID
from candleviewer.settings import Environment

FILE_NAME: Final = "requests.jsonl"
DEFAULT_MAX_BYTES: Final = 8 * 1024 * 1024
DEFAULT_BACKUPS: Final = 2
#: Every line the field rules allow is shorter, so `max_bytes` may not be smaller.
MAX_LINE_BYTES: Final = 4096

HostEnv = Literal["demo", "live", "testnet"]
Transport = Literal["rest", "ws"]
KeyClass = Literal["fixture", "non_fixture", "unsigned"]
Refusal = Literal["refused_host", "refused_key", "signature_mismatch", "refused_fund_path"]
Outcome = Literal["served", "unstubbed", "switch", Refusal]
Side = Literal["Buy", "Sell"]
OrderType = Literal["Limit", "Market"]
TriggerBy = Literal["LastPrice", "MarkPrice", "IndexPrice"]

_PACK_KEY_ID: Final = re.compile(r"fixture-[a-z0-9_]{1,64}-[0-9]{4}")
_PACK_ORDER_LINK: Final = re.compile(r"fixture-order-[0-9]{4}")
_TOKEN: Final = re.compile(r"[a-z0-9_]{1,64}")
_HOST: Final = re.compile(r"(?=.{1,253}\Z)[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+")
_PATH: Final = re.compile(r"(?:/[a-z0-9_-]{1,64}){1,8}")
_METHOD: Final = re.compile(r"[A-Z]{1,16}")
_SYMBOL: Final = re.compile(r"[0-9A-Z]{1,26}USDT")
_KEY_SHAPED: Final = re.compile(r"[A-Za-z0-9]{18,}")
_ORDER_PATHS: Final = frozenset({"/v5/order/create", "/v5/order/amend"})
#: A trading-stop sets or clears (stop_loss 0) a native SL: it logs only these (TC-316, TC-410).
_TRADING_STOP: Final = "/v5/position/trading-stop"
_STOP_FIELDS: Final = frozenset({"symbol", "stop_loss", "sl_trigger_by"})
_O_FLAGS: Final = os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS: Final = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | _O_FLAGS
_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | _O_FLAGS


class RequestLogFieldError(ValueError):
    """A field is outside its rule; the message names the field and the rule, never the value."""


class RequestLogFileError(RuntimeError):
    """The log's directory or file is missing or unsafe, or the log is closed."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderFields:
    """The order subset of an order create or amend (plan section 9.7), or the SL fields of a
    trading-stop (TC-316, TC-410), each None when the request leaves it out; logged as named."""

    order_link_id: str | None = None
    symbol: str | None = None
    side: Side | None = None
    order_type: OrderType | None = None
    qty: Decimal | None = None
    price: Decimal | None = None
    reduce_only: bool | None = None
    stop_loss: Decimal | None = None
    sl_trigger_by: TriggerBy | None = None


def _text(name: str, value: object, rule: re.Pattern[str], *, shaped: bool = False) -> str | None:
    """None, or `value` if it is text matching `rule` and, unless `shaped`, neither key-shaped nor
    naming a secret."""
    if value is None:
        return None
    if isinstance(value, str) and rule.fullmatch(value):
        if shaped or (not _KEY_SHAPED.search(value) and "secret" not in value.lower()):
            return value
    raise RequestLogFieldError(f"{name} is outside its rule")


def _choice(
    name: str, value: object, options: tuple[str, ...], *, required: bool = False
) -> str | None:
    if value is None and not required:
        return None
    if isinstance(value, str) and value in options:
        return options[options.index(value)]
    raise RequestLogFieldError(f"{name} must be one of: {', '.join(options)}")


def _flag(name: str, value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise RequestLogFieldError(f"{name} must be true, false or null")


def _int(name: str, value: object, low: int, high: int) -> int | None:
    if value is None or (type(value) is int and low <= value <= high):
        return value
    raise RequestLogFieldError(f"{name} must be an integer from {low} to {high}")


def _amount(name: str, value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal) and value.is_finite() and value >= 0:
        if len(text := format(value, "f")) <= 32:
            return text
    raise RequestLogFieldError(f"{name} must be a finite, non-negative Decimal")


def _overlays(value: object) -> list[str | None]:
    if isinstance(value, tuple | list) and len(value) <= 16 and None not in value:
        return [_text("overlays", item, _TOKEN) for item in value]
    raise RequestLogFieldError("overlays must be at most 16 scenario tokens")


def _order(order: object) -> dict[str, object] | None:
    if order is None:
        return None
    if not isinstance(order, OrderFields):
        raise RequestLogFieldError("order must be an OrderFields")
    link = order.order_link_id
    if link is not None and not (
        isinstance(link, str) and (OUR_ID.fullmatch(link) or _PACK_ORDER_LINK.fullmatch(link))
    ):
        raise RequestLogFieldError("order_link_id must be an id the OMS or the pack mints")
    return {
        "order_link_id": link,
        "symbol": _text("symbol", order.symbol, _SYMBOL, shaped=True),
        "side": _choice("side", order.side, get_args(Side)),
        "order_type": _choice("order_type", order.order_type, get_args(OrderType)),
        "qty": _amount("qty", order.qty),
        "price": _amount("price", order.price),
        "reduce_only": _flag("reduce_only", order.reduce_only),
        "stop_loss": _amount("stop_loss", order.stop_loss),
        "sl_trigger_by": _choice("sl_trigger_by", order.sl_trigger_by, get_args(TriggerBy)),
    }


def _check_against_the_guards(line: dict[str, object]) -> None:
    """Refuse a line no guard may produce: a non-fixture key or a failed signature answered, a key
    id without its class, a verdict on a key with no secret, order fields its path cannot carry."""
    key_class, verified, outcome = line["key_class"], line["verified"], line["outcome"]
    if (key_class == "fixture") != (line["signing_key_id"] is not None):
        raise RequestLogFieldError("signing_key_id is set exactly when key_class is fixture")
    if key_class != "fixture" and verified is not None:
        raise RequestLogFieldError("verified is null unless a fixture key signed the request")
    if outcome != "switch" and (line["transport"] is None or key_class is None):
        raise RequestLogFieldError("a request line needs its transport and key_class")
    if outcome in ("served", "unstubbed") and (
        key_class == "non_fixture" or (key_class == "fixture" and verified is not True)
    ):
        raise RequestLogFieldError(f"{outcome} needs a fixture key that verified, or no key")
    if outcome == "signature_mismatch" and verified is not False:
        raise RequestLogFieldError("signature_mismatch needs verified false")
    order, path = line["order"], line["path"]
    if isinstance(order, dict) and path not in _ORDER_PATHS:
        if path != _TRADING_STOP:
            raise RequestLogFieldError("order is logged for an order create, amend or trading-stop")
        if any(order[name] is not None for name in order.keys() - _STOP_FIELDS):
            raise RequestLogFieldError("a trading-stop logs only symbol, stop_loss, sl_trigger_by")


def _open_directory(directory: str | os.PathLike[str]) -> int:
    """`O_NOFOLLOW` guards the last component, but the kernel follows a symlink there when `/` or
    `/.` trails it, so pathlib drops both; a last `..`, or no name (`.`, `/`, `""`), is refused."""
    path = PurePosixPath(directory)
    msg = "CV_ACCOUNT_FIXTURE_DIR must name an existing directory, not a symlink, '.' or '..'"
    if path.name in ("", ".."):
        raise RequestLogFileError(msg)
    try:
        return os.open(path, _DIR_FLAGS)
    except OSError as exc:
        raise RequestLogFileError(msg) from exc


class RequestLog:
    """The append-only, size-capped JSONL sink; one `write` is one line."""

    def __init__(
        self,
        directory: str | os.PathLike[str] | None,
        *,
        process_env: Environment,
        clock: Callable[[], datetime],
        pack_key_ids: Collection[str],
        max_bytes: int = DEFAULT_MAX_BYTES,
        backups: int = DEFAULT_BACKUPS,
    ) -> None:
        """`directory` is `CV_ACCOUNT_FIXTURE_DIR`, required; `clock` is the fixture clock (the
        `ts`); `pack_key_ids` are the pack's `tester_inputs.key_id` values, the only ids
        `signing_key_id` may name."""
        keys = frozenset(pack_key_ids)
        if not keys or not all(isinstance(k, str) and _PACK_KEY_ID.fullmatch(k) for k in keys):
            raise ValueError("pack_key_ids must be fixture-<scenario>-NNNN key ids")
        if not isinstance(process_env, Environment):
            raise ValueError("process_env must be an Environment")
        if max_bytes < MAX_LINE_BYTES or not 1 <= backups <= 9:
            raise ValueError(f"max_bytes must be at least {MAX_LINE_BYTES}; backups 1 to 9")
        if directory is None:
            raise RequestLogFileError(
                "the account fixture request log needs CV_ACCOUNT_FIXTURE_DIR"
            )
        self._keys, self._process_env, self._clock = keys, process_env.value, clock
        self._max_bytes, self._backups, self._fd = max_bytes, backups, -1
        self._dir_fd = _open_directory(directory)
        try:
            self._fd = self._open_file()
        except BaseException:
            self.close()
            raise

    def write(
        self,
        *,
        outcome: Outcome,
        transport: Transport | None = None,
        host: str | None = None,
        host_env: HostEnv | None = None,
        method: str | None = None,
        path: str | None = None,
        signing_key_id: str | None = None,
        key_class: KeyClass | None = None,
        verified: bool | None = None,
        scenario: str | None = None,
        stored_under: str | None = None,
        overlays: tuple[str, ...] = (),
        status: int | None = None,
        ret_code: int | None = None,
        code_unconfirmed: bool | None = None,
        order: OrderFields | None = None,
    ) -> None:
        """Append one line for one answer or refusal; a field outside its rule writes nothing."""
        if self._fd < 0:
            raise RequestLogFileError("the request log is closed")
        if signing_key_id is not None and signing_key_id not in self._keys:
            raise RequestLogFieldError(
                "signing_key_id must be a pack key id; log any other key as key_class=non_fixture"
            )
        line: dict[str, object] = {
            "ts": self._timestamp(),
            "host": _text("host", host, _HOST),
            "host_env": _choice("host_env", host_env, get_args(HostEnv)),
            "process_env": self._process_env,
            "transport": _choice("transport", transport, get_args(Transport)),
            "method": _text("method", method, _METHOD),
            "path": _text("path", path, _PATH),
            "signing_key_id": signing_key_id,
            "key_class": _choice("key_class", key_class, get_args(KeyClass)),
            "verified": _flag("verified", verified),
            "scenario": _text("scenario", scenario, _TOKEN),
            "stored_under": _text("stored_under", stored_under, _TOKEN),
            "overlays": _overlays(overlays),
            "status": _int("status", status, 100, 599),
            "ret_code": _int("ret_code", ret_code, 0, 999_999_999),
            "code_unconfirmed": _flag("code_unconfirmed", code_unconfirmed),
            "outcome": _choice("outcome", outcome, get_args(Outcome), required=True),
            "order": _order(order),
        }
        _check_against_the_guards(line)
        data = (json.dumps(line, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
        if len(data) > MAX_LINE_BYTES:
            raise RequestLogFieldError(f"a line must fit in {MAX_LINE_BYTES} bytes")
        size = os.fstat(self._fd).st_size  # the file's own, so another appender counts too
        if size and size + len(data) > self._max_bytes:
            self._rotate()
        view = memoryview(data)
        while view:
            view = view[os.write(self._fd, view) :]

    def close(self) -> None:
        """Close the file and the directory; idempotent."""
        for fd in (self._fd, self._dir_fd):
            if fd >= 0:
                os.close(fd)
        self._fd = self._dir_fd = -1

    def __enter__(self) -> RequestLog:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _timestamp(self) -> str:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RequestLogFieldError("ts: the fixture clock must be timezone-aware")
        return now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _open_file(self) -> int:
        """The file, relative to the directory: never through a symlink, a regular file this user
        owns with no other link, mode 0600 whatever the umask or an earlier mode, appended to."""
        try:
            fd = os.open(FILE_NAME, _FILE_FLAGS, 0o600, dir_fd=self._dir_fd)
        except OSError as exc:
            raise RequestLogFileError(f"{FILE_NAME} must be a regular file, not a symlink") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (info.st_uid, info.st_nlink) != (os.geteuid(), 1):
                msg = f"{FILE_NAME} must be a regular file owned by this user, with one link"
                raise RequestLogFileError(msg)
            os.fchmod(fd, 0o600)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _rotate(self) -> None:
        """`requests.jsonl` becomes `.1` and each `.n` becomes `.n+1`, dropping the oldest. On a
        failure the log stays closed, so no write reaches a stale descriptor."""
        fd, self._fd = self._fd, -1
        os.close(fd)
        names = [FILE_NAME, *(f"{FILE_NAME}.{n}" for n in range(1, self._backups + 1))]
        try:
            for src, dst in zip(reversed(names[:-1]), reversed(names[1:]), strict=True):
                with contextlib.suppress(FileNotFoundError):
                    os.rename(src, dst, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd)
        except OSError as exc:
            raise RequestLogFileError("rotating the request log failed; it is closed") from exc
        self._fd = self._open_file()
