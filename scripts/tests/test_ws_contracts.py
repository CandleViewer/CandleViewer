"""E17-T01: tests for tools/contracts (WS schema extraction, gate, constants)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
MD_TEXT = (REPO / "docs" / "plan" / "23-ws-protocol.md").read_text(encoding="utf-8")


def _load(name: str) -> ModuleType:
    path = REPO / "tools" / "contracts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_cv_{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ext = _load("extract_ws_schemas")
val = _load("validate_ws_schemas")
const = _load("gen_ws_constants")


def _doc(*blocks: str) -> str:
    body = "\n".join(f"```json\n{b}\n```\n" for b in blocks)
    return f"## 13. JSON Schemas\n\n{body}\n## 16. Conformance\n"


def test_extract_bundle_has_one_entry_per_fence() -> None:
    bundle = ext.build_bundle(MD_TEXT)
    section = ext.schema_section(MD_TEXT)
    assert bundle["schemaCount"] == len(ext.FENCE.findall(section)) == 36
    assert list(bundle["schemas"]) == sorted(bundle["schemas"])


def test_extract_duplicate_id_fails_loudly() -> None:
    block = '{"$id": "cv://x/a"}'
    with pytest.raises(ext.ExtractError, match="duplicate"):
        ext.extract_schemas(_doc(block, block))


def test_extract_invalid_json_fails_loudly() -> None:
    with pytest.raises(ext.ExtractError, match="not valid JSON"):
        ext.extract_schemas(_doc("{not json"))


def test_extract_comment_in_schema_block_fails() -> None:
    with pytest.raises(ext.ExtractError, match="not valid JSON"):
        ext.extract_schemas(_doc('{"$id": "cv://x/a" // c\n}'))


def test_extract_missing_id_and_empty_and_bad_bounds() -> None:
    with pytest.raises(ext.ExtractError, match=r"no string \$id"):
        ext.extract_schemas(_doc('{"type": "object"}'))
    with pytest.raises(ext.ExtractError, match="zero schemas"):
        ext.extract_schemas("## 13. x\n\n## 16. y\n")
    with pytest.raises(ext.ExtractError, match="locate"):
        ext.extract_schemas("nothing here")


def test_extract_new_block_appears_without_other_edit() -> None:
    a, b = '{"$id": "cv://x/a"}', '{"$id": "cv://x/b"}'
    assert set(ext.extract_schemas(_doc(a))) == {"cv://x/a"}
    assert set(ext.extract_schemas(_doc(a, b))) == {"cv://x/a", "cv://x/b"}


def test_extract_output_is_deterministic() -> None:
    one = ext.serialize(ext.build_bundle(MD_TEXT))
    two = ext.serialize(ext.build_bundle(MD_TEXT))
    assert one == two


def test_committed_bundle_is_fresh() -> None:
    assert ext.main(["--check"]) == 0


def test_extract_main_writes_and_detects_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    md = tmp_path / "p.md"
    md.write_text(_doc('{"$id": "cv://x/a"}'), encoding="utf-8")
    out = tmp_path / "b.json"
    assert ext.main(["--md", str(md), "--out", str(out), "--check"]) == 1  # missing
    assert ext.main(["--md", str(md), "--out", str(out)]) == 0
    assert ext.main(["--md", str(md), "--out", str(out), "--check"]) == 0
    out.write_text("{}", encoding="utf-8")
    assert ext.main(["--md", str(md), "--out", str(out), "--check"]) == 1
    md.write_text("broken", encoding="utf-8")
    assert ext.main(["--md", str(md), "--out", str(out)]) == 1
    assert "ERROR" in capsys.readouterr().err


@pytest.fixture(scope="module")
def schemas() -> dict[str, object]:
    return ext.build_bundle(MD_TEXT)["schemas"]  # type: ignore[no-any-return]


def test_gate_passes_on_real_document(schemas: dict[str, object]) -> None:
    assert val.check_schemas(schemas) == []
    errors, count = val.check_examples(schemas, MD_TEXT)
    assert errors == [] and count >= 30


def test_gate_names_id_and_keyword_for_invalid_schema(schemas: dict[str, object]) -> None:
    bad = json.loads(json.dumps(schemas))
    bad["cv://ws/v1/resync.schema.json"]["properties"]["reason"]["type"] = "strng"
    errors = val.check_schemas(bad)
    assert any("resync.schema.json" in e and "keyword" in e for e in errors)


def test_gate_names_referrer_and_target_for_dangling_ref(schemas: dict[str, object]) -> None:
    bad = json.loads(json.dumps(schemas))
    bad["cv://ws/v1/resync.schema.json"]["properties"]["last_seq"] = {
        "$ref": "cv://ws/v1/nope.json#/x"
    }
    errors = val.check_schemas(bad)
    assert any("resync.schema.json" in e and "nope.json" in e for e in errors)


def test_gate_fails_on_deliberately_broken_example(schemas: dict[str, object]) -> None:
    """Negative test: the gate must not be able to pass forever on broken examples."""
    broken = MD_TEXT.replace('"reason":"sequence_gap"}}', '"reason":"made_up_reason"}}', 1)
    assert broken != MD_TEXT
    errors, _ = val.check_examples(schemas, broken)
    assert any("resync" in e and "made_up_reason" in e for e in errors)


def test_gate_fails_when_example_envelope_is_broken(schemas: dict[str, object]) -> None:
    broken = MD_TEXT.replace('{"t":"resync","id":"c-90"', '{"t":"nonsense","id":"c-90"', 1)
    errors, _ = val.check_examples(schemas, broken)
    assert any("nonsense" in e for e in errors)


def test_parse_examples_strips_comments_and_handles_multiline() -> None:
    md = '## 12. x\n\n```jsonc\n// c\nC→S {"t":"sub","p":{"topics":[\n  {"ch":"orders"}]}}\n```\n## 13. y\n'
    frames = val.parse_examples(md)
    assert len(frames) == 1 and frames[0][1]["t"] == "sub"
    with pytest.raises(ValueError, match="section 12"):
        val.parse_examples("no section")
    with pytest.raises(ValueError, match="not JSON"):
        val.parse_examples("## 12. x\n\n```jsonc\nS→C {bad\n```\n## 13. y\n")


def test_payload_schema_id_routing() -> None:
    assert val.payload_schema_id({"t": "ping"}).endswith("heartbeat.schema.json")  # type: ignore[union-attr]
    assert val.payload_schema_id({"t": "d", "ch": "book.BTCUSDT.50", "e": "b"}) is None
    assert val.payload_schema_id({"t": "d", "ch": "orders"}).endswith("orders.schema.json")  # type: ignore[union-attr]
    machines = val.payload_schema_id({"t": "snap", "ch": "machines.kill_switch.state"})
    assert machines is not None and machines.endswith("machines.schema.json")
    assert val.payload_schema_id({"t": "err"}) is None


def test_validate_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert val.main(["--draft", "2020-12"]) == 0
    assert "ws_message_schemas" in capsys.readouterr().out
    md = tmp_path / "p.md"
    md.write_text(
        MD_TEXT.replace('"reason":"sequence_gap"}}', '"reason":"zzz"}}', 1), encoding="utf-8"
    )
    assert val.main(["--md", str(md)]) == 1


def test_constants_cover_section_6_and_are_fresh() -> None:
    assert const.main(["--check"]) == 0
    topics = const.topic_patterns(MD_TEXT)
    assert "orders" in topics and "book.{symbol}.{depth}" in topics
    text = const.OUT.read_text(encoding="utf-8")
    assert "GENERATED FILE - DO NOT EDIT BY HAND" in text
    assert re.search(r'"snap"', text)


def test_constants_main_writes_and_detects_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "g" / "c.py"
    monkeypatch.setattr(const, "OUT", out)
    assert const.main(["--check"]) == 1
    assert const.main([]) == 0
    assert const.main(["--check"]) == 0
    with pytest.raises(ValueError, match="section 6"):
        const.topic_patterns("x")


def test_every_coalesced_family_declares_the_disclosure_fields() -> None:
    """§8.2: a coalesced frame carries `coalesced` and `coalesced_count`, so every family the
    §8.1 "Coalescing" row names must declare both (E17-T03)."""
    row = re.search(r"^\| \*\*Coalescing\*\* +\|[^|]*\|([^|]*)\|", MD_TEXT, re.MULTILINE)
    assert row is not None
    families = [name.strip().rstrip(".").lower() for name in row.group(1).split(",")]
    assert len(families) == 8, f"§8.1 Coalescing row changed: {families}"
    schemas = ext.build_bundle(MD_TEXT)["schemas"]
    for family in families:
        props = schemas[f"cv://ws/v1/{family}.schema.json"]["properties"]
        assert {"coalesced", "coalesced_count"} <= props.keys(), family
        assert props["coalesced"].get("type") == "boolean", family
        assert props["coalesced_count"].get("type") == "integer", family
        assert props["coalesced_count"].get("minimum") == 1, family


def test_snap_meta_names_the_bar_build_identity(schemas: dict[str, object]) -> None:
    """SR-E12-14 (#399): a bars or footprint snapshot names its `spec_hash` and `build_version`."""
    from jsonschema import Draft202012Validator

    meta = Draft202012Validator(
        {"$ref": "cv://ws/v1/common.schema.json#/$defs/snapMeta"},
        registry=val.build_registry(schemas),
    )
    assert meta.is_valid({"reason": "initial", "spec_hash": "0" * 64, "build_version": 1})
    for bad in ({"spec_hash": "A" * 64}, {"spec_hash": "0" * 63}, {"build_version": 0}):
        assert not meta.is_valid({"reason": "initial", **bad}), bad


def test_snap_meta_echoes_include_delta_on_bars_frames(schemas: dict[str, object]) -> None:
    """#399: `meta.include_delta` says whether a kind-4 `delta` of 0 is real."""
    from jsonschema import Draft202012Validator

    meta = Draft202012Validator(
        {"$ref": "cv://ws/v1/common.schema.json#/$defs/snapMeta"},
        registry=val.build_registry(schemas),
    )
    assert meta.is_valid({"include_delta": False}) and meta.is_valid({"include_delta": True})
    assert not meta.is_valid({"include_delta": "no"})


def test_envelope_meta_carries_the_bars_fields_on_snap_and_d_frames(
    schemas: dict[str, object],
) -> None:
    """#399: the envelope `meta` is snapMeta on every frame type, so a `d` echoes `include_delta`;
    a bars snapshot carries no `meta.sources` (§6.1: the topic is tape-built only)."""
    from jsonschema import Draft202012Validator

    env = Draft202012Validator(
        {"$ref": "cv://ws/v1/envelope.schema.json"}, registry=val.build_registry(schemas)
    )
    frame = {"ch": "bars.BTCUSDT.time.5", "ts": 1789132262404, "e": "b", "p": "AAAA"}
    identity = {"spec_hash": "0" * 64, "build_version": 1, "include_delta": True}
    snap = {**frame, "t": "snap", "s": 1, "meta": {"reason": "initial", **identity}}
    delta = {**frame, "t": "d", "s": 2, "meta": {"include_delta": False}}
    assert env.is_valid(snap) and env.is_valid(delta)
    assert not env.is_valid({**delta, "meta": {"include_delta": False, "sources": ["tape"]}})


def test_snap_meta_names_the_bar_generation_swap_reason(schemas: dict[str, object]) -> None:
    """#399: a bars series whose generation changes is re-snapshotted with `generation_swap`
    (§7.4). The reason is in the closed `snapMeta` enum, and §7.4's prose lists that same set."""
    from jsonschema import Draft202012Validator

    meta = Draft202012Validator(
        {"$ref": "cv://ws/v1/common.schema.json#/$defs/snapMeta"},
        registry=val.build_registry(schemas),
    )
    assert meta.is_valid({"reason": "generation_swap", "previous_seq": 41})
    assert not meta.is_valid({"reason": "generation_swapped"})
    common = json.loads(json.dumps(schemas))["cv://ws/v1/common.schema.json"]
    enum = common["$defs"]["snapMeta"]["properties"]["reason"]["enum"]
    listed = re.search(r"^`reason` ∈ (.+)\.$", MD_TEXT, re.MULTILINE)
    assert listed is not None, "§7.4 no longer lists the reasons on one `reason` ∈ line"
    assert re.findall(r"`(\w+)`", listed.group(1)) == enum


def test_snap_meta_names_the_bar_history_repair_reason(schemas: dict[str, object]) -> None:
    """#2787: a held bars series whose store re-read repaired it is re-snapshotted with
    `history_repair` (§7.4). It is one member of the closed `snapMeta` enum, listed once; where it
    sits is not pinned here, because the order is pinned by the agreement tests (§7.4's list and
    `SNAP_REASONS`), so a later additive reason cannot break this one. That enum is open for
    clients (C18), the documented premise that makes a new member additive (C-6.3)."""
    from jsonschema import Draft202012Validator

    meta = Draft202012Validator(
        {"$ref": "cv://ws/v1/common.schema.json#/$defs/snapMeta"},
        registry=val.build_registry(schemas),
    )
    assert meta.is_valid({"reason": "history_repair", "previous_seq": 41})
    for near in ("history_repairs", "history_repaired", "history-repair", "History_repair"):
        assert not meta.is_valid({"reason": near}), near
    common = json.loads(json.dumps(schemas))["cv://ws/v1/common.schema.json"]
    reason = common["$defs"]["snapMeta"]["properties"]["reason"]
    assert reason["enum"].count("history_repair") == 1
    assert "MUST NOT validate" in reason["description"]
    c18 = r"^\| C18 \| Treat an unknown snap `reason` as a routine"
    assert re.search(c18, MD_TEXT, re.MULTILINE)


def test_snap_meta_carries_stale_as_a_boolean_that_may_be_absent(
    schemas: dict[str, object],
) -> None:
    """#3202 (§7.2): `meta.stale` says a snapshot may be behind the live market. It is a boolean the
    server sends only when true; a string or an integer is refused, and `snapMeta` stays closed
    (a near-miss key is refused, not ignored)."""
    from jsonschema import Draft202012Validator

    meta = Draft202012Validator(
        {"$ref": "cv://ws/v1/common.schema.json#/$defs/snapMeta"},
        registry=val.build_registry(schemas),
    )
    assert meta.is_valid({"stale": True}) and meta.is_valid({"stale": False})
    assert meta.is_valid({"reason": "initial"}), "a healthy snapshot's meta has no stale key"
    for bad in ("true", "false", "", 1, 0, None):
        assert not meta.is_valid({"stale": bad}), bad
    for near in ("Stale", "is_stale", "stale_", "stales"):
        assert not meta.is_valid({near: True}), near


def test_envelope_carries_stale_on_a_binary_and_a_structured_snap(
    schemas: dict[str, object],
) -> None:
    """#3202: `meta.stale` is on the envelope, so a binary snapshot (an opaque `p` with no field
    for the flag) and a structured one carry it alike (§7.2)."""
    from jsonschema import Draft202012Validator

    registry = val.build_registry(schemas)
    env = Draft202012Validator({"$ref": "cv://ws/v1/envelope.schema.json"}, registry=registry)
    bars = Draft202012Validator({"$ref": "cv://ws/v1/bars.schema.json"}, registry=registry)
    identity = {"spec_hash": "0" * 64, "build_version": 1, "include_delta": False}
    meta = {"reason": "initial", **identity, "stale": True}
    frame = {"t": "snap", "ch": "bars.BTCUSDT.time.5", "s": 1, "ts": 1789132262404}
    payload = {"symbol": "BTCUSDT", "bar_type": "time", "param": "5", "bars": []}
    binary = {**frame, "e": "b", "meta": meta, "p": "AAAA"}
    structured = {**frame, "e": "j", "meta": meta, "p": payload}
    assert env.is_valid(binary) and env.is_valid(structured) and bars.is_valid(payload)
    assert not env.is_valid({**binary, "meta": {**meta, "stale": "true"}})
    assert not env.is_valid({**structured, "meta": {**meta, "stale": 1}})


def test_bars_payload_refuses_a_stale_field_so_the_carrier_is_the_meta(
    schemas: dict[str, object],
) -> None:
    """#3202: the carrier is `meta.stale`, not a payload field. A binary `p` has no field to hold
    one, so a payload `stale` would reach structured subscribers only; `BarsBatch` stays closed."""
    from jsonschema import Draft202012Validator

    bars = Draft202012Validator(
        {"$ref": "cv://ws/v1/bars.schema.json"}, registry=val.build_registry(schemas)
    )
    payload = {"symbol": "BTCUSDT", "bar_type": "time", "param": "5", "bars": []}
    assert bars.is_valid(payload)
    assert not bars.is_valid({**payload, "stale": True})


def test_doc_names_meta_stale_and_its_two_causes_where_it_said_the_wire_had_none() -> None:
    """#3202: §7.7 no longer says `BarsBatch` has no `stale` field yet, §14.3 says where the flag
    is instead, §7.2 names its two causes and `meta.stale` and says when it is sent (only when
    true, as the snapshot was built, never on a `d`), §16.1 gives the client C21, and §12 shows
    one `meta.stale` frame, which the gate validates."""
    assert "has no `stale` field yet" not in MD_TEXT
    batch = MD_TEXT.split("### 14.3 `BarsBatch`")[1].split("\n### 14.4 ")[0]
    assert "`BarsBatch` has no `stale` field" in batch and "`meta.stale`" in batch
    snapshot = MD_TEXT.split("### 7.2 Snapshot frame")[1].split("\n### 7.3 ")[0]
    assert "freshness SLO" in snapshot and "quarantined" in snapshot and "`meta.stale`" in snapshot
    for said in ("only when true", "describes the snapshot as built", "never carries `meta.stale`"):
        assert said in snapshot, said
    assert len(re.findall(r"^\| C21 \| Show the staleness badge", MD_TEXT, re.MULTILINE)) == 1
    frames = [frame for _, frame in val.parse_examples(MD_TEXT)]
    assert any(f.get("meta", {}).get("stale") is True for f in frames), "§12: no meta.stale frame"


_RS = "bb000000-0000-4000-8000-000000000001"
_ENDED = {"ch": "trades.BTCUSDT", "ok": True, "ended": [{"sub_id": "s_01", "rs": _RS}]}


def test_section_12_examples_name_every_subscription_field() -> None:
    """#3218: the section-12 examples carry each new name, so the gate validates every one."""
    frames = [frame for _, frame in val.parse_examples(MD_TEXT)]
    names = ("resync", "ctl", "unsub", "sub_ok", "ctl_ok", "revoked", "unsub_ok", "err")
    shown = {t: [f for f in frames if f["t"] == t] for t in names}
    ended = [e for f in shown["unsub_ok"] for r in f["p"]["results"] for e in r.get("ended", [])]
    assert any("rs" in f and "sub_id" in f["p"] for f in shown["resync"]), "resync: rs, sub_id"
    assert any("rs" in f for f in shown["ctl"]), "ctl naming a replay stream by rs"
    assert any("rs" in f for f in shown["unsub"]), "unsub naming a replay stream by rs"
    assert any("rs" in r for f in shown["sub_ok"] for r in f["p"]["results"]), "sub_ok rs"
    assert any("rs" in f and "sub_id" in f["p"] for f in shown["ctl_ok"]), "ctl_ok: rs, sub_id"
    assert any("rs" in f and "sub_id" in f["p"] for f in shown["revoked"]), "revoked: rs, sub_id"
    assert any("rs" in e for e in ended), "an unsub_ok ended entry with rs"
    assert any("rs" in f for f in shown["err"]), "an err answering a replay request: rs"


@pytest.mark.parametrize(
    ("name", "valid", "broken"),
    [
        (
            "resync",
            {"reason": "manual", "sub_id": "s" * 64},
            {"reason": "manual", "sub_id": "s" * 65},
        ),
        ("resync", {"reason": "manual", "sub_id": "s"}, {"reason": "manual", "sub_id": ""}),
        ("ctl_ok", {"effective": {}, "sub_id": "s_01"}, {"effective": {}, "sub_id": 7}),
        (
            "revoked",
            {"reason": "topic_removed", "message": "m", "sub_id": "s_01"},
            {"reason": "topic_removed", "message": "m", "sub_id": "s" * 65},
        ),
        (
            "sub_ok",
            {"results": [{"ch": "trades.BTCUSDT", "ok": False, "rs": _RS}]},
            {"results": [{"ch": "trades.BTCUSDT", "ok": False, "rs": 5}]},
        ),
        ("unsub_ok", {"results": [_ENDED]}, {"results": [{**_ENDED, "ended": []}]}),
        ("unsub_ok", {"results": [_ENDED]}, {"results": [{**_ENDED, "ended": [{"rs": _RS}]}]}),
        (
            "unsub_ok",
            {"results": [_ENDED]},
            {"results": [{**_ENDED, "ended": [{"sub_id": "s_01", "x": 1}]}]},
        ),
    ],
    ids=[
        "resync-sub-id-over-64",
        "resync-sub-id-empty",
        "ctl-ok-sub-id-not-a-string",
        "revoked-sub-id-over-64",
        "sub-ok-rs-not-a-string",
        "unsub-ok-ended-empty",
        "unsub-ok-ended-without-sub-id",
        "unsub-ok-ended-unknown-key",
    ],
)
def test_subscription_names_reject_values_outside_the_contract(
    schemas: dict[str, object], name: str, valid: object, broken: object
) -> None:
    """#3218: `sub_id` and `rs` are checked, not only allowed: one change to a valid payload
    breaks it (`$defs/subId` is 1 to 64 characters; an `ended` entry needs its `sub_id`)."""
    payload = val.Draft202012Validator(
        {"$ref": f"cv://ws/v1/{name}.schema.json"}, registry=val.build_registry(schemas)
    )
    assert payload.is_valid(valid), f"{name}: the valid payload is refused"
    assert not payload.is_valid(broken), f"{name}: the broken payload is accepted"
