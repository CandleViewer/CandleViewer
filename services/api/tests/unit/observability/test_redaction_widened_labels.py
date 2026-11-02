"""#4713: the redaction filter and the bundle scan read more escaped labels and values (C-12.6).

Both now also read a label after any escaped whitespace character (`\\x0b`, `\\xa0`, `\\u2028`,
`\\f`), a value in doubled quotes (`""…""`, `''…''`, as CSV and SQL escape a quote), and a dotted
label whose value follows a doubled escape (`cfg.token:\\\\n…`). The two change together: the scan
flags each value the filter redacts, and nothing in what the filter writes. A label inside a
redacted value makes it run on to the end of the line where that label's value starts, and a value
shape in the text as given makes the whole text its marker, as one after the label step does.

The widened rules are compared with the rules before #4713 (`_redaction_before_4713`, frozen) on
generated texts across key names, quote shapes, whitespace and escape forms and renderings: each
value the rules before #4713 hid in an output (the label step, a message, a traceback) is still
hidden there, each text they flagged is still flagged, and the values only the widened rules
redact are counted by shape. The PR lane runs a sample and the kept cases; the `fuzz`-marked tests
(opt-in, `-m fuzz`) run 500,000 texts. A second pass changes nothing, and the rules stay linear
on long inputs.

Values are assembled at runtime; none is a real secret.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from candleviewer.observability import bundle_scan, redaction
from candleviewer.observability.redaction import redact_text
from tests.unit.observability import _redaction_before_4713 as before

_KEY_MARK = redaction._KEY_NAME_MARKER
_FAKE = "".join(("FAKE", "q9Xw3L"))


def _flags(text: str) -> bool:
    return "labelled-secret" in set(bundle_scan.scan_text(text))


def _assert_redacted_and_flagged(text: str, shown: str) -> None:
    assert _flags(text)
    for redact in (redact_text, redaction._redact_runs):
        assert redact(text) == shown
        assert redact(shown) == shown
    assert not _flags(shown)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f"x\\x0bapi_secret={_FAKE}", f"x\\x0bapi_secret={_KEY_MARK}"),
        (f"x\\xa0password={_FAKE}", f"x\\xa0password={_KEY_MARK}"),
        (f"x\\u2028token: {_FAKE}", f"x\\u2028token: {_KEY_MARK}"),
        (f"x\\u000bpassword={_FAKE}", f"x\\u000bpassword={_KEY_MARK}"),  # as JSON writes it
        (f"x\\fpassword={_FAKE}", f"x\\fpassword={_KEY_MARK}"),
        # a bare value takes the quoted part after it (`_QUOTED`), the closing quote here
        (repr(f"x\x1csecret={_FAKE}"), "'x\\x1csecret=" + _KEY_MARK),
        (json.dumps(f"x\u3000token={_FAKE}"), '"x\\u3000token=' + _KEY_MARK),
    ],
    ids=["vt", "nbsp", "line-separator", "json-vt", "form-feed", "repr", "json"],
)
def test_a_label_after_an_escaped_whitespace_character_is_redacted_and_flagged(
    text: str, shown: str
) -> None:
    _assert_redacted_and_flagged(text, shown)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f'api_secret=""{_FAKE}""', f'api_secret=""{_KEY_MARK}""'),
        (f"password=''{_FAKE}''", f"password=''{_KEY_MARK}''"),
        (f'password=""{_FAKE} two""', f'password=""{_KEY_MARK}""'),  # to its closing quotes
        (f'"{{""api_secret"": ""{_FAKE}""}}"', f'"{{""api_secret"": ""{_KEY_MARK}""}}"'),
        (f'token=""""{_FAKE}""""', f'token=""""{_KEY_MARK}""""'),  # escaped twice
    ],
    ids=["double", "single", "with-a-space", "csv-of-json", "csv-twice"],
)
def test_a_value_in_doubled_quotes_is_redacted_and_flagged(text: str, shown: str) -> None:
    _assert_redacted_and_flagged(text, shown)


def test_a_value_that_runs_into_a_label_is_redacted_with_the_value_that_label_names() -> None:
    # the cookie's value runs to its line's end, through `token :`; the value it names follows, on
    # the next line, so the redacted value runs on to that line's end
    text = f"x\\x0bset-cookie: a=1 token :\n{_FAKE} done"
    shown = f"x\\x0bset-cookie: {_KEY_MARK}"

    for redact in (redact_text, redaction._redact_runs):
        assert redact(text) == shown
        assert redact(shown) == shown
    assert _flags(text)
    assert not _flags(shown)


def test_a_key_shaped_value_under_a_label_keeps_the_label_and_its_marker() -> None:
    # the rule before #4713 redacts this value by its label, so no value shape is left
    key = "".join(("Zq9Xw3Lm", "Pv7Rt2Yb", "Nc4HdK8s", "Ae5FgJ6u"))  # 32 letters and digits

    assert redact_text(f"api_key={key}") == f"api_key={_KEY_MARK}"


def test_the_shape_check_reads_the_label_rule_before_4713() -> None:
    assert redaction._LABELLED_VALUE_BEFORE_4713.pattern == before.LABELLED_VALUE.pattern
    assert redaction._LABELLED_VALUE_BEFORE_4713.flags == before.LABELLED_VALUE.flags


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f'""password"": ""\'{_FAKE}\'""', f'""password"": ""{_KEY_MARK}""'),
        (f'password="" {_FAKE}""', f'password=""{_KEY_MARK}""'),
        (f"token='' {_FAKE}'' x", f"token=''{_KEY_MARK}'' x"),
    ],
    ids=["other-quote-first", "space-first", "single"],
)
def test_a_doubled_quote_value_that_starts_with_a_quote_or_a_space_is_redacted_and_flagged(
    text: str, shown: str
) -> None:
    _assert_redacted_and_flagged(text, shown)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f"password:\\xa0 {_FAKE}", f"password:\\xa0 {_KEY_MARK}"),
        (f"token=\\x0b {_FAKE}", f"token=\\x0b {_KEY_MARK}"),
        (f"token=\\u2028 {_FAKE}", f"token=\\u2028 {_KEY_MARK}"),
    ],
    ids=["nbsp", "vt", "line-separator"],
)
def test_an_escaped_whitespace_character_after_the_separator_reads_as_whitespace(
    text: str, shown: str
) -> None:
    _assert_redacted_and_flagged(text, shown)


def test_the_cut_reads_each_escaped_whitespace_character_back_as_whitespace() -> None:
    forms = {repr(c)[1:-1] for c in map(chr, range(0x3001)) if c.isspace() and c != " "}
    forms |= {json.dumps(c)[1:-1] for c in map(chr, range(0x3001)) if c.isspace() and c != " "}
    back = re.compile(f"(?i)(?:{'|'.join(redaction._SPACE_ESCAPES_BACK)})")

    assert forms and all(back.fullmatch(form[::-1]) for form in forms)


@pytest.mark.parametrize(
    "text", ["password='', user=bob", 'token="", n=1', "password='' user=x", 'token="" ']
)
def test_an_empty_value_in_quotes_stays_as_it_was(text: str) -> None:
    # doubled quotes are a value's only when a value's first character follows them
    for redact in (redact_text, redaction._redact_runs):
        assert redact(text) == text
    assert not _flags(text)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f"cfg.token:\\\\n{_FAKE}", f"cfg.token:{_KEY_MARK}"),
        (f"self.password:\\\\\\\\t{_FAKE}", f"self.password:{_KEY_MARK}"),
        (f"cfg.token:\\\\'{_FAKE}\\\\'", f"cfg.token:{_KEY_MARK}"),
        (f"obj.api_secret:\\\\x0b{_FAKE}", f"obj.api_secret:{_KEY_MARK}"),
        (f"obj.api_secret:\\xa0{_FAKE}", f"obj.api_secret:{_KEY_MARK}"),
    ],
    ids=["line-break", "tab-twice-doubled", "quote", "vt", "nbsp"],
)
def test_a_dotted_label_whose_value_follows_a_doubled_escape_is_redacted_and_flagged(
    text: str, shown: str
) -> None:
    _assert_redacted_and_flagged(text, shown)


@pytest.mark.parametrize(
    "text",
    [
        "password:\\\\n" + _KEY_MARK,
        "x.password:\\\\n" + _KEY_MARK,
        f"token=''{_KEY_MARK}''",
        f"password=\\\\'{_KEY_MARK}\\\\'",
        f"x\\x0bpassword=\\\\\\\\x0b{_KEY_MARK}",
    ],
)
def test_the_scan_passes_a_marker_after_escapes_and_doubled_quotes(text: str) -> None:
    assert not _flags(text)


# --- generated texts: the widened rules against the rules before #4713 ---

#: What comes before a label: nothing, punctuation, a dotted owner, real whitespace (which a
#: rendering escapes) and escapes already in the text, single or doubled.
_BEFORE = ["", " ", "(", "\n", "{'", '{"', "x.", "cfg.", "self.", "x\t", '""', "x\\\\"]
_BEFORE += ["x\x0b", "x\x0c", "x\xa0", "x\u2028", "x\x1c", "x\x85", "x\u3000"]
_BEFORE += ["x\\t", "x\\x0b", "x\\u2028", "x\\f", "x\\\\n", "x\\\\xa0"]
#: The ones that end in whitespace other than a space, a tab or a line break, or in an escape.
_ESCAPED_SPACE_BEFORE = frozenset(_BEFORE[12:])
_NAME_QUOTES = ["", '"', "'", '""', "''", "\\'", '\\"', "\"'"]
_SEP_BEFORE = ["", " ", "\t"]
_SEP_AFTER = ["", " ", "\t", "\n", "\r\n", "\xa0", "\x0b", "\\n", "\\t", "\\\\n", "\\\\\\\\t"]
_SEP_AFTER += ["\\x0b", "\\u2028"]
#: An escaped whitespace character and then a space.
_SEP_AFTER += ["\\xa0 ", "\\x0b ", "\\u2028 ", "\\f ", "\\u00a0 "]
_VALUE_QUOTES = ["", '"', "'", '""', "''", "\\'", '\\"', "\\\\'", '\\\\"', "\"'"]
#: Doubled quotes with whitespace or the other quote after them (`"" …""`, `""'…""'`).
_VALUE_QUOTES += ['"" ', "'' ", '""\'', "''\""]
_AFTER = ["", " ", ",", "'}", '"}', "\n", "\\n", ")", ";"]
#: What may follow a marker that is the whole value (`_NO_VALUE`): a marker with a `)` or `;`
#: after it holds a value, to the filter and the scan alike.
_AFTER_A_MARKER = _AFTER[:-2]
_MARKERS = [_KEY_MARK, "[redacted:value-shape]", "<omitted>", "***", "null", "None"]
_MARKERS += [redaction._TRUNCATED]
#: Value characters: a value alone matches no value shape.
_VALUE_CHARS = "q9Xw3LmPv7Rt2_-Zk"
_KEY_FORMS = sorted(redaction._REDACT_KEY_FORMS)


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
    "csv-json": lambda text: _csv(json.dumps(text)),
    "repr-json": lambda text: repr(json.dumps(text)),
}


@dataclass(frozen=True)
class _Case:
    text: str
    #: The values the text labels: generated ones, or markers and placeholders only.
    values: tuple[str, ...]
    genuine: bool
    #: The shape of the first label: `dotted`, `doubled-quote`, `escaped-space` or `other`.
    shape: str


def _key(rng: random.Random) -> str:
    key = rng.choice(_KEY_FORMS)
    key = key.replace("_", "-") if rng.random() < 0.3 else key
    case = rng.random()
    return key.upper() if case < 0.1 else key.title() if case < 0.2 else key


def _labelled(rng: random.Random, genuine: bool) -> tuple[str, str, str]:
    before, name_quote, value_quote = (
        rng.choice(c) for c in (_BEFORE, _NAME_QUOTES, _VALUE_QUOTES)
    )
    length = rng.randint(6, 12)
    value = (
        "FAKE" + "".join(rng.choice(_VALUE_CHARS) for _ in range(length))
        if genuine
        else rng.choice(_MARKERS)
    )
    raw = "".join(
        (
            before,
            _key(rng),
            name_quote,
            rng.choice(_SEP_BEFORE),
            rng.choice(":="),
            rng.choice(_SEP_AFTER),
            value_quote + value + value_quote,
            rng.choice(_AFTER if genuine else _AFTER_A_MARKER),
        )
    )
    doubled = any(quote.startswith(('""', "''")) for quote in (name_quote, value_quote))
    shape = (
        "dotted"
        if before.endswith(".")
        else "doubled-quote"
        if doubled
        else "escaped-space"
        if before in _ESCAPED_SPACE_BEFORE
        else "other"
    )
    return raw, value, shape


#: A label only the widened rules read, with a short value, then a label whose value runs to the
#: line's end or holds spaces (`_TO_LINE_END`, a scheme) after an escaped or a real space or tab.
_WIDENED_FIRST = ["x\\x0b{k}={v}", "x\\u2028{k}={v}", "x\\f{k}={v}", '""{k}"":{v}', "{k}=''{v}"]
_WIDENED_FIRST += ['{k}=""{v}', "cfg.{k}:\\\\n{v}", "x\x0b{k}={v}"]
_BETWEEN = ["\\t", "\t", " ", "\\x0b", "\\u2028"]
_LONG_VALUE_NAMES = ["cookie", "Cookie", "set-cookie", "input_value", "authorization"]


def _fake(rng: random.Random) -> str:
    return "FAKE" + "".join(rng.choice(_VALUE_CHARS) for _ in range(rng.randint(6, 12)))


def _label_inside_a_widened_value(rng: random.Random) -> tuple[str, tuple[str, ...]]:
    """One to three widened labels in a row, each value short (`zz`) or generated, then a label
    whose value runs to the line's end or holds spaces: each label sits inside the value before."""
    widened, named = [], []
    for _ in range(rng.randint(1, 3)):
        short = rng.choice(["zz", "abc"]) if rng.random() < 0.5 else _fake(rng)
        named += [short] if short.startswith("FAKE") else []
        widened += [rng.choice(_WIDENED_FIRST).format(k=_key(rng), v=short), rng.choice(_BETWEEN)]
    first, more, last = _fake(rng), _fake(rng), _fake(rng)
    shapes = [f"sid={first}; other={more}", f'{{"a": {first}, "b": "{more}"}}']
    value = rng.choice([*shapes, f"Bearer {first} {more}", f"{first} {more}"])
    raw = "".join(
        (
            "".join(widened),
            rng.choice(_LONG_VALUE_NAMES),
            rng.choice([":", "=", ": "]),
            value,
            rng.choice(["", "''", '""']),
            rng.choice(["", f" tail-{last}"]),
        )
    )
    return raw, (*named, first, more, last)


