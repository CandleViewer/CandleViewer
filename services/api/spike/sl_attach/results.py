"""One row per sample, discarded ones included (the scout's §5), written as Parquet through
`pyarrow` (already a dependency of `services/api`) with a JSON Lines twin for review diffs.

The row is a pydantic model that refuses an unknown field. It names the order only by a per-run
token (`order_ref`), never an id, and holds `retMsg` only as a short class. Before anything is
written every row passes #843's scrubber check (`Scrubber.check`): a row that still carries a
registered value (a key id, a UID, an order or link id) is refused whole (`LeakDetected`), so
the files hold scrubbed rows or none. Both files go through #843's `outputs.write_file`
(created 0600, `O_NOFOLLOW`: a symlink planted at either name is refused, never followed).
"""

from __future__ import annotations

import io
import json
import types
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final, Literal, Union, get_args, get_origin

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict

from spike.oms_demo_path.outputs import write_file
from spike.oms_demo_path.scrub import Scrubber
from spike.sl_attach.config import Arm

PARQUET: Final = "samples.parquet"
JSONL: Final = "samples.jsonl"

type Outcome = Literal["ok", "rejected", "ambiguous", "discarded"]
type Discard = Literal["incomplete", "skew", "stopped", "no_fill", "refused"]
type Stage = Literal["create", "trading_stop"]


class Sample(BaseModel):
    """One attempt of one arm."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    sample_id: int
    arm: Arm
    symbol: str
    side: str
    position_idx: int
    qty: str
    order_ref: str
    # arm (a): the create's call
    ack_ms: float | None = None
    port_latency_ms: float | None = None
    rtt_ms: float | None = None
    overhead_ms: float | None = None
    attempts: int = 0
    # arm (b), and the protection evidence of both arms
    exec_time_ms: int | None = None
    ingest_us: int | None = None
    push_lag_ms: float | None = None
    react_ms: float | None = None
    stop_rtt_ms: float | None = None
    #: the port's return after the tap's receipt of the stop's `200` (its parse); not in
    #: `exposure_ms`, which ends at the receipt
    port_parse_ms: float | None = None
    exposure_ms: float | None = None
    exposure_venue_ms: float | None = None
    #: arm (b): whether its `trading-stop` landed (acked and shown on the position). `False`
    #: also when its opener filled but no stop write was sent (a lost or late execution push,
    #: an ambiguous create that filled): that position sat on the backstop alone. `None` only
    #: when no stop was owed (the opener never filled). A `False` is unbounded exposure.
    stop_landed: bool | None = None
    protected_lag_ms: float | None = None
    # the clocks and the venue's rate headers on the measured call
    offset_ms: float | None = None
    offset_uncertainty_ms: float | None = None
    skew_ms: float | None = None
    server_time_ms: int | None = None
    timenow_ms: int | None = None
    limit_status: int | None = None
    limit_cap: int | None = None
    limit_reset_ms: int | None = None
    # the taxonomy, of the call named by `stage`
    stage: Stage | None = None
    ret_code: int | None = None
    ret_msg_class: str | None = None
    adapter_error_code: str | None = None
    s86_code: str | None = None
    retryable: bool | None = None
    taxonomy_divergent: bool = False
    # what protecting the position cost (the close is not counted)
    requests_order_class: int = 0
    requests_position_class: int = 0
    requests_reads: int = 0
    outcome: Outcome
    discard_reason: Discard | None = None


_ARROW: Final = {str: pa.string(), int: pa.int64(), float: pa.float64(), bool: pa.bool_()}


def _arrow_type(annotation: object) -> pa.DataType:
    """A field's Arrow type: its one non-`None` member; a `Literal` is a string."""
    origin = get_origin(annotation)
    if origin in (types.UnionType, Union):
        [member] = [a for a in get_args(annotation) if a is not type(None)]
        return _arrow_type(member)
    if origin is Literal:
        return pa.string()
    value = getattr(annotation, "__value__", None)  # a `type X = Literal[...]` alias
    if value is not None:
        return _arrow_type(value)
    return _ARROW[annotation]  # type: ignore[index]  # an unknown type is a defect: KeyError


SCHEMA: Final = pa.schema(
    [pa.field(name, _arrow_type(f.annotation)) for name, f in Sample.model_fields.items()]
)


def write_samples(directory: Path, samples: Sequence[Sample], scrubber: Scrubber) -> None:
    """Both files, every row checked first; nothing is written if any row is refused."""
    rows = [s.model_dump(mode="json") for s in samples]
    lines = [json.dumps(row, separators=(",", ":"), sort_keys=True) for row in rows]
    for line in lines:
        scrubber.check(line)
    parquet = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), parquet)
    directory.mkdir(parents=True, exist_ok=True)
    write_file(directory / JSONL, "".join(f"{line}\n" for line in lines).encode(), append=False)
    write_file(directory / PARQUET, parquet.getvalue(), append=False)


def _validated(rows: Iterable[dict[str, object]]) -> list[Sample]:
    return [Sample.model_validate(row) for row in rows]


def read_parquet(directory: Path) -> list[Sample]:
    return _validated(pq.read_table(directory / PARQUET, schema=SCHEMA).to_pylist())


def read_jsonl(directory: Path) -> list[Sample]:
    text = (directory / JSONL).read_text(encoding="utf-8")
    return _validated(json.loads(line) for line in text.splitlines() if line)
