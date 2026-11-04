"""Smoke test of the E29 OMS scenario pack and its loader (E29-Q01, #844, BQ-3).

Every scenario directory of `packages/fixtures/oms/` is checked by name, so a scenario added later
is covered with no edit here: its manifest meets the schema, every file it reads parses, every
derived file names sources that exist and keeps their shape, its evidence class is the corpus's,
it names the plan's cases, two loads of it are byte-identical, and loading it touches no network.
Derived files are outside the corpus drift check
(`tests/contract/bybit/test_contract_trading_drift.py`), so this is the only parse check they
get. A template's slots (the AC-15 inputs) fill from a seed and leak no value. The loader's own
rules are driven on planted scenarios in a temporary pack.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests import _oms_fixtures as pack
from tests._corpus import CORPUS_ROOT
from tests._oms_fixtures import PackError, UnstubbedCall, load, path_of, scenario_names
from tests.contract.bybit.test_contract_trading_drift import disagreements

NAMES = scenario_names()
CORPUS = f"../{CORPUS_ROOT.name}/2026-10-05"
#: Corpus files of each evidence class, by the `source` their corpus manifest entry states.
TRANSCRIBED_REST = f"{CORPUS}/rest/trading-error-110017.json"
READ_REST = f"{CORPUS}/rest/trading-order-realtime.json"
BUILT_REST = f"{CORPUS}/rest/error_503.json"  # documented-shape: built, not captured
RECORDED_REST = f"{CORPUS}/rest/risk_limit_BTCUSDT.json"
TRANSCRIBED_WS = f"{CORPUS}/ws/private-execution.jsonl"
DERIVED_WS = f"{CORPUS}/ws/public-subscribe-ack-derived.jsonl"
RECORDED_WS = f"{CORPUS}/ws/recorded_tickers_BTCUSDT.jsonl"
CREATE = "POST /v5/order/create"
FRAMES = "".join(f'{{"n":{n}}}\n' for n in range(4))


def test_the_pack_holds_a_scenario_and_a_valid_schema() -> None:
    assert "ws_duplicate_exec" in NAMES
    Draft202012Validator.check_schema(pack.schema())


@pytest.mark.parametrize("name", NAMES)
def test_a_scenario_loads_and_its_manifest_meets_the_schema(name: str) -> None:
    validator = Draft202012Validator(pack.schema())
    assert [e.message for e in validator.iter_errors(pack.manifest(name))] == []
    assert load(name).name == name


@pytest.mark.parametrize("name", NAMES)
def test_every_file_a_scenario_reads_parses(name: str) -> None:
    scenario = load(name)
    assert scenario.files  # a scenario reads at least the file it delivers
    for ref in scenario.files:
        text = path_of(name, ref).read_text(encoding="utf-8")
        if ref.endswith(".jsonl"):
            lines = text.splitlines()
            assert lines
            assert all(isinstance(json.loads(line), dict) for line in lines), ref
        else:
            assert isinstance(json.loads(text), dict), ref


@pytest.mark.parametrize("name", NAMES)
def test_a_derived_file_names_sources_that_exist(name: str) -> None:
    for ref, entry in pack.manifest(name).get("files", {}).items():
        assert entry["derived_from"], ref
        for source in entry["derived_from"]:
            assert path_of(name, source).is_file(), f"{ref} is derived from {source}"


def kind(frame: dict[str, Any]) -> str:
    """What a frame is of: its topic, its reply `op`, or `body` (a REST reply)."""
    return str(frame.get("topic") or frame.get("op") or "body")


@pytest.mark.parametrize("name", NAMES)
def test_a_derived_file_keeps_the_shape_of_the_corpus_file_of_its_kind(name: str) -> None:
    """Never invent a payload shape (README): each derived frame or body has the field paths and
    JSON types of its source's frame of the same kind: values changed, no key added or dropped."""
    for ref, entry in pack.manifest(name).get("files", {}).items():
        texts = [path_of(name, s).read_text(encoding="utf-8") for s in entry["derived_from"]]
        sources = [json.loads(line) for text in texts for line in text.splitlines()]
        for line in path_of(name, ref).read_text(encoding="utf-8").splitlines():
            frame = json.loads(line)
            [source] = [s for s in sources if kind(s) == kind(frame)]
            assert disagreements(source, frame) == [], f"{name}/{ref}"


