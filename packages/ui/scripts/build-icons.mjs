// E05-T06: compiles the icon sources into one React component per icon, and the map by registry
// name that CMP-019 Icon draws from (16-design-system-brief.md §5), from packages/ui:
//   node scripts/build-icons.mjs          write src/icons/generated/ (deleting stale modules)
//   node scripts/build-icons.mjs --check  exit 1, naming each stale, missing or extra module
//
// A source is `src/icons/source/<origin>/<name>.svg`: `lucide/` holds vendored Lucide glyphs (ISC,
// with their LICENSE), `custom/` CandleViewer's own. A source is data, never executed, fetched or
// inlined as markup: a strict allowlist parser accepts only a 24x24 outline root and the geometry
// of path, circle, ellipse, line, polyline, polygon and rect children, and rejects anything else
// (scripts, event handlers, styles, references, colours, transforms, text, a space that is not
// XML whitespace), naming the file. A module keeps the geometry alone, each value's spacing
// collapsed to one space; `src/icons/IconSvg.tsx` draws the grid around it (the 24-unit box,
// `currentColor`, no fill, a 1.5 stroke). A Lucide source must carry its upstream licence line,
// `@license lucide-static v<version> - ISC`, which its module repeats as a legal comment (`/*!`)
// right above the component, where esbuild (tsup) and Rollup (the app's Vite build) keep it. The
// output is deterministic: sources in name order, no timestamps, each module as Prettier prints
// it. test/icons/generator.test.ts checks the drift.
//
// A custom source is CandleViewer's own, so one with a licence line fails. `<name>.sm.svg` beside
// a source is its size form: the reduced drawing `Icon` swaps in at `sm` where the 24-unit master
// closes up at 12 px (E05-D02 §6 J24), with a module of its own and an `ICON_FORMS` entry. It is
// never a registry name.

import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const SOURCE_DIR = "src/icons/source";
export const OUTPUT_DIR = "src/icons/generated";
/** Where a glyph may come from; the registry's `source` names the same origin. */
export const ORIGINS = ["custom", "lucide"];
/** Files an origin directory may hold besides its sources. */
const NOTICES = new Set(["LICENSE"]);
/** `<name>.svg`, or `<name>.<size>.svg` at a size J24 gives a reduced form: its name, its size. */
const SOURCE_FILE = /^([^.]*)(?:\.(sm))?\.svg$/;
/** packages/config/prettier.config.mjs: modules are written as Prettier prints them. */
const PRINT_WIDTH = 100;
const NAME = /^[a-z][\da-z]*(?:-[\da-z]+)*$/;
/** An object key Prettier prints unquoted. */
const NAME_KEY = /^[a-z][\da-z]*$/;
/** XML whitespace (space, tab, CR, LF): a run of it collapses to one space in a value. */
const SPACING = /[\t\n\r ]+/g;
/** Whitespace that is not XML's, a no-break space (U+00A0) among it: no source holds any. */
const NOT_XML_SPACE = /[^\S\t\n\r ]/;
const NUMBER = /^-?(?:\d+(?:\.\d*)?|\.\d+)$/;
// Geometry spaced as attributesOf leaves it: single ASCII spaces only.
const PATH_DATA = /^[\d ,.AaCcHhLlMmQqSsTtVvZz-]+$/;
const POINTS = /^[\d ,.-]+$/;
const SVG_NS = "http://www.w3.org/2000/svg";
/** A comment before the root, free of markup and of `--`: its text. */
const COMMENT = /^\s*<!--((?:(?!--)[^<>])*)-->/;
/** The one licence line a source may carry, as lucide-static writes it: what a module repeats. */
const LICENCE = /^@license (lucide-static v\d+\.\d+\.\d+ - ISC)$/;

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

/**
 * `[name, value]` pairs of a tag's attribute text, which the tag pattern has already shaped. Each
 * value's spacing collapses to one space, trimmed: Prettier would print an element whose value
 * spans lines otherwise than `element` does.
 */
function attributesOf(text, where, fail) {
  const found = [];
  for (const [, name, value] of text.matchAll(/\s+([^\s/<=>]+)="([^"&<>]*)"/g)) {
    if (found.some(([seen]) => seen === name)) fail(`${where} repeats ${name}`);
    found.push([name, value.replace(SPACING, " ").trim()]);
  }
  return found;
}

/**
 * One source's geometry, `[tag, [[attribute, value], ...]]` per child in order, the Lucide glyph
 * its `class` names and its licence line's `lucide-static v<version> - ISC` (each `null` without
 * one). Anything off the allowlist fails, naming `file`.
 */
