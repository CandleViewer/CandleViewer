"""The scanner's criteria and the rules of a `ScannerFilter` (E08-T09, #4708; 22
`ScannerFilter`, `ScannerCriterion`, `listScannerCriteria`). Pure: no I/O, no routing. The
presets (PR 2a) check a stored filter with `check_filter`, and the scan (PR 2b) its `filters`
query with the same function, so the two cannot drift.

The eight criteria, their order, labels (W-1), estimates and coverage are E08-D08 section 3.1's;
the unit is the one the matching `ScannerRow` field carries (a fraction, not a percentage).
Regime's classes are the vocabulary the scan reads, `orderflow_metrics.regime` (21 section 4.11):
E25-D01 F20 records six regime vocabularies across the plan and E08-D08 fixes none, leaving the
list to this descriptor (D08-G9). They stay `available: false` until E10 writes the column.

`available` (22 `ScannerCriterion.available`, `ScannerSortKeyStatus`) is `false` while no server
source feeds a criterion or a ranking key: tape speed and regime until E10 writes
`orderflow_metrics`, OI change until the recorded open-interest baseline is read, and the keys
`cvd`, `tape_speed` and `liquidation_intensity`, read from `orderflow_metrics` too. A criterion's
key carries that criterion's `available`. `check_filter` refuses a well-formed unavailable
criterion (`criterion_unavailable`, after its shape rules, so a malformed one still names its
defect) and `sort_defect` an unavailable key (field `sort`); `split_stored` serves a stored one
in `unavailable_criteria`, never dropping it from the row.

`check_filter` reports every criterion's first defect (at most `MAX_ERRORS`), each `field`
rooted at the caller's name (`filter.<criterion id>`, else `filter`), and a message that names the
criterion's label and the rule, never a submitted value or an unknown key (22 `runScanner`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal

CriterionKind = Literal["range", "class_set"]
CriterionUnit = Literal["fraction", "usdt", "bps", "zscore", "class"]

#: 21 section 4.11 `orderflow_metrics.regime`, in that order.
REGIME_CLASSES: Final = ("trend_up", "trend_down", "range", "volatile", "calm")
#: 22 `ScannerClassSet.classes.maxItems`.
MAX_CLASSES: Final = 16
#: At most this many field errors in one 422 (the drawings and workspaces bound).
MAX_ERRORS: Final = 20
#: 22 `ScannerSortKey`, in its order. A preset stores one; `runScanner` ranks by one.
SORT_KEYS: Final = (
    "volume_24h", "price_change_pct_24h", "cvd", "tape_speed", "open_interest",
    "liquidation_intensity", "turnover_24h", "funding_rate", "spread_bps", "range_pct_24h",
    "tape_speed_zscore", "oi_change_pct_24h",
)  # fmt: skip
#: 22 `Decimal`.
_DECIMAL: Final = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_RANGE_KEYS: Final = frozenset({"min", "max"})


@dataclass(frozen=True, slots=True)
class ScannerCriterionDef:
    """One `ScannerCriterion`."""

    id: str
    label: str
    kind: CriterionKind
    unit: CriterionUnit
    estimated: bool
    needs_recording: bool
    classes: tuple[str, ...] = ()
    available: bool = True

    @property
    def sortable(self) -> bool:
        return self.id in SORT_KEYS


def _range(cid: str, label: str, unit: CriterionUnit, *, est: bool = False,
           recorded: bool = False, available: bool = True) -> ScannerCriterionDef:  # fmt: skip
    return ScannerCriterionDef(cid, label, "range", unit, est, recorded, available=available)


#: E08-D08 section 3.1, in its order (22 `ScannerFilter.properties` too).
CRITERIA: Final = (
    _range("price_change_pct_24h", "24 h change %", "fraction"),
    _range("turnover_24h", "Turnover 24 h (USDT)", "usdt"),
    _range("funding_rate", "Funding %", "fraction"),
    _range("oi_change_pct_24h", "OI Δ 24 h %", "fraction", recorded=True, available=False),
    _range("spread_bps", "Spread (bps)", "bps"),
    _range("tape_speed_zscore", "Tape speed z-score", "zscore", est=True, recorded=True,
           available=False),
    _range("range_pct_24h", "24 h range %", "fraction"),
    ScannerCriterionDef("regime", "Regime", "class_set", "class", True, True, REGIME_CLASSES,
                        available=False),
)  # fmt: skip
CRITERIA_BY_ID: Final = {c.id: c for c in CRITERIA}
#: The ranking keys read from `orderflow_metrics` that are not criteria: no source until E10.
_UNFED_SORT_KEYS: Final = frozenset({"cvd", "tape_speed", "liquidation_intensity"})
#: 22 `ScannerSortKeyStatus.available` per `SORT_KEYS` entry, a criterion's key as its criterion.
SORT_KEY_AVAILABLE: Final = {
    k: CRITERIA_BY_ID[k].available if k in CRITERIA_BY_ID else k not in _UNFED_SORT_KEYS
    for k in SORT_KEYS
}


class FilterInvalidError(Exception):
    """422 `validation_failed`; `errors` are the contract's `{field, rule, message}` items."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(f"{len(errors)} invalid filter field(s)")
        self.errors = errors


