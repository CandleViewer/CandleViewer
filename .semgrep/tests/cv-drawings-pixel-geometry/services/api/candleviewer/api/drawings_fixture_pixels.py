# Fixture for cv-drawings-pixel-geometry (E14-X03, DR10): chart space only, never pixels. PEP 695
# generics and a `type` alias as in api/drawings_models.py (#3549). A marker sits on the finding's line.
from typing import Annotated

from pydantic import BaseModel, Field


class DrawingPointIn(BaseModel):
    t: str  # ok: cv-drawings-pixel-geometry
    p: str  # ok: cv-drawings-pixel-geometry


class PixelPoint(BaseModel):
    x: float  # ruleid: cv-drawings-pixel-geometry
    y: float = 0.0  # ruleid: cv-drawings-pixel-geometry
    px: Annotated[int, Field(ge=0)]  # ruleid: cv-drawings-pixel-geometry


def build(geometry, points):
    point = {"x": 10, "t": "2026-10-23T00:00:00Z"}  # ruleid: cv-drawings-pixel-geometry
    geometry["px"] = 3  # ruleid: cv-drawings-pixel-geometry
    moved = DrawingPointIn(y=2, p="1.5")  # ruleid: cv-drawings-pixel-geometry
    chart = {"t": "2026-10-23T00:00:00Z", "p": "1.5"}  # ok: cv-drawings-pixel-geometry
    parts = [int(x) for x in "2026-10-23".split("-")]  # ok: cv-drawings-pixel-geometry
    return point, moved, chart, parts


def total[T](x: T, y: T) -> list[T]:
    return [x, y]


type BatchPoint = Annotated[DrawingPointIn | PixelPoint, Field()]