export function parseIconSource(text, file) {
  const fail = (reason) => {
    throw new IconSourceError(`${file}: ${reason}`);
  };
  // XML whitespace alone spaces a source, so each `\s` below is one of its four characters.
  const space = NOT_XML_SPACE.exec(text);
  if (space) {
    const code = space[0].charCodeAt(0).toString(16).toUpperCase().padStart(4, "0");
    const line = text.slice(0, space.index).split("\n").length;
    fail(`U+${code} on line ${line} is not XML whitespace (space, tab, CR or LF)`);
  }
  let rest = text;
  const take = (pattern) => {
    const match = pattern.exec(rest);
    if (match) rest = rest.slice(match[0].length);
    return match;
  };
  // Leading comments only: among them at most one licence line, Lucide's, never dropped unread.
  let licence = null;
  for (let comment = take(COMMENT); comment; comment = take(COMMENT)) {
    if (!comment[1].includes("@license")) continue;
    if (licence !== null) fail("repeats its @license line");
    licence =
      LICENCE.exec(comment[1].trim())?.[1] ??
      fail('its @license line is not "@license lucide-static v<version> - ISC"');
  }
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
  return { glyph: glyph ?? null, licence, children };
}

/** `chevrons-up-down` → `ChevronsUpDownIcon`. */
export const componentName = (name) =>
  `${name
    .split("-")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join("")}Icon`;

/** A source's drawings: itself, then each size form, `drawn` naming the component of each. */
const drawings = (source) => [
  { ...source, drawn: source.name },
  ...Object.entries(source.forms ?? {}).map(([size, file]) => {
    return { ...source, file, drawn: `${source.name}-${size}` };
  }),
];
/** A registry name as an object key, as Prettier prints it. */
const key = (name) => (NAME_KEY.test(name) ? name : `"${name}"`);

/**
 * Every source, sorted by name, with its size forms by size (`forms`) where it has any; a misplaced
 * file, a bad name, a form without its master or a name used twice fails.
 */
