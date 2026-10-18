"""Tests for scripts/check_secrets_hygiene.py (E43-T06)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_secrets_hygiene as h

REAL = "AbCdEfGhIjKlMnOpQrSt"  # 20 alnum chars, no dummy prefix (synthetic, test-only)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_fixture_with_real_looking_key_fails_and_names_file(tmp_path: Path) -> None:
    _write(tmp_path, "services/api/tests/fixtures/bybit/a.json", f'{{"api_key": "{REAL}"}}')
    errors = h.check_fixtures(tmp_path)
    assert len(errors) == 1
    assert "services/api/tests/fixtures/bybit/a.json" in errors[0]


def test_fixture_with_dummy_prefix_passes(tmp_path: Path) -> None:
    _write(tmp_path, "tests/fixtures/a.json", f'{{"api_key": "{h.DUMMY_PREFIX}{REAL}"}}')
    assert h.check_fixtures(tmp_path) == []


def test_fixture_signature_and_private_key_fail(tmp_path: Path) -> None:
    _write(tmp_path, "tests/fixtures/s.json", '{"sign": "' + "a" * 64 + '"}')
    _write(tmp_path, "tests/fixtures/k.txt", "-----BEGIN PRIVATE KEY-----")
    assert len(h.check_fixtures(tmp_path)) == 2


def test_repo_fixtures_are_clean() -> None:
    assert h.check_fixtures(Path(__file__).resolve().parents[2]) == []


def test_dev_env_ok_and_violations(tmp_path: Path) -> None:
    _write(tmp_path, ".gitignore", ".env\n.env.*\n")
    _write(tmp_path, ".env.example", "# c\nCV_ENV=demo\nBYBIT_API_SECRET=\n")
    assert h.check_dev_env(tmp_path) == []
    _write(tmp_path, ".env.example", f"BYBIT_API_SECRET={REAL}\n")
    assert any("non-empty" in e for e in h.check_dev_env(tmp_path))
    _write(tmp_path, ".gitignore", "node_modules\n")
    assert any(".gitignore" in e for e in h.check_dev_env(tmp_path))


def test_repo_dev_env_is_clean() -> None:
    assert h.check_dev_env(Path(__file__).resolve().parents[2]) == []


@pytest.mark.parametrize("line", ["run: set -x", "run: set -euxo pipefail", "run: printenv", "run: env | sort"])
def test_workflow_leaks_flagged(tmp_path: Path, line: str) -> None:
    _write(tmp_path, ".github/workflows/w.yml", f"jobs:\n  a:\n    steps:\n      - {line}\n")
    assert h.check_workflows(tmp_path)


def test_workflow_clean_and_allow_marker(tmp_path: Path) -> None:
    _write(tmp_path, ".github/workflows/w.yml", "      - run: set -euo pipefail\n      - run: env # x\n")
    assert h.check_workflows(tmp_path) == []
    _write(tmp_path, ".github/workflows/w.yml", "      - run: set -x # secrets-hygiene: allow\n")
    assert h.check_workflows(tmp_path) == []


def test_repo_workflows_report() -> None:
    # Informational guard: repository workflows must have no tracing/env dumps.
    assert h.check_workflows(Path(__file__).resolve().parents[2]) == []


# #3274: workflows mode also scans the shell scripts a workflow's `run:` steps invoke.
WF = ".github/workflows/w.yml"


def _runs(command: str) -> str:
    return f"jobs:\n  a:\n    steps:\n      - run: {command}\n"


def test_run_script_tracing_fails_naming_script_and_workflows(tmp_path: Path) -> None:
    _write(tmp_path, WF, _runs("bash tools/x.sh"))
    _write(tmp_path, ".github/workflows/nightly.yml", _runs("bash tools/x.sh"))
    _write(tmp_path, "tools/x.sh", "#!/usr/bin/env bash\nset -euxo pipefail\n")
    assert h.check_workflows(tmp_path) == [
        "tools/x.sh:2: 'set -x' tracing (SR-146); run by nightly.yml, w.yml"
    ]
    assert h.main(["workflows", "--root", str(tmp_path)]) == 1
    _write(tmp_path, "tools/x.sh", "#!/usr/bin/env bash\nset -euo pipefail\n")
    assert h.check_workflows(tmp_path) == []


def test_run_script_env_dump_fails(tmp_path: Path) -> None:
    _write(tmp_path, WF, _runs("./scripts/x.sh"))
    _write(tmp_path, "scripts/x.sh", "echo start\nprintenv\n")
    assert h.check_workflows(tmp_path) == [
        "scripts/x.sh:2: environment dump (SR-146); run by w.yml"
    ]


def test_script_no_workflow_runs_is_not_scanned(tmp_path: Path) -> None:
    run = "bash tools/run.sh && idle.sh && chmod +x tools/idle.sh && echo tools/idle.sh"
    _write(tmp_path, WF, _runs(f"{run}  # ; bash tools/idle.sh"))
    _write(tmp_path, "tools/run.sh", "set -x\n")
    _write(tmp_path, "tools/idle.sh", "set -x\n")
    _write(tmp_path, "idle.sh", "set -x\n")  # a bare `idle.sh` is a PATH lookup, not this file
    assert h.check_workflows(tmp_path) == [
        "tools/run.sh:1: 'set -x' tracing (SR-146); run by w.yml"
    ]


@pytest.mark.parametrize(
    ("run", "script"),
    [
        ("|\n          # old; bash tools/idle.sh\n          echo ok", ""),
        ("bash tools/a.sh", "echo ok  # was: cd x; bash tools/idle.sh\n"),
    ],
    ids=["workflow-block", "script"],
)
def test_commented_out_invocation_is_not_followed(tmp_path: Path, run: str, script: str) -> None:
    _write(tmp_path, WF, _runs(run))
    _write(tmp_path, "tools/a.sh", script)
    _write(tmp_path, "tools/idle.sh", "set -x\n")
    assert h.check_workflows(tmp_path) == []


def test_run_prose_is_not_read_as_sourcing_a_file(tmp_path: Path) -> None:
    _write(tmp_path, WF, _runs('echo "Gate failed (see the log). docs/notes.md has the fix."'))
    _write(tmp_path, "docs/notes.md", "# Fix\n\n    set -x\n")
    assert h.check_workflows(tmp_path) == []


@pytest.mark.parametrize(
    "run", ["source scripts/ci/lib", ". scripts/ci/lib", "source scripts/ci/lib.env"]
)
def test_run_sourced_file_without_a_shell_suffix_is_scanned(tmp_path: Path, run: str) -> None:
    lib = run.split()[1]
    _write(tmp_path, WF, _runs(run))
    _write(tmp_path, lib, "set -x\n")
    assert h.check_workflows(tmp_path) == [f"{lib}:1: 'set -x' tracing (SR-146); run by w.yml"]


@pytest.mark.parametrize("skipped", ["# never set -x", "set -x  # secrets-hygiene: allow"])
def test_run_script_comment_or_allow_marked_line_is_skipped(tmp_path: Path, skipped: str) -> None:
    _write(tmp_path, WF, _runs("sh scripts/x.sh"))
    _write(tmp_path, "scripts/x.sh", f"{skipped}\nenv | sort\n")
    assert h.check_workflows(tmp_path) == [
        "scripts/x.sh:2: environment dump (SR-146); run by w.yml"
    ]


def test_run_script_paths_outside_the_repo_are_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(tmp_path, "out.sh", "set -x\n")
    run = "bash ../out.sh; . tools/../../out.sh; bash tools/ln.sh; bash out.sh; ./tools/ok.sh"
    _write(repo, WF, f"      - working-directory: {tmp_path}\n        run: {run}\n")
    _write(repo, "tools/ok.sh", "printenv\n")
    (repo / "tools/ln.sh").symlink_to(tmp_path / "out.sh")
    assert h.check_workflows(repo) == ["tools/ok.sh:1: environment dump (SR-146); run by w.yml"]


@pytest.mark.parametrize(
    "run",
    [
        "bash tools/x.sh",
        "sh -e tools/x.sh",
        "source tools/x.sh",
        ". ./tools/x.sh",
        "./tools/x.sh",
        "set -eu; CV_X=1 tools/x.sh",
        'cd . && bash "tools/x.sh"',
        '"bash tools/x.sh"',
        "if true; then ./tools/x.sh; fi",
        "|\n          set -euo pipefail\n          bash tools/x.sh",
        '|\n          echo "see #1" && bash tools/x.sh',
        '|\n          echo "a \\" # b" && bash tools/x.sh',
        "! bash tools/x.sh",
        "if ! bash tools/x.sh; then exit 1; fi",
        "timeout 300 bash tools/x.sh",
        "timeout --preserve-status -k 5 10m ./tools/x.sh",
        "env -i CV_X=1 bash tools/x.sh",
        "nohup bash tools/x.sh &",
        "nice -n 10 bash tools/x.sh",
        "xvfb-run -a bash tools/x.sh",
        "sudo -E bash tools/x.sh",
        "uv run --frozen bash tools/x.sh",
        "stdbuf -oL bash tools/x.sh",
        "command bash tools/x.sh",
        "bash -o pipefail tools/x.sh",
        "bash --noprofile --norc tools/x.sh",
        "bash -eu tools/x.sh",
        "bash -euo pipefail tools/x.sh",
        'bash "$GITHUB_WORKSPACE/tools/x.sh"',
        "${GITHUB_WORKSPACE}/tools/x.sh",
        "/bin/bash tools/x.sh",
        "/usr/bin/bash -euo pipefail tools/x.sh",
        "/bin/sh -e tools/x.sh",
        "/usr/bin/sh tools/x.sh",
        "/usr/bin/env bash --noprofile tools/x.sh",
        "/usr/bin/env sh tools/x.sh",
        'bash "$GITHUB_WORKSPACE"/tools/x.sh',
        'bash -c "./tools/x.sh"',
        "sh -ec 'tools/x.sh arg'",
        'timeout 300 bash -o pipefail -c "./tools/x.sh"',
        'bash -c "exec ./tools/x.sh"',
        'bash -c -- "CV_X=1 ./tools/x.sh"',
        'bash "$GITHUB_WORKSPACE/tools/y.sh" "x #1"; ./tools/x.sh',
    ],
)
def test_run_script_forms_are_followed(tmp_path: Path, run: str) -> None:
    _write(tmp_path, WF, _runs(run))
    _write(tmp_path, "tools/x.sh", "printenv\n")
    assert h.check_workflows(tmp_path) == ["tools/x.sh:1: environment dump (SR-146); run by w.yml"]


@pytest.mark.parametrize("workdir", ["tools", "${{ github.workspace }}/tools"])
def test_run_script_path_is_tried_from_the_working_directory(tmp_path: Path, workdir: str) -> None:
    _write(tmp_path, WF, f"      - working-directory: {workdir}\n        run: ./x.sh\n")
    _write(tmp_path, "tools/x.sh", "printenv\n")
    assert h.check_workflows(tmp_path) == ["tools/x.sh:1: environment dump (SR-146); run by w.yml"]


def test_run_script_without_suffix_is_followed_by_its_shebang(tmp_path: Path) -> None:
    _write(tmp_path, WF, _runs("./tools/x"))
    _write(tmp_path, "tools/x", "#!/usr/bin/env bash\nprintenv\n")
    assert h.check_workflows(tmp_path) == ["tools/x:2: environment dump (SR-146); run by w.yml"]


@pytest.mark.parametrize(
    ("shebang", "traced"),
    [("#!/bin/bash -x", 1), ("#!/bin/sh -ex", 1), ("#!/usr/bin/env -S bash -x", 1)]
    + [("#!/usr/bin/env -S bash -o xtrace", 1), ("#!/usr/bin/env -S bash +o xtrace", 0)]
    + [("#!/usr/bin/env -S zsh --xtrace", 1), ("#!/opt/my-xtool/bin/bash", 0)]
    + [("#!/usr/bin/env bash", 0), ("#!/bin/bash -e", 0), ("#!/bin/bash -euo pipefail", 0)]
    # #3400: a longer option name; the allow marker (`env -S` reads a `#` word as a comment).
    + [("#!/usr/bin/env -S zsh --xtrace-not", 0)]
    + [("#!/usr/bin/env -S bash -x # secrets-hygiene: allow", 0)]
    # #3400: verbose, which echoes each line read.
    + [("#!/bin/bash -v", 1), ("#!/usr/bin/env -S bash --verbose", 1)]
    # #3400: `env -S` takes the quotes off its words (uutils env 0.8.0 traced it).
    + [('#!/usr/bin/env -S bash "-x"', 1)],
)
def test_run_script_shebang_x_flag_traces(tmp_path: Path, shebang: str, traced: int) -> None:
    _write(tmp_path, WF, _runs("./tools/x.sh"))
    _write(tmp_path, "tools/x.sh", f"{shebang}\nprintenv\n")
    hits = ["tools/x.sh:1: 'set -x' tracing"] * traced + ["tools/x.sh:2: environment dump"]
    assert h.check_workflows(tmp_path) == [f"{hit} (SR-146); run by w.yml" for hit in hits]


@pytest.mark.parametrize(
    "run", ["./tools/gen.py", "python3 tools/gen.py", 'bash -c "tools/gen.py --check"']
)
def test_run_python_script_is_not_followed(tmp_path: Path, run: str) -> None:
    _write(tmp_path, WF, _runs(run))
    _write(tmp_path, "tools/gen.py", '#!/usr/bin/env python3\n"""Never set -x in CI."""\n')
    assert h.check_workflows(tmp_path) == []


def test_run_script_dotdot_inside_the_repo_is_followed(tmp_path: Path) -> None:
    _write(tmp_path, WF, "      - working-directory: tools\n        run: bash ../scripts/y.sh\n")
    _write(tmp_path, "scripts/y.sh", "set -x\n")
    assert h.check_workflows(tmp_path) == [
        "scripts/y.sh:1: 'set -x' tracing (SR-146); run by w.yml"
    ]


def test_run_script_that_does_not_resolve_never_fails(tmp_path: Path) -> None:
    _write(tmp_path, WF, _runs("bash tools/missing.sh && ./scripts/gone.sh && . tools/x.sh/y.sh"))
    _write(tmp_path, "tools/x.sh", "set -x\n")
    assert h.check_workflows(tmp_path) == []
    assert h.main(["workflows", "--root", str(tmp_path)]) == 0


def test_run_script_sourced_helper_is_scanned(tmp_path: Path) -> None:
    _write(tmp_path, WF, _runs("bash tools/a.sh"))
    _write(tmp_path, "tools/a.sh", "set -eu\nsource tools/lib.sh\n")
    _write(tmp_path, "tools/lib.sh", "set -x\n")
    assert h.check_workflows(tmp_path) == [
        "tools/lib.sh:1: 'set -x' tracing (SR-146); run by w.yml via tools/a.sh"
    ]


def test_run_script_nested_scripts_are_followed_transitively_once_each(tmp_path: Path) -> None:
    _write(tmp_path, WF, _runs("bash tools/a.sh"))
    _write(tmp_path, "tools/a.sh", '. "$GITHUB_WORKSPACE/tools/b.sh"\n')
    _write(tmp_path, "tools/b.sh", "bash tools/a.sh  # a cycle\n./tools/c.sh\n")
    _write(tmp_path, "tools/c.sh", "printenv\n")
    assert h.check_workflows(tmp_path) == [
        "tools/c.sh:1: environment dump (SR-146); run by w.yml via tools/b.sh"
    ]


@pytest.mark.parametrize("script", ["tools/loop.sh", "tools/loop"])
def test_run_script_symlink_loop_fails_closed(tmp_path: Path, script: str) -> None:
    _write(tmp_path, WF, _runs(f"./{script}"))
    (tmp_path / "tools").mkdir()
    (tmp_path / script).symlink_to(Path(script).name)
    assert h.check_workflows(tmp_path) == [
        f"{script}: unreadable script (SR-146 scan); run by w.yml"
    ]


# #3294: the forms of SR-146 tracing, on a workflow `run:` line and in a script a workflow runs
# (one shared rule). A row per form, and per rule or alternative, so that dropping one fails.
TRACED = [
    # Caught before #3294.
    "set -x",
    "set -euxo pipefail",
    "bash -x ci.sh",
    "/bin/bash -x ci.sh",
    "/usr/local/bin/bash -x ci.sh",
    "/usr/bin/env bash -x ci.sh",
    "zsh --xtrace ci.sh",
    # #3294: `set` with x in a later group or as -o xtrace, and after a quote or bracket.
    "set -x; make test",
    "set -e -x",
    "set -eu -xo pipefail",
    "set +e -x",
    "set -o xtrace",
    "set -eo xtrace",
    "set -o errexit -o xtrace",
    "if true; then set -x; fi",
    "for f in a b; do set -x; done",
    "(set -x; make test)",
    "{ set -x; make test; }",
    "out=`set -x; make test`",
    'bash -c "set -x; make test"',
    "sh -c 'set -x'",
    'eval "set -x"',
    "${CV_DEBUG:+set -x}",
    # #3294: a shell started tracing, past its other options.
    "bash -ex ci.sh",
    "bash -xe ci.sh",
    "bash -e -x ci.sh",
    "bash -o xtrace ci.sh",
    "bash -o pipefail -x ci.sh",
    "bash -O extglob -x ci.sh",
    "bash --noprofile --norc -x ci.sh",
    "sh -x ci.sh",
    "sh -cx 'make test'",
    'bash -xc "make test"',
    "dash -x ci.sh",
    "ksh -x ci.sh",
    "zsh -x ci.sh",
    # #3294: a capital in the tracing group, +o before it, --xtrace past an option's argument.
    "set -Eeuxo pipefail",
    "set +o nounset -x",
    "bash --rcfile x.rc --xtrace ci.sh",
    # #3294: a second command word traces after one that does not.
    'sh -c "sh -x ci.sh"',
    # #3294: shells the base rule (bash -x anywhere) caught, kept by name or path: rbash, and a path
    # from $VAR or ~user, with an empty segment, `-`, `.` or a $NAME segment.
    "rbash -x ci.sh",
    "$HOME/bin/bash -x ci.sh",
    "~runner/bin/bash -x ci.sh",
    "//bin/bash -x ci.sh",
    "/opt/my-tools/bash -x ci.sh",
    "/usr/local/bash-5.2/bin/bash -x ci.sh",
    "/opt/$TOOL/bin/bash -x ci.sh",
    # #3400: the shellcheck exception ends with its command; zsh drops `-` and `_` from a long
    # option's name (zsh(1) INVOCATION, zshoptions(1)).
    "shellcheck -s bash ci.sh && bash -x ci.sh",
    "zsh --xtrace- ci.sh",
    # #3400: shopt's set -o names, with -s and -o in any order (bash 5.3).
    "shopt -so xtrace",
    "shopt -s -o xtrace",
    "shopt -o -s errexit xtrace",
    "shopt -pso xtrace",
    "shopt -s -o -- xtrace",
    # #3400: zsh reads an option name in any case and without its `_` (zshoptions(1)); setopt
    # sets and unsetopt unsets, each flipped by a `+` flag or a `no` name (Src/options.c).
    "set -o XTRACE",
    "set -o x_trace",
    "zsh --X-Trace ci.sh",
    "setopt xtrace",
    "setopt XTRACE",
    "setopt err_exit _x_trace",
    "setopt -x",
    "setopt -o xtrace",
    "unsetopt noxtrace",
    "unsetopt +o xtrace",
    "set +o noxtrace",
    # #3400: bash turns on the options SHELLOPTS lists when it starts; dash exports it.
    "SHELLOPTS=xtrace",
    "env SHELLOPTS=braceexpand:xtrace bash ci.sh",
    'export SHELLOPTS="$SHELLOPTS:xtrace"',
    # #3400: verbose echoes each line as the shell reads it: an eval string with its values in it
    # (bash 5.3: X=s; eval "echo $X" prints echo s), a step's script with its secrets in it.
    "set -v",
    "set -euvo pipefail",
    "set -o verbose",
    "bash -v ci.sh",
    "bash --verbose ci.sh",
    "shopt -so verbose",
    "setopt VERBOSE",
    "env SHELLOPTS=verbose bash ci.sh",
    # #3400: a DEBUG trap runs before each command, whatever it prints; zsh's TRAPDEBUG too.
    "trap 'echo \"+ $BASH_COMMAND\"' DEBUG",
    "trap -- 'echo $BASH_COMMAND' INT debug",
    "TRAPDEBUG() { print -r -- $ZSH_DEBUG_CMD; }",
    # #3400: the shell takes the quotes and escapes off each word, an empty quoted string inside
    # a word too (bash 5.3 traced each).
    'set "-x"',
    "set '-x'",
    'set -o "xtrace"',
    'set -"x"',
    "set -e''x",
    "set $'-x'",
    "set -\\x",
    'bash "-x" ci.sh',
    '"bash" -x ci.sh',
    "b\\ash -x ci.sh",
    "'/bin/bash' -x ci.sh",
    'shopt -so "xtrace"',
    # #3400: a shell named by $BASH (the running bash) or $SHELL (the login shell).
    '"$BASH" -x ci.sh',
    "$SHELL -x ci.sh",
    "${SHELL} -x ci.sh",
    "${SHELL:-sh} -x ci.sh",
    'exec "$BASH" -x "$0" "$@"',
    # #3400: a long option's argument (bash's --rcfile and --init-file, zsh's --emulate), and
    # redirections, which the shell takes out of the words it passes.
    "bash --rcfile x.rc -x ci.sh",
    "bash --init-file x -x ci.sh",
    "zsh --emulate csh -x ci.sh",
    "bash 2>&1 -x ci.sh",
    "bash >log -x ci.sh",
    "bash > log -x ci.sh",
    "bash &>>log -x ci.sh",
    "bash {fd}>log -x ci.sh",
    'bash </dev/null -x -c "make test"',
    "bash <<'EOF' -x",
    'bash <<<"" -x ci.sh',
    # #3400: a shell's path with any character a word keeps in a segment, and $NAME or ${NAME}
    # (bash 5.3 ran each through a link to bash); option letters, or a whole option word, as an
    # expansion's default or alternate value (`set -e${DEBUG:+x}` traces once DEBUG is set).
    "/opt/bash@5/bin/bash -x ci.sh",
    "/opt/gcc+x/bin/bash -x ci.sh",
    "/~u/bash -x ci.sh",
    "/opt/${X}y/bin/bash -x ci.sh",
    "/opt/a%2C,b=1/bin/bash -x ci.sh",
    "/opt/bash-5*/bin/bash -x ci.sh",
    "set -e${DEBUG:+x}",
    "set -eu${TRACE:+x}o pipefail",
    "set -e${O:-v}",
    "set -e${CI:+u} -x",
    "set ${DEBUG:+-x}",
    "bash ${DEBUG:+-o xtrace} ci.sh",
]
NOT_TRACED = [
    "set -e",
    "set -euo pipefail",
    "set -o pipefail",
    "set +x",
    "set +o xtrace",
    "set -e +x",
    "set -- -x",
    "set - -x",
    "reset -x",
    "bash ci.sh -x",
    "bash +x ci.sh",
    "bash +o xtrace ci.sh",
    "sh -c 'echo -x'",
    'echo "-x"',
    "ssh -x host uptime",
    "shellcheck -x ci.sh",
    "tar -xzf a.tgz",
    "unzip -o a.zip -x '*.md'",
    "grep -x pattern file",
    "xargs -x echo",
    "mybash -x ci.sh",
    "x-bash -x ci.sh",
    "foo.bash -x ci.sh",
    "zap.sh -x",
    "tools/sh -x ci.sh",
    "./bash -x ci.sh",
    "bin/bash -x ci.sh",
    "du -sh -x /var",
    "# set -o xtrace; bash -x ci.sh",
    # #3400: the dialect shellcheck checks, a URL's last segment, an option name xtrace only starts.
    "shellcheck -s bash -x ci.sh",
    "shellcheck --shell=sh -x ci.sh",
    "shellcheck -e SC1091 --rcfile .shellcheckrc --shell bash -x ci.sh",
    "/usr/bin/shellcheck -s dash -x ci.sh",
    "wget -O- https://example.com/sh -x",
    "curl https://x/bash -x y",
    "zsh --xtrace-not ci.sh",
    "set -o xtraced",
    # #3400: shopt without -s and -o (a query, a listing, unset, no set -o name), zsh's options
    # turned off, and other SHELLOPTS values.
    "shopt -s nullglob",
    "shopt -o xtrace",
    "shopt -po xtrace",
    "shopt -uo xtrace",
    "shopt -s xtrace",
    "set -o noxtrace",
    "setopt noxtrace",
    "setopt +o xtrace",
    "unsetopt xtrace",
    "unsetopt -o xtrace",
    "SHELLOPTS=braceexpand:errexit",
    'echo "$SHELLOPTS"',
    # #3400: another tool's --verbose and set -o vi; a DEBUG trap reset, listed or given no
    # action; other traps, which run once, on their event.
    "pytest --verbose",
    "set -o vi",
    "trap - DEBUG",
    "trap DEBUG",
    "trap -p DEBUG",
    "trap '' DEBUG",
    "trap 'rm -f x.tmp' EXIT",
    "trap 'echo \"failed: $BASH_COMMAND\"' ERR",
    # #3400: an empty quoted word is a word (`set "" -x` sets $1); quotes inside a word and an
    # escaped space join it (`bash\ -x` is one word); a trap's quoted action is one word; the
    # rcfile named -x; other variables; a process substitution, a file bash runs with -x as $1.
    'set "" -x',
    'my"bash" -x ci.sh',
    "bash\\ -x ci.sh",
    "trap 'echo DEBUG' EXIT",
    "bash --rcfile -x ci.sh",
    "$SHELLCHECK -x ci.sh",
    "echo ${BASH_VERSION} -x",
    "bash <(make) -x",
    # #3400: a path naming no shell (`x+bash` is a file in /opt); an expansion giving x only as
    # its error message (`${O:?x}` stops the shell when O is unset). Not reported though they
    # trace: an option the scan cannot read (FLAGS may hold x), a `:` in a shell's path (a rule
    # starts no word after a `:`, as in a URL: `https://example.com/sh -x`).
    "/opt/x+bash -x ci.sh",
    "set -e${O:?x}",
    "set -e$FLAGS",
    "/opt/a:b/bin/bash -x ci.sh",
]
VIA = ["run", "script"]


def _sr146_in(tmp_path: Path, line: str, via: str) -> list[str]:
    """``line`` in a workflow's `run:` block, or as line 1 of a script a workflow step runs."""
    if via == "run":
        _write(tmp_path, WF, _runs(f"|\n          {line}"))
    else:
        _write(tmp_path, WF, _runs("bash tools/x.sh"))
        _write(tmp_path, "tools/x.sh", f"{line}\n")
    return h.check_workflows(tmp_path)


