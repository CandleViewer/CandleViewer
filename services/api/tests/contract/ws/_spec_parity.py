"""`runtime_spec_parity` for the WS surface (#572, 23-ws-protocol.md section 16.5).

The document is the source of truth (C-6.1), so a number or a name that the running gateway and
`23-ws-protocol.md` state differently is drift, and the code moves to match. This module is the
pure half: readers of the document's tables, the registries that map a documented row to the code
that enforces it, and the failure text. `test_ws_spec_parity.py` drives it, with the running
gateway (the E17-Q01 harness) as the runtime side; no compose stack and no network.

A table that is not as expected is an assertion failure, never a skipped row
(`_doc.strict_table`), and a limit with no row is a failure too (`limits_without_a_doc_row`)."""

from __future__ import annotations

import ast
import importlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from tests.contract.ws import _doc
from tests.contract.ws._doc import Row, Section

_REPO: Final = Path(__file__).resolve().parents[5]
_WS: Final = _REPO / "services" / "api" / "candleviewer" / "ws"
_ABSENT: Final = "absent"


@dataclass(frozen=True)
class Drift:
    """One value the document and the running gateway state differently."""

    surface: str
    key: str
    doc: Any
    runtime: Any
    where: str


def render(drifts: Sequence[Drift]) -> str:
    lines = [
        f"[runtime_spec_parity ws] {d.surface}.{d.key}: runtime {d.runtime}, {d.where} says {d.doc}"
        for d in drifts
    ]
    lines.append(
        "The document is the source of truth (C-6.1): change the document in the same PR, "
        "or revert the code."
    )
    return "\n".join(lines)


def diff(
    surface: str, doc: Mapping[str, Any], runtime: Mapping[str, Any], where: Callable[[str], str]
) -> list[Drift]:
    """Every key whose documented and runtime values differ, or that only one side has."""
    return [
        Drift(surface, key, doc.get(key, _ABSENT), runtime.get(key, _ABSENT), where(key))
        for key in sorted(set(doc) | set(runtime))
        if doc.get(key, _ABSENT) != runtime.get(key, _ABSENT)
    ]


def numbers(cell: str) -> list[float]:
    """The quantities a cell states, in order and in base units (`256 KiB` is 262144). References
    (`§4.4`, `SR-E12-07`, `#2176`, a ticket key such as E21-X02), code spans and a bracket's
    reasoning are not quantities."""
    text = cell.replace("2\u00b3\u00b2\u22121", str(2**32 - 1)).replace("\u202f", " ")
    text = re.sub(
        r"`[^`]*`|§\s?[\d.]+|SR-[A-Z0-9-]+|\bE\d{2}-[A-Z]\d{2}\b|#\d+|\([^)]*§[^)]*\)", " ", text
    )
    units = {"KiB": 1024, "MiB": 1024**2}
    return [
        int(m[1].replace(" ", "")) * units.get(m[2] or "", 1)
        for m in re.finditer(r"(\d[\d ]*\d|\d)(?:\s*(KiB|MiB))?(?![\w])", text)
    ]


def constant(ref: str) -> Any:
    """`module.NAME`: a constant of `candleviewer.ws.<module>`."""
    module, _, name = ref.rpartition(".")
    return getattr(importlib.import_module(f"candleviewer.ws.{module}"), name)


def _schema(name: str) -> Any:
    from tests.contract.ws._harness import SCHEMAS

    return SCHEMAS[f"cv://ws/v1/{name}.schema.json"]


# --- welcome.limits (4.2, 16.2) ----------------------------------------------------------------

#: `welcome.limits` key -> the 16.2 row that states it again, and the constant that enforces it.
LIMIT_KEYS: Final = {
    "max_subscriptions": ("Max subscriptions / connection", "limits.MAX_SUBSCRIPTIONS"),
    "max_topics_per_request": ("Max topics / `sub` frame", "limits.MAX_TOPICS_PER_SUB"),
    "max_inbound_frame_bytes": ("Max inbound frame", "limits.MAX_INBOUND_FRAME_BYTES"),
    "max_outbound_frame_bytes": ("Max outbound frame", "limits.MAX_OUTBOUND_FRAME_BYTES"),
    "min_throttle_ms": ("Min throttle", "limits.MIN_THROTTLE_MS"),
    "max_symbols_per_connection": ("Max symbols / connection", "limits.MAX_SYMBOLS_PER_CONNECTION"),
}


def _limits_section() -> Section:
    return _doc.section("### 4.2 ", "### 4.3 ")


def documented_limits() -> dict[str, Row]:
    """The normative `welcome.limits` table of 4.2, by key."""
    columns = ("Key", "Value", "Unit", "Enforced as")
    rows = _doc.strict_table(_limits_section(), columns, "23 section 4.2 limits table")
    return {r.cells[0].strip("`"): r for r in rows}


def documented_limit_values() -> dict[str, int]:
    return {key: _doc.first_number(row.cells[1]) for key, row in documented_limits().items()}


def section_16_2() -> dict[str, Row]:
    """The limits summary of 16.2, by its `Limit` cell."""
    sec = _doc.section("### 16.2 Limits summary", "### 16.3 ")
    return {r.cells[0]: r for r in _doc.strict_table(sec, ("Limit", "Value"), "23 section 16.2")}


