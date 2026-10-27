// @vitest-environment jsdom
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OUTPUT_DIR, renderIconModules } from "../../scripts/build-icons.mjs";
import { ICON_COMPONENTS, ICON_FORMS } from "../../src/icons/generated/components.js";
import { Icon, ICON_SIZES, ICONS, type IconName, type IconSize } from "../../src/icons/index.js";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE_DIR = path.join(PACKAGE, "src/icons/source");
const SVG_NS = "http://www.w3.org/2000/svg";
// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
/** The size forms as `Icon` reads them: by name, then by size. */
const FORMS: Partial<Record<IconName, Partial<Record<IconSize, { name: string }>>>> = ICON_FORMS;
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

// Through `Icon`, the public way to draw a glyph, which picks a size form where a name has one.
const markup = (name: IconName, size?: IconSize) =>
  renderToStaticMarkup(createElement(Icon, size === undefined ? { name } : { name, size }));
const svgOf = (name: IconName, size?: IconSize): SVGSVGElement => {
  const doc = new DOMParser().parseFromString(markup(name, size), "image/svg+xml");
  const root = doc.documentElement;
  if (!(root instanceof SVGSVGElement)) throw new Error(`${name} did not render one <svg>`);
  return root;
};
/** Each source, `<origin>/<name>.svg`, or `<origin>/<name>.<size>.svg` for a size form. */
const sourceFiles = (origin?: string) =>
  readdirSync(SOURCE_DIR)
    .filter((dir) => origin === undefined || dir === origin)
    .flatMap((dir) =>
      readdirSync(path.join(SOURCE_DIR, dir))
        .filter((entry) => entry.endsWith(".svg"))
        .map((entry) => path.join(dir, entry)),
    );
/** A source's root element, as the DOM's own XML parser reads the file. */
const sourceSvg = (file: string): Element =>
  new DOMParser().parseFromString(
    readFileSync(path.join(SOURCE_DIR, file), "utf-8"),
    "image/svg+xml",
  ).documentElement;
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

type Point = readonly [number, number];
const pairs = (values: readonly number[]): Point[] =>
  values.flatMap((x, k): Point[] => (k % 2 === 0 ? [[x, values[k + 1] ?? NaN]] : []));

/** A circular, unrotated arc's points, every degree: its centre as SVG's arc notes find it. */
function arcPoints(from: Point, [r = NaN, ry, rotation, large, sweep, x = NaN, y = NaN]: number[]) {
  if (r !== ry || rotation !== 0) throw new Error("a custom arc is circular and unrotated");
  const [dx, dy] = [(x - from[0]) / 2, (y - from[1]) / 2];
  const half = Math.hypot(dx, dy);
  const radius = Math.max(r, half); // SVG scales up a radius that cannot reach
  const offset = ((large === sweep ? -1 : 1) * Math.sqrt(radius ** 2 - half ** 2)) / half;
  const [cx, cy] = [from[0] + dx - offset * dy, from[1] + dy + offset * dx];
  const start = Math.atan2(from[1] - cy, from[0] - cx);
  let turn = Math.atan2(y - cy, x - cx) - start;
  if (sweep && turn < 0) turn += 2 * Math.PI;
  if (!sweep && turn > 0) turn -= 2 * Math.PI;
  const steps = Math.ceil(Math.abs((turn * 180) / Math.PI));
  return Array.from({ length: steps + 1 }, (_, n): Point => {
    const angle = start + (turn * n) / steps;
    return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
  });
}

/**
 * Every point a custom path's outline can reach. A custom glyph writes absolute M, L, H, V, C, A
 * and Z only: each end and Bezier control point is a number pair (a Bezier stays in their hull),
 * and each arc is circular and unrotated. Anything else fails the bounds check.
 */
function pathPoints(d: string): Point[] {
  const points: Point[] = [];
  let start: Point = [NaN, NaN];
  for (const [, command, args] of d.matchAll(/([A-Za-z])([^A-Za-z]*)/g)) {
    const values = (args?.match(/-?(?:\d+\.?\d*|\.\d+)/g) ?? []).map(Number);
    const [x, y] = points.at(-1) ?? start;
    if (command === "M") start = pairs(values)[0] ?? start;
    if (command === "M" || command === "L" || command === "C") points.push(...pairs(values));
    else if (command === "H") points.push(...values.map((h): Point => [h, y]));
    else if (command === "V") points.push(...values.map((v): Point => [x, v]));
    else if (command === "Z") points.push(start);
    else if (command !== "A")
      throw new Error(`a custom path writes M, L, H, V, C, A and Z: ${command}`);
    for (let k = 0; command === "A" && k < values.length; k += 7) {
      points.push(...arcPoints(points.at(-1) ?? start, values.slice(k, k + 7)));
    }
  }
  return points;
}

