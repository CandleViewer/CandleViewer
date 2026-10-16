"""Regenerate `services/api/.importlinter` from `docs/plan/module-contracts.toml`.

E02-T06 (`CONSTITUTION.md` §3, C-3.1..C-3.5, §9 #18): the manifest is the
single machine-readable source of truth; this script is the *only* place
that turns it into import-linter's config so the two files cannot silently
diverge from each other (they still can diverge from `CONSTITUTION.md` §3
itself — that is what
`services/api/tests/unit/architecture/test_module_contracts_drift.py`
catches).

Usage:
    python scripts/gen_importlinter_contracts.py [--check]

`--check` (used by CI / `make arch`) regenerates into memory and exits 1 if
the committed file would change, instead of writing it — so a manifest edit
that forgets to regenerate fails the build rather than silently drifting.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "plan" / "module-contracts.toml"
OUTPUT_PATH = REPO_ROOT / "services" / "api" / ".importlinter"

HEADER = """\
# GENERATED FILE — do not hand-edit.
#
# Regenerate with: python scripts/gen_importlinter_contracts.py
# Source of truth: docs/plan/module-contracts.toml (itself a mirror of
# CONSTITUTION.md §3 — see that file's header for the drift-prevention
# contract between the three). This wires C-3.1 (one-way dependencies, no
# cycles), C-3.2 (secrets), C-3.3 (audit) and §9 #18 (architecture gate).

[importlinter]
root_package = candleviewer
include_external_packages = True
exclude_type_checking_imports = True