def limits_drifts(runtime: Mapping[str, int]) -> list[Drift]:
    """What `welcome` advertises against the 4.2 table; a drift names the 16.2 row repeating it."""
    doc, rows = documented_limits(), section_16_2()

    def where(key: str) -> str:
        row, also = doc.get(key), rows.get(LIMIT_KEYS.get(key, ("",))[0])
        text = f"23-ws-protocol.md section 4.2 (line {row.line})" if row else "section 4.2"
        return text + (
            f", also section 16.2 row {also.cells[0]!r} (line {also.line})" if also else ""
        )

    return diff("welcome.limits", documented_limit_values(), runtime, where)


def enforced_limits() -> dict[str, int]:
    """The constants that enforce each advertised limit."""
    return {key: int(constant(ref)) for key, (_, ref) in LIMIT_KEYS.items()}


def limit_renderings_drifts() -> list[Drift]:
    """The 4.2 table, its welcome example and 16.2 state the six limits alike."""
    table, text = documented_limit_values(), _limits_section().text
    block = re.search(r'"limits": \{(.*?)\}', text, re.S)
    assert block, "23 section 4.2 no longer has a welcome example with limits"
    example = {k: int(v) for k, v in re.findall(r'"(\w+)":\s*(\d+)', block[1])}
    drifts = diff("welcome.limits.example", table, example, lambda key: "the 4.2 example")
    rows = section_16_2()
    for key, (label, _) in LIMIT_KEYS.items():
        stated = numbers(rows[label].cells[1])[0] if label in rows else _ABSENT
        if table.get(key) != stated:
            drifts.append(Drift("welcome.limits.16_2", key, table.get(key), stated, label))
    return drifts


# --- 16.2 and 3.6 -------------------------------------------------------------------------------


def _cap(family: str, option: str) -> Callable[[], float]:
    from candleviewer.ws.topics import FAMILIES

    return lambda: FAMILIES[family].options[option].hi or 0


def _items(family: str, option: str) -> Callable[[], float]:
    from candleviewer.ws.topics import FAMILIES

    return lambda: FAMILIES[family].options[option].max_items or 0


def _instance_cap(name: str) -> Callable[[], float]:
    """A cap of the indicator engine (`orderflow/indicators/limits.py`), which the gateway asks."""
    return lambda: getattr(
        importlib.import_module("candleviewer.orderflow.indicators.limits"), name
    )


def _heatmap(name: str) -> Callable[[], float]:
    """A bound of the heatmap producer (`orderflow/heatmap.py`, #605), which the gateway asks."""
    return lambda: getattr(importlib.import_module("candleviewer.orderflow.heatmap"), name)


def _unthrottled() -> float:
    from candleviewer.ws.topics import FAMILIES

    return min(f.default_throttle_ms for f in FAMILIES.values() if f.never_throttled)


#: Each 16.2 row by its `Limit` cell: the quantities its `Value` cell states, in order, as the
#: constants that enforce them (`module.NAME`, space-separated; a callable where there is no one).
LIMIT_ROWS: Final[dict[str, str | Sequence[str | Callable[[], float]]]] = {
    "Max subscriptions / connection": "limits.MAX_SUBSCRIPTIONS",
    "Max topics / `sub` frame": "limits.MAX_TOPICS_PER_SUB",
    "Max topics / `unsub` frame": "limits.MAX_TOPICS_PER_SUB",
    "Max symbols / connection": "limits.MAX_SYMBOLS_PER_CONNECTION",
    "Max `bars.*` / connection": "limits.MAX_BARS_SUBSCRIPTIONS",
    "Max deep `book.*` / connection": "limits.MAX_DEEP_BOOK_SUBSCRIPTIONS "
    "limits.DEEP_BOOK_MIN_DEPTH",
    # #605 (E21-T02): the spec caps (G-02) and the snapshot column cap (G-03); the server row's
    # second quantity is its "x 16 B", a kind-6 row.
    "Max `heatmap.*` specs / symbol": [_heatmap("HEATMAP_MAX_SPECS_PER_SYMBOL")],
    "Max `heatmap.*` specs / server": [
        _heatmap("HEATMAP_MAX_SPECS_PER_SERVER"),
        _heatmap("ROW_BYTES"),
    ],
    "`heatmap` snapshot bound": [_heatmap("HEATMAP_SNAPSHOT_MAX_COLUMNS")],
    "`indicators` server instances": [
        _items("indicators", "instances"),
        _instance_cap("INSTANCE_CAP_PER_USER"),
        _instance_cap("INSTANCE_CAP_PER_SYMBOL"),
        _instance_cap("INSTANCE_CAP_PROCESS"),
    ],
    "Max connections / user": "lifecycle.MAX_CONNECTIONS_PER_USER",
    "Connect rate / user / minute": "lifecycle.MAX_AUTHS_PER_USER_PER_MIN "
    "lifecycle.AUTH_RATE_WINDOW_S",
    "Upgrade request line + headers": "limits.SERVER_MAX_REQUEST_HEAD_BYTES",
    "Upgrade complete within": "limits.SERVER_READ_HEADER_TIMEOUT_S",
    "Sockets awaiting `auth_ok`": "limits.MAX_UNAUTHENTICATED_SOCKETS",
    "Max inbound frame": "limits.MAX_INBOUND_FRAME_BYTES limits.MAX_PREAUTH_FRAME_BYTES",
    "Fragments per inbound message": "limits.WS_MAX_FRAGMENTS_PER_MESSAGE",
    "Charge per inbound fragment": "limits.WS_FRAGMENT_OVERHEAD_BYTES limits.SERVER_WS_MAX_SIZE",
    "Inbound frames / connection": "limits.WS_INBOUND_FRAME_BURST limits.WS_INBOUND_FRAMES_PER_S",
    "Max `pong` after `auth_ok`": "limits.MAX_PONG_BYTES",
    "Max envelope `id`": "limits.ENVELOPE_ID_MAX_LEN",
    "Max outbound frame": "limits.MAX_OUTBOUND_FRAME_BYTES",
    "Max `bars` frame span (kind 4)": "bars_wire.MAX_TS_SPAN_MS",
    "Outbound queue budget": "outbound.QUEUE_BYTES outbound.QUEUE_FRAMES",
    "`bars.*` share of that budget": "limits.BARS_SHARE_PCT",
    "Min throttle": ["limits.MIN_THROTTLE_MS", _unthrottled],
    "Client inbound rate": "lifecycle.RATE_PER_SECOND lifecycle.RATE_PER_MINUTE "
    "lifecycle.PONG_BUDGET_PER_S lifecycle.PONG_BUDGET_BURST",
    "Rebuild budget (§7.5)": "limits.REBUILD_MAX_PER_TOPIC limits.REBUILD_MAX_PER_CONNECTION "
    "limits.REBUILD_MAX_PER_USER limits.REBUILD_WINDOW_S",
    "`ws.subscribe.denied` records": "limits.DENIAL_AUDITS_PER_WINDOW limits.DENIAL_AUDIT_WINDOW_S",
    "Heartbeat interval / timeout": "lifecycle.HEARTBEAT_INTERVAL_S lifecycle.HEARTBEAT_TIMEOUT_S",
    "Auth timeout": "limits.AUTH_TIMEOUT_S lifecycle.MAX_AUTH_FAILURES limits.AUTH_CALL_TIMEOUT_S",
    "Replay `history` caps": [
        _cap("bars", "history"),
        _cap("footprint", "history"),
        _cap("heatmap", "window_seconds"),
    ],
    "Machine registry entries": "limits.MACHINE_ENTRIES_MAX",
    "Terminal machine retention": "limits.MACHINE_TERMINAL_RETENTION_S limits.MACHINE_TERMINAL_MAX",
    "Terminal sweep batch": "limits.MACHINE_SWEEP_BATCH",
    "Machine audit queue": "limits.MACHINE_AUDIT_PENDING_MAX",
}


