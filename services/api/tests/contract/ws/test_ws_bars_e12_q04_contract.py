"""E12-Q04 (#420): the `bars.*` topic against `23-ws-protocol.md` §14.3 `BarsBatch`, through the
real `/ws` router on the bars conformance rig (`test_ws_bars_contract._Rig`: the recorded BTCUSDT
tape through the real builders, C-13.5), under `cv.v1.json` and `cv.v1.msgpack`; the harness
validates every frame it receives against §13-§15 before a test sees it.

AC2: a snapshot and 50 deltas of `bars.BTCUSDT.time.1`, in both encodings. AC3: a server that sends
`closed` for `confirm` fails the suite, naming the member, the topic and §14.3. AC5: one script on
two rigs, decoded from binary and from JSON, agrees at the frame's scales (§3.4 is normative where
the two differ: `turnover` rounded half-even, three members structured only). The `close_t_ms` rule
per documented bar type; the dead-member guard over a run that sends every member a frame can
carry; the `param` bound at `sub`; and the seeded mutations its checks must catch.

A series a snapshot is built from is hydrated before the `sub` (`SeriesStore.ensure`), so the
snapshot never races its read.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from candleviewer.bars.activity_builders import TickBarBuilder
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.rows import BUILD_VERSIONS, bar_row
from candleviewer.bars.series_store import Hold
from candleviewer.bars.spec import from_wire
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.ws import bars_publish, bars_source, bars_wire
from candleviewer.ws.bars_wire import bar_item
from tests.contract._market_world import QTY_STEP, bar_type_params, stored_rows
from tests.contract._market_world import _bars as tape_bars
from tests.contract.test_market_bars_contract import _SERIES, _TAPE
from tests.contract.test_market_e12_q04_contract import _alternative
from tests.contract.ws import _harness as h
from tests.contract.ws.test_ws_bars_contract import CH, _closed, _Rig, _script, _Series, _up

_REPO: Final = Path(__file__).resolve().parents[5]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
#: `tools/contracts/wire_contract.py`, whose bundle walker gives the members §14.3 declares.
wc: Final[Any] = importlib.import_module("tools.contracts.wire_contract")

BARS: Final = "cv://ws/v1/bars.schema.json"
_MINUTE: Final = _SERIES["time", "1"]
#: The members kind 4 has no slot for (§3.4, C19): structured only.
_JSON_ONLY: Final = frozenset({"close_t_ms", "min_delta", "max_delta"})
_PRICES: Final = ("o", "h", "l", "c")
_SIZES: Final = ("v", "delta")
#: Members §14.3 declares that no frame of the run sends, each with the reason it is never sent
#: (`test_contract_bars_dead_member_allowlist_is_justified_and_current`).
_DEAD_ALLOWED: Final = {
    "BarsBatch.bars[].cvd": (
        "never sent per bar: the client sums `delta` (23 §6.1 include_delta); dropping it from "
        "the schema would break cv.v1 (C-6.3)"
    ),
    **{
        member: (
            "#5396 contract first (C-6.1): declared before the server sends it; #5396's "
            "follow-up serves it and removes this row"
        )
        for member in ("BarsBatch.bars[].gap_before", "BarsBatch.bars[].partial")
    },
}


def _emissions(spec: BarSpec, start: int, stop: int) -> list[list[BarUpdate]]:
    """The real builder's non-empty emissions for the tape's trades `start` to `stop`, each one
    source event; the trades before `start` are built and not published."""
    builder: Any = (TimeBarBuilder if spec.kind == "time" else TickBarBuilder)(spec, "BTCUSDT")
    out = [[*builder.on_trade(t), *builder.on_clock(t.ts_event)] for t in _TAPE[:stop]]
    return [emission for emission in out[start:] if emission]


def _hydrate(rig: _Rig, spec: BarSpec) -> Hold:
    """Hold `spec`'s series, read from the rig's rows, before any `sub` takes it."""
    hold: Hold = rig.w.call(rig.store.ensure, "BTCUSDT", spec)
    assert rig.store.hydrated("BTCUSDT", spec.spec_hash), "the stored tail was not read"
    return hold


def _items(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for frame in frames for item in h.structured_of(frame)["bars"]]


def _single_forming_newest(frame: dict[str, Any]) -> bool:
    """At most one bar of `frame` is unconfirmed, and it is the frame's newest."""
    keys = [(i["generation"], i["index"]) for i in h.structured_of(frame)["bars"]]
    forming = [(i["generation"], i["index"]) for i in h.structured_of(frame)["bars"]
               if not i["confirm"]]  # fmt: skip
    return len(forming) <= 1 and all(key == max(keys) for key in forming)


