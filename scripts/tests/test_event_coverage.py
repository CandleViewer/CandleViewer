"""Tests for tools/statechart/event_coverage.py (E50-T05, MUST-10)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.statechart.event_coverage import (
    check,
    load_descriptors,
    main,
    scan_source,
)

CHART = {
    "id": "order",
    "on": {"KILL": {}},
    "states": {"a": {"on": {"ORDER_FILLED": {}}}},
}


def _machines(tmp_path: Path) -> Path:
    d = tmp_path / "machines"
    d.mkdir()
    (d / "B01.order.machine.json").write_text(json.dumps(CHART), encoding="utf-8")
    return d


def test_descriptors_collect_nested_events(tmp_path: Path) -> None:
    assert load_descriptors(_machines(tmp_path)) == {"order": {"KILL", "ORDER_FILLED"}}


def test_unknown_event_fails_naming_the_site(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    src = "async def f(gw):\n    await gw.send('order:1', 'ORDER_FILED')\n"
    findings = check(scan_source(src, "svc/x.py"), desc)
    assert len(findings) == 1
    assert "svc/x.py:2" in findings[0] and "ORDER_FILED" in findings[0]


def test_known_event_forms_pass(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    src = (
        "gw.send('order', 'ORDER_FILLED')\n"
        "gw.send('order:2', {'type': 'KILL'})\n"
        "gw.send_threadsafe('order', Event('KILL'))\n"
    )
    assert check(scan_source(src, "x.py"), desc) == []


def test_unknown_machine_and_dynamic_event(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    src = "gw.send('ghost', 'KILL')\ngw.send('order', name)\n"
    findings = check(scan_source(src, "x.py"), desc)
    assert len(findings) == 1 and "unknown machine 'ghost'" in findings[0]


def test_main_exit_codes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    m = _machines(tmp_path)
    scan = tmp_path / "src"
    scan.mkdir()
    (scan / "ok.py").write_text("gw.send('order', 'KILL')\n", encoding="utf-8")
    assert main(["--machines", str(m), "--scan", str(scan)]) == 0
    (scan / "bad.py").write_text("gw.send('order', 'ORDER_FILED')\n", encoding="utf-8")
    assert main(["--machines", str(m), "--scan", str(scan)]) == 1
    assert "bad.py:1" in capsys.readouterr().out
    assert main(["--machines", str(tmp_path / "nope"), "--scan", str(scan)]) == 2


WRAP = """
class C:
    def build(self, sid, interp):
        self._gw.register(sid, interp, kind="order")

    async def _send(self, sid, event, **p):
        await self._gw.send(sid, {"type": event, **p})

    async def record(self, rec, now, event, **p):
        await self._send(str(rec.id), event, **p)

    async def go(self, rec, now):
        await self.record(rec, now, "%s")
"""


def test_wrapper_call_sites_checked_against_registered_machine(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    desc["other"] = {"ONLY_OTHER"}
    assert check(scan_source(WRAP % "KILL", "w.py"), desc) == []
    bad = check(scan_source(WRAP % "ONLY_OTHER", "w.py"), desc)
    assert len(bad) == 1 and "not declared by machine 'order'" in bad[0]


def test_registered_kind_beats_union_for_nonliteral_key(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    desc["other"] = {"ONLY_OTHER"}
    src = "gw.register(sid, i, kind='order')\ngw.send(sid, 'ONLY_OTHER')\n"
    assert len(check(scan_source(src, "x.py"), desc)) == 1


def _package(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "pkg"
    for rel, src in {"__init__.py": "", **files}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src, encoding="utf-8")
    return root


SESSION_WRAPPER = """
async def _record(gw, sid, event):
    await gw.send("order", {"type": event, "sid": sid})
"""


def test_wrapper_resolved_by_module_not_bare_name(tmp_path: Path) -> None:
    """#4730: an unrelated module's own `_record` is not the gateway wrapper of the same name."""
    from tools.statechart.event_coverage import scan_tree

    root = _package(
        tmp_path,
        {
            "auth/__init__.py": "",
            "auth/chart.py": SESSION_WRAPPER,
            "bars/__init__.py": "",
            # Its own `_record`: same bare name, same arity, a literal at the event index.
            "bars/emit.py": "def _record(a, b, c):\n    pass\n\n_record(1, 2, 'BAR_CLOSED')\n",
            # A method call on an object of a module that does not import the wrapper's module.
            "bars/other.py": "async def f(x):\n    await x._record(1, 2, 'NOT_AN_EVENT')\n",
            "a.py": "from pkg.auth.chart import _record\n\nasync def f(gw):\n"
            "    await _record(gw, '1', 'KILL')\n",
            "b.py": "from .auth import chart\n\nasync def f(gw):\n"
            "    await chart._record(gw, '1', 'ORDER_FILLED')\n",
            "c.py": "import pkg.auth.chart as ch\n\nasync def f(gw):\n"
            "    await ch._record(gw, '1', 'KILL')\n",
        },
    )
    sites = scan_tree(root)
    assert not [s for s in sites if "bars" in s.path]
    found = {(Path(s.path).name, s.key, s.event) for s in sites}
    assert found == {
        ("a.py", "order", "KILL"),
        ("b.py", "order", "ORDER_FILLED"),
        ("c.py", "order", "KILL"),
    }
    assert check(sites, load_descriptors(_machines(tmp_path))) == []


SESSION_METHOD = """
class SessionChart:
    async def record(self, sid, at, event):
        await self._gw.send("order", {"type": event, "sid": sid})


class StepUp:
    async def _record(self, sid, at, event):
        await self._chart.record(sid, at, event)
"""


