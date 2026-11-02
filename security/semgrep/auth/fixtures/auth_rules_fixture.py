"""Fixtures for the E09-X03 auth Semgrep pack: positive (`ruleid`) and negative (`ok`).

Never imported or run -- only scanned by tools/ci/check_auth_semgrep.py.
"""
# ruff: noqa
# fmt: off


# --- no-raw-account-id (SR-051) -------------------------------------------
@router.get("/positions")  # ruleid: no-raw-account-id
async def positions_bad(account_id: str):
    return await repo.positions(account_id)


@router.get("/orders")  # ok: no-raw-account-id
async def orders_ok(account_id: str, scope):
    allowed = scope.intersect(account_id)
    return await repo.orders(allowed)


@router.get("/fills")  # ruleid: no-raw-account-id
async def fills_bad_unrelated_intersect(account_ids: list[str], scope):
    # scope.intersect(account_ids) -- a comment is not scoping
    other = tags.intersect(set())
    return await repo.fills(account_ids)


@router.get("/pnl")  # ruleid: no-raw-account-id
async def pnl_bad_camel(accountId: str = Query(None)):
    return await repo.pnl(accountId)


@router.post("/rules/check")  # ok: no-raw-account-id
async def rules_ok(account_ids: list[str], resolver, caller):
    await resolver.authorize_accounts(caller, [UUID(a) for a in account_ids])
    return None


# --- no-adhoc-authz (SR-017) ----------------------------------------------
def adhoc_bad(principal):
    if principal.role == "owner":  # ruleid: no-adhoc-authz
        return True
    return False


def adhoc_getattr_bad(principal):
    return getattr(principal, "role") == "owner"  # ruleid: no-adhoc-authz


def adhoc_ok(principal):
    return authorize(principal, "orders.read", None)  # ok: no-adhoc-authz


# --- no-target-user-on-self-service (SR-026) ------------------------------
@router.post("/me/password")  # ruleid: no-target-user-on-self-service
async def me_bad(user_id: str):
    return None


@router.post("/me/sessions")  # ok: no-target-user-on-self-service
async def me_ok(principal):
    return None


@router.get("/users/{user_id}")  # ok: no-target-user-on-self-service
async def admin_get_user(user_id: str):
    return None


# --- stepup-required (SR-025) ---------------------------------------------
@router.post("/admin/kill-switch")  # ruleid: stepup-required
async def kill_bad():
    return None


@router.post(KILL_SWITCH_PATH)  # ruleid: stepup-required
async def kill_const_bad():
    return None


@router.post("/me/api-keys")  # ruleid: stepup-required
async def keys_comment_only_bad():
    # require_step_up is mentioned here but never called
    return None


@router.delete("/me/api-keys/{key_id}")  # ok: stepup-required
async def keys_body_ok(auth):
    gate = await require_elevation_for(auth, "x", "api_keys")
    return gate


@router.post("/admin/kill-switch/arm", dependencies=[Depends(require_step_up("kill"))])  # ok: stepup-required
async def kill_ok():
    return None


@router.post("/backups/{backupId}/download")  # ruleid: stepup-required
async def link_unbound_bad(auth):
    await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)
    return None


@router.post("/backups/{backupId}/download")  # ok: stepup-required
async def link_bound_ok(auth):
    spent = await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)
    if not isinstance(spent, SpentGrant):
        return spent
    return None


@router.post("/backups/{backupId}/download")  # ruleid: stepup-required
async def link_discarded_bad(auth):
    _ = await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)


@router.post("/backups/{backupId}/download")  # ruleid: stepup-required
async def link_unchecked_bad(auth):
    spent = await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)
    return {"spent": str(spent)}


@router.post("/backups/{backupId}/download")  # ruleid: stepup-required
async def link_swallowed_bad(auth):
    try:
        spent = await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)
    except Exception:
        spent = None


@router.post("/backups/{backupId}/download")  # ruleid: stepup-required
async def link_checked_not_returned_bad(auth):
    spent = await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)
    if not isinstance(spent, SpentGrant):
        pass


@router.post("/backups/{backupId}/restore")  # ruleid: stepup-required
async def restore_unbound_bad(auth):
    await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)