@pytest.mark.parametrize("via", VIA)
@pytest.mark.parametrize("line", TRACED)
def test_tracing_form_is_flagged(tmp_path: Path, line: str, via: str) -> None:
    hit = "w.yml:5: 'set -x' tracing (SR-146)"
    if via == "script":
        hit = "tools/x.sh:1: 'set -x' tracing (SR-146); run by w.yml"
    assert _sr146_in(tmp_path, line, via) == [hit]


@pytest.mark.parametrize("via", VIA)
@pytest.mark.parametrize("line", TRACED)
def test_tracing_form_with_the_allow_marker_passes(tmp_path: Path, line: str, via: str) -> None:
    assert _sr146_in(tmp_path, f"{line}  # secrets-hygiene: allow", via) == []


@pytest.mark.parametrize("via", VIA)
@pytest.mark.parametrize("line", NOT_TRACED)
def test_not_tracing_is_not_flagged(tmp_path: Path, line: str, via: str) -> None:
    assert _sr146_in(tmp_path, line, via) == []


@pytest.mark.parametrize("value", ["xtrace", '"braceexpand:xtrace"'])
def test_workflow_env_shellopts_is_flagged(tmp_path: Path, value: str) -> None:
    # #3400: a job's or a step's env reaches the bash that runs each `run:` script.
    env = f"jobs:\n  a:\n    env:\n      SHELLOPTS: {value}\n"
    _write(tmp_path, WF, env + "    steps:\n      - run: make\n")
    assert h.check_workflows(tmp_path) == ["w.yml:4: 'set -x' tracing (SR-146)"]


