import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("avatar.css");
const { normal, forced } = css;

describe("avatar.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("md is a size.control.height circle, sm a size.icon one, in the interim neutral fill", () => {
    const md = find(normal, ".cv-avatar", "width");
    expect(md).toContain("width: var(--size-control-height)");
    expect(md).toContain("height: var(--size-control-height)");
    expect(md).toContain("border-radius: var(--radius-badge)");
    expect(md).toContain("background: var(--color-neutral-subtle)");
    expect(md).toContain("color: var(--color-text-primary)");
    expect(md).toContain("--type-ui-label-font-size");
    expect(md).toContain("overflow: hidden");
    const sm = find(normal, '.cv-avatar[data-size="sm"]', "width");
    expect(sm).toContain("width: var(--size-icon)");
    expect(sm).toContain("--type-ui-caption-font-size");
  });

  it("forced colours: the transparent hairline becomes a CanvasText edge with CanvasText initials", () => {
    expect(find(normal, ".cv-avatar", "width")).toMatch(
      /border: calc\(var\(--border-hairline\) \* 1px\) solid transparent/,
    );
    const fc = find(forced, ".cv-avatar", "border-color");
    expect(fc).toContain("border-color: CanvasText");
    expect(fc).toContain("color: CanvasText");
  });
});
