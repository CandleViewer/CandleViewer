"""E17-T05: tests for tools/errorcodes + the error_registry_single_source gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.contracts import check_error_registry as gate
from tools.errorcodes import generate

MD = (REPO / "docs" / "plan" / "23-ws-protocol.md").read_text(encoding="utf-8")
YAML = generate.OPENAPI.read_text(encoding="utf-8")
FRESH = generate.render_all(YAML)

MINI = """
x-error-codes:
  - {code: Not_Found, status: 404, title: t, retryable: false}
  - {code: forbidden, status: 403, title: t, retryable: false, surface: [rest, ws]}
x-error-codes-ws:
  - {code: unknown_topic, scope: topic, retryable: false, title: t, rest_analogue: not_found}
"""
ROW_F = "| `forbidden` | topic | no | = | x |"
ROW_U = "| `unknown_topic` | topic | no | `not_found` | x |"
MINI_MD = f"""### 10.2 Catalogue

| Code | Scope | `retryable` | REST | Meaning |
| --- | --- | --- | --- | --- |
{ROW_F}
{ROW_U}

### 10.3 next
"""


def test_repo_registry_passes_gate() -> None:
    assert gate.check(MD, YAML, FRESH) == []


def test_generator_normalises_case_and_emits_metadata() -> None:
    entries = generate.load_registry(MINI)
    assert [e["code"] for e in entries] == ["not_found", "forbidden", "unknown_topic"]
    py = generate.render_py(entries)
    assert 'UNKNOWN_TOPIC = "unknown_topic"' in py and "DO NOT EDIT" in py
    assert 'restAnalogue: "not_found"' in generate.render_ts(entries)


def test_duplicate_code_rejected() -> None:
    with pytest.raises(generate.RegistryError, match="duplicate"):
        generate.load_registry(MINI.replace("unknown_topic", "forbidden"))


def test_generator_rejects_a_title_outside_the_bmp() -> None:
    entries = generate.load_registry(MINI.replace("title: t", "title: '\U0001f600'", 1))
    with pytest.raises(generate.RegistryError, match="BMP"):
        generate.render_py(entries)


def test_generator_rejects_a_lone_surrogate_title_naming_the_code() -> None:
    entries = generate.load_registry(MINI)
    entries[0]["title"] = "bad \ud800 title"
    with pytest.raises(generate.RegistryError, match="surrogate"):
        generate.render_py(entries)


@pytest.mark.parametrize("code", ["9lives", "a-b", "a b", "a.b", "_x", "caf\u00e9", 'a"b'])
def test_load_registry_rejects_a_code_outside_the_identifier_shape(code: str) -> None:
    text = MINI.replace("Not_Found", f"'{code}'")
    with pytest.raises(generate.RegistryError, match="code"):
        generate.load_registry(text)


def test_scope_and_analogue_strings_containing_null_survive_python_emission() -> None:
    text = MINI.replace("scope: topic", "scope: nullable").replace(
        "rest_analogue: not_found", "rest_analogue: nullish"
    )
    py = generate.render_py(generate.load_registry(text))
    assert '"nullable"' in py and '"nullish"' in py
    assert "Nonetable" not in py and "Noneish" not in py
    ns: dict[str, object] = {}
    exec(compile(py, "<generated>", "exec"), ns)  # noqa: S102 - trusted generator output in a test


def test_gate_reports_a_render_refusal_as_a_registry_line() -> None:
    text = MINI.replace("title: t", "title: '\U0001f600'", 1)
    errs = gate.check(MINI_MD, text, {})
    assert len(errs) == 1 and errs[0].startswith("registry: ") and "not_found" in errs[0]


def _ws(extra: str) -> str:
    if extra.startswith("surface:"):
        return MINI.replace("surface: [rest, ws]", extra, 1)
    return MINI.replace("{code: forbidden,", "{code: forbidden, " + extra + ",", 1)


@pytest.mark.parametrize(
    "field",
    [
        "surface: rest",
        "surface: [rest, smtp]",
        "surface: ['rest\"']",
        "surface: [[rest]]",
        "surface: []",
        "surface: [rest, ' REST ']",
        "close_code: '4401'",
        "close_code: '1); import os #'",
        "close_code: true",
        "close_code: 4401.5",
        "close_code: 999",
        "close_code: 5000",
    ],
)
def test_load_registry_rejects_bad_surface_and_close_code(field: str) -> None:
    with pytest.raises(generate.RegistryError, match="forbidden"):
        generate.load_registry(_ws(field))


def test_load_registry_accepts_the_registry_close_codes() -> None:
    entries = generate.load_registry(_ws("close_code: 4401"))
    assert entries[1]["close_code"] == 4401


@pytest.mark.parametrize("scope", ["true", "'\U0001f600'", "[a]", "1"])
def test_ws_scope_must_be_clean_text(scope: str) -> None:
    text = MINI.replace("scope: topic", f"scope: {scope}")
    with pytest.raises(generate.RegistryError, match="unknown_topic"):
        generate.render_py(generate.load_registry(text))


def test_lone_surrogate_scope_is_refused() -> None:
    entries = generate.load_registry(MINI)
    entries[2]["scope"] = "to\ud800pic"
    with pytest.raises(generate.RegistryError, match="surrogate"):
        generate.render_py(entries)


@pytest.mark.parametrize("ra", ["[a, b]", "{a: b}", "true", "5"])
def test_gate_reports_a_bad_rest_analogue_as_a_registry_line(ra: str) -> None:
    text = MINI.replace("rest_analogue: not_found", f"rest_analogue: {ra}")
    errs = gate.check(MINI_MD, text, {})
    assert len(errs) == 1 and errs[0].startswith("registry: ") and "unknown_topic" in errs[0]


def test_generator_keeps_a_bmp_title_as_a_valid_literal() -> None:
    entries = generate.load_registry(MINI.replace("title: t", "title: '\u2014'", 1))
    assert "\\u2014" in generate.render_py(entries)


def test_ws_code_without_scope_rejected() -> None:
    with pytest.raises(generate.RegistryError, match="scope"):
        generate.load_registry(MINI.replace("scope: topic, ", ""))


def test_malformed_registry_rejected() -> None:
    with pytest.raises(generate.RegistryError):
        generate.load_registry("a: 1")


def test_minimal_fixture_passes() -> None:
    assert gate.check(MINI_MD, MINI, generate.render_all(MINI)) == []


def test_orphan_in_markdown_fails_naming_code() -> None:
    md = MINI_MD.replace(ROW_U, "| `extra_code` | topic | no | - | x |\n" + ROW_U)
    assert any("extra_code" in e for e in gate.check(md, MINI, generate.render_all(MINI)))


def test_orphan_in_registry_fails_naming_code() -> None:
    md = MINI_MD.replace(ROW_U + "\n", "")
    assert any("unknown_topic" in e for e in gate.check(md, MINI, generate.render_all(MINI)))


def test_dangling_rest_analogue_names_both() -> None:
    bad = MINI.replace("rest_analogue: not_found", "rest_analogue: nope")
    errs = gate.check(MINI_MD, bad, generate.render_all(bad))
    assert any("unknown_topic" in e and "nope" in e for e in errs)


def test_hand_edited_generated_file_fails() -> None:
    tampered = dict(FRESH)
    tampered[generate.OUT_TS] += "// hand edit\n"
    assert any("byte-identical" in e for e in gate.check(MD, YAML, tampered))


def test_missing_generated_file_fails() -> None:
    assert any("byte-identical" in e for e in gate.check(MD, YAML, {}))


@pytest.mark.parametrize("row", ["| `x` | only | three |", "| not-backticked | a | b | c | d |"])
def test_malformed_row_fails_not_skipped(row: str) -> None:
    with pytest.raises(ValueError):
        gate.parse_md_codes(MINI_MD.replace(ROW_F, row))


def test_duplicate_md_row_fails() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        gate.parse_md_codes(MINI_MD.replace(ROW_U, ROW_F))


def test_missing_section_fails() -> None:
    with pytest.raises(ValueError, match="not found"):
        gate.parse_md_codes("# nothing")


def test_committed_files_match_regeneration() -> None:
    assert generate.main(["--check"]) == 0
    assert gate.main() == 0


def _titles() -> dict[str, str]:
    return {e["code"]: e["title"] for e in generate.load_registry(YAML)}


def test_internal_error_title_names_no_rest_only_field() -> None:
    # #2553: the title serves REST and WS clients; WS frames have no `instance`.
    title = _titles()["internal_error"]
    assert title == "Unhandled server error"
    assert "instance" not in title


def test_registry_titles_carry_no_exchange_brand() -> None:
    # #2553: titles land in ws/_generated and the TS catalogue; they say "the exchange".
    branded = {code: t for code, t in _titles().items() if "bybit" in t.lower()}
    assert branded == {}
    assert all("bybit" not in text.lower() for text in FRESH.values())


def test_reworded_titles_keep_their_meaning_and_the_md_row() -> None:
    titles = _titles()
    assert titles["unsupported_category"] == "Only the exchange's USDT linear perpetuals are supported in v1"
    assert titles["exchange_error"] == "The exchange returned a non-zero refusal code"
    assert titles["exchange_rate_limited"].startswith("The exchange's per-UID rate budget is exhausted")
    assert titles["unsupported_symbol"] == "Not one of the exchange's USDT linear perpetuals, or unknown instrument"
    assert f"{titles['unsupported_symbol']}." in MD


def test_request_level_use_of_invalid_options_and_the_wide_frame_malformed_title() -> None:
    # #2553: `invalid_options` also refuses a malformed sub/unsub or a ctl/resync naming a bad
    # `ch`, `rs` or `sub_id`, with no `ch`; `frame_malformed` is §3.6's code for a malformed
    # inbound frame, and §7.7's for a resync with no `ch` or a `p` that is no object.
    titles = _titles()
    assert titles["invalid_options"] == (
        "Subscription option out of range, of the wrong type, or an unknown key; also a "
        "request-level refusal of a malformed `sub` or `unsub`, or a `ctl` or `resync` naming a "
        "bad `ch`, `rs` or `sub_id`, with no `ch`"
    )
    assert titles["frame_malformed"] == (
        "Malformed inbound frame (§3.6): invalid or over-bound JSON or MessagePack, a frame of "
        "the wrong kind for the connection's subprotocol, a binary body inconsistent with its "
        "header, or a resync with no ch or a p that is not an object"
    )
    flat = " ".join(MD.split())
    assert (
        "Also a request-level refusal: a malformed `sub` or `unsub`, or a `ctl` or `resync` "
        "naming a bad `ch`, `rs` or `sub_id`, gets it with no `ch`"
    ) in flat
    assert "Malformed inbound frame (§3.6): invalid or over-bound JSON or MessagePack" in flat
    assert "or a `resync` with no `ch` or a `p` that is not an object (§7.7)" in flat
