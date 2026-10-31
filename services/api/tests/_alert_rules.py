"""Shared readers for the E04-Q02 alert-rule checks (#257, BQ-07 and BQ-08).

`tests/qa/test_e04_q02_alert_guards.py` and `tests/qa/test_e04_q02_alert_series.py` both parse the
alert rule files under `infra/prometheus/alerts/` and pull the series names out of each
expression. The name scan is the dashboard lint's (`infra/grafana/lint_dashboards.py`,
`metrics_in`), loaded by path and never copied, plus a pre-pass for the PromQL words it leaks
(`offset 5m`, `ignoring(...)`, `group_left(...)`). Pure parsing: no network, no docker.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import yaml

ROOT: Final = Path(__file__).resolve().parents[3]
ALERT_DIR: Final = ROOT / "infra" / "prometheus" / "alerts"
PROMETHEUS_YML: Final = ROOT / "infra" / "prometheus" / "prometheus.yml"
LINT_PATH: Final = ROOT / "infra" / "grafana" / "lint_dashboards.py"

_ABSENT: Final = re.compile(r"\babsent(?:_over_time)?\s*\(")
# A comparison operator outside strings and label matchers (`{a!="b"}`); `==`, `!=`, `>=`, `<=`
# are matched whole so the `=` of a matcher or `=~` is never read as one.
_COMPARISON: Final = re.compile(r"(?<![=!<>~])(?:>=|<=|==|!=|>|<)(?![=~])")
_PROMQL_WORDS: Final = frozenset(
    {"unless", "offset", "bool", "ignoring", "group_left", "group_right", "vector", "time"}
)
# The client library's own process series ride on every scrape of the API; they are never what
# an alert is about, so a rule reading one beside its own series needs no guard for it.
_PROCESS_PREFIX: Final = "process_"
# The alert-drill rule reads a gauge `alert_drill.py` pushes on demand (`infra/alertmanager/`): it
# is a test fixture of the alert path, not a rule about a service, so neither check judges it.
DRILL_RULE: Final = "SyntheticAlert"


@dataclass(frozen=True, slots=True)
class Rule:
    file: str
    alert: str
    expr: str


@cache
def lint_module() -> ModuleType:
    """The dashboard lint, loaded by path (it has no side effects at import)."""
    spec = importlib.util.spec_from_file_location("cv_lint_dashboards", LINT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_rules(alert_dir: Path = ALERT_DIR) -> list[Rule]:
    """Every `alert:` rule in every rule file, in file then source order."""
    out: list[Rule] = []
    for path in sorted(alert_dir.glob("*.yml")):
        doc: Any = yaml.safe_load(path.read_text("utf-8"))
        for group in doc["groups"]:
            for rule in group["rules"]:
                if "alert" in rule:
                    out.append(
                        Rule(path.name, str(rule["alert"]), " ".join(str(rule["expr"]).split()))
                    )
    return out


def base_name(name: str) -> str:
    """A histogram's `_bucket` / `_count` / `_sum` series share the family's name."""
    return str(lint_module()._base(name))


def series_in(expr: str, *, with_process: bool = False) -> frozenset[str]:
    """Series names read by `expr`, PromQL words excluded, and the client library's process
    series too unless `with_process` (the series-existence check wants them)."""
    text = re.sub(r"\boffset\s+\d+[smhdwy]", "", expr)
    text = re.sub(r"\b(?:ignoring|group_left|group_right)\s*\([^)]*\)", "", text)
    names = lint_module().metrics_in(text)
    return frozenset(
        n
        for n in names
        if n not in _PROMQL_WORDS and (with_process or not n.startswith(_PROCESS_PREFIX))
    )


def is_guard(expr: str) -> bool:
    return _ABSENT.search(expr) is not None


def is_threshold(expr: str) -> bool:
    """True for a comparison on series that is not itself an `absent()` guard."""
    if is_guard(expr):
        return False
    bare = re.sub(r'"[^"]*"', '""', expr)
    bare = re.sub(r"\{[^}]*\}", "{}", bare)
    return _COMPARISON.search(bare) is not None and bool(series_in(expr))


def guarded_names(rules: list[Rule]) -> frozenset[str]:
    """Family names some `absent()` / `absent_over_time()` expression in any rule file reads."""
    return frozenset(base_name(s) for r in rules if is_guard(r.expr) for s in series_in(r.expr))


def scrape_jobs() -> frozenset[str]:
    doc: Any = yaml.safe_load(PROMETHEUS_YML.read_text("utf-8"))
    return frozenset(str(job["job_name"]) for job in doc["scrape_configs"])


def recorded_names() -> frozenset[str]:
    return frozenset(lint_module().recorded_rules(ROOT / "infra" / "prometheus"))
