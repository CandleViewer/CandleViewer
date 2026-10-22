"""Exception text is redacted before it is rendered into a log line (#415; SR-121, C-12.6).

A traceback (alone or chained), a stack, and an exception logged as a value or an argument are
turned into text first and redacted after, on the structlog and the stdlib path, on stdout and in
the support bundle's log buffer. The text of a traceback or a stack is redacted where each value
stands, so its frames and lines stay. The access-token shape takes 42 to 44 URL-safe characters,
a 64-character token shape keeps hex digests readable, and neither takes the ids the service logs.
The redaction key list names the token, header and signature forms the services use: a field or a
header line of each is redacted by name, and so is a value labelled with a key name in message or
exception text (`token = …`), so such a line passes the support bundle's scan. A long text keeps
its start and its last lines, and a second pass changes nothing. A placeholder is no value only as
the whole value or right before the cut's marker, a dotted id (`machines.session:<id>`) is no label
where a dotted attribute and its value is one, a format string is left to format, and the buffer
writes each record on one line. The redaction filter and the bundle scan agree on whitespace
between a label and its value. Each backup download path (E42-T05 BK-11) in a traceback or a stack
shows its marker where it stood, as the whole of a message line that holds one does.

Values are assembled at runtime, so no secret-shaped literal sits in the repo.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import re
import sys
import threading
import types
import uuid
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pydantic
import pytest
import structlog
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.domain.primitives import GroupId
from candleviewer.observability import redaction
from candleviewer.observability.bundle_scan import scan_text
from candleviewer.observability.logging import (
    RedactionFilter,
    UpgradeLineFilter,
    configure_logging,
    reset_logging,
)
from candleviewer.observability.redaction import redact_text
from candleviewer.observability.support_bundle import BundleSources, build_bundle
from candleviewer.observability.support_bundle_wiring import LogRingBuffer
from candleviewer.oms.order_link import OrderLinkIdParts

#: URL-safe characters, `_` and `-` among them, with no dot, no run of 18 letters and digits and
#: no 6 digits: of the value shapes, only the access-token shape can match a string of them.
_CHARS = "".join(("Zq9X", "_w3L", "m-Pv", "7Rt2"))
#: How every such string starts: a part of one left in a line shows it.
_PART = _CHARS[:4]


def _url_safe(length: int) -> str:
    return (_CHARS * (length // len(_CHARS) + 1))[:length]


#: Shaped like `secrets.token_urlsafe(32)`: 43 characters.
TOKEN = _url_safe(43)
_MARK = "[redacted:invite-token-shape]"
#: Shaped like `secrets.token_urlsafe(48)`, a refresh token: 64 characters.
REFRESH = _url_safe(64)
_REFRESH_MARK = "[redacted:refresh-token-shape]"
_KEY_MARK = "[redacted:key-name]"
_EPOCH = datetime.fromtimestamp(0, UTC)


def _capture(emit: Callable[[], None]) -> tuple[list[dict[str, Any]], list[str]]:
    """Configure logging as the app does, with the support bundle's buffer on the root logger as
    `build_support_bundle_service` adds it, and call `emit()`. Returns the JSON lines on stdout
    and the lines of the buffer, each in emission order."""
    out, ring = io.StringIO(), LogRingBuffer()
    with redirect_stdout(out):
        configure_logging(env="ci", level="debug", fmt="json")
        logging.getLogger().addHandler(ring)
        try:
            emit()
        finally:
            logging.getLogger().removeHandler(ring)
            reset_logging()  # stops the QueueListener, which writes every queued record first
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    return lines, ring.window(_EPOCH, datetime.now(UTC) + timedelta(hours=1))[::-1]


def _logged(lines: list[dict[str, Any]], ring: list[str]) -> str:
    return json.dumps(lines) + "\n".join(ring)


def _fail(value: str) -> None:
    raise ValueError(f"bad value {value}")


#: How a traceback shows the frame of `_fail` and its line.
_FAIL_FRAME = (
    f'", line {_fail.__code__.co_firstlineno + 1}, in _fail\n'
    '    raise ValueError(f"bad value {value}")\n'
)
_CHAINS = {
    "alone": "",
    "cause": "The above exception was the direct cause of the following exception:",
    "context": "During handling of the above exception, another exception occurred:",
}


def _fail_in_chain(chain: str, value: str) -> None:
    try:
        _fail(value)
    except ValueError as exc:
        if chain == "cause":
            raise RuntimeError("op failed") from exc
        if chain == "context":
            raise RuntimeError("op failed")  # noqa: B904 - the implicit context is the subject
        raise


def _log_exc_info(path: str, chain: str, value: str) -> Callable[[], None]:
    def emit() -> None:
        try:
            _fail_in_chain(chain, value)
        except (ValueError, RuntimeError):
            if path == "structlog":
                structlog.get_logger("t.app").exception("op_failed")
            else:
                logging.getLogger("t.lib").error("op failed", exc_info=True)

    return emit


def _assert_readable(text: str, chain: str, mark: str = _MARK) -> None:
    """The traceback keeps its frames and lines; the value is redacted where it stood."""
    assert text.startswith("Traceback (most recent call last):\n")
    assert _FAIL_FRAME in text
    if chain == "alone":
        assert text.endswith(f"ValueError: bad value {mark}")
    else:
        assert f"ValueError: bad value {mark}\n\n{_CHAINS[chain]}\n\nTraceback" in text
        assert text.endswith("RuntimeError: op failed")


@pytest.mark.parametrize(
    ("value", "mark"), [(TOKEN, _MARK), (REFRESH, _REFRESH_MARK)], ids=["token-43", "token-64"]
)
@pytest.mark.parametrize("chain", _CHAINS)
@pytest.mark.parametrize("path", ["structlog", "stdlib"])
def test_a_traceback_is_redacted_where_the_value_stands_on_stdout_and_in_the_buffer(
    path: str, chain: str, value: str, mark: str
) -> None:
    lines, ring = _capture(_log_exc_info(path, chain, value))

    assert _PART not in _logged(lines, ring)
    [line], [entry] = lines, ring
    _assert_readable(line["exception"], chain, mark)
    field = "'exception': {!r}" if path == "structlog" else " exception={!r}"
    assert field.format(line["exception"]) in entry  # the same text, kept on one line
    assert "\n" not in entry


def _warn_with_stack(log: Any) -> None:
    log.warning("with_stack", stack_info=True)


def _log_stack(path: str, directory: str = f"/srv/{TOKEN}") -> Callable[[], None]:
    """`_warn_with_stack` as if its file sat in a directory named by the value, on a thread of its
    own: the stack is short, so all of it is within the length that is scanned."""
    code = _warn_with_stack.__code__.replace(co_filename=f"{directory}/app.py")
    warn = types.FunctionType(code, globals())

    def emit() -> None:
        log = structlog.get_logger("t.app") if path == "structlog" else logging.getLogger("t.lib")
        thread = threading.Thread(target=warn, args=(log,))
        thread.start()
        thread.join(timeout=10)
        assert not thread.is_alive()

    return emit


@pytest.mark.parametrize("path", ["structlog", "stdlib"])
def test_a_stack_is_redacted_where_the_value_stands_on_stdout_and_in_the_buffer(
    path: str,
) -> None:
    lines, ring = _capture(_log_stack(path))

    assert _PART not in _logged(lines, ring)
    [line], [entry] = lines, ring
    stack = line["stack"]
    assert stack.startswith("Stack (most recent call last):\n")
    assert ", in _bootstrap_inner\n" in stack  # the frames of the thread that logged
    frame = f", line {_warn_with_stack.__code__.co_firstlineno + 1}, in _warn_with_stack"
    assert stack.endswith(f'  File "/srv/{_MARK}/app.py"{frame}')
    field = "'stack': {!r}" if path == "structlog" else " stack={!r}"
    assert field.format(stack) in entry


def _structlog_field(exc: BaseException) -> None:
    structlog.get_logger("t.app").error("op_failed", error=exc)


def _structlog_key_field(exc: BaseException) -> None:
    structlog.get_logger("t.app").error("op_failed", token=exc)


def _stdlib_argument(exc: BaseException) -> None:
    logging.getLogger("t.lib").error("op failed: %s", exc)


def _stdlib_message(exc: BaseException) -> None:
    logging.getLogger("t.lib").error(exc)


def _stdlib_mapping(exc: BaseException) -> None:
    logging.getLogger("t.lib").error("op failed: %(token)s", {"token": exc})


@pytest.mark.parametrize(
    ("emit", "field", "text"),
    [
        (_structlog_field, "error", _MARK),
        (_structlog_key_field, "token", "[redacted:key-name]"),
        (_stdlib_argument, "event", f"op failed: {_MARK}"),
        (_stdlib_message, "event", _MARK),
        (_stdlib_mapping, "event", "op failed: [redacted:key-name]"),
    ],
    ids=["structlog-field", "structlog-key-field", "stdlib-argument", "stdlib-message", "mapping"],
)
def test_an_exception_logged_as_a_value_is_turned_into_text_before_it_is_redacted(
    emit: Callable[[BaseException], None], field: str, text: str
) -> None:
    lines, ring = _capture(lambda: emit(ValueError(f"bad value {TOKEN}")))

    assert _PART not in _logged(lines, ring)
    [line], [entry] = lines, ring
    assert line[field] == text
    assert text in entry


class _Unprintable(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no text")


def test_an_exception_whose_text_cannot_be_rendered_is_logged_with_a_placeholder() -> None:
    lines, ring = _capture(lambda: _structlog_field(_Unprintable()))

    [line], [entry] = lines, ring
    assert line["error"] == "<exception str() failed>"
    assert "<exception str() failed>" in entry


def test_the_filter_stores_a_rendered_traceback_only_once_it_is_redacted() -> None:
    """The handlers of a record share it across threads (the stdout listener and the bundle's
    buffer), so the rendered text must not sit on the record unredacted, even for a moment."""
    stored: list[str] = []

    class _Watched(logging.LogRecord):
        def __setattr__(self, name: str, value: Any) -> None:
            if name == "exc_text" and isinstance(value, str):
                stored.append(value)
            super().__setattr__(name, value)

    try:
        _fail(TOKEN)
    except ValueError:
        record = _Watched("t.lib", logging.ERROR, __file__, 1, "op failed", (), sys.exc_info())

    assert RedactionFilter().filter(record) is True
    assert stored
    assert [text for text in stored if _PART in text] == []
    assert record.exc_info is None
    _assert_readable(record.exc_text or "", "alone")


def test_the_filter_redacts_a_stack_where_the_value_stands() -> None:
    stack = f'Stack (most recent call last):\n  File "/srv/{TOKEN}/app.py", line 2, in emit'
    record = logging.makeLogRecord({"name": "t.lib", "msg": "with stack", "stack_info": stack})

    assert RedactionFilter().filter(record) is True
    assert record.stack_info == stack.replace(TOKEN, _MARK)


def test_the_filter_turns_an_exception_in_a_record_attribute_into_redacted_text() -> None:
    record = logging.makeLogRecord({"name": "t.lib", "msg": "op failed"})
    record.__dict__["error"] = ValueError(f"bad value {TOKEN}")  # as `extra={"error": ...}` does

    assert RedactionFilter().filter(record) is True
    assert record.__dict__["error"] == _MARK


@pytest.mark.parametrize("as_message", [True, False], ids=["message", "argument"])
def test_the_filter_turns_an_exception_as_the_message_or_an_argument_into_redacted_text(
    as_message: bool,
) -> None:
    exc = ValueError(f"bad value {TOKEN}")
    msg, args = (exc, ()) if as_message else ("op failed: %s", (exc,))
    record = logging.LogRecord("t.lib", logging.ERROR, __file__, 1, msg, args, None)

    assert RedactionFilter().filter(record) is True
    assert (record.msg if as_message else record.args) == (_MARK if as_message else (_MARK,))


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (ValueError({"password": ["ab", "cd"]}), "{'password': '[redacted:key-name]'}"),
        (ValueError(b"\x00\x01"), "[redacted:bytes]"),
        (ValueError("op", b"\x00\x01"), "('op', '[redacted:bytes]')"),
        (ValueError(), ""),
        (KeyError("token"), "'token'"),  # its own `__str__`: the text rules only
    ],
    ids=["mapping", "bytes", "arguments", "no-arguments", "own-str"],
)
def test_an_exception_logged_as_a_value_has_its_arguments_redacted_first(
    exc: BaseException, text: str
) -> None:
    assert redaction.redact_structure({"error": exc}) == {"error": text}


def _mint(size: int) -> str:
    raise ValueError(f"no entropy for {size} bytes")


def _issue() -> str:
    token = _mint(32)
    return token


def _log_issue(path: str) -> Callable[[], None]:
    def emit() -> None:
        try:
            _issue()
        except ValueError:
            if path == "structlog":
                structlog.get_logger("t.app").exception("issue_failed")
            else:
                logging.getLogger("t.lib").error("issue failed", exc_info=True)

    return emit


def _build(ring: list[str], tmp_path: Path) -> Path:
    """Build a support bundle of the buffer's lines, as the service does; its scan is the gate."""
    now = datetime.now(UTC)
    sources = BundleSources(
        logs=lambda start, end: ring,
        metrics=lambda: "",
        health=lambda: {},
        system_events=lambda start, end: [],
        alerts=lambda: [],
        build_info=lambda: {},
        config=lambda: {},
    )
    window = (now - timedelta(hours=1), now)
    return build_bundle(sources, tmp_path, *window, free_bytes=lambda _: 1 << 40).path


