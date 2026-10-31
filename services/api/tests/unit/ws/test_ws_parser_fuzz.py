"""E17-X02 (#415): nightly fuzz of the WS topic and option parsers and the JSON client-frame path.

Each target returns a typed refusal or a bounded value for any input a decoded frame can carry,
and takes under `CALL_SECONDS` to do it:
- `parse_topic`: a `TopicError` with one of its three codes that names no field, or a parse of a
  name of the §13 topic shape (`_topic_shaped`, written out here) whose parts are in the
  registry's sets;
- `validate_options`, for every family: `invalid_options` whose `field` is an option name or
  `opts`, never client text (§5.1), or options within what the registry declares: list sizes and
  items (a string of at most 64 characters, or an `indicators` instance of the §13 shape), ranges
  and choices, a `bool`, a `param` of 1 to 24 characters, a decimal of the §13 grammar (a value
  kind the registry declares without a bound is checked against its grammar only);
- `is_topic_name`: true for a string of the §13 topic shape, 1 to 120 characters, and only then;
- `parse_replay_session_id`: None, or the input in lower case, a canonical uuid;
- `_Connection.decode` (JSON text frames, before and after `auth_ok`): the refusal `[]`, the
  oversize close, or a value at most `MAX_JSON_DEPTH` deep from a frame within its size cap; and,
  from `auth_ok`, never a frame over `MAX_PONG_BYTES` that opens with `t: "pong"` or is one.
Seeds: `topics.json` (the registry) and `json-client.json` (the §12 example frames, whose options
and replay session ids seed those targets), edited; frames also with JSON tokens, repeated past
the size caps, and `pong` frames of a size on either side of their bound; options also with each
cap the registry declares probed alone, from below as well as above. A frame has no lone
surrogate: an ASGI server delivers only valid UTF-8. A failure reports as `test_cvwb_fuzz.py`'s do
(`_fuzz.py`). Only the checks of the seeds and of the oracles' own premises run in the PR lane.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import string
import uuid
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Final, cast

import pytest
from fastapi import WebSocket
from hypothesis import strategies as st

from candleviewer.ws import gateway, topics
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import _OVERSIZE, _Connection
from candleviewer.ws.limits import (
    MAX_INBOUND_FRAME_BYTES,
    MAX_JSON_DEPTH,
    MAX_PONG_BYTES,
    MAX_PREAUTH_FRAME_BYTES,
)
from tests.unit.ws._fuzz import Input, Watch, drive, encode, save_failure
from tests.unit.ws._option_fill import required_fill

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
#: What a refusal's `field` may be. `validate_options` names an option or `opts`, never client text
#: (§5.1); `parse_topic` names nothing, and the other targets raise no `TopicError`.
_NO_FIELD: Final = frozenset({None})
_OPTION_FIELDS: Final = topics.OPTION_NAMES | {"opts"}
_PARAM: Final = re.compile(r"[A-Za-z0-9:]{1,24}")
#: §13 `common.schema.json#/$defs/decimal`.
_DECIMAL: Final = re.compile(r"-?[0-9]+(\.[0-9]+)?")
#: §13 `common.schema.json#/$defs/indicatorInstance`, written out from the schema, not read from
#: the registry's: the `indicator` pattern, its two members, at most 16 params, and the longest
#: text an item or a param holds.
_INDICATOR: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_INSTANCE_KEYS: Final = frozenset({"indicator", "params"})
_INSTANCE_PARAMS: Final = 16
_ITEM_TEXT: Final = 64
#: §13 `common.schema.json#/$defs/topic`: 1 to 120 characters, `[a-z_]+`, then any number of a dot
#: and `[A-Za-z0-9:_-]+`. Written out from the schema's pattern, not read from the registry's.
_TOPIC_MAX: Final = 120
_TOPIC_HEAD: Final = frozenset(string.ascii_lowercase + "_")
_TOPIC_PART: Final = frozenset(string.ascii_letters + string.digits + ":_-")
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


class _Quiet:
    """A logger that drops every record."""

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def _no_gateway_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_Connection.close_with` logs one `ws close` line per oversize or over-bound frame, about
    one example in six of the JSON frame target: captured output that a failing night would print
    ahead of the one line that matters."""
    quiet = _Quiet()
    monkeypatch.setattr(gateway, "_log", lambda: quiet)


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


