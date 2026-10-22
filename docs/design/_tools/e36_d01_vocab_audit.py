"""E36-D01 vocabulary audit: the words a rule is made of, as the shipped vocabulary says them.

Standalone, offline, stdlib only; nothing here is user evidence. It does run repo code: it loads
`catalogue.py` as a module by path and executes it (the module has no project imports), and it
imports the shipped package `candleviewer.rules.vocabulary.metrics` for the kernel-bound
confidences when that package is importable (otherwise they are assumed exact and the output
says so). Everything else is a text read. It prints, with a source label on every row: (1) the
shipped signal ids - the descriptor rows and the kernel-bound rows of `metrics.py`, the golden
list, the estimated set, the counts by scope, input and unit; (2) the shipped actions, operators
and triggers of `catalogue.py`; (3) SCR-081's surfaced metric and action names against the
shipped ids - the names with no shipped id, the nearest candidates, the estimated-mark
mismatches; (4) CMP-140's operator symbols against the 15 operator ids; (5) US-RULE-002's
catalogue terms; (6) the PROPOSED R2 categories derived from `scope` and `inputs`, with the
estimated ids per category; (7) the card-sort deck A size; (8) the word count of the three
candidate summaries read from the memo; (9) the field inventory of `ir/models.py` (text parse)
and which of those fields the memo's section 5.6 field -> phrase map leaves unphrased. A row
reads NOT FOUND when the anchor text moved; the tool never guesses a value and never calls the
API.

Usage: python3 -I docs/design/_tools/e36_d01_vocab_audit.py          (Markdown)
       python3 -I docs/design/_tools/e36_d01_vocab_audit.py --json   (the boards' numbers)
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "services/api/candleviewer/rules"
METRICS = RULES / "vocabulary/metrics.py"
CATALOGUE = RULES / "vocabulary/catalogue.py"
GOLDEN = RULES / "vocabulary/metric_names.golden.txt"
IR_MODELS = RULES / "ir/models.py"
SCREENS = ROOT / "docs/plan/14-screens-catalogue.md"
COMPONENTS = ROOT / "docs/plan/15-component-catalogue.md"
STORIES = ROOT / "docs/plan/11-user-stories.md"
MEMO = ROOT / "docs/design/research/e36-rules-in-words.md"

_INPUT = {"_T": "trades", "_B": "book", "_R": "bars"}
_CONF = {"_E": "exact", "_S": "estimated"}
_ROW = re.compile(
    r'^\s*\("([a-z0-9_]+)", "[^"]*", "([^"]*)", (_T|_B|_R|"[a-z]+"), "[^"]*", \d+, '
    r'(_E|_S), "([a-z]+)",',
    re.MULTILINE,
)
_KERNEL = re.compile(
    r'^\s*\("([a-z0-9_]+)", "[a-z0-9_]+", "[a-z0-9_]+", "[^"]*", (_TAPE|_NO_TAPE),',
    re.MULTILINE,
)
# SCR-081's five names with no shipped id and the ids they stand for (the memo's C2).
NEAREST: dict[str, list[str]] = {
    "unrealized_r_multiple": ["unrealised_r_multiple"],
    "unrealized_pnl_pct": ["unrealised_pnl_pct"],
    "realized_pnl_today": ["realised_pnl_today"],
    "time_in_trade": ["time_in_trade_ms"],
    "orderbook_imbalance": ["dom_imbalance_ratio", "book_pressure"],
}
DERIVATIVE_INPUTS = {"oi", "funding", "liquidations"}
# The IR classes the memo's section 5.6 phrases field by field (ir/models.py).
IR_CLASSES = ("Rule", "RuleScope", "Trigger", "Action", "RuleLimits")
_CLASS = re.compile(r"^class (\w+)\(BaseModel\):\n((?:    .*\n|\n)*)", re.MULTILINE)
_FIELD = re.compile(r"^    ([a-z][a-z0-9_]*): ", re.MULTILINE)
CATEGORIES = ("price", "orderflow", "book", "derivatives", "position", "account", "replay")


class Signal(TypedDict):
    name: str
    unit: str
    inputs: list[str]
    confidence: str
    scope: str
    kernel: bool


class Catalogue(TypedDict):
    actions: int
    action_ids: list[str]
    operators: list[str]
    triggers: int
    targets: dict[str, str]
    loosens_risk: list[str]
    places_orders: list[str]
    arm_live_permission: str


def signals() -> tuple[list[Signal], str]:
    """The shipped signals from the module text; kernel-bound confidence by import if possible."""
    text = METRICS.read_text(encoding="utf-8")
    out: list[Signal] = []
    for name, unit, inp, conf, scope in _ROW.findall(text):
        out.append(
            {
                "name": name,
                "unit": "enum" if unit.startswith("enum:") else unit,
                "inputs": [_INPUT.get(inp, inp.strip('"'))],
                "confidence": _CONF[conf],
                "scope": scope,
                "kernel": False,
            }
        )
    source = "assumed exact (import unavailable)"
    by_import: dict[str, tuple[str, str]] = {}
    try:  # read-only; the module needs the project's packages, so the text parse is the default
        from candleviewer.rules.vocabulary import metrics as shipped

        by_import = {d.name: (d.confidence, d.unit) for d in shipped.DEFAULT_DESCRIPTORS}
        source = "candleviewer.rules.vocabulary.metrics (imported)"
    except ImportError:
        pass
    for name, tape in _KERNEL.findall(text):
        conf, unit = by_import.get(name, ("exact", "?"))
        inputs = ["bars", "trades"] if tape == "_TAPE" else ["bars"]
        out.append(
            {
                "name": name,
                "unit": unit,
                "inputs": inputs,
                "confidence": conf,
                "scope": "symbol",
                "kernel": True,
            }
        )
    return out, source


def category(s: Signal) -> str:
    """R2 (PROPOSED): the category from `scope` and `inputs`; estimated is a tag, not a category."""
    if s["scope"] == "position":
        return "position"
    if s["scope"] == "account":
        return "account"
    if s["scope"] == "global":
        return "replay"
    inputs = set(s["inputs"])
    if inputs & DERIVATIVE_INPUTS:
        return "derivatives"
    if "book" in inputs:
        return "book"
    if "trades" in inputs:
        return "orderflow"
    return "price"


def catalogue() -> Catalogue | None:
    """Load `catalogue.py` by path (it imports only the stdlib); None when it cannot be loaded."""
    spec = importlib.util.spec_from_file_location("e36_d01_catalogue", CATALOGUE)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass(slots=True) looks the module up by name
    spec.loader.exec_module(mod)
    actions = list(mod.ACTIONS)
    return {
        "actions": len(actions),
        "action_ids": [str(a.type) for a in actions],
        "operators": sorted(str(op) for op in mod.OPERATORS),
        "triggers": len(mod.TRIGGERS),
        "targets": {str(k): str(v) for k, v in mod.TARGET_SEMANTICS.items()},
        "loosens_risk": [str(a.type) for a in actions if a.loosens_risk],
        "places_orders": [str(a.type) for a in actions if a.places_orders],
        "arm_live_permission": str(mod.ARM_LIVE_PERMISSION),
    }


def anchored(path: Path, start: str, end: str, line_start: str) -> str | None:
    text = path.read_text(encoding="utf-8")
    i = text.find(start)
    j = text.find(end, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        return None
    for line in text[i:j].splitlines():
        if line.startswith(line_start):
            return line[len(line_start) :].strip().rstrip(".")
    return None


def scr081_lists() -> tuple[list[str], list[str]]:
    m = anchored(SCREENS, "### SCR-081", "### SCR-082", "- **Metric vocabulary surfaced:**")
    a = anchored(SCREENS, "### SCR-081", "### SCR-082", "- **Action vocabulary surfaced:**")
    metrics = [] if m is None else [x.strip() for x in m.split(",")]
    actions = [] if a is None else [x.strip() for x in a.split(",")]
    return metrics, actions


def cmp140_operators() -> list[str]:
    text = COMPONENTS.read_text(encoding="utf-8")
    i = text.find("### CMP-140")
    j = text.find("### CMP-141", i + 1)
    if i < 0 or j < 0:
        return []
    m = re.search(r"operator: ((?:\"[^\"]+\"\|?)+)", text[i:j])
    return [] if m is None else re.findall(r'"([^"]+)"', m.group(1))


def us_rule_002_terms() -> list[str]:
    line = anchored(STORIES, "#### US-RULE-002", "#### US-RULE-003", "  Then ")
    if line is None or " are all selectable" not in line:
        return []
    return [t.strip() for t in line.split(" are all selectable")[0].split(", ")]


def summaries() -> dict[str, dict[str, int | str]]:
    out: dict[str, dict[str, int | str]] = {}
    if MEMO.exists():
        rows = re.findall(
            r"^\| (S[123]) +\| (.+?) +\|", MEMO.read_text(encoding="utf-8"), re.MULTILINE
        )
        for sid, text in rows:
            out[sid] = {"words": len(text.split()), "chars": len(text)}
    return out or {"S1": {"status": "NOT FOUND"}}


def ir_fields() -> dict[str, list[str]]:
    """Field names per pydantic model in `ir/models.py`, from the text (no project import)."""
    text = IR_MODELS.read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    for name, body in _CLASS.findall(text):
        fields = [f for f in _FIELD.findall(body) if f != "model_config"]
        if fields:
            out[name] = fields
    return out


def field_map_coverage(fields: dict[str, list[str]]) -> dict[str, object]:
    """Which fields of the five classes the memo's section 5.6 table leaves unphrased."""
    if not MEMO.exists():
        return {"status": "NOT FOUND"}
    memo = MEMO.read_text(encoding="utf-8")
    i = memo.find("### 5.6")
    j = memo.find("## 6. ", i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        return {"status": "NOT FOUND"}
    table = memo[i:j]
    unphrased = {
        cls: [f for f in fields.get(cls, []) if re.search(rf"[`.]{re.escape(f)}\b", table) is None]
        for cls in IR_CLASSES
    }
    return {
        "fields_per_class": {cls: len(fields.get(cls, [])) for cls in IR_CLASSES},
        "unphrased": {cls: names for cls, names in unphrased.items() if names},
        "table_rows": sum(1 for line in table.splitlines() if line.startswith("| `")),
    }


def plain(name: str) -> str:
    """`atr(n)` -> `atr`; `iceberg_present_at_level _(estimated)_` -> `iceberg_present_at_level`."""
    return re.sub(r"\(n\)$", "", name.split(" ")[0])


def main(argv: list[str]) -> int:
    sigs, kernel_source = signals()
    golden = GOLDEN.read_text(encoding="utf-8").split()
    ids = {s["name"] for s in sigs}
    conf = {s["name"]: s["confidence"] for s in sigs}
    estimated = [s["name"] for s in sigs if s["confidence"] == "estimated"]
    cats = Counter(category(s) for s in sigs)
    est_by_cat = Counter(category(s) for s in sigs if s["confidence"] == "estimated")
    surfaced, surfaced_actions = scr081_lists()
    plan_names = [plain(n) for n in surfaced]
    plan_est = {plain(n) for n in surfaced if "(estimated)" in n}
    missing = [n for n in plan_names if n not in ids]
    nearest = {c for n in missing for c in NEAREST.get(n, [])}
    resolved = sorted({n for n in plan_names if n in ids} | nearest)
    deck_a = sorted(set(resolved) | set(estimated))
    cat = catalogue()
    ops = [] if cat is None else cat["operators"]
    action_ids = [] if cat is None else cat["action_ids"]
    cmp_ops = cmp140_operators()
    fields = ir_fields()
    cat_report: dict[str, object] = {"error": "NOT FOUND"}
    if cat is not None:
        cat_report = {k: v for k, v in cat.items() if k != "action_ids"}
        cat_report["operators"] = len(cat["operators"])
    report: dict[str, dict[str, object]] = {
        "signals": {
            "total": len(sigs),
            "descriptor_rows": sum(not s["kernel"] for s in sigs),
            "kernel_bound": sum(s["kernel"] for s in sigs),
            "golden": len(golden),
            "golden_matches": sorted(ids) == sorted(golden),
            "estimated": estimated,
            "by_scope": dict(Counter(s["scope"] for s in sigs).most_common()),
            "by_input": dict(Counter(i for s in sigs for i in s["inputs"]).most_common()),
            "by_unit": dict(Counter(s["unit"] for s in sigs).most_common()),
            "kernel_confidence_source": kernel_source,
        },
        "catalogue": cat_report,
        "scr081": {
            "surfaced_metrics": len(surfaced) or "NOT FOUND",
            "surfaced_actions": len(surfaced_actions) or "NOT FOUND",
            "actions_not_surfaced": sorted(set(action_ids) - set(surfaced_actions)),
            "names_without_shipped_id": {n: NEAREST.get(n, []) for n in missing},
            "marked_estimated_but_exact": sorted(n for n in plan_est if conf.get(n) == "exact"),
            "estimated_but_unmarked": sorted(
                n for n in plan_names if conf.get(n) == "estimated" and n not in plan_est
            ),
        },
        "cmp140": {
            "symbols": len(cmp_ops) or "NOT FOUND",
            "operator_ids": len(ops),
            "ids_without_symbol": len(ops) - len(cmp_ops) if cmp_ops else "NOT FOUND",
        },
        "us_rule_002_terms": {"count": len(us_rule_002_terms()) or "NOT FOUND"},
        "categories_r2": {
            c: {"ids": cats[c], "estimated": est_by_cat.get(c, 0)} for c in CATEGORIES
        },
        "deck_a": {
            "cards": len(deck_a),
            "resolved_scr081": len(resolved),
            "estimated_added": len(set(estimated) - set(resolved)),
        },
        "summaries": dict(summaries()),
        "ir_fields": {cls: fields.get(cls, []) for cls in IR_CLASSES},
        "field_map_section_5_6": field_map_coverage(fields),
    }
    if "--json" in argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print("# E36-D01 vocabulary audit (every row from the repo's own text; nothing observed)\n")
    for section, rows in report.items():
        print(f"## {section}\n")
        for k, v in rows.items():
            print(f"- `{k}`: {json.dumps(v, ensure_ascii=False)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
