"""E08-T06: ingestion metric registry consistency + label cardinality guard.

Gherkin "Metric drift fails the build": a child module emitting a metric
name not declared in `ingestion/metrics.py` fails this test, naming it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.ingestion import metrics as reg
from candleviewer.observability.metrics import CollectorRegistry

PKG = Path(reg.__file__).resolve().parents[1]
#: Packages whose metrics the registry owns (ingestion + the adapter layers
#: and bus it declares on their behalf) plus the composition-root wiring.
SCANNED = ("ingestion", "exchange", "bus", "book")
_FACTORIES = {"Counter": "counter", "Gauge": "gauge", "Histogram": "histogram"}


def _declarations(root: Path) -> list[tuple[str, str, tuple[str, ...], str, str]]:
    """(name, kind, labels, help, file) for every literal metric constructor."""
    out: list[tuple[str, str, tuple[str, ...], str, str]] = []
    for sub in SCANNED:
        for f in sorted((root / sub).rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                kind = _FACTORIES.get(node.func.id)
                if kind is None or len(node.args) < 2:
                    continue
                name, help_ = node.args[0], node.args[1]
                if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                    continue  # registry builders pass a variable; checked via SPECS
                labels: tuple[str, ...] = ()
                lab = node.args[2] if len(node.args) > 2 else None
                for kw in node.keywords:
                    if kw.arg == "labelnames":
                        lab = kw.value
                if isinstance(lab, ast.List | ast.Tuple):
                    labels = tuple(str(e.value) for e in lab.elts if isinstance(e, ast.Constant))
                help_text = help_.value if isinstance(help_, ast.Constant) else ""
                out.append((name.value, kind, labels, str(help_text), f.name))
    return out


def check_registry(root: Path = PKG) -> list[str]:
    """Return human-readable violations (empty == consistent)."""
    errs: list[str] = []
    decls = _declarations(root)
    seen: dict[str, str] = {}
    for name, kind, labels, help_text, where in decls:
        if name.startswith("cv_bus_publish"):
            continue  # synthetic-feed test double on a caller-owned registry
        if name in seen:
            errs.append(f"duplicate metric '{name}' in {where} and {seen[name]}")
        seen[name] = where
        spec = reg.SPEC_BY_NAME.get(name)
        if spec is None:
            errs.append(f"undeclared metric '{name}' in {where}")
            continue
        if spec.owner == "ingestion":
            errs.append(f"'{name}' in {where} must be imported from ingestion.metrics")
        elif (kind, labels, help_text) != (spec.kind, spec.labels, spec.help):
            errs.append(f"'{name}' in {where} drifts from its registry declaration")
    built = {n for n, s in reg.SPEC_BY_NAME.items() if s.owner == "ingestion"}
    used = _used_names(root)
    for name in reg.SPEC_BY_NAME:
        if name in built and name not in used:
            errs.append(f"orphaned declaration '{name}' (no module emits it)")
        elif name not in built and name not in seen:
            errs.append(f"orphaned declaration '{name}' (owner never instantiates it)")
    return errs


def _used_names(root: Path) -> set[str]:
    """Ingestion-owned metric objects used anywhere (a registry-internal hot
    helper like `count_event` counts via `name.labels(`)."""
    used: set[str] = set()
    for f in [*sorted(root.rglob("*.py"))]:
        text = f.read_text(encoding="utf-8")
        if f.name == "metrics.py" and f.parent.name == "ingestion":
            used |= {n for n in reg.SPEC_BY_NAME if f"{n}.labels(" in text}
            continue
        used |= {n for n in reg.SPEC_BY_NAME if n in text}
    return used


def _write(tmp_path: Path, rel: str, body: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _tree_with(tmp_path: Path, extra: str) -> Path:
    for sub in SCANNED:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for f in PKG.rglob("*.py"):
        _write(tmp_path, str(f.relative_to(PKG)), f.read_text(encoding="utf-8"))
    _write(tmp_path, "ingestion/rogue.py", extra)
    return tmp_path


def test_registry_repo_is_consistent() -> None:
    assert check_registry() == []


def test_registry_undeclared_child_metric_fails_naming_it(tmp_path: Path) -> None:
    root = _tree_with(tmp_path, 'from x import Counter\nm = Counter("ingest_rogue_total", "h")\n')
    errs = check_registry(root)
    assert errs == ["undeclared metric 'ingest_rogue_total' in rogue.py"]


def test_registry_redeclared_ingestion_metric_fails(tmp_path: Path) -> None:
    root = _tree_with(tmp_path, 'm = Gauge("ingest_lag_seconds", "h", ["stream"])\n')
    assert "'ingest_lag_seconds' in rogue.py must be imported from ingestion.metrics" in (
        check_registry(root)
    )


def test_registry_duplicate_and_drift_fail(tmp_path: Path) -> None:
    root = _tree_with(tmp_path, 'm = Counter("bus_published_total", "other help", ["x"])\n')
    errs = check_registry(root)
    assert any(e.startswith("duplicate metric 'bus_published_total'") for e in errs)
    assert "'bus_published_total' in rogue.py drifts from its registry declaration" in errs


def test_registry_orphaned_declaration_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    ghost = reg.MetricSpec("ingest_ghost_total", "counter", (), "never emitted")
    monkeypatch.setitem(reg.SPEC_BY_NAME, ghost.name, ghost)
    assert "orphaned declaration 'ingest_ghost_total' (no module emits it)" in check_registry()


def test_registry_labels_are_from_allowed_set_and_no_env_or_exchange() -> None:
    for spec in reg.SPECS:
        assert set(spec.labels) <= reg.ALLOWED_LABELS, spec.name
        assert not {"env", "exchange", "uid"} & set(spec.labels), spec.name
    assert len(reg.SPECS) == len(reg.SPEC_BY_NAME)


# --- label cardinality guard -------------------------------------------------


@pytest.fixture(autouse=True)
def _unbound() -> Iterator[None]:
    reg.reset_symbol_universe()
    yield None
    reg.reset_symbol_universe()


def test_symbol_label_bound_universe_folds_unknown_to_other() -> None:
    reg.bind_symbol_universe(["BTCUSDT", "ETHUSDT", "SOLUSDT", "bad symbol"])
    assert reg.symbol_label("BTCUSDT") == "BTCUSDT"
    assert reg.symbol_label("DOGEUSDT") == reg.OTHER_SYMBOL
    assert reg.symbol_label("bad symbol") == reg.OTHER_SYMBOL


def test_symbol_label_unbound_caps_distinct_values() -> None:
    values = {reg.symbol_label(f"SYM{i}USDT") for i in range(reg.MAX_SYMBOLS * 3)}
    assert len(values) == reg.MAX_SYMBOLS + 1  # capped set + the overflow bucket
    assert reg.symbol_label("SYM0USDT") == "SYM0USDT"  # admitted values stay stable


_TAILS = pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])


@_TAILS
def test_symbol_label_unbound_a_symbol_ending_in_a_newline_folds_to_other(tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` made it a label of its own.
    Nothing else is in play: the cap is far off and no universe is bound."""
    assert reg.symbol_label("BTCUSDT") == "BTCUSDT"
    assert reg.symbol_label("ETHUSDT" + tail) == reg.OTHER_SYMBOL


