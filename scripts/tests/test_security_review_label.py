"""#2892: tools/ci/security_review_label.py labels a PR touching a C-10.2 path `security-review`.

The matcher follows CONSTITUTION C-10.2 verbatim (the clause is parsed here, so an amendment fails
these tests until the rule follows it), in both spellings of the backend prefixes. The flow runs on
a fake API: it adds a missing label, never removes one, and fails closed when it cannot add the
label or cannot read every changed file. The job runs main's copy of the script, never the PR's.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
s = importlib.import_module("tools.ci.security_review_label")

LABEL_PATH = "/issues/7/labels"
SECURITY = [
    *(f"services/api/{m}/x.py" for m in s.MODULES),  # C-10.2's spelling
    *(f"services/api/candleviewer/{m}/sub/x.py" for m in s.MODULES),  # the real package (#2708)
    "infra/compose/docker-compose.yml",
    "infra/images/Dockerfile.api",
    *(p + "Screen.tsx" if p.endswith("/") else p for p in s.WEB_AUTH_PATHS),
    "apps/web/src/features/sessions/SessionsScreen.tsx",  # a future slice, before the list names it
    "apps/web/src/lib/session/store.ts",
    "package.json",
    "apps/web/package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    ".npmrc",
    "services/api/pyproject.toml",
    "services/api/uv.lock",
    "scripts/requirements-ci.txt",
    "tools/ci/requirements-security-gate.txt",
    "packages/chart-engine/bench/matrix/tauri/src-tauri/Cargo.toml",
    ".github/workflows/pr.yml",
    ".github/workflows/_job-js.yml",
    "docs/a/b/c/apikey-rotation.md",  # the four globs on a file name in a deep path
    "services/api/candleviewer/ws/client_secret.py",
    "apps/web/src/lib/ws/AccessToken.ts",  # any case: camelCase TS names
    "tools/x/y/ENCRYPT_notes.txt",
    "apps/web/src/keymap/keymap.ts",  # C-10.2 is verbatim: the keymap and design tokens match
    "packages/ui/tokens/primitives.tokens.json",
]
NOT_SECURITY = [
    "services/api/candleviewer/ws/app.py",
    "services/api/candleviewer/auditing/x.py",  # `audit/` is a directory, not a prefix of a name
    "services/api/tests/auth/test_login.py",  # C-10.2 names the modules, not their tests
    "services/api/candleviewer/rules/engine.py",  # #2892 asked for these three; C-10.2 lacks them
    "services/api/candleviewer/accounts/service.py",
    "services/api/candleviewer/migrations/versions/0001_init.py",
    "apps/web/src/lib/ws/core/engine.ts",
    "apps/web/src/features/appearance/AppearanceScreen.tsx",
    "apps/web/e2e/auth/login.spec.ts",
    "my-infra/x.yml",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    "docs/package.json.md",
    "docs/requirements.md",
    "README.md",
]


@pytest.mark.parametrize("path", SECURITY)
def test_a_c10_2_path_matches_a_rule_and_the_combined_regex(path: str) -> None:
    assert s.rule_for(path) is not None
    assert s.SECURITY_PATH_RE.match(path)


@pytest.mark.parametrize("path", NOT_SECURITY)
def test_any_other_path_matches_nothing(path: str) -> None:
    assert (s.rule_for(path), s.SECURITY_PATH_RE.match(path)) == (None, None)


def _c10_2() -> str:
    text = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    start = text.index("**C-10.2 Security review trigger.**")
    return " ".join(text[start : text.index("\n\n", start)].split())


def test_the_rules_follow_the_c10_2_clause_verbatim() -> None:
    clause = _c10_2()
    spans = re.findall(r"`([^`]+)`", clause)
    assert {m[1] for x in spans if (m := re.fullmatch(r"services/api/(\w+)/", x))} == set(s.MODULES)
    assert {m[1] for x in spans if (m := re.fullmatch(r"\*(\w+)\*", x))} == set(s.WORDS)
    assert f"The `{s.LABEL}` label is applied **automatically**" in clause
    for phrase in ("anything under `infra/`", "authentication/session code in `apps/web`"):
        assert phrase in clause
    assert "dependency manifests, CI workflow files" in clause


def test_the_named_paths_exist_so_a_rename_cannot_drop_one_silently() -> None:
    assert all((ROOT / "services/api/candleviewer" / m).is_dir() for m in s.MODULES)
    for path in s.WEB_AUTH_PATHS:
        assert (ROOT / path).is_dir() if path.endswith("/") else (ROOT / path).is_file(), path


def test_the_combined_regex_is_portable_ere_for_the_merge_guard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pattern = s.SECURITY_PATH_RE.pattern
    assert not re.search(r"\(\?|\\[ZAdwsb]", pattern)  # no Python-only syntax
    assert s.main(["--print-regex"]) == 0
    assert capsys.readouterr().out == pattern + "\n"
    grep = shutil.which("grep")
    if not grep:
        pytest.skip("grep -E proves the same regex matches the same paths outside Python")
    paths = "\n".join([*SECURITY, *NOT_SECURITY, ""])
    run = subprocess.run([grep, "-E", pattern], input=paths, capture_output=True, text=True)
    assert run.stdout.splitlines() == SECURITY


class FakeApi:
    """The PR #7 endpoints the script reads and writes; records every call."""

    def __init__(self, files: list[Any], labels: tuple[str, ...] = (), **kw: Any) -> None:
        self.files = [{"filename": f} if isinstance(f, str) else f for f in files]
        self.labels = list(labels)
        self.changed: int = kw.get("changed", len(self.files))
        self.fail_get: Exception | None = kw.get("fail_get")
        self.fail_post: Exception | None = kw.get("fail_post")
        self.answer: Any = kw.get("answer")
        self.calls: list[tuple[str, ...]] = []

    def get(self, path: str) -> Any:
        self.calls.append(("GET", path))
        if path == "/pulls/7":
            return {"changed_files": self.changed, "labels": [{"name": n} for n in self.labels]}
        if self.fail_get:
            raise self.fail_get
        match = re.fullmatch(r"/pulls/7/files\?per_page=100&page=(\d+)", path)
        assert match, path
        page = int(match[1])
        return self.files[(page - 1) * 100 : page * 100]

    def post(self, path: str, body: dict[str, object]) -> Any:
        self.calls.append(("POST", path, json.dumps(body)))
        if self.fail_post:
            raise self.fail_post
        self.labels.append(s.LABEL)
        return [{"name": n} for n in self.labels] if self.answer is None else self.answer

    def posts(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == "POST"]