/** Every point of a shape's outline: a rect, a circle or an ellipse reaches its box. */
function outlinePoints(shape: Element): Point[] {
  const n = (attribute: string) => Number(shape.getAttribute(attribute) ?? 0);
  const [cx, cy, rx, ry] = [n("cx"), n("cy"), n("rx") || n("r"), n("ry") || n("r")];
  const box: Readonly<Record<string, number[]>> = {
    line: [n("x1"), n("y1"), n("x2"), n("y2")],
    rect: [n("x"), n("y"), n("x") + n("width"), n("y") + n("height")],
    circle: [cx - rx, cy - ry, cx + rx, cy + ry],
    ellipse: [cx - rx, cy - ry, cx + rx, cy + ry],
  };
  if (shape.tagName === "path") return pathPoints(shape.getAttribute("d") ?? "");
  const points = (shape.getAttribute("points") ?? "").trim().split(/[\s,]+/);
  return pairs(box[shape.tagName] ?? points.map(Number));
}

/** A ring's dash: a subpath of one minor arc, circular and unrotated: `M x y A r r 0 0 1 x y`. */
const DASH = /^M([\d.]+) ([\d.]+)A([\d.]+) \3 0 0 1 ([\d.]+) ([\d.]+)$/;
/** A stroke of the "≈": a move, then Beziers only. */
const WAVE = /^M[\d. ]+(?:C[\d. ]+)+$/;

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
    // One module per source: each name's 24-unit master, and each size form.
    expect(committed).toHaveLength(sourceFiles().length);
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
    // `<name>.svg` is a name's 24-unit master; `<name>.<size>.svg`, its form at that size.
    const sources = sourceFiles().map((file) => {
      const [name = "", size, ...rest] = path.basename(file, ".svg").split(".");
      return { file, name: name as IconName, size: size as IconSize | undefined, rest };
    });
    const masters = sources.filter(({ size }) => size === undefined).map(({ name }) => name);
    expect(masters.sort()).toEqual([...NAMES].sort());
    for (const { file, name, size, rest } of sources) {
      const sized = size === undefined || ICON_SIZES.includes(size);
      expect([NAMES.includes(name), sized, rest], file).toEqual([true, true, []]);
      const source = sourceSvg(file);
      expect([source.namespaceURI, source.tagName], file).toEqual([SVG_NS, "svg"]);
      const drawn = svgOf(name, size);
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
      expect(shapesOf(drawn), file).toEqual(shapesOf(source));
      // React's markup drops event handlers, so none may hide in the module: no JSX expression.
      const component = size === undefined ? ICON_COMPONENTS[name] : FORMS[name]?.[size];
      const generated = readFileSync(
        path.join(PACKAGE, OUTPUT_DIR, `${component?.name ?? file}.tsx`),
        "utf-8",
      );
      const body = generated.split(`icon="${name}">`)[1]?.split("</IconSvg>")[0];
      expect(body, name).toMatch(/^[^{}]+$/);
    }
  });

  // E05-D02 §6 J24 and E25-D05 CR-3: at 12 px the dashed ring resolves to dots, so `estimated`
  // draws its reduced form, the "≈" alone, at `sm`, and its master at every other size. A form is
  // a second drawing of its name, never a name of its own.
  it("draws a size form at its size only: estimated's at sm, its master at md, lg and by default", () => {
    const sizes = Object.entries(ICON_FORMS).map(([name, forms]) => [name, Object.keys(forms)]);
    expect(sizes).toEqual([["estimated", ["sm"]]]);
    const master = shapesOf(sourceSvg("custom/estimated.svg"));
    const reduced = svgOf("estimated", "sm");
    expect(shapesOf(reduced)).toEqual(shapesOf(sourceSvg("custom/estimated.sm.svg")));
    expect(shapesOf(reduced)).not.toEqual(master);
    expect(reduced.getAttribute("data-icon")).toBe("estimated");
    for (const size of [undefined, "md", "lg"] as const) {
      expect(shapesOf(svgOf("estimated", size)), size).toEqual(master);
    }
    // The dash is the cue that a value is inferred (E25-D05), so each drawing's structure is
    // pinned, not left to review. The master: a ring of eight arcs on one circle about (12, 12),
    // each apart from the next by more than the stroke that round caps would close up.
    const [ring, ...marks] = sourceSvg("custom/estimated.svg").children;
    const dashes = (ring?.getAttribute("d") ?? "").split(/(?=M)/);
    expect(dashes.map((dash) => DASH.test(dash))).toEqual(Array<boolean>(8).fill(true));
    const ends = dashes.map((dash) => (DASH.exec(dash) ?? []).slice(1).map(Number));
    const radius = ends[0]?.[2] ?? NaN;
    for (const [k, [x1 = NaN, y1 = NaN, r, x2 = NaN, y2 = NaN]] of ends.entries()) {
      const onRing = [r, Math.hypot(x1 - 12, y1 - 12), Math.hypot(x2 - 12, y2 - 12)];
      const near = expect.closeTo(radius, 1);
      expect(onRing, `dash ${k}`).toEqual([radius, near, near]);
      const [nx = NaN, ny = NaN] = ends[(k + 1) % ends.length] ?? [];
      expect(Math.hypot(nx - x2, ny - y2), `the gap after dash ${k}`).toBeGreaterThan(1.5);
    }
    // Inside it, the "≈": two strokes of Beziers, every point clear of the ring's stroke.
    const waves = [...marks].map((mark) => mark.getAttribute("d") ?? "");
    expect(waves).toEqual([expect.stringMatching(WAVE), expect.stringMatching(WAVE)]);
    for (const [x, y] of waves.flatMap(pathPoints)) {
      expect(Math.hypot(x - 12, y - 12), `(${x}, ${y})`).toBeLessThan(radius - 1.5);
    }
    // The sm form: the "≈" alone, with no ring: no arc, no circle.
    const alone = [...sourceSvg("custom/estimated.sm.svg").children];
    expect(alone.map((shape) => [shape.tagName, shape.getAttribute("d")])).toEqual([
      ["path", expect.stringMatching(WAVE)],
      ["path", expect.stringMatching(WAVE)],
    ]);
  });
});

