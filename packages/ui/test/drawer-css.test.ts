// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { find, loadCss } from "./css-contract.js";

const { all, normal, forced } = loadCss("drawer.css");

describe("drawer.css contract (CMP-046)", () => {
  it("binds tokens only: no raw colour, raw px only as a token multiplier", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(forced).not.toMatch(/\d+px/);
  });

  it("the only raw lengths are the 480 px default width and the 720 px narrow breakpoint, in rem", () => {
    const rems = [...normal.matchAll(/(\d+(?:\.\d+)?)rem/g)].map((m) => m[1]);
    expect(new Set(rems)).toEqual(new Set(["30", "45"]));
  });

  it("the layer passes the pointer through and is insettable by the shell (H23)", () => {
    const layer = find(normal, ".cv-drawer-layer", "position");
    expect(layer).toContain("position: fixed");
    expect(layer).toContain(
      "inset: var(--cv-scrim-inset-top, 0) 0 var(--cv-scrim-inset-bottom, 0)",
    );
    expect(layer).toContain("pointer-events: none");
    expect(find(normal, ".cv-drawer", "pointer-events")).toContain("pointer-events: auto");
  });

  it("the scrim: palette.black at opacity.scrim, catching presses (H1)", () => {
    const scrim = find(normal, ".cv-drawer__scrim", "background");
    expect(scrim).toContain("background: var(--palette-black)");
    expect(scrim).toContain("opacity: var(--opacity-scrim)");
    expect(scrim).toContain("pointer-events: auto");
  });

  it("the panel: overlay fill, square, an inner hairline edge, the host's width capped by the viewport", () => {
    const panel = find(normal, ".cv-drawer", "background");
    expect(panel).toContain("background: var(--color-surface-overlay)");
    expect(panel).toContain("box-shadow: var(--elevation-dialog)");
    expect(panel).toContain("width: min(var(--cv-drawer-width, 30rem), 100%)");
    expect(panel).toContain(
      "border-left: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(panel).not.toContain("border-radius");
    const left = find(normal, '.cv-drawer[data-side="left"]', "border-right");
    expect(left).toContain("left: 0");
    expect(left).toContain("border-left: none");
  });

  it("H31: a non-modal panel floats at elevation.popover", () => {
    expect(find(normal, ".cv-drawer:not([data-modal])", "box-shadow")).toContain(
      "box-shadow: var(--elevation-popover)",
    );
  });

  it("anatomy: a ruled header, a scrolling body and a wrapping footer, padded space.panel.padding", () => {
    const header = find(normal, ".cv-drawer__header", "border-bottom");
    expect(header).toContain("padding: var(--space-panel-padding)");
    expect(header).toContain("flex: none");
    const body = find(normal, ".cv-drawer__body", "overflow");
    expect(body).toContain("overflow: auto");
    expect(body).toContain("min-height: 0");
    expect(body).toContain("gap: var(--space-stack-md)");
    expect(body).toContain("padding: var(--space-panel-padding)");
    expect(find(normal, ".cv-drawer__footer", "flex-wrap")).toContain("flex-wrap: wrap");
    expect(find(normal, ".cv-drawer__title", "font")).toContain(
      "var(--type-ui-heading-sm-font-size)",
    );
  });

  it("narrow: the full width at a viewport of 720 CSS px or less (conventions 39)", () => {
    const narrow = /@media \(max-width: 45rem\)\s*\{([\s\S]*?\}\s*)\}/.exec(normal)?.[1];
    expect(find(narrow ?? "", ".cv-drawer", "width")).toContain("width: 100%");
  });

  it("H21: it slides in over normal / decelerate from its side; the scrim fades in", () => {
    const motion = /prefers-reduced-motion: no-preference\)\s*\{([\s\S]*?\}\s*)\}/.exec(all)?.[1];
    expect(find(motion ?? "", ".cv-drawer", "animation")).toContain(
      "animation: cv-drawer-in-right var(--motion-duration-normal)",
    );
    expect(motion).toContain("cubic-bezier(var(--motion-easing-decelerate))");
    expect(find(motion ?? "", '.cv-drawer[data-side="left"]', "animation-name")).toContain(
      "cv-drawer-in-left",
    );
    expect(all).toMatch(
      /@keyframes cv-drawer-in-right\s*\{\s*from\s*\{\s*transform: translateX\(100%\)/,
    );
    expect(all).toMatch(
      /@keyframes cv-drawer-in-left\s*\{\s*from\s*\{\s*transform: translateX\(-100%\)/,
    );
    // Opaque from frame 0: only transform moves the panel.
    expect(all).not.toMatch(/@keyframes cv-drawer-in-[a-z]+\s*\{[^}]*opacity/);
  });

  it("the exit slides out over fast / accelerate with no pointer events", () => {
    const exit = find(normal, '.cv-drawer-layer[data-state="closing"] > .cv-drawer', "transition");
    expect(exit).toContain("transform: translateX(100%)");
    expect(exit).toContain(
      "transition: transform var(--motion-duration-fast) cubic-bezier(var(--motion-easing-accelerate))",
    );
    expect(
      find(normal, '.cv-drawer-layer[data-state="closing"] > .cv-drawer', "pointer-events"),
    ).toContain("pointer-events: none");
    expect(
      find(
        normal,
        '.cv-drawer-layer[data-state="closing"] > .cv-drawer[data-side="left"]',
        "transform",
      ),
    ).toContain("translateX(-100%)");
  });

  it("reduced motion: the in-app override and the OS preference both make it a cut", () => {
    expect(find(all, ':root[data-motion="reduce"] .cv-drawer', "animation")).toContain(
      "animation: none",
    );
    expect(
      find(
        all,
        ':root[data-motion="reduce"] .cv-drawer-layer[data-state="closing"] > .cv-drawer',
        "transition",
      ),
    ).toContain("transition: none");
    expect(
      find(
        all,
        ':root:not([data-motion]) .cv-drawer-layer[data-state="closing"] > .cv-drawer',
        "transition",
      ),
    ).toContain("transition: none");
  });

  it("forced colours: CanvasText edges and rule on Canvas; the scrim keeps its black (conventions 38)", () => {
    expect(find(forced, ".cv-drawer__header", "border-color")).toContain(
      "border-color: CanvasText",
    );
    expect(find(forced, ".cv-drawer", "background")).toContain("background: Canvas");
    expect(find(forced, ".cv-drawer__scrim", "forced-color-adjust")).toContain(
      "forced-color-adjust: none",
    );
    expect(forced).not.toMatch(/var\(--color/);
  });
});
