// @vitest-environment jsdom
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, expectTypeOf, it } from "vitest";
import { ICON_COMPONENTS } from "../../src/icons/generated/components.js";
import { ICON_SIZES, ICONS, type IconName, type IconProps } from "../../src/icons/index.js";

const ICONS_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/icons");
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
/** Props a caller could pass from untyped code, outside IconProps. */
type Untyped = Record<string, unknown>;

const markup = (name: IconName, props: IconProps | Untyped = {}) =>
  renderToStaticMarkup(createElement(ICON_COMPONENTS[name], props));
const svgOf = (name: IconName, props?: IconProps | Untyped): SVGSVGElement => {
  const root = new DOMParser().parseFromString(
    markup(name, props),
    "image/svg+xml",
  ).documentElement;
  if (!(root instanceof SVGSVGElement)) throw new Error(`${name} did not render one <svg>`);
  return root;
};
const shapesOf = (svg: SVGSVGElement) => [...svg.children];
/** The inline style React wrote, property by property (`var()` values verbatim). */
const styleOf = (svg: SVGSVGElement) =>
  Object.fromEntries(
    (svg.getAttribute("style") ?? "").split(";").map((rule) => rule.split(/:(.*)/s).slice(0, 2)),
  );

describe("the icon components (src/icons/generated/)", () => {
  it.each(NAMES.flatMap((name) => ICON_SIZES.map((size) => [name, size] as const)))(
    "draws %s at size %s as its snapshot",
    (name, size) => {
      expect(markup(name, { size })).toMatchSnapshot();
    },
  );

  it.each(NAMES)("paints %s with currentColor only, never a hardcoded colour", (name) => {
    const svg = svgOf(name);
    expect([svg.getAttribute("fill"), svg.getAttribute("stroke")]).toEqual([
      "none",
      "currentColor",
    ]);
    for (const shape of shapesOf(svg)) {
      expect([shape.getAttribute("fill"), shape.getAttribute("stroke")]).toEqual([null, null]);
    }
    expect(markup(name)).not.toMatch(/#[\da-f]{3,8}\b|rgba?\(|hsla?\(|oklch\(/i);
  });

  it.each(NAMES)("strokes %s at 1.5px on the 24-unit box, at every optical size", (name) => {
    for (const size of ICON_SIZES) {
      const svg = svgOf(name, { size });
      const extent = `var(--size-icon-${size}, 1em)`;
      expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
      expect(svg.getAttribute("stroke-width")).toBe("1.5");
      expect(styleOf(svg)).toEqual({ width: extent, height: extent });
      for (const shape of shapesOf(svg)) {
        expect(shape.getAttribute("vector-effect"), shape.outerHTML).toBe("non-scaling-stroke");
        expect(shape.getAttribute("stroke-width"), shape.outerHTML).toBeNull();
      }
    }
  });

  it("sizes an icon with the semantic size.icon when no size is given", () => {
    const extent = "var(--size-icon, 1em)";
    expect(styleOf(svgOf("close"))).toEqual({ width: extent, height: extent });
  });

  it("hides an icon from assistive technology unless it is named, then exposes it as an image", () => {
    const decorative = svgOf("warning");
    expect([decorative.getAttribute("aria-hidden"), decorative.getAttribute("role")]).toEqual([
      "true",
      null,
    ]);
    expect(decorative.getAttribute("focusable")).toBe("false");
    for (const naming of [{ "aria-label": "Warning" }, { "aria-labelledby": "warning-text" }]) {
      const named = svgOf("warning", naming);
      expect([named.getAttribute("aria-hidden"), named.getAttribute("role")]).toEqual([
        null,
        "img",
      ]);
    }
  });

  it.each([{ "aria-label": "" }, { "aria-label": "  " }, { "aria-labelledby": "" }])(
    "keeps an icon hidden when its name is blank (%o): an unnamed image is no image",
    (blank) => {
      const svg = svgOf("warning", blank);
      expect([svg.getAttribute("aria-hidden"), svg.getAttribute("role")]).toEqual(["true", null]);
    },
  );

  it("keeps the grid whatever untyped props a caller passes", () => {
    const svg = svgOf("close", {
      fill: "#ff0000",
      stroke: "red",
      strokeWidth: 3,
      viewBox: "0 0 48 48",
      icon: "check",
      style: { width: 99, color: "var(--color-status-danger-default)" },
      className: "toolbar-icon",
    });
    expect(svg.getAttribute("fill")).toBe("none");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("stroke-width")).toBe("1.5");
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("data-icon")).toBe("close");
    expect(styleOf(svg)).toEqual({
      width: "var(--size-icon, 1em)",
      height: "var(--size-icon, 1em)",
      color: "var(--color-status-danger-default)",
    });
    expect(svg.getAttribute("class")).toBe("toolbar-icon");
  });

  it("takes no markup string: the props type omits it and React refuses it beside the geometry", () => {
    expectTypeOf<IconProps>().not.toHaveProperty("dangerouslySetInnerHTML");
    expectTypeOf<IconProps>().not.toHaveProperty("children");
    expect(() => markup("close", { dangerouslySetInnerHTML: { __html: "<g />" } })).toThrow();
    const sources = readdirSync(ICONS_DIR, { recursive: true, encoding: "utf-8" })
      .filter((file) => /\.tsx?$/.test(file))
      .filter((file) =>
        /dangerouslySetInnerHTML\s*=/.test(readFileSync(path.join(ICONS_DIR, file), "utf-8")),
      );
    expect(sources).toEqual([]);
  });
});
