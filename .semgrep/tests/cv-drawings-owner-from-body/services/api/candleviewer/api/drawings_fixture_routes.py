# Fixture for cv-drawings-owner-from-body (E14-X03, DR1): the flow arms, in a file with PEP 695
# generics and `async def` handlers shaped like api/drawings.py (#3549). A marker sits on the
# line a finding starts on.
from pydantic import BaseModel


def _parse[M: BaseModel](model: type[M], text: str) -> M:
    return model.model_validate_json(text)


async def owner_from_the_request(request, store, did, fields):
    owner = request.query_params["owner"]  # ruleid: cv-drawings-owner-from-body
    await store().list_page(request.query_params["user"], symbol="BTCUSDT")  # ruleid: cv-drawings-owner-from-body
    await store().soft_delete((await request.json())["u"], did)  # ruleid: cv-drawings-owner-from-body
    body = _parse(DrawingIn, "{}")
    await store().create(body.owner_user_id, "id", fields)  # ruleid: cv-drawings-owner-from-body
    await audit.emit("touch", owner_user_id=body.owner_user_id)  # ruleid: cv-drawings-owner-from-body
    return {"owner": request.headers["x-owner"], "id": owner}  # ruleid: cv-drawings-owner-from-body


async def owner_from_the_session(request, store, caller, did, drawing_id):
    principal = await caller(request, "workspaces:write")  # ok: cv-drawings-owner-from-body
    owner, did = str(principal.user_id), str(drawing_id)  # ok: cv-drawings-owner-from-body
    q = ListQuery.model_validate(dict(request.query_params))  # ok: cv-drawings-owner-from-body
    await store().list_page(owner, symbol=q.symbol, layout_id=q.layout_id, limit=q.limit)  # ok: cv-drawings-owner-from-body
    body = _parse(DrawingIn, "{}")  # ok: cv-drawings-owner-from-body
    await store().update(owner, did, _fields(body), if_match=None)  # ok: cv-drawings-owner-from-body
    key = request.headers.get("idempotency-key")  # ok: cv-drawings-owner-from-body
    hit = cache.get(body.key)  # ok: cv-drawings-owner-from-body
    owner = str((await caller(request, "workspaces:read")).user_id)  # ok: cv-drawings-owner-from-body
    return key, hit
