import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

const SCRIPT = fileURLToPath(new URL("../../scripts/storybook-a11y.mjs", import.meta.url));
const reports = mkdtempSync(path.join(tmpdir(), "cv-a11y-selftest-"));
afterAll(() => rmSync(reports, { recursive: true }));

/** A fixture story's result in the Vitest JSON report: a failed one carries axe's failure text. */
interface Story {
  readonly id: string;
  readonly status: "failed" | "passed";
  readonly failure?: string;
}

/** axe's failure text as the gate prints it: the element, then each rule as "<help> (<rule>)". */
const axeFailure = (element: string, rule: string) =>
  `Expected the HTML found at $('${element}') to have no violations:\n\nReceived:\n\n"${rule}"`;
const CONTRAST: Story = {
  id: "foundations-a11y-gate-fixture--low-contrast-button",
  status: "failed",
  failure: axeFailure("#a11y-gate-fixture", "Elements must meet minimum colour (color-contrast)"),
};
const ICON_ONLY: Story = {
  id: "foundations-icon-a11y-gate-fixture--icon-only-button-without-label",
  status: "failed",
  failure: axeFailure(
    "#icon-only-gate-fixture",
    "Buttons must have discernible text (button-name)",
  ),
};

let written = 0;
/** The self-test's verdict on a fixture run of `stories` that exited with `status`. */
function selftest(stories: readonly Story[], status = "1") {
  written += 1;
  const file = path.join(reports, `fixtures-${written}.json`);
  const results = stories.map(({ id, status: state, failure = "" }) => ({
    status: state,
    failureMessages: [failure],
    meta: { storyId: id },
  }));
  writeFileSync(file, JSON.stringify({ testResults: [{ assertionResults: results }] }));
  const run = spawnSync(process.execPath, [SCRIPT, "selftest", file, status], {
    encoding: "utf-8",
  });
  return { code: run.status, stderr: run.stderr };
}

describe("the a11y gate self-test (scripts/storybook-a11y.mjs selftest, CI-A11Y-003)", () => {
  it("passes when both fixtures failed the gate, each naming its rule and its element", () => {
    expect(selftest([CONTRAST, ICON_ONLY])).toEqual({ code: 0, stderr: "" });
  });

  it("keeps the E05-T03 contract on a run that has the contrast fixture alone", () => {
    expect(selftest([CONTRAST])).toEqual({ code: 0, stderr: "" });
  });

  it.each<[string, readonly Story[], string]>([
    [
      "the icon-only fixture passed (E05-T06 Gherkin: the axe story check must fail)",
      [CONTRAST, { ...ICON_ONLY, status: "passed", failure: "" }],
      "the unlabelled icon-only button did not fail",
    ],
    [
      "the icon-only fixture failed on another rule",
      [CONTRAST, { ...ICON_ONLY, failure: axeFailure("#icon-only-gate-fixture", "x (region)") }],
      "the unlabelled icon-only button's failure does not name (button-name)",
    ],
    [
      "the icon-only fixture failed on another element",
      [CONTRAST, { ...ICON_ONLY, failure: axeFailure("#other", "Buttons (button-name)") }],
      "the unlabelled icon-only button's failure does not name #icon-only-gate-fixture",
    ],
    ["the contrast fixture is missing", [ICON_ONLY], "the 2:1-contrast button did not fail"],
    [
      "any other fixture story passed",
      [CONTRAST, ICON_ONLY, { id: "foundations-later-fixture--story", status: "passed" }],
      "fixture story foundations-later-fixture--story did not fail",
    ],
  ])("fails when %s", (_, stories, problem) => {
    const { code, stderr } = selftest(stories);
    expect(code).toBe(1);
    expect(stderr).toContain(`a11y gate self-test: ${problem}\n`);
  });

  it("fails when the fixture run itself exited 0: the gate is blind", () => {
    const { code, stderr } = selftest([CONTRAST, ICON_ONLY], "0");
    expect(code).toBe(1);
    expect(stderr).toContain("a11y gate self-test: the fixture run passed: the gate is blind\n");
  });
});
