#!/usr/bin/env python3
"""E17-T07 (#572): the `cv.v1` wire-contract golden and the gate that checks it.

`packages/protocol/wire-contract.v1.golden.json` is a committed description of the WebSocket wire
as the implementation speaks it (23-ws-protocol.md section 2.3): the CVWB header and every body
kind's layout, the envelope and control-frame shapes, the close codes and the reasons that map to
them, the error codes, the advertised limits as one-sided bounds, the topic names, the
subprotocols and the bounds the pre-freeze tightening set (`PINNED_BOUNDS`). This tool collects
that description from the implementation and compares it with the golden.

    python tools/contracts/wire_contract.py            check (the default; `make contracts`)
    python tools/contracts/wire_contract.py --write    create the golden: the first freeze only,
                                                       it refuses if the file exists
    python tools/contracts/wire_contract.py --extend   rewrite it when the diff is purely additive

No flag accepts a breaking diff (C-6.3). A breaking change adds `wire-contract.v2.golden.json` next
to this one and serves `cv.v2` in parallel; editing the golden to get green is not a move this
tool offers. A deleted or damaged golden is restored from git and never rewritten: a golden that
lacks a group, or a bound, enumeration or limit that this tool declares, is reported as damaged and
not as news (`PIN_ADDITIONS` is the one way to start pinning something new). The comparison and the
rendering are pure and stdlib-only; `collect()` reads the repository files and imports
`candleviewer.ws.*` lazily, so run it as
`uv run --project services/api python tools/contracts/wire_contract.py`.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import struct
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

REPO = Path(__file__).resolve().parents[2]
PROTOCOL = REPO / "packages" / "protocol"
GOLDEN = PROTOCOL / "wire-contract.v1.golden.json"
LAYOUT = PROTOCOL / "cvwb-layout.json"
BUNDLE = PROTOCOL / "ws-schemas.json"
CONSTANTS = PROTOCOL / "generated" / "ws_constants.py"

CONTRACT: Final = "cv.v1"
BREAKING: Final = "breaking"
ADDITIVE: Final = "additive"
_MISSING: Final = object()

_SIZES: Final = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "i8": 1, "i16": 2, "i32": 4, "i64": 8}
_CODES: Final = {"u8": "B", "u16": "H", "u32": "I", "u64": "Q", "i8": "b", "i16": "h", "i32": "i"}

#: The frames whose payload schema the golden walks (23 section 13.2 to 13.6). The `err` payload,
#: `common#/$defs/error`, is walked too.
CONTROL_FRAMES: Final = (
    *("hello", "welcome", "auth", "auth_ok", "permission_change"),
    *("sub", "sub_ok", "unsub", "unsub_ok", "ctl", "ctl_ok", "resync", "revoked", "bye"),
    "heartbeat",
)
#: The server-to-client enumerations the golden pins: name -> (schema, JSON pointer). The close
#: codes, the error codes and the envelope's `t` and `e` have groups of their own.
PINNED_ENUMS: Final = {
    "welcome.encoding": ("welcome", "/properties/encoding"),
    "auth_ok.roles": ("auth_ok", "/properties/roles/items"),
    "permission_change.roles": ("permission_change", "/properties/roles/items"),
    "revoked.reason": ("revoked", "/properties/reason"),
    "snap.meta.reason": ("common", "/$defs/snapMeta/properties/reason"),
    "snap.meta.source": ("common", "/$defs/snapMeta/properties/source"),
}
#: The pinned enumerations that are open-ended, so a new value is additive (C-6.3): a client keeps
#: an unknown reason as a tag (23 section 2.3, section 7.4 C18). Every other one is closed.
OPEN_ENUMS: Final = frozenset({"revoked.reason", "snap.meta.reason"})
#: `welcome.limits` keys by the one side a client may rely on: the server never advertises less
#: than a `floor`, never more than a `ceiling`. A key not listed is recorded without a promise.
LIMIT_BOUNDS: Final = {
    "max_subscriptions": "floor",
    "max_topics_per_request": "floor",
    "max_inbound_frame_bytes": "floor",
    "max_symbols_per_connection": "floor",
    "max_outbound_frame_bytes": "ceiling",
    "min_throttle_ms": "ceiling",
}
#: The `bye` reasons `RevocationHub.close_for` builds for a socket: the disable cascade, and every
#: other session revocation (`app._hub_publisher`).
REVOCATION_REASONS: Final = ("session_revoked", "user_disabled")
#: The registry's placeholder names that differ from the document's (`profile_kind` for `kind`):
#: the golden spells a topic as 23 section 6 does.
PLACEHOLDER_ALIASES: Final = {"profile_kind": "kind"}
#: The schema facets that bound a value: a `lower` one is a minimum, an `upper` one a maximum.
BOUND_FACETS: Final = {
    "minimum": "lower",
    "maximum": "upper",
    "minLength": "lower",
    "maxLength": "upper",
    "minItems": "lower",
    "maxItems": "upper",
}
#: The bounds the pre-freeze tightening set in 23 section 13 (the first commit of #572), so that
#: undoing one is breaking: name -> (schema, JSON pointer, side). `request` is what the server
#: accepts from a client, `response` what it promises to send. Nothing else of this kind is pinned:
#: the other ranges, lengths, item bounds and enumerations of the request options (13.5, 13.6) are
#: not, and neither are the payloads of sections 14 and 15 (only the schema's name per topic is).
PINNED_BOUNDS: Final = {
    "common.subId": ("common", "/$defs/subId", "response"),
    "ctl.metrics": ("ctl", "/properties/metrics", "request"),
    "sub.indicator_options.from_seq": (
        "sub",
        "/$defs/indicatorOptions/properties/from_seq",
        "request",
    ),
    "sub.options.from_seq": ("sub", "/$defs/options/properties/from_seq", "request"),
    "sub.options.metrics": ("sub", "/$defs/options/properties/metrics", "request"),
    "sub.options.rule_ids": ("sub", "/$defs/options/properties/rule_ids", "request"),
    "sub.options.status": ("sub", "/$defs/options/properties/status", "request"),
    "sub.options.symbols": ("sub", "/$defs/options/properties/symbols", "request"),
    "sub_ok.results.sub_id": ("sub_ok", "/properties/results/items/properties/sub_id", "response"),
}
#: The members of a group that this tool itself declares: a golden that lacks one of them has lost
#: a pin, which must not read as a new one (so `--extend` cannot record a breaking change to it).
DECLARED: Final[dict[str, Mapping[str, Any]]] = {
    "bounds": PINNED_BOUNDS,
    "enums": PINNED_ENUMS,
    "limits": LIMIT_BOUNDS,
}
#: What this tool pins that a golden may not hold yet: a group that `compare` reads with `.get`
#: (`body_kinds`, `control_frames`, `enums`, `bounds`, `error_codes`, `limits` or `topics`; the
#: other five are read directly, and a golden without one is malformed), a declared member as
#: `bounds.<name>`, `enums.<name>` or `limits.<key>`, or the path of a new member of a pinned layout
#: such as `body_kinds.6.header_record_count`. Empty when every pin is recorded. To start pinning
#: something new, name it here, run `--extend`, and remove the name in the same change.
PIN_ADDITIONS: Final[frozenset[str]] = frozenset()
#: Every group of the golden. A golden that lacks one, or has it empty, promises nothing there.
GROUPS: Final = (
    "contract",
    "header",
    "body_kinds",
    "envelope",
    "control_frames",
    "enums",
    "bounds",
    "close_codes",
    "error_codes",
    "limits",
    "topics",
    "subprotocols",
)
#: The repository path of the golden, for the message that says where to restore it from.
GOLDEN_PATH: Final = GOLDEN.relative_to(REPO).as_posix()

GUIDANCE: Final = """\
cv.v1 is frozen (23-ws-protocol.md section 2.3, CONSTITUTION C-6.3). A change like this one breaks
every deployed client. It needs `cv.v2` served in parallel with `cv.v1` for at least one full
release, a deprecation entry in 23-ws-protocol.md and an ADR. Do not edit the golden to make this
pass: the check has no such mode.
If the change is additive (a new optional member, topic, error code or close reason), it should not
be listed above: see packages/protocol/README.md, "Compatibility: additive or breaking?"."""
DAMAGED: Final = f"""\
The golden is damaged or incomplete, so there is nothing to compare the implementation with. Restore
it from git (`git restore -- {GOLDEN_PATH}`): it is never rewritten to make a check pass, and
`--write` only creates the first golden."""

_API: Final = "services/api/candleviewer/ws"
_SCHEMAS: Final = "packages/protocol/ws-schemas.json (23-ws-protocol.md"
_SOURCES: Final = {
    "header": "packages/protocol/cvwb-layout.json -> header",
    "body_kinds": "packages/protocol/cvwb-layout.json -> kinds",
    "envelope": f"{_SCHEMAS} section 13.1)",
    "control_frames": f"{_SCHEMAS} section 13.2 to 13.6)",
    "enums": f"{_SCHEMAS} section 13)",
    "bounds": f"{_SCHEMAS} section 13.5 and 13.6; common#/$defs/subId)",
    "close_codes": f"{_API}/lifecycle.py CloseCode, CLOSE_REASONS; {_API}/revocation.py",
    "error_codes": f"{_API}/_generated/error_codes.py ERROR_META",
    "limits": f"{_API}/lifecycle.py LIMITS_BLOCK (welcome_payload)",
    "topics": f"{_API}/topics.py FAMILIES",
    "subprotocols": f"{_API}/lifecycle.py SUPPORTED_SUBPROTOCOLS",
}


@dataclass(frozen=True)
class Finding:
    """One difference. `golden` and `impl` are its two sides (`_MISSING` where a side lacks the
    member), `labels` names them, and `source` says where to look to change the implementation."""

    severity: str
    path: str
    golden: Any
    impl: Any
    source: str = ""
    note: str = ""
    labels: tuple[str, str] = ("golden", "implementation")


@dataclass
class Collected:
    """The contract as the implementation speaks it, and where its own sources disagree."""

    contract: dict[str, Any]
    findings: list[Finding] = field(default_factory=list)


# --- Comparison (pure) -------------------------------------------------------------------------


def _source_of(path: str, golden: Mapping[str, Any], impl: Mapping[str, Any]) -> str:
    top = path.split(".", 1)[0]
    if top != "body_kinds" or path.count(".") == 0:
        return _SOURCES.get(top, "")
    kind_id = path.split(".")[1].split("[")[0]
    kind = (impl.get(top) or {}).get(kind_id) or (golden.get(top) or {}).get(kind_id)
    if not kind:
        return _SOURCES[top]
    if path.endswith(".header_record_count"):  # written by the encoder, not declared in the layout
        return f"{_API}/binary.py _header_count (encode), kind {kind['name']}"
    source = f"packages/protocol/cvwb-layout.json -> kinds[{kind['name']}]"
    return source + (".record_bytes" if path.endswith(".record_stride") else "")


class _Diff:
    """Collects findings. Each group has its rule: `exact`, `members`, `values`, `limits`."""

    def __init__(self, golden: Mapping[str, Any], impl: Mapping[str, Any]) -> None:
        self.golden, self.impl = golden, impl
        self.out: list[Finding] = []

    def add(self, severity: str, path: str, g: Any, i: Any, note: str = "") -> None:
        self.out.append(
            Finding(severity, path, g, i, _source_of(path, self.golden, self.impl), note)
        )

    def exact(self, path: str, g: Any, i: Any) -> None:
        """Any difference is breaking."""
        if isinstance(g, dict) and isinstance(i, dict):
            for k in g:
                if k in i:
                    self.exact(f"{path}.{k}", g[k], i[k])
                else:
                    self.add(BREAKING, f"{path}.{k}", g[k], _MISSING, "removed")
            for k in i:
                if k not in g:
                    new = f"{path}.{k}"
                    if new in PIN_ADDITIONS:  # a pin this change starts: --extend may record it
                        self.add(ADDITIVE, new, _MISSING, i[k], "new pin")
                    else:
                        self.add(BREAKING, new, _MISSING, i[k], "added to a pinned layout")
        elif isinstance(g, list) and isinstance(i, list) and len(g) == len(i):
            for n, (a, b) in enumerate(zip(g, i, strict=True)):
                self.exact(f"{path}[{n}]", a, b)
        elif g != i:
            self.add(BREAKING, path, g, i)

    def members(
        self,
        path: str,
        g: Mapping[str, Any],
        i: Mapping[str, Any],
        each: Callable[[str, Any, Any], None] | None = None,
    ) -> None:
        """A removed member is breaking, a new one additive, a kept one compared by `each`."""
        for k in g:
            if k not in i:
                self.add(BREAKING, f"{path}.{k}", g[k], _MISSING, "removed")
            else:
                (each or self.exact)(f"{path}.{k}", g[k], i[k])
        for k in i:
            if k not in g:
                self.add(ADDITIVE, f"{path}.{k}", _MISSING, i[k], "new")

    def values(self, path: str, g: Iterable[Any], i: Iterable[Any], *, open_: bool) -> None:
        """A removed value is breaking; a new one is additive only in an open set."""
        old, new = list(g), list(i)
        for v in old:
            if v not in new:
                self.add(BREAKING, path, v, _MISSING, "value removed")
        for v in new:
            if v not in old:
                self.add(ADDITIVE if open_ else BREAKING, path, _MISSING, v, "new value")

    def shape(self, path: str, g: Mapping[str, Any], i: Mapping[str, Any]) -> None:
        """An object schema: the required set and the additionalProperties rule are exact, a new
        member is additive (it is optional: `required` is exact), a member's type is exact."""
        self.exact(f"{path}.required", g["required"], i["required"])
        self.members(f"{path}.members", g["members"], i["members"])
        for key in ("additional_properties", "min_properties"):
            self.exact(f"{path}.{key}", g.get(key), i.get(key))

    def enum(self, path: str, g: Mapping[str, Any], i: Mapping[str, Any]) -> None:
        self.values(f"{path}.values", g["values"], i["values"], open_=bool(g["open"]))
        if g["open"] != i["open"]:
            self.add(BREAKING if g["open"] else ADDITIVE, f"{path}.open", g["open"], i["open"])

    def limits(self, g: Mapping[str, Any], i: Mapping[str, Any]) -> None:
        """A floor may rise and a ceiling may fall (loosening); the other way is tightening."""
        for key, want in g.items():
            path = f"limits.{key}"
            if key not in i:
                self.add(BREAKING, path, want, _MISSING, "removed")
                continue
            g_bound, g_value = next(iter(want.items()))
            i_bound, i_value = next(iter(i[key].items()))
            if g_bound != i_bound:
                self.add(BREAKING, path, want, i[key], "bound changed")
            elif g_bound != "seen" and i_value != g_value:
                tighter = i_value < g_value if g_bound == "floor" else i_value > g_value
                self.add(BREAKING if tighter else ADDITIVE, path, g_value, i_value,
                         "tightened" if tighter else "loosened")  # fmt: skip
        for key in i:
            if key not in g:
                self.add(ADDITIVE, f"limits.{key}", _MISSING, i[key], "new")

    def bound(
        self, path: str, g: Mapping[str, Any], i: Mapping[str, Any], side: str | None = None
    ) -> None:
        """A pinned bound. The side and the type are exact. A bound that lets in more values is a
        widening: relief for a `request` (what the server accepts), breaking for a `response` (what
        it promises to send, which clients are sized to); narrowing is the other way round."""
        side = side or g.get("side")
        for key in ("side", "type"):
            if g.get(key) != i.get(key):
                self.add(BREAKING, f"{path}.{key}", g.get(key, _MISSING), i.get(key, _MISSING))
        for facet, kind in BOUND_FACETS.items():
            old, new = g.get(facet, _MISSING), i.get(facet, _MISSING)
            if old == new:
                continue
            if new is _MISSING:
                wider = True
            elif old is _MISSING:
                wider = False
            else:
                wider = new < old if kind == "lower" else new > old
            hard = (not wider) if side == "request" else wider
            note = "widened" if wider else "narrowed"
            self.add(BREAKING if hard else ADDITIVE, f"{path}.{facet}", old, new, note)
        g_items, i_items = g.get("items", _MISSING), i.get("items", _MISSING)
        if isinstance(g_items, dict) and isinstance(i_items, dict):
            self.bound(f"{path}.items", g_items, i_items, side)
        elif g_items != i_items:
            self.add(BREAKING, f"{path}.items", g_items, i_items, "item bounds appeared or went")


