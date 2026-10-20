"""The 18 built-in indicator presets (21-database-schema.md Sec.10.5; E13-T03, #427).

Revision `0040_indicator_presets` inserts these rows with `owner_user_id` NULL and `is_builtin`
true; `db/seed.py` re-runs the same rows the same way (`ON CONFLICT DO NOTHING`). The revision
holds them as frozen literals (C-5.4) and a unit test pins it to this module, this module to
Sec.10.5 (one row per label, in its order) and every id to `builtin_preset_id`.

- `name` is the Sec.10.5 label verbatim and `indicator_code` the text before its `(`.
- `params` are the indicator's complete parameters where the catalogue
  (`orderflow/indicators/catalogue.py`) defines the indicator, and `pane_target` follows its
  `pane` (`price` draws over the price pane, `sub` in a sub-pane of its own). Nine rows name an
  indicator no catalogue registers yet: `delta`, a rule metric kept out of `V1_INDICATORS`, and
  seven R2 indicators of E18, E19, E23 and E24 over eight rows (`oi` has two). Those carry `{}`
  and a placeholder `pane_target` until their owning epic amends them in a new revision.
- `cvd(never reset)` asks for an anchor the cvd descriptor does not have (`session` or
  `utc_day`; 24 Sec.7.2 has no `since_load`), and the `vwap` row with its 1 and 2 sigma bands
  holds `vwap(session)`'s parameters: the bands are outputs, not parameters. Both are seeded as
  Sec.10.5 lists them; the unit test names each row the catalogue cannot validate, with why.
- Ids are uuid5 of `<indicator_code>/<name>` under `BUILTIN_NAMESPACE`, so they are stable
  wherever a layout pane or a bundle refers to a built-in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

#: uuid5(NAMESPACE_URL, "https://candleviewer.local/indicator-presets/builtin").
BUILTIN_NAMESPACE: Final = uuid.UUID("7b34a329-a3e9-5ca2-8439-d0d3235f4d30")

PaneTarget = Literal["overlay", "subpane"]


def builtin_preset_id(indicator_code: str, name: str) -> uuid.UUID:
    """The stable id of a built-in: uuid5 of `<indicator_code>/<name>`."""
    return uuid.uuid5(BUILTIN_NAMESPACE, f"{indicator_code}/{name}")


@dataclass(frozen=True, slots=True)
class BuiltinPreset:
    """One seeded row; the columns not named here take the table's defaults (`style` `{}`,
    `is_favourite` false), and `is_builtin` is true with no owner."""

    id: str
    indicator_code: str
    name: str
    params: MappingProxyType[str, int | str]
    pane_target: PaneTarget


def _row(
    preset_id: str, code: str, name: str, pane_target: PaneTarget, **params: int | str
) -> BuiltinPreset:
    return BuiltinPreset(preset_id, code, name, MappingProxyType(params), pane_target)


#: 21 Sec.10.5, in its order.
BUILTIN_PRESETS: Final[tuple[BuiltinPreset, ...]] = (
    _row("a9f5bf39-b784-5aaa-ba89-44913e44e85c", "ema", "ema(9)", "overlay", n=9),
    _row("3b3dc488-4d3c-5e9c-aad0-ea73d0029699", "ema", "ema(21)", "overlay", n=21),
    _row("2d9df74b-d718-5a1c-bd57-3cafd116d80a", "ema", "ema(50)", "overlay", n=50),
    _row("515e3c5f-8504-5eef-8838-e005c5dda3bb", "ema", "ema(200)", "overlay", n=200),
    _row("d4aaf9d5-6223-57c7-bba8-d2af49f40789", "vwap", "vwap(session)", "overlay",
         anchor="session"),
    _row("9e84cbef-4759-5e1e-9b5d-3138046688af", "vwap", "vwap(session, ±1\u03c3, ±2\u03c3)",
         "overlay", anchor="session"),  # \u03c3: sigma, escaped for RUF001
    _row("dee545ed-f288-5b06-b413-0beb58f12ebe", "atr", "atr(14)", "subpane", n=14),
    _row("2dd34f1a-bc9d-5d6a-b9e5-0ce33f0df45d", "cvd", "cvd(session reset)", "subpane",
         anchor="session"),
    _row("2c75f7dc-337b-51f9-87fe-b56e34faf492", "cvd", "cvd(never reset)", "subpane",
         anchor="since_load"),
    _row("16875d45-7f91-5432-a146-600fc2ba5640", "delta", "delta(bar)", "subpane"),
    _row("58d4656b-50aa-5d07-bcfd-7eb06427a64b", "volume_profile",
         "volume_profile(VA 70 %, session)", "overlay"),
    _row("165600be-0b5c-5fb8-b294-047e75226993", "delta_profile", "delta_profile(VA 70 %)",
         "overlay"),
    _row("9ce21029-22bc-590a-9eb7-066fbc73bc14", "oi", "oi(absolute)", "subpane"),
    _row("d2aa8e19-11dc-5ebb-a0d8-79a7e0f0877b", "oi", "oi(delta per bar)", "subpane"),
    _row("fa1acea8-1f00-59d4-87a6-6a75de3acc0c", "funding", "funding(annualised)", "subpane"),
    _row("b7c139b9-aa44-56c7-98d8-c9a26046efd3", "speed_of_tape", "speed_of_tape(5 s)",
         "subpane"),
    _row("76b18b62-2548-56db-854b-8c630a03c265", "imbalance_tracker",
         "imbalance_tracker(300 %, stack 3)", "overlay"),
    _row("5a4d54b7-38fc-5cb4-8f03-60d16690d51b", "market_regime", "market_regime(default)",
         "subpane"),
)  # fmt: skip

__all__ = [
    "BUILTIN_NAMESPACE", "BUILTIN_PRESETS", "BuiltinPreset", "PaneTarget", "builtin_preset_id",
]  # fmt: skip
