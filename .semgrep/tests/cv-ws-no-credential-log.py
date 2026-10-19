"""Fixtures for cv-ws-no-credential-log (E17-X02, SR-122).

Scanned only, never imported: each `ruleid` row must fire and each `ok` row must stay clean.
"""
import logging

import structlog
from structlog.contextvars import bind_contextvars, bound_contextvars

log = structlog.get_logger(__name__)

# --- a credential-named value, in each position and form
_log().warning("auth failed", token=token)  # ruleid: cv-ws-no-credential-log
_log().warning("auth failed", token)  # ruleid: cv-ws-no-credential-log
log.info("auth", access_token)  # ruleid: cv-ws-no-credential-log
log.error("auth", refresh=refresh_token)  # ruleid: cv-ws-no-credential-log
log.info("auth", self.access_token)  # ruleid: cv-ws-no-credential-log
log.info("auth", frame=self._token)  # ruleid: cv-ws-no-credential-log
log.debug("handshake", authorization)  # ruleid: cv-ws-no-credential-log
log.debug("handshake", header=auth_header)  # ruleid: cv-ws-no-credential-log
log.warning("handshake", bearer)  # ruleid: cv-ws-no-credential-log
log.warning("handshake", value=cookie)  # ruleid: cv-ws-no-credential-log
log.warning("handshake", cookie=cookie)  # ruleid: cv-ws-no-credential-log
log.error("handshake", secret)  # ruleid: cv-ws-no-credential-log
log.error("handshake", secret_key)  # ruleid: cv-ws-no-credential-log
log.info(f"auth {token}")  # ruleid: cv-ws-no-credential-log
log.info("auth %s", token)  # ruleid: cv-ws-no-credential-log
log.info("auth %s" % token)  # ruleid: cv-ws-no-credential-log
log.info("auth {}".format(token))  # ruleid: cv-ws-no-credential-log
log.info("auth", value=str(token))  # ruleid: cv-ws-no-credential-log
log.info("auth", prefix=token[:6])  # ruleid: cv-ws-no-credential-log
log.info("auth", frame["token"])  # ruleid: cv-ws-no-credential-log
log.info("auth", value=frame["p"]["access_token"])  # ruleid: cv-ws-no-credential-log
log.info("handshake", headers["authorization"])  # ruleid: cv-ws-no-credential-log
log.info("handshake", value=request.headers.get("Authorization", ""))  # ruleid: cv-ws-no-credential-log
# --- ... beside a safe form, or inside a parenthesised expression
log.info("auth", n=len(token), t=token)  # ruleid: cv-ws-no-credential-log
log.info("auth", value=token or "")  # ruleid: cv-ws-no-credential-log
log.info("auth", value=(token + suffix))  # ruleid: cv-ws-no-credential-log
# --- a credential-named keyword, whatever its value
log.info("auth", token=value)  # ruleid: cv-ws-no-credential-log
log.info("auth", access_token=value)  # ruleid: cv-ws-no-credential-log
log.info("auth", Authorization=value)  # ruleid: cv-ws-no-credential-log
log.info("auth", cookie=value)  # ruleid: cv-ws-no-credential-log
log.info("auth", secret=value)  # ruleid: cv-ws-no-credential-log
log.info("auth", bearer=value)  # ruleid: cv-ws-no-credential-log
log.info("auth", auth_header=value)  # ruleid: cv-ws-no-credential-log
# --- the logger, as it is spelled
structlog.get_logger(__name__).warning("handshake", cookie=cookie)  # ruleid: cv-ws-no-credential-log
logging.getLogger(__name__).error("handshake", secret)  # ruleid: cv-ws-no-credential-log
log.bind(token=token)  # ruleid: cv-ws-no-credential-log
log.new(token=token)  # ruleid: cv-ws-no-credential-log
self._log.bind(connection=1).info("auth", self.token)  # ruleid: cv-ws-no-credential-log
log.new(connection=1).info("auth", token)  # ruleid: cv-ws-no-credential-log
ws_log.warning("auth", token)  # ruleid: cv-ws-no-credential-log
logger.info("auth", token)  # ruleid: cv-ws-no-credential-log
self.logger.warning("auth", token)  # ruleid: cv-ws-no-credential-log
logging.warning("auth %s", token)  # ruleid: cv-ws-no-credential-log
await log.ainfo("auth", token)  # ruleid: cv-ws-no-credential-log
_log().bind(
    connection_id=connection_id,
).warning("auth", token)  # ruleid: cv-ws-no-credential-log
# --- the log context binders
structlog.contextvars.bind_contextvars(token=value)  # ruleid: cv-ws-no-credential-log
structlog.contextvars.bind_contextvars(user_id=1, who=token)  # ruleid: cv-ws-no-credential-log
bind_contextvars(access_token=value)  # ruleid: cv-ws-no-credential-log
bind_contextvars(who=token)  # ruleid: cv-ws-no-credential-log
bound_contextvars(token=value)  # ruleid: cv-ws-no-credential-log
bound_contextvars(who=token)  # ruleid: cv-ws-no-credential-log