@pytest.mark.parametrize("path", ["structlog", "stdlib"])
def test_a_frame_line_that_labels_a_value_shows_the_marker_and_passes_the_bundle_scan(
    path: str, tmp_path: Path
) -> None:
    lines, ring = _capture(_log_issue(path))

    frame = f"line {_issue.__code__.co_firstlineno + 1}, in _issue\n"
    assert f"{frame}    token = [redacted:key-name]\n" in lines[0]["exception"]
    assert list(scan_text(ring[0])) == []
    assert _build(ring, tmp_path).is_file()


#: Short and of no value shape: only its label can hide it.
_SHORT_VALUE = "".join(("hun", "ter2"))


def _labelled_event() -> None:
    structlog.get_logger("t.app").warning(f"login failed password={_SHORT_VALUE}")


def _labelled_argument() -> None:  # the format string keeps its placeholder
    logging.getLogger("t.lib").warning("login failed password=%s", _SHORT_VALUE)


def _labelled_exception_value() -> None:
    structlog.get_logger("t.app").error("op_failed", error=ValueError(f"password={_SHORT_VALUE}"))


def _labelled_traceback() -> None:
    try:
        raise ValueError(f"login failed password={_SHORT_VALUE}")
    except ValueError:
        logging.getLogger("t.lib").error("op failed", exc_info=True)


