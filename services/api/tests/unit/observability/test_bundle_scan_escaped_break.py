"""#4681: the bundle scan passes a marker the log buffer wrote after a doubled escape (C-12.6).

The support bundle's log buffer `repr`s what the redaction already wrote (a stdlib traceback and
stack, a structlog traceback, an event dict's values), so `password:\\n[redacted:key-name]`
reaches the scan as `password:\\\\n[redacted:key-name]`. The scan keeps `_LABELLED` as it was and
drops a match only when its value, after its escapes, is a marker or a placeholder: its findings
are the old ones less exactly those. Values are assembled at runtime; none is a real secret.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from hypothesis import example, given
from hypothesis import strategies as st

from candleviewer.observability import bundle_scan, redaction
from candleviewer.observability.bundle_scan import scan_text, scan_tree
from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.observability.support_bundle import BundleSources, build_bundle
from candleviewer.observability.support_bundle_wiring import LogRingBuffer

#: `bundle_scan._LABELLED` as `main` wrote it before #4681, pinned: the scan before the fix.
_MAIN_SOURCE = (
    rf"""(?ix)["']?(?:\b|(?<=\\[tnr])){redaction._NOT_DOTTED}"""
    rf"""(?:{redaction._KEY_NAMES})["']?
    \s*[:=](?:\s|\\[tnr])*+(?:\\?["'])?{redaction._NO_VALUE}[^\s"',}}\]]{{6,}}"""
)
_TAIL = r"""[^\s"',}\]]{6,}"""
_MAIN_LABELLED = re.compile(_MAIN_SOURCE.removesuffix(_TAIL) + f"(?P<value>{_TAIL})")
#: A marker or a placeholder (what the redaction writes for a value) and what may follow one.
_MARKER_AHEAD = re.compile(
    r"""(?i)(?:\[redacted:[a-z-]+\]|\.\.\.\[truncated:oversize\]|<omitted>|\*\*\*|null|none)"""
    r"""(?=[\s"',}\]\\]|\.\.\.\[truncated:oversize\]|\Z)"""
)
_KEY_MARK = "[redacted:key-name]"
_FAKE = "".join(("abcd", "efgh"))
_EPOCH = datetime.fromtimestamp(0, UTC)


def _main_flags(text: str) -> bool:
    return _MAIN_LABELLED.search(text) is not None


def _new_flags(text: str) -> bool:
    return "labelled-secret" in set(scan_text(text))


def _marker_after_escapes(text: str, at: int) -> bool:
    """A run of `\\` (each with a `t`, `n` or `r` or not) from `at`, then a marker."""
    while at < len(text) and text[at] == "\\":
        while at < len(text) and text[at] == "\\":
            at += 1
        if at < len(text) and text[at] in "tnr":
            at += 1
    return _MARKER_AHEAD.match(text, at) is not None


def test_the_scan_keeps_mains_labelled_rule() -> None:
    assert bundle_scan._LABELLED.pattern == _MAIN_SOURCE
    assert _MAIN_LABELLED.pattern != _MAIN_SOURCE  # the value is a group in the pinned copy


def test_the_scan_head_is_the_labelled_rule_with_a_six_character_value() -> None:
    assert bundle_scan._LABELLED_HEAD.pattern == _MAIN_SOURCE.removesuffix("{6,}") + "{6}"
    assert bundle_scan._LABELLED_HEAD.flags == bundle_scan._LABELLED.flags


def test_the_scan_head_refuses_a_rule_whose_value_is_not_six_or_more_characters() -> None:
    # `match.end() - 6` is the value's start only if the head ends at exactly six characters
    with pytest.raises(ValueError, match="six"):
        bundle_scan._six_character_head(re.compile(r"password=\S+"))


# --- the issue's Gherkin, through the buffer and the bundle ---


def _capture(emit: Callable[[], None]) -> str:
    """The support bundle's buffer line for what `emit()` logs, logging set up as the app does."""
    ring = LogRingBuffer()
    with redirect_stdout(io.StringIO()):
        configure_logging(env="ci", level="debug", fmt="json")
        logging.getLogger().addHandler(ring)
        try:
            emit()
        finally:
            logging.getLogger().removeHandler(ring)
            reset_logging()
    [line] = ring.window(_EPOCH, datetime.now(UTC) + timedelta(hours=1))
    return line


def _labelled() -> str:
    return repr("password:\n" + _FAKE)  # `'password:\\nabcdefgh'`, an escaped line break


def _raising(log: Callable[[], None]) -> Callable[[], None]:
    def emit() -> None:
        try:
            raise ValueError(_labelled())
        except ValueError:
            log()

    return emit


def _stack() -> None:
    # the stack holds this source line, whose label and escaped line break the buffer `repr`s;
    # `[:0]` logs an empty argument, so the label reaches the bundle only through the stack
    logging.getLogger("t.lib").error("x%s", f"password:\n{_FAKE}"[:0], stack_info=True)


_PATHS: dict[str, Callable[[], None]] = {
    "stdlib-exception": _raising(lambda: logging.getLogger("t.lib").error("x", exc_info=True)),
    "stdlib-stack": _stack,
    "stdlib-message": lambda: logging.getLogger("t.lib").error("x %r", _labelled()),
    "structlog-traceback": _raising(lambda: structlog.get_logger("t.app").exception("x")),
    "structlog-field": lambda: structlog.get_logger("t.app").error("x", detail=_labelled()),
}


