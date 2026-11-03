// E10-Q03 (#302) driver B: merge <dir>/checks/*.json (written by e10-q03-manual.qa.ts) into <dir>/results.json.gz
// (every record of every check) and <dir>/summary.md (headline counts per check, the sha256 of every file and
// of the greyscale and designer captures, and the records that failed).
// Usage: node e10-q03-manual-merge.mjs [--strict] <dir>   Exit 1 on a missing check or control file, or (with
// --strict) any failed record.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const args = process.argv.slice(2);
const strict = args.includes("--strict");
const dir = args.find((a) => a !== "--strict");
const sha256 = (b) => createHash("sha256").update(b).digest("hex");
const REQUIRED = [
  "keyboard-walk",
  "keyboard-esc",
  "keyboard-overlay-focus",
  "zoom",
  "greyscale",
  "names",
  "token-audit",
  "announce",
  "control-trap",
  "control-clip-hue",
  "control-focus",
];
const checks = join(dir, "checks");
const problems = [];
const lines = [];
const all = [];
const hashes = [];
for (const name of REQUIRED) {
  const f = join(checks, `${name}.json`);
  if (!existsSync(f)) {
    problems.push(`${name}: no result file`);
    continue;
  }
  const raw = readFileSync(f);
  hashes.push(`${sha256(raw)}  checks/${name}.json`);
  const c = JSON.parse(raw);
  const pass = c.rows.filter((r) => r.pass && !r.skip).length;
  const skip = c.rows.filter((r) => r.skip).length;
  const bad = c.rows.filter((r) => !r.pass && !r.skip);
  if ((c.offsite ?? []).length > 0)
    problems.push(`${name}: ${c.offsite.length} off-site request(s)`);
  all.push(...c.rows.map((r) => ({ file: name, ...r })));
  lines.push(`| ${name} | ${c.rows.length} | ${pass} | ${bad.length} | ${skip} | ${c.ms} |`);
  for (const r of bad)
    problems.push(`${name}: ${r.check} [${r.state}/${r.theme}/${r.density}]: ${r.detail}`);
}
for (const sub of ["greyscale", "designer"]) {
  const d = join(checks, sub);
  if (existsSync(d))
    for (const f of readdirSync(d).sort())
      hashes.push(`${sha256(readFileSync(join(d, f)))}  checks/${sub}/${f}`);
}
const gz = gzipSync(JSON.stringify({ sha: process.env.A11Y_SHA ?? "unset", records: all }));
writeFileSync(join(dir, "results.json.gz"), gz);
const out = [
  `sha ${process.env.A11Y_SHA ?? "unset"}; records ${all.length}; results.json.gz sha256 ${sha256(gz)}`,
  "",
  "| check file | records | pass | fail | not applicable / not built | ms |",
  "|---|---|---|---|---|---|",
  ...lines,
  "",
  "```text",
  ...hashes,
  "```",
  "",
  ...(problems.length === 0 ? ["no failed record"] : ["failed:", ...problems.map((p) => `- ${p}`)]),
];
writeFileSync(join(dir, "summary.md"), out.join("\n"));
if (problems.length > 0 && (strict || problems.some((p) => p.includes("no result file")))) {
  console.error(`A11Y-INFRA/fail: ${problems.slice(0, 8).join("; ")}`);
  process.exit(1);
}
console.log(`merged ${REQUIRED.length} check files, ${all.length} records`);
