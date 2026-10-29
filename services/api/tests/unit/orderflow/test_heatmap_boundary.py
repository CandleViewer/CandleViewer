"""E21-T02 (#605) technical note: no heatmap value crosses into the OMS, the journal or the audit
in E21 (24 §6.5, C3), so none of those modules may reach `orderflow.heatmap` by any import chain,
direct or indirect, at runtime. Read from the real module graph (import-linter's `grimp`), not a
list; a `TYPE_CHECKING` import (each module's `service.py` names the composition root's
`AppContext` for typing) runs nothing and is left out, as the composition root itself is: it
wires every module and is no module's dependency (C-3.1)."""

from __future__ import annotations

import grimp
import pytest

HEATMAP = ("candleviewer.orderflow.heatmap", "candleviewer.orderflow.heatmap_metrics")


@pytest.fixture(scope="module")
def graph() -> grimp.ImportGraph:
    built = grimp.build_graph("candleviewer", exclude_type_checking_imports=True)
    for root in [m for m in built.modules if m == "candleviewer.app" or m.endswith("_wiring")]:
        built.remove_module(root)
    return built


@pytest.mark.parametrize(
    "importer", ["candleviewer.oms", "candleviewer.journal", "candleviewer.audit"]
)
def test_no_heatmap_value_reaches_the_oms_journal_or_audit(
    graph: grimp.ImportGraph, importer: str
) -> None:
    for imported in HEATMAP:
        chain = graph.find_shortest_chain(importer=importer, imported=imported, as_packages=True)
        assert chain is None, f"{importer} reaches {imported}: {' -> '.join(chain or ())}"


def test_the_graph_sees_a_real_chain(graph: grimp.ImportGraph) -> None:
    """The control: the gateway does import the heatmap, so an empty graph cannot pass above."""
    chain = graph.find_shortest_chain(
        importer="candleviewer.ws", imported=HEATMAP[0], as_packages=True
    )
    assert chain is not None