@pytest.mark.parametrize(
    "emit",
    [_labelled_event, _labelled_argument, _labelled_exception_value, _labelled_traceback],
    ids=["structlog-event", "stdlib-argument", "exception-value", "traceback"],
)
def test_a_value_labelled_with_a_key_name_is_redacted_on_stdout_and_in_the_buffer(
    emit: Callable[[], None],
) -> None:
    lines, ring = _capture(emit)

    assert _SHORT_VALUE not in _logged(lines, ring)
    [line], [entry] = lines, ring
    assert "password=[redacted:key-name]" in json.dumps(line)
    assert "password=[redacted:key-name]" in entry


#: Shaped like HTTP Basic credentials, assembled at runtime.
_BASIC = base64.b64encode(b"user:pass").decode()


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("token = secrets.token_urlsafe(32)", "token = [redacted:key-name]"),  # a frame line
        ("token: ab", "token: [redacted:key-name]"),  # short and of no value shape
        ("{'password': 'ab cd'}", "{'password': '[redacted:key-name]'}"),  # to its closing quote
        ('{"token": "a\\"b c"}', '{"token": "[redacted:key-name]"}'),  # past an escaped quote
        ("token=b'ab cd' ok", "token=[redacted:key-name] ok"),  # a bare value's quoted part
        ('password: "ab\nValueError: x', 'password: "[redacted:key-name]\nValueError: x'),  # 1 line
        ("Authorization: Bearer ab.cd", "Authorization: [redacted:key-name]"),  # with its scheme
        (f"Authorization: Basic {_BASIC}", "Authorization: [redacted:key-name]"),
        ('Set-Cookie: session="ab cd"; Path=/', "Set-Cookie: [redacted:key-name]"),  # its line
        ("Cookie: cv_refresh=ab; cv_csrf=cd\nok", "Cookie: [redacted:key-name]\nok"),
        ("?access_token=ab&x=1 ok", "?access_token=[redacted:key-name] ok"),  # a query string
        ("/cb?state=1&token=ab#top", "/cb?state=1&token=[redacted:key-name]"),
        ("Login(password='ab')", "Login(password='[redacted:key-name]')"),
        ("<token: ab> ok", "<token: [redacted:key-name] ok"),
        ("x-bapi-sign: ab", "x-bapi-sign: [redacted:key-name]"),
        ("Refresh-Token=ab", "Refresh-Token=[redacted:key-name]"),  # in any case, either twin
        ("token = None", "token = None"),  # a placeholder
        ("tokens=3 my_token=4 token_type=bearer", "tokens=3 my_token=4 token_type=bearer"),
        # a stated over-redaction: a key name that labels no secret
        ("sign = 1 if diff > 0 else -1", "sign = [redacted:key-name] if diff > 0 else -1"),
    ],
)
def test_a_value_labelled_with_a_key_name_shows_the_key_name_marker(text: str, shown: str) -> None:
    assert redact_text(text) == shown
    assert redaction._redact_runs(text) == shown


def test_each_key_name_ends_with_a_letter() -> None:
    # text whose `:` and `=` all follow something else than a letter, quote or space holds no label
    assert all(name[-1].isalpha() for name in redaction._REDACT_KEY_FORMS)


#: Of no value shape and long enough for the scan (6 characters or more): only its label masks it.
_LABELLED_ONLY = "".join(("hun", "ter2x"))


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        # a cut marker ends a placeholder only as a cut leaves it; a value right before it is one
        (f"password='***{redaction._TRUNCATED}{_LABELLED_ONLY}'", f"password='{_KEY_MARK}'"),
        (f"password='{_LABELLED_ONLY}{redaction._TRUNCATED}'", f"password='{_KEY_MARK}'"),
        # unquoted, a value ends at `]`, the marker's too, as in `password=ab]cdefgh`: a value that
        # follows the marker directly stays (a cut never writes one: it joins its parts at a line
        # break)
        (
            f"password=***{redaction._TRUNCATED}{_LABELLED_ONLY}",
            f"password={_KEY_MARK}]{_LABELLED_ONLY}",
        ),
        *[(text, text) for text in ("token=***", "token=null, x=1", "password='***'")],
        *[
            (f"token={mark}", f"token={mark}")  # the last: a cut right after a marker
            for mark in (redaction._TRUNCATED, _KEY_MARK, _KEY_MARK + redaction._TRUNCATED)
        ],
        *[
            (f"password={value}{_SHORT_VALUE}", f"password={_KEY_MARK}")
            for value in ("***", "null-", "<omitted>", "[redacted")
        ],
        (f"password='***{_SHORT_VALUE}'", f"password='{_KEY_MARK}'"),
    ],
)
def test_a_placeholder_is_no_value_only_as_the_whole_value(text: str, shown: str) -> None:
    assert redact_text(text) == shown
    assert redaction._redact_runs(text) == shown
    assert ("labelled-secret" in set(scan_text(text))) is (shown != text)  # the scan reads alike


_TOPIC = f"machines.session:{uuid.UUID(int=1)}.state"


