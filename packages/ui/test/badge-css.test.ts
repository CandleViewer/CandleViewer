import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("badge.css");
const { normal, forced } = css;

describe("badge.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("count: size.icon minimums, inset.xs padding, tinted fill, .strong outline, text.primary numeral", () => {
    const count = find(normal, '.cv-badge[data-variant="count"]', "min-width");
    expect(count).toContain("min-width: var(--size-icon)");
    expect(count).toContain("min-height: var(--size-icon)");
    expect(count).toContain("padding-inline: var(--space-inset-xs)");
    expect(count).toContain("color: var(--color-text-primary)");
    expect(count).toContain("--type-num-xs-font-size");
    expect(find(normal, '.cv-badge[data-tone="danger"]', "--cv-badge-edge")).toContain(
      "--cv-badge-edge: var(--color-status-danger-strong)",
    );
    expect(find(normal, ".cv-badge", "--cv-badge-fill")).toContain(
      "--cv-badge-fill: var(--color-neutral-subtle)",
    );
  });

  it("dot: an inset.xs-padded mark centred in a size.icon slot", () => {
    expect(find(normal, '.cv-badge[data-variant="dot"]', "width")).toContain(
      "width: var(--size-icon)",
    );
    expect(find(normal, ".cv-badge__dot", "padding")).toContain("padding: var(--space-inset-xs)");
  });

  it("forced colours: a CanvasText outline and numeral; the dot keeps a CanvasText fill", () => {
    const count = find(forced, '.cv-badge[data-variant="count"]', "border-color");
    expect(count).toContain("border-color: CanvasText");
    expect(count).toContain("color: CanvasText");
    const dot = find(forced, ".cv-badge__dot", "background");
    expect(dot).toContain("background: CanvasText");
    expect(dot).toContain("forced-color-adjust: none");
  });
});
