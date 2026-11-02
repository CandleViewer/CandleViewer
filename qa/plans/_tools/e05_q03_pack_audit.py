#!/usr/bin/env python3
"""E05-Q03 (#263) audit: the E05 regression pack against the baselines, tests and stories.

Standalone, offline, stdlib only; it runs under `python3 -I` and executes no repo code. It reads
the pack (`qa/plans/e05-regression-pack.md`) and the sign-off record (`docs/qa/e05-signoff.md`)
from the working tree, the VR baseline names from `git ls-tree` at HEAD, and the cited test and
story files as text.

Gates (one mutation each in `--self-test`, each caught by its own gate):
  G-MATRIX    the block between the `e05-vr-matrix` markers equals the per-component table
              derived from `packages/ui/vr/baselines/` (`{story}--{theme}--{density}.png`),
              cell padding aside; `--fill` rewrites it.
  G-DEFECTS   every row of the pack's defect map (D1-D3, F-1-F-3) cites a test file that exists,
              and each quoted test title in the row stands in one of the row's cited files.
  G-EXCLUDED  the pack names exactly as many stories as `packages/ui/src` tags `perf`.
  G-HYGIENE   both documents: no local path, no worker name, no closing keyword followed by an
              issue number.

Usage (from the repo root):
  python3 -I qa/plans/_tools/e05_q03_pack_audit.py --check [--fill]
  python3 -I qa/plans/_tools/e05_q03_pack_audit.py --self-test
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "qa/plans/e05-regression-pack.md"
RECORD = ROOT / "docs/qa/e05-signoff.md"
BASELINES = "packages/ui/vr/baselines/"
BEGIN, END = "<!-- e05-vr-matrix:begin -->", "<!-- e05-vr-matrix:end -->"
TIERS = ("atoms", "molecules", "organisms", "foundations", "trading")
DEFECT_IDS = ("D1", "D2", "D3", "F-1", "F-2", "F-3")
CLOSING = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s*:?\s+#\d+", re.IGNORECASE)
LOCAL = re.compile(r"/home/|/tmp/|/Users/|-worker-[0-9]")


def baseline_names() -> list[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", BASELINES],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line.rsplit("/", 1)[1] for line in out.splitlines() if line.endswith(".png")]


def matrix_block(names: list[str]) -> str:
    stories: dict[str, set[str]] = defaultdict(set)
    cells: dict[str, int] = defaultdict(int)
    for name in names:
        component, story, _theme, _density = name[: -len(".png")].split("--")
        stories[component].add(story)
        cells[component] += 1
    rows = ["| Component | Tier | Stories | Cells |", "| --- | --- | ---: | ---: |"]
    tier_counts: dict[str, list[int]] = {t: [0, 0, 0] for t in TIERS}
    for component in sorted(stories):
        tier = component.split("-", 1)[0]
        n_s, n_c = len(stories[component]), cells[component]
        rows.append(f"| `{component}` | {tier} | {n_s} | {n_c} |")
        tc = tier_counts[tier]
        tc[0], tc[1], tc[2] = tc[0] + 1, tc[1] + n_s, tc[2] + n_c
    total_s = sum(len(s) for s in stories.values())
    rows.append(f"| **total: {len(stories)} components** | | **{total_s}** | **{len(names)}** |")
    by_tier = "; ".join(
        f"{t} {c[0]} ({c[1]} stories, {c[2]} cells)" for t, c in tier_counts.items()
    )
    return "\n".join([f"By tier: {by_tier}.", "", *rows])


def between(text: str) -> str | None:
    if BEGIN not in text or END not in text:
        return None
    return text.split(BEGIN, 1)[1].split(END, 1)[0].strip()


def normalise(block: str) -> list[str]:
    """Prettier pads table cells and separator dashes; compare the cells, not the padding."""
    out = []
    for line in block.strip().splitlines():
        line = re.sub(r"\s*\|\s*", "|", line.strip())
        out.append(re.sub(r"-{3,}", "---", line))
    return out


def gate_matrix(pack: str, names: list[str]) -> list[str]:
    got = between(pack)
    if got is None:
        return ["G-MATRIX: the e05-vr-matrix markers are missing"]
    if normalise(got) == normalise(matrix_block(names)):
        return []
    return ["G-MATRIX: the table differs from the baselines (--fill)"]


def gate_defects(pack: str) -> list[str]:
    fails: list[str] = []
    for did in DEFECT_IDS:
        row = next((ln for ln in pack.splitlines() if ln.startswith(f"| {did} ")), None)
        if row is None:
            fails.append(f"G-DEFECTS: no row for {did}")
            continue
        files = re.findall(r"`(packages/ui/test/[\w./-]+\.test\.tsx?)`", row)
        if not files:
            fails.append(f"G-DEFECTS: {did} cites no test file")
            continue
        texts = []
        for f in files:
            p = ROOT / f
            if not p.is_file():
                fails.append(f"G-DEFECTS: {did} cites a missing file {f}")
            else:
                texts.append(p.read_text(encoding="utf-8"))
        for title in re.findall(r"\"([^\"]{8,})\"", row):
            if not any(title in t for t in texts):
                fails.append(f"G-DEFECTS: {did} title not found in its files: {title[:60]}")
    return fails


def gate_excluded(pack: str) -> list[str]:
    tagged = 0
    for p in (ROOT / "packages/ui/src").rglob("*.stories.tsx"):
        tagged += len(re.findall(r"tags:\s*\[[^\]]*\"perf\"", p.read_text(encoding="utf-8")))
    section = pack.split("## H. ", 1)[1] if "## H. " in pack else ""
    named = len(re.findall(r"^- `[a-z0-9-]+--[a-z0-9-]+`", section, re.MULTILINE))
    if named != tagged:
        return [f"G-EXCLUDED: the pack names {named} perf stories, packages/ui/src tags {tagged}"]
    return []


def gate_hygiene(label: str, text: str) -> list[str]:
    fails = []
    if m := CLOSING.search(text):
        fails.append(f"G-HYGIENE: {label} has a closing keyword: {m.group(0)}")
    if m := LOCAL.search(text):
        fails.append(f"G-HYGIENE: {label} has a local path or worker name: {m.group(0)}")
    return fails


def check(pack: str, record: str, names: list[str]) -> list[str]:
    return [
        *gate_matrix(pack, names),
        *gate_defects(pack),
        *gate_excluded(pack),
        *gate_hygiene("pack", pack),
        *gate_hygiene("record", record),
    ]


def self_test(pack: str, record: str, names: list[str]) -> int:
    base = check(pack, record, names)
    if base:
        print("SELF-TEST: the unmutated documents must pass first:", *base, sep="\n  ")
        return 1
    first_row = next(ln for ln in pack.splitlines() if ln.startswith("| `"))
    d2 = next(ln for ln in pack.splitlines() if ln.startswith("| D2 "))
    section_h = pack.split("## H. ", 1)[1]
    excluded_first = re.search(r"^- `[a-z0-9-]+--[a-z0-9-]+`.*$", section_h, re.MULTILINE)
    if excluded_first is None:
        print("SELF-TEST: section H names no story")
        return 1
    mutations = {
        "G-MATRIX": (pack.replace(first_row + "\n", "", 1), record),
        "G-DEFECTS": (pack.replace(d2, d2.replace("max-height", "max-width", 1), 1), record),
        "G-EXCLUDED": (pack.replace(excluded_first.group(0) + "\n", "", 1), record),
        "G-HYGIENE": (pack, record + "\nCloses " + "#263\n"),
    }
    bad = 0
    for gate, (p, r) in mutations.items():
        found = {f.split(":", 1)[0] for f in check(p, r, names)}
        ok = found == {gate}
        bad += not ok
        caught = sorted(found) or "nothing"
        print(f"{'ok  ' if ok else 'FAIL'} mutation for {gate}: caught by {caught}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    pack = PACK.read_text(encoding="utf-8")
    record = RECORD.read_text(encoding="utf-8")
    names = baseline_names()
    if args.self_test:
        return self_test(pack, record, names)
    if args.fill:
        if between(pack) is None:
            print("FAIL G-MATRIX: the e05-vr-matrix markers are missing")
            return 1
        head, rest = pack.split(BEGIN, 1)
        tail = rest.split(END, 1)[1]
        pack = f"{head}{BEGIN}\n\n{matrix_block(names)}\n\n{END}{tail}"
        PACK.write_text(pack, encoding="utf-8", newline="\n")
    fails = check(pack, record, names)
    for f in fails:
        print("FAIL", f)
    print(f"{len(names)} baseline cells; {len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