def _list(opt: topics.Opt, n: int) -> list[Any]:
    """`n` items of the kind `opt` holds, each one the registry takes: a list of them is refused for
    its size alone."""
    if opt.kind == "instances":
        return [{"indicator": f"i{i}", "params": {"n": i}} for i in range(n)]
    item = {"uuids": "a1000000-0000-4000-8000-{:012x}", "symbols": "S{}USDT"}.get(opt.kind, "{}")
    return [item.format(i) for i in range(n)]


def _past(opt: topics.Opt) -> list[Any]:
    """Values just past a cap the registry declares for `opt`: a list one over its largest size or
    one under its smallest (the empty list, when that is one), of items it takes; a list of one
    item no list kind takes (a string of 65 characters, an instance named with 33); or a number
    past its range."""
    if opt.max_items is not None:
        under = [_list(opt, opt.min_items - 1)] if opt.min_items > 0 else []
        return [_list(opt, opt.max_items + 1), *under, ["x" * 65], [{"indicator": "a" * 33}]]
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


def _pong(pad: int, form: str) -> str:
    """A `pong` echoing an id, with `pad` characters of padding in its `p`: its `t` first (`first`)
    or last (`last`), or first with the end cut off (`cut`), which no parser reads."""
    members = ['"id":"c-hb-118"', '"p":{"pad":"' + "x" * pad + '"}']
    t = '"t":"pong"'
    text = "{" + ",".join([*members, t] if form == "last" else [t, *members]) + "}"
    return text[:-3] if form == "cut" else text


@st.composite
def _frames(draw: st.DrawFn) -> list[object]:
    """[after `auth_ok`, text]: a corpus frame, edited with JSON tokens and characters; one time in
    four, a `ping` whose `p` nests the frame 4 levels short of `MAX_JSON_DEPTH` to 4 past it; one
    time in eight, a `pong` 40 to 555 characters long, on either side of `MAX_PONG_BYTES`."""
    after_auth = draw(st.booleans())
    pick = draw(st.integers(0, 7))
    if pick < 2:
        depth = draw(st.integers(MAX_JSON_DEPTH - 4, MAX_JSON_DEPTH + 4)) - 1
        return [after_auth, '{"t":"ping","p":' + "[" * depth + "]" * depth + "}"]
    if pick == 2:
        pad, form = (
            draw(st.integers(0, 2 * MAX_PONG_BYTES)),
            draw(st.sampled_from(("first", "last", "cut"))),
        )
        return [after_auth, _pong(pad, form)]
    return [after_auth, _edit(draw(st.sampled_from(_TEXTS)), draw(_EDITS), _PIECES)]


def _decode(arg: list[Any]) -> object:
    """`decode` on a fresh connection, in a loop of its own: a frame that closes the socket
    starts the pipeline's flush deadline on the running loop (§8.4)."""
    return asyncio.run(_decoded(arg))


async def _decoded(arg: list[Any]) -> object:
    conn = _Connection(
        cast(WebSocket, None),  # `decode` never touches the socket
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: 0,
        auth_timeout_s=10.0,
        backpressure=BackpressureConfig(),  # #2409: the budgeted pipeline
    )
    conn.user_id = uuid.UUID(int=1) if arg[0] else None
    return conn.decode({"text": arg[1]}, MAX_INBOUND_FRAME_BYTES)


def _topic_shaped(ch: object) -> bool:
    """`ch` has the §13 topic shape: a string of 1 to 120 characters whose first part is lower-case
    letters and underscores and whose other parts, split on dots, are letters, digits, colons,
    underscores and hyphens, none of them empty."""
    if not isinstance(ch, str) or not 0 < len(ch) <= _TOPIC_MAX:
        return False
    head, *parts = ch.split(".")
    return (
        bool(head) and set(head) <= _TOPIC_HEAD and all(p and set(p) <= _TOPIC_PART for p in parts)
    )