def compare(golden: Mapping[str, Any], impl: Mapping[str, Any]) -> list[Finding]:
    """The findings of `impl` against `golden`: what is breaking and what is additive (C-6.3)."""
    d = _Diff(golden, impl)
    empty = [g for g in GROUPS if not golden.get(g) and g not in PIN_ADDITIONS]
    for group in empty:
        note = "no promises are recorded here"
        d.add(BREAKING, f"golden.{group}", golden.get(group, _MISSING), impl.get(group), note)
    for group, declared in DECLARED.items():
        held = golden.get(group) or {}
        for name in declared:
            pin = f"{group}.{name}"
            if (
                group not in empty
                and group not in PIN_ADDITIONS
                and pin not in PIN_ADDITIONS
                and name in impl.get(group, {})
                and name not in held
            ):
                note = "a pin this tool declares is missing: it is not new"
                d.add(BREAKING, f"golden.{pin}", _MISSING, impl[group][name], note)
    if d.out:
        return d.out
    d.exact("contract", golden["contract"], impl["contract"])
    d.exact("header", golden["header"], impl["header"])
    d.members("body_kinds", golden.get("body_kinds", {}), impl["body_kinds"])  # above 6 is new
    g, i = golden["envelope"], impl["envelope"]
    d.values("envelope.frame_types", g["frame_types"], i["frame_types"], open_=False)
    d.values("envelope.encodings", g["encodings"], i["encodings"], open_=False)
    d.members("envelope.members", g["members"], i["members"])
    for key in ("required", "per_type_required", "per_type_properties", "additional_properties"):
        d.exact(f"envelope.{key}", g[key], i[key])
    d.members("control_frames", golden.get("control_frames", {}), impl["control_frames"], d.shape)
    d.members("enums", golden.get("enums", {}), impl["enums"], d.enum)
    d.members("bounds", golden.get("bounds", {}), impl["bounds"], d.bound)
    g, i = golden["close_codes"], impl["close_codes"]
    d.values("close_codes.gateway", g["gateway"], i["gateway"], open_=True)
    d.values("close_codes.host_only", g["host_only"], i["host_only"], open_=True)
    d.members("close_codes.reasons", g["reasons"], i["reasons"])
    d.members("error_codes", golden.get("error_codes", {}), impl["error_codes"])
    d.limits(golden.get("limits", {}), impl["limits"])
    d.members("topics", golden.get("topics", {}), impl["topics"])
    g, i = golden["subprotocols"], impl["subprotocols"]
    d.values("subprotocols.offered", g["offered"], i["offered"], open_=True)
    d.exact("subprotocols.protocol", g["protocol"], i["protocol"])
    return d.out


