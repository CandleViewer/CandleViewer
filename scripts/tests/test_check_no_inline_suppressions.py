"""Unit tests for tools/ci/check_no_inline_suppressions.py (E14-X03, #549; DR6, SR-E14-01)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.ci.check_no_inline_suppressions as check  # noqa: E402 - sys.path first (#549)

TODAY = "2026-10-24"
OK = "reason=reviewed-case owner=@basiltt review=2026-12-01"
SCOPE = "apps/web/src/features/drawings"
# One form per marker; `{a}` is the annotation (a block comment holds it inside).
FORMS = [
    "// eslint-disable-next-line react/no-danger{a}",
    "/* eslint-disable{a} */",
    "foo(); // eslint-disable-line no-console{a}",
    "// @ts-ignore{a}",
    "// @ts-expect-error{a}",
    "// nosemgrep: cv-drawings-text-to-html-sink{a}",
]
MARKER = re.compile(r"eslint-disable(?:-next-line|-line)?|@ts-ignore|@ts-expect-error|nosemgrep")


def _check(root: Path, capsys: pytest.CaptureFixture[str], files: dict[str, str], *paths: str):
    for rel, text in {
        check.CONFIG: json.dumps({"paths": paths or [f"{SCOPE}/**"]}),
        **files,
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    code = check.main(["--root", str(root), "--today", TODAY])
    return code, capsys.readouterr().err


@pytest.mark.parametrize("form", FORMS)
def test_a_bare_suppression_fails_naming_file_line_and_marker(tmp_path, capsys, form):
    files = {f"{SCOPE}/deep/a.tsx": f"export const a = 1;\n{form.format(a='')}\n"}
    code, err = _check(tmp_path, capsys, files)
    marker = MARKER.search(form)
    assert code == 1 and marker
    assert f"{SCOPE}/deep/a.tsx:2: {marker.group(0)}: suppression missing reason, owner" in err
    assert "DR6, SR-E14-01" in err


@pytest.mark.parametrize("form", FORMS)
def test_a_reviewed_annotation_passes(tmp_path, capsys, form):
    files = {f"{SCOPE}/a.ts": form.format(a=f" -- {OK}") + "\n"}
    assert _check(tmp_path, capsys, files) == (0, "")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("// @ts-expect-error reason=x owner=@basiltt review=2026-10-23", "has expired"),
        ("// @ts-expect-error reason=x owner=@basiltt review=2027-06-01", "expiry too far"),
        ("// @ts-expect-error owner=@basiltt review=2026-12-01", "missing reason"),
        ("// @ts-expect-error reason=x owner=basiltt review=2026-12-01", "is not @<handle>"),
        (f"/* eslint-disable */ {OK}", "missing reason, owner, review"),  # outside the comment
        (f"// @ts-ignore\n// {OK}", "missing reason, owner, review"),  # in the next comment
    ],
)
def test_an_annotation_is_judged_by_the_shared_grammar_in_its_own_comment(
    tmp_path, capsys, text, problem
):
    code, err = _check(tmp_path, capsys, {f"{SCOPE}/a.ts": text + "\n"})
    assert code == 1 and problem in err


def test_the_review_date_is_judged_against_the_given_day(tmp_path, capsys):
    _check(tmp_path, capsys, {f"{SCOPE}/a.ts": f"// @ts-ignore {OK}\n"})  # review=2026-12-01
    assert check.main(["--root", str(tmp_path), "--today", "2026-11-30"]) == 0
    assert check.main(["--root", str(tmp_path), "--today", "2026-12-02"]) == 1
    assert "has expired" in capsys.readouterr().err


def test_a_glob_means_what_the_path_filters_mean() -> None:
    assert check.covered("a/b/c.ts", ["a/**"]) and check.covered("a/c.ts", ["a/**/*.ts"])
    assert check.covered("a/b/c.ts", ["a/**/*.ts"]) and not check.covered("ax/c.ts", ["a/**"])
    assert not check.covered("a/b/c.ts", ["a/*.ts"])  # `*` stays inside one path segment
    assert check.covered("a/b.ts", ["a/?.ts"]) and not check.covered("a/b.ts", ["a?b.ts"])


def test_only_source_files_under_the_listed_paths_are_read(tmp_path, capsys):
    bare = "// @ts-ignore\n"
    files = {
        "apps/web/src/features/indicators/a.ts": bare,  # another feature
        f"{SCOPE}/notes.md": bare,  # not source
        f"{SCOPE}/node_modules/x/a.ts": bare,  # a build tree
        f"{SCOPE}/s.ts": "export const s = \"eslint-disable\"; const t = '@ts-ignore';\n",
        f"{SCOPE}/p.ts": "export const p = 1; // note: see the lint config\n",
    }
    assert _check(tmp_path, capsys, files) == (0, "")


def test_extending_the_path_list_extends_the_scan(tmp_path, capsys):
    files = {"apps/web/src/objecttree/a.ts": "// @ts-ignore\n", f"{SCOPE}/b.ts": "// @ts-ignore\n"}
    code, err = _check(tmp_path / "one", capsys, files)
    assert code == 1 and "objecttree" not in err  # out of scope until listed
    code, err = _check(
        tmp_path / "two", capsys, files, f"{SCOPE}/**", "apps/web/src/objecttree/a.ts"
    )
    assert code == 1 and "objecttree/a.ts:1" in err and f"{SCOPE}/b.ts:1" in err


@pytest.mark.parametrize(
    "config",
    ["{", '{"paths": []}', '{"paths": [1]}', '{"paths": ["/x/**"]}', '{"paths": ["../x"]}'],
)
def test_a_bad_path_list_is_a_config_error(tmp_path, capsys, config):
    (tmp_path / "tools/ci").mkdir(parents=True)
    (tmp_path / check.CONFIG).write_text(config, encoding="utf-8")
    assert check.main(["--root", str(tmp_path)]) == 2
    assert check.main(["--root", str(tmp_path / "missing")]) == 2  # no list at all


def test_the_script_runs_as_a_command(tmp_path, capsys):
    _check(tmp_path, capsys, {f"{SCOPE}/a.ts": "// nosemgrep: cv-x\n"})
    script = str(ROOT / "tools/ci/check_no_inline_suppressions.py")
    run = subprocess.run(  # noqa: S603 - the interpreter and the script under test (#549)
        [sys.executable, script, "--root", str(tmp_path), "--today", TODAY],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 1 and f"{SCOPE}/a.ts:1: nosemgrep" in run.stderr


def test_the_repository_is_clean() -> None:
    assert check.main([]) == 0


def _unlisted(root: Path, paths: list[str]) -> list[str]:
    """Drawing or object-tree code (a `drawing*` dir, an `object-tree*` name) not in `paths`."""
    named = re.compile(r"(?i)^drawings?(?:[-_.]|$)|^object-?tree")
    missing: list[str] = []
    for src in [*root.glob("apps/*/src"), *root.glob("packages/*/src")]:
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in check.SKIP_DIRS]
            for name in [*dirnames, *filenames]:
                is_dir = name in dirnames
                if named.match(name) and (is_dir or name.lower().startswith("object")):
                    rel = Path(dirpath, name).relative_to(root).as_posix()
                    if not check.covered(f"{rel}/x.ts" if is_dir else rel, paths):
                        missing.append(rel)
    return sorted(missing)


def test_the_tripwire_names_drawing_and_object_tree_code_outside_the_list(tmp_path):
    for rel in [
        f"{SCOPE}/a.ts",  # listed
        "apps/web/src/features/drawings-legacy/a.ts",
        "apps/web/src/objecttree/a.ts",
        "packages/ui/src/components/ObjectTree.tsx",
        "packages/chart-engine/src/layers/drawings/a.ts",
        "apps/web/src/features/indicators/drawings.ts",  # a file, not a directory: not drawing code
    ]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    assert _unlisted(tmp_path, [f"{SCOPE}/**"]) == [
        "apps/web/src/features/drawings-legacy",
        "apps/web/src/objecttree",
        "packages/chart-engine/src/layers/drawings",
        "packages/ui/src/components/ObjectTree.tsx",
    ]


def test_every_drawing_or_object_tree_path_is_a_listed_one() -> None:
    assert _unlisted(ROOT, check.load_paths(ROOT / check.CONFIG)) == []


def test_the_semgrep_rule_and_the_check_read_the_same_paths() -> None:
    text = (ROOT / ".semgrep/cv-drawings-text-to-html-sink.yml").read_text(encoding="utf-8")
    rule = yaml.safe_load(text)["rules"][0]
    assert rule["paths"]["include"] == check.load_paths(ROOT / check.CONFIG)