@pytest.mark.parametrize(
    "line",
    [
        "set " + "-e " * 3000,
        "bash " + "-o a " * 2500,
        "set -o" + " " * 10000 + "y",
        "set -" + "x" * 20000 + "2",
        "set -" + "o" * 20000 + "2",
        "/a" * 5000 + "/sh -e",
        "(" * 10000,
        # #3294: an -o argument that is itself a command word, so each one starts a rule.
        "sh " + "-o sh " * 16000,
        "set " + "-o set " * 14000,
        "bash " + "-o bash " * 12000,
        # A shell's path: all slashes, and a `$` before each `/` (a rule start after each `$`).
        "/" * 96000 + "sh -e",
        "/a$" * 32000,
        # #3400: shellcheck words, each starting a dialect match that reads the words after it.
        "shellcheck " * 20000,
        "shellcheck " + "-a " * 70000,
        "x=shellcheck -a " * 14000,
        "/a/shellcheck " * 16000,
        # #3400: a name's separators; a `--` name starts at its letter (a `-` run before it read
        # the rest of the line at each `--`: about 10 s at 48k); shopt's flags, read by two
        # lookaheads; setopt words; SHELLOPTS items, which end at `=` (else about 1.3 s at 80k).
        "set -o x" + "_" * 90000 + "y",
        "-" * 96000,
        "shopt -s " * 15000,
        "shopt -" + "s" * 90000,
        "shopt -so " + "a " * 45000,
        "setopt " + "-o a " * 19000,
        "unsetopt " * 11000,
        "SHELLOPTS=" * 9600,
        "SHELLOPTS=" + "a:" * 45000,
        # #3400: trap words, all taken by one match (a DEBUG required after them re-read the
        # rest of the line at each trap: about 15 s at 98k); quotes and escapes in its action.
        "trap x " * 14000,
        "trap '" * 20000,
        'trap "' + "\\\\" * 45000,
        # #3400: quotes and escapes, taken off in one pass (each quote read to its end once, an
        # unclosed one to the end of the line); the words they leave; a long option's argument;
        # redirections; $SHELL, braced, with a default that ends at `$`.
        "'" * 96000,
        "\"'" * 48000,
        '\\"' * 48000,
        '"\\' * 48000,
        "$'" * 48000,
        "-''" * 32000,
        "'bash' " * 13000,
        "bash " + "--rcfile " * 10000,
        "bash " + "2>&1 " * 19000,
        "bash" + " >" * 48000,
        "$SHELL " * 13000,
        "${SHELL:-" * 10000,
        "${SHELL:-a" * 9000,
        # #3400: path segments a rule may start in (after a `+`, a `}` or a `@` before a `~`),
        # each read once as one path naming no shell; letters from expansions, an unclosed one.
        "/a+" * 32000,
        "${X}" * 24000,
        "@~" * 48000,
        "set -" + "${A}" * 20000,
        "set -e${A:+" + "a" * 90000,
        "set " + "${A:+-e} " * 12000,
    ],
    ids=["set-groups", "bash-o-words", "o-spaces", "x-run", "o-run", "deep-path", "brackets"]
    + ["sh-o-sh", "set-o-set", "bash-o-bash", "slashes", "dollar-path"]
    + ["shellcheck-words", "shellcheck-options", "shellcheck-mid-word", "shellcheck-paths"]
    + ["name-separators", "dashes", "shopt-flags", "shopt-long-flag", "shopt-names"]
    + ["setopt-o-words", "unsetopt-words", "shellopts-assignments", "shellopts-items"]
    + ["trap-words", "trap-quotes", "trap-escapes"]
    + ["single-quotes", "mixed-quotes", "escaped-quotes", "quote-escapes", "ansi-c-quotes"]
    + ["empty-quotes", "quoted-shells", "rcfile-words", "redirect-words", "redirect-ops"]
    + ["shell-vars", "shell-defaults", "shell-default-runs"]
    + ["plus-paths", "brace-pieces", "tilde-starts", "letter-expansions", "unclosed-value"]
    + ["value-words"],
)
def test_tracing_rules_stay_linear_on_a_long_line(line: str) -> None:
    # CPU time, not wall-clock time (C-13.7): a busy runner delays this test but adds no CPU time
    # to it. Each line takes milliseconds; a quadratic rule took seconds (about 20 s at 96k).
    start = time.process_time()
    h._sr146_hits(line)
    h._SHEBANG_X.match(h._unquoted(f"#!/bin/sh {line}"))
    assert time.process_time() - start < 1.0