def breaking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == BREAKING]


def _show(value: Any) -> str:
    text = "absent" if value is _MISSING else json.dumps(value)
    return text if len(text) <= 90 else text[:87] + "..."


def render(findings: Sequence[Finding]) -> str:
    """The report: the breaking findings with the `cv.v2` guidance, then the additive and known
    notes. Each finding names the golden path, both values and where the implementation's lives."""
    lines: list[str] = []
    hard = breaking(findings)
    damaged = [f for f in hard if f.path == "golden" or f.path.startswith("golden.")]
    if hard:
        n = len(hard)
        s = "s" * (n != 1)
        if len(damaged) == n:
            lines.append(f"[wire_contract] the cv.v1 golden is damaged - {n} finding{s}")
        else:
            lines.append(f"[wire_contract] cv.v1 WIRE CONTRACT CHANGED - {n} breaking finding{s}")
        for f in hard:
            note = f" ({f.note})" if f.note else ""
            if f in damaged:
                lines.append(f"  BREAKING {f.path}:{note}")
                continue
            both = f"{f.labels[0]} {_show(f.golden)}, {f.labels[1]} {_show(f.impl)}"
            lines.append(f"  BREAKING {f.path}: {both}{note}")
            if f.source:
                lines.append(f"           ({f.source})")
        if damaged:
            lines.append(DAMAGED)
        if len(damaged) < len(hard):
            lines.append(GUIDANCE)
    for f in findings:
        if f.severity == ADDITIVE:
            value = (
                _show(f.impl) if f.golden is _MISSING else f"{_show(f.golden)} -> {_show(f.impl)}"
            )
            lines.append(
                f"[wire_contract] NOTE additive: {f.path}: {f.note or 'changed'} ({value})"
            )
    return "\n".join(lines)


