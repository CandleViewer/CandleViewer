"""#272 (E05-X02): the design-system security review's repeatable facts.

docs/security/reviews/E05-X02-design-system-review.md records the review; these tests keep three
of its verdicts true after it merges:

- §9: the design tokens are scanned for secrets. `.gitleaks.toml` extends the default ruleset and
  no allowlist path, global or per rule, matches a file under `packages/ui/tokens/`.
- §10: the CSP is not weakened. Neither CSP site lets `script-src` run inline code by
  `'unsafe-inline'` (or eval), and every inline script in `apps/web/index.html` is allowed by its
  own hash (none exists today; E10-S01 embeds the pre-paint script).
- §11: Storybook is not published. No workflow uploads a Storybook build or runs a pages / hosted
  Storybook step (by `uses:`, by an `upload-artifact` path, or by a `run:` that copies the build
  out), and the dev server binds loopback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[2]
GITLEAKS = ROOT / ".gitleaks.toml"
TOKENS = ROOT / "packages" / "ui" / "tokens"
INDEX = ROOT / "apps" / "web" / "index.html"
DESKTOP_CSP = ROOT / "apps" / "desktop" / "src" / "main" / "csp.ts"
WORKFLOWS = ROOT / ".github" / "workflows"
UI_PACKAGE = ROOT / "packages" / "ui" / "package.json"

#: Sources a `script-src` may hold: the app's own origin or a hash (CSP3 hash-source).
SCRIPT_SOURCE = re.compile(r"'self'|'sha(?:256|384|512)-[A-Za-z0-9+/]+={0,2}'")
#: Steps that would put a Storybook build on a host: pages deploys and hosted-Storybook services.
PUBLISH_USES = re.compile(
    r"deploy-pages|upload-pages-artifact|gh-pages|chromaui|chromatic", re.IGNORECASE
)
#: Shell verbs that would copy a Storybook build to a host from a `run:` step.
TRANSFER_VERBS = re.compile(
    r"\b(?:rsync|scp|aws s3|s3 (?:cp|sync)|netlify|vercel|surge|gsutil|az storage)\b", re.IGNORECASE
)
#: What a `run:` step that names the Storybook build may do with it: build it or test against it.
BUILD_OR_TEST = re.compile(r"storybook build|playwright", re.IGNORECASE)


def _allowlist_paths(config: dict[str, Any]) -> list[str]:
    paths = list((config.get("allowlist") or {}).get("paths", []))
    for allowlist in config.get("allowlists", []) or []:
        paths += allowlist.get("paths", [])
    for rule in config.get("rules", []):
        for allowlist in [rule.get("allowlist") or {}, *(rule.get("allowlists") or [])]:
            paths += allowlist.get("paths", [])
    return [str(path) for path in paths]


def _token_files() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in TOKENS.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def _script_src(policy: str) -> list[str]:
    for directive in policy.split(";"):
        name, *sources = directive.split()
        if name == "script-src":
            return sources
    raise AssertionError(f"no script-src in {policy!r}")


def _steps() -> Iterator[tuple[str, dict[str, Any]]]:
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                yield workflow.name, step


def test_gitleaks_scans_the_design_tokens_with_no_allowlisted_path() -> None:
    config = tomllib.loads(GITLEAKS.read_text(encoding="utf-8"))
    assert config["extend"]["useDefault"] is True
    files = _token_files()
    assert any(name.endswith(".tokens.json") for name in files), files
    allowed = [
        (pattern, name)
        for pattern in _allowlist_paths(config)
        for name in files
        if re.search(pattern, name)
    ]
    assert allowed == []


def test_the_web_meta_csp_runs_no_inline_script_without_its_hash() -> None:
    html = INDEX.read_text(encoding="utf-8")
    (policy,) = re.findall(
        r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html, flags=re.DOTALL
    )
    sources = _script_src(policy)
    assert sources and all(SCRIPT_SOURCE.fullmatch(source) for source in sources), sources
    inline = re.findall(
        r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE
    )
    for body in inline:
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in sources, "an inline script without its hash in script-src"


def test_the_desktop_csp_script_src_holds_no_unsafe_source() -> None:
    source = DESKTOP_CSP.read_text(encoding="utf-8")
    (directive,) = re.findall(r'"(script-src [^"]*)"', source)
    sources = directive.split()[1:]
    assert sources and all(SCRIPT_SOURCE.fullmatch(token) for token in sources), sources


def test_no_workflow_publishes_a_storybook_build() -> None:
    uploads, publishers, transfers = [], [], []
    for workflow, step in _steps():
        run = str(step.get("run", ""))
        if "storybook-static" in run and (
            TRANSFER_VERBS.search(run) or not BUILD_OR_TEST.search(run)
        ):
            transfers.append((workflow, str(step.get("name", run[:60]))))
        uses = str(step.get("uses", ""))
        if PUBLISH_USES.search(uses):
            publishers.append((workflow, uses))
        if "upload-artifact@" in uses:
            path = str((step.get("with") or {}).get("path", ""))
            if "storybook-static" in path:
                uploads.append((workflow, path))
    assert (uploads, publishers, transfers) == ([], [], [])


def test_the_storybook_dev_server_binds_loopback() -> None:
    scripts = json.loads(UI_PACKAGE.read_text(encoding="utf-8"))["scripts"]
    assert re.search(r"--host 127\.0\.0\.1(?:\s|$)", scripts["storybook"]), scripts["storybook"]
    assert "--disable-telemetry" in scripts["storybook"]
    assert "--disable-telemetry" in scripts["storybook:build"]