def _probe(module: str, word: str) -> Callable[[], bool]:
    return lambda: any(
        word in n for n in vars(importlib.import_module(f"candleviewer.ws.{module}"))
    )


#: 16.2 rows the contract states and no code enforces yet: the owning ticket, and a probe that is
#: true once code for it exists (the row must then be mapped above, so this list cannot rot).
#: None is left: the deep-book cap (#604, E21-T01) and the heatmap spec caps and snapshot bound
#: (#605, E21-T02) are built and mapped.
CONTRACT_ONLY_ROWS: Final[dict[str, tuple[str, Callable[[], bool]]]] = {}
#: 3.6 table rows that 16.2 does not repeat: the JSON bounds of SR-184.
SECTION_3_6_ROWS: Final = {
    "Max inbound JSON nesting depth": "limits.MAX_JSON_DEPTH",
    "Max inbound JSON containers": "limits.MAX_JSON_CONTAINERS",
}
#: The MessagePack bounds of SR-185, in a paragraph of 3.6: the phrase that states each (its
#: number is group 1) and the constant of `ws/codec.py`.
MSGPACK_BOUNDS: Final = (
    (r"nesting (\d+)", "codec.MAX_MSGPACK_DEPTH"),
    (r"(\d+) entries in an array", "codec.MAX_MSGPACK_ARRAY_LEN"),
    (r"(\d+) in a map", "codec.MAX_MSGPACK_MAP_LEN"),
    (r"(\d[\d ]*\d) values in the frame", "codec.MAX_MSGPACK_VALUES"),
    (r"(\d+) until `auth_ok`", "codec.MAX_PREAUTH_MSGPACK_VALUES"),
)
#: Numeric constants of `ws/limits.py` that are no row of 16.2 or 3.6, and why.
NOT_A_PROTOCOL_LIMIT: Final = {
    "SUB_ID_MAX_LEN": "the `subId` definition of 13 (`maxLength`), checked against the schema",
    "MAX_DENIALS_LISTED": "what one `ws.subscribe.denied` audit record lists, not a wire limit",
    "FANOUT_SEND_TIMEOUT_S": "a bound inside the server on one fan-out send (9.5)",
    "FANOUT_AUDIT_TIMEOUT_S": "a bound inside the server on one audit row",
    "FANOUT_AUDIT_MAX_FAILURES": "a bound inside the server on a fan-out's audit rows",
    "CLOSE_TOO_BIG": "a close code (4.4), not a limit",
    "CLOSE_SLOW_CONSUMER": "a close code (4.4), not a limit",
    "SERVER_WS_HEADROOM_BYTES": "the 4 KiB of 4.4, whose sum with 256 KiB is the 260 KiB of 16.2",
    "SERVER_LIMIT_CONCURRENCY": "the process's concurrency bound, which no client can see",
    "SERVER_KEEP_ALIVE_TIMEOUT_S": "uvicorn's idle bound on an HTTP connection",
    "WS_MAX_QUEUED_MESSAGES": "the transport's inbound queue, which no client can see",
    "SERVER_CLOSE_DRAIN_TIMEOUT_S": "the transport's close drain, which no client can see",
}


