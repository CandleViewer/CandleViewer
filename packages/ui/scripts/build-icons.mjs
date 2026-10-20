// E05-T06: compiles the icon sources into one tree-shakeable React component per icon
// (16-design-system-brief.md §5), from packages/ui:
//   node scripts/build-icons.mjs          write src/icons/generated/ (deleting stale modules)
//   node scripts/build-icons.mjs --check  exit 1, naming each stale, missing or extra module
//
// A source is `src/icons/source/<origin>/<name>.svg`: `lucide/` holds vendored Lucide glyphs (ISC,
// with their LICENSE), `custom/` CandleViewer's own. A source is data, never executed, fetched or
// inlined as markup: a strict allowlist parser accepts only a 24x24 outline root and the geometry of
// path, circle, ellipse, line, polyline, polygon and rect children, and rejects anything else
// (scripts, event handlers, styles, references, colours, transforms, text), naming the file. A
// module keeps the geometry alone; `src/icons/IconSvg.tsx` draws the grid around it.

import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const SOURCE_DIR = "src/icons/source";
export const OUTPUT_DIR = "src/icons/generated";
/** Where a glyph may come from; the registry's `source` names the same origin. */
export const ORIGINS = ["custom", "lucide"];
/** Files an origin directory may hold besides its sources. */
const NOTICES = new Set(["LICENSE"]);
/** packages/config/prettier.config.mjs: modules are written as Prettier prints them. */
const PRINT_WIDTH = 100;
const NAME = /^[a-z][\da-z]*(?:-[\da-z]+)*$/;
const NUMBER = /^-?(?:\d+(?:\.\d*)?|\.\d+)$/;
const PATH_DATA = /^[\d\s,.AaCcHhLlMmQqSsTtVvZz-]+$/;
const POINTS = /^[\d\s,.-]+$/;
const SVG_NS = "http://www.w3.org/2000/svg";

/** The root attributes a source may carry, each with the only values the grid accepts. */
const ROOT = new Map([
  ["xmlns", (value) => value === SVG_NS],
  ["class", (value) => /^lucide lucide-[\da-z-]+$/.test(value)],
  ["width", (value) => value === "24"],
  ["height", (value) => value === "24"],
  ["viewBox", (value) => value === "0 0 24 24"],
  ["fill", (value) => value === "none"],
  ["stroke", (value) => value === "currentColor"],
  // The grid's own 1.5 replaces it.
  ["stroke-width", (value) => NUMBER.test(value)],
  ["stroke-linecap", (value) => value === "round"],
  ["stroke-linejoin", (value) => value === "round"],
]);

/** Each geometry element: its attributes, each with its value syntax, and the ones it needs. */
const GEOMETRY = new Map([
  ["path", { syntax: { d: PATH_DATA }, required: ["d"] }],
  ["circle", { syntax: { cx: NUMBER, cy: NUMBER, r: NUMBER }, required: ["r"] }],
  [
    "ellipse",
    { syntax: { cx: NUMBER, cy: NUMBER, rx: NUMBER, ry: NUMBER }, required: ["rx", "ry"] },
  ],
  [
    "line",
    {
      syntax: { x1: NUMBER, y1: NUMBER, x2: NUMBER, y2: NUMBER },
      required: ["x1", "y1", "x2", "y2"],
    },
  ],
  ["polyline", { syntax: { points: POINTS }, required: ["points"] }],
  ["polygon", { syntax: { points: POINTS }, required: ["points"] }],
  [
    "rect",
    {
      syntax: { x: NUMBER, y: NUMBER, width: NUMBER, height: NUMBER, rx: NUMBER, ry: NUMBER },
      required: ["width", "height"],
    },
  ],
]);

/** A source the generator refuses; the message starts with the file. */
export class IconSourceError extends Error {}

/** `[name, value]` pairs of a tag's attribute text, which the tag pattern has already shaped. */
function attributesOf(text, where, fail) {
  const found = [];
  for (const [, name, value] of text.matchAll(/\s+([^\s/<=>]+)="([^"&<>]*)"/g)) {
    if (found.some(([seen]) => seen === name)) fail(`${where} repeats ${name}`);
    found.push([name, value]);
  }
  return found;
}