def test_inventory_flags_prod_credentials_and_unprotected() -> None:
    errs = h.check_inventory(["BYBIT_LIVE_API_KEY", "PROD_KEK", "CODECOV_TOKEN", "AWS_SECRET_ACCESS_KEY"], {"RELEASE_SIGN": False})
    assert len(errs) == 4 + 0 or len(errs) == 4
    assert any("IR-02" in e for e in errs)
    assert h.check_inventory(["CODECOV_TOKEN"], {"X": True}) == []


def test_logs_scan_catches_leak_and_references_ir02(tmp_path: Path) -> None:
    (tmp_path / "job.log").write_text(f"X-BAPI-API-KEY: {REAL}\n", encoding="utf-8")
    (tmp_path / "ok.log").write_text("all good\n", encoding="utf-8")
    errs = h.check_logs([tmp_path])
    assert len(errs) == 1 and "job.log" in errs[0] and "IR-02" in errs[0]


def test_main_exit_codes(tmp_path: Path) -> None:
    _write(tmp_path, "tests/fixtures/a.json", f'{{"api_key": "{REAL}"}}')
    assert h.main(["fixtures", "--root", str(tmp_path)]) == 1
    assert h.main(["workflows", "--root", str(tmp_path)]) == 0


def test_leaky_job_output_fails_log_scan_and_ci_wires_it(tmp_path: Path) -> None:
    leaky = tmp_path / "job.log"
    leaky.write_text("X-BAPI-API-KEY: " + REAL + chr(10), encoding="utf-8")
    assert h.check_logs([leaky])
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/_job-security.yml").read_text(
        encoding="utf-8"
    )
    assert "check_secrets_hygiene.py logs" in wf
    assert "check_secrets_hygiene.py all" in wf


