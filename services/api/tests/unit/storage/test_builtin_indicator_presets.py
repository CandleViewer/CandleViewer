"""The 18 built-in indicator presets (E13-T03, #427): `db/builtin_indicator_presets.py` against
21 Sec.10.5, its pinned ids, the seed statement, and the catalogue it is checked against.

The revision's frozen literals are pinned to this module by `test_0040_indicator_presets.py`; the
re-seed on real Postgres is in `tests/integration/storage/test_indicator_presets_migration.py`.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from candleviewer.db import seed
from candleviewer.db.builtin_indicator_presets import (
    BUILTIN_NAMESPACE,
    BUILTIN_PRESETS,
    builtin_preset_id,
)
from candleviewer.orderflow.errors import InvalidParamsError
from candleviewer.orderflow.indicators.catalogue import default_catalogue, validate_params

_DOC = Path(__file__).resolve().parents[5] / "docs" / "plan" / "21-database-schema.md"
_SIGMA = "vwap(session, ±1\u03c3, ±2\u03c3)"  # \u03c3: sigma, escaped for RUF001
#: label -> why the catalogue cannot validate the row today. A row named here must still fail;
#: once it validates (its indicator registered or its anchor added), the stale check below fails
#: until the entry is removed (the composition allowlist's pattern).
PENDING: dict[str, str] = {
    "cvd(never reset)": "the cvd anchor is session or utc_day; 24 Sec.7.2 has no since_load",
    "delta(bar)": "delta is a rule-metric kernel kept out of V1_INDICATORS",
    "volume_profile(VA 70 %, session)": "no descriptor yet (an R2 indicator)",
    "delta_profile(VA 70 %)": "no descriptor yet (an R2 indicator)",
    "oi(absolute)": "no descriptor yet (an R2 indicator)",
    "oi(delta per bar)": "no descriptor yet (an R2 indicator)",
    "funding(annualised)": "no descriptor yet (an R2 indicator)",
    "speed_of_tape(5 s)": "no descriptor yet (an R2 indicator)",
    "imbalance_tracker(300 %, stack 3)": "no descriptor yet (an R2 indicator)",
    "market_regime(default)": "no descriptor yet (an R2 indicator)",
}
_PANE = {"price": "overlay", "sub": "subpane"}


def _section_10_5_labels() -> list[str]:
    text = _DOC.read_text(encoding="utf-8")
    section = text[text.index("### 10.5 Built-in indicator presets") : text.index("### 10.6")]
    first_paragraph = section.split("\n\n", 2)[1]  # the label list, before the notes and table
    return re.findall(r"`([^`]+)`", first_paragraph)


def test_seed_rows_equal_section_10_5_of_doc_21_in_its_order() -> None:
    labels = _section_10_5_labels()
    assert len(labels) == 18 and _SIGMA in labels
    assert [p.name for p in BUILTIN_PRESETS] == labels
    assert [p.indicator_code for p in BUILTIN_PRESETS] == [x.split("(", 1)[0] for x in labels]


def test_seed_ids_are_the_pinned_uuid5s_of_code_and_name() -> None:
    url = "https://candleviewer.local/indicator-presets/builtin"
    assert uuid.uuid5(uuid.NAMESPACE_URL, url) == BUILTIN_NAMESPACE
    for p in BUILTIN_PRESETS:
        assert p.id == str(builtin_preset_id(p.indicator_code, p.name)), p.name
        assert p.id == str(uuid.uuid5(BUILTIN_NAMESPACE, f"{p.indicator_code}/{p.name}"))
    assert len({p.id for p in BUILTIN_PRESETS}) == 18


def test_every_row_fits_the_table_checks_and_the_unique_name_index() -> None:
    for p in BUILTIN_PRESETS:
        assert re.fullmatch(r"[a-z0-9_]{2,32}", p.indicator_code), p.name  # ip_code
        assert 1 <= len(p.name) <= 80 and p.pane_target in _PANE.values()  # ip_name_len, ip_target
        assert len(json.dumps(dict(p.params)).encode()) <= 4096  # ip_params_shape
    keys = [(p.indicator_code, p.name.lower()) for p in BUILTIN_PRESETS]
    assert len(set(keys)) == len(keys)  # ux_ip_name: the built-ins share the NULL-owner space


def test_the_pending_list_names_only_seeded_rows() -> None:
    assert set(PENDING) <= {p.name for p in BUILTIN_PRESETS}


@pytest.mark.parametrize(
    "preset", [p for p in BUILTIN_PRESETS if p.name not in PENDING], ids=lambda p: p.name
)
def test_every_row_the_catalogue_defines_is_complete_canonical_and_on_its_pane(preset: Any) -> None:
    """A built-in a user can copy (`createIndicatorPreset` validates the copy) holds the
    indicator's complete canonical parameters and draws where the descriptor's `pane` says."""
    definition = default_catalogue().get(preset.indicator_code)
    assert definition is not None
    assert validate_params(definition, dict(preset.params)) == dict(preset.params)
    assert _PANE[definition.pane] == preset.pane_target


@pytest.mark.parametrize("name", sorted(PENDING))
def test_every_pending_entry_still_fails_so_none_is_stale(name: str) -> None:
    (preset,) = [p for p in BUILTIN_PRESETS if p.name == name]
    definition = default_catalogue().get(preset.indicator_code)
    if definition is None:
        return  # not registered: still pending
    with pytest.raises(InvalidParamsError):
        validate_params(definition, dict(preset.params))


def test_the_two_vwap_rows_hold_the_same_parameters() -> None:
    """The 1 and 2 sigma bands of the second `vwap` row are outputs of `vwap`, not parameters."""
    rows = [p for p in BUILTIN_PRESETS if p.indicator_code == "vwap"]
    assert [p.name for p in rows] == ["vwap(session)", _SIGMA]
    assert rows[0].params == rows[1].params == {"anchor": "session"}


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any]) -> None:
        self.calls.append((str(stmt), params))


async def test_upsert_builtin_indicator_presets_inserts_each_row_and_never_overwrites() -> None:
    conn = _Conn()
    await seed.upsert_builtin_indicator_presets(conn)  # type: ignore[arg-type]  # fake connection
    assert len(conn.calls) == 18
    sql = {stmt for stmt, _ in conn.calls}
    (statement,) = sql
    assert statement.endswith("ON CONFLICT DO NOTHING")
    assert "VALUES (CAST(:id AS uuid), NULL, :indicator_code, :name, CAST(:params AS jsonb), " in (
        statement
    )
    assert "'{}'::jsonb, :pane_target, true, false)" in statement
    assert [params for _, params in conn.calls] == [
        {
            "id": p.id,
            "indicator_code": p.indicator_code,
            "name": p.name,
            "params": json.dumps(dict(p.params)),
            "pane_target": p.pane_target,
        }
        for p in BUILTIN_PRESETS
    ]
