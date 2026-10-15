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


@router.get("/accounts")  # ok: audit-write-required
async def list_ok():
    return await svc.list()