# E27-Q01 (#833): the bare key-shape rule over the accounts fault-injection pack. Tokens are
# built at run time, so no key-shaped literal sits in this file.
PACK = "packages/fixtures/accounts"


def _alnum(n: int) -> str:
    return "".join("aB3"[i % 3] for i in range(n))


def _capitals_then_small(capitals: int, n: int) -> str:
    return "Q" * capitals + "q" * (n - capitals)


@pytest.mark.parametrize(
    ("token", "shape"),
    [
        (_alnum(18), "api-key"),
        (_alnum(19), "api-key"),
        (_alnum(20), "api-key"),
        (_alnum(36), "api-secret"),
        ("".join("aB"[i % 2] for i in range(20)), "api-key"),
        (_capitals_then_small(h._MIXED_CASE_MIN, 18), "api-key"),
    ],
    ids=["18", "19", "20", "36", "letters_alternating", "letters_at_threshold"],
)
def test_bare_key_shape_in_the_accounts_pack_fails_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], token: str, shape: str
) -> None:
    _write(tmp_path, f"{PACK}/x/manifest.json", f'{{"description": "pasted {token} here"}}')
    errors = h.check_fixtures(tmp_path)
    assert errors == [
        (
            f"{PACK}/x/manifest.json: bare {shape}-shaped token ({len(token)} chars at offset 24);"
            " the token is never printed (E27-Q01)"
        )
    ]
    assert h.main(["fixtures", "--root", str(tmp_path)]) == 1
    assert token not in capsys.readouterr().err


