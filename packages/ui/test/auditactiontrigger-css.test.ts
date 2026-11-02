import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("auditactiontrigger.css");
const { normal, forced } = css;

describe("auditactiontrigger.css contract (CMP-093; E42-D02 §4.3, E42-D04 §12.1)", () => {
  itIsTokenOnlyAndStatic(css);

  it("stacks the control, its reason and the marker, space.stack.xs apart, from the start by default", () => {
    const root = find(normal, ".cv-audit-action", "flex-direction");
    expect(root).toContain("display: inline-flex");
    expect(root).toContain("flex-direction: column");
    expect(root).toContain("align-items: flex-start");
    expect(root).toContain("gap: var(--space-stack-xs)");
    expect(root).toContain("min-width: 0");
    const end = find(normal, '.cv-audit-action[data-align="end"]', "align-items");
    expect(end).toContain("align-items: flex-end");
    expect(end).toContain("text-align: end");
  });

  it("the marker: type.ui.caption in text.tertiary (D02 §4.3), wrapping, never truncated", () => {
    const marker = find(normal, ".cv-audit-action__marker", "color");
    expect(marker).toContain("color: var(--color-text-tertiary)");
    expect(marker).toContain("--type-ui-caption-font-size");
    expect(marker).toContain("margin: 0");
    expect(marker).toContain("overflow-wrap: anywhere");
  });

  it("the T2 reason: type.ui.caption in text.secondary (§12.1), never text.disabled or opacity", () => {
    const reason = find(normal, ".cv-audit-action__reason", "color");
    expect(reason).toContain("color: var(--color-text-secondary)");
    expect(reason).toContain("--type-ui-caption-font-size");
    expect(reason).toContain("margin: 0");
    expect(css.all).not.toMatch(/text-disabled|opacity/);
  });

  it("forced colours: both lines in CanvasText", () => {
    for (const line of [".cv-audit-action__marker", ".cv-audit-action__reason"]) {
      expect(find(forced, line, "color")).toContain("color: CanvasText");
    }
  });
});
