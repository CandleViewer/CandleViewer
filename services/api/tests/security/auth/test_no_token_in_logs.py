"""SR-122 end-to-end: no credential reaches any log sink on login -> MFA -> refresh -> step-up.

Drives the REAL `create_app()` HTTP surface (fake repositories only, no network, C-13.5) while
capturing structlog events (`capture_logs`), stdlib `logging` (`caplog`) and stdout/stderr, then
asserts that no captured text contains a session token, refresh token, CSRF/cookie value, TOTP
code, password, recovery code or MFA challenge token. Detection = the `.gitleaks.toml` `cv-*`
secret shapes plus the literal values this test generated (the shape regexes alone would miss
the un-prefixed `token_urlsafe` values the services mint today).
"""

from __future__ import annotations

import logging
import os
import re
import tomllib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.auth.csrf import CSRF_COOKIE
from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_GITLEAKS = Path(__file__).resolve().parents[5] / ".gitleaks.toml"
# Every cv-* rule in .gitleaks.toml; the drift guard at the end of this module enforces it.
_SHAPE_IDS = (
    "cv-session-token",
    "cv-refresh-token",
    "cv-invite-token",
    "cv-recovery-code",
    "cv-totp-secret",
)
_PASSWORD = "pw-canary-7"  # noqa: S105 - test-only literal
_ORIGIN = "https://app.example.test"
_T0 = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "owner", "roles": ["owner"], "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": [], "account_scope": []}


class _Audit:
    async def emit(self, action: str, **kw: Any) -> None:
        return None


def _shape_regexes() -> list[re.Pattern[str]]:
    rules = tomllib.loads(_GITLEAKS.read_text(encoding="utf-8"))["rules"]
    found = {r["id"]: re.compile(r["regex"]) for r in rules if r["id"] in _SHAPE_IDS}
    assert set(found) == set(_SHAPE_IDS), "gitleaks cv-* secret shapes missing"
    return list(found.values())


def _gitleaks_cv_rule_ids() -> list[str]:
    rules = tomllib.loads(_GITLEAKS.read_text(encoding="utf-8"))["rules"]
    return [r["id"] for r in rules if r["id"].startswith("cv-")]


# What the logging module fills in on every record from the clock (`created`, `relativeCreated`),
# the thread (`thread`, `threadName`), the process (`process`) and the asyncio task (`taskName`).
# No log call can put a credential there: `Logger.makeRecord` raises KeyError for an `extra` key
# that is already a record attribute, and none of these is a parameter of the call. Their digits
# differ on every run (`threadName` is `asyncio-portal-<hex id>` in the anyio thread that serves
# the TestClient requests, `taskName` is `Task-<n>`), so a random 6-digit TOTP code spells a run
# of one of them in a small fraction of runs. Scanning them made this test flaky: a false leak
# of `totp_code_1`. `msecs` (`ddd.0`) and `asctime` (`YYYY-MM-DD hh:mm:ss,mmm`) cannot hold a
# 6-digit run, so they stay in the scan with every other attribute.
_STAMPED = frozenset({"created", "relativeCreated", "thread", "threadName", "process", "taskName"})


def _record_texts(record: logging.LogRecord) -> list[str]:
    """A record as the leak check reads it: its message and every attribute but the stamps."""
    supplied = {k: v for k, v in record.__dict__.items() if k not in _STAMPED}
    return [record.getMessage(), repr(supplied)]


