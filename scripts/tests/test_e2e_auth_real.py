"""#2490 (E09-Q02, #293): the real-backend auth lane's workflow keeps its header's properties.

`e2e-auth-real.yml` runs the Playwright real lane against a throwaway stack every night and on
demand. Every credential is made per run, masked and never echoed. After a failure the test results
are uploaded for 14 days, public to the repository's readers, and only once a scan has found none of
the run's passwords, keys and TOTP seeds in them. The scan (`check_artefact_secrets.py`) skips a
variable that is unset or empty, so a credential made here and left out of its `--env` list, or
spelt differently there, passes silently: only these tests would notice. They pin the triggers and
permissions, the generated names against the scan's, the scan directly before the upload and
gating it, the upload sending what the scan read, the teardown, the bounded waits, and no
repository secret, persisted credential or unpinned action; #2086 adds that no secret is made or
traced outside the pinned lines and that the clocked API runs on the job's own throwaway
database. Names are compared, never values.
(test_nightly_issue.py owns the report job and lists this workflow as a caller; test_zap_admin.py
pins the same properties for dast-admin-nightly.yml.)
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "e2e-auth-real.yml"
JOB = "e2e-auth-real"
CRON = "51 3 * * *"
#: Every value the credentials step makes into $GITHUB_ENV, masked: the scan must search each one.
GENERATED = frozenset(
    {
        "POSTGRES_PASSWORD",
        "CV_AUTH_PEPPER",
        "CV_AUTH_TOTP_KEY_HEX",
        "CV_AUTH_RECOVERY_HMAC_KEY_HEX",
        "CV_AUTH_CSRF_KEY_HEX",
        "CV_E2E_REAL_PASSWORD",
    }
)


def _workflow() -> dict[Any, Any]:
    """The workflow's YAML; its keys are strings except `on`, which YAML 1.1 reads as True."""
    doc: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc


def _steps() -> dict[str, dict[str, Any]]:
    """The job's steps in order, by name (an action step without one: by its `uses`)."""
    steps: list[dict[str, Any]] = _workflow()["jobs"][JOB]["steps"]
    by_label = {str(step.get("name", step.get("uses", ""))): step for step in steps}
    assert len(by_label) == len(steps)  # a repeated or missing label would hide a step
    return by_label


def _step(prefix: str) -> dict[str, Any]:
    """The one step whose name starts with `prefix`."""
    found = [step for label, step in _steps().items() if label.startswith(prefix)]
    assert len(found) == 1, f"{len(found)} steps are named {prefix!r}..., not one"
    return found[0]


def _label(prefix: str) -> str:
    """The full label of the one step whose name starts with `prefix`."""
    found = [label for label in _steps() if label.startswith(prefix)]
    assert len(found) == 1, f"{len(found)} steps are named {prefix!r}..., not one"
    return found[0]


def _condition(step: dict[str, Any]) -> str:
    """A step's `if` without the `${{ }}` some are written in, its spaces normalised."""
    text = str(step["if"]).strip()
    inner = re.fullmatch(r"\$\{\{(.*)\}\}", text, re.DOTALL)
    return " ".join((inner.group(1) if inner else text).split())


def _globs(path: str, pattern: str) -> bool:
    """Whether the shell glob `pattern` matches `path`: `*` stays inside one path segment."""
    (where, name), (pattern_where, pattern_name) = path.rsplit("/", 1), pattern.rsplit("/", 1)
    return where == pattern_where and fnmatch.fnmatchcase(name, pattern_name)


def test_the_workflow_runs_nightly_and_by_hand_never_on_a_pull_request() -> None:
    workflow = _workflow()
    triggers = workflow[True]  # YAML 1.1 reads the `on` key as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}  # never a pull_request trigger
    assert triggers["schedule"] == [{"cron": CRON}]
    assert triggers["workflow_dispatch"] in (None, {})  # no input can move the target


def test_the_workflow_and_its_job_can_only_read_the_repository() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    # a block of its own: a later widening of the top one would not reach this job (`report` has
    # its own, `issues: write`, which test_nightly_issue.py pins)
    assert workflow["jobs"][JOB]["permissions"] == {"contents": "read"}