@pytest.mark.parametrize("mode", h.MODES)
def test_contract_bars_ws_frames_conform_to_bars_batch(mode: str) -> None:
    """AC2: on `bars.BTCUSDT.time.1`, a snapshot then 50 deltas from the recorded tape through the
    real builder: each frame valid against `cv://ws/v1/bars.schema.json` (checked on receipt and
    here by name), `s` 1 to 51 with none skipped, at most one `confirm: false` in a frame and that
    the newest bar, exactly one in the series the frames build; the snapshot's `meta` names the
    series' `spec_hash` and `build_version` (§6.1, §7.1, §14.3; C3, SR-E12-14)."""
    rig, mine = _Rig({}), _Series(binary=mode == "binary")
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": mode, "include_delta": True}})
        frames = [c.next_of("snap")]
        for emission in _emissions(_MINUTE, 0, 50):
            rig.emit(_MINUTE, *emission)
            frames.append(c.next_of("d"))
    for frame in frames:
        h.check_schema(BARS, h.structured_of(frame), f"{frame['t']} {frame['ch']}")
    assert [mine.apply(f) for f in frames] == [True] * 51
    assert [f["s"] for f in frames] == list(range(1, 52))
    assert all(map(_single_forming_newest, frames))
    assert [bar["confirm"] for bar in mine.bars.values()].count(False) == 1
    meta = frames[0]["meta"]
    assert (meta["spec_hash"], meta["build_version"]) == (_MINUTE.spec_hash, BUILD_VERSIONS["time"])


def _check_close_t_ms(frames: list[dict[str, Any]], bar_type: str) -> None:
    """§14.3: every item of a non-time bar carries `close_t_ms`, a time bar's none."""
    wrong = [(f["ch"], f["s"], item["index"]) for f in frames for item in h.structured_of(f)["bars"]
             if ("close_t_ms" in item) == (bar_type == "time")]  # fmt: skip
    where = h.schema_section(BARS)
    assert not wrong, f"close_t_ms is wrong on {wrong}: non-time bars only ({where})"


def _served(bar_type: str, param: str) -> bool:
    return _alternative({"bar_type": bar_type, "param": param}) is None


_SERVED: Final = [(t, p) for t, p in bar_type_params() if _served(t, p)]
_UNBUILT: Final = [(t, p) for t, p in bar_type_params() if not _served(t, p)]


def _stored_rig() -> _Rig:
    """A rig over the world's stored closed rows (the series store reads a forming one as a
    skipped row, and the series as not hydrated), with the catalogue's BTCUSDT `qty_step` (the
    `volume`/`delta` floor, SR-E12-03)."""
    rig = _Rig({key: [r for r in rows if r["is_closed"]] for key, rows in stored_rows().items()})
    rig.w.registry.services.qty_step = lambda _symbol: QTY_STEP
    return rig


@pytest.mark.parametrize(("bar_type", "param"), _SERVED)
def test_contract_bars_close_t_ms_is_sent_for_non_time_bars_only(bar_type: str, param: str) -> None:
    """§14.3 per documented bar type the server builds: its snapshot (hydrated from the stored
    rows) and a delta of its newest bar carry `close_t_ms` on every item for a non-time type and
    on none for `time`."""
    spec = from_wire(bar_type, param)
    rig, ch = _stored_rig(), f"bars.BTCUSDT.{bar_type}.{param}"
    with h.connect(rig.w) as c:
        hold = _hydrate(rig, spec)
        try:
            c.sub({"ch": ch, "opts": {"encoding": "structured"}})
            frames = [c.next_of("snap")]
            rig.emit(spec, _up("update", tape_bars(spec)[-1]))
            frames.append(c.next_of("d"))
        finally:
            hold.release()
    assert _items(frames)
    _check_close_t_ms(frames, bar_type)


