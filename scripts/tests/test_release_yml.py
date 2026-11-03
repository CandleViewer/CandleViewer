"""#3099: `.github/workflows/release.yml`, the release run (07 §4; the #2341 release contract).

Structure: triggers (push to `main` touching CHANGELOG.md or version.txt, and a dispatch from
`main`), the chain classify -> verify -> e2e + sbom -> tag-draft -> build-sign, least privilege
per job, a dry run that skips every write job, inputs only through env, the e2e gate checked out
at the candidate, concurrency per candidate, and no branch push. Behaviour: the dispatch guards,
the dry-run decision, the stdout grep into $GITHUB_OUTPUT and the zero-artefact failure run as the
runner runs them (`bash -e`), with stand-in commands on PATH (no network, no GitHub).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DOC: dict[Any, Any] = yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))
E2E: dict[Any, Any] = yaml.safe_load((WORKFLOWS / "_job-e2e.yml").read_text(encoding="utf-8"))
JOBS: dict[str, dict[str, Any]] = DOC["jobs"]
CANDIDATE = "${{ needs.classify.outputs.candidate }}"
DRY_RUN_OFF = "needs.classify.outputs.dry_run == 'false'"
SHA = "a" * 40
#: The #2341 ruling's per-job permissions (contract (4)); the sbom job only reads (it attaches
#: nothing: tag-draft attaches its SBOMs), so it holds less than the ruling allowed it.
PERMISSIONS = {
    "classify": {"contents": "read"},
    "verify": {"contents": "read"},
    "e2e": {"contents": "read"},
    "sbom": {"contents": "read"},
    "tag-draft": {"contents": "write", "issues": "write"},
    "build-sign": {"contents": "write", "id-token": "write"},
}
WRITE_JOBS = {"tag-draft", "build-sign"}
SBOM_ACTION = "anchore/sbom-action@66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c"


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = JOBS[job]["steps"]
    return steps


def _step(job: str, name_part: str) -> dict[str, Any]:
    (step,) = [s for s in _steps(job) if name_part in str(s.get("name", ""))]
    return step


def _needs(job: str) -> set[str]:
    needs = JOBS[job].get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _bash(
    tmp_path: Path, run: str, env: dict[str, str], fakes: dict[str, str] | None = None
) -> tuple[int, str, str]:
    """Run a step's script as the runner does: exit code, output and $GITHUB_OUTPUT."""
    if not shutil.which("bash"):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, source in (fakes or {}).items():
        (bin_dir / name).write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    output, temp = tmp_path / "github-output", tmp_path / "runner-temp"
    output.touch()
    temp.mkdir(exist_ok=True)
    base = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(temp),
        "GITHUB_REPOSITORY": "owner/repo",
    }
    proc = subprocess.run(
        ["bash", "-e", "-c", run],
        cwd=tmp_path,
        env=base | env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr, output.read_text(encoding="utf-8")


# --- structure ------------------------------------------------------------------------------------


def test_triggers_are_a_push_to_main_touching_the_prep_files_and_a_dispatch() -> None:
    on = DOC[True]  # YAML 1.1 reads the `on` key as True
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"branches": ["main"], "paths": ["CHANGELOG.md", "version.txt"]}
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"candidate", "dry_run", "RELEASE_ALLOW_1_0_0"}
    assert (inputs["candidate"]["type"], inputs["candidate"]["required"]) == ("string", True)
    assert (inputs["dry_run"]["options"], inputs["dry_run"]["default"]) == (
        ["true", "false"],
        "true",
    )
    allow = inputs["RELEASE_ALLOW_1_0_0"]
    assert (allow["options"], allow["default"]) == (["false", "true"], "false")


def test_permissions_are_least_privilege_per_job() -> None:
    assert DOC["permissions"] == {"contents": "read"}
    assert {name: job.get("permissions") for name, job in JOBS.items()} == PERMISSIONS


def test_the_chain_gates_every_write_on_verify_e2e_and_the_sboms() -> None:
    assert _needs("verify") == {"classify"}
    assert _needs("e2e") >= {"verify"} and _needs("sbom") >= {"verify"}
    assert _needs("tag-draft") >= {"verify", "e2e", "sbom"}
    assert _needs("build-sign") >= {"tag-draft"}
    # The tag job also needs verify's own verdict, not only its success (a dry run passes verify).
    assert "needs.verify.outputs.verified == 'true'" in JOBS["tag-draft"]["if"]


