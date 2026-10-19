"""E17-X02 (#415): nightly fuzz of the WS topic and option parsers and the JSON client-frame path.

Each target returns a typed refusal or a bounded value for any input a decoded frame can carry:
- `parse_topic`: a `TopicError` with one of its three codes and no `field`, or a parse of a name
  of the §13 topic shape whose parts are in the registry's sets;
- `validate_options`, for every family: `invalid_options` whose `field` is an option name or
  `opts`, never client text (§5.1), or options within what the registry declares;
- `is_topic_name`: a bool, true only for a string of at most `TOPIC_MAX_LEN` characters;
- `parse_replay_session_id`: None, or the input in lower case, a canonical uuid;
- `_Connection.decode` (JSON text frames, before and after `auth_ok`): the refusal `[]`, the
  oversize close, or a value at most `MAX_JSON_DEPTH` deep from a frame within its size cap.
Seeds: `topics.json` (the registry) and `json-client.json` (the §12 example frames, whose options
and replay session ids seed those targets), edited; frames also with JSON tokens, and repeated past
the size caps. A frame has no lone surrogate: an ASGI server delivers only valid UTF-8. A failure
reports as `test_cvwb_fuzz.py`'s do (`_fuzz.py`). Only the corpus check runs in the PR lane.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, Final, cast

import pytest
from fastapi import WebSocket
from hypothesis import strategies as st

from candleviewer.ws import topics
from candleviewer.ws.gateway import _OVERSIZE, _Connection
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES, MAX_JSON_DEPTH, MAX_PREAUTH_FRAME_BYTES
from tests.unit.ws._fuzz import Input, drive, encode, save_failure

CORPORA = Path(__file__).resolve().parents[5] / "tests/fuzz/ws-frames"
#: `parse_topic`'s outcome ("ok" or its refusal code) -> topic names.
TOPICS: Final[dict[str, list[str]]] = json.loads((CORPORA / "topics.json").read_text("utf-8"))
#: "ok" (decodes to a JSON object) or "malformed" -> {name: the text frame's UTF-8, as hex}.
FRAMES: Final[dict[str, dict[str, str]]] = json.loads((CORPORA / "json-client.json").read_bytes())
_TEXTS: Final = [bytes.fromhex(h).decode() for group in FRAMES.values() for h in group.values()]
_SENT: Final = [json.loads(bytes.fromhex(h)) for h in FRAMES["ok"].values()]
#: (family, opts) of each topic a §12 `sub` names with options.
_SUB_OPTS: Final = [
    (t["ch"].split(".")[0], t["opts"])
    for f in _SENT
    if f.get("t") == "sub"
    for t in f["p"]["topics"]
    if "opts" in t
]
#: Seeds by name: a composite strategy's repr shows its arguments, never these.
_SEEDS: Final = {
    "topics": [t for group in TOPICS.values() for t in group],
    "sessions": sorted(
        {f.get("rs") or f.get("p", {}).get("replay_session_id") for f in _SENT} - {None}
    ),
}
_CODES: Final = frozenset({"invalid_topic_format", "unknown_topic", "unsupported_symbol"})
#: A refusal names an option or `opts`, never client text (§5.1); `parse_topic`'s names nothing.
_FIELDS: Final = topics.OPTION_NAMES | {"opts", None}
_PARAM: Final = re.compile(r"[A-Za-z0-9:]{1,24}")
#: Separators, both cases, digits, look-alikes (fullwidth, Cyrillic, Arabic-Indic), controls.
_CHARS: Final = tuple(".:-_aAzZfF09 /*{}\x00\n\u200b\uff21\u0410\u0663\u00df")
#: Frame edits: JSON's tokens, those Python's decoder reads past the standard (NaN, infinities),
#: escapes of a surrogate and NUL, an integer past the int-string limit; then runs of containers,
#: a byte-order mark, a line separator and `_CHARS`.
_TOKENS: Final = (*'[]{}",:\\', "NaN", "-Infinity", "1e999", '"\\ud800"', "\\u0000", "9" * 4301)
_PIECES: Final = (*_TOKENS, "[" * 40, '{"a":' * 40, "\ufeff", "\u2028", *_CHARS)
_EDITS: Final = st.lists(
    st.tuples(
        st.sampled_from(("set", "insert", "delete", "cut", "repeat")),
        st.integers(0, 1 << 16),
        st.integers(0, 300),
    ),
    max_size=5,
)
_JSON: Final = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=70),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=12), inner),
    max_leaves=8,
)


def _edit(text: str, edits: list[tuple[str, int, int]], pieces: tuple[str, ...]) -> str:
    """Each edit sets or inserts a piece at a position, deletes up to 64 characters there, cuts
    there, or repeats the whole up to 302 times (past every size cap)."""
    for kind, at, n in edits:
        at %= len(text) + 1
        if kind in ("set", "insert"):
            text = text[:at] + pieces[n % len(pieces)] + text[at + (kind == "set") :]
        elif kind in ("delete", "cut"):
            text = text[:at] + ("" if kind == "cut" else text[at + 1 + n % 64 :])
        else:
            text = (text * (2 + n))[: 2 * MAX_INBOUND_FRAME_BYTES]
    return text


def _list(opt: topics.Opt, n: int) -> list[str]:
    item = {"uuids": "a1000000-0000-4000-8000-{:012x}", "symbols": "S{}USDT"}.get(opt.kind, "{}")
    return [item.format(i) for i in range(n)]


def _past(opt: topics.Opt) -> list[Any]:
    """Values just past a cap the registry declares for `opt`: list size, item size or range."""
    if opt.max_items is not None:
        return [_list(opt, opt.max_items + 1), ["x" * 65]]
    return [b + d for b, d in ((opt.lo, -1), (opt.hi, 1)) if b is not None]


def _limits(opt: topics.Opt) -> list[Any]:
    """Values at and just past what the registry declares for `opt`."""
    if opt.max_items is not None:
        return [_list(opt, opt.min_items), _list(opt, opt.max_items), *_past(opt)]
    if opt.choices:
        return sorted(opt.choices, key=repr)
    edges = [b + d for b in (opt.lo, opt.hi) if b is not None for d in (-1, -0.5, 0, 0.5, 1)]
    return [*edges, True, "1.5", "-0", "1e3", "atr:14", ""]


#: (family, opts) with one option just past a cap the registry declares for it, alone.
_PAST: Final = [
    (name, {key: v})
    for name, family in sorted(topics.FAMILIES.items())
    for key, opt in {**topics.UNIVERSAL, **family.options}.items()
    for v in _past(opt)
]


@st.composite
def _edited(draw: st.DrawFn, seeds: str) -> object:
    """One of the named seeds, edited; one time in ten, any JSON value."""
    if draw(st.integers(0, 9)) == 0:
        return draw(_JSON)
    return _edit(draw(st.sampled_from(_SEEDS[seeds])), draw(_EDITS), _CHARS)


@st.composite
def _options(draw: st.DrawFn) -> list[object]:
    """[family, opts]: one time in three, one option just past a cap, alone; else a §12 `sub`'s
    options for its family, or none for any family, with one or two options set to their limits
    and maybe one more key of any JSON value; or, one time in ten, opts any JSON value."""
    if draw(st.integers(0, 2)) == 0:
        return list(draw(st.sampled_from(_PAST)))
    family, opts = draw(st.sampled_from([*_SUB_OPTS, *((f, {}) for f in sorted(topics.FAMILIES))]))
    if draw(st.integers(0, 9)) == 0:
        return [family, draw(_JSON)]
    opts, schema = dict(opts), {**topics.UNIVERSAL, **topics.FAMILIES[family].options}
    for name in draw(st.lists(st.sampled_from(sorted(schema)), min_size=1, max_size=2)):
        opts[name] = draw(st.sampled_from(_limits(schema[name])))
    if draw(st.integers(0, 4)) == 0:
        key = draw(st.sampled_from(sorted(topics.OPTION_NAMES)) | st.text(max_size=12))
        opts[key] = draw(_JSON)
    return [family, opts]


@st.composite
def _frames(draw: st.DrawFn) -> list[object]:
    """[after `auth_ok`, text]: a corpus frame, edited with JSON tokens and characters; one time in
    four, a `ping` whose `p` nests the frame 4 levels short of `MAX_JSON_DEPTH` to 4 past it."""
    if draw(st.integers(0, 3)) == 0:
        depth = draw(st.integers(MAX_JSON_DEPTH - 4, MAX_JSON_DEPTH + 4)) - 1
        return [draw(st.booleans()), '{"t":"ping","p":' + "[" * depth + "]" * depth + "}"]
    return [draw(st.booleans()), _edit(draw(st.sampled_from(_TEXTS)), draw(_EDITS), _PIECES)]


def _decode(arg: list[Any]) -> object:
    conn = _Connection(
        cast(WebSocket, None),  # `decode` never touches the socket
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: 0,
        auth_timeout_s=10.0,
    )
    conn.user_id = uuid.UUID(int=1) if arg[0] else None
    return conn.decode({"text": arg[1]}, MAX_INBOUND_FRAME_BYTES)


def _parsed(ch: Any, p: object) -> bool:
    if not isinstance(p, topics.ParsedTopic) or p.ch != ch or len(ch) > topics.TOPIC_MAX_LEN:
        return False
    sets = (topics.DEPTHS, topics.BAR_TYPES, topics.PROFILE_KINDS, topics.MACHINE_KINDS)
    return (
        topics.TOPIC_NAME_RE.fullmatch(ch) is not None
        and p.family is topics.FAMILIES.get(ch.split(".")[0])
        and all(
            v is None or v in s
            for v, s in zip((p.depth, p.bar_type, p.kind, p.entity_kind), sets, strict=True)
        )
        and (p.symbol is None or topics.SYMBOL_RE.fullmatch(p.symbol) is not None)
        and (p.param is None or _PARAM.fullmatch(p.param) is not None)
    )


def _within(opt: topics.Opt, v: Any) -> bool:
    if opt.max_items is not None:
        items = isinstance(v, list) and all(isinstance(x, str) and len(x) <= 64 for x in v)
        return items and opt.min_items <= len(v) <= opt.max_items
    number = isinstance(v, int | float) and not isinstance(v, bool)
    if opt.choices:
        return (number or isinstance(v, str)) and v in opt.choices
    if opt.lo is not None or opt.hi is not None:
        return number and (opt.lo is None or v >= opt.lo) and (opt.hi is None or v <= opt.hi)
    return isinstance(v, bool | str)


def _options_within(arg: list[Any], out: object) -> bool:
    schema = {**topics.UNIVERSAL, **topics.FAMILIES[arg[0]].options}
    return isinstance(out, dict) and all(
        k in schema and _within(schema[k], v) for k, v in out.items()
    )


def _name(ch: Any, named: object) -> bool:
    short = isinstance(ch, str) and 0 < len(ch) <= topics.TOPIC_MAX_LEN
    return named is False or (named is True and short)


def _session(raw: Any, rs: object) -> bool:
    return rs is None or (isinstance(raw, str) and rs == raw.lower() == str(uuid.UUID(raw)))


def _frame(arg: list[Any], frame: object) -> bool:
    if frame is _OVERSIZE:
        return True
    depth, level = 0, [frame]
    while nodes := [n for n in level if isinstance(n, dict | list)]:
        depth += 1
        level = [c for n in nodes for c in (n.values() if isinstance(n, dict) else n)]
    cap = MAX_INBOUND_FRAME_BYTES if arg[0] else MAX_PREAUTH_FRAME_BYTES
    return len(arg[1].encode()) <= cap and depth <= MAX_JSON_DEPTH


def _check(
    case: Input,
    call: Callable[[Any], object],
    bounded: Callable[[Any, Any], bool],
    codes: frozenset[str],
) -> None:
    """A typed refusal (a `TopicError` with one of `codes`) or a value `bounded` accepts. A
    violation, or a bound check that raises, fails with the target and the digest alone, raised
    where no exception is in flight."""
    arg, why = json.loads(case.data), ""
    value: object = None
    try:
        try:
            value = call(arg)
        except topics.TopicError as exc:
            if exc.code not in codes or exc.field not in _FIELDS:
                why = "refusal outside the catalogue"
        except BaseException as exc:
            why = f"untyped {type(exc).__name__}"
        else:
            why = "" if bounded(arg, value) else "unbounded value"
    except Exception as exc:
        why = f"bounds check raised {type(exc).__name__}"
    finally:
        del arg, value  # nothing derived from the input stays in the frame that fails
    if why:
        raise AssertionError(f"{why}: {save_failure(case)}") from None


def _fuzz(
    target: str,
    values: st.SearchStrategy[Any],
    call: Callable[[Any], object],
    bounded: Callable[[Any, Any], bool],
    codes: frozenset[str] = frozenset(),
) -> None:
    def check(case: Input) -> None:
        _check(case, call, bounded, codes)

    drive(values.map(lambda value: Input(target, partial(encode, value))), check)


@pytest.mark.fuzz
def test_parse_topic_returns_a_typed_refusal_or_a_bounded_parse() -> None:
    _fuzz("parse_topic", _edited("topics"), topics.parse_topic, _parsed, _CODES)


@pytest.mark.fuzz
def test_validate_options_returns_a_typed_refusal_or_bounded_options_for_every_family() -> None:
    def call(arg: list[Any]) -> object:
        return topics.validate_options(topics.FAMILIES[arg[0]], arg[1])

    _fuzz("validate_options", _options(), call, _options_within, frozenset({"invalid_options"}))


@pytest.mark.fuzz
def test_is_topic_name_returns_a_bool_true_only_for_a_short_string() -> None:
    _fuzz("is_topic_name", _edited("topics"), topics.is_topic_name, _name)


@pytest.mark.fuzz
def test_parse_replay_session_id_returns_none_or_a_canonical_uuid() -> None:
    _fuzz("replay_session_id", _edited("sessions"), topics.parse_replay_session_id, _session)


@pytest.mark.fuzz
def test_json_client_frames_decode_to_a_refusal_or_a_bounded_value() -> None:
    _fuzz("json_client_frame", _frames(), _decode, _frame)


def _outcome(ch: str) -> str:
    try:
        topics.parse_topic(ch)
    except topics.TopicError as exc:
        return exc.code
    return "ok"


def test_each_committed_seed_meets_its_expectation() -> None:
    """Each topic sits in the group of what `parse_topic` makes of it; each frame decodes to a
    JSON object ("ok") or not, before and after `auth_ok`."""
    wrong = [ch for expect, seeds in TOPICS.items() for ch in seeds if _outcome(ch) != expect]
    for expect, frames in FRAMES.items():
        for name, hexed in frames.items():
            for authed in (False, True):
                frame = _decode([authed, bytes.fromhex(hexed).decode()])
                if ("ok" if isinstance(frame, dict) else "malformed") != expect:
                    wrong.append(name)
    assert wrong == []