@pytest.mark.parametrize(("bar_type", "param"), _UNBUILT)
def test_contract_bars_unbuilt_bar_types_are_invalid_topic_format(
    bar_type: str, param: str
) -> None:
    """As built (`_AS_BUILT`, OD6): a documented type the server does not build (`pnf`,
    `heikin_ashi`, ATR renko) is refused at `sub` as `invalid_topic_format`, holding nothing."""
    rig = _Rig({})
    with h.connect(rig.w) as c:
        (result,) = c.sub(f"bars.BTCUSDT.{bar_type}.{param}")["p"]["results"]
    refusal = (result["ok"], result.get("error", {}).get("code"))
    assert refusal == (False, "invalid_topic_format")
    assert (rig.store.series_count(), rig.leases.registered) == (0, [])


# -- AC5: binary and JSON encodings agree -------------------------------------------------------

_TICK: Final = _SERIES["tick", "100"]


def _encoding_script() -> list[list[BarUpdate]]:
    """One tick-100 series' updates after its first two closed bars: the tape's trades 200 to
    203 through the real builder (bar 2 opens and updates), a high finer than the instrument's
    price scale (C16), bar 2's real close, then that close amended (§8.2)."""
    tape = _emissions(_TICK, 200, 203)
    finer = tape[-1][-1].bar.model_copy(update={"high": tape[-1][-1].bar.high + Decimal("0.05")})
    close = _closed("tick", "100")[2]
    amended = close.model_copy(update={"close": close.open})
    return [*tape, [_up("update", finer)], [_up("close", close)],
            [_up("close", amended, amended=True)]]  # fmt: skip


def _encoding_rig() -> _Rig:
    """A rig holding the tick-100 series' first two closed bars, hydrated before any `sub`."""
    return _Rig({"tick:100": [bar_row(b, _TICK, generation=0) for b in _closed("tick", "100")[:2]]})


def _encoded(rig: _Rig, c: h.Client, mode: str) -> list[dict[str, Any]]:
    """The frames a subscription in `mode` gets for `_encoding_script`, the two stored bars as its
    snapshot; `include_delta` on, each update in a 250 ms window of its own (§8.1)."""
    hold = _hydrate(rig, _TICK)
    try:
        c.sub({"ch": "bars.BTCUSDT.tick.100", "opts": {"encoding": mode, "include_delta": True}})
        frames = [c.next_of("snap")]
        for emission in _encoding_script():
            rig.emit(_TICK, *emission)
            frames.append(c.next_of("d"))
    finally:
        hold.release()
    return frames


def _places(text: str) -> int:
    exponent = Decimal(text).normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _disagreements(structured: dict[str, Any], binary: dict[str, Any]) -> Iterator[str]:
    """How a JSON frame and its binary twin differ beyond what §3.4 allows: exact values at the
    binary frame's scales, `turnover` rounded half-even to `qty_scale`, the structured-only
    members (C19) and a JSON value finer than the frame's scales (C16). A twin the server sent
    structured too (an amended close) must equal it whole."""
    pairs = list(zip(h.structured_of(structured)["bars"], h.structured_of(binary)["bars"],
                     strict=True))  # fmt: skip
    if binary["e"] == "j":
        yield from (f"s={binary['s']}: {j} != {b}" for j, b in pairs if j != b)
        return
    part = h.cvwb_part(binary)
    scale = {**dict.fromkeys(_PRICES, part.price_scale), **dict.fromkeys(_SIZES, part.qty_scale)}
    unit = Decimal(1).scaleb(-part.qty_scale)
    for j, b in pairs:
        key = f"s={binary['s']} index {j['index']}"
        same = ("generation", "index", "t_ms", "trades", "confirm")
        yield from (f"{key}: {k}" for k in same if j[k] != b[k])
        yield from (f"{key}: {k}" for k in scale if Decimal(j[k]) != Decimal(b[k]))
        yield from (f"{key}: {k} finer than its scale" for k in scale if _places(j[k]) > scale[k])
        if Decimal(j["turnover"]).quantize(unit, ROUND_HALF_EVEN) != Decimal(b["turnover"]):
            yield f"{key}: turnover"
        if not _JSON_ONLY <= set(j) or _JSON_ONLY & set(b):
            yield f"{key}: {sorted(_JSON_ONLY)} are structured only"


