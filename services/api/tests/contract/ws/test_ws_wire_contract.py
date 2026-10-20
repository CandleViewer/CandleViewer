"""E17-T07 (#572): the `cv.v1` wire-contract gate, `tools/contracts/wire_contract.py`.

The comparison is exercised on the contract the implementation really speaks (`collect()`), copied
and changed, so no repository file is touched; the collector is exercised on a copy of the layout
declaration and on a patched codec. The golden's own tests are at the end of the file."""

from __future__ import annotations

import copy
import functools
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[5]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.contracts import wire_contract as wc  # noqa: E402

from candleviewer.ws import binary, lifecycle  # noqa: E402
from tests.contract.ws import _spec_parity as sp  # noqa: E402

Contract = dict[str, Any]
Mutation = Callable[[Contract], None]


@functools.cache
def _base() -> wc.Collected:
    return wc.collect()


def _golden() -> Contract:
    return copy.deepcopy(_base().contract)


def _findings(mutate: Mutation) -> list[wc.Finding]:
    """The findings of the contract with `mutate` applied, against the contract as it is."""
    impl = _golden()
    mutate(impl)
    return wc.compare(_golden(), impl)


def _set(path: str, value: Any) -> Mutation:
    def apply(c: Contract) -> None:
        *parents, last = path.split("|")
        node: Any = c
        for key in parents:
            node = node[key]
        node[last] = value

    return apply


def _remove(path: str, value: Any) -> Mutation:
    def apply(c: Contract) -> None:
        node: Any = c
        for key in path.split("|"):
            node = node[key]
        node.remove(value)

    return apply


def _append(path: str, value: Any) -> Mutation:
    def apply(c: Contract) -> None:
        node: Any = c
        for key in path.split("|"):
            node = node[key]
        node.append(value)

    return apply


def _delete(path: str) -> Mutation:
    def apply(c: Contract) -> None:
        *parents, last = path.split("|")
        node: Any = c
        for key in parents:
            node = node[key]
        del node[last]

    return apply


def _name_reserved_byte(c: Contract) -> None:
    record = c["body_kinds"]["4"]["record"]
    at = next(n for n, f in enumerate(record) if f["type"].startswith("pad"))
    pad = record[at]
    record[at : at + 1] = [
        {"name": "hops", "type": "u8", "offset": pad["offset"], "size": 1},
        {
            "name": "reserved",
            "type": f"pad{pad['size'] - 1}",
            "offset": pad["offset"] + 1,
            "size": pad["size"] - 1,
        },
    ]


_ERROR = {"scope": "topic", "retryable": False, "close_code": None}
_KIND_7 = {"name": "x", "format_version": 1, "length_rule": "min", "record_stride": 8, "record": []}
_CTL = "control_frames"