def test_the_pack_loads_byte_identically_in_any_order() -> None:
    forward = {name: load(name).canonical() for name in NAMES}
    backward = {name: load(name).canonical() for name in reversed(NAMES)}
    assert forward == backward


@pytest.mark.parametrize("name", NAMES)
def test_two_loads_of_a_scenario_are_byte_identical(name: str) -> None:
    first, second = load(name), load(name)
    assert first == second
    assert first.canonical() == second.canonical()
    assert first.delivered_frames() == second.delivered_frames()


@pytest.mark.parametrize("name", NAMES)
def test_loading_a_scenario_touches_no_network(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("the loader reached for the network")

    for attribute in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, attribute, refuse)
    for attribute in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection"):
        monkeypatch.setattr(socket, attribute, refuse)
    load(name)


def test_the_loader_imports_nothing_that_reaches_a_network() -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(Path(pack.__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    reaching = {"socket", "ssl", "http", "urllib", "httpx", "requests", "aiohttp", "websockets"}
    reaching |= {"ftplib", "smtplib", "telnetlib", "xmlrpc", "subprocess", "asyncio"}
    assert imported >= {"json", "hashlib", "jsonschema", "tests"}  # the walk saw the imports
    assert not imported & reaching


def test_the_duplicate_scenario_delivers_the_transcribed_frame_twice() -> None:
    source = CORPUS_ROOT / "2026-10-05" / "ws" / "private-execution.jsonl"
    [frame] = source.read_text(encoding="utf-8").splitlines()
    scenario = load("ws_duplicate_exec")
    assert scenario.delivered_frames() == (frame, frame)
    assert (scenario.manifest["evidence"], scenario.manifest["rules"]) == ("derived", ["S4"])


# -- the loader's rules, on planted scenarios in a temporary pack -------------------------------


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A pack with the real schema and no scenario."""
    pack_root = tmp_path / "oms"
    pack_root.mkdir()
    shutil.copy(pack.PACK_ROOT / pack.SCHEMA, pack_root / pack.SCHEMA)
    return pack_root


def plant(root: Path, name: str, contents: dict[str, str] | None = None, **changes: Any) -> None:
    """Scenario `name` holding the files `contents` names: the smallest sound manifest, then
    `changes` (a key set to `None` is removed)."""
    sound: dict[str, Any] = {
        "$schema": "../manifest.schema.json",
        "scenario": name,
        "origin": "plan",
        "description": "A planted scenario.",
        "environment": "demo",
        "evidence": "docs-transcribed",
        "rules": [],
        "cases": [],
        "rest": {CREATE: {"payload": TRANSCRIBED_REST}},
        "expected": "Nothing happens.",
        "consumers": ["E29-Q02"],
    }
    manifest = {k: v for k, v in (sound | changes).items() if v is not None}
    (root / name).mkdir()
    (root / name / pack.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    for file, text in (contents or {}).items():
        (root / name / file).write_text(text, encoding="utf-8")


def frames_scenario(root: Path, name: str, text: str, **changes: Any) -> None:
    """Scenario `name` delivering one derived `frames.jsonl` holding `text`."""
    derived = {"derived_from": [TRANSCRIBED_WS], "derivation": "planted"}
    sound: dict[str, Any] = {
        "evidence": "derived",
        "rest": None,
        "ws": {"private": ["frames.jsonl"]},
        "files": {"frames.jsonl": derived},
    }
    plant(root, name, {"frames.jsonl": text}, **(sound | changes))


def refused(root: Path, name: str, rule: str) -> None:
    with pytest.raises(PackError, match=rule) as error:
        load(name, root)
    assert str(error.value).startswith(f"{name}: ")


def test_a_stub_answers_with_its_corpus_file_and_status_and_an_unstubbed_call_raises(
    root: Path,
) -> None:
    stubs = {
        CREATE: {"payload": TRANSCRIBED_REST},
        "GET /v5/order/realtime": {"payload": READ_REST},
        "POST /v5/order/cancel": {"payload": BUILT_REST, "http_status": 503},
    }
    plant(root, "stubs", evidence="derived", rest=stubs)
    scenario = load("stubs", root)
    reply = scenario.reply("POST", "/v5/order/create")
    assert (reply.status, reply.payload) == (200, TRANSCRIBED_REST)
    assert reply.body == {"retCode": 110017, "retMsg": "orderQty will be truncated to zero"}
    assert scenario.reply("GET", "/v5/order/realtime").body["retCode"] == 0
    assert scenario.reply("POST", "/v5/order/cancel").status == 503
    with pytest.raises(UnstubbedCall, match="stubs: no stub answers GET /v5/position/list"):
        scenario.reply("GET", "/v5/position/list")


@pytest.mark.parametrize(
    ("ref", "evidence"),
    [
        (TRANSCRIBED_REST, "docs-transcribed"),
        (BUILT_REST, "derived"),
        (RECORDED_REST, "recorded"),
        (TRANSCRIBED_WS, "docs-transcribed"),
        (DERIVED_WS, "derived"),
        (RECORDED_WS, "recorded"),
    ],
)
def test_a_delivered_corpus_file_s_class_comes_from_the_corpus_manifest(
    root: Path, ref: str, evidence: str
) -> None:
    side: dict[str, Any] = {"rest": {CREATE: {"payload": ref}}}
    if "/ws/" in ref:
        side = {"rest": None, "ws": {"private": [ref]}}
    plant(root, "right", evidence=evidence, **side)
    assert load("right", root).manifest["evidence"] == evidence
    other = next(e for e in pack.EVIDENCE_RANK if e != evidence)
    plant(root, "wrong", evidence=other, **side)
    refused(root, "wrong", f"evidence is {other!r} but what it delivers is {evidence!r}")


def test_a_scenario_is_as_strong_as_the_weakest_file_it_delivers(root: Path) -> None:
    ws = {"private": [TRANSCRIBED_WS]}
    plant(root, "mixed", rest={CREATE: {"payload": TRANSCRIBED_REST}}, ws=ws)
    assert load("mixed", root).manifest["evidence"] == "docs-transcribed"
    plant(root, "weaker", rest={CREATE: {"payload": BUILT_REST}}, ws=ws)
    refused(root, "weaker", "what it delivers is 'derived'")


def test_a_corpus_file_whose_source_is_in_no_evidence_class_is_refused(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = {"path": "rest/trading-error-110017.json", "source": "k01 harness"}
    monkeypatch.setattr(pack, "corpus_manifest", lambda **_: {"fixtures": [entry]})
    plant(root, "unknown")
    refused(root, "unknown", "in no evidence class")


def test_a_corpus_file_its_manifest_does_not_list_is_refused(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pack, "corpus_manifest", lambda **_: {"fixtures": []})
    plant(root, "unlisted")
    refused(root, "unlisted", "not listed in its corpus manifest")


def test_a_scenario_that_delivers_nothing_is_refused(root: Path) -> None:
    plant(root, "empty", rest=None)
    refused(root, "empty", "delivers nothing")


def test_a_manifest_that_breaks_the_schema_is_refused(root: Path) -> None:
    plant(root, "extra", surprise=1)
    refused(root, "extra", "breaks the schema.*surprise")
    plant(root, "no_such_rule", rules=["S12"])
    refused(root, "no_such_rule", "breaks the schema")
    plant(root, "no_description", description=None)
    refused(root, "no_description", "'description' is a required property")


@pytest.mark.parametrize(
    "ref",
    [
        "../accounts/_base/order_ack.json",
        "/etc/hostname",
        "sub/other.json",
        f"{CORPUS}/rest/../../../README.md",
        f"{CORPUS}/rest/risk_limit_BTCUSDT.json.gz",
    ],
)
def test_a_payload_outside_the_scenario_and_the_corpus_is_refused(root: Path, ref: str) -> None:
    plant(root, "reach", rest={CREATE: {"payload": ref}})
    refused(root, "reach", "breaks the schema")


def test_a_scenario_not_named_as_its_directory_is_refused(root: Path) -> None:
    plant(root, "one", scenario="two")
    refused(root, "one", "scenario 'two' is not its directory name")


def test_a_directory_without_a_manifest_is_refused(root: Path) -> None:
    (root / "bare").mkdir()
    assert scenario_names(root) == ["bare"]
    refused(root, "bare", "no manifest.json")


def test_a_derived_file_whose_source_does_not_exist_is_refused(root: Path) -> None:
    source = CORPUS_ROOT / "2026-10-05" / "ws" / "private-execution.jsonl"
    frames_scenario(root, "good", source.read_text(encoding="utf-8"))
    load("good", root)
    missing = f"{CORPUS}/ws/private-never-recorded.jsonl"
    derived = {"derived_from": [missing], "derivation": "planted"}
    frames_scenario(root, "bad", "{}\n", files={"frames.jsonl": derived})
    refused(root, "bad", f"frames.jsonl is derived from {missing}, which does not exist")


def test_a_file_the_manifest_does_not_account_for_is_refused(root: Path) -> None:
    frames_scenario(root, "orphan", "{}\n")
    (root / "orphan" / "stray.json").write_text("{}", encoding="utf-8")
    refused(root, "orphan", "stray.json is in the directory but no `files` entry declares it")
    frames_scenario(root, "idle", "{}\n", ws=None, rest={CREATE: {"payload": TRANSCRIBED_REST}})
    refused(root, "idle", "frames.jsonl is declared but no rest stub or ws list delivers it")
    plant(root, "undeclared", rest={CREATE: {"payload": "reply.json"}})
    refused(root, "undeclared", "reply.json is delivered but no `files` entry declares it")
    frames_scenario(root, "gone", "{}\n")
    (root / "gone" / "frames.jsonl").unlink()
    refused(root, "gone", "frames.jsonl is declared but is not in the directory")


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ('{"op":"ping"}\n{\n', "line 2 is not JSON"),
        ('{"op":"ping"}\n\n{"op":"pong"}\n', "one JSON frame per line"),
        ('{"op":"ping"}\r\n', "one JSON frame per line"),
        ('{"op":"ping"}', "one JSON frame per line"),
        ("", "one JSON frame per line"),
    ],
)
def test_a_frames_file_off_the_form_is_refused(root: Path, text: str, rule: str) -> None:
    frames_scenario(root, "frames", text)
    refused(root, "frames", rule)


def test_a_file_that_is_not_utf8_is_refused(root: Path) -> None:
    frames_scenario(root, "latin1", "{}\n")
    (root / "latin1" / "frames.jsonl").write_bytes(b'{"n":"\xe9"}\n')  # é as latin-1 writes it
    refused(root, "latin1", "frames.jsonl is not UTF-8")


def test_a_rest_file_that_is_not_json_is_refused(root: Path) -> None:
    derived = {"derived_from": [TRANSCRIBED_REST], "derivation": "planted"}
    own: dict[str, Any] = {"evidence": "derived", "rest": {CREATE: {"payload": "reply.json"}}}
    plant(root, "bad_json", {"reply.json": "{not json"}, files={"reply.json": derived}, **own)
    refused(root, "bad_json", "reply.json is not JSON")
    plant(root, "good_json", {"reply.json": '{"n":0}\n'}, files={"reply.json": derived}, **own)
    assert load("good_json", root).reply("POST", "/v5/order/create").body == {"n": 0}


def delivered(root: Path, *faults: dict[str, Any]) -> list[int]:
    """The `n` of each frame a scenario of four frames, `0` to `3`, delivers under `faults`."""
    name = f"run{len(scenario_names(root))}"
    frames_scenario(root, name, FRAMES, inject=list(faults))
    return [json.loads(line)["n"] for line in load(name, root).delivered_frames()]


def test_a_ws_fault_acts_on_the_sequence_as_the_one_before_left_it(root: Path) -> None:
    assert delivered(root) == [0, 1, 2, 3]
    assert delivered(root, {"kind": "duplicate", "frame": 1}) == [0, 1, 1, 2, 3]
    assert delivered(root, {"kind": "drop", "frame": 0}) == [1, 2, 3]
    assert delivered(root, {"kind": "reorder", "frame": 3, "to": 0}) == [3, 0, 1, 2]
    assert delivered(
        root,
        {"kind": "drop", "frame": 0},
        {"kind": "duplicate", "frame": 2},
        {"kind": "reorder", "frame": 0, "to": 3},
    ) == [2, 3, 3, 1]


@pytest.mark.parametrize(
    ("fault", "rule"),
    [
        ({"kind": "duplicate"}, "needs `frame`"),
        ({"kind": "duplicate", "frame": 4}, "frame the sequence does not have"),
        ({"kind": "drop", "frame": 0, "to": 1}, "needs `frame`"),
        ({"kind": "reorder", "frame": 0}, "needs `frame` and `to`"),
        ({"kind": "reorder", "frame": 1, "to": 1}, "to where it already is"),
        ({"kind": "reorder", "frame": 0, "to": 4}, "frame the sequence does not have"),
        ({"kind": "timeout", "call": CREATE}, "needs `call` alone, naming a stubbed call"),
        ({"kind": "explode", "frame": 0}, "breaks the schema"),
    ],
)
def test_a_fault_that_names_nothing_it_can_hit_is_refused(
    root: Path, fault: dict[str, Any], rule: str
) -> None:
    frames_scenario(root, "faulty", FRAMES, inject=[fault])
    refused(root, "faulty", rule)


def test_a_frame_a_fault_dropped_cannot_be_hit_again(root: Path) -> None:
    faults = [{"kind": "drop", "frame": 3}, {"kind": "duplicate", "frame": 3}]
    frames_scenario(root, "twice", FRAMES, inject=faults)
    refused(root, "twice", r"inject\[1\] \(duplicate\) hits a frame the sequence does not have")


def test_a_rest_fault_names_a_stubbed_call_and_is_left_to_the_harness(root: Path) -> None:
    faults = [{"kind": "timeout", "call": CREATE}, {"kind": "http_5xx", "call": CREATE}]
    plant(root, "late", inject=faults)
    scenario = load("late", root)
    assert [(i.kind, i.call) for i in scenario.injections] == [(f["kind"], CREATE) for f in faults]
    assert scenario.delivered_frames() == ()  # a REST fault never touches the stream
    plant(root, "wrong_call", inject=[{"kind": "timeout", "call": "POST /v5/order/cancel"}])
    refused(root, "wrong_call", "needs `call` alone, naming a stubbed call")
    plant(root, "ws_less", inject=[{"kind": "drop", "frame": 0}])
    refused(root, "ws_less", "frame the sequence does not have")


def test_a_scenario_with_faults_loads_byte_identically(root: Path) -> None:
    faults = [{"kind": "duplicate", "frame": 1}, {"kind": "reorder", "frame": 0, "to": 2}]
    frames_scenario(root, "faulty", FRAMES, inject=faults)
    assert load("faulty", root).canonical() == load("faulty", root).canonical()
    assert [json.loads(f)["n"] for f in load("faulty", root).delivered_frames()] == [1, 1, 0, 2, 3]


# -- the AC-15 templates: slots, a seed and no leaked value -------------------------------------

TEMPLATE = "credential_shaped_inputs"
SHAPES = {
    "alnum": r"(?=.*[0-9])(?=.*[A-Za-z])[A-Za-z0-9]+",
    "letters": r"[A-Z]{6}[a-z]{6}[A-Za-z]*",
    "symbol": r"[A-Z0-9]+USDT",
    "hex": r"[0-9a-f]+",
    "digits": r"[1-9][0-9]*",
}


def test_a_template_s_slots_are_the_placeholders_of_its_files_and_draw_their_shape() -> None:
    scenario = load(TEMPLATE)
    slots = scenario.manifest["slots"]
    texts = [path_of(TEMPLATE, f).read_text(encoding="utf-8") for f in scenario.manifest["files"]]
    assert {m for text in texts for m in pack.PLACEHOLDER.findall(text)} == set(slots)
    for name, slot in slots.items():
        value = pack.generate("s", name, slot["shape"], slot["length"])
        assert len(value) == slot["length"] and re.fullmatch(SHAPES[slot["shape"]], value), name


def test_a_short_alnum_value_still_holds_a_letter_and_a_digit() -> None:
    values = [pack.generate(f"s{n}", "k", "alnum", 2) for n in range(40)]
    assert all(re.fullmatch(SHAPES["alnum"], value) for value in values)


def test_a_rendered_template_is_fixed_by_its_seed_and_leaks_no_value() -> None:
    scenario = load(TEMPLATE)
    one, again, other = (scenario.render(s) for s in ("seed-one", "seed-one", "seed-two"))
    assert (one.frames, one.replies, one.values) == (again.frames, again.replies, again.values)
    assert one.values.keys() == other.values.keys() and one.values != other.values
    text = "".join(one.frames) + json.dumps([r.body for r in one.replies.values()])
    assert "{{" not in text and "}}" not in text  # every placeholder is filled
    assert all(isinstance(json.loads(frame), dict) for frame in one.frames)
    committed = [p.read_text(encoding="utf-8") for p in (pack.PACK_ROOT / TEMPLATE).iterdir()]
    assert (one.leaks(text), one.leaks(*committed)) == (sorted(one.values), [])
    assert one.leaks(f"seen {one.values['api_key']}") == ["api_key"]  # the name, never the value
    assert not any(value in repr(one) for value in one.values.values())


def test_a_scenario_without_slots_renders_as_it_is() -> None:
    scenario = load("ws_duplicate_exec")
    assert (scenario.render("any").frames, scenario.render("any").values) == (
        scenario.delivered_frames(),
        {},
    )


HEX = {"one": {"shape": "hex", "length": 8}}


def template(root: Path, name: str, text: str, slots: dict[str, Any]) -> None:
    """Scenario `name` delivering one derived `reply.json` holding `text`, its `slots` named."""
    derived = {"derived_from": [TRANSCRIBED_REST], "derivation": "planted"}
    own: dict[str, Any] = {"evidence": "derived", "files": {"reply.json": derived}, "slots": slots}
    plant(root, name, {"reply.json": text}, rest={CREATE: {"payload": "reply.json"}}, **own)


@pytest.mark.parametrize(
    ("text", "slots", "rule"),
    [
        ('{"n":"{{one}}"}\n', {}, r"the placeholder \{\{one\}\} has no entry under `slots`"),
        ('{"n":"x"}\n', HEX, "the slot 'one' is declared but no file uses it"),
        ('{"n":"{{One}}"}\n', {}, "holds a placeholder that is not"),
        ('{"n":"}} {{one}}"}\n', HEX, "holds a placeholder that is not"),
        ('{"n":"{{one}}"}\n', {"one": {"shape": "letters", "length": 8}}, "cannot hold a letters"),
        ('{"n":"{{one}}"}\n', {"one": {"shape": "symbol", "length": 21}}, "cannot hold a symbol"),
    ],
)
def test_a_template_whose_placeholders_and_slots_disagree_is_refused(
    root: Path, text: str, slots: dict[str, Any], rule: str
) -> None:
    template(root, "bad", text, slots)
    refused(root, "bad", rule)


def test_a_template_with_its_slots_loads_as_committed_and_renders_filled(root: Path) -> None:
    slots = HEX | {"two": {"shape": "digits", "length": 5}}
    template(root, "good", '{"n":"{{one}}-{{two}}-{{one}}"}\n', slots)
    one, two = (load("good", root).render("s").values[k] for k in ("one", "two"))
    assert load("good", root).render("s").replies[CREATE].body == {"n": f"{one}-{two}-{one}"}
    assert load("good", root).replies[CREATE].body == {"n": "{{one}}-{{two}}-{{one}}"}