@pytest.mark.parametrize("text", [f"ch='{_TOPIC}'", json.dumps({"ch": _TOPIC})])
def test_a_dotted_id_is_no_label_to_the_redaction_or_the_scan(text: str) -> None:
    # a name after a `.`, then a `:` and neither a space nor a quote: a WS machine topic
    assert redact_text(text) == text
    assert redaction._redact_runs(text) == text
    assert list(scan_text(text)) == []


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f"self.password='{_SHORT_VALUE}'", f"self.password='{_KEY_MARK}'"),
        ("obj.api_secret=abcd1234", f"obj.api_secret={_KEY_MARK}"),
        ("cfg.token: shortone", f"cfg.token: {_KEY_MARK}"),
        ("cfg.token:'shortone'", f"cfg.token:'{_KEY_MARK}'"),
        ("    self.token = mint(32)", f"    self.token = {_KEY_MARK}"),  # a frame line
    ],
)
def test_a_dotted_attribute_and_its_value_are_masked_by_name_and_flagged_by_the_scan(
    text: str, shown: str
) -> None:
    assert redact_text(text) == shown
    assert redaction._redact_runs(text) == shown
    assert "labelled-secret" in set(scan_text(text))
    assert list(scan_text(shown)) == []


def test_the_scan_reads_an_escaped_line_break_after_a_dotted_label_as_a_space() -> None:
    # as the buffer writes a label that ends its line and the value on the next line
    assert "labelled-secret" in set(scan_text("cfg.token:\\nshortone"))


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f"token=\\'{_LABELLED_ONLY}\\'", f"token={_KEY_MARK}"),
        (f'token=\\"{_LABELLED_ONLY}\\"', f"token={_KEY_MARK}"),
        (f"cfg.token:\\'{_LABELLED_ONLY}\\'", f"cfg.token:{_KEY_MARK}"),  # a label, not an id
    ],
)
def test_the_scan_reads_an_escaped_quote_after_a_label_as_a_quote(text: str, shown: str) -> None:
    # as the buffer writes a quote it escapes: the scan flags the value, which the filter masks
    assert "labelled-secret" in set(scan_text(text))
    assert redact_text(text) == shown
    assert redaction._redact_runs(text) == shown
    assert list(scan_text(shown)) == []


def test_the_filter_leaves_a_format_string_of_a_value_shape_so_that_it_formats() -> None:
    msg, args = "ConnectionResetErrorX %s=%d", ("n", 3)  # the key shape takes the first word
    record = logging.LogRecord("t.lib", logging.WARNING, __file__, 1, msg, args, None)

    assert RedactionFilter().filter(record) is True
    assert record.getMessage() == "ConnectionResetErrorX n=3"


def test_a_format_string_of_a_value_shape_renders_redacted_and_writes_nothing_to_stderr() -> None:
    err = io.StringIO()  # `handleError` writes a line that fails to format there, with its args
    with redirect_stderr(err):
        lines, ring = _capture(
            lambda: logging.getLogger("t.lib").warning("ConnectionResetErrorX password=%s", "ab")
        )

    assert err.getvalue() == ""
    [line], [entry] = lines, ring
    assert line["event"] == "[redacted:key-shape]"  # the rendered line gets every rule
    assert entry == "WARNING t.lib [redacted:key-shape]"


def _log_raised(text: str) -> Callable[[], None]:
    def emit() -> None:
        try:
            raise ValueError(text)
        except ValueError:
            logging.getLogger("t.lib").error("op failed", exc_info=True)

    return emit


@pytest.mark.parametrize(
    "text", [f"token =\t{_SHORT_VALUE}", f"token=\n{TOKEN}"], ids=["tab", "line-break"]
)
def test_a_marker_after_a_label_and_an_escaped_space_passes_the_bundle_scan(text: str) -> None:
    _, [entry] = _capture(_log_raised(text))

    assert re.search(r"token ?=\\[tn]\[redacted:", entry)  # the buffer writes it as an escape
    assert list(scan_text(entry)) == []


def _two_line_message() -> None:
    logging.getLogger("t.lib").warning("password:\n%s", _SHORT_VALUE)


@pytest.mark.parametrize(
    "emit",
    [_two_line_message, _log_raised(f"config:\ntoken=\n{_SHORT_VALUE}")],
    ids=["message", "traceback"],
)
def test_the_filter_and_the_scan_agree_on_whitespace_between_a_label_and_its_value_in_the_buffer(
    emit: Callable[[], None], tmp_path: Path
) -> None:
    lines, ring = _capture(emit)

    [entry] = ring
    assert "\n" not in entry  # logs.ndjson keeps one record per line
    assert _SHORT_VALUE not in _logged(lines, ring)
    assert _build(ring, tmp_path).is_file()


_LABEL_KINDS = {
    "name": ("password=", _LABELLED_ONLY, _KEY_MARK),
    "quoted-name": ('{"token":', f'"{_LABELLED_ONLY}"}}', f'"{_KEY_MARK}"}}'),
    "dotted-name": ("cfg.token:", _LABELLED_ONLY, _KEY_MARK),
    "to-line-end": ("Cookie:", f"a={_LABELLED_ONLY}; b=1", _KEY_MARK),
    "scheme": ("Authorization:", f"Bearer {_LABELLED_ONLY}", _KEY_MARK),
}
_SPACES = ["\t", "   ", "\n", "\r\n", " \t\\n\r\n \n", "\\t", "\\r"]


@pytest.mark.parametrize("space", _SPACES, ids=list("abcdefg"))
@pytest.mark.parametrize(("label", "value", "shown"), _LABEL_KINDS.values(), ids=_LABEL_KINDS)
def test_the_redaction_filter_and_the_bundle_scan_agree_on_whitespace_between_a_label_and_its_value(
    label: str, value: str, shown: str, space: str
) -> None:
    text, out = label + space + value, label + space + shown

    assert "labelled-secret" in set(scan_text(text))
    for redact in (redact_text, redaction._redact_runs):
        assert redact(text) == out
        assert redact(out) == out
    assert list(scan_text(out)) == []


@pytest.mark.parametrize("before", ["\\t", "\\n", "\\r"], ids=["a", "b", "c"])
@pytest.mark.parametrize(("label", "value", "shown"), _LABEL_KINDS.values(), ids=_LABEL_KINDS)
def test_the_redaction_filter_and_the_bundle_scan_agree_on_where_a_label_starts(
    label: str, value: str, shown: str, before: str
) -> None:
    text, out = f"{before}{label} {value}", f"{before}{label} {shown}"

    assert "labelled-secret" in set(scan_text(text))
    for redact in (redact_text, redaction._redact_runs):
        assert redact(text) == out
        assert redact(out) == out
    assert list(scan_text(out)) == []