def _quantities(refs: str | Sequence[str | Callable[[], float]]) -> list[float]:
    parts = refs.split() if isinstance(refs, str) else refs
    return [float(p() if callable(p) else constant(p)) for p in parts]


def _mapped(rows: Mapping[str, Any]) -> set[str]:
    refs = (
        r for v in rows.values() for r in ([v] if isinstance(v, str) else v) if isinstance(r, str)
    )
    return {name.rpartition(".")[2] for ref in refs for name in ref.split()}


def table_drifts(rows: Mapping[str, Row], registry: Mapping[str, Any], what: str) -> list[Drift]:
    """Each mapped row of a document table against the constants the registry names for it."""
    out = []
    for label, refs in registry.items():
        row = rows.get(label)
        if row is None:
            out.append(Drift(what, label, _ABSENT, "a row", f"{what} has no row"))
        elif (got := numbers(row.cells[1])) != (want := _quantities(refs)):
            out.append(Drift(what, label, got, want, f"23-ws-protocol.md {what} (line {row.line})"))
    return out


def rows_without_a_registry_entry() -> list[str]:
    """16.2 rows that are neither mapped nor contract only: a new limit with no entry."""
    return [r for r in section_16_2() if r not in LIMIT_ROWS and r not in CONTRACT_ONLY_ROWS]


def contract_only_rows_that_landed() -> list[str]:
    return [label for label, (_, landed) in CONTRACT_ONLY_ROWS.items() if landed()]


def limits_without_a_doc_row() -> list[str]:
    """Numeric constants of `ws/limits.py` that no row maps and no reason excuses."""
    limits = importlib.import_module("candleviewer.ws.limits")
    public = {
        n
        for n, v in vars(limits).items()
        if n.isupper() and isinstance(v, int | float) and not isinstance(v, bool)
    }
    mapped = _mapped(LIMIT_ROWS) | _mapped(SECTION_3_6_ROWS)
    return sorted(public - mapped - set(NOT_A_PROTOCOL_LIMIT))


def section_3_6_rows() -> dict[str, Row]:
    sec = _doc.section("### 3.6 Frame size limits", "**Fragmented client messages")
    rows = _doc.strict_table(sec, ("Limit", "Value", "Enforcement"), "23 section 3.6")
    return {r.cells[0]: r for r in rows}


def msgpack_bound_drifts() -> list[Drift]:
    """The SR-185 bounds of the 3.6 paragraph, each quantity next to its phrase, against `codec`."""
    sec = _doc.section("### 3.6 Frame size limits", "## 4. Connection lifecycle")
    text = _doc.paragraph(sec.text, "**MessagePack client frames (as built, SR-185")
    out = []
    for pattern, ref in MSGPACK_BOUNDS:
        found = re.search(pattern, text)
        stated = int(found[1].replace(" ", "")) if found else _ABSENT
        if stated != constant(ref):
            out.append(Drift("3.6", ref, stated, constant(ref), "23-ws-protocol.md section 3.6"))
    return out


# --- 10.2 error catalogue, 4.4 close codes, 2.2 subprotocols, 4.3 settings ---------------------


def error_drifts(field: str) -> list[Drift]:
    """`scope`, `retryable` or the REST analogue of every WS code, 10.2 against the registry."""
    from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES

    sec = _doc.section("### 10.2 Catalogue", "### 10.3 ")
    columns = ("Code", "Scope", "`retryable`", "REST", "Meaning / client action")
    meta = {c.value: ERROR_META[c] for c in WS_ERROR_CODES}
    out = []
    for row in _doc.strict_table(sec, columns, "23 section 10.2"):
        code, scope, retryable, rest = (c.strip("`") for c in row.cells[:4])
        m = meta.get(code)
        if m is None:
            out.append(
                Drift(f"errors.{field}", code, "a row", _ABSENT, f"section 10.2 line {row.line}")
            )
            continue
        # `=` is the same code on both surfaces, `—` none, else the code a client may fold it into
        rest_analogue = "=" if "rest" in m.surfaces else (m.rest_analogue or "—")
        doc, runtime = {
            "scope": (scope, m.scope),
            "retryable": (retryable == "yes", m.retryable),
            "rest": (rest, rest_analogue),
        }[field]
        if doc != runtime:
            out.append(
                Drift(f"errors.{field}", code, doc, runtime, f"section 10.2 line {row.line}")
            )
    return out


def close_code_drifts() -> list[Drift]:
    """4.4 lists the gateway's codes and the host's `1012`; the `bye.code` enum, the gateway's."""
    from candleviewer.ws.gateway import SERVER_RESTART_CLOSE
    from candleviewer.ws.lifecycle import CloseCode

    sec = _doc.section("### 4.4 Close codes", "A refused upgrade")
    rows = _doc.strict_table(sec, ("Code", "Name", "Meaning", "Client action"), "23 section 4.4")
    doc = {int(r.cells[0].strip("`")) for r in rows}
    gateway = {int(c) for c in CloseCode}
    enum = set(_schema("bye")["properties"]["code"]["enum"])
    pairs = (
        ("section 4.4 against the gateway's codes and 1012", doc, gateway | {SERVER_RESTART_CLOSE}),
        ("the bye.code enum against the gateway's codes", enum, gateway),
    )
    return [
        Drift("close_codes", str(c), c in a, c in b, w) for w, a, b in pairs for c in sorted(a ^ b)
    ]


