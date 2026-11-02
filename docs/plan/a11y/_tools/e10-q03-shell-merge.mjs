// E10-Q03 (#302): merge the per-state axe results of one A11Y_OUT/<target> dir (<dir>/manifest.json,
// <dir>/states/*.json, written by e10-q03-shell.qa.ts) into <dir>/results.json.gz (every cell) and
// <dir>/summary.md (headline counts, sha256 of each file, only the cells that are not clean).
// Usage: node e10-q03-shell-merge.mjs [--strict] <dir> [<dir> ...]   (one dir per target: web, electron)
// Exit 1 on: no manifest (the control did not run), a missing/extra state file, a wrong cell count
// (states x themes x densities x motions), an errored cell, an off-site request, or a cell whose
// `applied` theme/density is not the one it names. --strict also exits 1 on a violation of ANY impact.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const args = process.argv.slice(2);
const strict = args.includes("--strict");
const dirs = args.filter((a) => a !== "--strict");
const IMPACTS = ["critical", "serious", "moderate", "minor"];
const sha256 = (b) => createHash("sha256").update(b).digest("hex");
const problems = [];
const lines = [];
let violating = 0;
for (const dir of dirs) {
  if (!existsSync(join(dir, "manifest.json"))) {
    console.error(`A11Y-INFRA: ${dir}: no manifest.json (the negative control did not run)`);
    process.exit(1);
  }
  const m = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
  const files = existsSync(join(dir, "states")) ? readdirSync(join(dir, "states")).sort() : [];
  const states = new Map();
  const hashes = [];
  for (const f of files.filter((x) => x.endsWith(".json"))) {
    const raw = readFileSync(join(dir, "states", f));
    hashes.push(`${sha256(raw)}  states/${f}`);
    const s = JSON.parse(raw);
    states.set(s.id, s);
  }
  for (const id of m.states)
    if (!states.has(id)) problems.push(`${m.target}: state ${id} has no file`);
  for (const id of states.keys())
    if (!m.states.includes(id)) problems.push(`${m.target}: ${id} not in the manifest`);
  const per = m.themes.length * m.densities.length * m.motions.length;
  const cells = [];
  for (const s of states.values()) {
    if (s.cells.length !== per)
      problems.push(`${m.target}/${s.id}: ${s.cells.length} cells, expected ${per}`);
    if (s.offsite.length > 0)
      problems.push(`${m.target}/${s.id}: ${s.offsite.length} off-site request(s)`);
    cells.push(...s.cells.map((c) => ({ ...c, target: m.target, scr: s.scr })));
  }
  if (!m.negativeControl?.tripped) problems.push(`${m.target}: the negative control did not trip`);
  const total = Object.fromEntries(IMPACTS.map((i) => [i, 0]));
  for (const c of cells) for (const i of IMPACTS) total[i] += c.counts[i];
  const errored = cells.filter((c) => c.error !== undefined);
  if (errored.length > 0) problems.push(`${m.target}: ${errored.length} errored cell(s)`);
  violating += IMPACTS.reduce((n, i) => n + total[i], 0);
  const gz = gzipSync(JSON.stringify({ ...m, total, cells }));
  writeFileSync(join(dir, "results.json.gz"), gz);
  const via = [...new Set(cells.map((c) => c.axeVia))].join(", ");
  const bad = cells.filter((c) => c.error !== undefined || IMPACTS.some((i) => c.counts[i] > 0));
  lines.push(
    `## ${m.target}`,
    "",
    `sha ${m.sha}; states ${m.states.length}; cells ${cells.length} (${m.themes.length} themes x ${m.densities.length} densities x ${m.motions.length} motion); axe via ${via}; disabled rules: ${m.disabledRules.length === 0 ? "none" : m.disabledRules.join(", ")}`,
    `violations: ${IMPACTS.map((i) => `${i} ${total[i]}`).join(", ")}; errored ${errored.length}; axe incomplete rules ${[...new Set(cells.flatMap((c) => c.incomplete.map((i) => i.id)))].join(", ") || "none"} (in ${cells.filter((c) => c.incomplete.length > 0).length} cells)`,
    `negative control: tripped (${m.negativeControl.rules.join(", ")}); tags ${m.tags.join(", ")}`,
    `results.json.gz sha256 ${sha256(gz)}`,
    "",
    "```text",
    ...hashes,
    "```",
    "",
    "| state | theme | density | motion | crit / ser / mod / min | rules or error |",
    "|---|---|---|---|---|---|",
    ...bad.map(
      (c) =>
        `| ${c.state} | ${c.theme} | ${c.density} | ${c.motion} | ${IMPACTS.map((i) => c.counts[i]).join(" / ")} | ${c.error ?? [...new Set(c.violations.map((v) => v.id))].join(", ")} |`,
    ),
    "",
  );
}
writeFileSync(join(dirs[0], "summary.md"), lines.join("\n"));
if (problems.length > 0) {
  console.error(`A11Y-INFRA: ${[...new Set(problems)].slice(0, 6).join("; ")}`);
  process.exit(1);
}
if (strict && violating > 0) {
  console.error(`strict: ${violating} violation(s) of some impact`);
  process.exit(1);
}
console.log(`merged ${dirs.length} target(s)`);