def _corpus(count: int, seed: int) -> Iterator[_Case]:
    rng = random.Random(seed)  # noqa: S311 - fixed seed: the same texts on every run
    for _ in range(count):
        if rng.random() < 0.1:
            inside, labelled = _label_inside_a_widened_value(rng)
            text = _RENDERINGS[rng.choice(list(_RENDERINGS))](inside)
            yield _Case(text, labelled, True, "label-inside")
            continue
        genuine = rng.random() < 0.8
        raw, value, shape = _labelled(rng, genuine)
        values: tuple[str, ...] = (value,)
        if rng.random() < 0.15:  # a second label on the same line
            second, other, _ = _labelled(rng, genuine)
            raw, values = f"{raw} {second}", (value, other)
        rendering = rng.choice(list(_RENDERINGS))
        if rendering.startswith("csv") and shape == "other":
            shape = "doubled-quote"
        yield _Case(_RENDERINGS[rendering](raw), values, genuine, shape)


def _labelled_step(text: str) -> str:
    """The labelled-value step of `redaction._redact_str_value` (its gate, `_has_label`, and
    `_redact_labels`), as `before.redact_labelled` is the one before #4713."""
    return redaction._redact_labels(text) if redaction._has_label(text) else text


def _shapes(text: str) -> str:
    """The value-shape step after it, unchanged by #4713."""
    match = redaction._VALUE_PATTERN.search(text)
    return text if match is None else redaction._marker(match)


