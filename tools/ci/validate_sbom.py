#!/usr/bin/env python3
"""E03-T08: SR-133 -- structural validation of the CycloneDX SBOM.

The full JSON-Schema for CycloneDX (hosted upstream) is not vendored here
because pulling it over the network from a supply-chain-hardening job is
exactly the kind of dependency this ticket is trying to reduce (SR-137's
"no long-lived registry password" principle extends to "no ad hoc network
fetch mid-job" more broadly, ADR-0013 rule 6). Instead this validates the
required top-level shape the ticket's "Test plan" contract check cares
about: a well-formed CycloneDX 1.x document with the fields any consumer
(deploy-time gate, `07-release-and-prr.md` artefact index) depends on.

Error code: CI-IMG-005 (SBOM generation/structure failure).

#3099 (SR-133, the release run): with `--artefact NAME` the codes are CI-REL-006 and name the
artefact, and an SBOM listing no component is refused as empty; a missing, empty or non-JSON
file is a finding too (exit 1). `main.yml`'s image SBOM call is unchanged.

Exit codes: 0 valid, 1 invalid (CI-IMG-005, or CI-REL-006 with `--artefact`), 2 internal error
(file missing or not JSON, without `--artefact`).

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_TOP_LEVEL_FIELDS = ("bomFormat", "specVersion", "components")


def validate(doc: dict[str, object]) -> list[str]:
    """Return a list of CI-IMG-005 problems (empty means valid)."""
    problems: list[str] = []

    missing = [f for f in REQUIRED_TOP_LEVEL_FIELDS if f not in doc]
    if missing:
        problems.append(f"missing required field(s): {missing}")
        return problems  # further checks would just KeyError

    if doc["bomFormat"] != "CycloneDX":
        problems.append(f"bomFormat is {doc['bomFormat']!r}, expected 'CycloneDX'")

    spec_version = doc["specVersion"]
    if not isinstance(spec_version, str) or not spec_version.startswith("1."):
        problems.append(f"specVersion {spec_version!r} is not a CycloneDX 1.x version")

    components = doc["components"]
    if not isinstance(components, list):
        problems.append("components is not a list")
    else:
        for i, component in enumerate(components):
            if not isinstance(component, dict):
                problems.append(f"components[{i}] is not an object")
                continue
            for field in ("type", "name"):
                if field not in component:
                    problems.append(f"components[{i}] missing {field!r}")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbom", required=True, type=Path, help="path to the CycloneDX JSON SBOM")
    parser.add_argument(
        "--artefact", default=None, help="release artefact the SBOM describes (CI-REL-006 mode)"
    )
    args = parser.parse_args(argv)
    prefix = f"CI-REL-006: {args.artefact} SBOM ({args.sbom})" if args.artefact else "CI-IMG-005"
    unreadable = 1 if args.artefact else 2

    if not args.sbom.exists():
        print(f"{prefix}: SBOM file not found: {args.sbom}", file=sys.stderr)
        return unreadable

    try:
        doc = json.loads(args.sbom.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"{prefix}: SBOM is not valid JSON: {exc}", file=sys.stderr)
        return unreadable

    if not isinstance(doc, dict):
        print(f"{prefix}: SBOM root is not a JSON object", file=sys.stderr)
        return unreadable

    problems = validate(doc)
    if args.artefact and not problems and not doc["components"]:
        problems.append("empty: it lists no component")
    if problems:
        for p in problems:
            print(f"{prefix}: {p}", file=sys.stderr)
        return 1

    print(f"SBOM OK: {len(doc['components'])} components, specVersion={doc['specVersion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