@router.post("/backups/{backupId}/restore")  # ok: stepup-required
async def restore_bound_ok(auth):
    spent = await require_bound_elevation(auth, "s", "backups", fingerprint="f", emitter=None)
    if not isinstance(spent, SpentGrant):
        return spent
    return None


@router.get("/backups/{backupId}/download/{token}")  # ok: stepup-required
async def link_fetch_ok():
    return None


# #2110 (BQ-220): the caller's own password change is not step-up gated.
@router.put("/auth/password")  # ok: stepup-required
async def own_password_change_ok():
    return None


@router.put("/auth/password/reset")  # ruleid: stepup-required
async def password_longer_path_bad():
    return None


@router.put("/admin/auth/password")  # ruleid: stepup-required
async def password_prefixed_path_bad():
    return None


@router.put("/x.auth/password")  # ruleid: stepup-required
async def password_dotted_prefix_bad():
    return None


@router.put("/auth/password.json")  # ruleid: stepup-required
async def password_dotted_suffix_bad():
    return None


@router.put("/users/{userId}/password")  # ruleid: stepup-required
async def other_users_password_bad():
    return None


# --- no-secret-logging (SR-122) -------------------------------------------
def log_bad(logger, session_token):
    logger.info("login", session_token)  # ruleid: no-secret-logging


def log_fstring_bad(logger, recovery_code):
    logger.warning(f"bad code {recovery_code}")  # ruleid: no-secret-logging


class Svc:
    def attr_logger_bad(self, body):
        self.logger.info(body.password)  # ruleid: no-secret-logging


def log_attr_secret_bad(log, user):
    log.warning("x %s", user.token)  # ruleid: no-secret-logging


def log_structlog_bad(req):
    structlog.get_logger().info("k", key=req.api_key)  # ruleid: no-secret-logging


def log_attr_ok(self, user):
    self.logger.info("login", user_id=user.id)  # ok: no-secret-logging


def log_session_id_ok(_log, session_id):
    _log.error("x", extra={"session_id": session_id})  # ok: no-secret-logging


def log_nonlogger_ok(cache, body):
    cache.info(body.password)  # ok: no-secret-logging


def log_ok(logger, user_id):
    logger.info("login", user_id=user_id)  # ok: no-secret-logging


# --- cookie-flags (SR-012) ------------------------------------------------
def cookie_bad(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True)  # ruleid: cookie-flags


def cookie_domain_bad(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="strict", domain=".x.io")  # ruleid: cookie-flags-domain


def cookie_domain_ok(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="strict")  # ok: cookie-flags-domain


def cookie_ok(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="strict")  # ok: cookie-flags


def cookie_samesite_none_bad(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="none")  # ruleid: cookie-flags


def cookie_samesite_lax_bad(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="lax")  # ruleid: cookie-flags


def cookie_samesite_computed_bad(response, sid, attrs):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite=attrs.samesite)  # ruleid: cookie-flags


def cookie_samesite_conditional_bad(response, sid, request):
    samesite = "none" if request.headers.get("origin") == "app://candleviewer" else "strict"
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite=samesite)  # ruleid: cookie-flags


def cookie_csrf_computed_bad(response, token, attrs):
    # HttpOnly=False is the CSRF cookie's one exception; its samesite is not an exception (ADR-0038 4b)
    response.set_cookie("__Host-cv_csrf", token, path="/", secure=True, httponly=False, samesite=attrs.samesite)  # ruleid: cookie-flags


def cookie_delete_ok(response):
    response.delete_cookie("cv_refresh", path="/api/v1/auth", httponly=True, secure=True, samesite="strict")  # ok: cookie-flags


def cookie_delete_computed_bad(response, attrs):
    response.delete_cookie("cv_refresh", path="/api/v1/auth", httponly=True, secure=True, samesite=attrs.samesite)  # ruleid: cookie-flags


def cookie_delete_default_bad(response):
    response.delete_cookie("cv_refresh", path="/api/v1/auth")  # ruleid: cookie-flags


