"""#2689: `redact_text` scans client-shaped text in linear time and finds the same matches.

Before #2689 the JWT alternative backtracked from every offset of a long dot-free run (O(n^2),
about 10 ms per call at the 4096-character scan cap). The fix must not change what is redacted,
so the scan is checked against the old, backtracking alternation on generated text.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from candleviewer.observability import redaction
from candleviewer.observability.redaction import redact_text

#: `_VALUE_PATTERN` as it was before #2689: the same alternatives, with the backtracking `_JWT_RE`.
_REFERENCE = re.compile(
    f"(?P<jwt>{redaction._JWT_RE})|(?P<apikey>{redaction._APIKEY_RE})"
    f"|(?P<invite>{redaction._INVITE_SHAPE_RE})|(?P<refresh>{redaction._REFRESH_SHAPE_RE})"
    f"|(?P<totp>{redaction._TOTP_RE})|(?P<download>{redaction._DOWNLOAD_PATH_RE})"
)
#: Non-ASCII word characters and digits: separators for the JWT segments (ASCII classes), word
#: characters for the `\b` and `\d` of the API-key and TOTP alternatives.
_UNICODE = "é٣"
_SEGMENT = "aZ09_-"
#: Runs of segment characters, often 8-13 long so three of them make a JWT, joined by separators.
_RUNS = st.lists(
    st.tuples(
        st.one_of(
            st.text(alphabet=_SEGMENT, min_size=8, max_size=13), st.text(_SEGMENT, max_size=4)
        ),
        st.sampled_from([".", ".", ".", " ", "=", "", *_UNICODE]),
    ),
    max_size=8,
).map(lambda parts: "".join(run + sep for run, sep in parts))
#: A JWT-shaped string in random context, including context that extends its first or last run.
_AROUND = st.text(alphabet=_SEGMENT + ". =" + _UNICODE, max_size=6)
_JWT_IN_TEXT = st.tuples(_AROUND, st.from_regex(redaction._JWT_RE, fullmatch=True), _AROUND)
#: Alphanumeric runs of API-key and invite-token length (18-36 and 43) in random context.
_KEY_IN_TEXT = st.tuples(_AROUND, st.text(alphabet="aZ09", min_size=16, max_size=45), _AROUND)
#: URL-safe, lowercase hex and snake_case runs about the token lengths in random context (#415).
_LONG_RUN = st.one_of(
    st.text(alphabet=_SEGMENT, min_size=63, max_size=65),
    st.text("0a9f", min_size=63, max_size=65),
    st.text("a0_", min_size=41, max_size=65),
)
_LONG_IN_TEXT = st.tuples(_AROUND, _LONG_RUN, _AROUND)
#: Free text over the characters the alternatives tell apart, runs, and embedded secret shapes.
_TEXT = st.one_of(
    st.text(alphabet=_SEGMENT + ". 1234567" + _UNICODE, max_size=200),
    _RUNS,
    _JWT_IN_TEXT.map("".join),
    _KEY_IN_TEXT.map("".join),
    _LONG_IN_TEXT.map("".join),
)
_CAP = redaction._MAX_SCAN_LEN
#: Inputs at the scan cap that made the old JWT alternative backtrack from every offset, and runs
#: that the token alternatives read to their bounds and reject (#415).
_PATHOLOGICAL = [
    pytest.param("k" * _CAP, id="letter-run"),
    pytest.param("_-" * (_CAP // 2), id="underscore-dash-run"),
    pytest.param(("aZ09" * _CAP)[:_CAP], id="alnum-run"),
    pytest.param("x" * 12 + "." + "y" * (_CAP - 13), id="one-dot-then-run"),
    pytest.param(("0123456789abcdef" * 4 + " ") * (_CAP // 65), id="hex-digest-runs"),
    pytest.param((("aZ09_-" * 11)[:65] + " ") * (_CAP // 66), id="url-safe-65-runs"),
    pytest.param(("snake_case_" * _CAP)[:_CAP], id="snake-case-run"),
    pytest.param((("ab_" * 15)[:44] + " ") * (_CAP // 45), id="snake-case-runs"),
]
#: A long traceback with a backup download path on each line, and texts at the cap whose backup id
#: reads on: prefixes with no `/download/`, prefixes nested before one path, and an id with no `/`
#: after it (#415).
_PATH = f"/admin/backups/{'0' * 8}/download/{'aZ09_-' * 7}a"
_DOWNLOAD_HEAVY = [
    pytest.param(f'  File "{_PATH}/app.py", line 1\n' * 3000, id="a-path-per-line"),
    pytest.param("/admin/backups/" * (_CAP // 15), id="prefixes"),
    pytest.param("/admin/backups/a" * (_CAP // 16) + "/download/k", id="nested-prefixes"),
    pytest.param("/admin/backups/" + "k " * (_CAP // 2), id="id-to-the-end"),
]


def _fill(unit: str, head: str = "") -> str:
    """The `_TAIL_MAX` characters that end a long text: `head`, then `unit` repeated."""
    return (head + unit * redaction._TAIL_MAX)[: redaction._TAIL_MAX]


#: The last `_TAIL_MAX` characters of a long text, which the cut reads each line break of for a
#: label (#4671): a label before each line break, a label and then a long run of blank lines, and
#: a key name and its separator on lines of their own (the most line breaks to read back).
_LABEL_ENDS = [
    pytest.param(_fill("sign:\n"), id="a-label-per-line"),
    pytest.param(_fill("\n", head="sign:"), id="a-label-then-blank-lines"),
    pytest.param(_fill("sign\n:\n"), id="a-name-and-separator-per-line"),
]


def _long_text_ending_in(end: str) -> str:
    """A text of 5 MB: a single run, a line break, and `end` as its last characters."""
    return "k" * 5_000_000 + "\n" + end


_Found = tuple[str | None, tuple[int, int]] | None


def _found(pattern: re.Pattern[str], text: str) -> _Found:
    match = pattern.search(text)
    return None if match is None else (match.lastgroup, match.span())


@settings(max_examples=2000, deadline=None)
@given(_TEXT)
def test_redaction_scan_finds_the_same_match_as_the_backtracking_pattern(text: str) -> None:
    found = _found(redaction._VALUE_PATTERN, text)
    event(f"match: {found[0] if found else None}")  # --hypothesis-show-statistics: jwt is reached
    assert found == _found(_REFERENCE, text)


@pytest.mark.parametrize(
    "text",
    [
        "eyJhbGciOiJIUzI1NiJ9.CANARYPAYLOAD1234567.SIGNATURECANARY12345",
        "--header_123.payload-123.signature-1-",  # segments that start and end with `-`
        "id.aaaaaaaaaa.bbbbbbbbbb.cccccccccc.dd",  # a short run first, then a JWT run
        "x" * 30 + "." + "y" * 9 + "." + "z" * 30,  # middle segment one character short
        "token=" + "q" * 15 + "." + "r" * 15 + "." + "s" * 15 + "!",
        *_PATHOLOGICAL,
        *_DOWNLOAD_HEAVY,
    ],
)
def test_redaction_scan_matches_the_backtracking_pattern_on_known_shapes(text: str) -> None:
    assert _found(redaction._VALUE_PATTERN, text) == _found(_REFERENCE, text)


def test_redaction_scan_starts_a_jwt_only_where_a_run_starts() -> None:
    # The guard behind the linear cost: an attempt from inside a run fails at once, so each run
    # is scanned once rather than from every offset (the old pattern matched from offsets 0-10).
    text = "a" * 20 + "." + "b" * 10 + "." + "c" * 10
    starts = [
        pos
        for pos in range(20)
        if (match := redaction._VALUE_PATTERN.match(text, pos)) and match.lastgroup == "jwt"
    ]
    assert starts == [0]


def test_redaction_scan_still_redacts_a_jwt_after_a_long_run() -> None:
    text = "k" * 3000 + " Bearer eyJhbGciOiJIUzI1NiJ9.CANARYPAYLOAD1234567.SIGNATURECANARY12345"
    assert redact_text(text) == "[redacted:jwt-shape]"


class _ReadBackSpy:
    """Stands in for `_LABEL_END_BACK` and records how many characters each read-back is given."""

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self._pattern = pattern
        self.lengths: list[int] = []

    def match(self, string: str) -> re.Match[str] | None:
        self.lengths.append(len(string))
        return self._pattern.match(string)


@pytest.fixture
def read_backs(monkeypatch: pytest.MonkeyPatch) -> _ReadBackSpy:
    spy = _ReadBackSpy(redaction._LABEL_END_BACK)
    monkeypatch.setattr(redaction, "_LABEL_END_BACK", spy)
    return spy


# The next two tests count operations, not time, so they hold on any runner; the perf case below
# holds the same ends to a clock, in the perf lane only (#4671).
@pytest.mark.parametrize("end", _LABEL_ENDS)
@pytest.mark.parametrize(
    "redact", [redact_text, redaction._redact_runs], ids=["message", "traceback"]
)
def test_redaction_cut_reads_back_once_for_each_line_that_holds_text(
    redact: Callable[[str], str], end: str, read_backs: _ReadBackSpy
) -> None:
    out = redact(_long_text_ending_in(end))

    # each read-back finds a label, to the text's end: no line is kept
    assert out == redaction._TRUNCATED
    # a run of blank lines is passed over in one step, not read back at each of its line breaks
    lines_that_hold_text = sum(1 for line in end.split("\n") if line.strip())
    assert 0 < len(read_backs.lengths) <= lines_that_hold_text


@pytest.mark.parametrize("end", _LABEL_ENDS)
@pytest.mark.parametrize(
    "redact", [redact_text, redaction._redact_runs], ids=["message", "traceback"]
)
def test_redaction_cut_reads_back_at_most_256_characters_from_a_line_break(
    redact: Callable[[str], str], end: str, read_backs: _ReadBackSpy
) -> None:
    redact(_long_text_ending_in(end))

    assert read_backs.lengths
    assert max(read_backs.lengths) <= 256  # `_LABEL_REACH`, whatever the text's length


@pytest.mark.perf
@pytest.mark.parametrize("text", _PATHOLOGICAL)
def test_perf_redact_text_scans_a_capped_pathological_string_within_budget(text: str) -> None:
    best_ms = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        redact_text(text)
        best_ms = min(best_ms, (time.perf_counter() - start) * 1000)
    assert best_ms < 2.0, f"{best_ms:.3f} ms (about 10 ms before #2689)"


@pytest.mark.perf
@pytest.mark.parametrize(
    "redact", [redact_text, redaction._redact_runs], ids=["message", "traceback"]
)
def test_perf_a_5_mb_run_is_cut_within_budget(redact: Callable[[str], str]) -> None:
    text = "k" * 5_000_000  # one run: the cut reads the character at its end, not the run (#415)
    best_ms = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        out = redact(text)
        best_ms = min(best_ms, (time.perf_counter() - start) * 1000)
    assert out == redaction._TRUNCATED  # the run is dropped whole
    assert best_ms < 1.0, f"{best_ms:.3f} ms (the whole run was read: about 30 ms)"


@pytest.mark.perf
@pytest.mark.parametrize("end", _LABEL_ENDS)
@pytest.mark.parametrize(
    "redact", [redact_text, redaction._redact_runs], ids=["message", "traceback"]
)
def test_perf_a_long_text_that_ends_in_labels_is_cut_within_budget(
    redact: Callable[[str], str], end: str
) -> None:
    # each line break of the end is read back at most `_LABEL_REACH` characters, and a run of
    # blank lines in one step, whatever the text's length (#4671)
    text = _long_text_ending_in(end)
    best_ms = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        out = redact(text)
        best_ms = min(best_ms, (time.perf_counter() - start) * 1000)
    assert out == redaction._TRUNCATED  # each label goes with the line it names, the run whole
    assert best_ms < 5.0, (
        f"{best_ms:.3f} ms (about 1-3 ms; reading the whole text back: seconds; "
        "reading back at each blank line: about 30 ms)"
    )


@pytest.mark.perf
@pytest.mark.parametrize("text", _DOWNLOAD_HEAVY)
@pytest.mark.parametrize(
    "redact", [redact_text, redaction._redact_runs], ids=["message", "traceback"]
)
def test_perf_backup_download_paths_are_redacted_within_budget(
    redact: Callable[[str], str], text: str
) -> None:
    best_ms = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        out = redact(text)
        best_ms = min(best_ms, (time.perf_counter() - start) * 1000)
    assert re.search(redaction._DOWNLOAD_PATH_RE, out) is None
    assert best_ms < 2.0, f"{best_ms:.3f} ms (each `/admin/backups/` is read once)"
