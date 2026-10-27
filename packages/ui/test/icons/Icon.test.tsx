import type { JSX } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import * as ui from "../../src/index.js";
import {
  Icon,
  IconButton,
  ICON_SIZES,
  ICONS,
  type IconName,
  type IconProps,
} from "../../src/index.js";
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

  // The generated maps stay internal: `Icon` alone draws a glyph, or a size form of it.
  it("exports the registry and the sizes from the package entry, never a generated map", () => {
    const maps = Object.keys(ui).filter((name) => name.startsWith("ICON"));
    expect(maps.sort()).toEqual(["ICONS", "ICON_SIZES"]);
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

  // E05-D02 §6 J24: a "16 px minimum" glyph is never drawn at sm, 12 px as shipped. The types hold
  // it wherever a call site fixes the name; one that leaves it open keeps all three sizes.
  it("refuses sm for a 16 px minimum glyph in the types, in Icon and in IconButton", () => {
    // @ts-expect-error twap is "16 px minimum": never drawn at 12 px
    const twap = <Icon name="twap" size="sm" />;
    // @ts-expect-error named or decorative alike
    const named = <Icon name="flatten-all" size="sm" decorative={false} label="Flatten all" />;
    // @ts-expect-error CMP-002 draws its glyph at its own size, through the same guard
    const button = <IconButton icon="native-sl-shield" label="Protected" size="sm" />;
    // @ts-expect-error the props type carries the guard too
    const props: IconProps<"iceberg-order"> = { name: "iceberg-order", size: "sm" };
    // Exactly the six marked names refuse sm, both ways: a name missing, or one too many, fails.
    type Refusing = { [N in IconName]: "sm" extends IconProps<N>["size"] ? never : N }[IconName];
    type Marked =
      | "chase-limit"
      | "flatten-all"
      | "heatmap-convention-swap"
      | "iceberg-order"
      | "native-sl-shield"
      | "twap";
    const exact: [Refusing, Marked] extends [Marked, Refusing] ? true : never = true;
    const held = [
      <Icon name="one-click-arm" size="sm" />,
      <Icon name="estimated" size="sm" />,
      <Icon name="twap" size="md" />,
      <IconButton icon="twap" label="TWAP" size="lg" />,
    ];
    // A name left open, as in a map over the registry, and the unparameterised props type.
    const open = NAMES.map((name) => <Icon name={name} size="sm" />);
    const any: IconProps = { name: NAMES[0] ?? "twap", size: "sm" };
    expect([twap, named, button, props, exact, ...held, any]).toHaveLength(10);
    expect(open).toHaveLength(NAMES.length);
  });
});
