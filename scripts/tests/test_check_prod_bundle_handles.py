"""Unit tests for tools/ci/check_prod_bundle_handles.py (E14-X03, #549; DR5, SR-E14-10; E11-X02,
#392; CE-E05)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.ci.check_prod_bundle_handles as guard  # noqa: E402 - sys.path first (#549)

CLEAN = {"index.html": "<html></html>\n", "assets/index-ab12.js": 'console.log("hi");\n'}
SOURCE_MAP = json.dumps({"sources": ["engine.ts"], "sourcesContent": ["window.__cvEngine = {}"]})


def _run(tmp_path, capsys, files, *extra):
    for rel, text in files.items():
        (tmp_path / "dist" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "dist" / rel).write_text(text, encoding="utf-8")
    (tmp_path / "dist").mkdir(exist_ok=True)
    code = guard.main(["--dist", str(tmp_path / "dist"), *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.parametrize("name", ["__cvEngine", "projectForTest"])
def test_a_handle_in_a_js_file_fails_naming_it_the_threat_and_the_requirement(
    tmp_path, capsys, name
):
    js = f"var a = 1;\nvar b = 2;\nwindow.{name} = {{}};\n"
    code, _, err = _run(tmp_path, capsys, CLEAN | {"assets/main-9f.js": js})
    assert code == 1
    assert f"assets/main-9f.js:3:8: '{name}' (DR5; SR-E14-10)" in err
    assert "E14-drawings.md" in err  # the threat model it mitigates


def test_a_handle_in_inline_html_fails(tmp_path, capsys):
    page = "<script>window.__cvEngine = {}</script>"
    code, _, err = _run(tmp_path, capsys, CLEAN | {"index.html": page})
    assert code == 1 and "index.html:1:" in err


def test_a_handle_only_in_a_source_map_passes(tmp_path, capsys):
    code, out, err = _run(tmp_path, capsys, CLEAN | {"assets/index-ab12.js.map": SOURCE_MAP})
    assert (code, err) == (0, "") and "2 file(s) scanned" in out  # the map was not read


def test_a_clean_dist_passes(tmp_path, capsys):
    assert _run(tmp_path, capsys, CLEAN)[::2] == (0, "")


def test_an_identifier_is_matched_as_a_substring_and_other_files_are_not_read(tmp_path, capsys):
    other = {"assets/x.css": "/* __cvEngine */", "assets/x.json": '{"projectForTest": 1}'}
    assert _run(tmp_path / "a", capsys, CLEAN | other)[0] == 0
    code, _, err = _run(tmp_path / "b", capsys, CLEAN | {"a.js": "x.__cvEngineDebug()"})
    assert code == 1 and "'__cvEngine'" in err
    assert _run(tmp_path / "c", capsys, CLEAN | {"UP.JS": "window.__cvEngine = 1"})[0] == 1  # case


@pytest.mark.parametrize("files", [{}, {"assets/a.js.map": SOURCE_MAP}, {"a.css": "a{}"}])
def test_a_dist_with_nothing_to_scan_fails_closed(tmp_path, capsys, files):
    assert _run(tmp_path, capsys, files)[0] == 2
    assert guard.main(["--dist", str(tmp_path / "missing")]) == 2  # no build at all


def test_a_dist_with_html_but_no_script_file_fails_closed(tmp_path, capsys):
    code, _, err = _run(tmp_path, capsys, {"index.html": "<html></html>\n"})
    assert code == 2 and "no script file" in err  # a half-written build is not a clean one


@pytest.mark.parametrize("suffix", [".mjs", ".cjs"])
def test_a_handle_in_an_mjs_or_cjs_chunk_fails(tmp_path, capsys, suffix):
    chunk = {f"assets/chunk-1a{suffix}": "window.__cvEngine = {};\n"}
    code, _, err = _run(tmp_path, capsys, {"index.html": "<html></html>\n"} | chunk)
    assert code == 1 and f"assets/chunk-1a{suffix}:1:8: '__cvEngine'" in err


def test_the_manifest_extends_and_a_bad_one_is_refused(tmp_path, capsys):
    entry = {"identifier": "__cvDebugBus", "threat": "DR5", "requirement": "SR-E14-10"}
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"handles": [entry]}), encoding="utf-8")
    code, _, err = _run(
        tmp_path, capsys, CLEAN | {"a.js": "__cvDebugBus"}, "--manifest", str(manifest)
    )
    assert code == 1 and "'__cvDebugBus'" in err
    short = {
        "identifier": "abc",
        "threat": "DR5",
        "requirement": "SR-E14-10",
    }  # under 4 characters, it would match too much
    for bad in [
        "{",
        "[]",
        '{"handles": []}',
        '{"handles": ["__cvEngine"]}',  # an entry that is no object: a likely hand-edit slip
        '{"handles": [{"identifier": "__cvEngine"}]}',
        json.dumps({"handles": [short]}),
        json.dumps({"handles": [entry | {"threat": ""}]}),
        json.dumps({"handles": [entry | {"requirement": ""}]}),
    ]:
        manifest.write_text(bad, encoding="utf-8")
        assert _run(tmp_path, capsys, CLEAN, "--manifest", str(manifest))[0] == 2
    assert guard.main(["--dist", str(tmp_path), "--manifest", str(tmp_path / "none.json")]) == 2


def test_an_identifier_of_four_characters_is_the_shortest_accepted(tmp_path, capsys):
    entry = {"identifier": "abcd", "threat": "DR5", "requirement": "SR-E14-10"}
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"handles": [entry]}), encoding="utf-8")
    assert _run(tmp_path, capsys, CLEAN, "--manifest", str(manifest))[0] == 0


def test_each_handle_found_in_a_file_is_named_once(tmp_path, capsys):
    both = {"assets/a.js": "window.__cvEngine.projectForTest(1)\n"}
    code, _, err = _run(tmp_path, capsys, CLEAN | both)
    named = [line for line in err.splitlines() if line.startswith("prod-bundle: assets/a.js:")]
    assert code == 1 and len(named) == 2  # one per (file, identifier), not one per file


def test_findings_are_named_in_path_order(tmp_path, capsys):
    hits = {"z/b.js": "__cvEngine", "a/c.js": "__cvEngine"}
    _, _, err = _run(tmp_path, capsys, CLEAN | hits)
    paths = [line.split(":")[1].strip() for line in err.splitlines() if ".js:" in line]
    assert paths == ["a/c.js", "z/b.js"]


def test_a_file_that_is_not_utf_8_is_still_scanned(tmp_path, capsys):
    (tmp_path / "dist" / "assets").mkdir(parents=True)
    (tmp_path / "dist" / "assets" / "x.js").write_bytes(b"\xff\xfe window.__cvEngine = 1")
    code, _, err = _run(tmp_path, capsys, CLEAN)
    assert code == 1 and "assets/x.js:1:" in err


def test_a_directory_named_like_a_script_is_not_read(tmp_path, capsys):
    (tmp_path / "dist" / "chunks.js").mkdir(parents=True)
    assert _run(tmp_path, capsys, CLEAN)[::2] == (0, "")


def test_a_handle_in_an_htm_page_fails(tmp_path, capsys):
    page = {"legacy.htm": "<script>window.__cvEngine = {}</script>"}
    code, _, err = _run(tmp_path, capsys, CLEAN | page)
    assert code == 1 and "legacy.htm:1:" in err


def test_the_build_job_runs_the_guard_on_the_web_build_it_just_made() -> None:
    """The step sits in `_job-js.yml`'s `build` job after the step that builds `apps/web`, and reads
    that build's dist, not another (`apps/desktop/dist` holds `.js` files too)."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/_job-js.yml").read_text(encoding="utf-8"))
    runs = [str(step.get("run", "")) for step in workflow["jobs"]["build"]["steps"]]
    guard_at = next(i for i, run in enumerate(runs) if "check_prod_bundle_handles.py" in run)
    built_at = max(i for i, run in enumerate(runs) if "--filter @candleviewer/web " in run)
    command = "python tools/ci/check_prod_bundle_handles.py --dist apps/web/dist"
    assert runs[guard_at].strip() == command
    assert built_at < guard_at


