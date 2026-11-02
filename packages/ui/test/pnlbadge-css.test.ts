import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const pnl = loadCss("pnlbadge.css");
const mode = loadCss("positionmode.css");

describe("pnlbadge.css contract (E29-D04 §2.3)", () => {
  itIsTokenOnlyAndStatic(pnl);

  it("digits: color.text.primary, tabular, type.num.base by default, sm and md by size", () => {
    const base = find(pnl.normal, ".cv-pnl-badge", "font-variant-numeric");
    expect(base).toContain("font-variant-numeric: tabular-nums");
    expect(base).toContain("color: var(--color-text-primary)");
    expect(base).toContain("var(--type-num-base-font-size)");
    expect(base).toContain("white-space: nowrap");
    expect(find(pnl.normal, '.cv-pnl-badge[data-size="sm"]', "--cv-pnl-size")).toContain(
      "--type-num-sm-font-size",
    );
    expect(find(pnl.normal, '.cv-pnl-badge[data-size="lg"]', "--cv-pnl-size")).toContain(
      "--type-num-md-font-size",
    );
  });

  it("the hue rides on a border.thick bar only: buy, sell, neutral; the digits never take it", () => {
    expect(find(pnl.normal, ".cv-pnl-badge__bar", "width")).toContain(
      "calc(var(--border-thick) * 1px)",
    );
    expect(find(pnl.normal, ".cv-pnl-badge__bar", "background")).toContain(
      "--color-neutral-default",
    );
    expect(
      find(pnl.normal, '.cv-pnl-badge[data-sign="positive"] > .cv-pnl-badge__bar', "background"),
    ).toContain("--color-buy-default");
    expect(
      find(pnl.normal, '.cv-pnl-badge[data-sign="negative"] > .cv-pnl-badge__bar', "background"),
    ).toContain("--color-sell-default");
    expect(pnl.normal).not.toMatch(/color:\s*var\(--color-(buy|sell)/);
  });

  it("forced colours: the bar falls back to CanvasText (E29-D02:527)", () => {
    const body = find(pnl.forced, ".cv-pnl-badge__bar", "background");
    expect(body).toContain("background: CanvasText");
    expect(body).toContain("forced-color-adjust: none");
  });
});

describe("positionmode.css contract (D04H §C.4)", () => {
  itIsTokenOnlyAndStatic(mode);

  it("display: type.ui.body in color.text.primary, no ring", () => {
    const body = find(mode.normal, ".cv-position-mode", "font");
    expect(body).toContain("--type-ui-body-font-size");
    expect(body).toContain("color: var(--color-text-primary)");
    expect(mode.all).not.toMatch(/outline|focus/);
  });
});