BREAKING: list[Any] = [
    pytest.param(_set("header|magic", "0x43565743"), id="header-magic"),
    pytest.param(_set("body_kinds|4|format_version", 3), id="kind-4-format-version"),
    pytest.param(_delete("body_kinds|6"), id="body-kind-removed"),
    pytest.param(_remove(f"{_CTL}|auth|required", "access_token"), id="required-member-removed"),
    pytest.param(_append(f"{_CTL}|sub|required", "mode"), id="new-required-member"),
    pytest.param(_set(f"{_CTL}|welcome|members|protocol", "integer"), id="member-type-changed"),
    pytest.param(_delete("error_codes|forbidden"), id="error-code-removed"),
    pytest.param(_set("error_codes|internal_error|retryable", False), id="retryable-changed"),
    pytest.param(_remove("close_codes|gateway", 4429), id="close-code-removed"),
    pytest.param(_set("close_codes|reasons|shutdown|code", 1000), id="reason-moved-to-a-code"),
    pytest.param(_delete("topics|trades.{symbol}"), id="topic-removed"),
    pytest.param(_remove("envelope|frame_types", "ctl"), id="frame-type-removed"),
    pytest.param(_append("envelope|frame_types", "cancel"), id="frame-type-added"),
    pytest.param(_set("limits|max_subscriptions", {"floor": 100}), id="floor-lowered"),
    pytest.param(_set("limits|min_throttle_ms", {"ceiling": 100}), id="ceiling-raised"),
    pytest.param(_append("enums|welcome.encoding|values", "cbor"), id="closed-enum-grows"),
    pytest.param(_remove("enums|revoked.reason|values", "topic_removed"), id="enum-value-removed"),
    pytest.param(_remove("subprotocols|offered", "cv.v1.json"), id="subprotocol-removed"),
    # the golden pins the declared layout exactly: a header flag name and a reserved byte are in it
    pytest.param(_append("header|flags", "compressed"), id="header-flag-named"),
    pytest.param(_name_reserved_byte, id="reserved-byte-named"),
    # what the pre-freeze tightening set: `s` on a `d`, and the bounds of the options and `sub_id`
    pytest.param(_set("envelope|per_type_properties|d|s", "integer|null"), id="d-s-nullable-again"),
    pytest.param(_delete("envelope|per_type_properties|d"), id="d-members-removed"),
    pytest.param(_set("bounds|sub.options.from_seq|minimum", 1), id="request-minimum-raised"),
    pytest.param(_set("bounds|sub.options.metrics|maxItems", 6), id="request-list-shortened"),
    pytest.param(
        _set(
            "bounds|sub.options.metrics|items", {"type": "string", "minLength": 1, "maxLength": 16}
        ),
        id="request-item-length-shortened",
    ),
    pytest.param(_set("bounds|common.subId|maxLength", 4096), id="response-bound-widened"),
    pytest.param(_delete("bounds|common.subId|maxLength"), id="response-bound-removed"),
    pytest.param(
        _set("bounds|sub_ok.results.sub_id", {"side": "response", "type": "string"}),
        id="sub-id-no-longer-bounded",
    ),
    pytest.param(_delete("bounds|sub.options.status"), id="pinned-bound-removed"),
    pytest.param(_set("bounds|sub.options.from_seq|side", "response"), id="bound-side-changed"),
    pytest.param(
        _append(f"{_CTL}|welcome#/properties/limits|required", "max_things"),
        id="new-required-limits-key",
    ),
]
ADDITIVE: list[Any] = [
    pytest.param(_set("error_codes|new_code", _ERROR), id="error-code-added"),
    pytest.param(
        _set("close_codes|reasons|queue_full", {"code": 4429, "reconnect": True}),
        id="close-reason-added",
    ),
    pytest.param(_append("close_codes|gateway", 4430), id="close-code-added"),
    pytest.param(_set("body_kinds|7", _KIND_7), id="body-kind-7"),
    pytest.param(_set("limits|max_subscriptions", {"floor": 300}), id="floor-raised"),
    pytest.param(_set("limits|min_throttle_ms", {"ceiling": 20}), id="ceiling-lowered"),
    pytest.param(_set("limits|max_things", {"seen": 5}), id="limits-key-added"),
    pytest.param(
        _set(f"{_CTL}|common#/$defs/error|members|trace", "string"), id="err-optional-member"
    ),
    pytest.param(
        _set(f"{_CTL}|sub#/$defs/options|members|lookback", "integer"), id="sub-option-added"
    ),
    pytest.param(_set("topics|fills.{symbol}", "FillsBatch"), id="topic-added"),
    pytest.param(_append("enums|revoked.reason|values", "kill_switch"), id="open-enum-grows"),
    pytest.param(_append("subprotocols|offered", "cv.v1.cbor"), id="subprotocol-added"),
    pytest.param(_set("bounds|sub.options.metrics|maxItems", 16), id="request-list-widened"),
    pytest.param(_set("bounds|sub.options.from_seq|minimum", -1), id="request-minimum-lowered"),
    pytest.param(_set("bounds|common.subId|maxLength", 32), id="response-bound-narrowed"),
    pytest.param(
        _set("bounds|ctl.reason", {"side": "request", "type": "string", "maxLength": 64}),
        id="pinned-bound-added",
    ),
    pytest.param(
        _set(f"{_CTL}|welcome#/properties/limits|members|max_things", "integer"),
        id="welcome-limits-optional-key",
    ),
]


