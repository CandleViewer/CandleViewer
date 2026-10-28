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

  it("forced colours: the restatement keeps an edge, its label and the reason are CanvasText", () => {
    expect(find(forced, ".cv-confirm__restatement", "border-color")).toContain(
      "border-color: CanvasText",
    );
    expect(find(forced, ".cv-confirm__reason", "color")).toContain("color: CanvasText");
    expect(find(forced, ".cv-confirm__restatement-label", "color")).toContain("color: CanvasText");
  });
});
