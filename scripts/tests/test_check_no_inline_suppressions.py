"""Unit tests for tools/ci/check_no_inline_suppressions.py (E14-X03, #549; DR6, SR-E14-01)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.ci.check_no_inline_suppressions as check  # noqa: E402 - sys.path first (#549)
import tools.ci.suppressions as suppressions  # noqa: E402 - sys.path first (#549)

TODAY = "2026-10-24"
OWNER = "@CandleViewer/security"
OK = f"reason=reviewed-case owner={OWNER} review=2026-12-01"
SCOPE = "apps/web/src/features/drawings"
# One form per marker; `{a}` is the annotation (a block comment holds it inside).
FORMS = [
    "// eslint-disable-next-line react/no-danger{a}",
    "/* eslint-disable{a} */",
    "foo(); // eslint-disable-line no-console{a}",
    "// @ts-ignore{a}",
    "// @ts-ignorexyz{a}",
    "// @ts-expect-error{a}",
    "// @ts-expect-errorxyz{a}",
    "// nosemgrep: cv-drawings-text-to-html-sink{a}",
    "// nosem{a}",
    "// NOSEMGREP{a}",
    "// NoSemgrep: cv-drawings-text-to-html-sink{a}",
    "// nosemantic{a}",
    "// nosem_reason{a}",
    "/* eslint no-restricted-globals: off{a} */",
    "/* eslint @typescript-eslint/no-explicit-any: off{a} */",
]
MARKER = re.compile(
    r"eslint-disable(?:-next-line|-line)?|@ts-ignore|@ts-expect-error|(?i:nosem\w*)|eslint(?= )"
)


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


@pytest.mark.parametrize(
    "lines",
    [
        ["/*", "eslint-disable react/no-danger", "*/"],
        ["/**", " * @ts-ignore", " */"],
        ["/*", "** @ts-expect-error because", "*/"],  # tsc reads `(?:/|*)*` before the marker
    ],
)
def test_a_marker_opening_a_line_inside_a_block_comment_counts(tmp_path, capsys, lines):
    text = "\n".join(["export const a = 1;", *lines, "export const b = 2;"])
    code, err = _check(tmp_path, capsys, {f"{SCOPE}/a.ts": text})
    assert code == 1 and f"{SCOPE}/a.ts:3: " in err


def test_a_marker_opening_a_block_comment_line_takes_its_annotation(tmp_path, capsys):
    text = f"/*\neslint-disable react/no-danger -- {OK}\n*/\nexport const a = 1;\n"
    assert _check(tmp_path, capsys, {f"{SCOPE}/a.ts": text}) == (0, "")


def test_every_marker_on_a_line_is_judged_not_only_the_first(tmp_path, capsys):
    first = f"/* nosemgrep -- {OK} */"
    code, err = _check(
        tmp_path, capsys, {f"{SCOPE}/a.ts": f"{first} // @ts-expect-error: hidden\n"}
    )
    assert code == 1 and f"{SCOPE}/a.ts:1: @ts-expect-error: suppression missing" in err
    both = {f"{SCOPE}/a.ts": f"{first} // @ts-ignore -- {OK}\n"}
    assert _check(tmp_path / "two", capsys, both) == (0, "")


def test_only_the_security_team_may_own_a_drawing_path_suppression(tmp_path, capsys):
    """The shared grammar takes any `@handle`, the team form too: on these paths the escape is the
    Security engineer's review, not self-service (#4377's L5)."""
    handle = OK.replace(OWNER, "@basiltt")
    assert suppressions.field_problems(OK, date.fromisoformat(TODAY)) == []
    assert suppressions.field_problems(handle, date.fromisoformat(TODAY)) == []
    code, err = _check(tmp_path, capsys, {f"{SCOPE}/a.ts": f"// @ts-ignore {handle}\n"})
    assert code == 1 and f"owner '@basiltt' must be {OWNER}" in err


def test_a_drawing_path_suppression_names_one_owner(tmp_path, capsys):
    """The shared grammar reads the first `owner=`, so a second could ride behind the team's."""
    files = {f"{SCOPE}/a.ts": f"// @ts-ignore {OK} owner=@basiltt\n"}
    code, err = _check(tmp_path, capsys, files)
    assert code == 1 and "names one owner, not several" in err


