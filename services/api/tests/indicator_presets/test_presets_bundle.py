"""`WorkspaceBundle.indicator_presets` export and import (E13-T03, #427; SR-E13-07, IR-06,
IR-26, IR-35, AC-09, AC-24) through `IndicatorPresetService`. No operation takes a bundle yet
(E15-S07 adds it), so these drive the service; the atomic import on real Postgres is
`tests/integration/storage/test_indicator_presets_repository.py`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _presets_env import (
    BUILTIN_IDS,
    USER_A,
    USER_B,
    Audit,
    FakePresetRepo,
    Metrics,
    body,
    new_ids,
    principal,
)
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.indicator_presets_models import PresetInput, PresetInvalidError
from candleviewer.api.indicator_presets_service import (
    IndicatorPresetService,
    PresetBundleTooLargeError,
    PresetStoreUnavailableError,
)
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.orderflow.indicators.catalogue import default_catalogue
from candleviewer.orderflow.indicators.limits import (
    BUNDLE_IMPORT_MAX_BYTES,
    BUNDLE_IMPORT_PRESETS_MAX,
    PRESETS_PER_USER_MAX,
)
from candleviewer.storage.repositories.indicator_presets import PresetConflictError

_SPEC: dict[str, Any] = load_openapi_spec()
_BASE = "urn:cv:22-api-openapi"
_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(_SPEC))
_INPUT_FIELDS = sorted(_SPEC["components"]["schemas"]["IndicatorPresetInput"]["properties"])


def _errors(pointer: str, doc: Any) -> list[str]:
    ref, checker = {"$ref": f"{_BASE}#{pointer}"}, Draft202012Validator.FORMAT_CHECKER
    validator = Draft202012Validator(ref, registry=_REGISTRY, format_checker=checker)
    return [e.message for e in validator.iter_errors(doc)]


class _Env:
    def __init__(self) -> None:
        self.repo, self.audit, self.metrics, self.up = FakePresetRepo(), Audit(), Metrics(), True
        self.service = IndicatorPresetService(
            lambda: self.repo if self.up else None, default_catalogue(), self.audit,
            new_id=new_ids(), metrics=self.metrics,
        )  # fmt: skip

    async def create(self, user: Any = USER_A, **over: Any) -> str:
        row = await self.service.create(principal(user), PresetInput.model_validate(body(**over)))
        return row.id


async def test_export_has_no_owner_builtin_or_other_users_preset() -> None:
    """IR-26: only the caller's live presets, as closed `IndicatorPresetInput`s."""
    env = _Env()
    mine = await env.create(name="Mine")
    gone = await env.create(name="Gone")
    await env.service.soft_delete(principal(), gone)
    await env.create(USER_B, name="Theirs")
    exported = await env.service.export_for_bundle(str(USER_A))
    assert [item["name"] for item in exported] == ["Mine"] and mine not in json.dumps(exported)
    assert all(sorted(item) == _INPUT_FIELDS for item in exported)
    assert not any(pid in json.dumps(exported) for pid in BUILTIN_IDS)
    bundle = "/components/schemas/WorkspaceBundle/properties/indicator_presets"
    assert _errors(bundle, exported) == []


async def test_roundtrip_create_list_update_delete_export_import() -> None:
    """The ticket's test plan: create -> list -> update -> delete -> export -> import."""
    env = _Env()
    a = principal()
    first = await env.create(name="Fast", params={"n": 7})
    keep = await env.create(name="Slow", params={"n": 50}, is_favourite=True)
    assert {first, keep} <= {r.id for r in await env.service.list_visible(str(USER_A))}
    faster = PresetInput.model_validate(body(name="Faster", params={"n": 5}))
    await env.service.replace(a, first, faster)
    await env.service.soft_delete(a, keep)
    exported = await env.service.export_for_bundle(str(USER_A))
    assert exported == [body(name="Faster", params={"n": 5})]
    imported = await env.service.import_from_bundle(principal(USER_B), exported)
    assert [(r.owner_user_id, r.name, r.params, r.is_builtin) for r in imported] == [
        (str(USER_B), "Faster", {"n": 5}, False)
    ]
    assert env.audit.actions()[-1] == "indicator_preset.imported"


async def test_import_owns_what_it_imports_and_renames_a_held_name() -> None:
    env = _Env()
    await env.create(name="Fast")
    rows = await env.service.import_from_bundle(principal(), [body(name="Fast"), body(name="fast")])
    assert [r.name for r in rows] == ["Fast (2)", "fast (3)"]
    assert all(r.owner_user_id == str(USER_A) and not r.is_builtin for r in rows)


