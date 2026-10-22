"""Server-written rule IR hash vectors (E37-T01, #951): what the server hashes for a request body.

``packages/fixtures/golden/rule-ir/hash_vectors.json`` holds, per body, the server's canonical
bytes, ``ir_hash`` and form reasons, or where it refuses the body: the reference that the client
mirror in ``packages/rule-graph`` (E37-T01) is held to, on the ``js: true`` vectors. They follow
the HTTP path: ``json.loads`` (floats), ``Rule.model_validate``, hash. Three quirks are pinned, not
fixed (C-Q2: a JSON ``1.0`` const is ``true``; C-Q1: compile returns a Decimal const as its ``str``;
save hashes the sent ``version`` but stores its own), so a client hashes what it sends and never
re-hashes what it loads. Regenerate from ``services/api`` and review the diff (nothing is written
otherwise): ``CV_REGEN_GOLDEN=1 uv run pytest tests/rules/roundtrip/test_client_hash_vectors.py``.
"""

from __future__ import annotations

import copy
import json
import math
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.ir import IR_HASH_VERSION, Rule, canonicalize, ir_hash, parse_ir_json
from candleviewer.rules.ir.canonical import IrValueError
from candleviewer.rules.ir.form import form_incompatibility_reasons
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules.roundtrip.chain import reorder_keys

