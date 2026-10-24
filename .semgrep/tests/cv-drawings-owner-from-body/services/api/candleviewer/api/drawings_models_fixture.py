# Fixture for cv-drawings-owner-from-body (E14-X03, DR1): the schema arm, a request model that names
# an owner. It has a PEP 695 `type` alias (BatchOp), as drawings_models.py does.
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_CFG = ConfigDict(frozen=True, extra="forbid")


class DrawingIn(BaseModel):
    model_config = _CFG
    symbol: str
    owner_user_id: UUID  # ruleid: cv-drawings-owner-from-body


class BatchCreateIn(BaseModel):
    model_config = _CFG
    op: Literal["create"]
    owner: str = ""  # ruleid: cv-drawings-owner-from-body
    user_id: Annotated[UUID, Field()] | None = None  # ruleid: cv-drawings-owner-from-body


class DrawingOut(BaseModel):
    owner_user_id: UUID  # ok: cv-drawings-owner-from-body


class DrawingPointIn(BaseModel):
    t: str  # ok: cv-drawings-owner-from-body

    def describe(self, owner: str) -> str:  # ok: cv-drawings-owner-from-body
        return owner


type BatchOp = Annotated[BatchCreateIn | DrawingIn, Field(discriminator="op")]
