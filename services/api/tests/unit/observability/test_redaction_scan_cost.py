"""#2689: `redact_text` scans client-shaped text in linear time and finds the same matches.

Before #2689 the JWT alternative backtracked from every offset of a long dot-free run (O(n^2),
about 10 ms per call at the 4096-character scan cap). The fix must not change what is redacted,
so the scan is checked against the old, backtracking alternation on generated text.
"""

from __future__ import annotations

import re
import time

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from candleviewer.observability import redaction
from candleviewer.observability.redaction import redact_text

#: `_VALUE_PATTERN` as it was before #2689: the same alternatives, with the backtracking `_JWT_RE`.
_REFERENCE = re.compile(
    f"(?P<jwt>{redaction._JWT_RE})|(?P<apikey>{redaction._APIKEY_RE})"
    f"|(?P<invite>{redaction._INVITE_SHAPE_RE})|(?P<totp>{redaction._TOTP_RE})"
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
#: Free text over the characters the alternatives tell apart, runs, and embedded secret shapes.
_TEXT = st.one_of(
    st.text(alphabet=_SEGMENT + ". 1234567" + _UNICODE, max_size=200),
    _RUNS,
    _JWT_IN_TEXT.map("".join),
    _KEY_IN_TEXT.map("".join),
)
_CAP = redaction._MAX_SCAN_LEN
#: Inputs at the scan cap that made the old JWT alternative backtrack from every offset.
_PATHOLOGICAL = [
    pytest.param("k" * _CAP, id="letter-run"),
    pytest.param("_-" * (_CAP // 2), id="underscore-dash-run"),
    pytest.param(("aZ09" * _CAP)[:_CAP], id="alnum-run"),
    pytest.param("x" * 12 + "." + "y" * (_CAP - 13), id="one-dot-then-run"),
]

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


@pytest.mark.perf
@pytest.mark.parametrize("text", _PATHOLOGICAL)
def test_perf_redact_text_scans_a_capped_pathological_string_within_budget(text: str) -> None:
    best_ms = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        redact_text(text)
        best_ms = min(best_ms, (time.perf_counter() - start) * 1000)
    assert best_ms < 2.0, f"{best_ms:.3f} ms (about 10 ms before #2689)"