def _parsed(ch: Any, p: object) -> bool:
    if not isinstance(p, topics.ParsedTopic) or p.ch != ch or not _topic_shaped(ch):
        return False
    sets = (topics.DEPTHS, topics.BAR_TYPES, topics.PROFILE_KINDS, topics.MACHINE_KINDS)
    return (
        p.family is topics.FAMILIES.get(ch.split(".")[0])
        and all(
            v is None or v in s
            for v, s in zip((p.depth, p.bar_type, p.kind, p.entity_kind), sets, strict=True)
        )
        and (p.symbol is None or topics.SYMBOL_RE.fullmatch(p.symbol) is not None)
        and (p.param is None or _PARAM.fullmatch(p.param) is not None)
    )


#: Options with no list size, choices or range: what each kind is, as the registry declares it.
#: A new kind with no cap fails the target (KeyError in the bound check) and, in the PR lane,
#: `test_the_options_bound_check_knows_every_option_kind_the_registry_declares`, until one is added.
_UNRANGED: Final[dict[str, Callable[[Any], bool]]] = {
    "bool": lambda v: isinstance(v, bool),
    "decimal": lambda v: isinstance(v, str) and _DECIMAL.fullmatch(v) is not None,
    "str": lambda v: isinstance(v, str) and _PARAM.fullmatch(v) is not None,
}


def _text_item(v: Any) -> bool:
    return isinstance(v, str) and len(v) <= _ITEM_TEXT


def _param_value(v: Any) -> bool:
    """A string of at most 64 characters, a boolean, or a number the wire can carry (an integer of
    any size; NaN and the infinities are no JSON)."""
    if isinstance(v, str):
        return len(v) <= _ITEM_TEXT
    return isinstance(v, int) or (isinstance(v, float) and math.isfinite(v))


def _instance(v: Any) -> bool:
    """§13 `common.schema.json#/$defs/indicatorInstance`: an object with an `indicator`, a string of
    `[a-z][a-z0-9_]{0,31}`, and `params`, at most 16 of them, each named by a string, and no other
    member."""
    if not isinstance(v, dict) or not set(v) <= _INSTANCE_KEYS:
        return False
    name, params = v.get("indicator"), v.get("params", {})
    return (
        isinstance(name, str)
        and _INDICATOR.fullmatch(name) is not None
        and isinstance(params, dict)
        and len(params) <= _INSTANCE_PARAMS
        and all(isinstance(k, str) and _param_value(x) for k, x in params.items())
    )


#: What one item of a list option is, by kind, as the registry declares it. A new list kind with no
#: item check fails the target (KeyError in the bound check) and, in the PR lane,
#: `test_the_options_bound_check_knows_every_option_kind_the_registry_declares`, until one is added.
_ITEMS: Final[dict[str, Callable[[Any], bool]]] = {
    "uuids": _text_item,
    "symbols": _text_item,
    "strings": _text_item,
    "instances": _instance,
}


def _within(opt: topics.Opt, v: Any) -> bool:
    if opt.max_items is not None:
        item = _ITEMS[opt.kind]
        return (
            isinstance(v, list)
            and opt.min_items <= len(v) <= opt.max_items
            and all(item(x) for x in v)
        )
    number = isinstance(v, int | float) and not isinstance(v, bool)
    if opt.choices:
        return (number or isinstance(v, str)) and v in opt.choices
    if opt.lo is not None or opt.hi is not None:
        return number and (opt.lo is None or v >= opt.lo) and (opt.hi is None or v <= opt.hi)
    return _UNRANGED[opt.kind](v)


def _options_within(arg: list[Any], out: object) -> bool:
    schema = {**topics.UNIVERSAL, **topics.FAMILIES[arg[0]].options}
    return isinstance(out, dict) and all(
        k in schema and _within(schema[k], v) for k, v in out.items()
    )


def _name(ch: Any, named: object) -> bool:
    return named is _topic_shaped(ch)


def _session(raw: Any, rs: object) -> bool:
    return rs is None or (isinstance(raw, str) and rs == raw.lower() == str(uuid.UUID(raw)))