def test_the_scan_searches_every_secret_the_run_makes_the_totp_seeds_and_the_lane_key() -> None:
    made = _step("Make this run's")["run"]
    (listed,) = re.findall(r"for name in ([A-Z0-9_\s\\]+); do secret", made)
    generated = set(listed.replace("\\", " ").split())  # each one is in $GITHUB_ENV, masked
    scrub = _step("No secret of this run")["run"]
    assert generated == GENERATED
    assert set(re.findall(r"--env (\w+)", scrub)) == generated  # none left out, none misspelt
    assert '--secret-file "$RUNNER_TEMP/cv/*.totp"' in scrub  # where seed_fixture_user.py writes
    assert '--secret-file "$RUNNER_TEMP/cv-lane/lane.key"' in scrub  # the audit lane key
    assert "--title e2e-auth-real" in scrub  # its errors name this lane, not zap-admin
    assert not re.search(r"\$\{?(" + "|".join(sorted(generated)) + r")\b", scrub)  # names only


def test_every_secret_is_masked_the_moment_it_exists() -> None:
    # the passwords, pepper and keys are masked before they reach $GITHUB_ENV, the lane key right
    # after its file is written, and each TOTP seed right after its file is
    made = _step("Make this run's")["run"]
    assert 'echo "::add-mask::$v"; echo "$1=$v" >> "$GITHUB_ENV"' in made
    assert 'lane.key")\necho "::add-mask::$(cat "$RUNNER_TEMP/cv-lane/lane.key")"' in made
    assert (
        'echo "::add-mask::$(cat "$RUNNER_TEMP/cv/e2e-$i.totp")"'
        in _step("Migrate, then seed")["run"]
    )


def test_the_seeds_and_the_lane_key_are_written_where_the_scan_looks() -> None:
    scrub = _step("No secret of this run")["run"]
    globs = re.findall(r'--secret-file "([^"]+)"', scrub)
    (seed_path,) = re.findall(r'--totp-secret-out "([^"]+)"', _step("Migrate, then seed")["run"])
    assert any(_globs(seed_path, pattern) for pattern in globs)
    (key_path,) = re.findall(r'> "([^"]*lane\.key)"', _step("Make this run's")["run"])
    assert key_path in globs


def test_the_upload_waits_for_a_passing_scan_that_runs_just_before_it() -> None:
    steps = _steps()
    order = list(steps)
    keep_log, scrub_label = _label("Keep the API's log"), _label("No secret of this run")
    upload_label = _label("Upload the failure artefacts")
    # the log is copied in before the scan reads the directory; the upload is the very next step
    assert order.index(keep_log) < order.index(scrub_label) == order.index(upload_label) - 1
    scrub, upload = steps[scrub_label], steps[upload_label]
    assert scrub["id"] == "scrub" and _condition(scrub) == "failure()"
    assert "check_artefact_secrets.py" in scrub["run"]
    assert scrub["run"].startswith("set -euo pipefail")  # a refusal (exit 1 or 2) fails the step
    assert "||" not in scrub["run"]  # and nothing swallows it
    assert "continue-on-error" not in scrub
    assert str(upload["uses"]).startswith("actions/upload-artifact@")
    assert _condition(upload) == "failure() && steps.scrub.outcome == 'success'"


def test_the_scan_and_the_text_only_check_read_exactly_the_directory_the_upload_sends() -> None:
    steps = _steps()
    scrub = steps[_label("No secret of this run")]["run"]
    sent = steps[_label("Upload the failure artefacts")]["with"]["path"]
    assert scrub.split()[-1] == sent.rstrip("/")  # the scan's last argument
    assert f"find {sent.rstrip('/')} -type f" in scrub  # the text-only check reads it too


def test_teardown_runs_last_always_and_removes_the_database_and_every_directory_it_made() -> None:
    steps = _steps()
    teardown_label = _label("Tear down")
    assert list(steps)[-1] == teardown_label
    teardown = steps[teardown_label]
    assert _condition(teardown) == "always()"
    assert "docker compose down -v" in teardown["run"]
    (removed,) = re.findall(r"rm -rf ([^\n|;&]+)", teardown["run"])
    made = _step("Make this run's")["run"]
    (made_dirs,) = re.findall(r'mkdir -p ((?:"\$RUNNER_TEMP/[\w-]+"\s*)+)', made)
    names = set(re.findall(r'"\$RUNNER_TEMP/([\w-]+)"', made_dirs))
    assert names == {"cv", "cv-lane", "cv-clock"}  # the seeds and users, the lane key, the clock
    assert set(re.findall(r'"\$RUNNER_TEMP/([\w-]+)"', removed)) == names


