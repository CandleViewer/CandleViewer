"""#898 (E27-S04 B3b): the null `Flattener` reports every account still not flat (22
`OpenExposure`), so a `flatten_first` action is never carried out."""

from __future__ import annotations

from uuid import UUID

from candleviewer.accounts.flatten import Flattener, NoFlatten

ACC = UUID("a1000000-0000-4000-8000-000000000001")
OWNER = UUID("00000000-0000-4000-8000-0000000000aa")


async def test_the_null_flattener_reports_every_account_still_not_flat() -> None:
    flattener: Flattener = NoFlatten()
    assert await flattener.flatten(ACC, actor=OWNER) is False