export function iconSources(root = PACKAGE) {
  const sources = [];
  const forms = [];
  for (const origin of readdirSync(path.join(root, SOURCE_DIR)).sort()) {
    if (!ORIGINS.includes(origin)) {
      throw new IconSourceError(`${SOURCE_DIR}/${origin}: not an origin (${ORIGINS.join(", ")})`);
    }
    for (const entry of readdirSync(path.join(root, SOURCE_DIR, origin)).sort()) {
      const file = `${SOURCE_DIR}/${origin}/${entry}`;
      if (NOTICES.has(entry)) continue;
      const [, name = "", size] = SOURCE_FILE.exec(entry) ?? [];
      if (!NAME.test(name)) {
        throw new IconSourceError(`${file}: not a kebab-case <name>.svg or <name>.sm.svg`);
      }
      if (size === undefined) sources.push({ name, origin, file });
      else forms.push({ name, origin, file, size });
    }
  }
  sources.sort((a, b) => (a.name < b.name ? -1 : 1));
  for (const { name, origin, file, size } of forms) {
    const master = sources.find((source) => source.name === name && source.origin === origin);
    if (!master) {
      throw new IconSourceError(`${file}: no ${name}.svg beside it, the master it redraws`);
    }
    master.forms = { ...master.forms, [size]: file };
  }
  const components = new Map();
  for (const { drawn, file } of sources.flatMap(drawings)) {
    const component = componentName(drawn).toLowerCase();
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

function iconModule({ name, drawn, file }, licence, geometry) {
  const size = drawn.slice(name.length + 1);
  return [
    `${HEADER}. Its source is`,
    `// ${file} (packages/ui/README.md, "Icons").`,
    'import type { JSX } from "react";',
    'import { IconSvg, type GlyphProps } from "../IconSvg.js";',
    "",
    // Above the component, not the imports: Rollup drops a comment that leads an import it removes.
    ...(licence === null
      ? []
      : [`/*! @license ${licence} (see packages/ui/${SOURCE_DIR}/lucide/LICENSE) */`]),
    size === ""
      ? `/** The \`${name}\` icon: its meaning is its entry in \`../registry.ts\`. */`
      : `/** The \`${name}\` icon at \`${size}\`: the reduced form \`Icon\` draws there (E05-D02 §6 J24). */`,
    `export function ${componentName(drawn)}(props: GlyphProps): JSX.Element {`,
    "  return (",
    `    <IconSvg {...props} icon="${name}">`,
    ...geometry.flatMap(([tag, attributes]) => element(tag, attributes, 6)),
    "    </IconSvg>",
    "  );",
    "}",
    "",
  ].join("\n");
}

/** The maps `Icon` draws from: INTERNAL, as the per-icon modules are (no barrel exports them). */
function byName(sources) {
  const forms = sources.filter((source) => source.forms !== undefined);
  const entry = ({ name, forms: sized }) => {
    const pairs = Object.keys(sized).map((size) => `${size}: ${componentName(`${name}-${size}`)}`);
    return `  ${key(name)}: { ${pairs.join(", ")} },`;
  };
  return [
    `${HEADER} (packages/ui/README.md, "Icons").`,
    "// Every registered icon's component, keyed by registry name: INTERNAL, `Icon` (CMP-019) is the",
    "// public way to draw one.",
    'import type { JSX } from "react";',
    'import type { GlyphProps } from "../IconSvg.js";',
    'import type { IconName } from "../registry.js";',
    ...sources
      .flatMap(drawings)
      .map(
        ({ drawn }) => `import { ${componentName(drawn)} } from "./${componentName(drawn)}.js";`,
      ),
    "",
    "export const ICON_COMPONENTS = {",
    ...sources.map(({ name }) => `  ${key(name)}: ${componentName(name)},`),
    "} as const satisfies Readonly<Record<IconName, (props: GlyphProps) => JSX.Element>>;",
    "",
    "// Each name's size forms by size: the reduced drawings `Icon` swaps in (E05-D02 §6 J24).",
    ...(forms.length === 0
      ? ["export const ICON_FORMS = {} as const;"]
      : ["export const ICON_FORMS = {", ...forms.map(entry), "} as const;"]),
    "",
  ].join("\n");
}

/** Every generated module: its path in the package → its content. */
export function renderIconModules(root = PACKAGE) {
  const sources = iconSources(root);
  const modules = new Map();
  for (const source of sources.flatMap(drawings)) {
    const { licence, children } = parseIconSource(
      readFileSync(path.join(root, source.file), "utf-8"),
      source.file,
    );
    if (source.origin === "lucide" && licence === null) {
      throw new IconSourceError(
        `${source.file}: a Lucide source needs its "@license lucide-static v<version> - ISC" line`,
      );
    }
    if (source.origin === "custom" && licence !== null) {
      throw new IconSourceError(
        `${source.file}: a custom source is CandleViewer's own: it carries no @license line`,
      );
    }
    modules.set(
      `${OUTPUT_DIR}/${componentName(source.drawn)}.tsx`,
      iconModule(source, licence, children),
    );
  }
  modules.set(`${OUTPUT_DIR}/components.ts`, byName(sources));
  return modules;
}

/**
 * The command line on the package at `root`: writes the modules, or with `--check` reports drift.
 * Returns the exit code; a rejected source is one line naming the file, not a stack trace.
 */
export function run(args, root = PACKAGE) {
  if (args.some((arg) => arg !== "--check")) {
    console.error("usage: node scripts/build-icons.mjs [--check]");
    return 1;
  }
  let modules;
  try {
    modules = renderIconModules(root);
  } catch (error) {
    if (!(error instanceof IconSourceError)) throw error;
    console.error(error.message);
    return 1;
  }
  const outDir = path.join(root, OUTPUT_DIR);
  const read = (file) =>
    existsSync(path.join(root, file)) ? readFileSync(path.join(root, file), "utf-8") : null;
  const extra = (existsSync(outDir) ? readdirSync(outDir) : [])
    .map((entry) => `${OUTPUT_DIR}/${entry}`)
    .filter((file) => !modules.has(file));
  const stale = [...modules]
    .filter(([file, content]) => read(file) !== content)
    .map(([file]) => file);
  if (args.includes("--check")) {
    for (const file of stale) console.error(`stale or missing: ${file}`);
    for (const file of extra) console.error(`not generated: ${file}`);
    if (stale.length + extra.length === 0) return 0;
    console.error(
      'Regenerate: pnpm --filter @candleviewer/ui build:icons (packages/ui/README.md, "Icons")',
    );
    return 1;
  }
  mkdirSync(outDir, { recursive: true });
  for (const file of stale) writeFileSync(path.join(root, file), modules.get(file));
  for (const file of extra) rmSync(path.join(root, file));
  console.log(`[icons] ${modules.size} modules: ${stale.length} written, ${extra.length} deleted`);
  return 0;
}

// Run only as a command, never on import (the tests import it). argv[1] holds the path as typed
// (under `node -e`, any argument), and Node loads the module from its real path: both compare
// real, so a command run through a symlink or a junction cannot exit 0 having checked nothing.
const entry = process.argv[1];
if (
  entry &&
  existsSync(entry) &&
  realpathSync(entry) === realpathSync(fileURLToPath(import.meta.url))
) {
  process.exitCode = run(process.argv.slice(2));
}
