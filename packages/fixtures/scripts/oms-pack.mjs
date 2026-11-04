// E29-Q01 (#844) OMS scenario pack check against the black-box plan's traceability table (section 9
// of docs/qa/e29-oms-test-plan.md), the way accounts-pack.mjs reads E27's section 9.3. Pure Node, no
// network, no dependency beyond accounts-pack.mjs's schema subset. In CI it runs through the package
// `lint` script: scripts/verify.mjs calls `checkOmsPack`, and test/oms-pack-plan.test.mjs runs the
// real pack against the real plan. What each scenario's files hold is checked in Python, by the
// loader (services/api/tests/_oms_fixtures.py). See oms/README.md, "Checks".
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { assertSupportedSchema, validateSchema } from "./accounts-pack.mjs";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
export const OMS_DIR = join(packageRoot, "oms");
/** The plan, two levels above this package: CI's lint job checks out the whole repository. */
export const OMS_PLAN_FILE = join(packageRoot, "..", "..", "docs", "qa", "e29-oms-test-plan.md");
/** The Scenario cell of the one row with no folder: S11, a unit-level contract (section 9). */
export const NO_FIXTURE = "none";

const HEADER = ["Scenario", "Rules", "Cases", "Evidence", "Consumers"];
const RULES = Array.from({ length: 11 }, (_, i) => `S${i + 1}`);
const CLASSES = ["recorded", "docs-transcribed", "derived"];
const IS = {
  Rules: (t) => RULES.includes(t),
  Cases: (t) => /^E29-TC-\d{3}$/u.test(t),
  Consumers: (t) => /^E29-[A-Z]\d{2}$/u.test(t),
};

/** A table row's cells, trimmed; a pipe escaped as `\|` stays in its cell. */
function cellsOf(line) {
  const inner = line
    .trim()
    .replace(/^\|/u, "")
    .replace(/(?<!\\)\|$/u, "");
  return inner.split(/(?<!\\)\|/u).map((cell) => cell.trim());
}

function planRow(cells) {
  const name = /^`([a-z][a-z0-9_]*)`$/u.exec(cells[0])?.[1];
  if (cells.length !== HEADER.length || name === undefined) {
    return { problem: `plan: section 9 row "${cells[0]}" is not a \`name\` and four cells` };
  }
  const split = (cell) => cell.split(/\s*,\s*/u);
  const lists = { Rules: cells[1] === "none" ? [] : split(cells[1]), Cases: split(cells[2]) };
  lists.Consumers = split(cells[4]);
  for (const [what, ids] of Object.entries(lists)) {
    const bad = ids.find((id) => !IS[what](id));
    if (bad !== undefined) return { problem: `plan: ${name}'s ${what} cell holds "${bad}"` };
    if (new Set(ids).size !== ids.length)
      return { problem: `plan: ${name}'s ${what} cell repeats an id` };
  }
  const evidence = cells[3];
  if (!(name === NO_FIXTURE ? evidence === "none" : CLASSES.includes(evidence))) {
    return { problem: `plan: ${name}'s Evidence cell holds "${evidence}"` };
  }
  const { Rules: rules, Cases: cases, Consumers: consumers } = lists;
  return { row: { name, rules, cases, evidence, consumers } };
}

/**
 * Section 9's table in the plan's `markdown`: `{ rows, problems }`, rows `{ name, rules, cases,
 * evidence, consumers }` in table order. A missing section, another header, a row of another width,
 * an id that is no rule, case or ticket (a range included), a repeat, an Evidence cell of no class
 * or a rule no row names is a problem.
 */