def test_contract_bars_binary_and_json_encodings_agree() -> None:
    """AC5 (§3.4, §16.4; C15, C16, C19): one script on two rigs, one subscription structured, the
    other binary, decoded with the reference decoder: frame by frame, the same `t` and `s` and
    the same bars, exactly, at each binary frame's own scales; the amended close is structured on
    both. "All fields equal" is read through §3.4: kind 4 rounds `turnover` and has no slot for
    `close_t_ms`, `min_delta` and `max_delta`."""
    frames: dict[str, list[dict[str, Any]]] = {}
    for mode in h.MODES:
        rig = _encoding_rig()
        with h.connect(rig.w) as c:
            frames[mode] = _encoded(rig, c, mode)
    structured, binary = frames["structured"], frames["binary"]
    assert [(f["t"], f["s"]) for f in structured] == [(f["t"], f["s"]) for f in binary]
    assert [f["e"] for f in binary] == [c.binary_e] * 6 + ["j"]  # the amended close falls back
    assert h.cvwb_part(binary[4]).price_scale == 2  # the finer high: its frame's own scale
    assert [d for j, b in zip(structured, binary, strict=True) for d in _disagreements(j, b)] == []


# -- the drift guard: declared ⊆ emitted ----------------------------------------------------------


def _declared() -> set[str]:
    """The `BarsBatch` members §14.3 declares, by `wire_contract`'s own walk of the bundle."""
    bundle = wc._Bundle(json.loads(wc.BUNDLE.read_text(encoding="utf-8"))["schemas"])
    shapes: dict[str, Any] = {}
    bundle._visit(shapes, "bars", "", bundle.node("bars"))
    named = {"bars": "BarsBatch", "bars#/properties/bars/items": "BarsBatch.bars[]"}
    unnamed = sorted(set(shapes) - set(named))
    assert not unnamed, f"§14.3 BarsBatch has object schemas this walk does not name: {unnamed}"
    members = ((named[key], member) for key, shape in shapes.items() for member in shape["members"])
    return {f"{where}.{member}" for where, member in members}


def _sent(payload: dict[str, Any]) -> set[str]:
    items = {f"BarsBatch.bars[].{member}" for item in payload["bars"] for member in item}
    return {f"BarsBatch.{member}" for member in payload} | items


def _member_run() -> list[dict[str, Any]]:
    """The structured payloads of a run that sends every member a `bars` frame can carry: time and
    non-time, `include_delta` on and off, a binary subscription (whose structured frames alone
    count: kind 4 has no member names), an amended close and a merged window."""
    payloads: list[dict[str, Any]] = []
    rig = _Rig({})
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": "structured", "include_delta": True}})
        payloads.append(h.structured_of(c.next_of("snap")))
        for emission in _emissions(_MINUTE, 0, 5):
            rig.emit(_MINUTE, *emission)
            payloads.append(h.structured_of(c.next_of("d")))
    for mode in h.MODES:
        rig = _encoding_rig()
        with h.connect(rig.w) as c:
            payloads += [h.structured_of(f) for f in _encoded(rig, c, mode) if f["e"] == "j"]
    rig, mine = _Rig({}), _Series(binary=False)
    script = _script("forty_updates")
    with h.connect(rig.w) as c:
        c.sub({"ch": script.ch, "opts": {"encoding": "structured"}})
        mine.apply(c.next_of("snap"))
        payloads += [h.structured_of(f) for f in rig.play(c, mine, script.spec, script.windows)]
    return payloads


@pytest.fixture(scope="module")
def member_run() -> list[dict[str, Any]]:
    """`_member_run` on `cv.v1.json`, the wire set only while it runs."""
    token = h.use_wire("json")
    try:
        return _member_run()
    finally:
        h.reset_wire(token)


def _dead(payloads: list[dict[str, Any]]) -> list[str]:
    return sorted(_declared() - set[str]().union(*map(_sent, payloads)))


def test_contract_bars_batch_has_no_dead_member(member_run: list[dict[str, Any]]) -> None:
    """Dead-contract detection (§14.3, §6.1): every member `BarsBatch` declares is sent by some
    structured frame of the run, but for the justified `_DEAD_ALLOWED`. Emitted ⊆ declared is the
    harness's: `additionalProperties: false` on every frame it receives."""
    dead = [member for member in _dead(member_run) if member not in _DEAD_ALLOWED]
    assert not dead, f"§14.3 declares members no frame of the run sends: {dead}"


@pytest.mark.parametrize("member", sorted(_DEAD_ALLOWED))
def test_contract_bars_dead_member_allowlist_is_justified_and_current(
    member_run: list[dict[str, Any]], member: str
) -> None:
    """Each allowlisted member says why, is still declared and is still never sent."""
    assert _DEAD_ALLOWED[member].strip() and member in _dead(member_run)


