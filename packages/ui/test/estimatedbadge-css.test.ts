import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("estimatedbadge.css");

describe("estimatedbadge.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the word stays text.primary on the info subtle fill; the hue rides on the outline and glyph", () => {
    expect(find(css.normal, ".cv-estimated", "color")).toContain("--color-text-primary");
    expect(find(css.normal, ".cv-estimated", "background")).toContain("--color-status-info-subtle");
    expect(find(css.normal, ".cv-estimated", "border")).toContain("dashed");
    expect(find(css.normal, ".cv-estimated__glyph", "color")).toContain(
      "--color-status-info-default",
    );
  });

  it("keeps a 24 px target by padding and a focus ring token", () => {
    expect(find(css.normal, ".cv-estimated", "min-height")).toContain("--size-target-min");
    expect(find(css.normal, ".cv-estimated:focus-visible", "outline")).toContain(
      "--color-focus-ring",
    );
  });
});