export function readPlanTable(markdown) {
  const lines = markdown.split(/\r?\n/u);
  const start = lines.findIndex((line) => /^## 9\. /u.test(line));
  const end = lines.findIndex((line, i) => i > start && /^#{1,3} /u.test(line));
  const section = start < 0 ? [] : lines.slice(start + 1, end < 0 ? undefined : end);
  const [header, rule, ...body] = section.filter((l) => l.startsWith("|")).map(cellsOf);
  if (header?.join("|") !== HEADER.join("|") || !rule?.every((c) => /^:?-{3,}:?$/u.test(c))) {
    return { rows: [], problems: [`plan: no section 9 table headed ${HEADER.join(" | ")}`] };
  }
  const problems = [];
  const rows = [];
  for (const { row, problem } of body.map(planRow)) {
    if (problem !== undefined) problems.push(problem);
    else if (rows.some((r) => r.name === row.name)) problems.push(`plan: ${row.name} has two rows`);
    else rows.push(row);
  }
  if (rows.length === 0) problems.push("plan: section 9's table has no rows");
  for (const id of RULES.filter((r) => !rows.some((row) => row.rules.includes(r)))) {
    problems.push(`plan: rule ${id} has no row in section 9`);
  }
  return { rows, problems };
}

function listProblems(name, field, listed, planned) {
  if (listed.join() === planned.join()) return [];
  const lacks = planned.filter((x) => !listed.includes(x));
  const adds = listed.filter((x) => !planned.includes(x));
  const diff = [
    lacks.length > 0 && `lacks ${lacks.join(", ")}`,
    adds.length > 0 && `adds ${adds.join(", ")}`,
  ];
  const what = diff.filter(Boolean).join("; ") || "the same ids in another order or repeated";
  return [`${name}: ${field} differ from the plan's section 9 row (${what})`];
}

/** A scenario folder against its row: the schema, its name, then Rules, Cases, Evidence, Consumers. */
function checkFolder(name, manifest, row, schema) {
  const errors = validateSchema(schema, manifest).map((e) => `${name}: ${e}`);
  if (errors.length > 0) return errors;
  const problems = [];
  if (manifest.scenario !== name)
    problems.push(`${name}: scenario "${manifest.scenario}" is not its directory name`);
  for (const field of ["rules", "cases", "consumers"]) {
    problems.push(...listProblems(name, field, manifest[field], row[field]));
  }
  if (manifest.evidence !== row.evidence) {
    problems.push(`${name}: evidence "${manifest.evidence}" is not the plan's "${row.evidence}"`);
  }
  return problems;
}

/**
 * The pack at `dir` against the plan's `markdown`: `{ problems, pending }`, problems as `<where>:
 * <what>`. A folder with no row fails, and so does a row that disagrees with its folder; a row with
 * no folder yet is pending (a `recorded` row waits for E29-K01's findings PR); the no-fixture row's
 * folder test is skipped, its Rules and Cases cells still read. No problem means the pack is sound.
 */
export function checkOmsPack(dir = OMS_DIR, { plan }) {
  let schema;
  try {
    schema = JSON.parse(readFileSync(join(dir, "manifest.schema.json"), "utf8"));
    assertSupportedSchema(schema);
  } catch (error) {
    return { problems: [`manifest.schema.json: ${error.message}`], pending: [] };
  }
  const { rows, problems } = readPlanTable(plan);
  const known = new Set([...plan.matchAll(/^\| (E29-TC-\d{3}) \|/gmu)].map((m) => m[1]));
  if (known.size === 0)
    problems.push("plan: no case rows (| E29-TC-nnn |) to check section 9 against");
  for (const { name, cases } of known.size === 0 ? [] : rows) {
    for (const id of cases.filter((c) => !known.has(c)))
      problems.push(`plan: ${name}'s case ${id} is no case row of the plan`);
  }
  const folders = readdirSync(dir)
    .sort()
    .filter((entry) => !/^[_.]/u.test(entry) && statSync(join(dir, entry)).isDirectory());
  for (const name of folders) {
    let manifest;
    try {
      manifest = JSON.parse(readFileSync(join(dir, name, "manifest.json"), "utf8"));
    } catch (error) {
      problems.push(
        `${name}: ${error.code === "ENOENT" ? "no manifest.json" : "manifest.json is not JSON"}`,
      );
      continue;
    }
    const row = rows.find((r) => r.name === name);
    if (name === NO_FIXTURE)
      problems.push(`${name}: the name of the plan's no-fixture row, not a scenario`);
    else if (row === undefined) problems.push(`${name}: no section 9 row names it`);
    else problems.push(...checkFolder(name, manifest, row, schema));
  }
  const pending = rows.filter((r) => r.name !== NO_FIXTURE && !folders.includes(r.name));
  return { problems, pending: pending.map(({ name, evidence }) => ({ name, evidence })) };
}
