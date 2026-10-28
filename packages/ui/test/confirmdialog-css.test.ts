// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("confirmdialog.css");
const { normal, forced } = css;

describe("confirmdialog.css contract (CMP-044)", () => {
  itIsTokenOnlyAndStatic(css);

  it("no raw rem lengths: every size is a token", () => {
    expect(normal).not.toMatch(/\d(?:\.\d+)?rem/);
  });

  it("the restatement: surface.raised on radius.card, padding inset.md, ui.body in text.primary (H24)", () => {
    const box = find(normal, ".cv-confirm__restatement", "background");
    expect(box).toContain("background: var(--color-surface-raised)");
    expect(box).toContain("border-radius: var(--radius-card)");
    expect(box).toContain("padding: var(--space-inset-md)");
    expect(box).toContain("color: var(--color-text-primary)");
    expect(box).toContain("var(--type-ui-body-font-size)");
    expect(find(normal, ".cv-confirm__restatement strong", "font")).toContain(
      "var(--type-ui-body-strong-font-weight)",
    );
  });

  it("the gated reason: its own row under the footer, text.secondary", () => {
    const line = find(normal, ".cv-confirm__reason", "color");
    expect(line).toContain("color: var(--color-text-secondary)");
    expect(line).toContain("flex: 1 0 100%");
  });

  it("the Cancel wrapper adds no box to the footer row", () => {
    expect(find(normal, ".cv-confirm__cancel", "display")).toContain("display: contents");
  });

  it("the hold ring: a 3 px stroke (thick + hairline), danger over a border.strong track, text num.sm", () => {
    expect(find(normal, ".cv-confirm__arc circle", "stroke-width")).toContain(
      "stroke-width: calc((var(--border-thick) + var(--border-hairline)) * 1px)",
    );
    expect(find(normal, ".cv-confirm__fill", "stroke")).toContain(
      "stroke: var(--color-status-danger-default)",
    );
    expect(find(normal, ".cv-confirm__track", "stroke")).toContain(
      "stroke: var(--color-border-strong)",
    );
    const text = find(normal, ".cv-confirm__hold", "font");
    expect(text).toContain("var(--type-num-sm-font-size)");
    expect(text).toContain("color: var(--color-text-secondary)");
  });

  it("a hold Confirm takes no touch scroll gesture, so a drifting finger keeps the hold", () => {
    expect(find(normal, ".cv-button[data-hold]", "touch-action")).toContain("touch-action: none");
  });

  it("the auto-cancel count: the footer's start in text.primary", () => {
    const line = find(normal, ".cv-confirm__countdown", "color");
    expect(line).toContain("color: var(--color-text-primary)");
    expect(line).toContain("margin-inline-end: auto");
  });

  it("reduced motion hides the arc (override and OS): the percentage text alone", () => {
    expect(find(normal, ':root[data-motion="reduce"] .cv-confirm__arc', "display")).toContain(
      "display: none",
    );
    const os = normal.split("@media (prefers-reduced-motion: reduce)")[1] ?? "";
    expect(find(os, ":root:not([data-motion]) .cv-confirm__arc", "display")).toContain(
      "display: none",
    );
  });

  it("forced colours: the ring is Highlight on a CanvasText track; its text CanvasText", () => {
    expect(find(forced, ".cv-confirm__fill", "stroke")).toContain("stroke: Highlight");
    expect(find(forced, ".cv-confirm__track", "stroke")).toContain("stroke: CanvasText");
    expect(find(forced, ".cv-confirm__hold", "color")).toContain("color: CanvasText");
    expect(find(forced, ".cv-confirm__countdown", "color")).toContain("color: CanvasText");
  });

  it("forced colours: the restatement keeps an edge, its label and the reason are CanvasText", () => {
    expect(find(forced, ".cv-confirm__restatement", "border-color")).toContain(
      "border-color: CanvasText",
    );
    expect(find(forced, ".cv-confirm__reason", "color")).toContain("color: CanvasText");
    expect(find(forced, ".cv-confirm__restatement-label", "color")).toContain("color: CanvasText");
  });
});
