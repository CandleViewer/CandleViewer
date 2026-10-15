"""BarSpec validation, spec_hash canonicalisation and golden vectors (E12-T01)."""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.bars.errors import BarParamOutOfRange, BarSpecError
from candleviewer.bars.limits import RENKO_TICKS_RANGE
from candleviewer.bars.models import KIND_PARAM, PARAM_FIELDS, BarSpec
from candleviewer.bars.schema import golden_specs, render_schema, render_vectors
from candleviewer.bars.spec import (
    SpecRegistry,
    bar_specs_registered_total,
    canonical_json,
    check_param_bounds,
    dec_str,
    from_wire,
)

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT.parents[1] / "packages" / "fixtures" / "golden" / "bars"
KINDS = list(KIND_PARAM)

_VALUE: dict[str, object] = {
    "interval_ms": 60_000,
    "tick_count": 500,
    "volume_threshold": Decimal("50"),
    "range_ticks": 40,
    "delta_threshold": Decimal("25"),
}

positive_dec = st.decimals(
    min_value=Decimal("0.0001"), max_value=Decimal("1e9"), places=4, allow_nan=False
)


@st.composite
def specs(draw: st.DrawFn) -> BarSpec:
    kind = draw(st.sampled_from(KINDS))
    field = KIND_PARAM[kind]
    value: object = (
        draw(positive_dec) if field.endswith("threshold") else draw(st.integers(1, 10**9))
    )
    if kind == "renko":  # SR-E12-03 bounds are part of BarSpec validation (E12-S04)
        value = draw(st.integers(*RENKO_TICKS_RANGE))
    return BarSpec.model_validate(
        {
            "kind": kind,
            field: value,
            "price_source": draw(st.sampled_from(["last", "mark"])),
            "session_anchor_utc_min": draw(st.integers(0, 1439)),
            "align_to_epoch": draw(st.booleans()),
            "renko_wick": draw(st.booleans()),
            "reversal_bricks": draw(st.integers(1, 10)),
        }
    )


# --- Scenario: Mismatched kind and parameter is rejected ---------------------------------


def test_barspec_volume_with_tick_count_names_kind_and_field() -> None:
    with pytest.raises(ValidationError) as exc:
        BarSpec(kind="volume", tick_count=500, volume_threshold=None)
    msg = str(exc.value)
    assert "'volume'" in msg
    assert "tick_count" in msg


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("field", PARAM_FIELDS)
def test_barspec_validator_matrix(kind: str, field: str) -> None:
    payload = {"kind": kind, field: _VALUE[field]}
    if field == KIND_PARAM[kind]:
        assert getattr(BarSpec.model_validate(payload), field) == _VALUE[field]
    else:
        with pytest.raises(ValidationError, match=field):
            BarSpec.model_validate(payload)


@pytest.mark.parametrize("kind", KINDS)
def test_barspec_missing_param_names_required_field(kind: str) -> None:
    with pytest.raises(ValidationError, match=f"requires {KIND_PARAM[kind]}"):
        BarSpec.model_validate({"kind": kind})


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "tick", "tick_count": 0},
        {"kind": "volume", "volume_threshold": Decimal("-1")},
        {"kind": "volume", "volume_threshold": Decimal("NaN")},
        {"kind": "time", "interval_ms": 1, "session_anchor_utc_min": 1440},
        {"kind": "renko", "range_ticks": 3, "reversal_bricks": 0},
        {"kind": "renko", "range_ticks": 1},
        {"kind": "renko", "range_ticks": 100_001},
        {"kind": "renko", "range_ticks": 30, "reversal_bricks": 11},
        {"kind": "time", "interval_ms": 1, "fill_gaps": True},
    ],
)
def test_barspec_out_of_bounds_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BarSpec.model_validate(payload)


def test_barspec_is_frozen() -> None:
    spec = BarSpec(kind="tick", tick_count=1)
    with pytest.raises(ValidationError):
        setattr(spec, "tick_count", 2)  # noqa: B010 - asserting immutability at runtime


# --- Scenario: spec_hash is stable and canonical -----------------------------------------


def test_spec_hash_explicit_default_equals_omitted() -> None:
    a = BarSpec(kind="time", interval_ms=60_000)
    b = BarSpec(
        kind="time",
        interval_ms=60_000,
        price_source="last",
        session_anchor_utc_min=0,
        align_to_epoch=True,
        renko_wick=False,
        reversal_bricks=2,
    )
    assert a.spec_hash == b.spec_hash


def test_spec_hash_decimal_scale_irrelevant() -> None:
    a = BarSpec(kind="volume", volume_threshold=Decimal("50"))
    b = BarSpec(kind="volume", volume_threshold=Decimal("50.00"))
    c = BarSpec(kind="volume", volume_threshold=Decimal("5E+1"))
    assert a.spec_hash == b.spec_hash == c.spec_hash
    assert a == b


