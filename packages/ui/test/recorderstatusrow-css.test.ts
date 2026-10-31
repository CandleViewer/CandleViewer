import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("recorderstatusrow.css");

describe("recorderstatusrow.css contract (E16-D02 §11.1, §10.4, §10.5)", () => {
  itIsTokenOnlyAndStatic(css);

  it("a stale row, in the grid or standalone, sits on surface.sunken (D02 §3.1)", () => {
    const grid = find(css.normal, ".cv-table__row:has(.cv-rsr__state[data-stale])", "background");
    expect(grid).toContain("var(--color-surface-sunken)");
    expect(find(css.normal, ".cv-rsr[data-stale]", "background")).toContain(
      "var(--color-surface-sunken)",
    );
  });

  it("state words stay text.primary; the tone is the icon's, success.default when stale (§10.4)", () => {
    expect(find(css.normal, ".cv-rsr__words", "color")).toContain("var(--color-text-primary)");
    const tone = (t: string): string =>
      find(css.normal, `.cv-rsr__icon[data-tone="${t}"]`, "color");
    expect(tone("warning")).toContain("var(--color-status-warning-strong)");
    expect(tone("danger")).toContain("var(--color-status-danger-default)");
    expect(tone("info")).toContain("var(--color-status-info-strong)");
    expect(find(css.normal, ".cv-rsr__icon .cv-badge[data-tone]", "--cv-badge-dot")).toContain(
      "var(--color-status-success-strong)",
    );
    expect(
      find(css.normal, "[data-stale] .cv-rsr__icon .cv-badge[data-tone]", "--cv-badge-dot"),
    ).toContain("var(--color-status-success-default)");
  });

  it("T2: the raised fill with a border.default hairline, label and lock tertiary, never dimmed", () => {
    const t2 = find(css.normal, '.cv-rsr__action.cv-button[aria-disabled="true"]', "background");
    expect(t2).toContain("background: var(--color-surface-raised)");
    expect(t2).toContain("border-color: var(--color-border-default)");
    expect(t2).toContain("color: var(--color-text-tertiary)");
    expect(find(css.normal, ".cv-rsr__lock", "color")).toContain("var(--color-text-tertiary)");
    expect(find(css.normal, ".cv-rsr__reason", "color")).toContain("var(--color-text-secondary)");
    expect(css.all).not.toMatch(/opacity|--color-text-disabled/);
  });

  it("forced colours: words and glyphs CanvasText, a T2 control's border GrayText", () => {
    expect(find(css.forced, ".cv-rsr__icon[data-tone]", "color")).toContain("CanvasText");
    expect(
      find(css.forced, '.cv-rsr__action.cv-button[aria-disabled="true"]', "border-color"),
    ).toContain("GrayText");
    expect(find(css.forced, ".cv-rsr", "border-color")).toContain("CanvasText");
    expect(css.forced).not.toContain("var(--color");
  });
});