@pytest.fixture(autouse=True)
def _pull_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_NAME", "pull_request")
    monkeypatch.setenv("PR_NUMBER", "7")


ADD = ("POST", LABEL_PATH, json.dumps({"labels": ["security-review"]}))
AUTH = "services/api/candleviewer/auth/sessions.py"


def test_no_security_path_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi(["docs/x.md", "apps/web/src/App.tsx"])
    assert (s.main([], api), api.posts()) == (0, [])
    assert "no C-10.2 security path" in capsys.readouterr().out


def test_a_present_label_is_kept_and_the_matches_are_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeApi([AUTH, "docs/x.md"], labels=("security-review",))
    assert (s.main([], api), api.posts()) == (0, [])
    assert f"'{AUTH}'\n" in capsys.readouterr().out


def test_a_file_name_cannot_inject_a_workflow_command(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi([AUTH + "\n::error::forged"], labels=("security-review",))
    assert s.main([], api) == 0
    assert [line for line in capsys.readouterr().out.splitlines() if line.startswith("::")] == []


def test_a_missing_label_is_added_once() -> None:
    api = FakeApi(["docs/x.md", AUTH, ".github/workflows/pr.yml"], labels=("type/chore",))
    assert (s.main([], api), api.posts()) == (0, [ADD])


UNSURE: dict[str, dict[str, Any]] = {
    "unreachable": {"fail_post": urllib.error.URLError("refused")},
    "forbidden": {"fail_post": OSError("403 Resource not accessible by integration")},
    "not-in-answer": {"answer": [{"name": "type/chore"}]},
    "list-failed": {"fail_get": OSError("502 Bad Gateway")},
    "over-3000": {"changed": 3001},  # over the API's 3000-file cap
    "short-list": {"changed": 2},  # a listing shorter than the PR's changed_files
}


@pytest.mark.parametrize("case", sorted(UNSURE))
def test_it_fails_closed_when_the_label_or_the_file_list_is_unsure(
    case: str, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeApi([AUTH], **UNSURE[case])
    assert s.main([], api) == 1
    assert "CI-GATE-004" in capsys.readouterr().err


def test_over_3000_files_reads_no_page_and_passes_only_if_already_labelled() -> None:
    api = FakeApi([], changed=3001, labels=("security-review",))
    assert (s.main([], api), api.calls) == (0, [("GET", "/pulls/7")])


@pytest.mark.parametrize(("count", "pages"), [(0, 1), (250, 3), (3000, 30)])
def test_every_page_is_read(count: int, pages: int) -> None:
    files = ["docs/x.md"] * count
    api = FakeApi([*files[:-1], AUTH] if count else [])
    assert s.main([], api) == 0
    assert len(api.calls) - 1 - len(api.posts()) == pages
    assert api.posts() == ([ADD] if count else [])


@pytest.mark.parametrize("old_is_security", [True, False])
def test_a_rename_counts_its_old_and_its_new_path(old_is_security: bool) -> None:
    paths = [AUTH, "services/api/candleviewer/ws/sessions.py"]
    old, new = paths if old_is_security else paths[::-1]
    api = FakeApi([{"filename": new, "previous_filename": old, "status": "renamed"}])
    assert (s.main([], api), api.posts()) == (0, [ADD])


def test_a_merge_group_has_no_pr_to_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_NAME", "merge_group")
    api = FakeApi([AUTH])
    assert (s.main([], api), api.calls) == (0, [])


@pytest.mark.parametrize(("event", "number"), [("push", "7"), ("", "7"), ("pull_request", "")])
def test_an_unknown_event_or_pr_number_fails_closed(
    event: str, number: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVENT_NAME", event)
    monkeypatch.setenv("PR_NUMBER", number)
    api = FakeApi([AUTH])
    assert (s.main([], api), api.calls) == (1, [])


def test_it_can_only_read_and_add_labels_never_remove_one() -> None:
    assert {name for name in vars(s.GitHubApi) if not name.startswith("_")} == {"get", "post"}
    source = (ROOT / "tools/ci/security_review_label.py").read_text(encoding="utf-8")
    assert re.findall(r"\.post\(([^,]+),", source) == ['f"/issues/{number}/labels"']


def test_the_live_client_sends_the_token_only_as_a_header(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    class Answer:
        def __enter__(self) -> Answer:  # the `with` target is the answer itself
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self, *size: int) -> bytes:
            return b"[]"

    def urlopen(req: Any, timeout: float) -> Answer:
        sent.append(req)
        return Answer()

    monkeypatch.setattr(s.urllib.request, "urlopen", urlopen)
    api = s.GitHubApi("o/r", "t0k")
    assert api.get("/pulls/7/files?page=1") == [] and api.post(LABEL_PATH, {"labels": ["x"]}) == []
    get, post = sent
    assert get.full_url == "https://api.github.com/repos/o/r/pulls/7/files?page=1"
    assert (get.get_method(), post.get_method()) == ("GET", "POST")
    assert json.loads(post.data) == {"labels": ["x"]}
    assert get.get_header("Authorization") == "Bearer t0k" and "t0k" not in get.full_url


# --- The job in pr.yml ----------------------------------------------------------------------------

JOB = yaml.safe_load((ROOT / ".github/workflows/pr.yml").read_text(encoding="utf-8"))["jobs"][
    "security-review-label"
]


def test_the_job_runs_mains_rule_with_only_the_write_it_needs() -> None:
    assert JOB["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert {"if", "needs", "strategy", "services", "container"}.isdisjoint(JOB)  # always runs
    checkout, step = JOB["steps"]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {"ref": "main", "persist-credentials": False}  # never the PR's tree
    assert "python3 -I tools/ci/security_review_label.py" in step["run"]
    assert set(step["env"]) == {"GH_TOKEN", "GITHUB_REPOSITORY", "EVENT_NAME", "PR_NUMBER"}
    text = json.dumps(JOB)
    assert "secrets." not in text and "pull_request.head" not in text


def _bootstrap(bash: str, tmp_path: Path, event: str) -> tuple[int, str]:
    """The job's step in a checkout of a `main` that has no script yet; `gh` is a recorder."""
    (tmp_path / "bin").mkdir(parents=True)
    gh = tmp_path / "bin" / "gh"
    gh.write_text('#!/usr/bin/env bash\necho "$@" > "$(dirname "$0")/gh.args"\n', encoding="utf-8")
    gh.chmod(0o755)
    env = {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "EVENT_NAME": event}
    env |= {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7", "GH_TOKEN": "t"}
    run = subprocess.run([bash, "-c", JOB["steps"][1]["run"]], cwd=tmp_path, env=env, timeout=60)
    args = tmp_path / "bin" / "gh.args"
    return run.returncode, args.read_text(encoding="utf-8") if args.exists() else ""


def test_until_main_has_the_script_the_job_labels_every_pr(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash runs the job's step")
    labels = "api --method POST repos/o/r/issues/7/labels -f labels[]=security-review --silent\n"
    assert _bootstrap(bash, tmp_path / "pr", "pull_request") == (0, labels)
    assert _bootstrap(bash, tmp_path / "group", "merge_group") == (0, "")
