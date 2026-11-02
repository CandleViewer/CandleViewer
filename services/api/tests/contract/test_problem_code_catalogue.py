"""Every REST error answers a catalogued `code` with `type == ERRORS_BASE + code` (#2828).

`Problem.code` must come from the `x-error-codes` catalogue of `22-api-openapi.yaml` and
`Problem.type` is `https://candleviewer.local/errors/{code}`. `about:blank` is a valid
`format: uri`, so schema validation alone never catches it: every layer below asserts the pair
explicitly. Four layers:

1. a static AST scan of `candleviewer/` for an `"about:blank"` literal or a literal code outside
   the catalogue (problem-shaped dicts, `code=` keywords, snake-case literals passed to a
   `*problem*` callable, `RuleError`'s code argument, `…/errors/<slug>` URIs);
2. a walk over every served route of the real `create_app()` world, unauthenticated and as the
   owner, checking every `>= 400` answer;
3. every registered exception handler, called directly;
4. the shared helper refuses a WS-only code.

Deferred (BQ-07, ruled on #2828, recorded in the PR body): FastAPI's own `{"detail": …}` bodies,
the `deny_by_default` fall-through 403 and the router's unmatched 404 / 405, have no problem
handler yet. The walk skips exactly those named bodies and the handler layer skips exactly
FastAPI's default `HTTPException` / WebSocket handlers; anything else must conform.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.exceptions import RequestValidationError, WebSocketRequestValidationError
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

from candleviewer.admin.http import AdminAreaRefused
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import PUBLIC_OPERATIONAL_ROUTES, served_operations
from candleviewer.api.problems import ERRORS_BASE, problem, problem_body
from candleviewer.api.view_as_subject import ViewAsUnstamped
from candleviewer.statechart.gateway import GatewayDegradedError, GatewayOverloadedError
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract.rbac.rbac_harness import World, bearer, build_world, fill_path

SPEC: dict[str, Any] = load_openapi_spec()
REST_CODES = frozenset(str(e["code"]) for e in SPEC["x-error-codes"])
WS_CODES = frozenset(str(e["code"]) for e in SPEC["x-error-codes-ws"]) | REST_CODES
PACKAGE = Path(__file__).resolve().parents[2] / "candleviewer"
_ERRORS_URI = "https://candleviewer.local/errors/"
_SLUG = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")
_PROBLEM_KEYS = frozenset({"type", "title", "status"})
_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})
#: A `*problem*` callable whose literal argument is another closed `Problem` member, not a code.
_MEMBER_ARGS = {
    "session_revoked_problem": frozenset(
        SPEC["components"]["schemas"]["Problem"]["properties"]["revoked_reason"]["enum"]
    ),
}
#: BQ-07 (deferred): FastAPI's non-problem bodies, skipped by name and nothing else.
_DEFERRED_BODIES = (
    (403, {"detail": "forbidden"}),  # deny_by_default's fall-through
    (404, {"detail": "Not Found"}),  # no route matched
    (405, {"detail": "Method Not Allowed"}),
)
_DEFERRED_HANDLERS = (StarletteHTTPException, WebSocketRequestValidationError)
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


# --- 1. static scan ------------------------------------------------------------------------------


def _docstrings(tree: ast.AST) -> set[int]:
    """`id`s of the constants that are bare expression statements (docstrings, notes)."""
    return {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }


def _name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_codes(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, code) for every literal the module states as a problem code."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            keys = {_str(k): v for k, v in zip(n.keys, n.values, strict=True) if _str(k)}
            code = _str(keys.get("code"))
            if code is not None and _PROBLEM_KEYS & keys.keys():
                yield n.lineno, code
        elif isinstance(n, ast.Call):
            name = _name(n.func)
            logged = isinstance(n.func, ast.Attribute) and name in _LOG_METHODS
            for kw in n.keywords:  # a log call's `code=` is a log field, not an answer
                if kw.arg == "code" and (code := _str(kw.value)) is not None and not logged:
                    yield n.lineno, code
            if "problem" in name.lower():
                for arg in n.args:
                    text = _str(arg)
                    if text and _SLUG.fullmatch(text) and text not in _MEMBER_ARGS.get(name, ()):
                        yield n.lineno, text
            if name == "RuleError" and len(n.args) >= 2 and (text := _str(n.args[1])):
                yield n.lineno, text
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            if n.value.startswith(_ERRORS_URI) and len(n.value) > len(_ERRORS_URI):
                yield n.lineno, n.value[len(_ERRORS_URI) :]


def scan(root: Path) -> list[str]:
    """`file:line message` for every violation under `root` (a `candleviewer/` tree). A module
    under `ws/` may also state a WS code (its error frames); every other module states REST codes
    only."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "_generated" in path.parts:
            continue
        rel = path.relative_to(root.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        notes = _docstrings(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and n.value == "about:blank" and id(n) not in notes:
                found.append(f"{rel}:{n.lineno} about:blank")
        allowed = WS_CODES if path.relative_to(root).parts[0] == "ws" else REST_CODES
        for line, code in _literal_codes(tree):
            if code not in allowed:
                found.append(f"{rel}:{line} code {code!r} is not in the catalogue")
    return found


def test_no_module_states_about_blank_or_an_uncatalogued_code() -> None:
    assert scan(PACKAGE) == []


def test_the_scan_sees_each_shape_it_guards(tmp_path: Path) -> None:
    """The scanner's own negative control: each guarded shape is reported, docstrings are not."""
    pkg = tmp_path / "candleviewer"
    (pkg / "api").mkdir(parents=True)
    (pkg / "api" / "bad.py").write_text(
        '"""A note may say about:blank."""\n'
        'A = {"type": "about:blank", "title": "t", "status": 503}\n'
        'B = {"title": "t", "code": "service_unavailable"}\n'
        'f(code="unauthorized")\n'
        '_problem(503, "service_unavailable", "Service unavailable")\n'
        'RuleError(409, "name_taken", "x")\n'
        'C = "https://candleviewer.local/errors/invalid_code"\n'
        'D = {"title": "t", "code": "not_found"}\n',
        encoding="utf-8",
    )
    lines = [hit.split(" ", 1)[0].rsplit(":", 1)[1] for hit in scan(pkg)]
    assert lines == ["2", "3", "4", "5", "6", "7"]


# --- 2. route walk -------------------------------------------------------------------------------


def _problem_validator() -> Draft202012Validator:
    base = "urn:cv:openapi"
    resource = Resource.from_contents(SPEC, default_specification=DRAFT202012)
    return Draft202012Validator(
        {"$ref": f"{base}#/components/schemas/Problem"},
        registry=Registry().with_resource(base, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


_VALIDATOR = _problem_validator()


def _violations(where: str, status: int, content_type: str, raw: bytes) -> list[str]:
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    if (status, body) in _DEFERRED_BODIES:
        return []
    if not isinstance(body, dict) or not content_type.startswith("application/problem+json"):
        return [f"{where}: {status} is not a problem ({content_type!r}, {raw[:120]!r})"]
    out = [f"{where}: {status} {err.message}" for err in _VALIDATOR.iter_errors(body)]
    code = body.get("code")
    if code not in REST_CODES:
        out.append(f"{where}: {status} code {code!r} is not a REST catalogue code")
    if body.get("type") != f"{ERRORS_BASE}{code}":
        out.append(f"{where}: {status} type {body.get('type')!r} is not the code's URI")
    if body.get("status") != status:
        out.append(f"{where}: body status {body.get('status')!r} != HTTP {status}")
    return out


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    """The RBAC pack's real-app world; its patches are undone at module teardown (C-13.7)."""
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp, bars_state_root=tmp_path_factory.mktemp("bars-state"))
    finally:
        mp.undo()


def test_every_route_answers_catalogued_problems(world: World) -> None:
    operations = sorted(
        op for op in served_operations(world.app) if op[1] not in PUBLIC_OPERATIONAL_ROUTES
    )
    assert operations, "the walk reached no route"
    failures: list[str] = []
    refused: dict[str, int] = {}
    codes: set[str] = set()
    for actor in ("unauthenticated", "owner"):
        refused[actor] = 0
        for method, path in operations:
            kwargs: dict[str, Any] = {"headers": bearer(actor)}
            if method in _BODY_METHODS:
                kwargs["json"] = {}
            answer = world.client.request(method, fill_path(path), **kwargs)
            if answer.status_code >= 400:
                refused[actor] += 1
                try:
                    codes.add(str(answer.json().get("code")))
                except (ValueError, AttributeError):
                    pass
                ctype = answer.headers.get("content-type", "")
                failures += _violations(
                    f"{actor} {method} {path}", answer.status_code, ctype, answer.content
                )
    assert failures == []
    # A floor, so a walk that stops reaching the routers cannot pass vacuously.
    assert all(n >= 1 for n in refused.values()), f"an actor saw no >=400 answer: {refused}"
    assert len(codes) >= 5, f"the walk saw only {sorted(codes)}"


# --- 3. exception handlers -----------------------------------------------------------------------

_VALIDATION = [{"loc": ("body", "x"), "type": "missing", "msg": "Field required", "input": {}}]
#: One or more instances per handled type; a new handler must be added here (or deferred above).
_RAISED: dict[type[BaseException], Callable[[], list[BaseException]]] = {
    RequestValidationError: lambda: [RequestValidationError(_VALIDATION)],
    GatewayOverloadedError: lambda: [GatewayOverloadedError("m1", "order")],
    GatewayDegradedError: lambda: [GatewayDegradedError("m1", "order")],
    AdminAreaRefused: lambda: [AdminAreaRefused(s, "refused") for s in (401, 403, 500, 501, 503)],
    ViewAsUnstamped: lambda: [ViewAsUnstamped()],
    Exception: lambda: [Exception("boom"), RuntimeError("boom")],
}


async def _handled(handler: Any, request: Request, exc: BaseException) -> Response:
    answered = handler(request, exc)
    return cast(Response, await answered if inspect.isawaitable(answered) else answered)


def test_every_exception_handler_answers_catalogued_problems(world: World) -> None:
    handlers = {
        key: handler
        for key, handler in world.app.exception_handlers.items()
        if key not in _DEFERRED_HANDLERS
    }
    assert set(handlers) == set(_RAISED), "an exception handler is not covered by this test"
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
    request = Request({**scope, "app": world.app})
    failures: list[str] = []
    for key, handler in handlers.items():
        assert isinstance(key, type)
        for exc in _RAISED[key]():
            answer = asyncio.run(_handled(handler, request, exc))
            ctype = answer.headers.get("content-type", "")
            where = f"{handler.__qualname__}({type(exc).__name__})"
            failures += _violations(where, answer.status_code, ctype, bytes(answer.body))
    assert failures == []


# --- 4. the helper -------------------------------------------------------------------------------


_WS_ONLY = sorted(c for c in ErrorCode if "rest" not in ERROR_META[c].surfaces)


@pytest.mark.parametrize("code", _WS_ONLY)
def test_the_helper_refuses_a_ws_only_code(code: ErrorCode) -> None:
    with pytest.raises(ValueError, match="not a REST error code"):
        problem(code, 400)


def test_the_helper_builds_the_code_uri_with_the_status_given() -> None:
    body = problem_body(ErrorCode.VALIDATION_FAILED, 422, "bad", rule="name_taken")
    assert body == {
        "type": "https://candleviewer.local/errors/validation_failed",
        "title": ERROR_META[ErrorCode.VALIDATION_FAILED].title,
        "status": 422,
        "code": "validation_failed",
        "detail": "bad",
        "errors": [{"rule": "name_taken"}],
    }
    answer = problem(ErrorCode.LIFECYCLE_UNAVAILABLE, 503, headers={"Retry-After": "1"})
    assert answer.headers["retry-after"] == "1"
    assert answer.headers["content-type"] == "application/problem+json"
    assert _violations("helper", 503, "application/problem+json", bytes(answer.body)) == []


def test_the_helper_refuses_a_non_error_status() -> None:
    with pytest.raises(ValueError, match="not an error status"):
        problem(ErrorCode.CONFLICT, 200)
