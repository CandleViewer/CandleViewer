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

import tools.ci.check_no_inline_suppressions as check  # noqa: E402 - sys.path first

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


def _tree(root: Path, files: dict[str, str], paths: tuple[str, ...] = (f"{SCOPE}/**",)) -> Path:
    for rel, text in {check.CONFIG: json.dumps({"paths": list(paths)}), **files}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = check.main(["--root", str(root), "--today", TODAY])
    return code, capsys.readouterr().err


@pytest.mark.parametrize("form", FORMS)
def test_a_bare_suppression_fails_naming_file_line_and_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], form: str
) -> None:
    root = _tree(tmp_path, {f"{SCOPE}/deep/a.tsx": f"export const a = 1;\n{form.format(a='')}\n"})
    code, err = _run(root, capsys)
    marker = MARKER.search(form)
    assert code == 1 and marker
    assert f"{SCOPE}/deep/a.tsx:2: {marker.group(0)}: suppression missing reason, owner" in err
    assert "DR6, SR-E14-01" in err


@pytest.mark.parametrize("form", FORMS)
def test_a_reviewed_annotation_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], form: str
) -> None:
    root = _tree(tmp_path, {f"{SCOPE}/a.ts": form.format(a=f" -- {OK}") + "\n"})
    assert _run(root, capsys) == (0, "")


@pytest.mark.parametrize(
    ("annotation", "problem"),
    [
        ("reason=x owner=@basiltt review=2026-10-23", "has expired"),
        ("reason=x owner=@basiltt review=2027-06-01", "expiry too far"),
        ("reason=x owner=@basiltt review=soon", "not YYYY-MM-DD"),
        ("owner=@basiltt review=2026-12-01", "missing reason"),
        ("reason=x review=2026-12-01", "missing owner"),
        ("reason=x owner=basiltt review=2026-12-01", "is not @<handle>"),
    ],
)
def test_an_annotation_is_judged_by_the_shared_grammar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], annotation: str, problem: str
) -> None:
    root = _tree(tmp_path, {f"{SCOPE}/a.ts": f"// @ts-expect-error {annotation}\n"})
    code, err = _run(root, capsys)
    assert code == 1 and problem in err


@pytest.mark.parametrize(
    "text",
    [
        f"/* eslint-disable */ {OK}\n",  # outside the block comment
        f"// @ts-ignore\n// {OK}\n",  # in the next line's comment
    ],
)
def test_the_annotation_must_sit_in_the_suppressing_comment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    root = _tree(tmp_path, {f"{SCOPE}/a.ts": text})
    code, err = _run(root, capsys)
    assert code == 1 and "suppression missing reason, owner, review" in err


def test_the_review_date_is_judged_against_the_given_day(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path, {f"{SCOPE}/a.ts": f"// @ts-ignore {OK}\n"})  # review=2026-12-01
    assert check.main(["--root", str(root), "--today", "2026-11-30"]) == 0
    assert check.main(["--root", str(root), "--today", "2026-12-02"]) == 1
    assert "has expired" in capsys.readouterr().err


def test_a_glob_means_what_the_path_filters_mean() -> None:
    assert check.covered("a/b/c.ts", ["a/**"]) and check.covered("a/c.ts", ["a/**/*.ts"])
    assert check.covered("a/b/c.ts", ["a/**/*.ts"]) and not check.covered("ax/c.ts", ["a/**"])
    assert not check.covered("a/b/c.ts", ["a/*.ts"])  # `*` stays inside one path segment
    assert check.covered("a/b.ts", ["a/?.ts"]) and not check.covered("a/b.ts", ["a?b.ts"])


def test_only_source_files_under_the_listed_paths_are_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = "// @ts-ignore\n"
    root = _tree(
        tmp_path,
        {
            "apps/web/src/features/indicators/a.ts": bare,  # another feature
            f"{SCOPE}/notes.md": bare,  # not source
            f"{SCOPE}/node_modules/x/a.ts": bare,  # a build tree
            f"{SCOPE}/s.ts": "export const s = \"eslint-disable\"; const t = '@ts-ignore';\n",
            f"{SCOPE}/p.ts": "export const p = 1; // note: see the lint config\n",
        },
    )
    assert _run(root, capsys) == (0, "")


def test_extending_the_path_list_extends_the_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {"apps/web/src/objecttree/a.ts": "// @ts-ignore\n", f"{SCOPE}/b.ts": "// @ts-ignore\n"}
    code, err = _run(_tree(tmp_path / "one", files), capsys)
    assert code == 1 and "objecttree" not in err  # the second file is out of scope until listed
    listed = (f"{SCOPE}/**", "apps/web/src/objecttree/a.ts")  # a single-file entry works too
    code, err = _run(_tree(tmp_path / "two", files, listed), capsys)
    assert code == 1 and "objecttree/a.ts:1" in err and f"{SCOPE}/b.ts:1" in err


@pytest.mark.parametrize(
    "config",
    [
        "{",
        "[]",
        '{"paths": []}',
        '{"paths": [1]}',
        '{"paths": ["/abs/**"]}',
        '{"paths": ["../x/**"]}',
    ],
)
def test_a_bad_path_list_is_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config: str
) -> None:
    (tmp_path / "tools/ci").mkdir(parents=True)
    (tmp_path / check.CONFIG).write_text(config, encoding="utf-8")
    assert _run(tmp_path, capsys)[0] == 2
    assert _run(tmp_path / "missing", capsys)[0] == 2  # no list at all


def test_the_script_runs_as_a_command(tmp_path: Path) -> None:
    root = _tree(tmp_path, {f"{SCOPE}/a.ts": "// nosemgrep: cv-x\n"})
    script = str(ROOT / "tools/ci/check_no_inline_suppressions.py")
    run = subprocess.run(  # noqa: S603 - the interpreter and the script under test
        [sys.executable, script, "--root", str(root), "--today", TODAY],
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


def test_the_tripwire_names_drawing_and_object_tree_code_outside_the_list(tmp_path: Path) -> None:
    for rel in [
        f"{SCOPE}/a.ts",  # listed
        "apps/web/src/features/drawings-legacy/a.ts",
        "apps/web/src/objecttree/a.ts",
        "packages/ui/src/components/ObjectTree.tsx",
        "packages/chart-engine/src/layers/drawings/a.ts",
        "apps/web/src/features/indicators/drawings.ts",  # a file, not a directory: not drawing code
    ]:
        _tree(tmp_path, {rel: ""})
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