def render_golden(contract: Mapping[str, Any]) -> str:
    """The golden's bytes: two-space indent, an object or a list on one line where it fits in 100
    columns, one member per line where it does not, a final LF, nothing else."""

    def dump(value: Any, level: int) -> str:
        flat = json.dumps(value)
        if not isinstance(value, dict | list) or not value or len(flat) + 2 * level + 2 <= 100:
            return flat
        pad, end = "  " * (level + 1), "  " * level
        if isinstance(value, dict):
            items = (f"{pad}{json.dumps(k)}: {dump(v, level + 1)}" for k, v in value.items())
            return "{\n" + ",\n".join(items) + f"\n{end}}}"
        return "[\n" + ",\n".join(pad + dump(v, level + 1) for v in value) + f"\n{end}]"

    return dump(contract, 0) + "\n"


# --- Collection (reads the repository, imports the implementation lazily) ----------------------


def _size(type_: str) -> int:
    return int(type_[3:]) if type_.startswith("pad") else _SIZES[type_]


def _fields(raw: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Declared fields with the offset and size the declaration implies."""
    offset, out = 0, []
    for f in raw:
        entry: dict[str, Any] = {"name": f["name"], "type": f["type"]}
        entry |= {"offset": offset, "size": _size(f["type"])}
        if "enum" in f:
            entry["enum"] = list(f["enum"])
        if f.get("count"):
            entry["count"] = True
        out.append(entry)
        offset += entry["size"]
    return out


def _part(raw: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    fields = _fields(raw)
    return {"size": sum(f["size"] for f in fields), "fields": fields}


def _header(layout: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "bytes": layout["header_bytes"],
        "endianness": layout["endianness"],
        "magic": f"0x{layout['magic']:08x}",
        "fields": _fields(layout["header"]),
        "flags": list(layout["header_flags"]),
    }


def _kinds(layout: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in layout["kinds"]:
        entry: dict[str, Any] = {
            "name": k["name"],
            "format_version": k["format_version"],
            "length_rule": k["length_rule"],
            "record_stride": k["record_bytes"],
            "record": _fields(k["record"]),
        }
        for part in ("trailer", "group_prefix", "body_prefix"):
            if part in k:
                entry[part] = _part(k[part])
        out[str(k["id"])] = entry
    return out


def _json_name(value: Any) -> str:
    if value is None:
        return "null"
    for kind, name in ((bool, "boolean"), (int, "integer"), (float, "number"), (str, "string")):
        if isinstance(value, kind):
            return name
    return "array" if isinstance(value, list) else "object"


class _Bundle:
    """`packages/protocol/ws-schemas.json`: refs resolved in it, shapes walked by JSON pointer."""

    PREFIX: Final = "cv://ws/v1/"

    def __init__(self, schemas: Mapping[str, Any]) -> None:
        self.schemas = schemas

    def node(self, name: str) -> Any:
        return self.schemas[f"{self.PREFIX}{name}.schema.json"]

    def ref(self, ref: str, base: str) -> tuple[str, str, Any]:
        """(schema name, pointer, node) of a `$ref` met inside the schema `base`."""
        file_id, _, pointer = ref.partition("#")
        name = file_id.removeprefix(self.PREFIX).removesuffix(".schema.json") if file_id else base
        node = self.node(name)
        for part in (p for p in pointer.split("/") if p):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return name, pointer, node

    def types(self, node: Mapping[str, Any], base: str, depth: int = 0) -> set[str]:
        """The JSON types a schema admits, `$ref`s followed and `oneOf`/`anyOf` united."""
        if "$ref" in node and depth < 8:
            name, _, target = self.ref(node["$ref"], base)
            return self.types(target, name, depth + 1)
        declared = node.get("type")
        found: set[str] = set([declared] if isinstance(declared, str) else declared or [])
        for key in ("oneOf", "anyOf"):
            for branch in node.get(key, []):
                found |= self.types(branch, base, depth + 1)
        if not found and "const" in node:
            found.add(_json_name(node["const"]))
        if not found and "enum" in node:
            found |= {_json_name(v) for v in node["enum"]}
        return found or {"any"}

    def type_name(self, node: Mapping[str, Any], base: str) -> str:
        return "|".join(sorted(self.types(node, base)))

    def shape(self, node: Mapping[str, Any], base: str) -> dict[str, Any]:
        """Required set, member names with their JSON type, additionalProperties, minProperties."""
        additional = node.get("additionalProperties", True)
        shape: dict[str, Any] = {
            "required": sorted(node.get("required", [])),
            "members": {k: self.type_name(v, base) for k, v in sorted(node["properties"].items())},
            "additional_properties": additional if isinstance(additional, bool) else "schema",
        }
        if "minProperties" in node:
            shape["min_properties"] = node["minProperties"]
        return shape

    def _visit(self, out: dict[str, Any], name: str, pointer: str, node: Mapping[str, Any]) -> None:
        """Record the shape of every object schema reachable from `node`, keyed `schema#pointer`
        (a `$ref` target under its own key, once)."""
        if "$ref" in node:
            target, target_pointer, target_node = self.ref(node["$ref"], name)
            self._visit(out, target, target_pointer, target_node)
            return
        key = f"{name}#{pointer}" if pointer else name
        if key in out:
            return
        out[key] = self.shape(node, name) if "properties" in node else None
        for prop, sub in node.get("properties", {}).items():
            self._visit(out, name, f"{pointer}/properties/{prop}", sub)
        if isinstance(node.get("items"), dict):
            self._visit(out, name, f"{pointer}/items", node["items"])
        for combiner in ("oneOf", "anyOf"):
            for n, branch in enumerate(node.get(combiner, [])):
                self._visit(out, name, f"{pointer}/{combiner}/{n}", branch)
        if out[key] is None:
            del out[key]

    def control_frames(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in CONTROL_FRAMES:
            self._visit(out, name, "", self.node(name))
        self._visit(out, "common", "/$defs/error", self.ref("#/$defs/error", "common")[2])
        return dict(sorted(out.items()))

    def envelope(self) -> dict[str, Any]:
        env = self.node("envelope")
        per_type: dict[str, list[str]] = {}
        per_type_members: dict[str, dict[str, str]] = {}
        for clause in env.get("allOf", []):
            const = clause.get("if", {}).get("properties", {}).get("t", {}).get("const")
            then = clause.get("then", {})
            if const is not None and "required" in then:
                per_type[const] = sorted(then["required"])
            if const is not None and "properties" in then:
                per_type_members[const] = {
                    k: self.type_name(v, "envelope") for k, v in sorted(then["properties"].items())
                }
        additional = env.get("additionalProperties", True)
        return {
            "frame_types": list(env["properties"]["t"]["enum"]),
            "encodings": list(env["properties"]["e"]["enum"]),
            "members": {
                k: self.type_name(v, "envelope") for k, v in sorted(env["properties"].items())
            },
            "required": sorted(env.get("required", [])),
            "per_type_required": dict(sorted(per_type.items())),
            "per_type_properties": dict(sorted(per_type_members.items())),
            "additional_properties": additional if isinstance(additional, bool) else "schema",
        }

    def facets(self, node: Mapping[str, Any], base: str, depth: int = 0) -> dict[str, Any]:
        """The type and the bounds a schema sets, `$ref`s followed (the node's own keywords win),
        and an array's `items` the same way."""
        found: dict[str, Any] = {}
        if "$ref" in node and depth < 8:
            name, _, target = self.ref(node["$ref"], base)
            found = self.facets(target, name, depth + 1)
        found["type"] = self.type_name(node, base)
        for facet in BOUND_FACETS:
            if facet in node:
                found[facet] = node[facet]
        if isinstance(node.get("items"), dict):
            found["items"] = self.facets(node["items"], base, depth + 1)
        ordered = {"type": found["type"]}
        ordered |= {facet: found[facet] for facet in BOUND_FACETS if facet in found}
        return ordered | ({"items": found["items"]} if "items" in found else {})

    def bounds(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, (schema, pointer, side) in PINNED_BOUNDS.items():
            node = self.ref(f"#{pointer}", schema)[2]
            out[name] = {"side": side, **self.facets(node, schema)}
        return out

    def enums(self) -> dict[str, Any]:
        out = {}
        for name, (schema, pointer) in PINNED_ENUMS.items():
            node = self.ref(f"#{pointer}", schema)[2]
            out[name] = {"open": name in OPEN_ENUMS, "values": list(node["enum"])}
        return out


def _load_constants(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("_cv_ws_constants", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inconsistent(
    path: str, left: Any, right: Any, labels: tuple[str, str], source: str, note: str = ""
) -> Finding:
    """Two sources of one fact disagree: breaking, since one of them is the wire."""
    return Finding(BREAKING, f"consistency.{path}", left, right, source, note, labels)


def _facts_declared(layout: Mapping[str, Any]) -> dict[str, Any]:
    """The declaration, reduced to what the generated Python twin also states."""

    def part(raw: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        fields = _fields(raw)
        return {
            "size": sum(f["size"] for f in fields),
            "offsets": {f["name"]: f["offset"] for f in fields if not f["type"].startswith("pad")},
            "enums": {f["name"]: f["enum"] for f in fields if "enum" in f},
        }

    kinds: dict[str, Any] = {}
    for k in layout["kinds"]:
        kinds[str(k["id"])] = {
            **{key: k[key] for key in ("name", "format_version", "length_rule")},
            "record": part(k["record"]),
            **{p: part(k[p]) for p in ("trailer", "group_prefix", "body_prefix") if p in k},
        }
    return {"magic": layout["magic"], "header": part(layout["header"]), "kinds": kinds}


def _facts_twin(twin: Any) -> dict[str, Any]:
    def part(p: Any) -> dict[str, Any]:
        enums = {name: list(values) for name, values in p.enums.items()}
        return {"size": p.size, "offsets": dict(p.offsets), "enums": enums}

    kinds: dict[str, Any] = {}
    for kid, k in twin.KINDS.items():
        kinds[str(kid)] = {
            "name": k.name,
            "format_version": k.format_version,
            "length_rule": k.length_rule,
            "record": part(k.record),
            **{
                p: part(getattr(k, p))
                for p in ("trailer", "group_prefix", "body_prefix")
                if getattr(k, p)
            },
        }
    return {"magic": twin.MAGIC, "header": part(twin.HEADER), "kinds": kinds}


def _struct_code(type_: str) -> str:
    return f"{_size(type_)}x" if type_.startswith("pad") else _CODES[type_]


def _measure(frame: Any, header_bytes: int) -> tuple[int | None, int | None]:
    """(record stride, fixed bytes) that `ws.binary.encode` writes for `frame`: the stride from
    the length of the frame against the same frame without its records (or its groups' cells), the
    fixed bytes (trailer, body prefix or group prefix) from what is left."""
    from candleviewer.ws import binary

    full = len(binary.encode(frame))
    if frame.groups is not None:
        bare = dataclasses.replace(frame, groups=tuple((p, ()) for p, _ in frame.groups))
        units, cells = len(frame.groups), sum(len(c) for _, c in frame.groups)
    else:
        bare = dataclasses.replace(frame, records=())
        units, cells = 1, len(frame.records)
    bare_len = len(binary.encode(bare))
    if not units or not cells:
        return None, None
    return (full - bare_len) // cells, (bare_len - header_bytes) // units


def _length_rule(frame: Any) -> str | None:
    """`min` if `ws.binary.decode` takes a byte after `frame`, `exact` if it refuses one, and None
    when that cannot be told: the decoder refuses the frame itself, so a trailing byte proves
    nothing. For a kind whose body counts its own rows, the count's finding names the cause (a
    heatmap whose header count is not 1). For any other kind, a sample that the decoder refuses
    yields no length-rule finding; the codec's round-trip test catches it."""
    from candleviewer.ws import binary

    plain = binary.encode(frame)
    try:
        binary.decode(plain)
    except binary.FrameMalformedError:
        return None
    try:
        binary.decode(plain + b"\x00")
    except binary.FrameMalformedError:
        return "exact"
    return "min"


def _layout_findings(layout: Mapping[str, Any]) -> list[Finding]:
    """The declaration against its own sums, the generated twin and the codec's bytes."""
    from candleviewer.ws import binary
    from candleviewer.ws._generated import cvwb_layout as twin
    from candleviewer.ws.cvwb_vectors import vector_frames

    out: list[Finding] = []
    header = _part(layout["header"])["size"]
    if header != layout["header_bytes"]:
        labels = ("declared", "the fields' sum")
        out.append(
            _inconsistent(
                "header.bytes", layout["header_bytes"], header, labels, _SOURCES["header"]
            )
        )
    for k in layout["kinds"]:
        total = _part(k["record"])["size"]
        if total != k["record_bytes"]:
            labels = ("record_bytes", "the fields' sum")
            path = f"body_kinds.{k['id']}.record_stride"
            out.append(
                _inconsistent(path, k["record_bytes"], total, labels, _SOURCES["body_kinds"])
            )

    twin_diff = _Diff({}, {})
    twin_diff.exact("twin", _facts_declared(layout), _facts_twin(twin))
    for f in twin_diff.out:
        regenerate = (
            "run `pnpm generate`: cvwb-layout.json -> services/api/candleviewer/ws/_generated"
        )
        labels = ("declaration", "generated twin")
        out.append(
            _inconsistent(f.path.removeprefix("twin."), f.golden, f.impl, labels, regenerate)
        )

    src = f"{_API}/binary.py (encode, decode), observed on ws/cvwb_vectors.vector_frames()"
    labels = ("declaration", "ws/binary.py")
    declared = {k["id"]: k for k in layout["kinds"]}
    head = "<" + "".join(_struct_code(f["type"]) for f in layout["header"])
    frames: dict[int, list[Any]] = {}
    for _, frame in vector_frames():
        frames.setdefault(frame.body_kind, []).append(frame)
        magic, version, kind = struct.unpack_from(head, binary.encode(frame))[:3]
        wanted = declared.get(frame.body_kind, {}).get("format_version")
        for what, want, got in (
            ("magic", layout["magic"], magic),
            ("format_version", wanted, version),
            ("body_kind", frame.body_kind, kind),
        ):
            if want != got:
                out.append(_inconsistent(f"header.{what}", want, got, labels, src, f"kind {kind}"))
    for kid, k in sorted(declared.items()):
        sample = max(frames.get(kid, []), key=lambda f: len(binary.encode(f)), default=None)
        if sample is None:
            out.append(
                _inconsistent(f"body_kinds.{kid}", "a layout", "no vector frame", labels, src)
            )
            continue
        stride, fixed = _measure(sample, layout["header_bytes"])
        if "group_prefix" in k:
            want_fixed = _part(k["group_prefix"])["size"]
        else:
            want_fixed = sum(_part(k[p])["size"] for p in ("trailer", "body_prefix") if p in k)
        checks: list[tuple[str, Any, Any]] = [
            ("record_stride", k["record_bytes"], stride),
            ("fixed_bytes", want_fixed, fixed),
        ]
        if (rule := _length_rule(sample)) is not None:
            checks.append(("length_rule", k["length_rule"], rule))
        for what, want, got in checks:
            if want != got:
                out.append(
                    _inconsistent(f"body_kinds.{kid}.{what}", want, got, labels, src, k["name"])
                )
    return out


def _frame_units(layout: Mapping[str, Any], found: list[Finding]) -> dict[str, int]:
    """The header `record_count` of each kind whose body counts its own rows (a counted body
    prefix), as `ws.binary.encode` writes it for every vector frame of the kind: one unit per
    frame (23 section 3.4). A decoder may take that count as the rule (it is the one a frame
    carries), so a server that wrote another is a change to the wire, and it is pinned."""
    from candleviewer.ws import binary
    from candleviewer.ws.cvwb_vectors import vector_frames

    head = {f["name"]: f for f in _fields(layout["header"])}["record_count"]
    code, at = "<" + _struct_code(head["type"]), head["offset"]
    counted = {
        k["id"]: k["name"]
        for k in layout["kinds"]
        if any(f.get("count") for f in _fields(k.get("body_prefix", [])))
    }
    counts: dict[int, set[int]] = {}
    for _, frame in vector_frames():
        if frame.body_kind in counted:
            data = binary.encode(frame)
            counts.setdefault(frame.body_kind, set()).add(struct.unpack_from(code, data, at)[0])
    src = f"{_API}/binary.py (encode), observed on ws/cvwb_vectors.vector_frames()"
    units: dict[str, int] = {}
    for kid, name in sorted(counted.items()):
        seen = counts.get(kid, set())
        if len(seen) != 1:
            path, labels = f"body_kinds.{kid}.header_record_count", ("one count", "ws/binary.py")
            found.append(_inconsistent(path, "one count", sorted(seen), labels, src, name))
            continue
        units[str(kid)] = next(iter(seen))
    return units


def _close_codes(found: list[Finding]) -> dict[str, Any]:
    """Every `bye` reason with the (code, reconnect) its builders answer, which must be one answer;
    and the code sets."""
    from candleviewer.ws import lifecycle
    from candleviewer.ws.gateway import SERVER_RESTART_CLOSE
    from candleviewer.ws.revocation import RevocationHub

    src, labels = _SOURCES["close_codes"], ("lifecycle.bye_frame", "RevocationHub.close_for")
    hub = RevocationHub()
    reasons: dict[str, Any] = {}
    by_code = sorted(lifecycle.CLOSE_REASONS, key=lambda r: (int(lifecycle.CLOSE_REASONS[r][0]), r))
    for reason in by_code:
        p = lifecycle.bye_frame(reason)["p"]
        entry = {"code": p["code"], "reconnect": p["reconnect"]}
        if reason in REVOCATION_REASONS:
            frame, close_code = hub.close_for(reason)
            wire = {"code": frame["p"]["code"], "reconnect": frame["p"]["reconnect"]}
            path = f"close_codes.reasons.{reason}"
            if close_code != wire["code"]:
                found.append(_inconsistent(f"{path}.code", wire["code"], close_code, labels, src))
            if wire != entry:
                note = "two builders answer one reason"
                found.append(_inconsistent(path, entry, wire, labels, src, note))
        reasons[reason] = entry
    return {
        "gateway": sorted(int(c) for c in lifecycle.CloseCode),
        "host_only": [SERVER_RESTART_CLOSE],
        "reasons": reasons,
    }


def _error_codes(bundle: _Bundle, found: list[Finding]) -> dict[str, Any]:
    from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES

    out: dict[str, Any] = {}
    for code in sorted(WS_ERROR_CODES, key=lambda c: c.value):
        meta = ERROR_META[code]
        out[code.value] = {
            "scope": meta.scope,
            "retryable": meta.retryable,
            "close_code": meta.close_code,
        }
    schema_codes = sorted(bundle.ref("#/$defs/errorCode", "common")[2]["enum"])
    if schema_codes != sorted(out):
        labels = ("common#/$defs/errorCode", "ERROR_META")
        found.append(
            _inconsistent("error_codes", schema_codes, sorted(out), labels, _SOURCES["error_codes"])
        )
    return out


def _limits() -> dict[str, Any]:
    """`welcome.limits` as `welcome_payload`, the builder of the frame, advertises it."""
    from candleviewer.ws import lifecycle

    welcome = lifecycle.welcome_payload(
        encoding="json",
        server_version="0",
        git_sha="0",
        connection_id="c",
        server_time_ms=0,
        client_clock_ms=None,
        features={},
    )
    return {k: {LIMIT_BOUNDS.get(k, "seen"): v} for k, v in welcome["limits"].items()}


def _topics(found: list[Finding], constants: Path) -> dict[str, str]:
    from candleviewer.ws.topics import FAMILIES

    out: dict[str, str] = {}
    for fam in FAMILIES.values():
        for pattern in fam.patterns:
            for old, new in PLACEHOLDER_ALIASES.items():
                pattern = pattern.replace("{" + old + "}", "{" + new + "}")
            out[pattern] = fam.payload_schema
    documented = sorted(_load_constants(constants).TOPIC_PATTERNS)
    if documented != sorted(out):
        labels = ("ws_constants.TOPIC_PATTERNS", "FAMILIES")
        found.append(_inconsistent("topics", documented, sorted(out), labels, _SOURCES["topics"]))
    return out


def collect(
    *, layout_path: Path = LAYOUT, bundle_path: Path = BUNDLE, constants_path: Path = CONSTANTS
) -> Collected:
    """The contract the implementation speaks, with every place its own sources disagree."""
    from candleviewer.ws import lifecycle

    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    bundle = _Bundle(json.loads(bundle_path.read_text(encoding="utf-8"))["schemas"])
    found = _layout_findings(layout)
    envelope = bundle.envelope()
    frame_types = list(_load_constants(constants_path).FRAME_TYPES)
    if sorted(frame_types) != sorted(envelope["frame_types"]):
        labels = ("ws_constants.FRAME_TYPES", "the envelope schema")
        path = "envelope.frame_types"
        found.append(
            _inconsistent(path, frame_types, envelope["frame_types"], labels, _SOURCES["envelope"])
        )
    kinds = _kinds(layout)
    for kid, count in _frame_units(layout, found).items():
        kinds[kid]["header_record_count"] = count
    contract = {
        "contract": CONTRACT,
        "header": _header(layout),
        "body_kinds": kinds,
        "envelope": envelope,
        "control_frames": bundle.control_frames(),
        "enums": bundle.enums(),
        "bounds": bundle.bounds(),
        "close_codes": _close_codes(found),
        "error_codes": _error_codes(bundle, found),
        "limits": _limits(),
        "topics": _topics(found, constants_path),
        "subprotocols": {"offered": list(lifecycle.SUPPORTED_SUBPROTOCOLS), "protocol": CONTRACT},
    }
    return Collected(contract, found)


# --- CLI ---------------------------------------------------------------------------------------


def check(golden: Mapping[str, Any], collected: Collected) -> list[Finding]:
    """What the implementation disagrees with itself on, then what it changed since the golden. A
    golden that cannot be read as a golden (a member missing from a group) is one finding."""
    try:
        changed = compare(golden, collected.contract)
    except (KeyError, TypeError, AttributeError, IndexError, ValueError, StopIteration) as exc:
        note = f"the golden is malformed - {type(exc).__name__} {exc}".rstrip()
        changed = [Finding(BREAKING, "golden", _MISSING, _MISSING, note=note)]
    return [*collected.findings, *changed]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="compare with the golden (the default)")
    mode.add_argument(
        "--write",
        action="store_true",
        help="create the golden, at the first freeze only; refuses if it exists",
    )
    mode.add_argument(
        "--extend", action="store_true", help="rewrite the golden if the diff is additive"
    )
    ap.add_argument("--golden", type=Path, default=GOLDEN, help="the golden file (tests only)")
    args = ap.parse_args(argv)
    path: Path = args.golden
    collected = collect()
    if args.write:
        if path.exists():
            print(
                f"[wire_contract] {path} exists: cv.v1 is frozen; --extend adds.", file=sys.stderr
            )
            return 1
        if breaking(collected.findings):
            print(render(collected.findings), file=sys.stderr)
            print(
                "[wire_contract] not writing a golden its own sources disagree on.", file=sys.stderr
            )
            return 1
        path.write_text(render_golden(collected.contract), encoding="utf-8", newline="\n")
        print(f"[wire_contract] wrote {path}")
        return 0
    if not path.exists():
        print(
            f"[wire_contract] {path} is missing: restore it from git "
            f"(`git restore -- {GOLDEN_PATH}`). --write creates the golden once, at the first "
            "freeze, and cv.v1 is frozen.",
            file=sys.stderr,
        )
        return 1
    try:
        golden = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(
            f"[wire_contract] {path} is not valid JSON ({exc}): restore it from git.",
            file=sys.stderr,
        )
        return 1
    findings = check(golden, collected)
    report = render(findings)
    if breaking(findings):
        print(report, file=sys.stderr)
        return 1
    if report:
        print(report)
    if args.extend:
        path.write_text(render_golden(collected.contract), encoding="utf-8", newline="\n")
        print(f"[wire_contract] extended {path}")
    else:
        print("[wire_contract] OK: the implementation keeps every promise of the cv.v1 golden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