def test_the_implementation_agrees_with_itself() -> None:
    assert _base().findings == []
    assert wc.compare(_golden(), _base().contract) == []


# --- a deliberate breaking change fails, and says cv.v2 -------------------------------------------


def test_trades_record_stride_24_fails_with_a_cv_v2_message() -> None:
    findings = _findings(_set("body_kinds|3|record_stride", 24))
    assert [(f.severity, f.path, f.golden, f.impl) for f in findings] == [
        (wc.BREAKING, "body_kinds.3.record_stride", 22, 24)
    ]
    text = wc.render(findings)
    assert "cv.v1 WIRE CONTRACT CHANGED - 1 breaking finding" in text
    assert "golden 22, implementation 24" in text
    assert "packages/protocol/cvwb-layout.json -> kinds[trades].record_bytes" in text
    assert "cv.v2" in text and "served in parallel" in text and "section 2.3" in text
    assert "Do not edit the golden" in text


def test_declaration_edit_changing_trades_to_24_fails_the_real_collect(tmp_path: Path) -> None:
    layout = json.loads(wc.LAYOUT.read_text(encoding="utf-8"))
    trades = next(k for k in layout["kinds"] if k["name"] == "trades")
    trades["record"].append({"name": "pad2", "type": "pad2"})
    trades["record_bytes"] = 24
    edited = tmp_path / "cvwb-layout.json"
    edited.write_text(json.dumps(layout), encoding="utf-8")
    collected = wc.collect(layout_path=edited)
    findings = wc.check(_golden(), collected)
    paths = {f.path for f in wc.breaking(findings)}
    assert "body_kinds.3.record_stride" in paths  # the declaration is read, not a mutated dict
    assert any("generated twin" in f.labels for f in findings)  # and the twin was not regenerated


def test_codec_stride_drift_without_declaration_edit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    golden = _golden()  # before the patch: the cached baseline is the real codec's, in any order
    real = binary.encode

    def padded(frame: Any, weight: int = 0) -> bytes:
        raw = real(frame, weight)
        return raw + b"\x00\x00" * len(frame.records) if frame.body_kind == 3 else raw

    monkeypatch.setattr(binary, "encode", padded)
    findings = wc.check(golden, wc.collect())
    drift = [f for f in wc.breaking(findings) if f.path == "consistency.body_kinds.3.record_stride"]
    assert [(f.golden, f.impl) for f in drift] == [(22, 24)]
    assert "ws/binary.py" in wc.render(findings)


def test_two_bye_builders_that_disagree_are_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _ = lifecycle.CLOSE_REASONS["session_revoked"]
    monkeypatch.setitem(lifecycle.CLOSE_REASONS, "session_revoked", (code, True))
    found = [f.path for f in wc.breaking(wc.collect().findings)]
    assert found == ["consistency.close_codes.reasons.session_revoked"]


@pytest.mark.parametrize("mutate", BREAKING)
def test_breaking_mutation_fails(mutate: Mutation) -> None:
    findings = _findings(mutate)
    assert wc.breaking(findings), "a removed, renamed, retyped or tightened promise must fail"
    assert "cv.v2" in wc.render(findings)


# --- an additive change passes --------------------------------------------------------------------


def test_new_optional_member_and_new_topic_pass() -> None:
    def both(c: Contract) -> None:
        _set(f"{_CTL}|sub_ok#/properties/results/items|members|note", "string")(c)
        _set("topics|fills.{symbol}", "FillsBatch")(c)

    findings = _findings(both)
    assert findings and not wc.breaking(findings)
    notes = wc.render(findings)
    assert "NOTE additive: control_frames.sub_ok#/properties/results/items.members.note" in notes
    assert "NOTE additive: topics.fills.{symbol}" in notes
    assert "cv.v2" not in notes