def _opens_with_pong(text: str) -> bool:
    """The text opens with the member `"t": "pong"` of an object, JSON whitespace between its
    tokens, within its first `MAX_PONG_BYTES` characters (§8.5)."""
    rest = text[:MAX_PONG_BYTES]
    for token in ("{", '"t"', ":", '"pong"'):
        rest = rest.lstrip(" \t\n\r")
        if not rest.startswith(token):
            return False
        rest = rest[len(token) :]
    return True


def _frame(arg: list[Any], frame: object) -> bool:
    if frame is _OVERSIZE:
        return True
    after_auth, text = arg
    size = len(text.encode())
    if after_auth and size > MAX_PONG_BYTES:  # §8.5: such a pong closes, parsed or not
        if _opens_with_pong(text) or (isinstance(frame, dict) and frame.get("t") == "pong"):
            return False
    depth, level = 0, [frame]
    while nodes := [n for n in level if isinstance(n, dict | list)]:
        depth += 1
        level = [c for n in nodes for c in (n.values() if isinstance(n, dict) else n)]
    cap = MAX_INBOUND_FRAME_BYTES if after_auth else MAX_PREAUTH_FRAME_BYTES
    return size <= cap and depth <= MAX_JSON_DEPTH


def _check(
    case: Input,
    call: Callable[[Any], object],
    bounded: Callable[[Any, Any], bool],
    codes: frozenset[str],
    fields: frozenset[str | None],
) -> None:
    """A typed refusal (a `TopicError` with one of `codes`, naming one of `fields`) or a value
    `bounded` accepts, in under `CALL_SECONDS`. A violation, or a bound check that raises, fails
    with the target and the digest alone, raised where no exception is in flight."""
    arg, why = json.loads(case.data), ""
    value: object = None
    watch = Watch()
    try:
        try:
            with watch:
                value = call(arg)
        except topics.TopicError as exc:
            if exc.code not in codes or exc.field not in fields:
                why = "refusal outside the catalogue"
        except Exception as exc:  # a Ctrl-C, or an exit, is not a finding
            why = f"untyped {type(exc).__name__}"
        else:
            why = "" if bounded(arg, value) else "value beyond its bounds"
    except Exception as exc:
        why = f"bounds check raised {type(exc).__name__}"
    finally:
        del arg, value  # nothing derived from the input stays in the frame that fails
    if not why and watch.slow:
        why = "slow input"
    if why:
        raise AssertionError(f"{why}: {save_failure(case)}") from None


def _fuzz(
    target: str,
    values: st.SearchStrategy[Any],
    call: Callable[[Any], object],
    bounded: Callable[[Any, Any], bool],
    codes: frozenset[str] = frozenset(),
    fields: frozenset[str | None] = _NO_FIELD,
) -> None:
    def check(case: Input) -> None:
        _check(case, call, bounded, codes, fields)

    drive(values.map(lambda value: Input(target, partial(encode, value))), check)


@pytest.mark.fuzz
def test_parse_topic_returns_a_typed_refusal_or_a_bounded_parse() -> None:
    _fuzz("parse_topic", _edited("topics"), topics.parse_topic, _parsed, _CODES, _NO_FIELD)


@pytest.mark.fuzz
def test_validate_options_returns_a_typed_refusal_or_bounded_options_for_every_family() -> None:
    def call(arg: list[Any]) -> object:
        return topics.validate_options(topics.FAMILIES[arg[0]], arg[1])

    codes = frozenset({"invalid_options"})
    _fuzz("validate_options", _options(), call, _options_within, codes, _OPTION_FIELDS)


@pytest.mark.fuzz
def test_is_topic_name_returns_a_bool_true_exactly_for_the_topic_shape() -> None:
    _fuzz("is_topic_name", _edited("topics"), topics.is_topic_name, _name)


@pytest.mark.fuzz
def test_parse_replay_session_id_returns_none_or_a_canonical_uuid() -> None:
    _fuzz("replay_session_id", _edited("sessions"), topics.parse_replay_session_id, _session)


@pytest.mark.fuzz
def test_json_client_frames_decode_to_a_refusal_or_a_bounded_value() -> None:
    _fuzz("json_client_frame", _frames(), _decode, _frame)