@pytest.mark.parametrize("form", FORMS)
def test_a_reviewed_annotation_passes(tmp_path, capsys, form):
    files = {f"{SCOPE}/a.ts": form.format(a=f" -- {OK}") + "\n"}
    assert _check(tmp_path, capsys, files) == (0, "")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (f"// @ts-expect-error reason=x owner={OWNER} review=2026-10-23", "has expired"),
        (f"// @ts-expect-error reason=x owner={OWNER} review=2027-06-01", "expiry too far"),
        (f"// @ts-expect-error owner={OWNER} review=2026-12-01", "missing reason"),
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
        **{f"{SCOPE}/{d}/x/a.ts": bare for d in ("node_modules", "dist", "coverage", ".turbo")},
        f"{SCOPE}/s.ts": "export const s = \"eslint-disable\"; const t = '@ts-ignore';\n",
        f"{SCOPE}/p.ts": "export const p = 1; // note: see the lint config\n",
    }
    assert _check(tmp_path, capsys, files) == (0, "")


def test_a_directory_symlink_is_not_entered(tmp_path, capsys):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside/a.ts").write_text("// @ts-ignore\n", encoding="utf-8")
    (tmp_path / SCOPE).mkdir(parents=True)
    (tmp_path / SCOPE / "link").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert _check(tmp_path, capsys, {f"{SCOPE}/b.ts": "export {};\n"}) == (0, "")


@pytest.mark.parametrize("suffix", [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"])
def test_each_source_suffix_is_read(tmp_path, capsys, suffix):
    code, err = _check(tmp_path, capsys, {f"{SCOPE}/a{suffix}": "// @ts-ignore\n"})
    assert code == 1 and f"a{suffix}:1" in err


def test_a_config_other_than_the_default_names_the_paths(tmp_path, capsys):
    (tmp_path / "other").mkdir()
    config = tmp_path / "other/paths.json"
    config.write_text(json.dumps({"paths": ["lib/**"]}), encoding="utf-8")
    for rel in ("lib/a.ts", f"{SCOPE}/a.ts"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("// @ts-ignore\n", encoding="utf-8")
    assert check.main(["--root", str(tmp_path), "--config", str(config), "--today", TODAY]) == 1
    err = capsys.readouterr().err
    assert "lib/a.ts:1" in err and SCOPE not in err


def test_without_a_day_the_review_date_is_judged_against_today(tmp_path, capsys):
    today = datetime.now(UTC).date()
    for review, code in ((today + timedelta(days=10), 0), (today - timedelta(days=10), 1)):
        text = f"// @ts-ignore reason=x owner={OWNER} review={review}\n"
        _check(tmp_path, capsys, {f"{SCOPE}/a.ts": text})
        assert check.main(["--root", str(tmp_path)]) == code
    assert "has expired" in capsys.readouterr().err


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


def test_the_repository_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Judged apart from the review window: a future expiry fails the lint job, which runs the check
    on the real clock, and not every pull request's governance shard (#4377's Nit 6)."""
    real = suppressions.field_problems
    window = ("has expired", "expiry too far")
    monkeypatch.setattr(
        check,
        "field_problems",
        lambda t, day: [p for p in real(t, day) if not any(w in p for w in window)],
    )
    assert check.main(["--today", TODAY]) == 0


def _unlisted(root: Path, paths: list[str]) -> list[str]:
    """Drawing or object-tree code (a `drawing*` dir, camel-cased too, an `object-tree*` name) not
    in `paths`."""
    named = re.compile(r"^(?i:drawings?)(?:[-_.A-Z0-9]|$)|(?i:^object-?tree)")
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
        "apps/web/src/features/drawingTools/a.ts",
        "apps/web/src/features/DRAWINGS/a.ts",
        "apps/web/src/features/DRAWING_TOOLS/a.ts",
        "apps/web/src/features/drawingsheet/a.ts",  # one word: not drawing code
        "apps/web/src/objecttree/a.ts",
        "packages/ui/src/components/ObjectTree.tsx",
        "packages/chart-engine/src/layers/drawings/a.ts",
        "apps/web/src/features/indicators/drawings.ts",  # a file, not a directory: not drawing code
    ]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    assert _unlisted(tmp_path, [f"{SCOPE}/**"]) == [
        "apps/web/src/features/DRAWINGS",
        "apps/web/src/features/DRAWING_TOOLS",
        "apps/web/src/features/drawingTools",
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
