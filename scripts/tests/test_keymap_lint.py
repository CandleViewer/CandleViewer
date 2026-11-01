"""Tests for scripts/keymap_lint.py (E49-T04)."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import keymap_lint as k


def cmd(id_: str, ctx: str, binding: str, **kw: object) -> dict:
    base: dict = {
        "id": id_,
        "label": id_,
        "context": ctx,
        "defaultBinding": binding,
        "destructive": False,
        "validWhen": "always",
        "visibleControl": True,
    }
    base.update(kw)
    return base


def km(*cmds: dict) -> dict:
    return {
        "safetyModifierDefault": True,
        "cheatsheetContexts": list(k.CONTEXTS),
        "commands": list(cmds),
    }


def sh(target: str) -> list[dict]:
    return [{"command": target, "rationale": "scoped to focused panel"}]


@pytest.mark.parametrize(
    "a,b",
    [
        ("Shift+Ctrl+F", "Ctrl+Shift+F"),
        ("Cmd+K", "Ctrl+K"),
        ("ctrl+shift+t", "Ctrl+Shift+T"),
        ("Escape", "Esc"),
        ("Alt+ArrowUp", "Alt+↑"),
        ("Mod+S", "Ctrl+S"),
    ],
)
def test_normalise_equates_variants(a: str, b: str) -> None:
    assert k.normalise(a) == k.normalise(b)


def test_normalise_special_keys() -> None:
    assert k.normalise("+") == "+"
    assert k.normalise("Ctrl") == "Ctrl"
    assert k.normalise("Space+drag") == "Space+drag"
    assert k.expand("Alt+1..3") == ["Alt+1", "Alt+2", "Alt+3"]


@pytest.mark.parametrize("bad", ["", "Hyper+F", "Ctrl+Foo"])
def test_normalise_rejects_garbage(bad: str) -> None:
    with pytest.raises(k.KeymapError):
        k.normalise(bad)


def test_same_context_collision_names_both_ids_context_and_binding() -> None:
    errs = k.lint_keymap(km(cmd("chart.a", "Chart", "F"), cmd("chart.b", "Chart", "F")))
    assert any(
        "chart.a" in e and "chart.b" in e and "Chart" in e and "binding F" in e for e in errs
    )


def test_modifier_order_does_not_hide_a_collision() -> None:
    errs = k.lint_keymap(km(cmd("a", "Chart", "Shift+Alt+J"), cmd("b", "Chart", "Alt+Shift+J")))
    assert any("conflict in context Chart" in e for e in errs)


def test_declared_cross_context_reuse_passes() -> None:
    a = cmd("chart.esc", "Chart", "Esc", shadows=sh("dom.esc"))
    b = cmd("dom.esc", "DOM", "Esc", shadows=sh("chart.esc"))
    assert k.lint_keymap(km(a, b)) == []


def test_one_sided_declaration_fails() -> None:
    a = cmd("chart.esc", "Chart", "Esc", shadows=sh("dom.esc"))
    b = cmd("dom.esc", "DOM", "Esc")
    assert any("undeclared reuse" in e for e in k.lint_keymap(km(a, b)))


def test_undeclared_global_shadow_fails_and_declared_passes() -> None:
    g = cmd("global.p", "Global", "Ctrl+K")
    assert any(
        "undeclared shadow" in e for e in k.lint_keymap(km(g, cmd("chart.p", "Chart", "Ctrl+K")))
    )
    ok = cmd("chart.p", "Chart", "Ctrl+K", shadows=sh("global.p"))
    assert k.lint_keymap(km(g, ok)) == []


def test_shadow_requires_rationale_and_known_target() -> None:
    c = cmd("a", "Chart", "F", shadows=[{"command": "ghost", "rationale": " "}])
    errs = k.lint_keymap(km(c))
    assert any("unknown command" in e for e in errs)
    assert any("without rationale" in e for e in errs)


def test_reserved_key_names_platform_and_override_needs_rationale() -> None:
    errs = k.lint_keymap(km(cmd("x", "Chart", "Ctrl+Shift+I")))
    assert any("Ctrl+Shift+I" in e and "devtools" in e for e in errs)
    ok = cmd("x", "Chart", "Ctrl+Shift+I", reservedOverride={"rationale": "reviewed"})
    assert k.lint_keymap(km(ok)) == []
    blank = cmd("x", "Chart", "Ctrl+Shift+I", reservedOverride={"rationale": "  "})
    assert k.lint_keymap(km(blank)) != []


def test_reserved_range_is_expanded() -> None:
    assert any("reserved" in e for e in k.lint_keymap(km(cmd("w", "Workspace", "Ctrl+1..9"))))


def test_destructive_single_letter_fails_and_modifier_passes() -> None:
    errs = k.lint_keymap(km(cmd("flat", "Chart", "X", destructive=True)))
    assert any("single-letter" in e and "flat" in e for e in errs)
    assert k.lint_keymap(km(cmd("flat", "Chart", "Ctrl+Shift+X", destructive=True))) == []


def test_safety_default_cannot_be_turned_off() -> None:
    m = km(cmd("a", "Chart", "Ctrl+Shift+X"))
    m["safetyModifierDefault"] = False
    assert any("safetyModifierDefault" in e for e in k.lint_keymap(m))


def test_hotkey_only_command_needs_control_or_rationale() -> None:
    bad = cmd("a", "Chart", "Ctrl+J", visibleControl=False)
    assert any("hotkey-only" in e for e in k.lint_keymap(km(bad)))
    assert k.lint_keymap(km(cmd("a", "Chart", "Ctrl+J", visibleControl="palette entry"))) == []


def test_structural_errors() -> None:
    errs = k.lint_keymap(km(cmd("a", "Nowhere", "F"), cmd("a", "Chart", "Hyper+F"), {"id": "z"}))
    joined = "\n".join(errs)
    assert "duplicate command id a" in joined
    assert "unknown context" in joined
    assert "invalid binding" in joined
    assert "missing field" in joined


CAT = (
    "### SCR-030 — Chart\n"
    "- **Interactions/hotkeys:** `F` toggle; `Ctrl+Z/Ctrl+Y` undo/redo; `1..9` presets; `Esc`.\n"
    "### SCR-097 — Replay\n"
    "- **Interactions/hotkeys:** `Shift+←/→` step; `[`/`]` bookmark.\n"
)


def test_parse_catalogue_expands_alternatives() -> None:
    screens, _g, errs = k.parse_catalogue(CAT)
    assert errs == []
    assert {"F", "Ctrl+Z", "Ctrl+Y", "1", "9", "Esc"} <= screens["SCR-030"]
    assert {"Shift+←", "Shift+→", "[", "]"} <= screens["SCR-097"]


def test_parse_catalogue_reports_unparseable_and_orphan_lines() -> None:
    _s, _g, errs = k.parse_catalogue("### SCR-030 — x\n- **Interactions/hotkeys:** `Hyper+Q`\n")
    assert any("SCR-030" in e and "Hyper+Q" in e for e in errs)
    _s, _g, errs = k.parse_catalogue("- **Interactions/hotkeys:** `F`\n")
    assert any("outside any SCR" in e for e in errs)


def test_catalogue_hotkey_missing_from_keymap_fails_naming_screen() -> None:
    m = km(cmd("chart.f", "Chart", "F"))
    errs = k.check_coverage(m, "### SCR-030 — Chart\n- **Interactions/hotkeys:** `F`; `Q`\n")
    assert any("SCR-030" in e and "hotkey Q" in e for e in errs)
    assert not any("hotkey F " in e for e in errs)


def test_unmapped_screen_cheatsheet_and_editable_checks() -> None:
    m = km(cmd("a", "Chart", "F", editable=False))
    m["cheatsheetContexts"] = []
    errs = k.check_coverage(m, "### SCR-999 — Y\n- **Interactions/hotkeys:** `F`\n")
    joined = "\n".join(errs)
    assert "no context mapping" in joined
    assert "missing from cheatsheet" in joined
    assert "editableException" in joined


def test_keymap_entry_not_documented_on_declared_screen() -> None:
    m = km(cmd("chart.z", "Chart", "Z", screens=["SCR-030"]))
    errs = k.check_coverage(m, "### SCR-030 — Chart\n- **Interactions/hotkeys:** `F`\n")
    assert any("chart.z" in e and "not documented" in e for e in errs)


def test_real_keymap_is_clean(capsys: pytest.CaptureFixture[str]) -> None:
    assert k.main([]) == 0
    assert "OK" in capsys.readouterr().out


def test_docs_generator_is_deterministic_and_committed_copy_is_fresh() -> None:
    data = json.loads(k.KEYMAP.read_text(encoding="utf-8"))
    first = k.render_docs(data)
    assert first == k.render_docs(copy.deepcopy(data))
    assert k.DOCS_OUT.read_text(encoding="utf-8") == first
    assert k.main(["--check-docs"]) == 0


def test_check_docs_flags_stale_file(tmp_path: Path) -> None:
    out = tmp_path / "d.md"
    out.write_text("stale", encoding="utf-8")
    assert k.main(["--check-docs", "--docs-out", str(out)]) == 1
    assert k.main(["--docs", "--docs-out", str(out)]) == 0
    assert k.main(["--check-docs", "--docs-out", str(out)]) == 0


def test_main_internal_error_on_missing_file(tmp_path: Path) -> None:
    assert k.main(["--keymap", str(tmp_path / "nope.json")]) == 2


def test_main_reports_violations(tmp_path: Path) -> None:
    p = tmp_path / "km.json"
    p.write_text(json.dumps(km(cmd("a", "Chart", "F"), cmd("b", "Chart", "F"))), encoding="utf-8")
    assert k.main(["--keymap", str(p)]) == 1


# --------------------------------------------------------------------------- server vocabulary
# E10-T05 (#5211, BQ-8): `--vocabulary` writes the keymap facts `/settings/hotkeys` judges by.
SPEC = (
    "components:\n"
    "  schemas:\n"
    "    HotkeyBinding:\n"
    "      properties:\n"
    "        scope:\n"
    "          description: |\n"
    "            | `keymap.json` context | `scope`     |\n"
    "            | --------------------- | ----------- |\n"
    "            | `Global`              | `global`    |\n"
    "            | `Chart`               | `chart`     |\n"
    "    HotkeyProfile:\n"
    "      description: |\n"
    "        | `DOM` | `dom` |\n"
)


def test_scope_table_reads_the_hotkey_binding_rows_only() -> None:
    assert k.scope_table(SPEC) == {"Global": "global", "Chart": "chart"}
    assert k.scope_table(SPEC.split("    HotkeyProfile:")[0]) == {
        "Global": "global",
        "Chart": "chart",
    }


@pytest.mark.parametrize(
    "spec",
    [
        SPEC.replace("HotkeyBinding:", "HotkeyBindings:"),  # no such schema
        SPEC.replace("| `Chart`               | `chart`     |", "| `Global` | `chart` |"),
        SPEC.replace("`Global`", "Global").replace("`Chart`", "Chart"),  # no row at all
    ],
)
def test_scope_table_refuses_a_missing_or_doubled_table(spec: str) -> None:
    with pytest.raises(k.KeymapError):
        k.scope_table(spec)


def test_atoms_expand_a_digit_range_as_binding_atoms_does() -> None:
    assert k._atoms("Ctrl+1..3") == ["Ctrl+1", "Ctrl+2", "Ctrl+3"]
    assert k._atoms("1..1") == ["1"]
    assert k._atoms("F5") == ["F5"]
    assert k._atoms("Ctrl+K") == ["Ctrl+K"]


def test_vocabulary_command_carries_each_fact_as_the_client_reads_it() -> None:
    scopes = {"Global": "global", "Chart": "chart"}
    shadows = [{"command": "g", "rationale": "why"}, {"command": "h", "rationale": "  "}]
    full = cmd(
        "chart.x", "Chart", "Ctrl+X", focusContexts=["Chart", "Global"], shadows=shadows,
        reservedOverride={"rationale": "reviewed"}, editable=False, audited=True,
        requiresArm=True, confirm=True,
    )  # fmt: skip
    assert k._vocabulary_command(full, scopes) == {
        "id": "chart.x", "context": "Chart", "scope": "chart",
        "focus_contexts": ["Chart", "Global"], "default": "Ctrl+X", "editable": False,
        "reserved_override": True, "shadows": ["g"], "dangerous": True, "requires_arm": True,
        "confirm": True,
    }  # fmt: skip
    bare = k._vocabulary_command(
        cmd("g", "Global", "F1", reservedOverride={"rationale": " "}), scopes
    )
    assert (bare["focus_contexts"], bare["editable"], bare["reserved_override"]) == (
        ["Global"], True, False)  # fmt: skip
    assert not (bare["shadows"] or bare["dangerous"] or bare["requires_arm"] or bare["confirm"])
    assert (
        k._vocabulary_command(cmd("e", "Chart", "F2", focusContexts=[]), scopes)["focus_contexts"]
        == []
    )  # `focusContexts ?? [context]`: an empty list stays empty
    with pytest.raises(k.KeymapError, match="context DOM"):
        k._vocabulary_command(cmd("dom.x", "DOM", "F3"), scopes)


def test_render_vocabulary_derives_permanent_keys_and_expands_the_reserved_ones() -> None:
    m = km(cmd("g.p", "Global", "Ctrl+K", editable=False), cmd("c.e", "Chart", "Esc", editable=False),
           cmd("c.r", "Chart", "Alt+1..2", editable=False), cmd("c.f", "Chart", "F"))  # fmt: skip
    doc = json.loads(k.render_vocabulary(m, SPEC, b"{}\r\n", b"{}\n"))
    assert doc["permanent_keys"] == ["Alt+1", "Alt+2", "Ctrl+K", "Esc"]
    assert [c["id"] for c in doc["commands"]] == ["g.p", "c.e", "c.r", "c.f"]
    reserved = {a: w for raw, w in k._RESERVED_RAW.items() for a in k._atoms(raw)}
    assert (
        doc["reserved_keys"] == reserved
        and doc["reserved_keys"]["Ctrl+9"] == "browser (switch tab)"
    )
    assert list(doc["reserved_keys"]) == sorted(reserved)
    sources = {item["path"]: item["sha256"] for item in doc["sources"]}
    assert sources["apps/web/src/keymap/keymap.json"] == k._sha256(b"{}\n")  # CRLF read as LF
    assert sources["apps/web/src/keymap/reserved-keys.json"] == k._sha256(b"{}\n")
    assert sources[k.SCOPE_SOURCE] == k._sha256(b'[["Global", "global"], ["Chart", "chart"]]')
    assert doc["$comment"].startswith("GENERATED by scripts/keymap_lint.py --vocabulary")


def test_vocabulary_generator_is_deterministic_and_committed_copy_is_fresh() -> None:
    data = json.loads(k.KEYMAP.read_text(encoding="utf-8"))
    spec = k.API_SPEC.read_text(encoding="utf-8")
    args = (k.KEYMAP.read_bytes(), k.RESERVED_FILE.read_bytes())
    first = k.render_vocabulary(data, spec, *args)
    assert first == k.render_vocabulary(copy.deepcopy(data), spec, *args)
    assert k.VOCABULARY_OUT.read_bytes() == first.encode("utf-8")
    assert k.main(["--check-vocabulary"]) == 0


def test_check_vocabulary_flags_a_stale_or_missing_file(tmp_path: Path) -> None:
    out = tmp_path / "v.json"
    assert k.main(["--check-vocabulary", "--vocabulary-out", str(out)]) == 1
    out.write_text("stale", encoding="utf-8")
    assert k.main(["--check-vocabulary", "--vocabulary-out", str(out)]) == 1
    assert k.main(["--vocabulary", "--vocabulary-out", str(tmp_path / "new" / "v.json")]) == 0
    assert (tmp_path / "new" / "v.json").read_bytes() == k.VOCABULARY_OUT.read_bytes()
    out.write_bytes(k.VOCABULARY_OUT.read_bytes())
    assert k.main(["--check-vocabulary", "--vocabulary-out", str(out)]) == 0


def test_a_vocabulary_that_cannot_render_is_a_violation_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec, out = tmp_path / "22.yaml", tmp_path / "v.json"
    spec.write_text("paths: {}\n", encoding="utf-8")
    args = ["--vocabulary", "--vocabulary-out", str(out)]
    assert k.main([*args, "--spec", str(spec)]) == 1
    assert k.main([*args, "--spec", str(tmp_path / "absent.yaml")]) == 1
    assert not out.exists()
    assert capsys.readouterr().out.count("vocabulary: cannot render it") == 2