class _Sink(logging.Handler):
    """Own root handler: app start-up may reconfigure logging and detach pytest's caplog one."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines += _record_texts(record)


def _collect(
    logs: list[dict[str, Any]], caplog: pytest.LogCaptureFixture, sink: _Sink, out: str
) -> list[str]:
    texts = [repr(e) for e in logs]
    for rec in caplog.records:
        texts.extend(_record_texts(rec))
    texts.append(caplog.text)
    texts.extend(sink.lines)
    texts.append(out)
    return texts


def _leaks(texts: list[str], literals: dict[str, str]) -> list[str]:
    hits: list[str] = []
    shapes = _shape_regexes()
    for text in texts:
        hits += [f"shape:{p.pattern[:20]}" for p in shapes if p.search(text)]
        hits += [name for name, val in literals.items() if val and val in text]
    return hits


def _csrf(response: Any) -> str:
    """The `__Host-cv_csrf` value the server just set (what the web client reads)."""
    token = response.cookies.get(CSRF_COOKIE)
    assert token, "server did not set the SR-041 cookie"
    return str(token)


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Any:
    clock = _Clock()
    monkeypatch.setenv("CV_ALLOWED_ORIGINS", _ORIGIN)
    users, mfa_repo, sessions = FakeUserRepository(), FakeMfaRepository(), FakeSessionRepository()
    pepper = os.urandom(8).hex()

    def _auth(_settings: Any, *, clock: Any = None) -> AuthService:
        mfa: MfaRepository = mfa_repo
        return AuthService(
            users,
            pepper=pepper,
            mfa_repository=mfa,
            totp_encryption_key=os.urandom(32),
            recovery_code_hmac_key=b"r" * 32,
            session_repository=sessions,
            clock=clock,
        )

    monkeypatch.setattr(
        appmod, "build_auth_service", lambda s, *, clock=None: _auth(s, clock=clock)
    )
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _s: _Identity())
    app = appmod.create_app(auth_clock=clock)
    ctx = app.state.app_context
    ctx.audit._writer = _Audit()
    with TestClient(
        app, base_url=_ORIGIN, client=("127.0.0.1", 50000), raise_server_exceptions=False
    ) as client:
        assert client.portal is not None
        client.portal.call(ctx.auth.start, ctx)
        yield client, ctx, users, mfa_repo, clock


def test_login_mfa_refresh_stepup_never_log_a_credential(
    stack: Any, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    client, ctx, users, mfa_repo, clock = stack
    portal = client.portal

    from candleviewer.auth.hashing import Hasher

    hasher = Hasher(pepper=ctx.auth._pepper)
    user = make_user(password_hash=portal.call(hasher.hash, _PASSWORD))
    users.add(user)
    uid = str(user.id)
    mfa = ctx.auth.mfa

    # Enrolment is setup (its one-time secrets are returned to the caller by design); what is
    # under test is that the HTTP flow below never writes them to a log.
    res = portal.call(
        lambda: mfa.enroll(
            uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
        )
    )
    seed = ctx.auth.mfa._encryptor.decrypt(mfa_repo.methods[str(res.method_id)].secret_enc)
    _, recovery_codes = portal.call(
        lambda: mfa.confirm_enrollment(
            uid, method_id=str(res.method_id),
            code=generate_code(seed, time_step_for(clock.now.timestamp()) - 1),
        )
    )  # fmt: skip
    assert recovery_codes

    def code() -> str:
        return generate_code(seed, time_step_for(clock.now.timestamp()))

    literals: dict[str, str] = {"password": _PASSWORD, "totp_seed_b32": res.secret_base32 or ""}
    structlog.reset_defaults()
    caplog.set_level(logging.DEBUG)
    sink = _Sink()
    root = logging.getLogger()
    root.addHandler(sink)
    root_level = root.level
    root.setLevel(logging.DEBUG)
    with capture_logs() as logs:
        # 1. login
        r = client.post("/auth/login", json={"identifier": "basiltt", "password": _PASSWORD})
        assert r.status_code == 200, r.text
        mfa_token = r.json()["mfa_token"]
        literals["mfa_token"] = mfa_token
        # 2. MFA verify -> session
        totp = code()
        literals["totp_code_1"] = totp
        r = client.post(
            "/auth/mfa/verify", json={"mfa_token": mfa_token, "method": "totp", "code": totp}
        )
        assert r.status_code == 200, r.text
        access = r.json()["tokens"]["access_token"]
        refresh_cookie = r.cookies.get("cv_refresh")
        assert access and refresh_cookie
        literals.update(access_token=access, refresh_cookie=refresh_cookie)
        csrf1 = _csrf(r)
        literals["csrf_token_1"] = csrf1
        # SR-041 refusal path (tampered MAC) must not log the token either
        tampered = csrf1[:-2] + ("AA" if not csrf1.endswith("AA") else "BB")
        literals["csrf_tampered"] = tampered
        r = client.post("/auth/logout", headers={"Authorization": f"Bearer {access}",
                        "X-CSRF-Token": tampered}, cookies={CSRF_COOKIE: tampered})  # fmt: skip
        assert r.status_code == 403 and r.json()["code"] == "csrf_token_invalid"
        assert tampered not in r.text and csrf1 not in r.text
        # 3. refresh (cookie path with Origin = CSRF guard, then body path)
        r = client.post("/auth/refresh", headers={"Origin": _ORIGIN, "X-CSRF-Token": csrf1},
                        cookies={"cv_refresh": refresh_cookie})  # fmt: skip
        assert r.status_code == 200, r.text
        access2 = r.json()["tokens"]["access_token"]
        refresh2 = r.cookies.get("cv_refresh")
        assert refresh2 and refresh2 != refresh_cookie
        literals.update(access_token_2=access2, refresh_cookie_2=refresh2)
        csrf2 = _csrf(r)
        assert csrf2 != csrf1  # rotated with the session
        literals["csrf_token_2"] = csrf2
        r = client.post("/auth/refresh", json={"refresh_token": refresh2},
                        headers={"X-CSRF-Token": csrf2})  # fmt: skip
        assert r.status_code == 200, r.text
        access3 = r.json()["tokens"]["access_token"]
        refresh3 = r.json()["tokens"]["refresh_token"]
        literals.update(access_token_3=access3, refresh_token_3=refresh3)
        literals["csrf_token_3"] = _csrf(r)
        # a replayed (rotated) refresh token exercises the reuse-detection log path
        r = client.post("/auth/refresh", json={"refresh_token": refresh2},
                        headers={"X-CSRF-Token": csrf2}, cookies={CSRF_COOKIE: csrf2})  # fmt: skip
        assert r.status_code == 401
        # 4. step-up needs a live session: mint one afresh via a second login + a new TOTP step
        clock.now += timedelta(seconds=60)
        r = client.post("/auth/login", json={"identifier": "basiltt", "password": _PASSWORD})
        mfa_token2 = r.json()["mfa_token"]
        literals["mfa_token_2"] = mfa_token2
        totp2 = code()
        literals["totp_code_2"] = totp2
        r = client.post(
            "/auth/mfa/verify", json={"mfa_token": mfa_token2, "method": "totp", "code": totp2}
        )
        assert r.status_code == 200, r.text
        access4 = r.json()["tokens"]["access_token"]
        literals["access_token_4"] = access4
        csrf4 = _csrf(r)
        literals["csrf_token_4"] = csrf4
        clock.now += timedelta(seconds=60)
        totp3 = code()
        literals["totp_code_3"] = totp3
        r = client.post(
            "/auth/step-up",
            headers={"Authorization": f"Bearer {access4}", "X-CSRF-Token": csrf4},
            json={"code": totp3, "password": _PASSWORD, "action_class": "users"},
        )
        assert r.status_code == 200, r.text
        # failing step-up (wrong password) must not echo the attempted secrets either
        r = client.post(
            "/auth/step-up",
            headers={"Authorization": f"Bearer {access4}", "X-CSRF-Token": csrf4},
            json={
                "code": "000000",
                "password": "pw-wrong-7",
                "action_class": "users",
            },
        )
        assert r.status_code in (401, 429)
        literals["wrong_password"] = "pw-wrong-7"  # noqa: S105
        # 5. recovery-code login path
        clock.now += timedelta(seconds=60)
        r = client.post("/auth/login", json={"identifier": "basiltt", "password": _PASSWORD})
        mfa_token3 = r.json()["mfa_token"]
        literals["mfa_token_3"] = mfa_token3
        literals["recovery_code"] = recovery_codes[0]
        r = client.post(
            "/auth/mfa/recovery",
            json={"mfa_token": mfa_token3, "recovery_code": recovery_codes[0]},
        )
        assert r.status_code == 200, r.text
        # wrong password / wrong code failure paths
        client.post("/auth/login", json={"identifier": "basiltt", "password": "pw-bad-7"})
        literals["bad_login_password"] = "pw-bad-7"  # noqa: S105

    root.removeHandler(sink)
    root.setLevel(root_level)
    out = capfd.readouterr()
    texts = _collect(logs, caplog, sink, out.out + out.err)
    assert _leaks(texts, literals) == []
    assert all(
        len(v) >= 6 for v in literals.values() if v
    )  # guard: literals are not trivially short
    assert uuid.UUID(uid)  # keep the user id (not a secret) out of the literal set


@pytest.mark.parametrize("rule_id", _gitleaks_cv_rule_ids())
def test_leak_check_applies_every_gitleaks_cv_rule(rule_id: str) -> None:
    assert rule_id in _SHAPE_IDS, f"{rule_id} is in .gitleaks.toml but not in _SHAPE_IDS"


# A 6-digit TOTP code, as `generate_code` returns it; the stamps below are built to spell it.
_CODE = "209734"
_CAPTURES = ("sink", "caplog")  # the two stdlib log captures the real test reads


def _record(
    msg: str = "ok", args: tuple[object, ...] = (), exc_info: Any = None, **extra: object
) -> logging.LogRecord:
    """The record `logger.info(msg, *args, exc_info=..., extra=extra)` builds, minus the logger."""
    record = logging.LogRecord("cv.test", logging.INFO, __file__, 1, msg, args, exc_info)
    record.__dict__.update(extra)
    return record


def _leaks_in(
    capture: str, record: logging.LogRecord, caplog: pytest.LogCaptureFixture
) -> list[str]:
    """Hand `record` to both stdlib captures, then run the leak check on one of them."""
    sink = _Sink()
    sink.handle(record)
    caplog.handler.handle(record)
    texts = sink.lines if capture == "sink" else _collect([], caplog, _Sink(), "")
    return _leaks(texts, {"totp_code_1": _CODE})


@pytest.mark.parametrize("capture", _CAPTURES)
@pytest.mark.parametrize(
    ("attr", "stamp"),
    [
        pytest.param("created", float(f"1792114514.{_CODE}"), id="created"),
        pytest.param("relativeCreated", float(f"1767.{_CODE}"), id="relative-created"),
        pytest.param("thread", int(f"1334{_CODE}"), id="thread"),
        pytest.param("threadName", f"asyncio-portal-7f{_CODE}ab", id="thread-name"),
        pytest.param("process", int(_CODE), id="process"),
        pytest.param("taskName", f"Task-{_CODE}", id="task-name"),
    ],
)
def test_leak_check_ignores_a_runtime_stamp_that_happens_to_spell_the_code(
    attr: str, stamp: object, capture: str, caplog: pytest.LogCaptureFixture
) -> None:
    record = _record()
    setattr(record, attr, stamp)
    assert _CODE in repr(record.__dict__)  # the stamp really does spell the code
    assert _leaks_in(capture, record, caplog) == []


@pytest.mark.parametrize("capture", _CAPTURES)
@pytest.mark.parametrize(
    "carried",
    [
        pytest.param({"msg": f"verified {_CODE}"}, id="message"),
        pytest.param({"msg": "verified %s", "args": (_CODE,)}, id="argument"),
        pytest.param({"otp": _CODE}, id="extra-attribute"),
        pytest.param({"exc_info": (ValueError, ValueError(_CODE), None)}, id="exception"),
    ],
)
def test_leak_check_still_flags_the_code_when_the_log_call_carried_it(
    carried: dict[str, Any], capture: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert "totp_code_1" in _leaks_in(capture, _record(**carried), caplog)


@pytest.mark.parametrize("attr", sorted(_STAMPED))
def test_no_log_call_can_write_a_stamped_attribute(attr: str) -> None:
    logger = logging.getLogger("cv.test")

    with pytest.raises(KeyError, match=attr):
        logger.makeRecord("cv.test", logging.INFO, __file__, 1, "ok", (), None, extra={attr: "x"})
