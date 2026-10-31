"""#2727 (SR-E14-11, widened 2026-10-20): the `/drawings` refusal counters.

`cv_drawings_payload_rejected_total{reason}` counts a 413 past the body cap (`body_too_large`) and
a 422 past a per-request count bound, points or levels (`bounds`);
`cv_drawings_batch_cap_rejected_total` counts a batch over the operation cap. Each moves once per
refusal, never on a success or another refusal, and never changes the answer. The denied counter
is the generic SR-125 pair (`authz_denied_total`, `authz_denied_by_route_total`), pinned in
`test_drawings_abuse_backend.py`.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from candleviewer.api.drawings import PAYLOAD_REFUSALS
from candleviewer.api.drawings_limiter import DrawingsWriteLimiter
from candleviewer.api.drawings_models import (
    MAX_BATCH_BODY_BYTES,
    MAX_BATCH_OPS,
    MAX_SINGLE_BODY_BYTES,
)
from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.drawings._drawings_api_env import TRENDLINE, Env, wire

PT = TRENDLINE["geometry"]["points"][0]
FIB = TRENDLINE | {"tool": "fib_retracement"}


def _env() -> tuple[Env, MagicMock]:
    metrics = MagicMock()
    env = Env(metrics=metrics)
    env.limiter = DrawingsWriteLimiter(burst=1000, clock=lambda: env.now)  # never the 429 here
    return env, metrics


def _reasons(metrics: MagicMock) -> list[str]:
    calls = metrics.payload_rejected.labels.call_args_list
    assert len(metrics.payload_rejected.labels.return_value.inc.call_args_list) == len(calls)
    return [c.args[0] for c in calls]


def _batch_caps(metrics: MagicMock) -> int:
    return len(metrics.batch_cap_rejected.child.return_value.inc.call_args_list)


def _ops(n: int) -> dict[str, Any]:
    """`n` creates, built past the generated model so `n` may exceed the op cap."""
    return {"operations": [{"op": "create", "drawing": wire(TRENDLINE)}] * n}


def _oversize(env: Env, target: str) -> Any:
    if target == "batch":
        body = b'{"operations":[],"x":"' + b"x" * MAX_BATCH_BODY_BYTES + b'"}'
        return env.c.post("/drawings/batch", content=body)
    body = b'{"label":"' + b"x" * MAX_SINGLE_BODY_BYTES + b'"}'
    if target == "put":
        return env.c.put(f"/drawings/{env.create()['id']}", content=body)
    return env.c.post("/drawings", content=body)


@pytest.mark.parametrize("target", ["create", "put", "batch"])
def test_a_body_over_its_cap_counts_body_too_large_once(target: str) -> None:
    env, metrics = _env()
    r = _oversize(env, target)
    assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    assert _reasons(metrics) == ["body_too_large"] and _batch_caps(metrics) == 0


def _geo(base: dict[str, Any], **geometry: Any) -> dict[str, Any]:
    """A wire body whose geometry breaks a count bound (the generated model would refuse it)."""
    body = wire(base)
    return body | {"geometry": body["geometry"] | geometry}


BOUNDS = {  # case -> (path, body): a point or level count past its per-tool bound
    "points": ("/drawings", _geo(TRENDLINE, points=[PT] * 3)),
    "levels": ("/drawings", _geo(FIB | {"geometry": {"points": [PT, PT], "levels": [0.5]}},
                                 levels=[i / 100 for i in range(25)])),
    "batch_points": ("/drawings/batch", {"operations": [
        {"op": "create", "drawing": _geo(TRENDLINE, points=[PT])}]}),
}  # fmt: skip


@pytest.mark.parametrize("case", list(BOUNDS))
def test_a_count_past_its_bound_is_422_counted_as_bounds_once(case: str) -> None:
    env, metrics = _env()
    path, body = BOUNDS[case]
    r = env.c.post(path, json=body)
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert _reasons(metrics) == ["bounds"] and _batch_caps(metrics) == 0


def test_a_batch_over_the_op_cap_counts_the_batch_cap_once_and_nothing_else() -> None:
    env, metrics = _env()
    r = env.c.post("/drawings/batch", content=json.dumps(_ops(MAX_BATCH_OPS + 1)).encode())
    assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    assert _batch_caps(metrics) == 1 and _reasons(metrics) == []
    assert metrics.batch_cap_rejected.labels.call_args_list == []  # unlabelled: no series grows


def test_successes_and_other_refusals_move_no_refusal_counter() -> None:
    env, metrics = _env()
    mine = env.create()
    assert env.c.post("/drawings/batch", json=_ops(MAX_BATCH_OPS)).status_code == 200
    assert env.c.put(f"/drawings/{mine['id']}", json=wire(TRENDLINE)).status_code == 200
    assert env.c.post("/drawings", json=wire(TRENDLINE) | {"symbol": "btc"}).status_code == 422
    assert env.c.post("/drawings", content=b"[" * 17 + b"]" * 17).status_code == 422  # depth
    assert env.c.delete(f"/drawings/{mine['id']}").status_code == 204
    assert _reasons(metrics) == [] and _batch_caps(metrics) == 0


def _three_refusals(env: Env) -> list[tuple[int, Any]]:
    path, body = BOUNDS["points"]
    over = json.dumps(_ops(MAX_BATCH_OPS + 1)).encode()
    rs = [_oversize(env, "create"), env.c.post(path, json=body),
          env.c.post("/drawings/batch", content=over)]  # fmt: skip
    return [(r.status_code, r.json()) for r in rs]


def test_a_failing_metric_backend_never_changes_the_answer() -> None:
    env, metrics = _env()
    expected = _three_refusals(env)
    metrics.payload_rejected.labels.side_effect = RuntimeError("backend down")
    metrics.batch_cap_rejected.child.side_effect = RuntimeError("backend down")
    assert _three_refusals(env) == expected
    assert [s for s, _ in expected] == [413, 422, 413]


def test_the_counters_are_catalogued_with_closed_bounded_labels() -> None:
    specs = {s.name: s for s in CATALOGUE}
    payload = specs["cv_drawings_payload_rejected_total"]
    assert (payload.kind, payload.labels, payload.max_series) == ("counter", ("reason",), 2)
    assert PAYLOAD_REFUSALS == ("body_too_large", "bounds")
    cap = specs["cv_drawings_batch_cap_rejected_total"]
    assert (cap.kind, cap.labels) == ("counter", ())
