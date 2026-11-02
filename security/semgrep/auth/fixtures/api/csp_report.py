"""Fixture: the one file where an unaudited POST /csp-report is allowed (E43-T01)."""


@router.post("/csp-report")  # ok: audit-write-required
async def csp_report_ok(body):
    return await svc.count(body)


@router.post("/csp-report")  # ok: audit-write-required-route-scope
async def csp_report_scope_ok(body):
    return await svc.count(body)


@router.post("/csp-report/flush")  # ruleid: audit-write-required
async def csp_report_flush_still_flagged(body):
    return await svc.flush(body)
