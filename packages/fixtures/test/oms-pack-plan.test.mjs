import { afterEach, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PLAN_FILE } from "../scripts/accounts-pack.mjs";
import { OMS_DIR, OMS_PLAN_FILE, checkOmsPack, readPlanTable } from "../scripts/oms-pack.mjs";
import { runVerify } from "../scripts/verify.mjs";

// E29-Q01 (#844): the OMS scenario pack against section 9 of the black-box plan
// (docs/qa/e29-oms-test-plan.md): the real pack against the real plan, then planted failures.
const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const PLAN = readFileSync(OMS_PLAN_FILE, "utf8");
const ROWS = readPlanTable(PLAN).rows;
const HEAD =
  "## 9. T\n\n| Scenario | Rules | Cases | Evidence | Consumers |\n| --- | --- | --- | --- | --- |";
const table = (...rows) => [HEAD, ...rows, "", "## 10. Next"].join("\n");
const ROW = "| `ws_x` | S4 | E29-TC-202 | derived | E29-Q02 |";
const PENDING = { name: "error_10001_duplicate_id", evidence: "recorded" };

/** The plan with one cell of one scenario's row replaced. */
function planWith(name, cell, value) {
  const line = PLAN.split("\n").find((l) => l.startsWith(`| \`${name}\` |`));
  const cells = line.split(" | ");
  const at = ["rules", "cases", "evidence", "consumers"].indexOf(cell) + 1;
  cells[at] = cell === "consumers" ? `${value} |` : value;
  return PLAN.replace(line, cells.join(" | "));
}

describe("section 9 of the plan", () => {
  it("reads as one row of five cells per scenario, every rule S1 to S11 named", () => {
    expect(readPlanTable(PLAN).problems).toEqual([]);
    const row = ROWS.find((r) => r.name === "ws_duplicate_exec");
    expect([row.rules, row.cases.length, row.evidence]).toEqual([["S4"], 4, "derived"]);
    const none = ROWS.find((r) => r.name === "none");
    expect(none).toMatchObject({ rules: ["S11"], cases: ["E29-TC-457"], evidence: "none" });
  });

  it.each([
    ["no section 9", "# a plan\n", "no section 9 table"],
    ["another header", table(ROW).replace("Consumers", "Owners"), "no section 9 table"],
    ["no rows", table(), "section 9's table has no rows"],
    ["a row of four cells", table("| `ws_x` | S4 | E29-TC-202 | derived |"), "four cells"],
    ["a rule that does not exist", table(ROW.replace("S4", "S12")), 'Rules cell holds "S12"'],
    ["a case range", table(ROW.replace("202", "202–205")), 'Cases cell holds "E29-TC-202–205"'],
    ["a repeated id", table(ROW.replace("S4", "S4, S4")), "Rules cell repeats an id"],
    ["a class of no kind", table(ROW.replace("derived", "copied")), 'Evidence cell holds "copied"'],
    ["a repeated name", table(ROW, ROW), "ws_x has two rows"],
    ["a rule no row names", table(ROW), "rule S1 has no row in section 9"],
    ["a table in the last section", table(ROW).replace("\n## 10. Next", ""), "rule S1 has no row"],
  ])("fails %s", (_, markdown, problem) => {
    expect(readPlanTable(markdown).problems.join("\n")).toContain(problem);
  });
});

