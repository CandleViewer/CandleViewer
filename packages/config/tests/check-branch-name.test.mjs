import { describe, expect, it } from "vitest";
import { isValidBranchName } from "../../../scripts/check-branch-name.mjs";

describe("isValidBranchName", () => {
  const validCases = [
    "feat/of-42-footprint-cells",
    "fix/oms-19-sl-rounding",
    "chore/bump-playwright",
    "design/of-50-heatmap-tokens",
    "spike/webgl-footprint-bench",
    "hotfix/oms-77-fanout-race",
    "release/1.4.0",
    "train/20261019-1",
    "main",
  ];

  for (const name of validCases) {
    it(`accepts "${name}"`, () => {
      expect(isValidBranchName(name)).toBe(true);
    });
  }

  const invalidCases = ["my-work", "feature/no-prefix-match", "feat/", "", "  "];

  for (const name of invalidCases) {
    it(`rejects "${name}"`, () => {
      expect(isValidBranchName(name)).toBe(false);
    });
  }

  it("rejects non-string input", () => {
    expect(isValidBranchName(undefined)).toBe(false);
    expect(isValidBranchName(null)).toBe(false);
  });
});
