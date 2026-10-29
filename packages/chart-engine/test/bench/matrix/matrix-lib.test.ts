import { describe, expect, it } from "vitest";
import { DONE_GRACE_MS, cellsComplete } from "../../../bench/matrix/matrix-lib.mjs";

describe("cellsComplete", () => {
  const cell = (scenario: string) => ({ kind: "cell", scenario });

  it("is true once every requested scenario has a cell", () => {
    expect(cellsComplete([cell("B1"), cell("B9")], ["B1", "B9"])).toBe(true);
  });

  it("is false while a requested scenario is missing", () => {
    expect(cellsComplete([cell("B1")], ["B1", "B9"])).toBe(false);
  });

  it("ignores results that are not cells", () => {
    const results = [cell("B1"), { kind: "gl-unavailable", scenario: "B9" }];
    expect(cellsComplete(results, ["B1", "B9"])).toBe(false);
  });

  it("is false for an empty request", () => {
    expect(cellsComplete([cell("B1")], [])).toBe(false);
  });

  it("waits a bounded grace for the page's own /done", () => {
    expect(DONE_GRACE_MS).toBe(30_000);
  });
});