describe("the pack against the plan", () => {
  let sandbox;
  const oms = (...parts) => join(sandbox, "oms", ...parts);
  const edit = (name, change) => {
    const manifest = JSON.parse(readFileSync(oms(name, "manifest.json"), "utf8"));
    change(manifest);
    writeFileSync(oms(name, "manifest.json"), JSON.stringify(manifest, null, 2));
  };
  const check = (plan = PLAN) => checkOmsPack(oms(), { plan });
  const copyPack = () => {
    sandbox = mkdtempSync(join(tmpdir(), "oms-pack-plan-"));
    cpSync(OMS_DIR, oms(), { recursive: true });
  };
  afterEach(() => sandbox && rmSync(sandbox, { recursive: true, force: true }));

  it("holds: every folder matches its row, and only the recorded row is pending", () => {
    expect(checkOmsPack(OMS_DIR, { plan: PLAN })).toEqual({ problems: [], pending: [PENDING] });
  });

  it("is in the lint gate, and the plan is an input of lint and the tests", () => {
    const { omsProblems, omsPending } = runVerify();
    expect({ omsProblems, omsPending }).toEqual({ omsProblems: [], omsPending: [PENDING] });
    const { tasks } = JSON.parse(readFileSync(join(packageRoot, "turbo.json"), "utf8"));
    for (const task of ["lint", "test", "test:cov"]) {
      expect(tasks[task].inputs).toContain("$TURBO_ROOT$/docs/qa/e29-oms-test-plan.md");
    }
    expect(OMS_PLAN_FILE).toBe(join(packageRoot, "..", "..", "docs", "qa", "e29-oms-test-plan.md"));
  });

  it("fails a folder no row names", () => {
    copyPack();
    expect(check().problems).toEqual([]); // the copy is sound, so what follows is the plant
    cpSync(oms("ws_partial_fill"), oms("zz_unplanned"), { recursive: true });
    edit("zz_unplanned", (m) => (m.scenario = "zz_unplanned"));
    expect(check().problems).toEqual(["zz_unplanned: no section 9 row names it"]);
  });

  it.each([
    ["rules", "S4", "rules differ from the plan's section 9 row (adds S5)"],
    [
      "rules",
      "S5, S4",
      "rules differ from the plan's section 9 row (the same ids in another order or repeated)",
    ],
    [
      "cases",
      `${ROWS[4].cases.slice(0, -1)}, E29-TC-001`,
      "cases differ from the plan's section 9 row (lacks E29-TC-001; adds E29-TC-810)",
    ],
    ["evidence", "docs-transcribed", 'evidence "derived" is not the plan\'s "docs-transcribed"'],
  ])("fails a row whose %s cell disagrees with its folder", (cell, value, problem) => {
    copyPack();
    expect(ROWS[4].name).toBe("ws_partial_fill");
    expect(check(planWith("ws_partial_fill", cell, value)).problems).toEqual([
      `ws_partial_fill: ${problem}`,
    ]);
  });

  it("fails a derived file with no `derived_from`, and a scenario not named as its folder", () => {
    copyPack();
    edit("ws_partial_fill", (m) => delete m.files["frames.jsonl"].derived_from);
    edit("ws_cancel_race", (m) => (m.scenario = "other"));
    const problems = check().problems;
    expect(problems).toHaveLength(2);
    expect(problems[0]).toMatch(/^ws_cancel_race: scenario "other" is not its directory name/);
    expect(problems[1]).toMatch(/^ws_partial_fill: .*missing required property "derived_from"/);
  });

  it("fails a folder with no manifest, a manifest that is no JSON, and a folder named `none`", () => {
    copyPack();
    rmSync(oms("ws_cancel_race", "manifest.json"));
    writeFileSync(oms("ws_partial_fill", "manifest.json"), "{");
    cpSync(oms("ws_amend_reject"), oms("none"), { recursive: true });
    expect(check().problems).toEqual([
      "none: the name of the plan's no-fixture row, not a scenario",
      "ws_cancel_race: no manifest.json",
      "ws_partial_fill: manifest.json is not JSON",
    ]);
  });

  it("leaves a row with no folder pending, and reads the no-fixture row's cells without a folder", () => {
    copyPack();
    rmSync(oms("rest_order_history"), { recursive: true });
    const { problems, pending } = check();
    expect([problems, pending.map((p) => p.name)]).toEqual([
      [],
      ["rest_order_history", PENDING.name],
    ]);
    expect(check(planWith("none", "rules", "none")).problems).toEqual([
      "plan: rule S11 has no row in section 9",
    ]);
    expect(check(planWith("none", "cases", "E29-TC-999")).problems).toEqual([
      "plan: none's case E29-TC-999 is no case row of the plan",
    ]);
    expect(check(table(ROW)).problems.join("\n")).toContain("no case rows");
  });

  it("fails closed when the pack has no readable schema", () => {
    copyPack();
    const { problems } = checkOmsPack(oms("missing"), { plan: PLAN });
    expect(problems[0]).toMatch(/^manifest\.schema\.json: ENOENT/);
  });

  it(
    "makes the lint gate exit 1 on a planted row, naming the folder and the cell",
    { timeout: 30_000 },
    () => {
      copyPack();
      const planFile = join(sandbox, "plan.md");
      writeFileSync(planFile, planWith("ws_partial_fill", "evidence", "docs-transcribed"));
      const verify = join(packageRoot, "scripts", "verify.mjs");
      const run = () =>
        execFileSync("node", [verify, packageRoot, PLAN_FILE, planFile], { stdio: "pipe" });
      expect(run).toThrow(
        /oms\/ws_partial_fill: evidence "derived" is not the plan's "docs-transcribed"/,
      );
      expect(runVerify(packageRoot, PLAN_FILE, join(sandbox, "none.md")).omsProblems).toEqual([
        "the OMS pack or plan cannot be read (ENOENT)",
      ]);
    },
  );
});