_WHITESPACE = [" ", "\t", "\n", "\r\n"]
_SPACE_RUN = st.lists(st.sampled_from(_WHITESPACE), max_size=4).map("".join)
_AROUND_PIECES = [*"ab9.,;:=()[]{}<>/-_*'\"", *_WHITESPACE, "\\t", "\\n", "\\r"]
_AROUND = st.lists(st.sampled_from(_AROUND_PIECES), max_size=10).map("".join)
_FLAGGED = st.builds(
    lambda quote, value: quote + value + quote,
    st.sampled_from(["", '"', "'"]),
    st.text(_CHARS + ".+/=:", min_size=6, max_size=12),
)
_LABELLED_TEXT = st.builds(
    lambda *parts: "".join(parts),
    _AROUND,
    st.sampled_from(sorted(redaction._REDACT_KEYS | redaction._REDACT_KEY_FORMS)),
    st.sampled_from(["", '"', "'"]),
    _SPACE_RUN,
    st.sampled_from(":="),
    _SPACE_RUN,
    _FLAGGED,
    _AROUND,
)


@given(_LABELLED_TEXT)
@example(f"token\n={_LABELLED_ONLY}")
@example(f'{{"password"\r\n:\r\n\t"{_LABELLED_ONLY}"}}')
@example(f"x\\tpassword={_LABELLED_ONLY}")
def test_the_filter_and_the_scan_agree_on_whitespace_between_a_label_and_its_value_in_any_text(
    text: str,
) -> None:
    for redact in (redact_text, redaction._redact_runs):
        assert list(scan_text(redact(text))) == []


class _Login(pydantic.BaseModel):
    password: str = pydantic.Field(min_length=12)
    user: str


def test_the_input_that_pydantic_writes_in_a_validation_error_is_redacted_by_its_label() -> None:
    with pytest.raises(pydantic.ValidationError) as caught:
        _Login.model_validate({"password": _SHORT_VALUE})  # too short, and no user
    texts = (redaction._redact_runs(str(caught.value)), redact_text(str(caught.value)))

    for out in (*texts, redaction.redact_structure({"error": caught.value})["error"]):
        assert _SHORT_VALUE not in out
        assert f"input_value='{_KEY_MARK}', input_type=str]" in out  # quoted: to its quote
        assert f"[type=missing, input_value={_KEY_MARK}\n" in out  # a mapping: to the line's end
    assert redaction.redact_structure({"input_value": "ab"}) == {"input_value": _KEY_MARK}


#: 32 letters and digits.
_ALNUM = "".join(("Zq9X", "w3Lm", "Pv7R", "t2Yb", "Nc4H", "dK8s", "Ae5F", "gJ6u"))


def test_a_run_that_a_shape_matches_in_part_is_redacted_whole() -> None:
    # the key shape matches the 30 characters before the `-`; the 15 after it match no shape
    text = f"ValueError: bad value {_ALNUM[:30]}-{_ALNUM[:15]} in request"

    assert redaction._redact_runs(text) == "ValueError: bad value [redacted:key-shape] in request"


def test_text_with_no_value_shape_is_kept_as_it_is() -> None:
    text = 'Traceback (most recent call last):\n  File "/srv/app.py", line 7, in run\nKeyError: 7'

    assert redaction._redact_runs(text) == text


#: The longest text that is not cut: the cap and the marker that ends a cut.
_CAP = redaction._MAX_SCAN_LEN + len(redaction._TRUNCATED)
#: Each place a text is cut: traceback text, message text, an exception logged as a value.
_REDACTIONS: dict[str, Callable[[str], str]] = {
    "traceback": redaction._redact_runs,
    "message": redact_text,
    "exception-value": lambda text: str(redaction.redact_structure(ValueError(text))),
}


@pytest.mark.parametrize("redact", _REDACTIONS.values(), ids=_REDACTIONS)
def test_the_scan_cap_cuts_before_a_run_that_it_would_split(redact: Callable[[str], str]) -> None:
    head = "x" * (redaction._MAX_SCAN_LEN - 11) + " "  # the cap falls 10 characters into TOKEN
    out = redact(head + TOKEN + " tail" * 10)

    assert out == head + redaction._TRUNCATED
    assert redact(out) == out  # a text cut once is not cut again


def _ping(depth: int, value: str) -> None:
    if depth > 0:
        _pong(depth - 1, value)
    _fail(value)


def _pong(depth: int, value: str) -> None:
    _ping(depth - 1, value)


def test_an_over_cap_traceback_keeps_its_start_and_its_last_lines() -> None:
    try:
        _ping(40, TOKEN)  # 41 frames that alternate, so no line is folded as repeated
    except ValueError:
        text = logging.Formatter().formatException(sys.exc_info())
    out = redaction._redact_runs(text)

    assert len(text) > _CAP >= len(out)
    assert out.startswith("Traceback (most recent call last):\n")
    assert f"{redaction._TRUNCATED}\n" in out  # the end is kept from the start of a line
    assert out.endswith(f"{_FAIL_FRAME}ValueError: bad value {_MARK}")


@pytest.mark.parametrize("text", ["ok 123456 " * 500, "token=ab " * 600], ids=["totp", "label"])
@pytest.mark.parametrize("redact", _REDACTIONS.values(), ids=_REDACTIONS)
def test_a_second_pass_changes_nothing_and_the_text_stays_within_the_cap(
    redact: Callable[[str], str], text: str
) -> None:
    out = redact(text)  # each marker is longer than the value it replaces

    assert len(out) <= _CAP
    assert redact(out) == out


#: Key names (one as the last part of a dotted name), separators, quotes, placeholders, digits,
#: spaces and line breaks, and the quote and line break as the bundle's buffer writes them (`\'`,
#: `\"`, `\n`); six digits are a TOTP shape, whose marker is longer: a pass grows a text.
_PIECES = (
    *("token", "password", "Cookie", "input_value", "machines.session", "x"),
    *("=", ": ", " = ", '"', "'", ",", "}", "]", "123456", " ", "\n"),
    *("\\'", '\\"', "\\n"),
    *(_KEY_MARK, redaction._TRUNCATED, "<omitted>", "***", "null", "None"),
)
#: Text of those pieces, where the run of TOTP shapes before them moves them across the cut.
_LABEL_HEAVY = st.builds(
    lambda pad, before, pieces, after: "x" * pad + " " + "123456 " * before + pieces + after,
    st.integers(0, 21),
    st.integers(0, 400),
    st.lists(st.sampled_from(_PIECES), max_size=40).map("".join),
    st.sampled_from(["", "123456 " * 300, "\n123456" * 300]),
)