def _hidden(values: tuple[str, ...], text: str) -> bool:
    return all(value not in text for value in values)


@dataclass
class _Tally:
    counts: Counter[str]
    gains: Counter[str]
    regressions: list[str]


#: Each output of the filter, as the rules before #4713 wrote it and as they write it now: the
#: labelled-value step, a message text and the text of a traceback or a stack.
_OUTPUTS: dict[str, tuple[Callable[[str], str], Callable[[str], str]]] = {
    "label": (before.redact_labelled, _labelled_step),
    "text": (before.redact_text, redact_text),
    "runs": (before.redact_runs, redaction._redact_runs),
}


def _lost(values: tuple[str, ...], text: str) -> list[str]:
    """The outputs that show a value the rules before #4713 hid there."""
    lost = []
    for output, (old, new) in _OUTPUTS.items():
        was, now = old(text), new(text)
        if any(value not in was and value in now for value in values):
            lost.append(output)
    return lost


def _differential(count: int, seed: int) -> _Tally:
    tally = _Tally(Counter(), Counter(), [])
    for case in _corpus(count, seed):
        text = case.text
        tally.counts["texts"] += 1
        old_scan, new_scan = before.scan_labelled(text), bundle_scan._labelled(text)
        tally.counts["scan-before"] += old_scan
        tally.counts["scan-now"] += new_scan
        if not case.genuine:  # a marker the scan no longer flags is no value lost
            continue
        if old_scan and not new_scan:
            tally.regressions.append(f"scan: {text!r}")
        tally.regressions += [f"{output}: {text!r}" for output in _lost(case.values, text)]
        old, new = before.redact_labelled(text), _labelled_step(text)
        for value in case.values:
            tally.counts["values"] += 1
            tally.counts["label-before"] += value not in old
            tally.counts["label-now"] += value not in new
            if value in old and value not in new:
                tally.gains[case.shape] += 1
    return tally


