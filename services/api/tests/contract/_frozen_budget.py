"""The consequence read the contract worlds build: the real `ConsequenceRead` and `ExposureRead`
over the world's fake ports, with a clock that never advances and deadlines that never fire.

With the production budget (`REQUEST_BUDGET_S` on `time.monotonic`, `READ_DEADLINE_S` on
`asyncio.timeout`) a runner stall of about a second inside a request turned a key read into
`timeout`, so a test expecting the port's verdict answered `503 exchange_unavailable` (#5639).
The budget's own behaviour is covered in `tests/unit/accounts`; a timeout these worlds need is
the fake port's `KeyReadFailed("timeout")`. `test_contract_frozen_budget.py` keeps every
contract world on this builder.
"""

from __future__ import annotations

import contextlib
from contextlib import AbstractAsyncContextManager
from typing import Any

from candleviewer.accounts.consequences import ConsequenceRead
from candleviewer.accounts.exposure import ExposureRead


def frozen_clock() -> float:
    """A clock that never advances: the budget is never spent."""
    return 0.0


def no_deadline(_seconds: float) -> AbstractAsyncContextManager[object]:
    """A deadline that never fires."""
    return contextlib.nullcontext()


def consequence_read(ports: Any, *, env: str) -> ConsequenceRead:
    """`ports` serves every port the read takes: stores, exposure reader, armed rules, algos."""
    exposure = ExposureRead(ports, env=env, deadline=no_deadline)
    return ConsequenceRead(
        ports, exposure, ports, ports, env=env, clock=frozen_clock, deadline=no_deadline
    )