def test_wrapper_method_needs_self_class_or_reviewed_port(tmp_path: Path) -> None:
    """#4730: a wrapper *method* (`SessionChart.record`, `StepUp._record`) is reached only
    through `self` on its class or a subclass, or a reviewed injected-port entry; never by
    a same-named method on an unrelated object, even in a module importing the wrapper's."""
    from tools.statechart.event_coverage import scan_tree

    root = _package(
        tmp_path,
        {
            "auth/__init__.py": "",
            "auth/chart.py": SESSION_METHOD,
            "auth/sub.py": "from .chart import SessionChart\n\nclass Sub(SessionChart):\n"
            "    async def f(self):\n        await self.record('1', 0, 'KILL')\n",
            "consumer.py": "async def f(target):\n    await target.push('1', 'KILL')\n",
            "machines.py": "class M:\n    async def push(self, k, event):\n"
            "        await self._gw.send('order:' + k, {'type': event})\n",
            # Unrelated receivers, same method names and arity, literals at the event index.
            "bars/__init__.py": "",
            "bars/emit.py": "async def f(sink, metrics):\n"
            "    await sink._record(1, 2, 'BAR_CLOSED')\n"
            "    metrics.record(1, 2, 'LIT')\n",
            "bars/near.py": "from pkg.auth.chart import SessionChart\n\n"
            "async def f(o):\n    await o._record(1, 2, 'FALSE1')\n\n"
            "class Own:\n    async def _record(self, a, b, c):\n        pass\n\n"
            "    async def g(self):\n        await self._record(1, 2, 'FALSE2')\n"
            "        await self.record(1, 2, 'FALSE3')\n",
            "other.py": "async def f(target):\n    await target.push('1', 'NOPE')\n",
        },
    )
    sites = scan_tree(
        root,
        ports={
            ("pkg.consumer", "target", "push"): "pkg.machines.M.push",
            (
                "pkg.auth.chart",
                "self._chart",
                "record",
            ): "pkg.auth.chart.SessionChart.record",
        },
    )
    assert not [s for s in sites if "bars" in s.path or "other.py" in s.path]
    found = {(Path(s.path).name, s.event) for s in sites}
    assert found == {("sub.py", "KILL"), ("consumer.py", "KILL")}


def test_module_function_shares_no_key_with_a_same_named_method(tmp_path: Path) -> None:
    from tools.statechart.event_coverage import scan_tree

    root = _package(
        tmp_path,
        {
            # A module-level wrapper `_record` beside an unrelated method `_record`.
            "chart.py": SESSION_WRAPPER
            + "\nclass C:\n    def _record(self, a, b, c):\n"
            "        pass\n\n    def g(self):\n        self._record(1, 2, 'NOT_AN_EVENT')\n",
        },
    )
    assert scan_tree(root, ports={}) == []


def test_stale_port_entry_fails_the_scan(tmp_path: Path) -> None:
    from tools.statechart.event_coverage import scan_tree

    root = _package(
        tmp_path, {"consumer.py": "async def f(t):\n    await t.push('1', 'KILL')\n"}
    )
    with pytest.raises(ValueError, match="name no wrapper"):
        scan_tree(root, ports={("pkg.consumer", "t", "push"): "pkg.machines.M.push"})


def test_port_entry_matching_no_call_fails_the_scan(tmp_path: Path) -> None:
    from tools.statechart.event_coverage import StalePortError, scan_tree

    # The receiver was renamed (`self._target.push` -> `self._sink.push`): the wrapper still
    # exists, but the reviewed call no longer occurs, so the entry would match nothing.
    root = _package(
        tmp_path,
        {
            "chart.py": SESSION_WRAPPER,
            "consumer.py": "class D:\n    async def f(self):\n"
            "        await self._sink.record(1, 2, 'KILL')\n",
        },
    )
    entry = ("pkg.consumer", "self._target", "record")
    with pytest.raises(StalePortError, match=r"match no call: .*self\._target\.record"):
        scan_tree(root, ports={entry: "pkg.chart._record"})


def test_main_exits_2_on_a_stale_port_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    from tools.statechart import event_coverage

    m = _machines(tmp_path)
    scan = tmp_path / "src"
    scan.mkdir()
    (scan / "ok.py").write_text("gw.send('order', 'KILL')\n", encoding="utf-8")
    real = event_coverage.scan_tree
    stale = {("src.ok", "t", "push"): "src.ok.M.push"}
    monkeypatch.setattr(event_coverage, "scan_tree", lambda root: real(root, ports=stale))
    assert main(["--machines", str(m), "--scan", str(scan)]) == 2
    assert "src.ok: t.push -> src.ok.M.push" in capsys.readouterr().err


def test_real_repo_wiring_is_resolved_and_clean() -> None:
    from tools.statechart.event_coverage import (
        DEFAULT_MACHINES,
        DEFAULT_SCAN,
        scan_tree,
    )

    # Also pins PORT_WRAPPERS: an entry whose wrapper or call is gone raises StalePortError here.
    # One scan of the real tree, judged as `main([])` judges it (exit 0 means no finding): a second
    # scan through main() doubled the slowest governance test (#3789).
    sites = scan_tree(DEFAULT_SCAN)
    session = {s.event for s in sites if s.key == "session"}
    assert {"MFA_OK", "REVOKE", "REQUEST"} <= session
    assert check(sites, load_descriptors(DEFAULT_MACHINES)) == []