# --- fine: a length, a presence test, a redacting wrapper, an id, a reason code, prose, a literal
log.info("auth", n=len(token))  # ok: cv-ws-no-credential-log
log.info("auth", have_token=token is not None)  # ok: cv-ws-no-credential-log
log.info("auth", no_token=token is None)  # ok: cv-ws-no-credential-log
log.info("auth", have_token=not token)  # ok: cv-ws-no-credential-log
log.info("auth", have_token=bool(token))  # ok: cv-ws-no-credential-log
log.info("auth", same=token == other, differs=token != other)  # ok: cv-ws-no-credential-log
log.info("auth", kind=type(token).__name__)  # ok: cv-ws-no-credential-log
log.info("auth", value=Secret(token))  # ok: cv-ws-no-credential-log
log.info("auth", token_len=len(token), kind=len(self.access_token))  # ok: cv-ws-no-credential-log
log.info("auth", token_expires_at_ms=expires_ms, token_kind=kind)  # ok: cv-ws-no-credential-log
# --- ... also nested in a larger expression
log.info("auth", n={"n": len(token)})  # ok: cv-ws-no-credential-log
log.info("auth", n=f"len {len(token)}")  # ok: cv-ws-no-credential-log
log.info("auth", n=(token is None) or other)  # ok: cv-ws-no-credential-log
# --- ... a keyword named like a credential, with a value that holds none
log.info("auth", token="redacted")  # ok: cv-ws-no-credential-log
log.info("auth", token=None)  # ok: cv-ws-no-credential-log
log.info("auth", have_token=True, have_cookie=False)  # ok: cv-ws-no-credential-log
log.info("auth", token=bool(value))  # ok: cv-ws-no-credential-log
# --- ... a lookalike: an expiry, a TTL, an ALL-CAPS constant, an enum member
log.info("auth", at=conn.token_expires_at_ms, ttl=self._token_ttl_ms, ends=conn.tokenExpiresAt)  # ok: cv-ws-no-credential-log
log.info("auth", size=PROBE_TOKEN_BYTES, code=ErrorCode.TOKEN_REJECTED)  # ok: cv-ws-no-credential-log
# --- ... valid code with a parenthesised argument: a nested `metavariable-pattern` made Semgrep report an engine error on it
log.info("ws_ping_lag", lag_ms=(now_us - sent_us) // 1000)  # ok: cv-ws-no-credential-log
# --- ... ids, a reason code, prose, another receiver
log.info("auth", user_id=user_id, session_id=session_id, connection_id=connection_id)  # ok: cv-ws-no-credential-log
log.warning("auth failed", failure="missing_token")  # ok: cv-ws-no-credential-log
log.warning("authorization header missing")  # ok: cv-ws-no-credential-log
log.info("frame", kind=frame["t"], user=frame["p"]["user_id"], code=frame.get("code"))  # ok: cv-ws-no-credential-log
cache.info("auth", token)  # ok: cv-ws-no-credential-log
catalog.warning("auth", token)  # ok: cv-ws-no-credential-log
bind_context(token=token)  # ok: cv-ws-no-credential-log
_log().warning("auth failed")  # ok: cv-ws-no-credential-log
