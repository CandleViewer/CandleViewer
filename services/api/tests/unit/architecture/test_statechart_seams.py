"""Two statechart seams the production code must keep (E50-T63, #3898 carries, C-2.21).

- The epoch seam: `Persister.epoch_source` is a test-only seam; production keeps `_os_epoch`, the
  OS CSPRNG, so a life's ids cannot be predicted before its first snapshot is readable (24 §17.6).
  No production call passes `epoch_source` (to `Persister(` or a `replace(`), and nothing assigns
  it.
- Every `Gateway(` names its admission: the synchronous check before any send stays visible in each
  call site (the latch-backed one, or `ALWAYS_ADMIT` where the owner has not adopted the bundle, or
  where it gates on its own latch: the OMS facade, the order path's one gate). When the OMS adopts
  the persistence bundle, it must pass `latch=persistence.latch` into `OrderMachines(...)` or switch
  its site to `LatchAdmission`: a restore latches into the bundle's latch, which the facade's own
  latch would otherwise never see (review round 1, security-4; C-2.21). Every `OrderMachines(`
  call names its `latch=`, so the bundle's cannot be forgotten (CR-S3E1-01).

Both scan the parsed code (`ast`) of every module under `candleviewer/` but the Alembic revisions
(which build neither, and one of which holds an escape `ast` warns about), so a new site is
checked the day it lands."""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer

PACKAGE = Path(candleviewer.__file__).resolve().parent
_MODULES = sorted(
    p for p in PACKAGE.rglob("*.py") if not {"_generated", "migrations"} & set(p.parts)
)


def _calls(name: str) -> list[tuple[str, ast.Call]]:
    found: list[tuple[str, ast.Call]] = []
    for path in _MODULES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if called == name:
                    found.append((str(path.relative_to(PACKAGE)), node))
    return found


def test_production_code_never_passes_or_sets_the_epoch_source() -> None:
    passed, assigned = [], []
    for path in _MODULES:
        rel = str(path.relative_to(PACKAGE))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and any(k.arg == "epoch_source" for k in node.keywords):
                passed.append(f"{rel}:{node.lineno}")
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "epoch_source" for t in node.targets
            ):
                assigned.append(f"{rel}:{node.lineno}")
    assert passed == [] and assigned == []
    assert _calls("Persister"), "the composition root builds the process-wide Persister"


def test_every_gateway_construction_names_its_admission() -> None:
    sites = [(rel, call) for rel, call in _calls("Gateway") if rel != "statechart/gateway.py"]
    unnamed = [
        f"{rel}:{call.lineno}"
        for rel, call in sites
        if not any(k.arg == "admission" for k in call.keywords)
    ]
    assert unnamed == []
    files = {rel for rel, _ in sites}
    assert files == {
        "alerts/lifecycle.py", "app.py", "auth/session_chart.py", "oms/order_machine.py",
        "recorder/policy.py", "replay/sessions_service.py", "rules/lifecycle.py",
    }  # fmt: skip
    assert len(sites) == 9


def test_every_order_machines_construction_names_its_latch() -> None:
    sites = _calls("OrderMachines")
    assert {rel for rel, _ in sites} == {"oms_wiring.py"}  # the one composition site
    assert [rel for rel, call in sites if "latch" not in {k.arg for k in call.keywords}] == []


def test_the_oms_gateway_admits_everything_its_facades_latch_is_the_gate() -> None:
    [(_, call)] = [(rel, c) for rel, c in _calls("Gateway") if rel == "oms/order_machine.py"]
    [admission] = [k.value for k in call.keywords if k.arg == "admission"]
    assert isinstance(admission, ast.Name) and admission.id == "ALWAYS_ADMIT"