def subprotocol_drifts() -> list[Drift]:
    from candleviewer.ws.lifecycle import SUPPORTED_SUBPROTOCOLS

    sec = _doc.section("### 2.2 Subprotocol negotiation", "The server echoes")
    rows = _doc.strict_table(sec, ("Subprotocol", "Meaning"), "23 section 2.2")
    doc, code = [r.cells[0].strip("`") for r in rows], list(SUPPORTED_SUBPROTOCOLS)
    return [] if doc == code else [Drift("subprotocols", "order", doc, code, "section 2.2 table")]


_URL_LINE: Final = re.compile(r"^wss://<host>(/\S*)$", re.M)
_OTHER_MOUNT: Final = re.compile(r"the same route without the server base, `(/[^`]*)`")


def endpoint_drifts() -> list[Drift]:
    """2.1's URL is the server base and the route of `ws/gateway.py`; its as-built paragraph names
    the other mount, the route without the base (#3907). A URL or a mount that the section no
    longer states is an assertion failure, never a skipped row."""
    from candleviewer.ws import gateway

    text = _doc.section("### 2.1 Endpoint", "### 2.2 ").text
    url, mount = _URL_LINE.findall(text), _OTHER_MOUNT.findall(text)
    assert len(url) == 1, f"23 section 2.1 states {len(url)} URLs; this test reads exactly one"
    assert len(mount) == 1, f"23 section 2.1 names {len(mount)} mounts without the server base"
    rows = {
        "url": (url[0], gateway.WS_SERVER_BASE + gateway.WS_PATH),
        "mount": (mount[0], gateway.WS_PATH),
    }
    return [Drift("endpoint", k, d, c, "section 2.1") for k, (d, c) in rows.items() if d != c]


def _settings_bullet() -> str:
    sec = _doc.section("### 4.3 ", "### 4.4 ")
    return _doc.paragraph(sec.text.replace("\n- ", "\n\n- "), "- Settings (`CV_WS_*`):")


def documented_settings() -> dict[str, str]:
    """`CV_WS_*` name (without the prefix) -> what 4.3 states in the brackets after it."""
    listed = _settings_bullet().split("The defaults are")[0]
    return dict(re.findall(r"`CV_WS_([A-Z_]+)` \(([^)]*)\)", listed))


def settings_drifts() -> list[Drift]:
    """Each `CV_WS_*` default of 4.3 against `Settings`, and the bounds the paragraph states."""
    from candleviewer.settings import Settings

    held = re.search(
        r"`CV_WS_CLASSIFY_INTERVAL_MS` is held to (\d+)-(\d[\d ]*\d)", _settings_bullet()
    )
    out = []
    for name, inner in documented_settings().items():
        field = Settings.model_fields[f"ws_{name.lower()}"]
        ge = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        le = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        want, got = {"default": _doc.first_number(inner)}, {"default": field.default}
        if "floor" in inner:  # lowered down to its floor, never raised (4.3)
            want |= {
                "floor": _doc.first_number(inner.split("floor")[1]),
                "ceiling": want["default"],
            }
            got |= {"floor": ge, "ceiling": le}
        if name == "CLASSIFY_INTERVAL_MS" and held:
            want |= {"floor": int(held[1]), "ceiling": int(held[2].replace(" ", ""))}
            got |= {"floor": ge, "ceiling": le}
        out += [
            Drift("settings", f"{name}.{k}", v, got[k], "section 4.3")
            for k, v in want.items()
            if v != got[k]
        ]
    return out


# --- 3.1 frame types ----------------------------------------------------------------------------


def _handled_types() -> set[str]:
    """The `t` strings `dispatch` in `ws/gateway.py` compares `kind` with."""
    tree = ast.parse((_WS / "gateway.py").read_text(encoding="utf-8"))
    dispatch = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "dispatch"
    )
    return {
        c.value
        for cmp in ast.walk(dispatch)
        if isinstance(cmp, ast.Compare) and isinstance(cmp.left, ast.Name) and cmp.left.id == "kind"
        for c in cmp.comparators
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    }


def _built_types() -> set[str]:
    """The `t` strings a module of `ws/` builds a frame with: `{"t": ...}` or `_reply(...)`."""
    found: set[str] = set()
    for path in _WS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Dict):
                pairs = zip(node.keys, node.values, strict=True)
                found |= {
                    v.value
                    for k, v in pairs
                    if isinstance(k, ast.Constant) and k.value == "t"
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                }
            elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_reply":
                found |= {
                    a.value
                    for a in node.args[:1]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                }
    return found


def frame_type_drifts() -> list[Drift]:
    """3.1's table against the envelope's `t` enum; every frame a client may send is one the
    gateway handles, and every frame the server may send is one a module of `ws/` builds."""
    sec = _doc.section("### 3.1 The envelope", "**The correlation `id`")
    rows = _doc.strict_table(sec, ("`t`", "Name", "Direction", "Purpose"), "23 section 3.1")
    direction = {r.cells[0].strip("`"): r.cells[2] for r in rows}
    enum = set(_schema("envelope")["properties"]["t"]["enum"])
    where = "section 3.1 table against the envelope enum"
    out = [
        Drift("frame_types", t, t in direction, t in enum, where)
        for t in sorted(enum ^ set(direction))
    ]
    handled, built = _handled_types(), _built_types()
    for t, way in direction.items():
        if way in {"C→S", "both"} and t not in handled:
            out.append(
                Drift("frame_types", t, f"{way}, handled", "not handled", "gateway dispatch")
            )
        if way in {"S→C", "both"} and t not in built:
            out.append(Drift("frame_types", t, f"{way}, built", "not built", "the modules of ws/"))
    return out