@pytest.mark.parametrize(
    "text",
    [
        "00000000-0000-4000-8000-000000000001",  # a UUID
        "ab" * 32,  # a sha256 digest
        "1792141200000",  # epoch milliseconds
        "1700000000123456789",  # epoch nanoseconds, digits only
        "fixture-withdraw_enabled-0003",  # a fixture key id
        "fixture-withdraw_enabled-secret-not-real",  # a fixture secret
        h.DUMMY_PREFIX + _alnum(18),  # a dummy-prefixed id
        _alnum(10) + "-" + _alnum(9),  # a hyphen-joined token
        "unifiedMarginStatus",  # camelCase field names
        "availableToWithdraw",
        "SubMemberTransferLis",  # PascalCase, four capitals
        _capitals_then_small(h._MIXED_CASE_MIN - 1, 18),
        _capitals_then_small(18 - h._MIXED_CASE_MIN + 1, 18),
        _alnum(17),
        _alnum(21),
        _alnum(35),
        _alnum(37),
    ],
)
def test_scan_key_shapes_passes_benign_tokens(text: str) -> None:
    assert h.scan_key_shapes(f'"{text}"') == []


def test_key_shape_rule_scans_every_pack_file_even_test_named_ones(tmp_path: Path) -> None:
    _write(tmp_path, f"{PACK}/test/test_x.txt", _alnum(20))
    _write(tmp_path, f"{PACK}/notes.bin", _alnum(36))
    assert len(h.check_fixtures(tmp_path)) == 2


def test_key_shape_rule_is_scoped_to_the_accounts_pack(tmp_path: Path) -> None:
    _write(tmp_path, "packages/fixtures/bybit/x.json", f'{{"note": "{_alnum(20)}"}}')
    assert h.check_fixtures(tmp_path) == []


def test_the_rule_matches_the_pack_checks_in_the_js_lane() -> None:
    """The JS twin (accounts-pack.mjs) must carry the same threshold."""
    js = (
        Path(__file__).resolve().parents[2] / "packages/fixtures/scripts/accounts-pack.mjs"
    ).read_text(encoding="utf-8")
    assert f"export const MIXED_CASE_MIN = {h._MIXED_CASE_MIN};" in js
    assert "const TOKEN = /[A-Za-z0-9_-]+/g;" in js