def _report(tally: _Tally) -> str:
    gains = ", ".join(f"{shape} {n}" for shape, n in sorted(tally.gains.items()))
    return f"{dict(tally.counts)}; gains: {gains}; regressions: {len(tally.regressions)}"


#: The PR lane's sample, and the `fuzz`-marked full run (#4713: at least 500,000 texts).
_PR_TEXTS = 20_000
_NIGHTLY_TEXTS = 500_000
_SEED = 4713


def _assert_no_regression(count: int, seed: int) -> None:
    tally = _differential(count, seed)
    print(f"\n#4713 differential, {count} texts, seed {seed}: {_report(tally)}")
    assert tally.regressions == [], tally.regressions[:5]
    assert tally.counts["label-now"] > tally.counts["label-before"]  # each shape is generated
    assert set(tally.gains) >= {"dotted", "doubled-quote", "escaped-space"}


def test_the_widened_rules_redact_and_flag_every_value_the_rules_before_them_did() -> None:
    _assert_no_regression(_PR_TEXTS, _SEED)


@pytest.mark.fuzz
def test_the_widened_rules_redact_and_flag_every_value_the_rules_before_them_did_nightly() -> None:
    _assert_no_regression(_NIGHTLY_TEXTS, _SEED)


#: Texts of the full run kept as fixed cases, each with the values it labels: on each, an
#: earlier form of the widened rules showed a value that the rules before #4713 hid (a value that
#: ran into the next label, a label inside a value, or a text that a value shape had made a
#: marker), and, last, values only the widened rules read (`_KEPT_GAINS`).
_KEPT = Path(__file__).with_name("golden") / "redaction_4713_cases.jsonl"