def test_a_dry_run_skips_every_write_job() -> None:
    for name, job in JOBS.items():
        writes = any(scope == "write" for scope in job.get("permissions", {}).values())
        assert writes == (name in WRITE_JOBS), name
        if writes:
            assert DRY_RUN_OFF in job["if"], name
    # The read-only jobs run in a dry run: verify, the e2e gate and the SBOMs.
    for name in ("verify", "e2e", "sbom"):
        assert "dry_run" not in JOBS[name].get("if", ""), name


def test_inputs_and_computed_values_reach_scripts_only_through_env() -> None:
    for name, job in JOBS.items():
        for step in job.get("steps", []):
            assert "${{" not in str(step.get("run", "")), (name, step.get("name"))
        assert "env" not in job, name  # the token lives in the steps that need it
    assert "GH_TOKEN" not in str(DOC.get("env", ""))


def test_the_e2e_gate_runs_the_shared_lane_at_the_candidate() -> None:
    job = JOBS["e2e"]
    assert job["uses"] == "./.github/workflows/_job-e2e.yml"
    assert job["with"] == {"ref": CANDIDATE, "electron": True}


def test_every_e2e_lane_checkout_honours_the_ref_input() -> None:
    ref = E2E[True]["workflow_call"]["inputs"]["ref"]
    assert (ref["type"], ref["default"]) == ("string", "")
    checkouts = [
        (name, step)
        for name, job in E2E["jobs"].items()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert {name for name, _ in checkouts} == {"e2e-web", "e2e-staging", "a11y-axe", "e2e-electron"}
    for name, step in checkouts:
        assert step["with"]["ref"] == "${{ inputs.ref }}", name
    assert "if" not in E2E["jobs"]["e2e-electron"]  # BQ-14: the arm runs on every call


def test_concurrency_is_per_candidate_and_never_cancels_a_running_release() -> None:
    assert "concurrency" not in DOC
    for name in ("tag-draft", "build-sign"):
        group = {"group": f"release-{CANDIDATE}", "cancel-in-progress": False}
        assert JOBS[name]["concurrency"] == group, name
    # Only the two write jobs (never run in a dry run) join the group: a dry run's pending job
    # there would cancel a real run's pending one (pending jobs in a group replace each other).
    assert {name for name, job in JOBS.items() if "concurrency" in job} == {
        "tag-draft",
        "build-sign",
    }


def test_no_asset_upload_can_replace_a_published_release() -> None:
    # C-15.7: the SBOM upload follows the draft step (which refuses a published release) in the
    # same job; the installer upload, a job later, re-checks the release is still a draft first.
    names = [str(s.get("name", "")) for s in _steps("tag-draft")]
    assert names.index(_step("tag-draft", "Draft the release")["name"]) < names.index(
        _step("tag-draft", "Attach the SBOMs")["name"]
    )
    attach = _step("build-sign", "Attach the signed installer")["run"]
    check = attach.index("--json isDraft --jq .isDraft")
    assert check < attach.index("gh release upload")
    assert (
        '[ "$draft" != "true" ]' in attach
        and "exit 1" in attach[check : attach.index("gh release upload")]
    )


def test_the_run_pushes_no_branch_and_keeps_no_credential() -> None:
    for name, job in JOBS.items():
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            assert not re.search(r"\bgit\b[^\n]*\b(push|commit)\b", run), (name, step.get("name"))
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False, name


def test_write_jobs_check_out_the_candidate_or_reverify_it() -> None:
    # tag-draft re-verifies C with the default (main) checkout's tools; build-sign and sbom build
    # from C itself.
    for name in ("sbom", "build-sign"):
        (checkout,) = [s for s in _steps(name) if "actions/checkout@" in str(s.get("uses", ""))]
        assert checkout["with"]["ref"] == CANDIDATE, name
    reverify = _step("tag-draft", "Re-verify")
    assert "prepare_release.py" in reverify["run"] and "--section-out" in reverify["run"]
    names = [str(s.get("name", "")) for s in _steps("tag-draft")]
    assert names.index(reverify["name"]) < min(
        i for i, n in enumerate(names) if n.startswith("Tag")
    )


def test_the_tag_job_drafts_from_the_verified_v_section() -> None:
    draft = _step("tag-draft", "Draft the release")
    assert '--notes-file "$RUNNER_TEMP/section.md"' in draft["run"]
    assert '--section-out "$RUNNER_TEMP/section.md"' in _step("tag-draft", "Re-verify")["run"]


def test_build_sign_gates_the_dists_it_packages_and_signs_from_the_builder_output() -> None:
    runs = [str(s.get("run", "")) for s in _steps("build-sign")]

    def at(text: str) -> int:
        (index,) = [i for i, run in enumerate(runs) if text in run]
        return index

    built = at("--filter @candleviewer/web --filter @candleviewer/desktop build")
    gate = at("electron_hardening_gate.py")
    package = at("pnpm run build:installer")
    assert at('--filter "@candleviewer/web^..." run build') < built < gate < package
    assert package == gate + 1  # the gate scans exactly what is packaged next (#3518)
    assert "--require-runtime" in runs[gate] and "xvfb-run -a" in runs[gate]
    sign, attach = runs[at("cosign sign-blob")], runs[at("gh release upload")]
    assert "apps/desktop/release/*.AppImage" in sign and "apps/desktop/dist" not in sign + attach
    assert "release.yml@refs/heads/main" in sign and "verify-blob" in sign
    assert "--clobber" in attach


def test_the_three_sboms_are_generated_validated_diffed_and_attached() -> None:
    sboms = [s for s in _steps("sbom") if str(s.get("uses", "")).startswith("anchore/")]
    assert [s["uses"].split(" ")[0] for s in sboms] == [SBOM_ACTION] * 3
    outputs = [s["with"]["output-file"] for s in sboms]
    assert outputs == ["sbom-api.cdx.json", "sbom-web.cdx.json", "sbom-desktop.cdx.json"]
    assert all(s["with"]["format"] == "cyclonedx-json" for s in sboms)
    assert all(s["with"]["upload-release-assets"] is False for s in sboms)
    main = (WORKFLOWS / "main.yml").read_text(encoding="utf-8")
    assert f"uses: {SBOM_ACTION}" in main  # the already-pinned action, not a second pin
    assert '--artefact "$artefact"' in _step("sbom", "Validate")["run"]
    assert (
        "sbom_diff.py" in _step("sbom", "Diff")["run"]
        and "--previous " in _step("sbom", "Diff")["run"]
    )
    attach = _step("tag-draft", "Attach the SBOMs")["run"]
    assert "--clobber" in attach and attach.count("sbom-") == 4
    assert "comment --issue" in _step("tag-draft", "Post the SBOM diff")["run"]


# --- behaviour ------------------------------------------------------------------------------------

FAKE_PYTHON = """import os, sys
print(os.environ["FAKE_OUT"])
sys.exit(int(os.environ.get("FAKE_RC", "0")))
"""


@pytest.mark.parametrize(
    ("ref", "candidate", "dry_run", "allow", "ok"),
    [
        ("refs/heads/main", SHA, "true", "false", True),
        ("refs/heads/feature", SHA, "true", "false", False),
        ("refs/tags/v1.0.0", SHA, "true", "false", False),
        ("refs/heads/main", "A" * 40, "true", "false", False),
        ("refs/heads/main", SHA[:39], "true", "false", False),
        ("refs/heads/main", SHA + "\nx", "true", "false", False),
        ("refs/heads/main", "main", "true", "false", False),
        ("refs/heads/main", SHA, "yes", "false", False),
        ("refs/heads/main", SHA, "true", "1", False),
    ],
)
def test_dispatch_is_refused_off_main_or_with_invalid_inputs(
    tmp_path: Path, ref: str, candidate: str, dry_run: str, allow: str, ok: bool
) -> None:
    step = _step("classify", "Refuse a ref other than main")
    env = {"EVENT": "workflow_dispatch", "REF": ref, "IN_CANDIDATE": candidate}
    env |= {"IN_DRY_RUN": dry_run, "IN_ALLOW": allow}
    rc, out, output = _bash(tmp_path, step["run"], env)
    assert (rc == 0) == ok, out
    if ok:
        assert output == f"candidate={SHA}\ndry_run=true\nallow_1_0_0=false\n"
    else:
        assert "::error::CI-REL-005" in out and "candidate=" not in output


def test_a_push_run_is_never_a_dry_run(tmp_path: Path) -> None:
    step = _step("classify", "Refuse a ref other than main")
    env = {"EVENT": "push", "REF": "refs/heads/main", "IN_CANDIDATE": "", "IN_DRY_RUN": ""}
    rc, out, output = _bash(tmp_path, step["run"], env | {"IN_ALLOW": ""})
    assert rc == 0 and output == "dry_run=false\nallow_1_0_0=false\n", out


@pytest.mark.parametrize(
    ("stdout", "rc", "expected_rc", "expected_output"),
    [
        (f"candidate={SHA}", 0, 0, f"candidate={SHA}\n"),
        ("candidate=", 0, 0, "candidate=\n"),
        # The tool's annotations go to stdout: only the key line reaches $GITHUB_OUTPUT.
        (f"::error::noise%0Acandidate=evil\ncandidate={SHA}", 0, 0, f"candidate={SHA}\n"),
        ("::error::CI-REL-005: 2 release candidates in one push", 1, 1, ""),
        ("candidate=not-a-sha", 0, 1, ""),
    ],
)
def test_classify_greps_only_the_candidate_line_into_the_outputs(
    tmp_path: Path, stdout: str, rc: int, expected_rc: int, expected_output: str
) -> None:
    step = _step("classify", "Name the push's one release candidate")
    env = {"BEFORE": "b" * 40, "AFTER": SHA, "FAKE_OUT": stdout, "FAKE_RC": str(rc)}
    got_rc, out, output = _bash(tmp_path, step["run"], env, {"python": FAKE_PYTHON})
    assert got_rc == expected_rc, out
    assert output == expected_output
    assert stdout.splitlines()[0] in out  # the tool's own output is still shown


def test_verify_greps_only_the_version_line_into_the_outputs(tmp_path: Path) -> None:
    step = _step("verify", "Verify the candidate")
    noisy = f"::error::CI-REL-005: x%0Aversion=9.9.9\nversion=0.2.0\nverified: {SHA}"
    env = {"CANDIDATE": SHA, "ALLOW_1_0_0": "false", "FAKE_OUT": noisy, "FAKE_RC": "0"}
    rc, out, output = _bash(tmp_path / "ok", step["run"], env, {"python": FAKE_PYTHON})
    assert rc == 0 and output == "version=0.2.0\nrc=0\n", out
    env |= {"FAKE_OUT": "::error::CI-REL-005: version 0.1.1 != expected 0.2.0", "FAKE_RC": "1"}
    rc, out, output = _bash(tmp_path / "refused", step["run"], env, {"python": FAKE_PYTHON})
    assert rc == 0 and output == "rc=1\n", out  # the decision is the next step's


@pytest.mark.parametrize(
    ("contract", "github", "version", "dry_run", "rc", "verified"),
    [
        ("0", "0", "0.2.0", "false", 0, "true"),
        ("0", "0", "0.2.0", "true", 0, "true"),
        ("1", "0", "", "false", 1, "false"),
        ("0", "1", "0.2.0", "false", 1, "false"),  # not GitHub-verified
        ("1", "0", "", "true", 0, "false"),  # a dry run reports without failing
        ("0", "1", "0.2.0", "true", 0, "false"),
        ("0", "0", "", "false", 1, "false"),  # no version line: refused
    ],
)
def test_verify_decides_and_a_dry_run_reports_without_failing(
    tmp_path: Path, contract: str, github: str, version: str, dry_run: str, rc: int, verified: str
) -> None:
    step = _step("verify", "Decide")
    env = {"CONTRACT_RC": contract, "GITHUB_RC": github, "VERSION": version, "DRY_RUN": dry_run}
    got, out, output = _bash(tmp_path, step["run"], env)
    assert got == rc, out
    assert f"verified={verified}\n" in output
    assert ("version=" in output) == (verified == "true")
    if verified == "false":
        assert ("::warning::CI-REL-005" if dry_run == "true" else "::error::CI-REL-005") in out


FAKE_COSIGN = """import json, os, sys
with open(os.environ["COSIGN_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1] == "sign-blob":
    open(sys.argv[sys.argv.index("--bundle") + 1], "w").write("{}")
"""


def test_sign_fails_ci_rel_003_when_the_builder_produced_nothing(tmp_path: Path) -> None:
    step = _step("build-sign", "Sign and verify the installer")
    (tmp_path / "apps/desktop/release").mkdir(parents=True)
    (tmp_path / "apps/desktop/dist").mkdir(parents=True)
    (tmp_path / "apps/desktop/dist/stray.AppImage").write_text("x", encoding="utf-8")
    log = tmp_path / "cosign.log"
    rc, out, _ = _bash(tmp_path, step["run"], {"COSIGN_LOG": str(log)}, {"cosign": FAKE_COSIGN})
    assert rc == 1 and "::error::CI-REL-003" in out
    assert not log.exists()  # nothing signed, and the old dist/ glob is not consulted


def test_sign_signs_and_verifies_each_installer_with_the_main_identity(tmp_path: Path) -> None:
    step = _step("build-sign", "Sign and verify the installer")
    release = tmp_path / "apps/desktop/release"
    release.mkdir(parents=True)
    (release / "CandleViewer-0.2.0.AppImage").write_text("x", encoding="utf-8")
    log = tmp_path / "cosign.log"
    rc, out, _ = _bash(tmp_path, step["run"], {"COSIGN_LOG": str(log)}, {"cosign": FAKE_COSIGN})
    assert rc == 0, out
    sign, verify = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert sign[:3] == ["sign-blob", "--yes", "--bundle"]
    identity = "https://github.com/owner/repo/.github/workflows/release.yml@refs/heads/main"
    assert verify[0] == "verify-blob" and identity in verify
    assert (release / "CandleViewer-0.2.0.AppImage.sigstore.json").exists()


FAKE_GH = """import json, os, sys
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["release", "view"]:
    print(os.environ["IS_DRAFT"])
"""


def _attach(tmp_path: Path, is_draft: str, bundle: bool) -> tuple[int, str, list[list[str]]]:
    step = _step("build-sign", "Attach the signed installer")
    release = tmp_path / "apps/desktop/release"
    release.mkdir(parents=True)
    (release / "CandleViewer-0.2.0.AppImage").write_text("x", encoding="utf-8")
    if bundle:
        (release / "CandleViewer-0.2.0.AppImage.sigstore.json").write_text("{}", encoding="utf-8")
    log = tmp_path / "gh.log"
    env = {"VERSION": "0.2.0", "GH_LOG": str(log), "IS_DRAFT": is_draft}
    rc, out, _ = _bash(tmp_path, step["run"], env, {"gh": FAKE_GH})
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return rc, out, calls


def test_attach_refuses_an_installer_without_its_signature_bundle(tmp_path: Path) -> None:
    rc, out, calls = _attach(tmp_path, "true", bundle=False)
    assert rc == 1 and "::error::CI-REL-003" in out
    assert not [c for c in calls if c[:2] == ["release", "upload"]]


def test_attach_uploads_to_a_draft(tmp_path: Path) -> None:
    rc, out, calls = _attach(tmp_path, "true", bundle=True)
    assert rc == 0, out
    (upload,) = [c for c in calls if c[:2] == ["release", "upload"]]
    assert upload[2] == "v0.2.0" and "--clobber" in upload and len(upload) == 8


@pytest.mark.parametrize("is_draft", ["false", ""])
def test_attach_never_replaces_a_published_release_s_assets(tmp_path: Path, is_draft: str) -> None:
    # C-15.7: the owner may publish while build-sign runs; the old shape uploaded with --clobber.
    rc, out, calls = _attach(tmp_path, is_draft, bundle=True)
    assert rc == 1 and "::error::CI-REL-005: release v0.2.0 is published" in out
    assert [c[:2] for c in calls] == [["release", "view"]]