@pytest.mark.parametrize("emit", _PATHS.values(), ids=list(_PATHS))
def test_a_redacted_exception_with_an_escaped_line_break_is_bundled(
    emit: Callable[[], None], tmp_path: Path
) -> None:
    line = _capture(emit)
    now = datetime.now(UTC)
    sources = BundleSources(
        logs=lambda start, end: [line],
        metrics=lambda: "",
        health=lambda: {},
        system_events=lambda start, end: [],
        alerts=lambda: [],
        build_info=lambda: {},
        config=lambda: {},
    )

    result = build_bundle(sources, tmp_path / "out", now - timedelta(hours=1), now)

    assert _FAKE not in line and _KEY_MARK in line
    assert list(scan_text(line)) == []
    assert result.path.is_file()
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "logs.ndjson").write_text(line + "\n", encoding="utf-8")
    assert scan_tree(stage) == []


# --- the new scan against the old one ---

_KEYS = sorted(redaction._REDACT_KEYS | redaction._REDACT_KEY_FORMS)
_QUOTES = ["", '"', "'", "\\'", '\\"', "\\\\'", '\\\\\\"', "\"'"]
_SPACES = [" ", "\t", "\n", "\r\n", "\xa0", "\u2028", "\\t", "\\n", "\\r", "\\\\n", "\\\\t"]
_SPACES += ["\\xa0", "\\u2028", "\\\\xa0", "\\\\u2028", "\\\\\\\\n", "\\\\r\\\\n"]
_MARKERS = [_KEY_MARK, "[redacted:value-shape]", "<omitted>", "***", "null", "None"]
_MARKERS += ["...[truncated:oversize]"]
_GENUINE = st.text("Zq9Xw3LmPv7Rt2_-", min_size=5, max_size=11).map("Z".__add__)


def _csv(text: str) -> str:
    out = io.StringIO()
    csv.writer(out).writerow(["x", text])
    return out.getvalue()


_RENDERINGS: dict[str, Callable[[str], str]] = {
    "as-is": lambda text: text,
    "repr": repr,
    "repr2": lambda text: repr(repr(text)),
    "json": json.dumps,
    "json2": lambda text: json.dumps(json.dumps(text)),
    "csv": _csv,
}


@st.composite
def _text(draw: st.DrawFn, value: st.SearchStrategy[str]) -> tuple[str, str]:
    quote = draw(st.sampled_from(_QUOTES))
    spaces = st.lists(st.sampled_from(_SPACES), max_size=3).map("".join)
    raw = "".join(
        (
            draw(st.sampled_from(["", " ", "(", "\n", "\\n", "{'", "x."])),
            draw(st.sampled_from(_KEYS)),
            draw(st.sampled_from(_QUOTES)),
            draw(spaces),
            draw(st.sampled_from(":=")),
            draw(spaces),
            quote + draw(value) + quote,
            draw(st.sampled_from(["", " ", ",", "'}", "\n", "\\n"])),
        )
    )
    rendering = draw(st.sampled_from(list(_RENDERINGS)))
    return rendering, _RENDERINGS[rendering](raw)


@given(case=_text(st.one_of(st.sampled_from(_MARKERS), _GENUINE)))
@example(case=("repr", "password:\\n" + _KEY_MARK))
def test_the_scan_finds_what_main_found_less_a_marker_after_its_escapes(
    case: tuple[str, str],
) -> None:
    _, text = case
    old = _MAIN_LABELLED.search(text)

    assert not _new_flags(text) or old is not None
    if old is not None and not _new_flags(text):
        assert _marker_after_escapes(text, old.start("value"))


@given(case=_text(_GENUINE))
@example(case=("repr2", repr(repr("token:\n" + _FAKE))))
@example(case=("as-is", "password:\\\\n<omitted>\\\\ntoken=" + _FAKE))
def test_the_scan_still_flags_every_genuine_value_main_flagged(case: tuple[str, str]) -> None:
    _, text = case

    assert _new_flags(text) == _main_flags(text)


@pytest.mark.parametrize("rendering", ["repr", "repr2", "json", "json2"])
@pytest.mark.parametrize("between", ["\n", "\t", "\r\n", " \n"])
@pytest.mark.parametrize("marker", _MARKERS)
def test_the_scan_passes_a_marker_after_an_escape_however_often_it_is_rendered(
    rendering: str, between: str, marker: str
) -> None:
    text = _RENDERINGS[rendering]("password:" + between + marker)

    assert not _new_flags(text)


@pytest.mark.perf
@pytest.mark.parametrize(
    "text",
    [
        "token:\\\\n<omitted>\\\\n" * 1000,
        "password:\\\\n" + _KEY_MARK + "\\" * 20000,
        "password:" + "\\\\n" * 6000 + _KEY_MARK,
        ("x-api-key:\\\\n" + _KEY_MARK) * 600,
        "password:" + "\\" * 20000,
    ],
    ids=["nested-markers", "backslash-run", "escape-run", "many-markers", "backslashes"],
)
def test_perf_the_scan_reads_an_adversarial_text_in_linear_time(text: str) -> None:
    def best_ms(probe: str) -> float:
        best = float("inf")
        for _ in range(5):
            start = time.perf_counter()
            list(scan_text(probe))
            best = min(best, (time.perf_counter() - start) * 1000)
        return best

    half, full = best_ms(text[: len(text) // 2]), best_ms(text)
    assert len(text) >= 18000
    assert full < 100.0 and full < 4 * half + 1.0, f"{half:.3f} ms -> {full:.3f} ms"
