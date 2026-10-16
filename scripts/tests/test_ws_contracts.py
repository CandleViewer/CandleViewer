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
    # #2438 (E17-T08) adds one more fence; whichever of #2569/#2438 merges second bumps this to 36.
    assert bundle["schemaCount"] == len(ext.FENCE.findall(section)) == 35
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