def _outcome(ch: str) -> str:
    """ "ok", or the code of `parse_topic`'s refusal, with the field it names (it names none)."""
    try:
        topics.parse_topic(ch)
    except topics.TopicError as exc:
        return exc.code if exc.field is None else f"{exc.code} naming {exc.field}"
    return "ok"


def test_each_committed_seed_meets_its_expectation() -> None:
    """Each topic sits in the group of what `parse_topic` makes of it, its refusal naming no field,
    and is a topic name exactly when it has the §13 shape; each frame decodes to a JSON object
    ("ok") or not, before and after `auth_ok`."""
    names = [ch for group in TOPICS.values() for ch in group]
    wrong = [ch for expect, seeds in TOPICS.items() for ch in seeds if _outcome(ch) != expect]
    wrong += [ch for ch in names if topics.is_topic_name(ch) is not _topic_shaped(ch)]
    for expect, frames in FRAMES.items():
        for name, hexed in frames.items():
            for authed in (False, True):
                frame = _decode([authed, bytes.fromhex(hexed).decode()])
                if ("ok" if isinstance(frame, dict) else "malformed") != expect:
                    wrong.append(name)
    assert wrong == []


def test_topics_json_has_an_ok_seed_for_every_registry_family_shape_and_kind() -> None:
    """The corpus stays complete as the registry grows: a new family, shape, machine kind, depth,
    bar type or profile kind fails here until a seed names it."""
    parsed = [topics.parse_topic(ch) for ch in TOPICS["ok"]]
    shapes = {(f.family, len(shape)) for f in topics.FAMILIES.values() for shape in f.shapes}
    missing = {
        "family and shape": shapes - {(p.family.family, p.ch.count(".")) for p in parsed},
        "machine kind": set(topics.MACHINE_KINDS) - {p.entity_kind for p in parsed},
        "depth": set(topics.DEPTHS) - {p.depth for p in parsed},
        "bar type": set(topics.BAR_TYPES) - {p.bar_type for p in parsed},
        "profile kind": set(topics.PROFILE_KINDS) - {p.kind for p in parsed},
    }
    assert {what: names for what, names in missing.items() if names} == {}


def _refused(family: str, opts: dict[str, Any]) -> str | None:
    """The option `validate_options` refuses `opts` for; None when it accepts them. A required
    option an object of `opts` leaves out takes its `required_fill` value: only `opts` is judged."""
    fam = topics.FAMILIES[family]
    if isinstance(opts, dict):
        opts = required_fill(fam) | opts
    try:
        topics.validate_options(fam, opts)
    except topics.TopicError as exc:
        return exc.field if exc.code == "invalid_options" else exc.code
    return None


def _taken_past_a_cap() -> list[tuple[str, dict[str, Any]]]:
    """The values of `_PAST` that the registry does not refuse for their one option."""
    return [(f, o) for f, o in _PAST if _refused(f, o) != next(iter(o))]


def test_each_value_just_past_a_declared_cap_is_refused_alone_naming_its_option() -> None:
    """`_PAST` is what the options target draws one time in three: one option of one family just
    past a cap the registry declares for it, which must be refused for that option. Each list
    option with a minimum is probed with fewer items than that."""
    assert _taken_past_a_cap() == []
    probed = [(f, k, len(v)) for f, o in _PAST for k, v in o.items() if isinstance(v, list)]
    wanted = [
        (name, key, opt.min_items)
        for name, family in sorted(topics.FAMILIES.items())
        for key, opt in {**topics.UNIVERSAL, **family.options}.items()
        if opt.min_items > 0
    ]
    assert wanted
    assert [w for w in wanted if not any(w[:2] == p[:2] and p[2] < w[2] for p in probed)] == []


