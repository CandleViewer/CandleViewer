// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { find, loadCss } from "./css-contract.js";

const { all, normal, forced } = loadCss("dialog.css");

describe("dialog.css contract (CMP-043)", () => {
  it("binds tokens only: no raw colour, raw px only for forced-colours edges", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(forced).not.toMatch(/\d+px/);
  });

  it("the only raw lengths are the H17 widths and the 200 % reflow breakpoints, in rem", () => {
    const rems = [...normal.matchAll(/(\d+(?:\.\d+)?)rem/g)].map((m) => m[1]);
    expect(new Set(rems)).toEqual(new Set(["35", "26.25", "60", "40", "25"]));
  });

  it("the scrim: palette.black at opacity.scrim over the layer, insettable by the shell (H1, H23)", () => {
    const scrim = find(normal, ".cv-dialog__scrim", "background");
    expect(scrim).toContain("background: var(--palette-black)");
    expect(scrim).toContain("opacity: var(--opacity-scrim)");
    expect(scrim).toContain("inset: 0");
    const layer = find(normal, ".cv-dialog-layer", "position");
    expect(layer).toContain("position: fixed");
    expect(layer).toContain(
      "inset: var(--cv-scrim-inset-top, 0) 0 var(--cv-scrim-inset-bottom, 0)",
    );
  });

  it("the card: overlay fill, dialog elevation and radius, default edge, dialog padding (conventions 30)", () => {
    const card = find(normal, ".cv-dialog", "background");
    expect(card).toContain("background: var(--color-surface-overlay)");
    expect(card).toContain("box-shadow: var(--elevation-dialog)");
    expect(card).toContain("border-radius: var(--radius-dialog)");
    expect(card).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(card).toContain("padding: var(--space-dialog-padding)");
    expect(card).toContain("gap: var(--space-stack-md)");
    expect(card).toContain("max-height: 80vh");
  });

  it("H17 widths: md 560, sm 420, lg 960 px, never wider than the viewport less its insets", () => {
    const cap = "calc(100vw - 2 * var(--space-inset-lg))";
    expect(find(normal, ".cv-dialog", "width")).toContain(`width: min(35rem, ${cap})`);
    expect(find(normal, '.cv-dialog[data-size="sm"]', "width")).toContain(
      `width: min(26.25rem, ${cap})`,
    );
    expect(find(normal, '.cv-dialog[data-size="lg"]', "width")).toContain(
      `width: min(60rem, ${cap})`,
    );
  });

  it("the header and footer stay while the body scrolls; the footer wraps (conventions 39)", () => {
    const body = find(normal, ".cv-dialog__body", "overflow");
    expect(body).toContain("overflow: auto");
    expect(body).toContain("min-height: 0");
    expect(find(normal, ".cv-dialog__header", "flex")).toContain("flex: none");
    const footer = find(normal, ".cv-dialog__footer", "flex-wrap");
    expect(footer).toContain("flex: none");
    expect(footer).toContain("flex-wrap: wrap");
    expect(footer).toContain("justify-content: flex-end");
    expect(footer).toContain("gap: var(--space-inset-sm)");
    expect(find(normal, ".cv-dialog__title", "font")).toContain(
      "var(--type-ui-heading-sm-font-size)",
    );
  });

  it("at 200 % zoom on 1280 x 800 the card fills the viewport", () => {
    const reflow = /@media \(max-width: 40rem\), \(max-height: 25rem\)\s*\{([\s\S]*?\}\s*)\}/.exec(
      normal,
    )?.[1];
    const card = find(reflow ?? "", ".cv-dialog", "width");
    expect(card).toContain("width: 100%");
    expect(card).toContain("max-height: 100%");
  });

  it("H21: the scrim fades in over normal / standard while the card is a cut", () => {
    expect(all).toMatch(
      /prefers-reduced-motion: no-preference\)\s*\{\s*\.cv-dialog__scrim\s*\{\s*animation: cv-dialog-scrim-in var\(--motion-duration-normal\)\s*cubic-bezier\(var\(--motion-easing-standard\)\)/,
    );
    expect(find(normal, ".cv-dialog", "animation")).toBe("");
    expect(find(normal, ".cv-dialog", "transition")).toBe("");
  });

  it("the exit fades both parts over fast / accelerate with no pointer events", () => {
    const exit = find(normal, '.cv-dialog-layer[data-state="closing"] > .cv-dialog', "transition");
    expect(exit).toContain("opacity: 0");
    expect(exit).toContain(
      "transition: opacity var(--motion-duration-fast) cubic-bezier(var(--motion-easing-accelerate))",
    );
    expect(find(normal, '.cv-dialog-layer[data-state="closing"]', "pointer-events")).toContain(
      "pointer-events: none",
    );
  });

  it("reduced motion: the in-app override and the OS preference both cut the fade", () => {
    expect(find(all, ':root[data-motion="reduce"] .cv-dialog__scrim', "animation")).toContain(
      "animation: none",
    );
    expect(
      find(
        all,
        ':root[data-motion="reduce"] .cv-dialog-layer[data-state="closing"] > .cv-dialog',
        "transition",
      ),
    ).toContain("transition: none");
    expect(
      find(
        all,
        ':root:not([data-motion]) .cv-dialog-layer[data-state="closing"] > .cv-dialog__scrim',
        "transition",
      ),
    ).toContain("transition: none");
  });

  it("forced colours: a CanvasText edge on Canvas; the scrim keeps its black (conventions 38)", () => {
    const card = find(forced, ".cv-dialog", "border-color");
    expect(card).toContain("border-color: CanvasText");
    expect(card).toContain("background: Canvas");
    expect(find(forced, ".cv-dialog__scrim", "forced-color-adjust")).toContain(
      "forced-color-adjust: none",
    );
    expect(forced).not.toMatch(/var\(--color/);
  });
});
