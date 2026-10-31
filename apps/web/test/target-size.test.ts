// E47-S05 (#1319), Gherkin "Targets meet the minimum or are registered exceptions" (WCAG 2.5.8): the
// rule the Playwright check applies to measured boxes, and the exception register it reads.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parseExceptionRegister, targetViolations, type TargetBox } from "../e2e/a11y/targetSize";

const box = (
  id: string,
  x: number,
  y: number,
  w: number,
  h: number,
  exempt?: TargetBox["exempt"],
): TargetBox => (exempt === undefined ? { id, x, y, w, h } : { id, x, y, w, h, exempt });

describe("targetViolations", () => {
  it("passes a 24 x 24 control and a larger one", () => {
    expect(targetViolations([box("a", 0, 0, 24, 24), box("b", 24, 0, 80, 32)])).toEqual([]);
  });

  it("fails a 23 px control that touches another target", () => {
    const v = targetViolations([box("small", 0, 0, 23, 24), box("next", 23, 0, 40, 24)]);
    expect(v).toEqual([{ id: "small", w: 23, h: 24, crowdedBy: "next" }]);
  });

  it("passes a small control with 24 px of clear space (the spacing arm)", () => {
    // Centre (10, 10), circle radius 12: the neighbour starts 30 px away.
    expect(targetViolations([box("small", 0, 0, 20, 20), box("far", 40, 0, 40, 24)])).toEqual([]);
  });

  it("measures the circle from the centre, so a 20 px box needs 2 px of gap and no less", () => {
    expect(targetViolations([box("s", 0, 0, 20, 20), box("n", 21, 0, 40, 24)])).toHaveLength(1);
    expect(targetViolations([box("s", 0, 0, 20, 20), box("n", 22, 0, 40, 24)])).toEqual([]);
  });

  it("fails two small controls whose circles intersect, and passes them 24 px centre to centre", () => {
    const near = [box("p", 0, 0, 16, 16), box("q", 20, 0, 16, 16)];
    expect(targetViolations(near).map((v) => v.id)).toEqual(["p", "q"]);
    expect(targetViolations([box("p", 0, 0, 16, 16), box("q", 24, 0, 16, 16)])).toEqual([]);
  });

  it("catches a short, wide control (one axis under 24)", () => {
    expect(targetViolations([box("bar", 0, 0, 200, 17), box("row", 0, 18, 200, 24)])).toHaveLength(
      1,
    );
  });

  it("exempts an inline or user-agent control but still counts it as a neighbour", () => {
    expect(targetViolations([box("link", 0, 0, 60, 14, "inline")])).toEqual([]);
    const v = targetViolations([box("link", 0, 0, 60, 14, "inline"), box("btn", 0, 10, 20, 20)]);
    expect(v.map((x) => x.id)).toEqual(["btn"]);
  });
});

const REGISTER = resolve(
  import.meta.dirname,
  "../../../docs/qa/a11y/e47-target-size-exceptions.md",
);

describe("parseExceptionRegister", () => {
  it("reads id, screen, selector and alternative from the table", () => {
    const md = [
      "| Id | Screen | Match | Size | Why | Alternative | Owner |",
      "| --- | --- | --- | --- | --- | --- | --- |",
      "| TS-01 | R-203 | `a.dense` | 20x20 | Dense cell | Table view of the same rows | E22 |",
    ].join("\n");
    expect(parseExceptionRegister(md)).toEqual([
      {
        id: "TS-01",
        screen: "R-203",
        selector: "a.dense",
        alternative: "Table view of the same rows",
      },
    ]);
  });

  it("ignores prose and the header", () => {
    expect(parseExceptionRegister("# Title\n\n| Id | Screen |\n| --- | --- |\n")).toEqual([]);
  });

  it("every committed exception has a screen, a valid selector and a named alternative", () => {
    const rows = parseExceptionRegister(readFileSync(REGISTER, "utf8"));
    const ids = rows.map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const r of rows) {
      expect(r.screen, `${r.id} screen`).not.toBe("");
      expect(r.selector, `${r.id} selector`).not.toBe("");
      expect(
        () => document.createElement("div").matches(r.selector),
        `${r.id} selector`,
      ).not.toThrow();
      expect(r.alternative.length, `${r.id} alternative`).toBeGreaterThan(10);
    }
  });
});
