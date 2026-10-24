# Fixture for cv-drawings-batch-unvalidated-ids (E14-X03, DR12/DR21/DR23): the repository arm. The
# owner-scoped snapshot precedes every UPDATE or DELETE of existing rows, in the same function.


class Repository:
    async def update_without_snapshot(self, uow, owner, ids, rows):
        return await uow.session.execute(_UPDATE_MANY, {"owner": owner, "ids": ids, "rows": rows})  # ruleid: cv-drawings-batch-unvalidated-ids

    async def delete_without_snapshot(self, uow, owner, ids):
        return await uow.session.execute(_SOFT_DELETE_MANY, {"owner": owner, "ids": ids})  # ruleid: cv-drawings-batch-unvalidated-ids

    async def snapshot_comes_after(self, uow, owner, ids, rows):
        await uow.session.execute(_UPDATE_MANY, {"owner": owner, "ids": ids, "rows": rows})  # ruleid: cv-drawings-batch-unvalidated-ids
        await uow.session.execute(_SNAPSHOT, {"owner": owner, "ids": ids})

    async def apply_batch(self, uow, owner, ids, rows, updates, deletes):
        locked = await uow.session.execute(_SNAPSHOT, {"ids": ids, "owner": owner})
        if updates:
            await uow.session.execute(_UPDATE_MANY, {"owner": owner, "ids": ids, "rows": rows})  # ok: cv-drawings-batch-unvalidated-ids
        if deletes:
            await uow.session.execute(_SOFT_DELETE_MANY, {"owner": owner, "ids": ids})  # ok: cv-drawings-batch-unvalidated-ids
        return locked

    async def creates_only(self, uow, owner, rows):
        return await uow.session.execute(_INSERT_MANY, {"owner": owner, "rows": rows})  # ok: cv-drawings-batch-unvalidated-ids
