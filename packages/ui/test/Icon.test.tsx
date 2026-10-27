import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Icon, type IconName } from "../src/components/index.js";
import { ICONS } from "../src/icons/registry.js";

describe("Icon (CMP-019, the #271 contract)", () => {
  it("is decorative by default", () => {
    const h = renderToStaticMarkup(<Icon name="lock" />);
    expect(h).toContain('aria-hidden="true"');
    expect(h).not.toContain("role=");
  });
  it("names a meaningful icon, which needs its label", () => {
    const h = renderToStaticMarkup(<Icon name="check" decorative={false} label="Done" />);
    expect(h).toContain('role="img"');
    expect(h).toContain('aria-label="Done"');
    // @ts-expect-error a meaningful icon without a label is refused at compile time
    void (<Icon name="check" decorative={false} />);
  });
  it("sizes from size.icon and strokes in currentColor, for every registry name", () => {
    for (const name of Object.keys(ICONS) as IconName[]) {
      const h = renderToStaticMarkup(<Icon name={name} size="lg" />);
      expect(h).toContain("var(--size-icon-lg)");
      expect(h).toContain('stroke="currentColor"');
    }
  });
});