@settings(max_examples=300, deadline=None)
@given(_LABEL_HEAVY)
@example("p" * 8 + " " + "123456 " * 185 + 'session: "<omitted> ok\n' + "123456 " * 300)
@example("x " * 2030 + "y" * 11 + " token=ab " + "z " * 300)
@example(" " + "123456 " * 185 + "token=ab " + "123456 " * 397)
@example("x" * 13 + " " + "123456 " * 184 + "Authorization: Bearer ab " + "123456 " * 397)
@example("x" * 18 + " " + "123456 " * 184 + "Cookie: v\n" + "123456 " * 397)
def test_a_label_heavy_text_stays_within_the_cap_and_a_second_pass_changes_nothing(
    text: str,
) -> None:
    # the examples: a cut inside a placeholder, the second cut inside a key-name marker, and a cut
    # right after one (after a label, a header with its scheme, a cookie header to its line's end)
    for redact in _REDACTIONS.values():
        out = redact(text)

        assert len(out) <= _CAP
        assert redact(out) == out


def test_a_label_whose_value_the_cut_dropped_passes_the_bundle_scan() -> None:
    out = redact_text("x " * 2040 + "token=" + _CHARS * 4)  # the cap falls inside the value

    assert out.endswith(f"token={redaction._TRUNCATED}")
    assert list(scan_text(out)) == []


@pytest.mark.parametrize(
    ("length", "redacted"), [(41, False), (42, True), (43, True), (44, True), (45, False)]
)
def test_the_access_token_shape_takes_42_to_44_url_safe_characters(
    length: int, redacted: bool
) -> None:
    value = _url_safe(length)
    line, last = f"GET /invites/{value} 200", f"ValueError: bad value {value}"

    assert redact_text(line) == (_MARK if redacted else line)
    assert redaction._redact_runs(last) == (f"ValueError: bad value {_MARK}" if redacted else last)


@pytest.mark.parametrize(("length", "redacted"), [(63, False), (64, True), (65, False)])
def test_the_refresh_token_shape_takes_64_url_safe_characters(length: int, redacted: bool) -> None:
    value = _url_safe(length)
    line, last = f"refresh failed for {value} at login", f"ValueError: bad value {value}"

    assert redact_text(line) == (_REFRESH_MARK if redacted else line)
    assert redaction._redact_runs(last) == (
        f"ValueError: bad value {_REFRESH_MARK}" if redacted else last
    )


def test_a_64_character_hex_digest_stays_readable_only_in_lower_case() -> None:
    digest = hashlib.sha256(b"cv").hexdigest()  # 64 lowercase hex characters
    line, upper = f"sha256 {digest} verified", f"sha256 {digest.upper()} verified"

    assert redact_text(line) == line
    assert redaction._redact_runs(line) == line
    assert redact_text(upper) == _REFRESH_MARK


#: snake_case log event names of 44 and 43 characters (`storage/retention/alert_tasks.py`,
#: `ingestion/clock.py`): identifiers, which no token shape takes.
_EVENT_NAMES = (
    "alert_deliveries_purge_disabled_no_owner_dsn",
    "clock_periodic_measurement_unexpected_error",
)


@pytest.mark.parametrize("name", _EVENT_NAMES)
def test_a_snake_case_event_name_stays_readable(name: str) -> None:
    lines, ring = _capture(lambda: structlog.get_logger("t.app").warning(name))

    assert lines[0]["event"] == name
    assert f"'event': {name!r}" in ring[0]
    assert redact_text(f"{name} after 3 attempts") == f"{name} after 3 attempts"
    assert redaction._redact_runs(f"KeyError: '{name}'") == f"KeyError: '{name}'"


@pytest.mark.parametrize("length", [42, 43, 44, 64])
def test_a_token_shape_leaves_only_an_all_lowercase_identifier_alone(length: int) -> None:
    snake = ("abcdefgh_" * 8)[:length]  # lowercase letters and `_`: an identifier
    upper, dash = snake[0].upper() + snake[1:], snake.replace("_", "-", 1)
    mark = _REFRESH_MARK if length == 64 else _MARK

    assert redact_text(f"id {snake} ok") == f"id {snake} ok"
    assert redact_text(f"id {upper} ok") == mark  # mixed case
    assert redact_text(f"id {dash} ok") == mark  # a `-`
    assert redaction._redact_runs(f"id {snake.replace('_', '0')} ok") == f"id {mark} ok"  # no `_`


def test_a_value_of_three_dotted_segments_is_redacted_whole() -> None:
    dotted = ".".join((_CHARS[:12],) * 3)  # the JWT shape
    last = f"ValueError: bad value {dotted}"

    assert redaction._redact_runs(last) == "ValueError: bad value [redacted:jwt-shape]"
    assert redact_text(last) == "[redacted:jwt-shape]"


@pytest.mark.parametrize(
    ("last", "shown"),
    [
        ("ConnectionResetError: [Errno 104] reset", "[redacted:key-shape]: [Errno 104] reset"),
        ("websockets.exceptions.ConnectionClosedOK: 1000", "[redacted:jwt-shape]: 1000"),
    ],
    ids=["class-name", "dotted-path"],
)
def test_a_class_name_of_a_value_shape_shows_as_its_marker_on_the_last_line(
    last: str, shown: str
) -> None:
    assert redaction._redact_runs(last) == shown


_UUID = uuid.UUID(bytes=hashlib.sha256(b"cv").digest()[:16], version=4)
_SHA256 = hashlib.sha256(b"cv").hexdigest()
#: Ids the service logs that no value shape takes: they stay readable.
_READABLE_IDS = {
    "uuid4": str(_UUID),  # request, connection, account, group and exchange order ids
    "sha256-hex": _SHA256,  # digests: 64 hex characters
    "commit-id": _SHA256[:40],  # `git_sha`: 40 hex characters
    "ws-connection-id": f"ws_{_UUID.hex[:12]}",
    "symbol": "1000PEPEUSDT",
    "session-topic": f"machines.session:{_UUID}.state",  # a WS machine topic (`ch=`)
}
#: Ids that the key shape takes already; the access-token shape must not take them either.
_KEY_SHAPED_IDS = {
    "uuid4-hex": _UUID.hex,  # 32 hex characters
    "order-link-id": OrderLinkIdParts(
        env="d", group_id=GroupId(_UUID), account_tag="Ab12", seq=7, tag="en"
    ).value,
}


@pytest.mark.parametrize("value", _READABLE_IDS.values(), ids=_READABLE_IDS.keys())
def test_an_id_the_service_logs_stays_readable(value: str) -> None:
    line, last = f"order {value} accepted", f"KeyError: 'unknown id {value}'"

    assert redact_text(line) == line
    assert redaction._redact_runs(last) == last


@pytest.mark.parametrize("shape", ["_INVITE_SHAPE_RE", "_REFRESH_SHAPE_RE"])
@pytest.mark.parametrize(
    "value",
    [*_READABLE_IDS.values(), *_KEY_SHAPED_IDS.values()],
    ids=[*_READABLE_IDS, *_KEY_SHAPED_IDS],
)
def test_no_token_shape_takes_an_id_the_service_logs(value: str, shape: str) -> None:
    assert re.search(getattr(redaction, shape), f"id={value};") is None


