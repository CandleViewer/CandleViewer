// Guard logic: every wall-clock bound in a `*.perf.test.ts` goes through `budget(<spec>)` from the
// runner calibration (perf-calibration.mjs), so a new perf test cannot skip it. Each perf-owning
// package runs it over its own test tree from a unit-project test (so editing a perf file re-runs
// it), and packages/config keeps the matcher's self-tests.
//
// Scope: it checks the `expect(...).toBeLessThan*` / `toBeGreaterThan*` forms only. Other
// assertion styles (`expect(x < 5)`, `toBeCloseTo`, `assert`, hand-rolled `if`) are not seen, so
// write wall-clock bounds in the checked forms. A comparison that is not a wall-clock bound
// carries a `// budget-exempt: <reason>` comment on the line above its statement, with a reason
// from EXEMPT_REASONS.
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

export const EXEMPT_REASONS = ["ratio"]; // a dimensionless comparison of two measurements in one process

const BOUND = /\.(toBeLessThan|toBeLessThanOrEqual|toBeGreaterThan|toBeGreaterThanOrEqual)\(\s*/g;
export const GOOD_UPPER = /^budget\(\s*(?:[0-9][0-9._]*|[A-Z][A-Z0-9_]*)\s*\)\s*(?:,\s*)?\)/; // unambiguous: no ReDoS

/** The bounds in `source` that skip `budget(<literal or SPEC_CONST>)` and carry no allowed exemption. */
export function bareBounds(source) {
  const lines = source.split("\n");
  const bare = [];
  for (const m of source.matchAll(BOUND)) {
    const start = (m.index ?? 0) + m[0].length;
    const rest = source.slice(start, start + 256); // a bound's argument is short; caps the regex input
    const upper = m[1].startsWith("toBeLessThan");
    if (upper ? GOOD_UPPER.test(rest) : /^0\s*\)/.test(rest)) continue; // `> 0` only guards a dead clock
    let at = source.slice(0, m.index).split("\n").length - 1;
    while (at > 0 && (lines[at] ?? "").trim().startsWith(".")) at -= 1; // a chain's statement start
    const above = (lines[at - 1] ?? "").trim();
    const reason = /^\/\/ budget-exempt: (\w+)/.exec(above)?.[1];
    if (reason !== undefined && EXEMPT_REASONS.includes(reason)) continue;
    bare.push(`${at + 1}: ${(lines[at] ?? "").trim()}`);
  }
  return bare;
}

/** Every `*.perf.test.ts` under `dir`, recursively (absolute paths, sorted). */
export function perfTestFiles(dir) {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "dist") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...perfTestFiles(full));
    else if (entry.name.endsWith(".perf.test.ts")) found.push(full);
  }
  return found.sort();
}

/** The perf test files under `dir` and, per file, its bare bounds (`<file>:<line>: <statement>`). */
export function scanPerfTests(dir) {
  const files = perfTestFiles(dir);
  const offenders = files.flatMap((file) =>
    bareBounds(readFileSync(file, "utf8")).map((b) => `${path.relative(dir, file)}:${b}`),
  );
  return { files: files.map((f) => path.relative(dir, f)), offenders };
}