@pytest.mark.parametrize(
    ("item", "field", "rule"),
    [
        (body(is_builtin=True), "indicator_presets.1.is_builtin", "extra_forbidden"),
        (body(owner_user_id=str(USER_B)), "indicator_presets.1.owner_user_id", "extra_forbidden"),
        (body(id="0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c"), "indicator_presets.1.id",
         "extra_forbidden"),
        (body(indicator_code="nope"), "indicator_presets.1.indicator_code", "unknown_indicator"),
        (body(style={"line": "#ff0000"}), "indicator_presets.1.style", "style_not_allowed"),
        (body(style={"k": "v" * 5000}), "indicator_presets.1.style", "style_not_allowed"),
        (body(params={"n": 14, "sl_atr_period": 14}), "indicator_presets.1.params",
         "additionalProperties"),
        (body(sl_atr_multiple=2), "indicator_presets.1.sl_atr_multiple", "extra_forbidden"),
        (body(params={"n": 0}), "indicator_presets.1.params.n", "minimum"),
        ("not an object", "indicator_presets.1", "model_type"),
    ],
)  # fmt: skip
async def test_hostile_bundle_is_rejected_atomically(item: Any, field: str, rule: str) -> None:
    """AC-09/AC-24, IR-06/IR-10: one invalid item refuses the whole array; nothing is written
    and no audit record claims an import."""
    env = _Env()
    before, calls = dict(env.repo.rows), len(env.audit.calls)
    with pytest.raises(PresetInvalidError) as err:
        await env.service.import_from_bundle(principal(), [body(name="valid"), item])
    assert [(e["field"], e["rule"]) for e in err.value.errors] == [(field, rule)]
    assert env.repo.rows == before and len(env.audit.calls) == calls
    assert not any(name == "import_many" for name, _ in env.repo.calls)


async def test_more_than_200_presets_is_refused_whole() -> None:
    env = _Env()
    items = [body(name=f"p{i}") for i in range(BUNDLE_IMPORT_PRESETS_MAX + 1)]
    with pytest.raises(PresetBundleTooLargeError) as err:
        await env.service.import_from_bundle(principal(), items)
    assert err.value.rule == "too_many_presets" and env.repo.calls == []
    rows = await env.service.import_from_bundle(principal(), items[:BUNDLE_IMPORT_PRESETS_MAX])
    assert len(rows) == BUNDLE_IMPORT_PRESETS_MAX  # exactly 200 is accepted


async def test_more_than_1_mib_of_preset_json_is_refused_whole() -> None:
    env = _Env()
    big = body(params={"k": "v" * 6000})  # checked before any item is: 6 KB each
    items = [big] * 199  # under 200 items, over 1 MiB in all (AC-09: "one of 1.1 MiB")
    assert len(json.dumps(items)) > BUNDLE_IMPORT_MAX_BYTES
    with pytest.raises(PresetBundleTooLargeError) as err:
        await env.service.import_from_bundle(principal(), items)
    assert err.value.rule == "too_large" and env.repo.calls == []


async def test_an_import_past_500_live_presets_is_limit_reached_and_imports_nothing() -> None:
    env = _Env()
    for i in range(PRESETS_PER_USER_MAX - 1):
        await env.create(name=f"p{i}")
    with pytest.raises(PresetConflictError) as err:
        await env.service.import_from_bundle(principal(), [body(name="x"), body(name="y")])
    assert err.value.rule == "limit_reached"
    assert len(env.repo.own_live(str(USER_A))) == PRESETS_PER_USER_MAX - 1


async def test_not_an_array_is_refused() -> None:
    with pytest.raises(PresetInvalidError) as err:
        await _Env().service.import_from_bundle(principal(), {"name": "x"})
    assert err.value.errors[0]["rule"] == "list_type"


async def test_errors_across_items_are_capped_at_20() -> None:
    env = _Env()
    items = [body(indicator_code="nope", style={"x": 1}) for _ in range(30)]
    with pytest.raises(PresetInvalidError) as err:
        await env.service.import_from_bundle(principal(), items)
    assert len(err.value.errors) == 20


async def test_the_import_record_is_written_ahead_and_carries_no_parameters() -> None:
    env = _Env()
    rows = await env.service.import_from_bundle(principal(), [body(name="a"), body(name="b")])
    (record,) = [c for c in env.audit.calls if c["action"] == "indicator_preset.imported"]
    after = record["after_state"]
    assert sorted(after) == ["content_sha256", "count", "preset_ids"]
    assert after["count"] == 2 and after["preset_ids"] == [r.id for r in rows]
    assert len(after["content_sha256"]) == 64 and "params" not in json.dumps(record, default=str)
    assert (record["object_kind"], record["object_id"]) == ("indicator_preset", None)


async def test_a_refused_audit_record_imports_nothing() -> None:
    env = _Env()
    env.audit.fail = AuditUnavailable("down")
    before = dict(env.repo.rows)
    with pytest.raises(AuditUnavailable):
        await env.service.import_from_bundle(principal(), [body(name="a")])
    assert env.repo.rows == before
    assert not any(name == "import_many" for name, _ in env.repo.calls)


async def test_no_store_is_unavailable_and_validation_still_comes_first() -> None:
    env = _Env()
    env.up = False
    with pytest.raises(PresetInvalidError):
        await env.service.import_from_bundle(principal(), [body(indicator_code="nope")])
    with pytest.raises(PresetStoreUnavailableError):
        await env.service.import_from_bundle(principal(), [body()])
    with pytest.raises(PresetStoreUnavailableError):
        await env.service.export_for_bundle(str(USER_A))


async def test_the_gauge_counts_built_ins_and_user_presets_after_an_import() -> None:
    env = _Env()
    await env.service.import_from_bundle(principal(), [body(name="a"), body(name="b")])
    assert env.metrics.presets.values == {("true",): 18, ("false",): 2}