#: Normal stdlib lines: the buffer's redaction pass leaves each as plain rendering writes it.
_NORMAL_LINES = [
    ('%s - "%s %s HTTP/%s" %d', ("127.0.0.1:50000", "GET", "/health/live", "1.1", 200)),
    ("Started server process [%d]", (1,)),
    ("order %s accepted for %s", (str(_UUID), "1000PEPEUSDT")),
    ("build %s ready", (_SHA256[:40],)),
]


@pytest.mark.parametrize(("msg", "args"), _NORMAL_LINES)
def test_a_normal_stdlib_line_reaches_the_buffer_byte_identical(
    msg: str, args: tuple[object, ...]
) -> None:
    _, ring = _capture(lambda: logging.getLogger("t.lib").info(msg, *args))

    assert ring == [f"INFO t.lib {msg % args}"]


def test_a_structlog_line_reaches_the_buffer_as_its_redacted_event_dict() -> None:
    # as text 123456 has the TOTP shape; the processor chain keeps the int, and so does the buffer
    log = structlog.get_logger("t.app")
    lines, ring = _capture(lambda: log.info("frame_sent", topic="bars.BTCUSDT.1m", seq=123456))

    assert ring == [f"INFO t.app {lines[0]!r}"]


#: The token, header and signature names the services use, named in the redaction key list.
_KEY_FORMS = tuple(
    "refresh_token session_token bearer x-api-key x-auth-token x-access-token x-csrf-token"
    " proxy-authorization sign signature arm_token x-arm-token".split()
)
#: Field and header names that name no secret.
_READABLE_NAMES = tuple(
    "origin user-agent sec-websocket-protocol sec-websocket-extensions forwarded"
    " x-request-id".split()
)
#: Twins of listed names, not listed themselves: a name is read with `-` as `_`.
_TWINS = (
    "refresh-token",
    "access-token",
    "api-key",
    "x_api_key",
    "proxy_authorization",
    "x_arm_token",
)
#: Short and of no value shape: only a key name can hide it.
_SHORT = "v1-abcd"
_BY_NAME = [(name, "[redacted:key-name]") for name in (*_KEY_FORMS, *_TWINS)]
_BY_NAME += [(name, _SHORT) for name in _READABLE_NAMES]
_NAME_IDS = [name for name, _ in _BY_NAME]


@pytest.mark.parametrize(("name", "shown"), _BY_NAME, ids=_NAME_IDS)
def test_a_field_named_as_a_token_or_header_form_is_redacted_by_name(name: str, shown: str) -> None:
    lines, ring = _capture(lambda: structlog.get_logger("t.app").info("request", **{name: _SHORT}))

    [line], [entry] = lines, ring
    assert line[name] == shown
    assert f"{name!r}: {shown!r}" in entry


@pytest.mark.parametrize("fmt", ["< %s: %s", "> %s: %s"], ids=["request", "response"])
@pytest.mark.parametrize(("name", "shown"), _BY_NAME, ids=_NAME_IDS)
def test_a_header_line_named_as_a_token_or_header_form_shows_the_marker(
    fmt: str, name: str, shown: str
) -> None:
    record = logging.makeLogRecord({"name": "uvicorn.error", "msg": fmt, "args": (name, _SHORT)})

    assert UpgradeLineFilter().filter(record) is True
    assert RedactionFilter().filter(record) is True
    assert record.getMessage() == fmt % (name, shown)


@pytest.mark.parametrize("name", _KEY_FORMS)
def test_the_bundle_scan_flags_a_value_labelled_with_a_token_or_header_form(name: str) -> None:
    # the scan's labelled-secret rule is built from the same key list
    assert "labelled-secret" in set(scan_text(f"{name}: {_SHORT}"))


@pytest.mark.parametrize("twin", ["api-key", "x_api_key", "set_cookie", "proxy_authorization"])
def test_the_bundle_scan_reads_a_key_name_with_hyphen_and_underscore_alike(twin: str) -> None:
    assert "labelled-secret" in set(scan_text(f"{twin}: {_SHORT}"))


@pytest.mark.parametrize("name", ["X-BAPI-SIGN", "sign", "signature"])
def test_a_signature_is_redacted_by_its_name(name: str) -> None:
    signature = hmac.new(b"k", b"GET/v5/order", hashlib.sha256).hexdigest()  # 64 lowercase hex

    assert redact_text(signature) == signature  # no value shape takes it: its name is the control
    assert redaction.redact_structure({name: signature}) == {name: "[redacted:key-name]"}
    assert redact_text(f"{name}: {signature}") == f"{name}: [redacted:key-name]"


#: A backup fetch's path (E42-T05 BK-11): its token shaped like `secrets.token_urlsafe(32)` or too
#: short for any other shape, and its backup id a uuid or empty.
_BACKUP_ID = str(uuid.UUID(int=1, version=4))
_DL_MARK = "[redacted:download-path]"
_DOWNLOAD_PATHS = {
    "token-43": f"/admin/backups/{_BACKUP_ID}/download/{TOKEN}",
    "token-22": f"/admin/backups/{_BACKUP_ID}/download/{_url_safe(22)}",
    "empty-id": f"/admin/backups//download/{_url_safe(22)}",
}
#: Three dotted segments: the JWT shape.
_JWT = ".".join((_CHARS[:12],) * 3)
#: Each path alone, and beside a JWT, a TOTP and an access token, with the text each shows.
_DOWNLOAD_VALUES = {
    **{f"{name}-alone": (path, _DL_MARK) for name, path in _DOWNLOAD_PATHS.items()},
    **{
        f"{name}-beside": (
            f"{_JWT} {path} 123456 {TOKEN}",
            f"[redacted:jwt-shape] {_DL_MARK} [redacted:totp-shape] {_MARK}",
        )
        for name, path in _DOWNLOAD_PATHS.items()
    },
}


@pytest.mark.parametrize(("value", "shown"), _DOWNLOAD_VALUES.values(), ids=_DOWNLOAD_VALUES)
@pytest.mark.parametrize("chain", _CHAINS)
@pytest.mark.parametrize("path", ["structlog", "stdlib"])
def test_a_traceback_shows_the_download_path_marker_where_the_path_stood(
    path: str, chain: str, value: str, shown: str
) -> None:
    lines, ring = _capture(_log_exc_info(path, chain, value))

    assert _PART not in _logged(lines, ring) and _BACKUP_ID not in _logged(lines, ring)
    [line], [entry] = lines, ring
    _assert_readable(line["exception"], chain, shown)
    field = "'exception': {!r}" if path == "structlog" else " exception={!r}"
    assert field.format(line["exception"]) in entry


