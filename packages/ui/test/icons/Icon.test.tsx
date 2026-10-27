import type { JSX } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Icon, ICON_SIZES, ICONS, type IconName } from "../../src/index.js";
import { ICON_COMPONENTS } from "../../src/icons/generated/components.js";

// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
const html = (element: JSX.Element) => renderToStaticMarkup(element);

describe("the icon registry", () => {
  it("has one component per name, and every name is sorted kebab-case", () => {
    expect(Object.keys(ICON_COMPONENTS)).toEqual(NAMES);
    expect(NAMES).toEqual([...NAMES].sort());
    for (const name of NAMES) {
      expect(name).toMatch(/^[a-z][\da-z]*(?:-[\da-z]+)*$/);
      expect(renderToStaticMarkup(<Icon name={name} />), name).toContain(` data-icon="${name}"`);
    }
  });

  it("registers lock and unlock, with no locked alias", () => {
    expect(NAMES).toEqual(expect.arrayContaining(["lock", "unlock"]));
    expect(NAMES).not.toContain("locked");
  });

  it("draws no glyph twice under two names", () => {
    const geometry = NAMES.map((name) =>
      renderToStaticMarkup(<Icon name={name} />).replace(/^<svg[^>]*>/, ""),
    );
    expect(new Set(geometry).size).toBe(NAMES.length);
  });
});

describe("Icon (CMP-019)", () => {
  it("is decorative by default: aria-hidden, no role, no name", () => {
    const out = html(<Icon name="check" />);
    expect(out).toContain('data-icon="check"');
    expect(out).toContain('aria-hidden="true"');
    expect(out).not.toContain("role=");
    expect(out).not.toContain("aria-label");
  });

  it("stays decorative when decorative is true", () => {
    const out = html(<Icon name="plus" decorative />);
    expect(out).toContain('aria-hidden="true"');
    expect(out).not.toContain("role=");
  });

  it("is a named image when decorative={false} with a label", () => {
    const out = html(<Icon name="warning" decorative={false} label="Order rejected" />);
    expect(out).toContain('role="img"');
    expect(out).toContain('aria-label="Order rejected"');
    expect(out).toContain('data-icon="warning"');
    expect(out).not.toContain("aria-hidden");
  });

  it.each(ICON_SIZES)("sizes %s from the size.icon token, with no pixel value", (size) => {
    const out = html(<Icon name="info" size={size} />);
    expect(out).toContain(
      `width:var(--size-icon-${size}, 1em);height:var(--size-icon-${size}, 1em)`,
    );
    expect(out).not.toMatch(/\d+px/);
  });

  it("takes the semantic size.icon when no size is given", () => {
    expect(html(<Icon name="minus" />)).toContain("width:var(--size-icon, 1em)");
  });

  it("rejects a label on a decorative icon, and none on a meaningful one, in the types", () => {
    // @ts-expect-error decorative={false} requires a label
    const missing = <Icon name="close" decorative={false} />;
    // @ts-expect-error a decorative icon takes no label
    const stray = <Icon name="close" label="Close" />;
    expect([missing, stray]).toHaveLength(2);
  });
});
