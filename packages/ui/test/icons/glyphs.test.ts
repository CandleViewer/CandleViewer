// @vitest-environment jsdom
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OUTPUT_DIR, renderIconModules } from "../../scripts/build-icons.mjs";
import { ICON_COMPONENTS } from "../../src/icons/generated/components.js";
import { ICON_SIZES, ICONS, type IconName, type IconSize } from "../../src/icons/index.js";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SVG_NS = "http://www.w3.org/2000/svg";
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
/** A colour written out: a hex value or a CSS colour function (`currentColor` is neither). */
const COLOUR = /#[\da-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/i;
/** A paint or style prop on a geometry element, which only the grid (`IconSvg`) may set. */
const PAINT = /\b(?:fill|stroke|color|style|className|opacity)[\w-]*=/;
/** What a glyph may draw: each geometry tag, with the attributes it may carry. */
const GEOMETRY: Readonly<Record<string, readonly string[]>> = {
  path: ["d"],
  circle: ["cx", "cy", "r"],
  ellipse: ["cx", "cy", "rx", "ry"],
  line: ["x1", "y1", "x2", "y2"],
  polyline: ["points"],
  polygon: ["points"],
  rect: ["x", "y", "width", "height", "rx", "ry"],
};

const markup = (name: IconName, size?: IconSize) =>
  renderToStaticMarkup(createElement(ICON_COMPONENTS[name], size === undefined ? {} : { size }));
const svgOf = (name: IconName, size?: IconSize): SVGSVGElement => {
  const doc = new DOMParser().parseFromString(markup(name, size), "image/svg+xml");
  const root = doc.documentElement;
  if (!(root instanceof SVGSVGElement)) throw new Error(`${name} did not render one <svg>`);
  return root;
};
/** Each shape, in order: its tag and its attributes but vector-effect, as SVG spaces them. */
const shapesOf = (svg: Element) =>
  [...svg.children].map((shape) => [
    shape.tagName,
    Object.fromEntries(
      [...shape.attributes]
        .filter(({ name }) => name !== "vector-effect")
        .map(({ name, value }) => [name, value.replace(/\s+/g, " ").trim()]),
    ),
  ]);

describe("the generated icon components (src/icons/generated/)", () => {
  it("paints every icon in currentColor, with no fill and no hard-coded colour", () => {
    for (const name of NAMES) {
      const svg = svgOf(name);
      expect([svg.getAttribute("fill"), svg.getAttribute("stroke")], name).toEqual([
        "none",
        "currentColor",
      ]);
      for (const shape of svg.querySelectorAll("*")) {
        const paint = ["fill", "stroke", "color", "style"].map((a) => shape.getAttribute(a));
        expect(paint, `${name}: ${shape.outerHTML}`).toEqual([null, null, null, null]);
      }
      expect(markup(name), name).not.toMatch(COLOUR);
    }
  });

  it("writes no fill, stroke or colour into any generated module, committed or rendered", () => {
    const committed = readdirSync(path.join(PACKAGE, OUTPUT_DIR))
      .filter((file) => file.endsWith(".tsx"))
      .map((file) => [file, readFileSync(path.join(PACKAGE, OUTPUT_DIR, file), "utf-8")] as const);
    const rendered = [...renderIconModules()].filter(([file]) => file.endsWith(".tsx"));
    expect(committed).toHaveLength(NAMES.length);
    for (const [file, content] of [...committed, ...rendered]) {
      expect(content, file).not.toMatch(PAINT);
      expect(content, file).not.toMatch(COLOUR);
    }
  });

  // Round caps and joins, as Lucide draws them: a dot (help, info, danger, warning) is an `h.01`
  // segment, which a butt cap all but erases.
  it("draws every icon in the 24-unit box with a round, non-scaling 1.5 stroke at each optical size", () => {
    for (const name of NAMES) {
      for (const size of ICON_SIZES) {
        const svg = svgOf(name, size);
        expect(svg.getAttribute("viewBox"), name).toBe("0 0 24 24");
        expect(svg.getAttribute("stroke-width"), name).toBe("1.5");
        expect(svg.getAttribute("stroke-linecap"), name).toBe("round");
        expect(svg.getAttribute("stroke-linejoin"), name).toBe("round");
        expect(svg.children.length, name).toBeGreaterThan(0);
        for (const shape of svg.children) {
          expect(shape.getAttribute("vector-effect"), `${name}: ${shape.outerHTML}`).toBe(
            "non-scaling-stroke",
          );
        }
      }
    }
  });

  // SEC-271B-02: the geometry, pinned without the generator. Both drift checks compare the
  // generator with itself, so one that changed a shape and rewrote its modules would pass them:
  // here the DOM's own XML parser reads each source, and each icon is read as React draws it.
  it("draws exactly its source's geometry, read by the DOM's XML parser, not the generator", () => {
    const sourceDir = path.join(PACKAGE, "src/icons/source");
    const sources = readdirSync(sourceDir).flatMap((origin) =>
      readdirSync(path.join(sourceDir, origin))
        .filter((entry) => entry.endsWith(".svg"))
        .map((entry) => path.join(origin, entry)),
    );
    expect(sources.map((file) => path.basename(file, ".svg")).sort()).toEqual([...NAMES].sort());
    for (const file of sources) {
      // Every source's name is registered, which the line above checks.
      const name = path.basename(file, ".svg") as IconName;
      const text = readFileSync(path.join(sourceDir, file), "utf-8");
      const source = new DOMParser().parseFromString(text, "image/svg+xml").documentElement;
      expect([source.namespaceURI, source.tagName], file).toEqual([SVG_NS, "svg"]);
      const drawn = svgOf(name);
      // Shapes only, side by side: none nests an element or holds text.
      expect(drawn.querySelectorAll("*"), name).toHaveLength(drawn.children.length);
      expect(drawn.textContent, name).toBe("");
      for (const shape of drawn.children) {
        const where = `${name}: ${shape.outerHTML}`;
        expect(Object.keys(GEOMETRY), where).toContain(shape.tagName);
        const allowed = [...(GEOMETRY[shape.tagName] ?? []), "vector-effect"];
        const others = shape
          .getAttributeNames()
          .filter((attribute) => !allowed.includes(attribute));
        expect(others, where).toEqual([]);
      }
      expect(shapesOf(drawn), name).toEqual(shapesOf(source));
      // React's markup drops event handlers, so none may hide in the module: no JSX expression.
      const generated = readFileSync(
        path.join(PACKAGE, "src/icons/generated", `${ICON_COMPONENTS[name].name}.tsx`),
        "utf-8",
      );
      const body = generated.split(`icon="${name}">`)[1]?.split("</IconSvg>")[0];
      expect(body, name).toMatch(/^[^{}]+$/);
    }
  });
});
