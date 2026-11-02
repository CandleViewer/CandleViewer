import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("auditfilterbar.css");
const { normal, forced } = css;

describe("auditfilterbar.css contract (CMP-174; E42-D04 §4 Filters, AL-28)", () => {
  itIsTokenOnlyAndStatic(css);

  it("the form: no margin, space.field.gap between rows, the notice and the chips full width", () => {
    const bar = find(normal, ".cv-audit-filters", "gap");
    expect(bar).toContain("display: flex");
    expect(bar).toContain("flex-direction: column");
    expect(bar).toContain("gap: var(--space-field-gap)");
    expect(bar).toContain("margin: 0");
    expect(bar).toContain("min-width: 0");
  });

  it("the fields: a grid that fills its row with as many columns as fit, space.field.gap apart", () => {
    const grid = find(normal, ".cv-audit-filters__fields", "grid-template-columns");
    expect(grid).toContain("display: grid");
    // Each track at least CMP-047's own basis for a picker with a time (8 control heights, 256 px comfortable),
    // so From and To show their day (A-5520-02); one column below it, never sideways (AL-28).
    expect(grid).toContain(
      "grid-template-columns: repeat(auto-fill, minmax(min(16rem, 100%), 1fr))",
    );
    expect(grid).toContain("gap: var(--space-field-gap)");
    expect(find(normal, ".cv-audit-filters__fields > *", "min-width")).toContain("min-width: 0");
  });

  it("the chips: a wrapping row space.inset.xs apart; the actions at the row's end", () => {
    const chips = find(normal, ".cv-audit-filters__chips", "flex-wrap");
    expect(chips).toContain("display: flex");
    expect(chips).toContain("flex-wrap: wrap");
    expect(chips).toContain("gap: var(--space-inset-xs)");
    expect(chips).toContain("margin: 0");
    expect(chips).toContain("padding: 0");
    expect(chips).toContain("list-style: none");
    const actions = find(normal, ".cv-audit-filters__actions", "justify-content");
    expect(actions).toContain("display: flex");
    expect(actions).toContain("justify-content: flex-end");
  });

  it("the bar's own T2 notice: type.ui.caption in text.secondary (§12.1), never dimmed", () => {
    const notice = find(normal, ".cv-audit-filters__notice", "color");
    expect(notice).toContain("color: var(--color-text-secondary)");
    expect(notice).toContain("--type-ui-caption-font-size");
    expect(notice).toContain("margin: 0");
    expect(css.all).not.toMatch(/text-disabled|opacity/);
  });

  it("forced colours: the notice in CanvasText; the controls keep their own rendering", () => {
    expect(find(forced, ".cv-audit-filters__notice", "color")).toContain("color: CanvasText");
  });
});