@pytest.mark.parametrize(("value", "shown"), _DOWNLOAD_VALUES.values(), ids=_DOWNLOAD_VALUES)
@pytest.mark.parametrize("path", ["structlog", "stdlib"])
def test_a_stack_shows_the_download_path_marker_where_the_path_stood(
    path: str, value: str, shown: str
) -> None:
    lines, ring = _capture(_log_stack(path, value))

    assert _PART not in _logged(lines, ring) and _BACKUP_ID not in _logged(lines, ring)
    [line], [entry] = lines, ring
    frame = f", line {_warn_with_stack.__code__.co_firstlineno + 1}, in _warn_with_stack"
    assert line["stack"].endswith(f'  File "{shown}/app.py"{frame}')
    field = "'stack': {!r}" if path == "structlog" else " stack={!r}"
    assert field.format(line["stack"]) in entry


@pytest.mark.parametrize("beside", [False, True], ids=["alone", "beside"])
@pytest.mark.parametrize("value", _DOWNLOAD_PATHS.values(), ids=_DOWNLOAD_PATHS)
@pytest.mark.parametrize(
    ("emit", "field", "text"),
    [
        (_structlog_field, "error", _DL_MARK),
        (_stdlib_argument, "event", f"op failed: {_DL_MARK}"),
        (_stdlib_message, "event", _DL_MARK),
    ],
    ids=["structlog-field", "stdlib-argument", "stdlib-message"],
)
def test_an_exception_logged_as_a_value_with_a_download_path_is_its_marker(
    emit: Callable[[BaseException], None], field: str, text: str, value: str, beside: bool
) -> None:
    # the path first: a message line is the marker of the first shape in it, as a whole
    message = f"fetch {value} failed" + (f" for {_JWT} 123456 {TOKEN}" if beside else "")
    lines, ring = _capture(lambda: emit(ValueError(message)))

    assert _PART not in _logged(lines, ring) and _BACKUP_ID not in _logged(lines, ring)
    [line], [entry] = lines, ring
    assert line[field] == text
    assert text in entry


def test_paths_nested_in_one_another_make_the_whole_traceback_text_the_marker() -> None:
    inner = _DOWNLOAD_PATHS["empty-id"]
    text = f"ValueError: /admin/backups/a{inner}/download/{_url_safe(22)} failed"

    assert redaction._redact_runs(text) == _DL_MARK  # no path is left for a second pass to find
    assert redact_text(text) == _DL_MARK


def test_two_download_paths_in_one_text_each_show_the_marker_where_they_stood() -> None:
    first, second = _DOWNLOAD_PATHS["token-43"], _DOWNLOAD_PATHS["empty-id"]

    assert redaction._redact_runs(f"a {first} b {second} c") == f"a {_DL_MARK} b {_DL_MARK} c"


def _fail_for(first: str, second: str) -> None:
    try:
        _fail(first)
    except ValueError as exc:
        raise RuntimeError(f"op failed for {second}") from exc


@pytest.mark.parametrize("path", ["structlog", "stdlib"])
def test_a_chained_traceback_with_a_path_in_each_exception_keeps_its_frames(path: str) -> None:
    def emit() -> None:
        try:
            _fail_for(_DOWNLOAD_PATHS["token-43"], _DOWNLOAD_PATHS["token-22"])
        except RuntimeError:
            if path == "structlog":
                structlog.get_logger("t.app").exception("op_failed")
            else:
                logging.getLogger("t.lib").error("op failed", exc_info=True)

    lines, ring = _capture(emit)

    assert _PART not in _logged(lines, ring) and _BACKUP_ID not in _logged(lines, ring)
    [line], [entry] = lines, ring
    text = line["exception"]
    assert text.startswith("Traceback (most recent call last):\n") and _FAIL_FRAME in text
    assert f"ValueError: bad value {_DL_MARK}\n\n{_CHAINS['cause']}\n\nTraceback" in text
    assert ", in _fail_for\n" in text and text.endswith(f"RuntimeError: op failed for {_DL_MARK}")
    field = "'exception': {!r}" if path == "structlog" else " exception={!r}"
    assert field.format(text) in entry


def test_a_cut_right_after_a_path_download_segment_makes_the_whole_text_the_marker() -> None:
    # stated: the run pass's markers move the cut to the `/download/` of a path with no token
    text = "123456 " * 185 + "/admin/backups/a/download/ " + "123456 " * 10

    assert redaction._redact_runs(text) == _DL_MARK


def test_a_download_path_that_the_cut_ends_shows_its_marker_where_it_stood() -> None:
    prefix = f"/admin/backups/{_BACKUP_ID}/download/"
    head = "x" * (redaction._MAX_SCAN_LEN - len(prefix) - 11) + " "  # the cap falls 10 into TOKEN
    out = redaction._redact_runs(head + prefix + TOKEN + " tail" * 10)

    assert out == head + _DL_MARK  # the path's marker, which took the cut's marker with it
    assert redaction._redact_runs(out) == out


#: Pieces of backup download paths, whole, nested or cut, among labels, quotes, spaces and TOTP
#: shapes, whose markers lengthen a text: a cut can fall inside a path.
_PATH_PIECES = (
    *("/admin/backups/", "/download/", "/", _BACKUP_ID, "a", _url_safe(22), TOKEN, "%0A"),
    *("token=", "password: ", '"', "'", " ", "\n", "123456", redaction._TRUNCATED, _DL_MARK),
)
_PATH_HEAVY = st.builds(
    lambda pad, before, pieces: "keep " + "x" * pad + " " + "123456 " * before + pieces,
    st.integers(0, 21),
    st.integers(0, 600),
    st.lists(st.sampled_from(_PATH_PIECES), max_size=40).map("".join),
)


def _nested(text: str) -> bool:
    """Paths nested in one another: a path is left once the labels and each path are replaced."""
    text = redaction._LABELLED_VALUE.sub(redaction._label_marker, text)
    return redaction._DOWNLOAD_PATH.search(redaction._DOWNLOAD_PATH.sub(_DL_MARK, text)) is not None


@settings(max_examples=300, deadline=None)
@given(_PATH_HEAVY)
@example(f"x /admin/backups/a{_DOWNLOAD_PATHS['empty-id']}/download/{TOKEN}")
@example(f"keep {_DOWNLOAD_PATHS['token-43']} 123456 {_DOWNLOAD_PATHS['empty-id']}")
def test_no_download_path_is_left_and_a_second_pass_changes_nothing(text: str) -> None:
    for redact in _REDACTIONS.values():
        out = redact(text)

        assert re.search(redaction._DOWNLOAD_PATH_RE, out) is None
        assert len(out) <= _CAP
        assert redact(out) == out
    if not _nested(text) and 4 * len(text) <= redaction._MAX_SCAN_LEN:  # no marker is 4 times
        # the text it replaces, so nothing is cut: a traceback keeps the text around its paths
        assert redaction._redact_runs(text).startswith("keep ")