def _kept() -> list[tuple[str, tuple[str, ...]]]:
    rows = [json.loads(line) for line in _KEPT.read_text(encoding="utf-8").splitlines()]
    return [(str(row["text"]), tuple(str(value) for value in row["values"])) for row in rows]


@pytest.mark.parametrize(("text", "values"), _kept())
def test_each_output_hides_each_value_the_rules_before_them_hid_in_a_kept_case(
    text: str, values: tuple[str, ...]
) -> None:
    assert _lost(values, text) == []


#: The last kept cases: values only the widened rules read, hidden on each output now.
_KEPT_GAINS = 4


def test_the_kept_cases_are_all_read() -> None:
    kept = _kept()
    assert len(kept) == 349
    for text, values in kept[:-_KEPT_GAINS]:  # each a value the rules before #4713 hid
        assert any(value not in old(text) for value in values for old, _ in _OUTPUTS.values())
    for text, values in kept[-_KEPT_GAINS:]:
        assert all(value not in new(text) for value in values for _, new in _OUTPUTS.values())


def _consistency_problems(count: int, seed: int) -> list[str]:
    problems: list[str] = []
    for case in _corpus(count, seed):
        text = case.text
        for redact in (redact_text, redaction._redact_runs):
            out = redact(text)
            if redact(out) != out:
                problems.append(f"second pass, {redact.__name__}: {text!r}")
            # the scan flags what the filter writes only for a value it left
            if bundle_scan._labelled(out) and (not case.genuine or _hidden(case.values, out)):
                problems.append(f"scan after {redact.__name__}: {text!r}")
        # the scan flags a value of six or more characters before a space, a quote, a comma or a
        # bracket (#415); a label-inside text starts its values with a shorter word on purpose
        hid = [value for value in case.values if value not in _labelled_step(text)]
        # one the rules before #4713 had too (they hid the value and did not flag it) is not new
        was = any(value not in before.redact_labelled(text) for value in hid)
        known = was and not before.scan_labelled(text)
        if case.genuine and case.shape != "label-inside" and hid and not known and not _flags(text):
            problems.append(f"filtered, not flagged: {text!r}")
        if not case.genuine and bundle_scan._labelled(text) and not before.scan_labelled(text):
            problems.append(f"marker flagged: {text!r}")
    return problems