@pytest.mark.parametrize("mutate", ADDITIVE)
def test_additive_mutation_passes(mutate: Mutation) -> None:
    findings = _findings(mutate)
    assert findings and {f.severity for f in findings} == {wc.ADDITIVE}


def test_new_required_member_is_breaking_even_beside_an_additive_one() -> None:
    def both(c: Contract) -> None:
        _set(f"{_CTL}|sub_ok#/properties/results/items|members|note", "string")(c)
        _append(f"{_CTL}|unsub|required", "force")(c)

    findings = _findings(both)
    assert [f.path for f in wc.breaking(findings)] == ["control_frames.unsub.required"]


def test_loosened_limit_passes_the_golden_but_not_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    golden = _golden()
    monkeypatch.setitem(lifecycle.LIMITS_BLOCK, "max_subscriptions", 300)
    impl = wc.collect().contract
    findings = wc.compare(golden, impl)
    assert [(f.severity, f.path, f.note) for f in findings] == [
        (wc.ADDITIVE, "limits.max_subscriptions", "loosened")
    ]
    runtime = {key: next(iter(bound.values())) for key, bound in impl["limits"].items()}
    assert [d.key for d in sp.limits_drifts(runtime)] == [
        "max_subscriptions"
    ]  # the document says 200


# --- undoing a pre-freeze tightening in the schemas is breaking -------------------------------

_SCHEMA_ID = "cv://ws/v1/{}.schema.json"
Schemas = dict[str, Any]


def _schema(schemas: Schemas, name: str) -> dict[str, Any]:
    schema: dict[str, Any] = schemas[_SCHEMA_ID.format(name)]
    return schema


def _d_clause(schemas: Schemas) -> dict[str, Any]:
    clauses = _schema(schemas, "envelope")["allOf"]
    then: dict[str, Any] = next(
        c["then"] for c in clauses if c["if"]["properties"].get("t", {}).get("const") == "d"
    )
    return then


def _options(schemas: Schemas) -> dict[str, Any]:
    options: dict[str, Any] = _schema(schemas, "sub")["$defs"]["options"]["properties"]
    return options


def _findings_after(edit: Callable[[Schemas], Any], tmp_path: Path) -> list[wc.Finding]:
    """The findings of the real collector over a copy of the schema bundle that `edit` changed."""
    bundle = json.loads(wc.BUNDLE.read_text(encoding="utf-8"))
    edit(bundle["schemas"])
    edited = tmp_path / "ws-schemas.json"
    edited.write_text(json.dumps(bundle), encoding="utf-8")
    return wc.check(_golden(), wc.collect(bundle_path=edited))