# --- 3.4 binary layout --------------------------------------------------------------------------

_SIZES: Final = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "i8": 1, "i16": 2, "i32": 4, "i64": 8}
_TYPED: Final = re.compile(r"`(u8|u16|u32|u64|i64) ([a-z_,]+)`")


def _declared(raw: Sequence[Mapping[str, Any]]) -> list[tuple[int, int, str, str]]:
    """(offset, size, type, name) of declared fields; a `pad` is `—`, as 3.4's table writes it."""
    offset, out = 0, []
    for f in raw:
        pad = f["type"].startswith("pad")
        size = int(f["type"][3:]) if pad else _SIZES[f["type"]]
        out.append((offset, size, "—" if pad else f["type"], f["name"]))
        offset += size
    return out


def _typed(sentence: str) -> list[str]:
    """The types of the fields a 3.4 sentence lists (`i64 o,h,l,c` is four)."""
    return [t for t, names in _TYPED.findall(sentence) for _ in names.split(",")]


def _stated(pattern: str, text: str) -> int | str:
    found = re.search(pattern, text)
    return int(next(g for g in found.groups() if g)) if found else _ABSENT


def layout_drifts() -> list[Drift]:
    """3.4's tables and stated sizes against `packages/protocol/cvwb-layout.json`, the one
    declaration both codecs are generated from. Where the prose names a field by a short name
    (`o,h,l,c`), the types and their order are compared, not the names."""
    layout = json.loads((_REPO / "packages" / "protocol" / "cvwb-layout.json").read_text("utf-8"))
    kinds = {k["id"]: k for k in layout["kinds"]}
    out: list[Drift] = []

    def check(key: str, doc: Any, code: Any, where: str) -> None:
        if doc != code:
            out.append(Drift("cvwb", key, doc, code, f"23-ws-protocol.md section 3.4 {where}"))

    def types(raw: Sequence[Mapping[str, Any]]) -> list[str]:
        return [f["type"] for f in raw if not f["type"].startswith("pad")]

    head = _doc.section("**Common header (24 bytes)**", "**body_kind 1/2")
    columns = ("Offset", "Size", "Type", "Field", "Notes")
    rows = _doc.strict_table(head, columns, "3.4 header")
    doc = [
        (int(r.cells[0]), int(r.cells[1]), r.cells[2].strip("`"), r.cells[3].strip("`"))
        for r in rows
    ]
    check("header", doc, _declared(layout["header"]), "header table")
    versions = re.search(r"`1`; `2` for body_kind (\d) .*? and (\d) ", head.text)
    two = sorted(k for k, v in kinds.items() if v["format_version"] == 2)
    check(
        "format_version",
        sorted(map(int, versions.groups())) if versions else _ABSENT,
        two,
        "header table",
    )

    # kinds 1 and 3 are tables of (size, type, field); the stride is stated in prose
    for kind, start, end in (
        (1, "**body_kind 1/2", "Snapshots carry"),
        (3, "**body_kind 3", "**body_kind 4"),
    ):
        sec = _doc.section(start, end)
        table = _doc.strict_table(sec, ("Size", "Type", "Field"), f"3.4 {start}")
        got = [(int(r.cells[0]), r.cells[1].strip("`"), r.cells[2].split("`")[1]) for r in table]
        want = [(size, type_, name) for _, size, type_, name in _declared(kinds[kind]["record"])]
        check(f"kind{kind}.record", got, want, start.strip("*"))
        stride = _stated(r"records of (\d+) bytes", sec.text)
        check(f"kind{kind}.stride", stride, kinds[kind]["record_bytes"], start.strip("*"))
    trailer = sum(_SIZES[f["type"]] for f in kinds[1]["trailer"])
    stated = _stated(r"(\d+)-byte trailer", _doc.between("**body_kind 1/2", "**body_kind 3"))
    check("kind1.trailer", stated, trailer, "body_kind 1/2")

    # kinds 4 to 6 are prose: a stride, then the fields as `type name`
    whole = _doc.section("**body_kind 4 — bars.**", "**Reserved record bytes").text
    names = {4: "bars", 5: "footprint", 6: "heatmap column"}
    prose = {n: _doc.paragraph(whole, f"**body_kind {n} — {name}.**") for n, name in names.items()}
    check(
        "kind4.stride",
        _stated(r"records of (\d+) bytes", prose[4]),
        kinds[4]["record_bytes"],
        "body_kind 4",
    )
    fields = prose[4].split(": ", 1)[1].split(". ")[0]
    check("kind4.types", _typed(fields), types(kinds[4]["record"]), "body_kind 4")
    prefix, cells = prose[5].split("then `cell_count`", 1)
    group = _declared(kinds[5]["group_prefix"])
    check(
        "kind5.prefix",
        _stated(r"(\d+)-byte prefix", prefix),
        group[-1][0] + group[-1][1],
        "body_kind 5",
    )
    check("kind5.prefix.types", _typed(prefix), types(kinds[5]["group_prefix"]), "body_kind 5")
    times = r"\u00d7 (\d+) bytes"
    check("kind5.stride", _stated(times, cells), kinds[5]["record_bytes"], "body_kind 5")
    check(
        "kind5.cell.types",
        _typed(cells.split("The group")[0]),
        types(kinds[5]["record"]),
        "body_kind 5",
    )
    prefix, rows6 = prose[6].split("then `row_count`", 1)
    check("kind6.prefix.types", _typed(prefix), types(kinds[6]["body_prefix"]), "body_kind 6")
    check("kind6.stride", _stated(times, rows6), kinds[6]["record_bytes"], "body_kind 6")
    check("kind6.row.types", _typed(rows6), types(kinds[6]["record"]), "body_kind 6")
    return out


