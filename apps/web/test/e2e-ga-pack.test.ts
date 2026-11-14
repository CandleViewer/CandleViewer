// @vitest-environment node
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AREAS,
  PACK_TAG,
  REASONS,
  gaps,
  greens,
  mapErrors,
  packTests,
  stories,
  storyTable,
  type PackTest,
} from "../e2e/support/gaPack";

/**
 * E49-Q01 (#1335) S1: the GA regression pack's coverage map is generated from the specs, so it cannot
 * drift from them (CI-E2E-003, CI-E2E-004 in `docs/ci-runbook.md` section 4). After tagging a test or
 * editing the gaps file, regenerate the page's table with `CV_GA_MAP_WRITE=1` and commit the result.
 */
const ROOT = resolve(import.meta.dirname, "../../..");
const PAGE = resolve(ROOT, "docs/qa/e49-ga-regression-pack.md");
const BEGIN = "<!-- ga-map:begin -->";
const END = "<!-- ga-map:end -->";
const read = (rel: string): string => readFileSync(resolve(ROOT, rel), "utf8");

const pack = packTests(ROOT, ["apps/web/e2e", "apps/desktop/e2e"]);
const all = stories(read("docs/plan/11-user-stories.md"));
const gapRows = gaps(read("docs/qa/e49-ga-regression-gaps.md"));
const page = readFileSync(PAGE, "utf8");
const nightly = greens(page);
const record = nightly.rows;

const T = { file: "a.spec.ts", title: "t", area: "auth", scenarios: [] };
const fake = (ids: string[]): PackTest => ({ ...T, stories: ids });
const must = (id: string, scenarios: readonly string[] = []) => ({
  id,
  priority: "Must",
  scenarios,
});
const row = (ids: string, date = "2026-11-04", reason = "unbuilt: no source"): string =>
  `| ${ids} | ${reason} | PROPOSED: none | PROPOSED: owner | ${date} |`;

describe("the GA regression pack's tags (CI-E2E-004)", () => {
  it("are on shipped tests only, each with one known area", () => {
    expect(pack.errors).toEqual([]);
    expect(pack.tests.length).toBeGreaterThan(0);
  });

  it("refuse a tagged test.only or describe title, and a conditional skip outside a test body", () => {
    const dir = mkdtempSync(join(tmpdir(), "ga-pack-"));
    const tag = "@ga-regression @ga-area-auth";
    writeFileSync(join(dir, "a.spec.ts"), `test.only("a ${tag}", f);\n`);
    writeFileSync(join(dir, "b.spec.ts"), `test.describe("b ${tag}", () => {});\n`);
    writeFileSync(join(dir, "c.spec.ts"), `test.skip(cond, "why");\ntest("c ${tag}", f);\n`);
    writeFileSync(
      join(dir, "d.spec.ts"),
      `test("d ${tag}", f);\ntest.describe("x", () => {\n  test.fail(cond);\n  test("e", f);\n});\n`,
    );
    const why = "a fixme, skip, fail or @flaky test is never in the pack";
    expect(packTests(dir, ["."]).errors).toEqual(
      ["a.spec.ts › a", "b.spec.ts › b", "c.spec.ts › c", "d.spec.ts › d"].map(
        (w) => `${w}: ${why}`,
      ),
    );
  });

  it("reads covers() past a test.step, which does not end the test", () => {
    const dir = mkdtempSync(join(tmpdir(), "ga-pack-"));
    const body = `test.step("s", f);\n  covers("US-ONB-004");`;
    writeFileSync(
      join(dir, "a.spec.ts"),
      `test("a @ga-regression @ga-area-auth", () => {\n  ${body}\n});\n`,
    );
    const { tests, errors } = packTests(dir, ["."]);
    expect(errors).toEqual([]);
    expect(tests.map((t) => t.stories)).toEqual([["US-ONB-004"]]);
  });

  it("refuse a fixme, skip or @flaky test, and a test with no known area", () => {
    const dir = mkdtempSync(join(tmpdir(), "ga-pack-"));
    const tag = "@ga-regression @ga-area-auth";
    writeFileSync(join(dir, "a.spec.ts"), `test.fixme(true, "x");\ntest("a ${tag}", f);\n`);
    writeFileSync(join(dir, "b.spec.ts"), `test("b @flaky ${tag}", f);\ntest("c ${PACK_TAG}", f);`);
    writeFileSync(join(dir, "c.spec.ts"), `test("d ${tag}", () => {\n  test.skip(x);\n});\n`);
    expect(packTests(dir, ["."]).errors).toEqual([
      "a.spec.ts › a: a fixme, skip, fail or @flaky test is never in the pack",
      "b.spec.ts › b: a fixme, skip, fail or @flaky test is never in the pack",
      `b.spec.ts › c: needs exactly one @ga-area-<slug> of ${AREAS.join(", ")}`,
      "c.spec.ts › d: a fixme, skip, fail or @flaky test is never in the pack",
    ]);
  });
});