def describe(c: ScannerCriterionDef) -> dict[str, Any]:
    """`c` as 22's `ScannerCriterion` (`classes` for a class set only)."""
    item: dict[str, Any] = {
        "id": c.id, "label": c.label, "kind": c.kind, "unit": c.unit, "estimated": c.estimated,
        "needs_recording": c.needs_recording, "sortable": c.sortable, "available": c.available,
    }  # fmt: skip
    return item | ({"classes": list(c.classes)} if c.kind == "class_set" else {})


def sort_keys() -> list[dict[str, Any]]:
    """22 `listScannerCriteria`'s `sort_keys`: each `ScannerSortKeyStatus`, in `SORT_KEYS` order."""
    return [{"id": k, "available": SORT_KEY_AVAILABLE[k]} for k in SORT_KEYS]


def sort_defect(key: str, *, field: str = "sort") -> dict[str, str] | None:
    """The `criterion_unavailable` error of a known ranking key no source feeds yet, else None
    (an unknown key is the caller's type check: `literal_error` on a preset)."""
    if SORT_KEY_AVAILABLE.get(key, True):
        return None
    message = "That ranking is not available yet."
    return {"field": field, "rule": "criterion_unavailable", "message": message}


def _range_defect(c: ScannerCriterionDef, value: object) -> tuple[str, str] | None:
    """(rule, message) of the first defect of a `ScannerRange`, else None."""
    if not isinstance(value, dict):
        return "dict_type", f"{c.label} must be an object with a minimum, a maximum or both."
    if not set(value) <= _RANGE_KEYS:
        return "extra_forbidden", f"{c.label} takes only a minimum and a maximum."
    if not value:
        return "range_empty", f"{c.label} needs a minimum, a maximum or both."
    bounds = [value[k] for k in ("min", "max") if k in value]
    if not all(isinstance(b, str) and _DECIMAL.fullmatch(b) for b in bounds):
        return "invalid_decimal", f"{c.label} bounds must be decimal strings."
    if len(bounds) == 2 and Decimal(bounds[0]) >= Decimal(bounds[1]):
        return "range_inverted", f"{c.label}: the minimum must be below the maximum."
    return None


def _class_set_defect(c: ScannerCriterionDef, value: object) -> tuple[str, str] | None:
    """(rule, message) of the first defect of a `ScannerClassSet`, else None."""
    if not isinstance(value, dict):
        return "dict_type", f"{c.label} must be an object with its classes."
    if not set(value) <= {"classes"}:
        return "extra_forbidden", f"{c.label} takes only its classes."
    classes = value.get("classes")
    if classes is None:
        return "missing", f"{c.label} needs its classes."
    if not isinstance(classes, list):
        return "list_type", f"{c.label} classes must be a list."
    if not classes:
        return "classes_empty", f"Choose at least one {c.label} class."
    if len(classes) > MAX_CLASSES:
        return "too_long", f"{c.label} takes at most {MAX_CLASSES} classes."
    if not all(isinstance(k, str) and k in c.classes for k in classes):
        return "unknown_regime_class", f"{c.label} classes must be ones the criteria list gives."
    if len(set(classes)) != len(classes):
        return "non_unique_items", f"{c.label} classes must be unique."
    return None


def check_filter(raw: Mapping[str, object], *, root: str) -> dict[str, Any]:
    """`raw` (a JSON object) as a valid `ScannerFilter`, returned as written; else
    `FilterInvalidError` with each criterion's first defect, rooted at `root`."""
    errors: list[dict[str, str]] = []
    unknown = False
    for key, value in raw.items():
        c = CRITERIA_BY_ID.get(key)
        if c is None:
            unknown = True
            continue
        check = _range_defect if c.kind == "range" else _class_set_defect
        defect = check(c, value)
        if defect is None and not c.available:
            defect = "criterion_unavailable", f"{c.label} is not available yet."
        if defect is not None:
            errors.append({"field": f"{root}.{c.id}", "rule": defect[0], "message": defect[1]})
    if unknown:  # once, at the filter: the key is the client's and is never echoed
        message = "The filter names a criterion the scanner does not know."
        errors.append({"field": root, "rule": "unknown_criterion", "message": message})
    if errors:
        raise FilterInvalidError(errors[:MAX_ERRORS])
    return dict(raw)


def _in_force(cid: str) -> bool:
    c = CRITERIA_BY_ID.get(cid)
    return c is not None and c.available


def split_stored(stored: Mapping[str, Any], *, sort: str) -> tuple[dict[str, Any], list[str]]:
    """A stored preset's filter as `ScannerPreset` serves it: the criteria in force (known and
    available), and, sorted and once each, the ids it names that the server no longer knows or
    lists unavailable, with the stored `sort` when no source feeds it (`unavailable_criteria`,
    never silently dropped; the row keeps both, and `sort` is served as stored)."""
    known = {k: v for k, v in stored.items() if _in_force(k)}
    flagged = {k for k in stored if not _in_force(k)}
    if not SORT_KEY_AVAILABLE.get(sort, True):
        flagged.add(sort)
    return known, sorted(flagged)


__all__ = [
    "CRITERIA", "CRITERIA_BY_ID", "MAX_CLASSES", "MAX_ERRORS", "REGIME_CLASSES", "SORT_KEYS",
    "SORT_KEY_AVAILABLE", "FilterInvalidError", "ScannerCriterionDef", "check_filter", "describe",
    "sort_defect", "sort_keys", "split_stored",
]  # fmt: skip