# -- AC3: the breaking-change canary --------------------------------------------------------------


def _closed_for_confirm(bar: Bar, **kw: Any) -> dict[str, Any]:
    """`bar_item` with `confirm` renamed `closed`: the breaking change AC3 seeds (23 §14.3)."""
    item = bar_item(bar, **kw)
    if "confirm" in item:  # a server already renamed (the red commit) keeps its `closed`
        item["closed"] = item.pop("confirm")
    return item


def test_contract_bars_a_breaking_change_fails_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3 (30 §5.3 exit criterion 7): a server that sends `closed` instead of `confirm` fails
    the suite on its first frame with a bar, naming the offending member, the topic and
    `23-ws-protocol.md` §14.3, on either wire; the empty snapshot before it passes."""
    monkeypatch.setattr(bars_publish, "bar_item", _closed_for_confirm)
    monkeypatch.setattr(bars_source, "bar_item", _closed_for_confirm)
    rig = _Rig({})
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": "structured"}})
        c.next_of("snap")
        rig.emit(_MINUTE, _up("open", _closed("time", "1")[0]))
        with pytest.raises(AssertionError) as failed:
            c.next_of("d")
    named = ("$.bars[0]: 'confirm' is a required property", "'closed' was unexpected", f"d {CH}",
             "23-ws-protocol.md §14.3 BarsBatch")  # fmt: skip
    assert [part for part in named if part not in str(failed.value)] == []


# -- the seeded mutations: each check above must refuse a broken server ---------------------------


_DEC: Final = bars_wire._dec


def _numeric_open(value: Decimal, bar: Bar, generation: int, field: str) -> float | str:
    """`bars_wire._dec` sending the open price as a JSON number, its value right (float
    serialisation, C6), and every other decimal as it is."""
    return float(value) if field == "open" else _DEC(value, bar, generation, field)


#: Mutation -> (attribute of `bars_wire`, its seeded value, the series it is seen on, the check
#: that must refuse it as a regex of its message).
_MUTATIONS: Final[dict[str, tuple[str, object, tuple[str, str], str]]] = {
    "numeric-price": ("_dec", _numeric_open, ("time", "1"),
                      r"\$\.bars\[0\]\.o: [0-9.]+ is not of type 'string'"),
    "renko-without-close_t_ms": ("TIME_KINDS", frozenset({"time", "heikin_ashi", "renko"}),
                                 ("renko", "30"), r"close_t_ms .*non-time bars only"),
}  # fmt: skip


@pytest.mark.parametrize("mutation", list(_MUTATIONS))
def test_contract_bars_seeded_mutation_fails(
    mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ticket's negative self-test, WS half: a numeric price fails the harness's validation
    at its JSON path; a renko item without `close_t_ms` fails the `close_t_ms` rule, naming the
    member, the topic and §14.3."""
    attribute, seeded, (bar_type, param), named = _MUTATIONS[mutation]
    monkeypatch.setattr(bars_wire, attribute, seeded)
    spec, rig = from_wire(bar_type, param), _stored_rig()
    with h.connect(rig.w) as c, pytest.raises(AssertionError, match=named):
        c.sub({"ch": f"bars.BTCUSDT.{bar_type}.{param}", "opts": {"encoding": "structured"}})
        frames = [c.next_of("snap")]  # validated on receipt, as every frame after it
        rig.emit(spec, _up("update", tape_bars(spec)[-1]))
        frames.append(c.next_of("d"))
        _check_close_t_ms(frames, bar_type)


# -- security notes: the `param` bound ------------------------------------------------------------


def test_contract_bars_param_longer_than_max_length_is_refused() -> None:
    """§14.3's `param` `maxLength` holds at `sub`, the WS twin of the REST bound: one character
    over is `invalid_topic_format`, and nothing is held or registered."""
    bound = h.SCHEMAS[BARS]["properties"]["param"]["maxLength"]
    rig = _Rig({})
    with h.connect(rig.w) as c:
        (result,) = c.sub(f"bars.BTCUSDT.tick.{'1' * (bound + 1)}")["p"]["results"]
    refusal = (result["ok"], result.get("error", {}).get("code"))
    assert refusal == (False, "invalid_topic_format")
    assert (rig.store.series_count(), rig.leases.registered) == (0, [])