def test_the_waits_are_bounded_and_a_dead_api_says_how_it_ended() -> None:
    assert "--wait-timeout" in _step("Start Postgres")["run"]
    start = _step("Start the API")["run"]
    assert re.search(r"curl [^\n]*--max-time \d+", start)
    assert 'kill -0 "$api" 2>/dev/null || break' in start  # an API that exited stops the wait
    # one still alive but silent has no exit code: the message must not claim `(exit 0)` for it
    assert 'state="still running, not answering"' in start and 'state="exit ${code}"' in start
    assert "(${state})" in start
    # `head` quits early and `find` then exits 141 under pipefail, before the message prints
    assert not re.search(r"\|\s*head\b", _step("No secret of this run")["run"])


def test_the_workflow_reads_no_repository_secret_and_persists_no_credential() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    expressions = re.findall(r"\$\{\{(.*?)\}\}", text, re.DOTALL)
    assert expressions  # the pattern finds the file's expressions, or the next line is vacuous
    assert [e for e in expressions if re.search(r"\bsecrets\b", e)] == []  # made per run instead
    checkouts = [
        s for s in _steps().values() if str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    assert all(s.get("with", {}).get("persist-credentials") is False for s in checkouts)


def test_the_workflow_pins_every_action_by_commit() -> None:
    jobs = _workflow()["jobs"]
    uses = [job["uses"] for job in jobs.values() if "uses" in job]
    uses += [
        step["uses"] for job in jobs.values() for step in job.get("steps", []) if "uses" in step
    ]
    assert len(uses) >= 5  # the four actions and the reusable report workflow, or the parse failed
    assert all(
        use.startswith("./.github/workflows/")
        or re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", use)
        for use in uses
    )


def test_one_upload_and_no_secret_made_or_traced_beside_the_pinned_ones() -> None:
    """#5103's security delta L3: an upload, a secret or a trace beside the pinned ones would pass
    every test above, and a shell trace prints a value before its mask exists."""
    upload = "actions/upload-artifact@"
    uploads = [s for s in _steps().values() if str(s.get("uses", "")).startswith(upload)]
    assert uploads == [_step("Upload the failure artefacts")]
    text, made = WORKFLOW.read_text(encoding="utf-8"), _step("Make this run's")["run"]
    assert not re.search(r"\bset\s+-\w*x|\bxtrace\b|\bbash\s+-\w*x", text)
    assert text.count('"$GITHUB_ENV"') == 1  # only secret() writes it
    assert len(re.findall(r"\bsecret\b", made)) == 2  # its definition and the loop's call
    assert len(re.findall(r"openssl rand -hex 32", text)) == 2  # secret() and the lane key


def test_the_text_only_check_admits_four_kinds_of_file_and_fails_the_step_on_any_other() -> None:
    scrub = _step("No secret of this run")["run"]
    (names,) = re.findall(r"find \S+ -type f ((?:! -name '[^']+' )+)\|", scrub)
    assert re.findall(r"'\*\.(\w+)'", names) == ["json", "md", "log", "txt"]
    assert re.search(r'if \[ -n "\$other" \]; then\n[^\n]*\n\s*exit 1\n\s*fi\n', scrub)


def test_the_clocked_api_runs_on_the_job_s_own_throwaway_database() -> None:
    """#2086 (carried from #2728's QA, C-2.11): rows written under a moved clock (sessions,
    lockouts, invites) must die with the run, so the clocked API's database is the Postgres this
    job starts on loopback and removes with its volume, never one a demo or live process uses."""
    assert re.search(r"docker compose up [^\n]* postgres\b", _step("Start Postgres")["run"])
    api = _step("Start the API")
    assert api["env"]["CV_ENVIRONMENT"] == "testnet" and api["env"]["CV_TEST_CLOCK"] == "true"
    own = "postgresql+asyncpg://cv:${POSTGRES_PASSWORD}@127.0.0.1:5432/candleviewer"
    assert re.findall(r'CV_PG_DSN="([^"]+)"', api["run"]) == [own]  # the password made per run
    assert re.findall(r'CV_PG_DSN="([^"]+)"', _step("Migrate, then seed")["run"]) == [own]
    assert "docker compose down -v" in _step("Tear down")["run"]