# ADR-0038 4b: the one function that picks SameSite. Its home is api/csrf.py, so its definition in
# any other module (this one) is refused; cookie-flags and cookie-flags-raw-header read its body as
# the writer's.
def write_auth_cookie(response, name, value, attrs, httponly, max_age):  # ruleid: cookie-flags-writer-location
    response.set_cookie(name, value, max_age=max_age, path="/", secure=True, httponly=httponly, samesite=attrs.samesite)  # ok: cookie-flags
    response.set_cookie(name, "", max_age=0, expires=0, path="/", secure=True, httponly=httponly, samesite=attrs.samesite)  # ok: cookie-flags
    response.set_cookie(name, value, max_age=max_age, path="/", httponly=httponly, samesite=attrs.samesite)  # ruleid: cookie-flags
    response.set_cookie(name, value, max_age=max_age, path="/", secure=True, samesite=attrs.samesite)  # ruleid: cookie-flags
    response.set_cookie(name, value, max_age=max_age, path="/", secure=True, httponly=httponly)  # ruleid: cookie-flags
    response.set_cookie(name, value, max_age=max_age, secure=True, httponly=httponly, samesite=attrs.samesite, domain=".x.io")  # ruleid: cookie-flags-domain
    response.delete_cookie(name, path="/", secure=True, httponly=httponly, samesite=attrs.samesite)  # ok: cookie-flags
    response.delete_cookie(name, path="/", httponly=httponly, samesite=attrs.samesite)  # ruleid: cookie-flags
    header_name, header = response.raw_headers[-1]
    response.raw_headers[-1] = (header_name, header + b"; Partitioned")  # ok: cookie-flags-raw-header


# Same-named writers outside api/csrf.py: each would escape cookie-flags by its name alone.
async def write_auth_cookie(response, name, value, attrs):  # ruleid: cookie-flags-writer-location
    response.set_cookie(name, value, secure=True, httponly=True, samesite=attrs.samesite)


def cookie_writer_nested(response, attrs):
    def write_auth_cookie(name, value):  # ruleid: cookie-flags-writer-location
        response.set_cookie(name, value, secure=True, httponly=True, samesite=attrs.samesite)

    write_auth_cookie("cv_refresh", "x")  # ok: cookie-flags-writer-location


class CookieWriter:
    def write_auth_cookie(self, response, name, value, attrs):  # ruleid: cookie-flags-writer-location
        response.set_cookie(name, value, secure=True, httponly=True, samesite=attrs.samesite)


def cookie_raw_header_bad(response, message, headers, pair, pairs, value):
    response.headers.append("set-cookie", value)  # ruleid: cookie-flags-raw-header
    response.headers["Set-Cookie"] = value  # ruleid: cookie-flags-raw-header
    headers.setdefault("set-cookie", value)  # ruleid: cookie-flags-raw-header
    headers.update({"Set-Cookie": value})  # ruleid: cookie-flags-raw-header
    message["headers"].append((b"set-cookie", value))  # ruleid: cookie-flags-raw-header
    response.raw_headers.append((b"set-cookie", value))  # ruleid: cookie-flags-raw-header
    response.raw_headers.extend(pairs)  # ruleid: cookie-flags-raw-header
    response.raw_headers.insert(0, pair)  # ruleid: cookie-flags-raw-header
    header_name, header = response.raw_headers[-1]
    response.raw_headers[-1] = (header_name, header + b"; Partitioned")  # ruleid: cookie-flags-raw-header
    response.raw_headers += [pair]  # ruleid: cookie-flags-raw-header
    response.raw_headers = [pair]  # ruleid: cookie-flags-raw-header
    response.raw_headers[:] = [pair]  # ruleid: cookie-flags-raw-header
    response.headers.raw.append(pair)  # ruleid: cookie-flags-raw-header
    response.headers.raw.extend(pairs)  # ruleid: cookie-flags-raw-header
    response.headers.raw.insert(0, pair)  # ruleid: cookie-flags-raw-header
    response.headers.raw[0] = pair  # ruleid: cookie-flags-raw-header
    response.headers.raw += [pair]  # ruleid: cookie-flags-raw-header
    response.headers.raw = [pair]  # ruleid: cookie-flags-raw-header
    response.headers . raw.append(pair)  # ruleid: cookie-flags-raw-header
    response.headers.raw.extend([(b"set-cookie", value)])  # ruleid: cookie-flags-raw-header
    response.raw_headers[1:] = pairs  # ruleid: cookie-flags-raw-header
    response.raw_headers[0] += pair  # ruleid: cookie-flags-raw-header


