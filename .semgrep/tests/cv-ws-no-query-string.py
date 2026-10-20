"""Fixtures for cv-ws-no-query-string (E17-X02): no code in `ws/` reads the upgrade's query string.
`todoruleid` marks an accepted miss, `todook` an accepted false positive (Known limits).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

import typing
import urllib.parse
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

import fastapi
import starlette.websockets
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, Query, Security, WebSocket
from starlette.datastructures import URL, QueryParams
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocket as SWS

router = APIRouter()
WS_PATH = "/ws"


async def reads_bad(ws: WebSocket, token: str = Query(None)):  # ruleid: cv-ws-no-query-string
    ws.query_params.get("token")  # ruleid: cv-ws-no-query-string
    ws.url.query  # ruleid: cv-ws-no-query-string
    ws.url.components.query  # ruleid: cv-ws-no-query-string
    ws.scope["query_string"]  # ruleid: cv-ws-no-query-string
    ws.scope.get("query_string", b"")  # ruleid: cv-ws-no-query-string
    QueryParams(b"token=x")  # ruleid: cv-ws-no-query-string
    parse_qs("token=x")  # ruleid: cv-ws-no-query-string
    urllib.parse.parse_qsl("token=x")  # ruleid: cv-ws-no-query-string
    ws.scope["query_string"] = ws.scope["query_string"].replace(b"token=x", b"")  # ruleid: cv-ws-no-query-string
    scope = ws.scope
    scope["query_string"]  # ruleid: cv-ws-no-query-string
    urlsplit(str(ws.url)).query  # todoruleid: cv-ws-no-query-string
    str(ws.url)  # todoruleid: cv-ws-no-query-string
    log.info("connect", url=ws.url)  # todoruleid: cv-ws-no-query-string
    URL(scope=ws.scope).query  # todoruleid: cv-ws-no-query-string
    url = ws.url
    url.query  # todoruleid: cv-ws-no-query-string
    ws.url.components[3]  # todoruleid: cv-ws-no-query-string
    getattr(ws, "query_params")  # todoruleid: cv-ws-no-query-string
    ws.scope[KEY]  # todoruleid: cv-ws-no-query-string
    ws.scope.pop("query_string", None)  # todoruleid: cv-ws-no-query-string
    ws.scope.setdefault("query_string", b"")  # todoruleid: cv-ws-no-query-string
    ws.scope.items()  # todoruleid: cv-ws-no-query-string
    {**ws.scope}  # todoruleid: cv-ws-no-query-string
    fastapi.params.Query(None)  # todoruleid: cv-ws-no-query-string
    (ws.query_params and ws.scope)["query_string"] = b""  # todoruleid: cv-ws-no-query-string


def query_of(url: URL) -> str:
    return url.query  # todoruleid: cv-ws-no-query-string


async def reads_ok(ws: WebSocket):
    origin = dict(ws.scope["headers"]).get(b"origin")  # ok: cv-ws-no-query-string
    protocols = ws.scope.get("subprotocols") or ()  # ok: cv-ws-no-query-string
    path = ws.url.path  # ok: cv-ws-no-query-string
    ws.scope["query_string"] = b""  # ok: cv-ws-no-query-string
    ws.scope["query_string"] = bytes()  # todook: cv-ws-no-query-string
    del ws.scope["query_string"]  # todook: cv-ws-no-query-string
    return origin, protocols, path, ws.scope["client"]  # ok: cv-ws-no-query-string


@router.websocket("/ws")
async def defaulted_bad(conn: WebSocket, token: str | None = None): ...  # ruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def required_bad(conn: WebSocket, limit: int): ...  # ruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def with_a_dependency_bad(conn: WebSocket, u: U = Depends(f), n: int = 3): ...  # ruleid: cv-ws-no-query-string
@router.websocket(path="/ws")
async def path_keyword_bad(conn: WebSocket, token: str | None = None): ...  # ruleid: cv-ws-no-query-string
@router.api_websocket_route("/ws")
async def api_route_bad(conn: WebSocket, token: str | None = None): ...  # ruleid: cv-ws-no-query-string
@router.websocket(WS_PATH)
async def constant_path_bad(conn: WebSocket, token: str | None = None): ...  # ruleid: cv-ws-no-query-string
@router.websocket("/ws", name="ws_main")
async def extra_argument_bad(conn: WebSocket, token: str | None = None): ...  # ruleid: cv-ws-no-query-string
@router.websocket(name="ws_main", path="/ws", dependencies=[])
async def path_among_arguments_bad(conn: WebSocket, token: str | None = None): ...  # ruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def wrapped_plain_annotated_bad(conn: WebSocket, n: Annotated[  # ruleid: cv-ws-no-query-string
    int, Field(ge=1)
]): ...
@router.websocket("/ws")
async def websocket_state_bad(conn: WebSocketState): ...  # ruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def other_metadata_bad(conn: WebSocket, u: Annotated[U, MyDepends(f)]): ...  # ruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def wrapped_signature_bad(
    conn: WebSocket,
    u: Annotated[  # ok: cv-ws-no-query-string
        U, Depends(f)
    ],
    limit  # ruleid: cv-ws-no-query-string
    : int | None = None,
): ...
@router.websocket("/ws")
async def websocket_only_ok(conn: WebSocket): ...  # ok: cv-ws-no-query-string
@router.websocket(WS_PATH)
async def constant_path_ok(conn: starlette.websockets.WebSocket): ...  # ok: cv-ws-no-query-string
@router.websocket("/ws")
async def dependencies_ok(conn: WebSocket, user: U = Depends(f), sec: S = Security(g)): ...  # ok: cv-ws-no-query-string
@router.websocket(path="/ws")
async def path_keyword_dependency_ok(conn: WebSocket, u: U = Depends(f)): ...  # ok: cv-ws-no-query-string
@router.api_websocket_route("/ws")
async def api_route_security_ok(conn: WebSocket, u: U = Security(g)): ...  # ok: cv-ws-no-query-string
@router.websocket("/ws")
async def annotated_ok(conn: WebSocket, u: Annotated[U, Depends(f)]): ...  # ok: cv-ws-no-query-string
@router.websocket("/ws")
async def annotated_forms_ok(conn: WebSocket, u: typing.Annotated[U, Depends(f)], v: Annotated[V, Security(g)]): ...  # ok: cv-ws-no-query-string
@router.websocket("/ws/{room}")
async def path_parameter_ok(conn: WebSocket, room: str): ...  # ok: cv-ws-no-query-string
@router.get("/ws")
async def http_route_ok(conn: WebSocket, token: str | None = None): ...  # ok: cv-ws-no-query-string
@router.websocket("/ws")
async def unannotated_misses(conn: WebSocket, token=None): ...  # todoruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def name_in_the_route_misses(conn: WebSocket, s: str = ""): ...  # todoruleid: cv-ws-no-query-string
@router.websocket(settings.token_path)
async def name_in_the_route_text_misses(conn: WebSocket, token: str = ""): ...  # todoruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def keyword_arguments_miss(conn: WebSocket, **kwargs: str): ...  # todoruleid: cv-ws-no-query-string
ws_route = router.websocket
@ws_route("/ws")
async def decorator_alias_misses(conn: WebSocket, token: str | None = None): ...  # todoruleid: cv-ws-no-query-string
async def registered_by_a_call(conn: WebSocket, token: str | None = None): ...  # todoruleid: cv-ws-no-query-string
router.add_api_websocket_route("/ws", registered_by_a_call)
async def a_dependency(conn: WebSocket, token: str | None = None): ...  # todoruleid: cv-ws-no-query-string
@router.websocket("/ws")
async def header_or_cookie(conn: WebSocket, t: str = Header(), c: str = Cookie()): ...  # todook: cv-ws-no-query-string
@router.websocket("/ws")
async def other_dependency_forms(conn: WebSocket, user: CurrentUser, u: U = fastapi.Depends(f)): ...  # todook: cv-ws-no-query-string
@router.websocket("/ws")
async def framework_parameters(conn: "WebSocket", tasks: BackgroundTasks, hc: HTTPConnection): ...  # todook: cv-ws-no-query-string
@router.websocket("/ws")
async def aliased_websocket(websocket: SWS): ...  # todook: cv-ws-no-query-string
