#!/usr/bin/env python3
"""E03-T08: SR-135 -- SBOM diff vs the previous `:dev` image, for the job summary.

Ticket "Technical notes / design": "a new transitive dependency appearing
without a lockfile change is a strong tamper signal and is highlighted."
This compares the current build's CycloneDX component set against the
previous `:dev` image's own attached SBOM attestation (fetched via
`cosign download sbom`, best-effort) and prints a Markdown summary of
added/removed components, suitable for `>> $GITHUB_STEP_SUMMARY`.

When there is no previous digest (first build ever, or the previous image's
attestation could not be fetched) every current component is reported as
"new" and a note explains why — this is not itself a failure (SR-135 is a
review aid, not a blocking gate; CI-IMG-003/004/005 are the blocking gates).

#3099 (SR-133, the release run): `--previous PATH` diffs against a file instead, the previous
release's attached SBOM, under `--heading`. A missing file is the first release (no baseline),
an unreadable one is said so; either way every current component is listed as new.

Stdlib only; shells out to `cosign` when a previous digest is available.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _component_keys(doc: dict[str, object]) -> set[str]:
    keys: set[str] = set()
    components = doc.get("components", [])
    if not isinstance(components, list):
        return keys
    for c in components:
        if not isinstance(c, dict):
            continue
        name = c.get("name", "?")
        version = c.get("version", "?")
        keys.add(f"{name}@{version}")
    return keys


def _fetch_previous_sbom(image: str, digest: str) -> dict[str, object] | None:
    if digest in ("", "none"):
        return None
    proc = subprocess.run(
        ["cosign", "download", "sbom", f"{image}@{digest}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        parsed: object = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


_IMAGE_HEADING = "### SBOM diff vs previous `:dev` image (SR-135)"
_IMAGE_NO_BASELINE = "No previous `:dev` attestation available (first build, or fetch failed)"
FIRST_RELEASE = "First release, no baseline (no previous release SBOM for this artefact)"


def _read_previous(path: Path) -> tuple[dict[str, object] | None, str]:
    """The previous release's SBOM, or None and why there is no baseline."""
    if not path.is_file():
        return None, FIRST_RELEASE
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        return None, f"The previous release SBOM `{path.name}` is unreadable, no baseline"
    return parsed, ""


def render_diff(
    current: dict[str, object],
    previous: dict[str, object] | None,
    *,
    heading: str = _IMAGE_HEADING,
    no_baseline: str = _IMAGE_NO_BASELINE,
) -> str:
    current_keys = _component_keys(current)

    lines = [heading, ""]

    if previous is None:
        lines.append(
            f"_{no_baseline} — all {len(current_keys)} components listed as new for review._"
        )
        lines.append("")
        for k in sorted(current_keys):
            lines.append(f"- + `{k}`")
        return "\n".join(lines) + "\n"

    previous_keys = _component_keys(previous)
    added = sorted(current_keys - previous_keys)
    removed = sorted(previous_keys - current_keys)

    if not added and not removed:
        lines.append("_No component changes._")
        return "\n".join(lines) + "\n"

    if added:
        lines.append(f"**Added ({len(added)}):**")
        lines.extend(f"- + `{k}`" for k in added)
        lines.append("")
    if removed:
        lines.append(f"**Removed ({len(removed)}):**")
        lines.extend(f"- - `{k}`" for k in removed)

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--current", required=True, type=Path, help="current build's CycloneDX SBOM"
    )
    baseline = parser.add_mutually_exclusive_group(required=True)
    baseline.add_argument("--previous-digest", help="previous :dev image digest, or 'none'")
    baseline.add_argument(
        "--previous", type=Path, help="previous release's SBOM file (missing: first release)"
    )
    parser.add_argument("--image", help="with --previous-digest: registry/repo ref")
    parser.add_argument("--heading", default=None, help="markdown heading line")
    args = parser.parse_args(argv)
    if args.previous_digest is not None and not args.image:
        parser.error("--previous-digest needs --image")

    current = json.loads(args.current.read_text(encoding="utf-8"))
    if args.previous is not None:
        previous, why = _read_previous(args.previous)
        heading = args.heading or f"### SBOM diff vs `{args.previous.name}` (SR-133)"
        print(render_diff(current, previous, heading=heading, no_baseline=why))
        return 0
    previous = _fetch_previous_sbom(args.image, args.previous_digest)

    print(render_diff(current, previous, heading=args.heading or _IMAGE_HEADING))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