def test_the_cap_probe_finds_a_registry_that_takes_800_instances_where_it_declares_8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_PAST` is built when the suite loads, from the caps the registry declares then. A registry
    that took 800 `instances` (changed in memory here) would take the probe's 9: they are real
    instances, which the registry refuses for their count alone, where a list of strings is refused
    for its shape at any count."""
    assert _taken_past_a_cap() == []
    options = topics.FAMILIES["indicators"].options
    monkeypatch.setitem(options, "instances", replace(options["instances"], max_items=800))
    assert [(f, len(o["instances"])) for f, o in _taken_past_a_cap()] == [("indicators", 9)]


@pytest.mark.parametrize(
    ("family", "opts", "field"),
    [
        ("book", {"nope": 1}, "opts"),  # an unknown key is never echoed
        ("book", {"history": 5}, "history"),  # a known option name, not this family's: named
        ("book", [], "opts"),  # opts must be an object
        ("book", {"throttle_ms": -1}, "throttle_ms"),
        ("orders", {"exchange_account_ids": []}, "exchange_account_ids"),
    ],
)
def test_a_refused_option_names_an_option_or_opts_never_client_text(
    family: str, opts: Any, field: str
) -> None:
    assert _refused(family, opts) == field


_PARAMS_16: Final = {f"p{i}": i for i in range(16)}
#: `indicators.instances` items (§13 `indicatorInstance`) the registry takes, and ones it refuses.
_GOOD_INSTANCES: Final[list[Any]] = [
    {"indicator": "rsi"},
    {"indicator": "rsi", "params": {}},
    {"indicator": "rsi", "params": {"n": 14, "k": 2.5, "on": True, "s": "x" * 64}},
    {"indicator": "a" + "b_9" * 10 + "c", "params": _PARAMS_16},  # 32 characters, 16 params
    {"indicator": "rsi", "params": {"n": 10**400}},  # an integer past a float's range
]
_BAD_INSTANCES: Final[list[Any]] = [
    *(None, "rsi", ["rsi"], {}, {"params": {}}, {"indicator": 5}, {"indicator": "rsi", "x": 1}),
    *(
        {"indicator": name}
        for name in ("", "Rsi", "rsI", "_rsi", "1rsi", "r.si", "rsi\n", "a" * 33)
    ),
    *({"indicator": "rsi", "params": p} for p in (None, [14], {**_PARAMS_16, "q": 1}, {1: 14})),
    *({"indicator": "rsi", "params": {"n": n}} for n in (None, [14], {"a": 1}, "x" * 65)),
    *({"indicator": "rsi", "params": {"n": n}} for n in (float("nan"), float("inf"))),
]


@pytest.mark.parametrize(
    ("kind", "good", "bad"),
    [
        ("bool", [True, False], ["yes", 1, None]),
        ("str", ["atr:14", "x" * 24, "Ab:1"], ["", "a.b", "x" * 25, "1 2", 5]),
        ("decimal", ["1.5", "-0", "10", "0.001"], ["", "1e3", "1.", ".5", "--1", 1.5]),
        ("instances", _GOOD_INSTANCES, _BAD_INSTANCES),
    ],
)
def test_options_are_bounded_by_the_grammar_of_their_kind(
    kind: str, good: list[Any], bad: list[Any]
) -> None:
    """Each option of these kinds takes what the kind's grammar says and refuses the rest, and the
    fuzz target's bound for the kind says the same: `_UNRANGED` for the value, or, for a list kind,
    `_ITEMS` for each item (here, the one item of a list)."""
    in_list = kind in _ITEMS
    oracle = _ITEMS[kind] if in_list else _UNRANGED[kind]
    options = [
        (name, key)
        for name, family in sorted(topics.FAMILIES.items())
        for key, opt in {**topics.UNIVERSAL, **family.options}.items()
        if opt.kind == kind
    ]
    assert options

    def refused(name: str, key: str, value: Any) -> str | None:
        return _refused(name, {key: [value] if in_list else value})

    wrong = [(n, k, v) for n, k in options for v in good if refused(n, k, v) is not None]
    wrong += [(n, k, v) for n, k in options for v in bad if refused(n, k, v) != k]
    assert wrong == []
    assert all(oracle(v) for v in good) and not any(oracle(v) for v in bad)


def test_the_options_bound_check_knows_every_option_kind_the_registry_declares() -> None:
    """`_within` judges an option with no list size, choices or range by its kind alone
    (`_UNRANGED`) and each item of a list option by its kind (`_ITEMS`), and raises KeyError for a
    kind either table lacks, which fails every example of the options target. A registry change
    that adds such a kind fails here, in its own PR, not only in the nightly."""
    lacking: list[tuple[str, str, str]] = []
    for name, family in sorted(topics.FAMILIES.items()):
        for key, opt in {**topics.UNIVERSAL, **family.options}.items():
            try:
                _within(opt, [None])  # a list option's item check runs on a value that is no item
            except KeyError:
                lacking.append((name, key, opt.kind))
    assert lacking == []


def test_an_option_the_registry_newly_requires_fails_the_fill_naming_it() -> None:
    """`_refused` fills in each option a family requires (`required_fill`), for every family, since
    `_PAST` names each. A registry change that makes one required with no value to fill fails
    there naming the family and the option, in its own PR, never with a bare KeyError."""
    metrics = replace(topics.FAMILIES["metrics"], required=frozenset({"bar_type"}))
    with pytest.raises(AssertionError, match=r"^`metrics` now requires \['bar_type'\]: "):
        required_fill(metrics)


def test_the_options_oracle_accepts_the_instances_option_the_registry_accepts() -> None:
    """`indicators.instances` is a list of `{indicator, params}` objects (§13 `indicatorInstance`),
    not of strings: options the registry accepts for it are within what the oracle allows."""
    opts = {"instances": [{"indicator": "rsi", "params": {"n": 14}}], "history": 10}
    accepted = topics.validate_options(topics.FAMILIES["indicators"], opts)
    assert _options_within(["indicators", opts], accepted)


@pytest.mark.parametrize(
    ("ch", "shaped"),
    [
        ("orders", True),
        ("book.BTCUSDT.50", True),
        ("machines.order:0a000000-0000-4000-8000-000000000001.state", True),
        ("a" * 120, True),
        ("a" * 121, False),
        ("", False),
        ("orders\n", False),
        ("Orders", False),
        ("orders.", False),
        (".orders", False),
        ("book..50", False),
        ("book.BTC USDT", False),
        ("book.\uff22TC", False),
        ("book\u0000.BTCUSDT", False),
        (None, False),
    ],
)
def test_the_topic_shape_oracle_reads_the_spec_as_the_registry_does(ch: Any, shaped: bool) -> None:
    """`_topic_shaped`, written from the §13 pattern, agrees with the registry's reading of it on
    the cases a prefix match, a missing anchor or a character class would get wrong."""
    registry = isinstance(ch, str) and bool(ch) and topics.TOPIC_NAME_RE.fullmatch(ch) is not None
    assert _topic_shaped(ch) is shaped
    assert (registry and len(ch) <= topics.TOPIC_MAX_LEN) is shaped
    assert topics.is_topic_name(ch) is shaped


@pytest.mark.parametrize(
    "text",
    [
        '{"t":"pong"}',
        '{ "t" : "pong" ,"id":"x"}',
        '\n\t {"t":"pong"',
        '{"t":"ping"}',
        '{"id":"x","t":"pong"}',
        '{"t":"pongs"}',
        '{"t":"pong',
        '["t","pong"]',
        " " * 250 + '{"t":"pong"}',
        " " * 244 + '{"t":"pong"}',
    ],
)
def test_the_pong_oracle_reads_the_opening_as_the_gateway_does(text: str) -> None:
    assert _opens_with_pong(text) is gateway._leads_with_pong(text, msgpack=False)


def test_a_ctrl_c_during_a_parse_is_not_a_finding() -> None:
    def interrupt(arg: Any) -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _check(Input("probe", lambda: b"[]"), interrupt, _name, frozenset(), _NO_FIELD)


def test_a_frame_that_closes_the_socket_logs_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """The fuzz run's gateway log is dropped (`_no_gateway_log`): an oversize frame closes the
    connection, which logs `ws close` otherwise."""
    assert _decode([False, "x" * (MAX_PREAUTH_FRAME_BYTES + 1)]) is _OVERSIZE
    assert capsys.readouterr() == ("", "")