describe("the custom glyphs (src/icons/source/custom/, E05-D02 §7.12)", () => {
  it("reads every point the bounds check needs, and fails on a command it does not read", () => {
    const points = pathPoints("M3 3H5V5L6 6C7 6 8 7 8 8ZM2 12A10 10 0 0 1 22 12");
    expect(points.slice(0, 8).flat()).toEqual([3, 3, 5, 3, 5, 5, 6, 6, 7, 6, 8, 7, 8, 8, 3, 3]);
    // The arc's bulge, its top at (12, 2), lies beyond its two ends.
    expect(Math.min(...points.slice(9).map(([, y]) => y))).toBeCloseTo(2, 6);
    expect(() => pathPoints("M2 2l1 1")).toThrow(/A and Z: l$/);
    expect(() => pathPoints("M2 12A10 8 0 0 1 22 12")).toThrow("circular and unrotated");
  });

  // §7.12: the stroke's outer edge never crosses the 1-unit clear margin, so every point of the
  // outline lies in [1.75, 22.25]: the margin plus half the master's 1.5 stroke.
  it("keeps every outline point, control points and arc bulges included, inside the margin", () => {
    const custom = sourceFiles("custom");
    expect(custom.length).toBeGreaterThan(0);
    for (const file of custom) {
      for (const shape of sourceSvg(file).children) {
        for (const [x, y] of outlinePoints(shape)) {
          const where = `${file}: ${shape.outerHTML} reaches (${x}, ${y})`;
          expect(Math.min(x, y) >= 1.75 && Math.max(x, y) <= 22.25, where).toBe(true);
        }
      }
    }
  });

  // A dash means estimated or absent (E25-D05), so a ring is dashed by drawing its arcs apart; and
  // §7.12 fills nothing but a dot, which no custom glyph draws. Each root states the grid's stroke,
  // 1.5 with round caps and joins, the stroke the bounds above leave half a width of margin for.
  it("dashes nothing and fills nothing, on a root stroked 1.5 with round caps and joins", () => {
    for (const file of sourceFiles("custom")) {
      const text = readFileSync(path.join(SOURCE_DIR, file), "utf-8");
      expect(text, file).not.toMatch(/dash/i);
      expect(text.match(/\bfill[\w-]*="[^"]*"/g), file).toEqual(['fill="none"']);
      const root = sourceSvg(file);
      expect(root.getAttribute("fill"), file).toBe("none");
      const stroke = (name: string) => root.getAttribute(`stroke-${name}`);
      expect(["width", "linecap", "linejoin"].map(stroke), file).toEqual(["1.5", "round", "round"]);
    }
  });
});