def test_spec_hash_is_64_hex_and_memoised() -> None:
    spec = BarSpec(kind="range", range_ticks=40)
    h = spec.spec_hash
    assert len(h) == 64 and int(h, 16) >= 0
    assert spec.spec_hash is h


def test_canonical_json_includes_every_field_sorted_without_whitespace() -> None:
    text = canonical_json(BarSpec(kind="tick", tick_count=1000))
    doc = json.loads(text)
    assert list(doc) == sorted(BarSpec.model_fields)
    assert " " not in text
    assert doc["volume_threshold"] is None and doc["reversal_bricks"] == 2


def test_dec_str_forms() -> None:
    assert dec_str(Decimal("-0.0")) == "0"
    assert dec_str(Decimal("1.2300")) == "1.23"
    assert dec_str(Decimal("1E+3")) == "1000"


@given(specs())
def test_spec_hash_survives_json_roundtrip(spec: BarSpec) -> None:
    again = BarSpec.model_validate_json(spec.model_dump_json())
    assert again.spec_hash == spec.spec_hash
    assert canonical_json(again) == canonical_json(spec)


@given(specs(), specs())
def test_spec_hash_distinct_specs_never_collide(a: BarSpec, b: BarSpec) -> None:
    assert (a == b) == (canonical_json(a) == canonical_json(b))
    assert (a == b) == (a.spec_hash == b.spec_hash)


@given(specs(), st.integers(0, 4))
def test_spec_hash_rescaled_decimal_is_identical(spec: BarSpec, extra: int) -> None:
    field = KIND_PARAM[spec.kind]
    v = getattr(spec, field)
    if not isinstance(v, Decimal):
        return
    rescaled = v.quantize(Decimal(1).scaleb(-(extra + 4)))
    other = spec.model_copy(update={field: rescaled})
    revalidated = BarSpec.model_validate(other.model_dump())
    assert revalidated.spec_hash == spec.spec_hash


def test_spec_hash_golden_vectors_unchanged() -> None:
    """'Unchanged across process restarts and Python versions': hashes pinned on disk."""
    doc = json.loads((GOLDEN / "spec_hash_vectors.json").read_text(encoding="utf-8"))
    assert doc["spec_hash_version"] == 1
    for spec, vec in zip(golden_specs(), doc["vectors"], strict=True):
        assert canonical_json(spec) == vec["canonical_json"]
        assert spec.spec_hash == vec["spec_hash"]


def test_spec_hash_stable_in_fresh_process() -> None:
    code = (
        "from candleviewer.bars.models import BarSpec;"
        "print(BarSpec(kind='tick', tick_count=1000).spec_hash)"
    )
    out = subprocess.run(  # noqa: S603 - fixed argv, sys.executable
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == BarSpec(kind="tick", tick_count=1000).spec_hash


def test_committed_bar_artifacts_are_fresh() -> None:
    script = ROOT / "scripts" / "generate_bar_artifacts.py"
    res = subprocess.run(  # noqa: S603 - fixed argv, sys.executable
        [sys.executable, str(script), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr


# --- Observability: spec_hash -> BarSpec resolution ---------------------------------------


def test_spec_registry_resolves_and_counts_once() -> None:
    reg = SpecRegistry()
    spec = BarSpec(kind="tick", tick_count=7)
    before = bar_specs_registered_total._value.get()
    h = reg.register(spec)
    reg.register(BarSpec(kind="tick", tick_count=7))
    assert reg.resolve(h) == spec
    assert reg.resolve("0" * 64) is None
    assert bar_specs_registered_total._value.get() == before + 1


def test_rendered_artifacts_match_committed_in_process() -> None:
    assert render_schema() == (GOLDEN / "bar-model.schema.json").read_text(encoding="utf-8")
    assert render_vectors() == (GOLDEN / "spec_hash_vectors.json").read_text(encoding="utf-8")


# -- SR-E12-03: one floor and ceiling for REST and the WS subscribe path (#399 slice E) -------


@pytest.mark.parametrize(
    ("bar_type", "param"),
    [("tick", "100"), ("tick", "1000000"), ("range", "2"), ("volume", "1"), ("time", "1")],
)
def test_check_param_bounds_accepts_the_floor_and_the_ceiling(bar_type: str, param: str) -> None:
    check_param_bounds(from_wire(bar_type, param), bar_type)


@pytest.mark.parametrize(
    ("bar_type", "param", "lo", "hi"),
    [("tick", "99", 100, 1_000_000), ("tick", "1000001", 100, 1_000_000),
     ("range", "1", 2, 100_000), ("delta", "1000000000001", 1, 10**12)],
)  # fmt: skip
def test_check_param_bounds_refuses_outside_them_naming_the_bound(
    bar_type: str, param: str, lo: int, hi: int
) -> None:
    with pytest.raises(BarParamOutOfRange) as err:
        check_param_bounds(from_wire(bar_type, param), bar_type)
    assert str(err.value) == f"param for bar_type {bar_type} must be between {lo} and {hi}."
    assert isinstance(err.value, BarSpecError)  # existing BarSpecError handlers still catch it
