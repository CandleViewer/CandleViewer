"""E37-S01 (#1067): compile builds, from each graph model the editor sends, its vector's rule.

``packages/fixtures/golden/rule-graph/compile_models.json`` holds, for each vector of
``packages/fixtures/golden/rule-ir/hash_vectors.json`` a JS client sends (``js``, with an
``ir_hash``), the model ``toCompileModel`` in ``packages/rule-graph`` builds from the vector's
IR: the ``model`` of ``POST /rules/{ruleId}/compile`` with ``editor: graph``. ``compile_graph``
must compile each to its vector's ``ir_hash``. A vitest test in ``packages/rule-graph`` keeps the
golden current. In-process: no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.rules.compiler import compile_graph
from candleviewer.rules.ir import ir_hash

GOLDEN = Path(__file__).resolve().parents[4] / "packages/fixtures/golden"
MODELS: list[dict[str, Any]] = json.loads(
    (GOLDEN / "rule-graph/compile_models.json").read_text("utf-8")
)["models"]
VECTORS = json.loads((GOLDEN / "rule-ir/hash_vectors.json").read_text("utf-8"))["vectors"]
#: The vectors a JS client sends, by name: their ``ir_hash``.
SENT = {v["name"]: v["ir_hash"] for v in VECTORS if v["js"] and "ir_hash" in v}


def test_the_golden_holds_one_model_per_vector_a_client_sends() -> None:
    assert [entry["name"] for entry in MODELS] == list(SENT)
    assert all(entry["ir_hash"] == SENT[entry["name"]] for entry in MODELS)


def test_the_golden_models_are_the_server_graph_shape() -> None:
    types = {"comparison", "boolean", "temporal", "arithmetic", "operand", "action"}
    for entry in MODELS:
        model = entry["model"]
        assert {node["type"] for node in model["nodes"]} <= types, entry["name"]
        assert all(set(edge) == {"from", "to", "port"} for edge in model["edges"]), entry["name"]
        assert "trigger" in model, entry["name"]


@pytest.mark.parametrize("entry", MODELS, ids=[entry["name"] for entry in MODELS])
def test_compile_graph_answers_the_vector_ir_hash_for_the_client_model(
    entry: dict[str, Any],
) -> None:
    assert ir_hash(compile_graph(entry["model"])) == SENT[entry["name"]]