@_TAILS
def test_bind_symbol_universe_drops_a_symbol_ending_in_a_newline(tail: str) -> None:
    """#3555: the universe is built with the same pattern; a bound universe answers only from it."""
    reg.bind_symbol_universe(["BTCUSDT", "ETHUSDT" + tail])
    assert reg.symbol_label("BTCUSDT") == "BTCUSDT"
    assert reg.symbol_label("ETHUSDT" + tail) == reg.OTHER_SYMBOL


@given(st.text(max_size=64))
def test_symbol_label_free_form_input_never_becomes_a_label(raw: str) -> None:
    reg.reset_symbol_universe()
    out = reg.symbol_label(raw)
    assert out == reg.OTHER_SYMBOL or (out == raw and raw.isascii() and raw.isalnum())
    assert out == reg.OTHER_SYMBOL or out.upper() == out


def test_count_event_folds_hostile_symbol_and_caches_children() -> None:
    reg.bind_symbol_universe(["BTCUSDT"])
    before = reg.ingest_events_total.labels(stream="trade", symbol="other")._value.get()
    reg.count_event("trade", "'; DROP TABLE x --")
    reg.count_event("trade", "'; DROP TABLE x --")
    after = reg.ingest_events_total.labels(stream="trade", symbol="other")._value.get()
    assert after - before == 2


def test_export_attaches_env_and_exchange_to_every_declared_series() -> None:
    reg.ingest_events_total.labels(stream="trade", symbol=reg.symbol_label("BTCUSDT")).inc()
    target = CollectorRegistry()
    col = reg.export_ingestion_metrics(target, env="demo", exchange="bybit")
    try:
        names = set()
        for fam in target.collect():
            names.add(fam.name)
            for s in fam.samples:
                assert s.labels["env"] == "demo" and s.labels["exchange"] == "bybit"
        assert "ingest_events" in names  # counter family name drops `_total`
        assert names <= {n.removesuffix("_total") for n in reg.SPEC_BY_NAME}
        value = target.get_sample_value(
            "ingest_events_total",
            {"stream": "trade", "symbol": "BTCUSDT", "env": "demo", "exchange": "bybit"},
        )
        assert value is not None and value >= 1
    finally:
        col.close()
        col.close()  # idempotent
    assert list(target.collect()) == []