# --- 6 topic catalogue (the half `test_ws_topic_registry_as_built.py` does not read) ------------

#: The registry spells a placeholder differently from the document in one pattern (`profile_kind`
#: for the document's `kind`): the tables are compared as the document writes them.
PLACEHOLDER_ALIASES: Final = {"profile_kind": "kind"}
PUBLIC_6_1: Final = ("### 6.1 Public market-data topics", "#### 6.1.1 ")
PRIVATE_6_2: Final = ("### 6.2 Private topics", "#### 6.2.1 ")
_SCOPE_TEXT: Final = {
    "none": "NONE",
    "granted accounts": "GRANTED_ACCOUNTS",
    "granted accounts, see §15.6": "GRANTED_ACCOUNTS",
    "own alerts only": "SELF",
}
#: The words with which 6.1 marks a family contract only, in a bullet under the family's own.
CONTRACT_ONLY_WORDS: Final = "**Status: contract only (C-6.1).**"


#: A family's own bullet in 6.1: the name in code, then `**` or ` (` (`- **`name` (ticket).**`). A
#: bullet that only mentions a family (`- **`book` depth is in the topic name**`) is not its bullet.
_FAMILY_BULLET: Final = re.compile(r"- \*\*`(\w+)`(?:\*\*| \()")


def families_marked_contract_only() -> set[str]:
    """The families whose bullet in 6.1 carries the marker words: none once every family is served.
    Read from the document, so a family going live changes the document and the registry, and
    this module not at all. A marker under any other bullet is filed under that bullet's first
    words, which name no family, so it is a drift and never a mark on the bullet before it."""
    marked: set[str] = set()
    owner = ""
    for line in _doc.DOC.splitlines():
        if line.startswith("- "):
            head = _FAMILY_BULLET.match(line)
            owner = head.group(1) if head else line[2:42]
        elif line.startswith("  - ") and CONTRACT_ONLY_WORDS in line:
            marked.add(owner or "(no bullet)")
    return marked


def doc_spelling(pattern: str) -> str:
    for old, new in PLACEHOLDER_ALIASES.items():
        pattern = pattern.replace("{" + old + "}", "{" + new + "}")
    return pattern


def topic_table_problems(
    public: Sequence[Sequence[str]],
    private: Sequence[Sequence[str]],
    families: Mapping[str, Any],
    as_built: str,
) -> list[str]:
    """Every row of the 6.1 and 6.2 tables against the registry: its topic, options, default
    throttle and binary form. An option the registry takes and a row leaves out is one that the
    row's "As built" paragraph names. A table row ahead of its registry row, and a registry row
    with no table row, are problems."""
    from candleviewer.ws.topics import UNIVERSAL

    by_pattern = {
        doc_spelling(p): fam
        for fam in families.values()
        if fam.family != "machines"
        for p in fam.patterns
    }
    problems: list[str] = []
    left_out: list[tuple[str, str]] = []  # (pattern, option) the registry takes, the row omits
    for row, has_binary_column in [(r, True) for r in public] + [(r, False) for r in private]:
        pattern = row[0].strip("`")
        fam = by_pattern.pop(pattern, None)
        if fam is None:
            problems.append(f"{pattern}: not in the registry")
            continue
        in_name = set(re.findall(r"\{([a-z_]+)\}", pattern))
        shown = {o for o in re.findall(r"`([a-z_]+)`", row[1]) if o not in in_name | set(UNIVERSAL)}
        if shown - set(fam.options):
            problems.append(f"{pattern}: lists {sorted(shown - set(fam.options))}, not taken")
        left_out += [(pattern, option) for option in sorted(set(fam.options) - shown)]
        ms = re.match(r"(\d[\d ]*\d|\d) ms", row[3])  # "1 000 ms"; `heatmap` is "= bucket"
        if ms is not None and int(ms.group(1).replace(" ", "")) != fam.default_throttle_ms:
            problems.append(
                f"{pattern}: default throttle {row[3]!r} is not {fam.default_throttle_ms}"
            )
        if has_binary_column and row[4].startswith("✔") != fam.binary:
            problems.append(f"{pattern}: binary form doc={row[4]!r} registry={fam.binary}")
    problems += [f"{p}: not in the doc tables" for p in sorted(by_pattern)]
    problems += [
        f"{p}: option {o} is taken and the row omits it, and the As built paragraph does not say so"
        for p, o in left_out
        if f"`{p}`" not in as_built or f"`{o}`" not in as_built
    ]
    return problems