#: Taking back what the first commit of the branch set: each is breaking.
UNDO: list[Any] = [
    pytest.param(
        lambda s: _d_clause(s).pop("properties"),
        {"envelope.per_type_properties.d"},
        id="d-s-integer-rule-removed",
    ),
    pytest.param(
        lambda s: _schema(s, "common")["$defs"]["subId"].update(maxLength=4096),
        {"bounds.common.subId.maxLength", "bounds.sub_ok.results.sub_id.maxLength"},
        id="sub-id-max-length-raised",
    ),
    pytest.param(
        lambda s: _schema(s, "sub_ok")["properties"]["results"]["items"]["properties"].update(
            sub_id={"type": "string"}
        ),
        {"bounds.sub_ok.results.sub_id.minLength", "bounds.sub_ok.results.sub_id.maxLength"},
        id="sub-ok-sub-id-unbounded-again",
    ),
    pytest.param(
        lambda s: _options(s).update(
            from_seq={"$ref": _SCHEMA_ID.format("common") + "#/$defs/seq"}
        ),
        {"bounds.sub.options.from_seq.type"},
        id="from-seq-nullable-again",
    ),
]
#: Tightening a request bound beyond what the first commit set: breaking.
TIGHTEN: list[Any] = [
    pytest.param(
        lambda s: _options(s)["metrics"].update(maxItems=6),
        {"bounds.sub.options.metrics.maxItems"},
        id="metrics-list-shortened",
    ),
    pytest.param(
        lambda s: _options(s)["status"]["items"].update(maxLength=8),
        {"bounds.sub.options.status.items.maxLength"},
        id="status-item-length-shortened",
    ),
]
#: Taking a request bound back, or widening it: additive, one finding each.
LOOSEN: list[Any] = [
    pytest.param(
        lambda s: _options(s)["symbols"].pop("minItems"),
        "bounds.sub.options.symbols.minItems",
        id="symbols-min-items-removed",
    ),
    pytest.param(
        lambda s: _options(s)["rule_ids"].pop("maxItems"),
        "bounds.sub.options.rule_ids.maxItems",
        id="rule-ids-max-items-removed",
    ),
    pytest.param(
        lambda s: _options(s)["metrics"].update(maxItems=16),
        "bounds.sub.options.metrics.maxItems",
        id="metrics-max-items-raised",
    ),
]


@pytest.mark.parametrize(("undo", "paths"), UNDO)
def test_undoing_a_pre_freeze_tightening_in_the_schemas_is_breaking(
    undo: Callable[[Schemas], Any], paths: set[str], tmp_path: Path
) -> None:
    findings = _findings_after(undo, tmp_path)
    assert paths <= {f.path for f in wc.breaking(findings)}
    assert "cv.v2" in wc.render(findings)


@pytest.mark.parametrize(("tighten", "paths"), TIGHTEN)
def test_tightening_a_pre_freeze_request_bound_further_is_breaking(
    tighten: Callable[[Schemas], Any], paths: set[str], tmp_path: Path
) -> None:
    findings = _findings_after(tighten, tmp_path)
    assert paths <= {f.path for f in wc.breaking(findings)}
    assert "cv.v2" in wc.render(findings)


@pytest.mark.parametrize(("loosen", "path"), LOOSEN)
def test_undoing_or_widening_a_request_bound_in_the_schemas_is_additive(
    loosen: Callable[[Schemas], Any], path: str, tmp_path: Path
) -> None:
    findings = _findings_after(loosen, tmp_path)
    assert [(f.severity, f.path, f.note) for f in findings] == [(wc.ADDITIVE, path, "widened")]


# --- a damaged golden is an error, not nothing to compare -------------------------------------


@pytest.mark.parametrize("group", wc.GROUPS)
def test_a_golden_without_a_group_is_an_error(group: str) -> None:
    golden = _golden()
    del golden[group]
    findings = wc.compare(golden, _base().contract)
    assert [f.path for f in wc.breaking(findings)] == [f"golden.{group}"]
    text = wc.render(findings)
    assert "git restore" in text and "never rewritten" in text
    assert "cv.v2" not in text  # the golden is damaged: no promise was broken


@pytest.mark.parametrize("group", wc.GROUPS)
def test_a_golden_with_a_group_emptied_is_an_error(group: str) -> None:
    golden = _golden()
    golden[group] = "" if group == "contract" else {}
    findings = wc.compare(golden, _base().contract)
    assert [f.path for f in wc.breaking(findings)] == [f"golden.{group}"]


def test_a_golden_missing_a_member_of_a_group_is_one_finding_not_a_traceback() -> None:
    golden = _golden()
    del golden["envelope"]["per_type_properties"]
    findings = wc.check(golden, _base())
    assert [f.path for f in wc.breaking(findings)] == ["golden"]
    assert "malformed" in wc.render(findings)


