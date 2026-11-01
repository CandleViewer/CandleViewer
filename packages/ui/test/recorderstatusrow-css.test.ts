import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("recorderstatusrow.css");

describe("recorderstatusrow.css contract (E16-D02 §11.1, §10.4, §10.5)", () => {
  itIsTokenOnlyAndStatic(css);

  it("a stale row, in the grid or standalone, sits on surface.sunken (D02 §3.1)", () => {
    const grid = find(css.normal, "tr.cv-rsr-row[data-stale]", "background");
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

  it("T2: the action is CMP-001's own (no restyle here); the switch's lock CMP-004's, its label tertiary, never dimmed", () => {
    // Composed as CMP-055's controls are: the atom's T2 look stands (#262's C-row), never restyled per molecule; the
    // switch's lock is CMP-004's centred `cv-choice__lock` (B-5309-09), no lock rule of the row's own.
    expect(css.all).not.toMatch(/\.cv-button|cv-rsr__action|cv-rsr__lock/);
    expect(find(css.normal, ".cv-rsr__keep[data-gated] .cv-choice__label", "color")).toContain(
      "var(--color-text-tertiary)",
    );
    expect(find(css.normal, ".cv-rsr__reason", "color")).toContain("var(--color-text-secondary)");
    expect(css.all).not.toMatch(/opacity|--color-text-disabled/);
  });

  it("the grid's State is one line, its words cut with an ellipsis, icon and tag whole (D02 §9.1, B-5309-01)", () => {
    const line = "tr.cv-rsr-row:not([data-stacked]) .cv-rsr__state";
    expect(find(css.normal, line, "white-space")).toContain("white-space: nowrap");
    const words = find(
      css.normal,
      "tr.cv-rsr-row:not([data-stacked]) .cv-rsr__words",
      "text-overflow",
    );
    expect(words).toContain("overflow: hidden");
    expect(words).toContain("text-overflow: ellipsis");
    expect(find(css.normal, ".cv-rsr__icon", "flex")).toContain("flex: none");
    expect(find(css.normal, ".cv-rsr__state > .cv-tag", "flex")).toContain("flex: none");
  });

  it("figures end-aligned; they wrap, the share on its own line, never over Retention (board 05, D-5309-03)", () => {
    const num = find(css.normal, ".cv-rsr__num", "white-space");
    expect(num).toContain("white-space: normal");
    expect(num).toContain("text-align: end");
  });

  it("forced colours: words and glyphs CanvasText, the card's border CanvasText", () => {
    expect(find(css.forced, ".cv-rsr__icon[data-tone]", "color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-rsr", "border-color")).toContain("CanvasText");
    expect(css.forced).not.toContain("var(--color");
  });
});