describe("the GA regression pack's coverage map (CI-E2E-003)", () => {
  it("counts the Must stories by the leading priority token (18 section 1)", () => {
    expect(all).toHaveLength(259);
    expect(all.filter((s) => s.priority === "Must")).toHaveLength(184);
  });

  it("covers every Must story or names it in the gaps file, and the record names pack tests", () => {
    expect(nightly.errors).toEqual([]);
    expect(mapErrors(pack.tests, all, gapRows, record)).toEqual([]);
  });

  it("is the table the page holds", () => {
    const table = storyTable(pack.tests, all, record);
    const [head, rest] = page.split(BEGIN);
    const tail = rest?.split(END)[1];
    if (process.env["CV_GA_MAP_WRITE"] === "1" && tail !== undefined) {
      writeFileSync(PAGE, `${head}${BEGIN}\n\n${table}\n\n${END}${tail}`);
    }
    const held = readFileSync(PAGE, "utf8").split(BEGIN)[1]?.split(END)[0];
    expect(held?.trim()).toBe(table);
  });

  it("fails an uncovered Must story, a gaps row that names a covered one, and an unknown id", () => {
    const musts = ["US-ONB-001", "US-ONB-002"].map((id) => must(id));
    expect(mapErrors([fake(["US-ONB-001"])], musts, [], new Map())).toEqual([
      "US-ONB-002: a Must story neither covered nor in the gaps file",
    ]);
    expect(
      mapErrors([fake(["US-ONB-001"])], musts, gaps(row("`US-ONB-001` `US-ONB-002`")), new Map()),
    ).toEqual(["US-ONB-001: in the gaps file but a pack test covers it"]);
    expect(
      mapErrors([fake(["US-ONB-001", "US-ONB-999"])], musts, gaps(row("`US-ONB-002`")), new Map()),
    ).toEqual(["US-ONB-999: not a story heading"]);
    expect(mapErrors([], musts, gaps(row("`US-ONB-001` `US-ONB-002`", "soon")), new Map())).toEqual(
      ["gaps row US-ONB-001 US-ONB-002: the date is YYYY-MM-DD"],
    );
  });

  it("fails a short gaps row, an id in two rows, an id not of the story shape", () => {
    const musts = [must("US-ONB-001")];
    expect(
      mapErrors([], musts, gaps("| `US-ONB-001` | unbuilt: x |  | x | 2026-11-04 |"), new Map()),
    ).toEqual(["gaps row US-ONB-001: needs reason, risk acceptance, by, date"]);
    expect(
      mapErrors([], musts, gaps(`${row("`US-ONB-001`")}\n${row("`US-ONB-001`")}`), new Map()),
    ).toEqual(["US-ONB-001: in 2 gaps rows"]);
    expect(mapErrors([], musts, gaps(row("`US-ONB-001` `US-ONB-1`")), new Map())).toEqual([
      "US-ONB-1: not a story id",
    ]);
  });

  it("reads every row of a nightly record prettier pads, and fails a row it cannot read", () => {
    const tests = [
      { ...T, stories: [] },
      { ...T, title: "a longer title", stories: [] },
    ];
    const md = [
      "| Test                           | Greens |",
      "| ------------------------------ | ------ |",
      "| `a.spec.ts › t`                | 3      |",
      "| `a.spec.ts › a longer title`   | 11     |",
      "",
    ].join("\n");
    const read2 = greens(md);
    expect(read2.errors).toEqual([]);
    expect([...read2.rows]).toEqual([
      ["a.spec.ts › t", 3],
      ["a.spec.ts › a longer title", 11],
    ]);
    expect(mapErrors(tests, [], [], read2.rows)).toEqual([
      "nightly record a.spec.ts › a longer title: at most 10 greens",
    ]);
    expect(greens(`${md}`.replace("a longer title`  ", "t`               ")).errors).toEqual([
      "nightly record a.spec.ts › t: in two rows",
    ]);
    expect(greens("no table").errors).toEqual(["nightly record: no `| Test | Greens |` table"]);
    const bad = greens(md.replace("| 3      |", "| three  |"));
    expect(bad.errors).toEqual([
      "nightly record row | `a.spec.ts › t`                | three  |: not `<spec> › <title>` | n",
    ]);
  });

  it("reads E17's covers() ids without failing on the ones that are not stories", () => {
    const e17 = pack.tests.filter((t) => t.file.startsWith("apps/web/e2e/e17/"));
    expect(e17.flatMap((t) => t.scenarios)).toContain("US-MKT-005#Reconnect");
    expect(e17.flatMap((t) => t.stories)).not.toContain("US-MKT-005");
    expect(e17.flatMap((t) => t.stories).every((s) => /^US-[A-Z]+-\d{3}$/u.test(s))).toBe(true);
  });

  it("never covers a story by a scenario citation: it is partial, with a gaps row naming the rest", () => {
    const t = { ...fake([]), scenarios: ["US-MKT-005#Reconnect"] };
    const musts = [must("US-MKT-005", ["Subscribed", "Unsubscribe on last consumer", "Reconnect"])];
    const id = "`US-MKT-005`";
    const named = "partial: Subscribed and Unsubscribe on last consumer are not cited";
    expect(mapErrors([t], musts, [], new Map())).toEqual([
      "US-MKT-005: a Must story cited by scenario only, with no gaps row",
    ]);
    expect(mapErrors([t], musts, gaps(row(id, "2026-11-04", named)), new Map())).toEqual([]);
    const why = "US-MKT-005: cited by scenario only; its gaps row is partial and names";
    expect(
      mapErrors([t], musts, gaps(row(id, "2026-11-04", "partial: Subscribed only")), new Map()),
    ).toEqual([`${why} Subscribed, Unsubscribe on last consumer`]);
    expect(
      mapErrors([t], musts, gaps(row(id, "2026-11-04", `parked${named.slice(7)}`)), new Map()),
    ).toEqual([`${why} Subscribed, Unsubscribe on last consumer`]);
    const table = storyTable([t], musts, new Map());
    expect(table).toContain("US-MKT-005#Reconnect");
    expect(table).toContain("partial, candidate (0/10)");
  });

  it("fails a scenario the story does not have, and a reason outside the vocabulary", () => {
    const t = { ...fake(["US-ONB-001"]), scenarios: ["US-ONB-001#Nope"] };
    const musts = [must("US-ONB-001", ["Successful sign-in"]), must("US-ONB-002")];
    const prose = "the screen renders a stub";
    expect(
      mapErrors([t], musts, gaps(row("`US-ONB-002`", "2026-11-04", prose)), new Map()),
    ).toEqual([
      `gaps row US-ONB-002: the reason starts with one of ${REASONS.join(", ")}, then a colon`,
      "US-ONB-001#Nope: not a scenario of US-ONB-001",
    ]);
  });

  it("reads the scenarios under each story heading", () => {
    const mkt = all.find((s) => s.id === "US-MKT-005");
    expect(mkt?.scenarios).toEqual(["Subscribed", "Unsubscribe on last consumer", "Reconnect"]);
  });

  it("keeps a test a candidate until its tenth green nightly", () => {
    const t = fake(["US-ONB-001"]);
    const all1 = [must("US-ONB-001")];
    expect(storyTable([t], all1, new Map([["a.spec.ts › t", 9]]))).toContain("candidate (9/10)");
    expect(storyTable([t], all1, new Map([["a.spec.ts › t", 10]]))).toContain("in (1)");
    expect(mapErrors([t], all1, [], new Map([["a.spec.ts › u", 1]]))).toEqual([
      "nightly record a.spec.ts › u: no pack test has this name",
    ]);
  });
});