def test_a_second_pass_changes_nothing_and_the_scan_agrees_with_the_filter() -> None:
    problems = _consistency_problems(_PR_TEXTS // 4, _SEED + 1)
    assert problems == [], problems[:5]


@pytest.mark.fuzz
def test_a_second_pass_changes_nothing_and_the_scan_agrees_with_the_filter_nightly() -> None:
    problems = _consistency_problems(_NIGHTLY_TEXTS, _SEED + 1)
    assert problems == [], problems[:5]


# --- long inputs: each new part of the rules reads a text once ---

#: About 20,000 characters each, made of the parts the widened rules read: escapes before a label,
#: doubled quotes, dotted names and runs of `\`, alone and repeated. A text ends in `_READ` where
#: it holds no `:` or `=` of its own, so that the filter reads it (`_LABEL_SEP`), and so does its
#: first half.
_READ = " a="
_LONG = {
    "escapes-before-names": "x\\x0b" * 4000 + _READ,
    "escapes-before-labels": "\\u2028token" * 2000 + _READ,
    "doubled-quotes": "password=" + '""' * 10000,
    "doubled-quote-value": 'password=""' + "a" * 20000,
    "doubled-quote-labels": '""token"":' * 2000,
    "dotted-backslashes": "cfg.token:" + "\\" * 20000,
    "dotted-labels": "cfg.token:\\\\" * 2000,
    "quotes-before-a-value": "password=" + "'" * 20000,
    "escaped-quotes-before-a-value": "password=" + "\\'" * 10000,
    "escapes-before-a-marker": "password=" + "\\\\x0b" * 4000 + _KEY_MARK,
    "doubled-quote-markers": f"token=''{_KEY_MARK}'' " * 600,
    # values that end in a key name, whose labels are read from the value's start (`_redact_labels`)
    "values-ending-in-names": "token=xpassword " * 1300,
    "a-value-ending-in-a-label": "set-cookie: " + "a token :" * 2300,
    "labels-run-into": "token=" + "\\'a' password" * 1500 + " :b",
    # labels inside a value: each is read from the value's start (`_redact_labels`)
    "labels-inside-values": '""token"":zz\\tcookie:a b\n' * 900,
    "nested-labels": "token=" * 3400,
    "labels-inside-labels": "x\\x0btoken=a" * 1700 + "cookie: x",
    "labels-and-line-values": '""token"":x\\tcookie:a' * 1000,
    "labels-before-doubled-quotes": '\\x0btoken=a""' * 1500,
}


def _best_ms(read: Callable[[str], object], text: str) -> float:
    best = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        read(text)
        best = min(best, (time.perf_counter() - start) * 1000)
    return best


@pytest.mark.perf
@pytest.mark.parametrize("text", _LONG.values(), ids=list(_LONG))
@pytest.mark.parametrize(
    "read",
    [_labelled_step, lambda text: list(bundle_scan.scan_text(text))],
    ids=["filter", "scan"],
)
def test_perf_the_widened_rules_read_a_long_text_in_linear_time(
    read: Callable[[str], object], text: str
) -> None:
    # the filter's labelled step reads the whole text (`redact_text` would cut it first)
    first_half = text[: len(text) // 2] + (_READ if text.endswith(_READ) else "")
    half, full = _best_ms(read, first_half), _best_ms(read, text)
    assert len(text) >= 18000
    assert full < 100.0 and full < 4 * half + 1.0, f"{half:.3f} ms -> {full:.3f} ms"


#: Labels inside labels, repeated: a unit and what ends the text (`_redact_labels`).
_WALK_SHAPES = {
    "labels-inside-labels": ("x\\x0btoken=a", "cookie: x"),
    "labels-and-line-values": ('""token"":x\\tcookie:a', ""),
    "labels-before-doubled-quotes": ('\\x0btoken=a""', ""),
}


def _best_cpu_ms(read: Callable[[str], object], text: str) -> float:
    best = float("inf")
    for _ in range(5):
        start = time.process_time()
        read(text)
        best = min(best, (time.process_time() - start) * 1000)
    return best


@pytest.mark.perf
@pytest.mark.parametrize(("unit", "end"), _WALK_SHAPES.values(), ids=list(_WALK_SHAPES))
@pytest.mark.parametrize(
    "read",
    [redaction._redact_labels, lambda text: list(bundle_scan.scan_text(text))],
    ids=["label-walk", "scan"],
)
def test_perf_the_label_walk_and_the_scan_take_linear_cpu_time(
    read: Callable[[str], object], unit: str, end: str
) -> None:
    # read whole, not cut first: twice the text takes about twice the time, where reading each
    # label's value again would take four times
    sizes = (20_000, 40_000, 80_000)
    ms = [_best_cpu_ms(read, unit * (size // len(unit)) + end) for size in sizes]
    assert ms[1] < 3 * ms[0] + 2.0 and ms[2] < 3 * ms[1] + 2.0, ms