VECTORS = Path(__file__).resolve().parents[5] / "packages/fixtures/golden/rule-ir/hash_vectors.json"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"
REGEN_CMD = "CV_REGEN_GOLDEN=1 uv run pytest tests/rules/roundtrip/test_client_hash_vectors.py"
NOTE = (
    f"GENERATED - do not hand-edit. Regenerate from services/api with `{REGEN_CMD}` and review the "
    "diff. A changed canonical or ir_hash means the server's hash moved: bump IR_HASH_VERSION and "
    "ship an upcaster. Fields: name is <source>/<slug>; kind is corpus, edge, quirk or refused; "
    "ir is the request body as sent; js is true when JSON.stringify(JSON.parse(ir)) sends the "
    "server the same values, and the client mirror is held to the js:true vectors only; "
    "canonical, ir_hash and form_reasons are the server's canonical bytes, their hash and the "
    "form-incompatibility reasons; refused is schema (the model refuses the body) or value (the "
    "canonical form cannot hold a value); same_as names a vector with the same canonical, "
    "differs_from one with another ir_hash. Quirks, pinned, not fixed: C-Q1, compile returns a "
    "Decimal const as its str (1E-7), which re-hashes as text; C-Q2, a JSON 1.0 or 0.0 const reads "
    "as true or false; and save hashes the sent version but stores its own. The client rule: hash "
    "what you send, never re-hash what you load."
)
SLOT, KEEP = "__slot__", object()  # KEEP: that part of form_simple_0 stays as it is
REFS = {  # checked by the writer: an identical canonical (same_as), another ir_hash (differs_from)
    "edge/metric-param-spelling": {"same_as": "edge/metric-param-fraction"},
    "edge/key-order-reversed": {"same_as": "edge/unicode-keys"},
    "edge/presentation-and-metadata": {"same_as": "edge/base"},
    "edge/returned-ir-metric-param": {"same_as": "edge/metric-param-tiny"},
    "quirk/returned-ir-const": {"differs_from": "edge/const-tiny"},
    "quirk/stored-version": {"differs_from": "edge/sent-version"},
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


BASE: dict[str, Any] = json.loads(read_text(FIXTURES / "rule_ir" / "form_simple_0.json"))


def dump(obj: object, spelling: str = "", *, sort: bool = False) -> str:
    """Compact JSON text, as a client sends it; ``spelling`` replaces the ``SLOT`` string."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=sort)
    return text.replace(f'"{SLOT}"', spelling) if spelling else text


def js_safe(o: object) -> bool:
    """JS round-trips it unchanged: no integral or non-finite float, and no int beyond 2**53 unless
    it is an exact double below 1e21, which JS prints back digit for digit."""
    if isinstance(o, dict | list):
        return all(map(js_safe, o.values() if isinstance(o, dict) else o))
    if isinstance(o, float):
        return math.isfinite(o) and not o.is_integer()
    if isinstance(o, int):
        return abs(o) <= 2**53 or (abs(o) < 10**21 and int(Decimal(repr(float(o)))) == o)
    return True


def edited(*, left: Any = KEEP, right: Any = KEEP, act: Any = KEEP, **top: Any) -> dict[str, Any]:
    """``form_simple_0`` with its metric params, right const, action params or top keys set."""
    doc: dict[str, Any] = copy.deepcopy({**BASE, **top})
    if left is not KEEP:
        doc["conditions"]["left"]["params"] = left
    if right is not KEEP:
        doc["conditions"]["right"]["const"] = right
    if act is not KEEP:
        doc["actions"][0]["params"] = act
    return doc


def returned(ir: str) -> str:
    """The IR compile returns for the body ``ir``: ``json.loads(rule.model_dump_json())``."""
    return dump(json.loads(Rule.model_validate(json.loads(ir)).model_dump_json()))


def targeted() -> dict[str, str]:
    """``form_simple_0`` with one change each, as request bodies, in file order."""
    cmp, act = BASE["conditions"], BASE["actions"][0]
    keys = edited(act={"channel": "ui", "B": "1", "b": "2", "\xe9": "3", "\U0000ffff": "4",
                       "\U0001f600": "5"})  # fmt: skip
    fractions = {"channel": "ui", "weight": 0.5, "ratio": 0.30000000000000004, "tiny": 1e-7,
                 "small": 2.5e-7}  # fmt: skip
    nulls = edited(left={"n": 14, "threshold": None}, act={"channel": "ui", "note": None})
    shown = edited(editor="graph", created_by="00000000-0000-4000-8000-0000000000cd",
                   created_at=1, updated_at=2, graph_layout={"positions": {"c1": {"x": 5, "y": 7}},
                   "collapsed": ["c1"], "comments": [{"id": "k1", "text": "note"}]})  # fmt: skip
    scope = {"level": "account", "account_ids": ["00000000-0000-4000-8000-0000000000AC"]}
    account = {**cmp, "left": {**cmp["left"], "account_id": "00000000-0000-4000-8000-0000000000AD"}}
    acts = [{**act, "node_id": "a10"}, {**act, "node_id": "a2"}]
    c2 = {**cmp, "node_id": "c2", "right": {"const": 123456789012345680}}
    g1 = {"node_id": "g1", "op": "all_of", "children": [{**cmp, "right": {"const": 10**20}}, c2]}
    notional = {"max_notional_per_fire": "1000.00", "max_daily_notional": "2000.0"}
    decimals = edited(conditions={**cmp, "tolerance": "0.10"}, limits=notional)
    t = {
        "edge/base": dump(BASE),
        "edge/uuid-uppercase": dump(edited(rule_id="00000000-0000-4000-8000-0000000000AB")),
        "edge/account-ids-uppercase": dump(edited(scope=scope, conditions=account)),
        "edge/action-param-fractions": dump(edited(act=fractions)),
        "edge/metric-param-fraction": dump(edited(left={"n": 14, "threshold": 0.5})),
        "edge/metric-param-spelling": dump(edited(left={"n": 14, "threshold": SLOT}), "5E-1"),
        "edge/param-nulls": dump(nulls),
        "edge/unicode-keys": dump(keys),
        "edge/key-order-reversed": dump(reorder_keys(keys)),
        "edge/string-escapes": dump(edited(name='q"b\\s\x01\x7f\U00002028\xe9\U0001f600\t')),
        "edge/presentation-and-metadata": dump(shown),
        "edge/renumbering": dump(edited(actions=acts, conditions={**cmp, "node_id": "zz"})),
        "edge/big-integers": dump(edited(conditions=g1)),
        "edge/decimal-strings": dump(decimals),
        "edge/numeric-string-const": dump(edited(right="1.50")),
        "edge/const-true": dump(edited(right=True)),
        "edge/const-minus-zero": dump(edited(right=SLOT), "-0"),
        "edge/const-tiny": dump(edited(right=1e-7)),
        "edge/metric-param-tiny": dump(edited(left={"n": 14, "k": 1e-7})),
        "edge/sent-version": dump(edited(version=7)),
        "quirk/const-one-point-zero": dump(edited(right=SLOT), "1.0"),
        "quirk/const-zero-point-zero": dump(edited(right=SLOT), "0.0"),
    }
    t["quirk/returned-ir-const"] = returned(t["edge/const-tiny"])
    t["edge/returned-ir-metric-param"] = returned(t["edge/metric-param-tiny"])
    stored = Rule.model_validate(json.loads(t["edge/sent-version"])).model_dump(mode="json")
    return t | {
        # save stores version 1 (manager.py); its own rule_id, mode and enabled overrides left out
        "quirk/stored-version": dump({**stored, "version": 1}),
        "refused/metric-params-null": dump(edited(left=None)),
        "refused/metric-param-object": dump(edited(left={"n": {"a": 1}})),
        "refused/metric-param-nan": dump(edited(left={"n": SLOT}), "NaN"),
        "refused/action-param-nan": dump(edited(act={"channel": "ui", "w": SLOT}), "NaN"),
        "refused/lone-surrogate": dump(edited(name=SLOT), '"x\\ud800"'),
        "refused/action-param-key-surrogate": dump(edited(act={SLOT: "x"}), '"\\ud800"'),
        "refused/action-param-surrogate": dump(edited(act={"note": SLOT}), '"\\udc00"'),
        "refused/metric-param-surrogate": dump(edited(left={"n": SLOT}), '"\\ud800"'),
        "refused/node-id-surrogate": dump(edited(conditions={**cmp, "node_id": SLOT}), '"\\ud800"'),
        "refused/layout-surrogate": dump(edited(graph_layout={SLOT: 1}), '"\\udc00"'),
        "refused/unknown-key": dump(edited(variables={})),
    }


def vector(name: str, ir: str) -> dict[str, object]:
    """``ir``'s vector as the routes compute it; a refusal is named by the step that raises."""
    kind = name.split("/")[0]
    out: dict[str, object] = {"name": name, "kind": kind, "ir": ir, "js": js_safe(json.loads(ir))}
    try:
        rule = Rule.model_validate(json.loads(ir))
        canonical = canonicalize(rule).decode("utf-8")
    except ValidationError:  # pydantic refuses the document
        return out | {"refused": "schema"}
    except IrValueError:  # the canonical form cannot hold a value
        return out | {"refused": "value"}
    out |= {"canonical": canonical, "ir_hash": ir_hash(rule)} | REFS.get(name, {})
    return out | {"form_reasons": form_incompatibility_reasons(rule)}


def build() -> list[dict[str, object]]:
    """Every vector in file order: the 30-rule corpus, then the targeted documents."""
    corpus = sorted((FIXTURES / "rule_corpus").glob("[0-9][0-9]_*.json"))
    docs = [(f"corpus/{p.stem}", dump(json.loads(read_text(p)))) for p in corpus]
    return [vector(name, ir) for name, ir in [*docs, *targeted().items()]]


def render(vectors: list[dict[str, object]]) -> str:
    """The file: a fixed head, then one compact vector per line (LF, final newline)."""
    head = f'{{\n  "$note": {json.dumps(NOTE)},\n  "ir_hash_version": {IR_HASH_VERSION},\n'
    rows = ",\n    ".join(dump(v, sort=True) for v in vectors)
    return f'{head}  "vectors": [\n    {rows}\n  ]\n}}\n'


VECS = build()
BY_NAME = {str(v["name"]): v for v in VECS}


def test_hash_vectors_file_is_byte_identical_to_what_the_server_writes() -> None:
    want = render(VECS).encode("utf-8")
    if REGEN:
        VECTORS.parent.mkdir(parents=True, exist_ok=True)
        VECTORS.write_bytes(want)
    same = VECTORS.is_file() and VECTORS.read_bytes() == want
    assert same, f"{VECTORS.name} is missing or stale: run `{REGEN_CMD}` from services/api"


def test_hash_vectors_corpus_entries_match_the_corpus_goldens() -> None:
    """All 30 goldens hold on the HTTP path (corpus 01 and 12 have fractional action params)."""
    goldens = json.loads(read_text(FIXTURES / "rule_corpus" / "golden_hashes.json"))["hashes"]
    want = {f"corpus/{n.removesuffix('.json')}": h for n, h in goldens.items()}
    assert {v["name"]: v.get("ir_hash") for v in VECS if v["kind"] == "corpus"} == want


def test_hash_vectors_js_vectors_hash_alike_on_the_decimal_path() -> None:
    js = [v for v in VECS if v["js"] is True and "ir_hash" in v]
    decimal = {v["name"]: ir_hash(parse_ir_json(str(v["ir"]))) for v in js}
    assert decimal == {v["name"]: v["ir_hash"] for v in js}


def test_hash_vectors_references_resolve_and_hold() -> None:
    assert len(BY_NAME) == len(VECS), "vector names are not unique"
    assert set(REFS) <= set(BY_NAME), "a REFS entry names no vector"
    for v in VECS:
        if "same_as" in v:
            assert v["canonical"] == BY_NAME[str(v["same_as"])]["canonical"], v["name"]
        if "differs_from" in v:
            assert v["ir_hash"] != BY_NAME[str(v["differs_from"])]["ir_hash"], v["name"]


def test_quirk_const_one_point_zero_canonicalises_as_a_bool() -> None:
    """Recorded quirk C-Q2, pinned, not fixed (#951); JS never sends ``1.0`` (nor ``0.0``)."""
    for name, flag, number in (("one", "true", "1"), ("zero", "false", "0")):
        v = BY_NAME[f"quirk/const-{name}-point-zero"]
        assert f'"const":{flag}' in str(v["canonical"]) and v["js"] is False
        assert f'"const":"{number}"' in canonicalize(parse_ir_json(str(v["ir"]))).decode()


def test_quirk_returned_ir_rebuilt_like_compile_does_not_rehash_to_its_ir_hash() -> None:
    """Recorded quirk C-Q1, pinned, not fixed (#951): the IR rebuilt as ``api/rules.py`` returns it
    holds the const as the string ``1E-7``. A metric param comes back canonical (#4132)."""
    sent, back = BY_NAME["edge/const-tiny"], BY_NAME["quirk/returned-ir-const"]
    assert back["ir"] == returned(str(sent["ir"])) and '"right":{"const":"1E-7"}' in str(back["ir"])
    assert back["ir_hash"] != sent["ir_hash"]


async def test_quirk_save_hashes_the_sent_version_and_stores_latest_version() -> None:
    sent = json.loads(str(BY_NAME["edge/sent-version"]["ir"]))
    sent["actions"][0]["params"] |= {"severity": "info", "template": "x"}  # save checks semantics
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    actor = Actor("u1", "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)
    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: mgr, lambda _request: actor))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        made = await client.post("/rules", json={"ir": sent})
        assert made.status_code == 201, made.text
        rid, version = made.json()["id"], made.json()["version"]
        stored = (await client.get(f"/rules/{rid}/versions/{version['id']}")).json()["ir"]
    hashed = {**sent, "rule_id": rid, "mode": "disabled", "enabled": False}
    assert sent["version"] == 7 and version["ir_hash"] == ir_hash(hashed)
    # recorded quirk: pinned, not fixed (#951)
    assert stored["version"] == 1 and ir_hash(Rule.model_validate(stored)) != version["ir_hash"]


def test_refused_vectors_are_refused_where_they_say() -> None:
    for v in VECS:
        assert ("refused" in v) == (v["kind"] == "refused"), v["name"]
        if v.get("refused") == "schema":
            with pytest.raises(ValidationError):
                Rule.model_validate(json.loads(str(v["ir"])))
        elif v.get("refused") == "value":
            with pytest.raises(IrValueError):
                canonicalize(Rule.model_validate(json.loads(str(v["ir"]))))
