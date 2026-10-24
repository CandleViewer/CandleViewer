# Fixture for cv-drawings-unbounded-geometry (E14-X03, DR29/DR30): the roads round the validator, in a
# file with PEP 695 generics (#3549). A marker sits on the line a finding starts on.
import dataclasses as dc
from dataclasses import replace

from pydantic import BaseModel, ConfigDict


def _parse[M: BaseModel](model: type[M], text: str) -> M:
    return model.model_validate_json(text)


def _fields(body):
    return DrawingFields(**body.db_values())  # ok: cv-drawings-unbounded-geometry


async def routes(store, owner, body, raw):
    fields = DrawingFields(symbol="BTCUSDT", geometry={"points": []})  # ruleid: cv-drawings-unbounded-geometry
    await store().create(owner, "id", {"symbol": "BTCUSDT", "geometry": {}})  # ruleid: cv-drawings-unbounded-geometry
    await store().apply_batch(owner, [{"op": "create"}])  # ruleid: cv-drawings-unbounded-geometry
    unchecked = DrawingIn.model_construct(symbol="BTCUSDT")  # ruleid: cv-drawings-unbounded-geometry
    moved = body.model_copy(update={"geometry": {}})  # ruleid: cv-drawings-unbounded-geometry
    swapped = dataclasses.replace(fields, geometry={"points": []})  # ruleid: cv-drawings-unbounded-geometry
    aliased = dc.replace(fields, geometry={"points": []})  # ruleid: cv-drawings-unbounded-geometry
    imported = replace(fields, geometry={"points": []})  # ruleid: cv-drawings-unbounded-geometry
    text = raw.replace("a", "b")  # ok: cv-drawings-unbounded-geometry
    same = body.model_copy()  # ok: cv-drawings-unbounded-geometry
    parsed = _parse(DrawingIn, raw)  # ok: cv-drawings-unbounded-geometry
    await store().update(owner, "id", _fields(parsed), if_match=None)  # ok: cv-drawings-unbounded-geometry
    return fields, unchecked, moved, same


class Open(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")  # ruleid: cv-drawings-unbounded-geometry


class Ignoring(BaseModel):
    model_config = {"extra": "ignore"}  # ruleid: cv-drawings-unbounded-geometry


class Closed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")  # ok: cv-drawings-unbounded-geometry


class _ListQuery(BaseModel):  # the list query ignores unknown parameters, as FastAPI does
    model_config = ConfigDict(frozen=True, extra="ignore")  # ok: cv-drawings-unbounded-geometry
