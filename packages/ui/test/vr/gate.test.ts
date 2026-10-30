import { describe, expect, it } from "vitest";
import { assertModeAllowed, assertUpdateAllowed, requestsUpdate } from "../../vr/gate.js";

/** `pnpm vr:update`'s argv as Playwright's CLI process sees it. */
const UPDATE = [
  "node",
  "playwright",
  "test",
  "-c",
  "vr/playwright.config.ts",
  "--update-snapshots=changed",
];
const COMPARE = UPDATE.slice(0, -1);

describe("the vr:update gate", () => {
  it.each([
    [["--update-snapshots=changed"], true],
    [["--update-snapshots=all"], true],
    [["--update-snapshots", "missing"], true],
    [["--update-snapshots"], true],
    [["-u"], true],
    [["-u", "vr.spec.ts"], true],
    // Short flags in a cluster: -x is a switch, -u takes the rest of the cluster as its mode.
    [["-xu"], true],
    [["-uall"], true],
    [["-xuall"], true],
    [["-xu", "missing"], true],
    [["--update-snapshots=none"], false],
    [["-u", "none"], false],
    [["-unone"], false],
    // -c, -g, -G and -j take the rest of the cluster as their value: no u flag there.
    [["-gu"], false],
    [["-cu.ts"], false],
    [["-xju"], false],
    [["--shard=1/4"], false],
  ])("reads %j as an update: %s", (args, update) => {
    expect(requestsUpdate(["node", "playwright", "test", ...args])).toBe(update);
  });

  it("refuses an update in CI that the dispatch input did not ask for, naming the way", () => {
    for (const env of [
      { CI: "true" },
      { CI: "1", VR_UPDATE: "" },
      { CI: "true", VR_UPDATE: "true" },
    ]) {
      expect(() => assertUpdateAllowed(UPDATE, env)).toThrow(
        /refuses to run in CI.*gh workflow run _job-a11y\.yml --ref <branch> -f vr_update=true/,
      );
    }
    expect(() =>
      assertUpdateAllowed(["node", "playwright", "test", "-u"], { CI: "true" }),
    ).toThrow();
  });

  it("refuses the mode Playwright resolved, whatever spelling asked for it, in CI without the dispatch", () => {
    for (const mode of ["all", "changed", "missing"]) {
      expect(() => assertModeAllowed(mode, { CI: "true" }), mode).toThrow(/refuses to run in CI/);
      expect(() => assertModeAllowed(mode, { CI: "true", VR_UPDATE: "1" }), mode).not.toThrow();
      expect(() => assertModeAllowed(mode, {}), mode).not.toThrow();
    }
    expect(() => assertModeAllowed("none", { CI: "true" })).not.toThrow();
  });

  it("lets the dispatch run update, a local run update, and any run compare", () => {
    expect(() => assertUpdateAllowed(UPDATE, { CI: "true", VR_UPDATE: "1" })).not.toThrow();
    expect(() => assertUpdateAllowed(UPDATE, {})).not.toThrow();
    expect(() => assertUpdateAllowed(UPDATE, { CI: "" })).not.toThrow();
    expect(() => assertUpdateAllowed(COMPARE, { CI: "true" })).not.toThrow();
  });
});
