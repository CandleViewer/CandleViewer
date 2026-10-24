# Fixture for cv-drawings-batch-unvalidated-ids (E14-X03): the API arm, in a file with PEP 695 generics
# and `async def` handlers (#3549). The batch goes to the store whole, not once per op in a loop.
from pydantic import BaseModel


def _parse[M: BaseModel](model: type[M], text: str) -> M:
    return model.model_validate_json(text)


async def batch_one_by_one(request, store, owner, body, ops):
    for op in ops:
        await store().update(owner, op.id, op.fields, if_match=op.if_match)  # ruleid: cv-drawings-batch-unvalidated-ids
    for op in body.operations:
        await store().soft_delete(owner, op.id)  # ruleid: cv-drawings-batch-unvalidated-ids
    return [await store().create(owner, op.id, op.fields) for op in ops]  # ruleid: cv-drawings-batch-unvalidated-ids


async def batch_whole(request, store, owner, body, new_id, audit):
    ops = [_op(op, new_id) for op in body.operations]  # ok: cv-drawings-batch-unvalidated-ids
    res = await store().apply_batch(owner, ops)  # ok: cv-drawings-batch-unvalidated-ids
    for op in ops:
        await audit.note(op.id)  # ok: cv-drawings-batch-unvalidated-ids
    return await store().update(owner, "id", body, if_match=None)  # ok: cv-drawings-batch-unvalidated-ids