def permission_scope_drifts(families: Mapping[str, Any]) -> list[Drift]:
    """6.3's permission and scope narrowing of each family against the registry."""
    sec = _doc.section("### 6.3 Topic", "Permissions are checked")
    columns = ("Topic family", "Required permission", "Scope narrowing")
    rows = _doc.strict_table(sec, columns, "23 section 6.3")
    documented = {name: r for r in rows for name in re.findall(r"`([a-z_]+)[^`]*`", r.cells[0])}
    out = []
    for name, fam in families.items():
        row = documented.get(name)
        if row is None:
            out.append(Drift("topics.permission", name, _ABSENT, "a row", "section 6.3"))
            continue
        perm = re.search(r"`([a-z]+:[a-z]+)`", row.cells[1])
        pairs = (
            (
                "permission",
                perm[1] if perm else None,
                fam.permission.value if fam.permission else None,
            ),
            ("scope", _SCOPE_TEXT.get(row.cells[2]), fam.scope.name if fam.scope else None),
        )
        out += [
            Drift(f"topics.{k}", name, d, c, f"section 6.3 line {row.line}")
            for k, d, c in pairs
            if d != c
        ]
    return out


def book_throttle_drifts() -> list[Drift]:
    """The `book` row of 6.1: 50 ms, 20 ms at depth 1 and 100 ms at depths 200 and 500."""
    from candleviewer.ws.topics import default_throttle_ms, parse_topic

    def default(depth: int) -> int:
        return default_throttle_ms(parse_topic(f"book.BTCUSDT.{depth}"))

    columns = ("Topic", "Options", "Snapshot", "Default throttle", "Binary", "Payload schema")
    rows = _doc.strict_table(_doc.section(*PUBLIC_6_1), columns, "23 section 6.1")
    row = next(r for r in rows if r.cells[0].startswith("`book."))
    want, got = [default(50), 1, default(1), 200, 500, default(200)], numbers(row.cells[3])
    out = (
        []
        if got == want
        else [Drift("topics.book", "throttle", got, want, f"section 6.1 line {row.line}")]
    )
    if default(200) != default(500):
        out.append(
            Drift("topics.book", "depth 200 and 500", default(200), default(500), "section 6.1")
        )
    return out


def contract_only_drifts(families: Mapping[str, Any]) -> list[Drift]:
    """A family the registry refuses (`served=False`) is one the document marks contract only, and
    a family it marks so is refused."""
    marked = families_marked_contract_only()
    out = [
        Drift("topics.served", name, "a contract-only marker", "no such family", "section 6")
        for name in sorted(marked - set(families))
    ]
    for name, fam in families.items():
        if (name in marked) == fam.served:
            doc = "contract only" if name in marked else "served"
            out.append(Drift("topics.served", name, doc, f"served={fam.served}", "section 6"))
    return out


def option_drifts(families: Mapping[str, Any]) -> dict[str, list[Drift]]:
    """Each option of the registry against its 13.5 property, in three kinds of fact: the type,
    range and enum (`scalar`), the item bounds of a list (`items`) and whether the schema allows
    `null` (`null`). 13.5 is the union of every topic's options, so a bound is the widest one."""
    from candleviewer.ws.topics import UNIVERSAL

    sub, common = _schema("sub")["$defs"], _schema("common")["$defs"]

    def resolve(node: Mapping[str, Any]) -> Mapping[str, Any]:
        while "$ref" in node:
            ref = node["$ref"]
            node = (sub if ref.startswith("#") else common)[ref.rsplit("/", 1)[1]]
        return node

    schema = {**sub["options"]["properties"], **sub["indicatorOptions"]["properties"]}
    taken: dict[str, list[Any]] = {name: [o] for name, o in UNIVERSAL.items()}
    for fam in families.values():
        for name, opt in fam.options.items():
            taken.setdefault(name, []).append(opt)
    types = {
        "int": "integer",
        "number": "number",
        "bool": "boolean",
        "decimal": "string",
        "str": "string",
    }
    out: dict[str, list[Drift]] = {"scalar": [], "items": [], "null": []}

    def check(group: str, name: str, doc: Any, code: Any) -> None:
        if doc != code:
            out[group].append(Drift(f"options.{name}", group, doc, code, "section 13.5"))

    def widest(opts: Sequence[Any], attr: str, pick: Callable[[list[Any]], Any]) -> Any:
        values = [getattr(o, attr) for o in opts]
        return None if any(v is None for v in values) else pick(values)

    for name, opts in sorted(taken.items()):
        kind = opts[0].kind
        if name not in schema:
            out["scalar"].append(
                Drift(f"options.{name}", "property", _ABSENT, kind, "section 13.5")
            )
            continue
        prop = resolve(schema[name])
        doc_type = prop.get("type", "enum" if "enum" in prop else None)
        nullable = isinstance(doc_type, list) and "null" in doc_type
        if nullable:
            doc_type = next(t for t in doc_type if t != "null")
        check("null", name, nullable, False)
        if kind in types:
            check("scalar", name, doc_type, types[kind])
        if kind in {"int", "number"}:
            doc = (prop.get("minimum"), prop.get("maximum"))
            check("scalar", name, doc, (widest(opts, "lo", min), widest(opts, "hi", max)))
        if kind == "enum":
            check(
                "scalar", name, set(prop.get("enum", ())), set().union(*(o.choices for o in opts))
            )
        if kind in {"uuids", "symbols", "strings", "instances"}:
            check("scalar", name, doc_type, "array")
            # 13.5 sets no `minItems` on `exchange_account_ids` on purpose (6.2, "As built")
            low = 0 if name == "exchange_account_ids" else max(o.min_items for o in opts)
            doc = (prop.get("minItems", 0), prop.get("maxItems"))
            check("items", name, doc, (low, widest(opts, "max_items", max)))
            if kind == "strings":  # an item is 1 to 64 characters (`_CHECKS["strings"]`)
                item = resolve(prop["items"])
                check("items", name, (item.get("minLength"), item.get("maxLength")), (1, 64))
    return out