def test_the_modes_refuse_a_damaged_golden_and_leave_it_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    damaged = _golden()
    del damaged["control_frames"], damaged["enums"]
    path = tmp_path / "golden.json"
    path.write_text(wc.render_golden(damaged), encoding="utf-8")
    assert wc.main(["--golden", str(path)]) == 1
    assert "golden.control_frames" in capsys.readouterr().err
    assert wc.main(["--extend", "--golden", str(path)]) == 1  # --extend does not repair it
    assert path.read_text(encoding="utf-8") == wc.render_golden(damaged)
    path.write_text("{", encoding="utf-8")
    assert wc.main(["--golden", str(path)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("group", "name"),
    [
        ("bounds", "common.subId"),
        ("bounds", "sub_ok.results.sub_id"),
        ("enums", "welcome.encoding"),
        ("limits", "max_subscriptions"),
    ],
)
def test_a_pin_the_tool_declares_that_the_golden_lacks_is_damage_not_news(
    group: str, name: str
) -> None:
    golden = _golden()
    del golden[group][name]
    findings = wc.compare(golden, _base().contract)
    assert [(f.severity, f.path) for f in findings] == [(wc.BREAKING, f"golden.{group}.{name}")]
    text = wc.render(findings)
    assert "golden is damaged" in text and "WIRE CONTRACT CHANGED" not in text
    assert "cv.v2" not in text


def test_extend_cannot_record_a_breaking_change_after_the_golden_lost_its_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    impl = _golden()  # sub_id may now be 4096 characters: breaking, as the check says
    impl["bounds"]["common.subId"]["maxLength"] = 4096
    impl["bounds"]["sub_ok.results.sub_id"]["maxLength"] = 4096
    monkeypatch.setattr(wc, "collect", lambda **_: wc.Collected(impl))
    path = tmp_path / "golden.json"
    path.write_text(wc.render_golden(_golden()), encoding="utf-8")
    assert wc.main(["--golden", str(path)]) == 1
    assert "bounds.common.subId.maxLength" in capsys.readouterr().err
    lost = _golden()  # the same golden after the two entries were deleted by hand
    del lost["bounds"]["common.subId"], lost["bounds"]["sub_ok.results.sub_id"]
    path.write_text(wc.render_golden(lost), encoding="utf-8")
    assert wc.main(["--extend", "--golden", str(path)]) == 1
    assert "golden.bounds.common.subId" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == wc.render_golden(lost)  # nothing was rewritten


def test_a_name_in_pin_additions_is_extended_and_not_damage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = _golden()
    del golden["bounds"]["common.subId"]
    monkeypatch.setattr(wc, "PIN_ADDITIONS", frozenset({"bounds.common.subId"}))
    findings = wc.compare(golden, _base().contract)
    assert [(f.severity, f.path) for f in findings] == [(wc.ADDITIVE, "bounds.common.subId")]
    path = tmp_path / "golden.json"
    path.write_text(wc.render_golden(golden), encoding="utf-8")
    assert wc.main(["--extend", "--golden", str(path)]) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == _golden()  # the pin is recorded


def test_a_group_in_pin_additions_is_extended_and_not_damage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = _golden()
    del golden["bounds"]
    monkeypatch.setattr(wc, "PIN_ADDITIONS", frozenset({"bounds"}))
    findings = wc.compare(golden, _base().contract)
    assert findings and {f.severity for f in findings} == {wc.ADDITIVE}
    assert {f.path for f in findings} == {f"bounds.{name}" for name in wc.PINNED_BOUNDS}


def test_a_golden_with_an_empty_limit_is_one_finding_and_not_a_traceback() -> None:
    golden = _golden()
    golden["limits"]["max_subscriptions"] = {}
    findings = wc.check(golden, _base())
    assert [f.path for f in wc.breaking(findings)] == ["golden"]
    text = wc.render(findings)
    assert "golden is damaged" in text and "malformed - StopIteration" in text


# --- the modes --------------------------------------------------------------------------------


def test_write_creates_the_golden_once_and_refuses_to_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    assert wc.main(["--write", "--golden", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == wc.render_golden(_base().contract)
    assert wc.main(["--golden", str(path)]) == 0
    assert wc.main(["--write", "--golden", str(path)]) == 1


def test_check_fails_when_there_is_no_golden(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert wc.main(["--golden", str(tmp_path / "none.json")]) == 1
    err = capsys.readouterr().err
    assert "restore it from git" in err and "git restore --" in err
    assert "first freeze" in err  # --write is named only to say what it is for


def test_check_prints_the_breaking_report_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "golden.json"
    path.write_text(wc.render_golden(_golden()), encoding="utf-8")
    impl = _golden()
    impl["body_kinds"]["3"]["record_stride"] = 24
    monkeypatch.setattr(wc, "collect", lambda **_: wc.Collected(impl))
    assert wc.main(["--golden", str(path)]) == 1
    err = capsys.readouterr().err
    assert "body_kinds.3.record_stride: golden 22, implementation 24" in err and "cv.v2" in err


def test_extend_records_an_additive_diff_and_refuses_a_breaking_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "golden.json"
    before = wc.render_golden(_golden())
    path.write_text(before, encoding="utf-8")
    additive = _golden()
    additive["topics"]["fills.{symbol}"] = "FillsBatch"
    monkeypatch.setattr(wc, "collect", lambda **_: wc.Collected(additive))
    assert wc.main(["--extend", "--golden", str(path)]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["topics"]["fills.{symbol}"] == "FillsBatch"
    breaking = _golden()
    del breaking["topics"]["trades.{symbol}"]
    monkeypatch.setattr(wc, "collect", lambda **_: wc.Collected(breaking))
    written = path.read_text(encoding="utf-8")
    assert wc.main(["--extend", "--golden", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == written  # nothing was rewritten


def test_write_refuses_a_contract_whose_own_sources_disagree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disagreeing = wc.Collected(_golden(), [wc._inconsistent("x", 1, 2, ("a", "b"), "somewhere")])
    monkeypatch.setattr(wc, "collect", lambda **_: disagreeing)
    assert wc.main(["--write", "--golden", str(tmp_path / "golden.json")]) == 1
    assert not (tmp_path / "golden.json").exists()


# --- the committed golden -----------------------------------------------------------------------


def test_the_committed_golden_is_kept_by_the_implementation() -> None:
    """The gate itself, run by the `contract` job and the `py` job's contract lane, so a PR that
    touches `ws/limits.py` and nothing else still meets it."""
    golden = json.loads(wc.GOLDEN.read_text(encoding="utf-8"))
    findings = wc.check(golden, _base())
    assert not wc.breaking(findings), wc.render(findings)


def test_the_committed_golden_is_the_tools_own_rendering() -> None:
    """Written by `--write` or `--extend`: a reformatted or reflowed file differs. An edited value
    renders the same, and is caught by the check against the implementation."""
    text = wc.GOLDEN.read_text(encoding="utf-8")
    assert text == wc.render_golden(json.loads(text))


def test_the_golden_is_not_marked_generated_so_its_diff_is_shown_in_review() -> None:
    attrs = [
        line.split()[1:]
        for line in (_REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
        if line.split()[:1] == [wc.GOLDEN_PATH]
    ]
    assert len(attrs) == 1 and {"text", "eol=lf"} <= set(attrs[0])
    assert not [
        a for a in attrs[0] if a.startswith("linguist-generated") or a in {"-diff", "binary"}
    ]
    ignored = (_REPO / ".prettierignore").read_text(encoding="utf-8").splitlines()
    assert wc.GOLDEN_PATH in ignored  # prettier must not reflow the tool's own rendering


def test_make_contracts_runs_the_wire_contract_check_and_never_a_mode_that_writes() -> None:
    lines = (_REPO / "Makefile").read_text(encoding="utf-8").splitlines()
    start = lines.index("contracts:")
    recipe = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line)
    (step,) = [line for line in recipe if "wire_contract.py" in line]
    assert step.strip() == "uv run --project services/api python tools/contracts/wire_contract.py"
