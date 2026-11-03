"""E21-X02 (#652; 22 `getHeatmap` "Bounds"): the backfill's caps are the contract's rows. Each
constant that enforces a bound is the number 22 states for it, so a change of either side is a
reviewed diff of both (C-6.1). The operation is read as text, as its description states it."""

from __future__ import annotations

import re
from pathlib import Path

from candleviewer.api.market_heatmap import MAX_PER_USER, MAX_WINDOW_DAYS, MAX_WINDOW_US
from candleviewer.orderflow.heatmap_history import MAX_CONCURRENT_FOLDS

_OPENAPI = Path(__file__).resolve().parents[5] / "docs" / "plan" / "22-api-openapi.yaml"


def _get_heatmap() -> str:
    """`getHeatmap`'s operation, its whitespace folded: from its `operationId` to the next one."""
    text = _OPENAPI.read_text(encoding="utf-8")
    start = text.index("operationId: getHeatmap")
    end = text.index("operationId:", start + len("operationId: getHeatmap"))
    return " ".join(text[start:end].split())


def test_the_window_bounds_are_the_contract_rows() -> None:
    op = _get_heatmap()
    span = re.search(r"`to - from` is at most (\d+) days", op)
    users = re.search(
        r"At most (\d+) backfills per user run at once, counted for the acting user", op
    )
    folds = re.search(r"at most (\d+) at once for the whole server and never on the event loop", op)
    assert span and users and folds, op[:400]
    assert int(span[1]) == MAX_WINDOW_DAYS and MAX_WINDOW_US == MAX_WINDOW_DAYS * 86_400 * 10**6
    assert (int(users[1]), int(folds[1])) == (MAX_PER_USER, MAX_CONCURRENT_FOLDS)
    assert "`to` is at most one `time_bucket_ms` past the server's clock" in op
    assert "answers `400 invalid_time_range`" in op
    assert '"400": { $ref: "#/components/responses/BadRequest" }' in op
