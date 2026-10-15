"""Admin read models (E42-T01): `GET /admin/overview` and `GET /admin/capacity`.

`fanout.SliceFanOut` is the partial-result core both read models share; the HTTP layer maps its
internal `SliceResult`s to the generated `AdminOverview` / `CapacityReport` models.
"""

from __future__ import annotations
