import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { URL, fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, test, vi } from "vitest";
import * as modifier from "../src/vitest-flaky.mjs";
import { vitestPreset } from "../vitest.preset.mjs";

// E02-T10: the C-9.3 quarantine modifier, which the preset loads before every test file. These
// tests call it through `quarantine`, never as a literal call on it, test or describe: the report
// tool and tests/toolchain/pack.py read such a call in any test file as a real quarantine, with a
// ticket and a 10-working-day expiry, and these tests are permanent.
const quarantine = { it: it.flaky, test: test.flaky, describe: describe.flaky };

/** The labels of the quarantined bodies that ran: none may. */
const ran = [];
const never = (label) => () => {
  ran.push(label);
  throw new Error(`${label}: a quarantined test ran`);
};

describe("a quarantined test", () => {
  quarantine.it("a plain one", never("plain"));
  quarantine.test("one with a timeout", never("timeout"), 1_234);
  quarantine.it("one with options", { retry: 2 }, never("options"));
  quarantine.describe("a quarantined suite", () => {
    it("a test in it", never("suite"));
  });

  it("is skipped and tagged, keeps its options, and never runs", ({ task }) => {
    const [plain, timed, optioned, suite] = task.suite.tasks;
    // `mode: "skip"` is what every reporter counts as skipped; the tag is what --tags-filter reads.
    for (const quarantined of [plain, timed, optioned, suite, ...suite.tasks]) {
      expect(quarantined).toMatchObject({ mode: "skip", tags: [modifier.FLAKY_TAG] });
    }
    expect([plain.name, timed.timeout, optioned.retry]).toEqual(["a plain one", 1_234, 2]);
    expect(ran).toEqual([]);
  });

  it("is Vitest's own it, test and describe, it and test sharing one modifier", () => {
    expect(modifier.it).toBe(it);
    expect(modifier.test).toBe(test);
    expect(modifier.describe).toBe(describe);
    expect(it.flaky).toBe(test.flaky);
  });
});

describe("installFlaky", () => {
  const fn = () => {};

  it("forwards each call form with the test skipped and tagged, keeping its own tags", () => {
    const api = vi.fn();
    modifier.installFlaky(api);
    api.flaky("bare");
    api.flaky("a function", fn);
    api.flaky("a timeout", fn, 5);
    api.flaky("options", { retry: 1, tags: "slow" }, fn);
    api.flaky("a tag list", { tags: ["a", "b"] });
    expect(api.mock.calls).toEqual([
      ["bare", { skip: true, tags: ["flaky"] }, undefined],
      ["a function", { skip: true, tags: ["flaky"] }, fn],
      ["a timeout", { timeout: 5, skip: true, tags: ["flaky"] }, fn],
      ["options", { retry: 1, skip: true, tags: ["slow", "flaky"] }, fn],
      ["a tag list", { skip: true, tags: ["a", "b", "flaky"] }, undefined],
    ]);
  });

  it("installs once: a second install keeps the first modifier", () => {
    const api = vi.fn();
    modifier.installFlaky(api);
    const first = api.flaky;
    modifier.installFlaky(api);
    expect(api.flaky).toBe(first);
    modifier.installFlaky(test); // the preset's install is already in place
    expect(test.flaky).toBe(quarantine.test);
  });

  it("refuses an API that already has another flaky, as a Vitest release could ship", () => {
    const api = Object.assign(vi.fn(), { flaky: vi.fn() });
    expect(() => modifier.installFlaky(api)).toThrow(/already has a `flaky`/);
  });
});

describe("the shared preset", () => {
  it("loads the modifier before every test file and declares its tag", () => {
    const setup = fileURLToPath(new URL("../src/vitest-flaky.mjs", import.meta.url));
    expect(vitestPreset.test.setupFiles).toEqual([setup]);
    expect(vitestPreset.test.tags.map(({ name }) => name)).toEqual([modifier.FLAKY_TAG]);
  });
});

describe("tools/ci/flaky_quarantine_report.py", () => {
  const TOOL = fileURLToPath(
    new URL("../../../tools/ci/flaky_quarantine_report.py", import.meta.url),
  );
  // The modifier's call, spelled out at run time for the reason at the top of this file.
  const CALL = `${["it", "flaky"].join(".")}(`;
  let dir;
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  /** The tool's exit status and report for a tree that holds one test file, `source`. */
  const scan = (source) => {
    dir = mkdtempSync(path.join(tmpdir(), "cv-flaky-"));
    writeFileSync(path.join(dir, "case.test.ts"), source);
    const args = ["-I", TOOL, "--repo-root", dir, "--out", "report.json"];
    const { status } = spawnSync("python", args, { encoding: "utf8", timeout: 60_000 });
    return { status, report: JSON.parse(readFileSync(path.join(dir, "report.json"), "utf8")) };
  };

  it("lists a quarantine written with the modifier, with the ticket on the line above", () => {
    const source = [
      'describe("x", () => {',
      "  // ticket: GH-1 quarantined: 2026-10-28",
      `  ${CALL}"y", async () => {});`,
      "});",
    ].join("\n");
    expect(scan(source)).toEqual({
      status: 0,
      report: {
        quarantined: [{ path: "case.test.ts", line: 3, ticket: "GH-1" }],
        unreferenced_count: 0,
      },
    });
  });

  it("fails on one with no ticket", () => {
    expect(scan(`${CALL}"y", () => {});`)).toMatchObject({
      status: 1,
      report: { unreferenced_count: 1 },
    });
  });
});