def cookie_raw_header_ok(response, token, ws):
    response.headers.append("x-csrf-token", token)  # ok: cookie-flags-raw-header
    response.headers["Cache-Control"] = "no-store"  # ok: cookie-flags-raw-header
    redacted = ("set-cookie", "authorization")  # ok: cookie-flags-raw-header
    count = len(response.headers.raw)  # ok: cookie-flags-raw-header
    # Header names, not a Set-Cookie pair, and a read of the request's raw headers (ws/gateway.py).
    names = (b"origin", b"sec-fetch-site")  # ok: cookie-flags-raw-header
    raw_headers = ws.scope.get("headers") or ()  # ok: cookie-flags-raw-header


# --- argon2-params (SR-011) -----------------------------------------------
weak = PasswordHasher(memory_cost=1024, time_cost=3, parallelism=4)  # ruleid: argon2-params
strong = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)  # ok: argon2-params


# --- audit-write-required (SR-112) ----------------------------------------
@router.post("/accounts")  # ruleid: audit-write-required
async def create_bad(body):
    return await svc.create(body)


@router.post("/accounts/archive")  # ok: audit-write-required
async def archive_ok(body):
    await _audit("account.archive")
    return await svc.archive(body)


@router.put("/drawings/{drawingId}")  # ok: audit-write-required
async def drawing_put_ok(body):
    return await svc.put(body)


@router.post("/drawings/{drawingId}/share")  # ruleid: audit-write-required
async def drawing_share_bad(body):
    return await svc.share(body)


@router.post("/workspaces/{workspaceId}/layouts")  # ok: audit-write-required
async def post_layout_ok(body):
    return await svc.post(body)


@router.post("/drawings/batch-delete")  # ruleid: audit-write-required
async def post_batch_delete_bad(body):
    return await svc.post(body)


@router.put("/workspaces/{workspaceId}")  # ok: audit-write-required
async def put_workspace_ok(body):
    return await svc.put(body)


@router.post("/csp-report/flush")  # ruleid: audit-write-required
async def csp_report_flush_bad(body):
    return await svc.flush(body)


@router.put("/drawings/{drawingId}/alert")  # ruleid: audit-write-required
async def put_alert_bad(body):
    return await svc.put(body)


@router.delete("/workspaces/{workspaceId}/layouts/{layoutId}")  # ok: audit-write-required
async def delete_layout_ok():
    return await svc.delete()


@router.delete("/workspaces/{workspaceId}/share")  # ruleid: audit-write-required
async def delete_ws_share_bad():
    return await svc.delete()


@router.delete("/drawings/batch")  # ruleid: audit-write-required
async def delete_batch_bad():
    return await svc.delete()


# --- audit-write-required-route-scope -------------------------------------
@admin.delete("/workspaces/{workspaceId}")  # ruleid: audit-write-required-route-scope
async def admin_delete_workspace_bad(workspace_id):
    return await svc.delete(workspace_id)


@admin.post("/drawings")  # ruleid: audit-write-required-route-scope
async def admin_post_drawing_bad(body):
    return await svc.post(body)


@admin.put("/drawings/{drawingId}")  # ruleid: audit-write-required-route-scope
async def admin_put_drawing_bad(body):
    return await svc.put(body)


@admin.post("/csp-report")  # ruleid: audit-write-required-route-scope
async def admin_post_csp_report_bad(body):
    return await svc.post(body)


@admin.delete("/workspaces/{workspaceId}")  # ok: audit-write-required-route-scope
async def admin_delete_workspace_audited_ok(workspace_id):
    await _audit("workspace.delete")
    return await svc.delete(workspace_id)


@admin.delete("/users/{userId}/workspaces")  # ok: audit-write-required-route-scope
async def admin_delete_user_workspaces_ok(user_id):
    await _audit("workspace.purge")
    return await svc.purge(user_id)


@router.get("/accounts")  # ok: audit-write-required
async def list_ok():
    return await svc.list()