def test_the_real_manifest_registers_both_handles_for_dr5() -> None:
    handles = guard.load_handles(guard.MANIFEST)
    owner = {h["identifier"]: (h["threat"], h["requirement"]) for h in handles}
    assert owner["__cvEngine"] == owner["projectForTest"] == ("DR5", "SR-E14-10")
    # E11-X02 (#392; CE-E05) registers the engine's debug surface beside them under its own threat.
    assert owner["__engine"] == owner["runBenchScene"] == ("CE-E05", "E11-X02")
    assert set(owner.values()) == {("DR5", "SR-E14-10"), ("CE-E05", "E11-X02")}


def test_the_script_runs_as_a_command(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "a.js").write_text("window.__cvEngine = 1", encoding="utf-8")
    script = str(ROOT / "tools/ci/check_prod_bundle_handles.py")
    run = subprocess.run(  # noqa: S603 - the interpreter and the script under test (#549)
        [sys.executable, script, "--dist", str(tmp_path / "dist")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 1 and "a.js:1:8: '__cvEngine'" in run.stderr


# E11-X02 (#392; CE-E05): the engine's debug surface cannot ship.
@pytest.mark.parametrize(
    ("name", "js"),
    [
        ("__engine", "window.__engineEvents = [];\n"),
        ("__engine", 'const routes = ["/", "/__engine-harness"];\n'),
        ("runBenchScene", "export function runBenchScene() {}\n"),
    ],
)
def test_an_engine_debug_surface_fails_naming_ce_e05(tmp_path, capsys, name, js):
    code, _, err = _run(tmp_path, capsys, CLEAN | {"assets/engine-1c.js": js})
    assert code == 1
    assert "assets/engine-1c.js:1:" in err and f"'{name}' (CE-E05; E11-X02)" in err
    assert "E11-chart-engine.md" in err and "E14-drawings.md" not in err  # its own threat model


def test_the_manifest_registers_the_engine_debug_surface():
    handles = {h["identifier"]: h for h in guard.load_handles(guard.MANIFEST)}
    for name in ("__engine", "runBenchScene"):
        assert (handles[name]["threat"], handles[name]["requirement"]) == ("CE-E05", "E11-X02")
    assert set(guard.THREATS) >= {h["threat"] for h in handles.values()}  # each one explained
