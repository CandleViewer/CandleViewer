"""Unit tests for scripts/apply_branch_protection.py (GOV-005 support)."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Self

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import apply_branch_protection as abp

ROOT = SCRIPTS_DIR.parent


def _valid_desired_state() -> dict:
    """The committed file, plus a merge queue for the ruleset tests (the file declares none)."""
    data = json.loads((ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
    return {**data, "merge_queue": {"merge_method": "SQUASH"}}


def test_load_desired_state_valid_file_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "branch-protection.json"
    path.write_text(json.dumps(_valid_desired_state()), encoding="utf-8")
    data = abp.load_desired_state(str(path))
    assert data["enforce_admins"] is True


def test_load_desired_state_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(abp.DesiredStateError):
        abp.load_desired_state(str(tmp_path / "does-not-exist.json"))


def test_load_desired_state_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(abp.DesiredStateError):
        abp.load_desired_state(str(path))


@pytest.mark.parametrize(
    "mutation,message_fragment",
    [
        (lambda d: d.update(allow_deletions=True), "allow_deletions"),
        (lambda d: d.update(lock_branch=True), "lock_branch"),
        (lambda d: d.update(enforce_admins=False), "enforce_admins"),
        (lambda d: d.update(allow_force_pushes=True), "force_pushes"),
        (lambda d: d.update(required_linear_history=False), "linear_history"),
    ],
)
# Regression: encodes E01-Q01 cases 1.3-1.5 (originating case id) -- desired-state
# mutations that must be rejected (enforce_admins, force pushes, linear history). Cases
# 1.1-1.2 (review count, code-owner reviews) are weaker-than-live refusals now (#3103).
def test_validate_desired_state_rejects_weakened_settings(mutation, message_fragment) -> None:
    data = _valid_desired_state()
    mutation(data)
    with pytest.raises(abp.DesiredStateError, match=message_fragment):
        abp.validate_desired_state(data)


@pytest.mark.parametrize(
    "mutation,message_fragment",
    [
        (lambda d: d.update({"x-pending-contexts": ["lint"]}), "unknown key x-pending-contexts"),
        (lambda d: d["required_status_checks"].update(contexts=["lint"]), "unknown key required_"),
        (lambda d: d["required_status_checks"].update(checks="not-a-list"), "must be list"),
        (lambda d: d["required_status_checks"].update(checks=[{"context": "lint"}]), "pairs"),
        (lambda d: d.pop("lock_branch"), "missing lock_branch"),
    ],
)
def test_validate_desired_state_refuses_unknown_missing_and_mistyped_keys(
    mutation, message_fragment
) -> None:
    data = _valid_desired_state()
    mutation(data)
    with pytest.raises(abp.DesiredStateError, match=message_fragment):
        abp.validate_desired_state(data)


def test_to_api_payload_strips_internal_keys() -> None:
    payload = abp.to_api_payload(_valid_desired_state())
    for key in [*abp.META_KEYS, *abp.CHECK_ONLY_KEYS, "$comment", "$deviations"]:
        assert key not in payload
    assert "required_pull_request_reviews" in payload


def test_to_api_payload_includes_restrictions_null_when_absent() -> None:
    payload = abp.to_api_payload(_valid_desired_state())
    assert "restrictions" in payload
    assert payload["restrictions"] is None


def test_to_api_payload_preserves_explicit_restrictions() -> None:
    data = _valid_desired_state()
    data["restrictions"] = {"users": [], "teams": ["release-managers"]}
    payload = abp.to_api_payload(data)
    assert payload["restrictions"] == {"users": [], "teams": ["release-managers"]}


# Regression: encodes E01-Q01 case 1.9 (originating case id) -- re-apply of an
# identical live/desired state must be a no-op diff.
def test_diff_state_no_changes_is_empty() -> None:
    live = {"enforce_admins": True, "allow_force_pushes": False}
    desired = {"enforce_admins": True, "allow_force_pushes": False}
    diff = abp.diff_state(live, desired)
    assert diff.is_empty()


def test_diff_state_detects_added_removed_and_changed() -> None:
    live = {"enforce_admins": False, "stale_key": 1}
    desired = {"enforce_admins": True, "new_key": 2}
    diff = abp.diff_state(live, desired)
    assert diff.added == {"new_key": 2}
    assert diff.removed == {"stale_key": 1}
    assert diff.changed == {"enforce_admins": (False, True)}
    assert not diff.is_empty()
    assert "enforce_admins" in diff.render()


# --- Live-state normalisation (finding: diff_state never went empty) -----


def _recorded_get_protection_response() -> dict:
    """The live GET .../branches/main/protection response (read 2026-10-18, #3103): booleans
    wrapped as `{"enabled": ...}`, read-only `url` fields, no `restrictions` key when unset."""
    return {
        "url": "https://api.github.com/repos/o/r/branches/main/protection",
        "required_status_checks": {
            "url": "https://api.github.com/repos/o/r/branches/main/protection/required_status_checks",
            "strict": False,
            "contexts": ["ci-required"],
            "contexts_url": "https://api.github.com/repos/o/r/branches/main/protection/required_status_checks/contexts",
            "checks": [{"context": "ci-required", "app_id": 15368}],
        },
        "required_pull_request_reviews": {
            "url": "https://api.github.com/repos/o/r/branches/main/protection/required_pull_request_reviews",
            "required_approving_review_count": 0,
            "require_code_owner_reviews": False,
            "dismiss_stale_reviews": False,
            "require_last_push_approval": False,
        },
        "enforce_admins": {
            "url": "https://api.github.com/repos/o/r/branches/main/protection/enforce_admins",
            "enabled": True,
        },
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": False},
        "block_creations": {"enabled": False},
        "lock_branch": {"enabled": False},
        "allow_fork_syncing": {"enabled": False},
        "required_signatures": {"url": "https://api.github.com/x", "enabled": False},
    }


def test_normalise_live_state_unwraps_bool_enabled_shape() -> None:
    normalised = abp._normalise_live_state(_recorded_get_protection_response())
    assert normalised["enforce_admins"] is True
    assert normalised["allow_force_pushes"] is False
    assert normalised["required_linear_history"] is True
    assert normalised["required_signatures"] is False
    assert normalised["restrictions"] is None


def test_normalise_live_state_strips_nested_readonly_fields() -> None:
    normalised = abp._normalise_live_state(_recorded_get_protection_response())
    assert "url" not in normalised["required_status_checks"]
    assert "contexts_url" not in normalised["required_status_checks"]
    assert "contexts" not in normalised["required_status_checks"]
    assert normalised["required_status_checks"]["checks"] == [
        {"context": "ci-required", "app_id": 15368}
    ]
    assert "url" not in normalised["required_pull_request_reviews"]


def test_normalise_then_diff_against_matching_desired_is_a_no_op() -> None:
    """AC4 and #3103: the committed file describes the live protection exactly, so re-applying
    it is a genuine no-op, not just a no-op between two hand-built flat fixtures."""
    desired = _valid_desired_state()
    payload = abp.compare_view(desired)
    live = abp._normalise_live_state(_recorded_get_protection_response())
    diff = abp.diff_state(live, payload)
    assert diff.is_empty(), diff.render()


def test_normalise_then_diff_detects_real_drift() -> None:
    desired = _valid_desired_state()
    payload = abp.compare_view(desired)
    raw_live = _recorded_get_protection_response()
    raw_live["required_pull_request_reviews"]["require_code_owner_reviews"] = True
    live = abp._normalise_live_state(raw_live)
    diff = abp.diff_state(live, payload)
    assert not diff.is_empty()
    assert diff.changed["required_pull_request_reviews"][0]["require_code_owner_reviews"] is True


# --- Rules on the branch: a merge queue is compared with the file, never written ----


def test_diff_rules_no_drift_when_matching() -> None:
    desired = _valid_desired_state()
    assert abp.diff_rules({"merge_queue": dict(desired["merge_queue"])}, desired).is_empty()
    assert abp.diff_rules({}, {k: v for k, v in desired.items() if k != "merge_queue"}).is_empty()


def test_diff_rules_detects_a_changed_missing_or_undeclared_rule() -> None:
    desired = _valid_desired_state()
    diff = abp.diff_rules({"merge_queue": {"merge_method": "MERGE"}, "deletion": {}}, desired)
    assert diff.changed["merge_queue"] == ({"merge_method": "MERGE"}, {"merge_method": "SQUASH"})
    assert diff.removed == {"deletion": {}}
    assert abp.diff_rules({}, desired).added == {"merge_queue": {"merge_method": "SQUASH"}}


class _Resp(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *a: object) -> None:
        return None


def _fetch_rules(monkeypatch: pytest.MonkeyPatch, answer: object) -> tuple[dict, list]:
    """fetch_branch_rules against a fake urlopen that returns `answer` as JSON, or raises it."""
    seen: list = []

    def fake(request: urllib.request.Request, timeout: float) -> _Resp:
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return _Resp(json.dumps(answer).encode())

    monkeypatch.setattr(abp.urllib.request, "urlopen", fake)
    return abp.fetch_branch_rules("o/r", "not-a-real-token"), seen


def test_fetch_branch_rules_reads_every_rule_with_one_get(monkeypatch) -> None:
    rules = [
        {"type": "merge_queue", "parameters": {"merge_method": "SQUASH"}},
        {"type": "deletion"},
        {"type": "merge_queue", "parameters": {"merge_method": "MERGE"}},
    ]
    view, seen = _fetch_rules(monkeypatch, rules)
    # A second ruleset's rule of the same type keeps its own key, so neither hides the other.
    assert view == {
        "merge_queue": {"merge_method": "SQUASH"},
        "deletion": {},
        "merge_queue #2": {"merge_method": "MERGE"},
    }
    url = "https://api.github.com/repos/o/r/rules/branches/main?per_page=100"
    assert [(r.get_method(), r.full_url) for r in seen] == [("GET", url)]
    assert _fetch_rules(monkeypatch, [])[0] == {}


@pytest.mark.parametrize(
    "answer,message",
    [
        ({"type": "merge_queue"}, "not a list of fewer than 100 rules"),
        ([{"type": "deletion"}] * 100, "not a list of fewer than 100 rules"),
        (urllib.error.HTTPError("u", 403, "Forbidden", None, None), "failed: 403 Forbidden"),
        (urllib.error.URLError("no route"), "failed: no route"),
    ],
)
def test_fetch_branch_rules_fails_closed(monkeypatch, answer, message) -> None:
    with pytest.raises(abp.ApplyError, match=message):
        _fetch_rules(monkeypatch, answer)


# --- Refusals (#3103): never write a weaker or a lockout configuration ------


def _stronger_live() -> dict:
    """Live protection stronger than the file: what E01-Q01 cases 1.1-1.2 guard."""
    live = abp.compare_view(_valid_desired_state())
    live["required_status_checks"] = {"strict": True, "checks": [{"context": "lint", "app_id": 1}]}
    live["required_pull_request_reviews"].update(
        required_approving_review_count=2, require_code_owner_reviews=True
    )
    return live


def test_weakening_changes_names_each_weaker_setting() -> None:
    changes = abp.weakening_changes(_stronger_live(), abp.compare_view(_valid_desired_state()))
    assert len(changes) == 4, changes
    for fragment in ("strict", "drops", "review_count: 2 -> 0", "code_owner_reviews"):
        assert any(fragment in change for change in changes), fragment


def _no_api_call() -> dict:
    raise AssertionError("fetch_live_state was called")


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: dict,
    *flags: str,
    live: Callable[[], dict] = _stronger_live,
    rules: Callable[[], dict] = dict,
) -> tuple:
    writes: list = []
    monkeypatch.setenv("CV_TEST_TOKEN", "not-a-real-token")
    monkeypatch.setattr(abp, "fetch_live_state", lambda *a: live())
    monkeypatch.setattr(abp, "fetch_branch_rules", lambda *a: rules())
    monkeypatch.setattr(abp, "apply_state", lambda *a: writes.append(a))
    path = tmp_path / "desired.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    argv = ["--desired-state", str(path), "--repo", "o/r", "--token-env", "CV_TEST_TOKEN"]
    argv += ["--workflows-glob", str(ROOT / ".github/workflows/*.yml"), *flags]
    return abp.main(argv), writes


def test_main_refuses_weakening_and_writes_only_when_told(tmp_path, monkeypatch, capsys) -> None:
    data = {k: v for k, v in _valid_desired_state().items() if k != "merge_queue"}
    assert _run(tmp_path, monkeypatch, data) == (1, [])
    assert "refusing: weaker than live" in capsys.readouterr().err
    assert _run(tmp_path, monkeypatch, data, "--allow-weaken") == (0, [])  # a dry run by default
    code, writes = _run(tmp_path, monkeypatch, data, "--allow-weaken", "--apply")
    assert code == 0 and writes[0][2] == abp.to_api_payload(data)
    with pytest.raises(SystemExit):  # --dry-run never writes, so it cannot be combined with --apply
        _run(tmp_path, monkeypatch, data, "--dry-run", "--apply")


# Security review round 4 of #3103: a full PUT drops a nested live setting the file leaves out.
@pytest.mark.parametrize("key", ["required_pull_request_reviews", "required_status_checks"])
def test_main_refuses_to_drop_a_nested_live_setting(tmp_path, monkeypatch, capsys, key) -> None:
    data = {k: v for k, v in _valid_desired_state().items() if k != "merge_queue"}
    live = json.loads(json.dumps(abp.compare_view(data)))
    live[key]["dismissal_restrictions"] = {"users": ["someone"], "teams": []}
    assert _run(tmp_path, monkeypatch, data, "--apply", live=lambda: live) == (1, [])
    assert f"live has {key}.dismissal_restrictions" in capsys.readouterr().err


# Security review round 5 of #3103: a merge queue is a ruleset, which this script never writes (it
# cannot prove a queue's timeout covers ci-required's run time), so it refuses while the rules on
# main differ from the file, and so never applies protection against a queue it does not know.
@pytest.mark.parametrize(
    "declared,live_rules,code",
    [
        (None, {"merge_queue": {"merge_method": "SQUASH"}}, 1),  # a queue the file does not declare
        ({"merge_method": "SQUASH"}, {}, 1),  # a queue only the file declares: never written
        ({"merge_method": "SQUASH"}, {"merge_queue": {"merge_method": "MERGE"}}, 1),
        (None, {"deletion": {}}, 1),  # any other rule on main
        ({"merge_method": "SQUASH"}, {"merge_queue": {"merge_method": "SQUASH"}}, 0),
    ],
)
def test_main_refuses_while_the_rules_on_main_differ_from_the_file(
    tmp_path, monkeypatch, capsys, declared, live_rules, code
) -> None:
    data = {k: v for k, v in _valid_desired_state().items() if k != "merge_queue"}
    data.update({"merge_queue": declared} if declared else {})
    live = json.loads(json.dumps(abp.compare_view(data)))
    live["required_linear_history"] = False  # a protection change the file would write
    stubs = {"live": lambda: live, "rules": lambda: live_rules}
    result = _run(tmp_path, monkeypatch, data, "--apply", **stubs)
    assert result[0] == code and len(result[1]) == 1 - code  # the protection PUT only when clean
    err = capsys.readouterr().err
    assert ("writes no ruleset" in err) is (code == 1), err


def _reviews(**settings: object) -> Callable[[dict], None]:
    return lambda d: d["required_pull_request_reviews"].update(settings)


@pytest.mark.parametrize(
    "mutation,message_fragment",
    [
        # A reusable workflow's job reports as `<caller> / <job>`: a bare `lint` never arrives.
        (
            lambda d: d["required_status_checks"].update(checks=[{"context": "lint", "app_id": 1}]),
            "'lint'",
        ),
        # With the queue on, a required check must also report on merge groups. pr.yml's do since
        # #3536 (#3433), but governance.yml listens to pull_request only.
        (
            lambda d: d["required_status_checks"]["checks"].append(
                {"context": "governance", "app_id": 15368}
            ),
            "no merge_group workflow reports required check 'governance'",
        ),
        # Security review round 3 of #3103: every agent uses the owner's account, and GitHub never
        # counts an author's own approval, so a required approval would hold every pull request.
        (_reviews(required_approving_review_count=2), "required_approving_review_count is 2"),
        (_reviews(require_code_owner_reviews=True), "require_code_owner_reviews is true"),
        (_reviews(require_last_push_approval=True), "require_last_push_approval is true"),
    ],
)
def test_main_refuses_a_lockout_before_any_api_call(
    tmp_path, monkeypatch, capsys, mutation, message_fragment
) -> None:
    data = _valid_desired_state()
    mutation(data)
    flags = ("--allow-weaken", "--apply")
    assert _run(tmp_path, monkeypatch, data, *flags, live=_no_api_call) == (1, [])
    assert message_fragment in capsys.readouterr().err


# Security review of #3103: a lane that calls a reusable workflow reports `<lane> / <job>` while
# it runs, and its own name only as a skipped placeholder, so requiring `contract` would hold PRs.
@pytest.mark.parametrize(
    "context,refusals", [("contract", 1), ("architecture", 0), ("pr-metadata", 0)]
)
def test_lockout_reasons_refuse_a_name_no_pull_request_check_run_carries(context, refusals) -> None:
    data = {k: v for k, v in _valid_desired_state().items() if k != "merge_queue"}
    data["required_status_checks"]["checks"].append({"context": context, "app_id": 15368})
    reasons = abp.lockout_reasons(data, str(ROOT / ".github/workflows/*.yml"))
    assert len(reasons) == refusals, reasons


# Review round 2 of #3103: GitHub waits for the pinned app, and only Actions reports these checks.
def test_lockout_reasons_refuse_a_check_pinned_to_another_app() -> None:
    data = {k: v for k, v in _valid_desired_state().items() if k != "merge_queue"}
    data["required_status_checks"]["checks"] = [{"context": "ci-required", "app_id": 57789}]
    reasons = abp.lockout_reasons(data, str(ROOT / ".github/workflows/*.yml"))
    assert len(reasons) == 1 and "app 57789" in reasons[0], reasons


def test_main_exits_2_when_a_called_workflow_is_missing(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "pr.yml").write_text(
        "on: [pull_request]\njobs:\n  lane:\n    uses: ./.github/workflows/_gone.yml\n",
        encoding="utf-8",
    )
    flags = ("--workflows-glob", str(tmp_path / "*.yml"))
    assert _run(tmp_path, monkeypatch, _valid_desired_state(), *flags, live=_no_api_call) == (2, [])
    assert "_gone.yml" in capsys.readouterr().err
