#!/usr/bin/env python3
"""E43-T01: the `csp-assertion (E43-T01)` step (`tools/ci/csp_assertion.py`) of the `build` CI job,
beside the Electron-hardening gate step (SR-112, SR-114, SR-119).

The web `<meta>` (built by `vite build` from `packages/config/src/csp-policy.mjs`), the Electron
response header (`dist/main/csp.js`, from the collected facts) and the FastAPI header
(`services/api/candleviewer/api/csp.py`, loaded by path: stdlib only) are one policy. Each must
equal the committed golden strings in `packages/config/src/csp-policy.golden.json` exactly, pass the
directive rules of `electron_hardening_checks.check_csp` (no `unsafe-inline` / `unsafe-eval`, no
wildcard or extra `connect-src`, header-only directives in the header only), and no `*.js` under
the web dist may name an exchange host. Exit 0 = clean, 1 = violations, 2 = usage. Stdlib only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.ci.electron_hardening_checks import (
    Violation,
    check_bundle_hosts,
    check_csp,
    extract_meta_csp,
)

GOLDEN = REPO / "packages/config/src/csp-policy.golden.json"
API_CSP = REPO / "services/api/candleviewer/api/csp.py"


def _api_policy(path: Path) -> tuple[str, str] | None:
    """(header, Reporting-Endpoints) the API builds by default, or None if csp.py will not load."""
    spec = importlib.util.spec_from_file_location("cv_api_csp", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module.build_csp_policy(), module.build_reporting_endpoints()
    except (
        ImportError,
        OSError,
        SyntaxError,
        AttributeError,
        TypeError,
        ValueError,
        RuntimeError,
    ):
        # reported as a violation by the caller
        return None


def _equal(subject: str, got: str, want: str) -> list[Violation]:
    if got == want:
        return []
    return [
        Violation(
            "SR-112",
            subject,
            f"policy is not the golden one\n  got:  {got}\n  want: {want}",
        )
    ]


def run_csp_assertion(
    *,
    web_dist: Path,
    facts: dict[str, Any],
    golden_path: Path = GOLDEN,
    api_csp_path: Path = API_CSP,
    require_header_fact: bool = True,
) -> list[Violation]:
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    vs: list[Violation] = []

    html_path = web_dist / "index.html"
    html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    meta = extract_meta_csp(html)
    if meta is None:
        vs.append(Violation("SR-112", "web dist index.html", "CSP <meta> is missing"))
    else:
        vs += check_csp("web dist <meta> CSP", meta, "meta")
        vs += _equal("web dist <meta> CSP", meta, golden["meta"])

    header = facts.get("cspHeader")
    if isinstance(header, str):
        vs += check_csp("Electron CSP header", header)
        vs += _equal("Electron CSP header", header, golden["header"])
    elif require_header_fact:
        vs.append(Violation("SR-112", "facts", "no Electron CSP header fact collected"))

    api = _api_policy(api_csp_path)
    if api is None:
        vs.append(
            Violation(
                "SR-112", str(api_csp_path), "the API policy builder does not load"
            )
        )
    else:
        vs += check_csp("FastAPI CSP header", api[0])
        vs += _equal("FastAPI CSP header", api[0], golden["header"])
        vs += _equal(
            "FastAPI Reporting-Endpoints", api[1], golden["reporting_endpoints"]
        )

    scripts = sorted(web_dist.rglob("*.js")) if web_dist.is_dir() else []
    if not scripts:
        vs.append(Violation("SR-114", str(web_dist), "no renderer *.js found to scan"))
    for p in scripts:
        text = p.read_text(encoding="utf-8", errors="replace")
        vs += check_bundle_hosts(
            f"renderer bundle {p.relative_to(web_dist).as_posix()}", text
        )
    return vs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--web-dist", type=Path, required=True, help="apps/web/dist")
    ap.add_argument("--facts", type=Path, required=True, help="hardening-facts.json")
    args = ap.parse_args(argv)
    facts = json.loads(args.facts.read_text(encoding="utf-8"))
    violations = run_csp_assertion(web_dist=args.web_dist, facts=facts)
    if not violations:
        print(
            "csp-assertion: clean (web meta, Electron header and API header are the golden policy)"
        )
        return 0
    for v in violations:
        print(v.render(), file=sys.stderr)
    print(f"csp-assertion: {len(violations)} violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