/**
 * One source's geometry, `[tag, [[attribute, value], ...]]` per child in order, and the Lucide
 * glyph its `class` names (`null` without one). Anything off the allowlist fails, naming `file`.
 */
export function parseIconSource(text, file) {
  const fail = (reason) => {
    throw new IconSourceError(`${file}: ${reason}`);
  };
  let rest = text;
  const take = (pattern) => {
    const match = pattern.exec(rest);
    if (match) rest = rest.slice(match[0].length);
    return match;
  };
  // Leading comments only (the upstream licence line), free of markup and of `--`.
  while (take(/^\s*<!--(?:(?!--)[^<>])*-->/));
  const root =
    take(/^\s*<svg((?:\s+[^\s/<=>]+="[^"&<>]*")*)\s*>/) ?? fail("expected an <svg> root first");
  const rootAttributes = attributesOf(root[1], "<svg>", fail);
  for (const [name, value] of rootAttributes) {
    const accepts = ROOT.get(name) ?? fail(`<svg> may not carry ${name}`);
    if (!accepts(value)) fail(`<svg> ${name}="${value}" is off the 24x24 outline grid`);
  }
  if (!rootAttributes.some(([name]) => name === "viewBox")) fail('<svg> needs viewBox="0 0 24 24"');
  const children = [];
  while (!take(/^\s*<\/svg>\s*$/)) {
    const child =
      take(/^\s*<([a-z]+)((?:\s+[^\s/<=>]+="[^"&<>]*")*)\s*\/>/) ??
      fail(`expected a self-closing geometry element or </svg> at "${rest.trim().slice(0, 32)}"`);
    const [, tag, text] = child;
    const shape = GEOMETRY.get(tag) ?? fail(`<${tag}> is not a geometry element`);
    const attributes = attributesOf(text, `<${tag}>`, fail);
    for (const [name, value] of attributes) {
      if (!Object.hasOwn(shape.syntax, name)) fail(`<${tag}> may not carry ${name}`);
      if (!shape.syntax[name].test(value)) fail(`<${tag}> ${name}="${value}" is not geometry`);
    }
    for (const name of shape.required) {
      if (!attributes.some(([seen]) => seen === name)) fail(`<${tag}> needs ${name}`);
    }
    children.push([tag, attributes]);
  }
  if (children.length === 0) fail("draws nothing");
  const glyph = rootAttributes
    .find(([name]) => name === "class")?.[1]
    .slice("lucide lucide-".length);
  return { glyph: glyph ?? null, children };
}

/** `chevrons-up-down` → `ChevronsUpDownIcon`. */
export const componentName = (name) =>
  `${name
    .split("-")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join("")}Icon`;

/** Every source, sorted by name; a misplaced file, a bad name or a name used twice fails. */
export function iconSources(root = PACKAGE) {
  const sources = [];
  for (const origin of readdirSync(path.join(root, SOURCE_DIR)).sort()) {
    if (!ORIGINS.includes(origin)) {
      throw new IconSourceError(`${SOURCE_DIR}/${origin}: not an origin (${ORIGINS.join(", ")})`);
    }
    for (const entry of readdirSync(path.join(root, SOURCE_DIR, origin)).sort()) {
      const file = `${SOURCE_DIR}/${origin}/${entry}`;
      if (NOTICES.has(entry)) continue;
      const name = entry.endsWith(".svg") ? entry.slice(0, -".svg".length) : "";
      if (!NAME.test(name)) throw new IconSourceError(`${file}: not a kebab-case <name>.svg`);
      sources.push({ name, origin, file });
    }
  }
  sources.sort((a, b) => (a.name < b.name ? -1 : 1));
  const components = new Map();
  for (const { name, file } of sources) {
    const component = componentName(name).toLowerCase();
    if (components.has(component)) {
      throw new IconSourceError(`${file}: its component clashes with ${components.get(component)}`);
    }
    components.set(component, file);
  }
  return sources;
}

/** One JSX element: on one line when it fits the print width, else one attribute per line. */
function element(tag, attributes, indent) {
  const pad = " ".repeat(indent);
  const props = [...attributes.map(([n, v]) => `${n}="${v}"`), 'vectorEffect="non-scaling-stroke"'];
  const line = `${pad}<${tag} ${props.join(" ")} />`;
  if (line.length <= PRINT_WIDTH) return [line];
  return [`${pad}<${tag}`, ...props.map((prop) => `${pad}  ${prop}`), `${pad}/>`];
}

const HEADER = "// GENERATED by packages/ui/scripts/build-icons.mjs: do not edit";

function iconModule({ name, file }, geometry) {
  return [
    `${HEADER}. Its source is`,
    `// ${file} (packages/ui/README.md, "Icons").`,
    'import type { JSX } from "react";',
    'import { IconSvg, type IconProps } from "../IconSvg.js";',
    "",
    `/** The \`${name}\` icon: its meaning is its entry in \`../registry.ts\`. */`,
    `export function ${componentName(name)}(props: IconProps): JSX.Element {`,
    "  return (",
    `    <IconSvg {...props} icon="${name}">`,
    ...geometry.flatMap(([tag, attributes]) => element(tag, attributes, 6)),
    "    </IconSvg>",
    "  );",
    "}",
    "",
  ].join("\n");
}

function barrel(sources) {
  return [
    `${HEADER} (packages/ui/README.md, "Icons").`,
    "// One module per icon, so a bundle carries only the icons it imports.",
    ...sources.map(
      ({ name }) => `export { ${componentName(name)} } from "./${componentName(name)}.js";`,
    ),
    "",
  ].join("\n");
}

function byName(sources) {
  return [
    `${HEADER} (packages/ui/README.md, "Icons").`,
    'import type { JSX } from "react";',
    'import type { IconProps } from "../IconSvg.js";',
    'import type { IconName } from "../registry.js";',
    ...sources.map(
      ({ name }) => `import { ${componentName(name)} } from "./${componentName(name)}.js";`,
    ),
    "",
    "/**",
    " * Every icon's component by its registry name, for CMP-019 Icon and the Storybook set. It bundles",
    " * the whole set: app code imports the component it draws (`CloseIcon`), never this map.",
    " */",
    "export const ICON_COMPONENTS = {",
    ...sources.map(
      ({ name }) => `  ${NAME_KEY.test(name) ? name : `"${name}"`}: ${componentName(name)},`,
    ),
    "} as const satisfies Record<IconName, (props: IconProps) => JSX.Element>;",
    "",
  ].join("\n");
}
/** An object key Prettier prints unquoted. */
const NAME_KEY = /^[a-z][\da-z]*$/;

/** Every generated module: its path in the package → its content. */
export function renderIconModules(root = PACKAGE) {
  const sources = iconSources(root);
  const modules = new Map();
  for (const source of sources) {
    const { children } = parseIconSource(
      readFileSync(path.join(root, source.file), "utf-8"),
      source.file,
    );
    modules.set(`${OUTPUT_DIR}/${componentName(source.name)}.tsx`, iconModule(source, children));
  }
  modules.set(`${OUTPUT_DIR}/components.ts`, byName(sources));
  modules.set(`${OUTPUT_DIR}/index.ts`, barrel(sources));
  return modules;
}

function main(args) {
  if (args.some((arg) => arg !== "--check")) {
    throw new Error("usage: node scripts/build-icons.mjs [--check]");
  }
  const modules = renderIconModules();
  const outDir = path.join(PACKAGE, OUTPUT_DIR);
  const read = (file) =>
    existsSync(path.join(PACKAGE, file)) ? readFileSync(path.join(PACKAGE, file), "utf-8") : null;
  const extra = (existsSync(outDir) ? readdirSync(outDir) : [])
    .map((entry) => `${OUTPUT_DIR}/${entry}`)
    .filter((file) => !modules.has(file));
  const stale = [...modules]
    .filter(([file, content]) => read(file) !== content)
    .map(([file]) => file);
  if (args.includes("--check")) {
    for (const file of stale) console.error(`stale or missing: ${file}`);
    for (const file of extra) console.error(`not generated: ${file}`);
    if (stale.length + extra.length > 0) {
      console.error('Regenerate: node scripts/build-icons.mjs (packages/ui/README.md, "Icons")');
      process.exitCode = 1;
    }
    return;
  }
  mkdirSync(outDir, { recursive: true });
  for (const file of stale) writeFileSync(path.join(PACKAGE, file), modules.get(file));
  for (const file of extra) rmSync(path.join(PACKAGE, file));
  console.log(`[icons] ${modules.size} modules: ${stale.length} written, ${extra.length} deleted`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2));
}