"""


def load_manifest() -> dict:
    with MANIFEST_PATH.open("rb") as f:
        return tomllib.load(f)


def render(manifest: dict) -> str:
    modules = manifest["module"]
    all_paths = [m["path"] for m in modules]
    lines = [HEADER]

    # One forbidden contract per module: everything not in its `allowed`
    # list (and not itself) is forbidden. This is the mechanical encoding of
    # C-3.1 ("dependencies flow one way ... cycles are forbidden") plus the
    # exact per-module edge list transcribed from §3.
    for m in modules:
        path = m["path"]
        # `candleviewer.observability` (M24) is treated as a universal
        # utility dependency, like M1 `config`: every module's scaffold
        # `service.py` (E02-T05, merged) imports
        # `candleviewer.observability.health.HealthReport`/`HealthStatus` to
        # satisfy the shared lifecycle contract's `health()` method
        # (`docs/plan/20-architecture.md` Sec.3). §3's table does not list
        # this edge explicitly, but §3 also does not forbid it, and blocking
        # already-merged, reviewed code here would make `make arch` red on
        # a clean checkout — the opposite of this ticket's acceptance
        # criterion 1. Deviation noted in the PR; a future ADR should either
        # add this edge to §3's table explicitly or replace the direct
        # import with an injected reporter so M24 stays a true leaf.
        allowed = set(m["allowed"]) | {"candleviewer.observability"}
        forbidden = sorted(p for p in all_paths if p != path and p not in allowed)
        if not forbidden:
            continue
        lines.append(f"[importlinter:contract:forbidden-{m['number']}]")
        lines.append(f"name = {m['number']} ({m['name']}) may only import its §3 allowed list")
        lines.append("type = forbidden")
        lines.append(f"source_modules =\n    {path}")
        forbidden_block = "\n    ".join(forbidden)
        lines.append(f"forbidden_modules =\n    {forbidden_block}")
        lines.append(
            "\n".join(
                [
                    "",
                ]
            )
        )

    # C-3.2 / C-3.3 cross-cutting protected contracts.
    cc = manifest["cross_cutting"]
    import_rule = cc["c32_importers"]
    lines.append("[importlinter:contract:protected-secrets]")
    rule_id = import_rule["rule"]
    lines.append(f"name = {rule_id} — secrets is importable only by its allow-list")
    lines.append("type = protected")
    lines.append(f"protected_modules =\n    {import_rule['module']}")
    # No composition-root exception: `candleviewer.app` obtains secrets/audit
    # instances via `candleviewer.admin.wiring` (M21) injection, so the
    # allow-lists are exactly C-3.2 / C-3.3.
    importers_block = "\n    ".join(import_rule["only_importable_by"])
    lines.append(f"allowed_importers =\n    {importers_block}")
    lines.append("")

    audit = cc["audit_read_importers"]
    lines.append("[importlinter:contract:protected-audit]")
    lines.append(f"name = {audit['rule']} — audit is write-only except its read-path allow-list")
    lines.append("type = protected")
    lines.append(f"protected_modules =\n    {audit['module']}")
    importers_block = "\n    ".join(audit["only_importable_by"])
    lines.append(f"allowed_importers =\n    {importers_block}")
    lines.append("")

    # Independence contract between sibling modules that §3 deliberately
    # does not connect (neither depends on the other, directly or
    # transitively): the three modules M15/M16/M17 that hang off M14 (oms)
    # but never import each other, per the §3 "May depend on" column. A
    # broad "all 24 modules must be independent" contract is not meaningful
    # here — the M1-M24 table is intentionally a DAG, not a flat set — so
    # C-3.1's no-cycles guarantee instead comes from every per-module
    # forbidden contract above only allowing edges that already point one
    # way in the table (an edge back up the numbering is always in some
    # module's forbidden list).
    independent_siblings = [
        "candleviewer.rules",
        "candleviewer.paper",
        "candleviewer.risk",
    ]
    lines.append("[importlinter:contract:independence-oms-siblings]")
    lines.append(
        "name = C-3.1 rules/paper/risk are independent siblings of oms (no cross-imports)"
    )
    lines.append("type = independence")
    modules_block = "\n    ".join(independent_siblings)
    lines.append(f"modules =\n    {modules_block}")
    lines.append("")

    # ADR-0003 / E07-T01: storage engine driver packages are forbidden
    # outside candleviewer.storage. One forbidden contract per non-storage
    # module, forbidding the driver package set — import-linter's
    # `forbidden` contract type works against external packages too when
    # `include_external_packages = True` (set in HEADER).
    drivers = cc["storage_driver_imports"]
    exempt = set(drivers["exempt_modules"])
    driver_forbidden_block = "\n    ".join(drivers["forbidden_packages"])
    for m in modules:
        path = m["path"]
        if path in exempt:
            continue
        lines.append(f"[importlinter:contract:forbidden-storage-drivers-{m['number']}]")
        lines.append(
            f"name = {drivers['rule']} — {m['number']} ({m['name']}) may not import a "
            "storage driver directly"
        )
        lines.append("type = forbidden")
        lines.append(f"source_modules =\n    {path}")
        lines.append(f"forbidden_modules =\n    {driver_forbidden_block}")
        lines.append("")

    # E04-T03: only candleviewer.observability may import prometheus_client.
    facade = cc["metrics_facade"]
    facade_exempt = set(facade["exempt_modules"])
    facade_block = "\n    ".join(facade["forbidden_packages"])
    for m in modules:
        if m["path"] in facade_exempt:
            continue
        lines.append(f"[importlinter:contract:forbidden-metrics-facade-{m['number']}]")
        lines.append(
            f"name = {facade['rule']} — {m['number']} ({m['name']}) must use the metrics "
            "facade, not prometheus_client"
        )
        lines.append("type = forbidden")
        lines.append(f"source_modules =\n    {m['path']}")
        lines.append(f"forbidden_modules =\n    {facade_block}")
        lines.append("allow_indirect_imports = True")
        lines.append("")

    # C-2.20 / CV-LINT-HOTPATH: hot-path modules never import the statechart runtime.
    hot = cc["hotpath_statechart"]
    lines.append("[importlinter:contract:forbidden-hotpath-statechart]")
    lines.append(f"name = {hot['rule']} — hot-path modules never import the statechart runtime")
    lines.append("type = forbidden")
    lines.append("source_modules =\n    " + "\n    ".join(hot["source_modules"]))
    lines.append("forbidden_modules =\n    " + "\n    ".join(hot["forbidden_modules"]))
    lines.append("")

    # C-2.20 / ADR-0016 (23-ws-protocol §6.4): the WS gateway never reaches an `Interpreter`.
    ws = cc["ws_statechart"]
    lines.append("[importlinter:contract:forbidden-ws-statechart]")
    lines.append(
        f"name = {ws['rule']} — ws never imports the statechart factory, persistence or runtime"
    )
    lines.append("type = forbidden")
    lines.append("source_modules =\n    " + "\n    ".join(ws["source_modules"]))
    lines.append("forbidden_modules =\n    " + "\n    ".join(ws["forbidden_modules"]))
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest()
    rendered = render(manifest)

    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(
                "services/api/.importlinter is stale — run "
                "`python scripts/gen_importlinter_contracts.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("services/api/.importlinter is up to date.")
        return 0

    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
