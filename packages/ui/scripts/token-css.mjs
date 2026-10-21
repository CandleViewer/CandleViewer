// How the build writes design tokens as CSS custom properties, and the check that the CSS is valid
// (#3422). `build-tokens.mjs` writes `build/css/tokens.<theme>.css` through `cssDeclarations`, and
// `checkCss` checks each file before it is written.
//
// A scalar token is one declaration. The two composite types the sources have are written as plain
// CSS, never as JSON (JSON in a custom property is no CSS: esbuild, the production minifier, warns
// on it and serves the property broken):
//   shadow      one declaration holding a `box-shadow` list, `[inset ]<x> <y> <blur> <spread> <colour>`
//               with layers joined by `, ` and a bare number a length in px, as in
//               `--elevation-1: 0px 1px 2px 0px #00000066`.
//   typography  one declaration per field (`--type-ui-label-font-size: 12px`), not one `font`
//               shorthand: the shorthand cannot carry letter-spacing. The composite's own name
//               (`--type-ui-label`) is not written.
// Any other object value has no CSS form here and fails the build. So does a name that is not a
// custom-property ident, and a value the minifier accepts but the browser would misread: one that
// would end or escape its declaration (`;`, a brace, a comment delimiter, a control character, a
// trailing backslash, which escapes the `;` after it), a `!` (the declaration would become
// `!important`, or invalid), or brackets that do not pair up (the browser drops the property).
//
// Error code (docs/plan/16-design-system-brief.md §11): TOKENS-E004 invalid CSS output, thrown for
// a token the writer cannot serialise or would let the browser misread, and for a theme's CSS that
// esbuild warns about or minifies to an empty custom property.
//
// esbuild is an exact-pinned devDependency of packages/ui: the version Vite resolves in
// pnpm-lock.yaml for its CSS minifier, so the check reads the CSS as the production bundle does,
// as long as apps/web keeps Vite's default CSS minifier (esbuild; its vite.config.ts sets neither
// `build.cssMinify` nor `css.transformer`). Keep the two versions equal when Vite moves to another
// esbuild; a unit test pins them.

/** TOKENS-E004 as a thrown error. */
const invalid = (message) => new Error(`TOKENS-E004 invalid CSS output: ${message}`);
/** A token name or field as a message shows it: quoted, any control character escaped. */
const quoted = (text) => JSON.stringify(String(text));

const asText = (value) => String(value).trim();

const NUMBER = /^-?(?:\d+(?:\.\d+)?|\.\d+)$/;

/**
 * The length writer for a property that takes `units`: a bare number is a length in px, a number
 * with one of the units (`0.75rem`) stays as written, and anything else fails.
 */
function lengthIn(units) {
  const form = new RegExp(`^-?(?:\\d+(?:\\.\\d+)?|\\.\\d+)(?:${units.join("|")})$`);
  return (value, name = "(unnamed token)") => {
    const text = asText(value);
    const css = NUMBER.test(text) ? `${text}px` : text;
    if (!form.test(css))
      throw invalid(`token ${quoted(name)} has a length with no CSS form: ${quoted(text)}`);
    return css;
  };
}
/** `box-shadow` takes no percentage; a font size and a letter spacing do. */
const shadowLength = lengthIn(["px", "rem", "em"]);
const typeLength = lengthIn(["px", "rem", "em", "%"]);

const SHADOW_LENGTHS = ["offsetX", "offsetY", "blur", "spread"];
const SHADOW_FIELDS = [...SHADOW_LENGTHS, "color", "inset"];
/** `inset` as DTCG writes it: a boolean (or its string), absent for an outer shadow. */
const INSET = new Map([
  [true, true],
  ["true", true],
  [false, false],
  ["false", false],
  [undefined, false],
]);

function shadowLayer(layer, name) {
  if (layer === null || typeof layer !== "object" || Array.isArray(layer)) {
    throw invalid(`shadow token ${quoted(name)} has a layer that is not an object`);
  }
  const unknown = Object.keys(layer).filter((field) => !SHADOW_FIELDS.includes(field));
  if (unknown.length > 0) {
    throw invalid(
      `shadow token ${quoted(name)} has field(s) with no CSS form: ${unknown.map(quoted).join(", ")}`,
    );
  }
  for (const field of [...SHADOW_LENGTHS, "color"]) {
    if (layer[field] === undefined || asText(layer[field]) === "") {
      throw invalid(`shadow token ${quoted(name)} has no ${field}`);
    }
  }
  if (!INSET.has(layer.inset))
    throw invalid(`shadow token ${quoted(name)} has an inset that is not true or false`);
  return [
    ...(INSET.get(layer.inset) ? ["inset"] : []),
    ...SHADOW_LENGTHS.map((field) => shadowLength(layer[field], name)),
    asText(layer.color),
  ].join(" ");
}

/** A shadow `$value` (one layer, or a list of layers, outermost first) as a `box-shadow` value. */
function shadowCss(value, name) {
  const layers = Array.isArray(value) ? value : [value];
  if (layers.length === 0) throw invalid(`shadow token ${quoted(name)} has no layer`);
  return layers.map((layer) => shadowLayer(layer, name)).join(", ");
}

/** Generic families are keywords: quoted, they would name a font instead. */
const GENERIC_FAMILY =
  /^(?:serif|sans-serif|monospace|cursive|fantasy|system-ui|ui-(?:serif|sans-serif|monospace|rounded)|emoji|math|fangsong)$/i;
const CSS_WIDE_KEYWORD = /^(?:inherit|initial|unset|revert|revert-layer|default)$/i;

/** A family name, quoted unless it is a generic keyword or one plain identifier (`Inter`). */
function familyName(name) {
  const text = asText(name);
  if (GENERIC_FAMILY.test(text)) return text;
  if (/^[A-Za-z_][\w-]*$/.test(text) && !CSS_WIDE_KEYWORD.test(text)) return text;
  return `"${text.replace(/["\\]/g, "\\$&")}"`;
}

/** A `font-family` list from a family name or an array of them. */
const fontFamily = (value) => (Array.isArray(value) ? value : [value]).map(familyName).join(", ");

/**
 * The DTCG typography fields in the order their parts are written, each with the custom property
 * suffix and how its value becomes CSS: a size and a spacing get px when unitless; a weight and a
 * line-height (a unitless ratio, or a dimension that keeps its unit) stay as written.
 */
const TYPOGRAPHY_PARTS = [
  ["fontFamily", "font-family", fontFamily],
  ["fontSize", "font-size", typeLength],
  ["fontWeight", "font-weight", asText],
  ["letterSpacing", "letter-spacing", typeLength],
  ["lineHeight", "line-height", asText],
];

/** `[[suffix, css]]` of a typography `$value`: one entry per field it has, in `TYPOGRAPHY_PARTS` order. */
function typographyParts(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw invalid(`typography token ${quoted(name)} is not an object of fields`);
  }
  const unknown = Object.keys(value).filter(
    (field) => !TYPOGRAPHY_PARTS.some(([known]) => known === field),
  );
  if (unknown.length > 0) {
    throw invalid(
      `typography token ${quoted(name)} has field(s) with no CSS part: ${unknown.map(quoted).join(", ")}`,
    );
  }
  const parts = TYPOGRAPHY_PARTS.filter(([field]) => value[field] !== undefined).map(
    ([field, suffix, toCss]) => [suffix, toCss(value[field], name)],
  );
  if (parts.length === 0) throw invalid(`typography token ${quoted(name)} has no field`);
  return parts;
}

/**
 * `;`, a brace, a comment delimiter, or a backslash at the end (it escapes the `;` written after
 * it): each would end or escape a declaration.
 */
const BREAKS_OUT = /[;{}]|\/\*|\*\/|\\$/;
/** A control character (U+0000 to U+001F, U+007F), which would break the declaration or its line. */
const hasControl = (text) =>
  [...text].some((ch) => ch.charCodeAt(0) < 0x20 || ch.charCodeAt(0) === 0x7f);

/**
 * Whether the `(`, `)`, `[` and `]` of `css` fail to pair up. esbuild warns on a `(` left open, but
 * not on a `)` or `]` that closes nothing, and the browser drops a custom property holding one
 * (css-variables-1). Quotes are not parsed, so a bracket in a quoted family name fails closed.
 */
function unpaired(css) {
  const closers = [];
  for (const ch of css) {
    if (ch === "(") closers.push(")");
    else if (ch === "[") closers.push("]");
    else if ((ch === ")" || ch === "]") && closers.pop() !== ch) return true;
  }
  return closers.length > 0;
}

/** `css`, unless the browser would read the declaration it is written into otherwise (TOKENS-E004). */
function contained(css, name) {
  if (BREAKS_OUT.test(css) || hasControl(css)) {
    throw invalid(`token ${quoted(name)} has a value that would end or escape its CSS declaration`);
  }
  if (css.includes("!")) {
    throw invalid(
      `token ${quoted(name)} has a value with a "!", which would make its declaration important or invalid`,
    );
  }
  if (unpaired(css)) {
    throw invalid(
      `token ${quoted(name)} has a value whose brackets do not pair up, which the browser would drop`,
    );
  }
  return css;
}

/**
 * The CSS value of one resolved token that is a single declaration. `name` only labels errors. A
 * typography token is several declarations (see `cssDeclarations`), so it never comes through here.
 */
export function cssValue(token, name = "(unnamed token)") {
  return contained(rawCssValue(token, name), name);
}

function rawCssValue(token, name) {
  const v = token.$value;
  if (token.$type === "shadow") return shadowCss(v, name);
  if (v !== null && typeof v === "object" && !Array.isArray(v)) {
    throw invalid(
      `token ${quoted(name)} ($type ${token.$type}) is an object, which has no CSS form; only shadow and typography tokens do`,
    );
  }
  if (Array.isArray(v)) {
    if (v.some((item) => item !== null && typeof item === "object")) {
      throw invalid(
        `token ${quoted(name)} ($type ${token.$type}) is a list holding an object, which has no CSS form`,
      );
    }
    return v.join(", ");
  }
  if (
    typeof v === "string" &&
    /^\d+(\.\d+)?$/.test(v) &&
    ["spacing", "sizing", "borderRadius"].includes(token.$type)
  ) {
    return `${v}px`;
  }
  return String(v);
}

/** A custom property's name: `--` then ident characters only (a token path's dots become dashes). */
const CUSTOM_PROPERTY = /^--[\w-]+$/;

/** `[[--property, css]]` for one resolved token: one entry, or one per field for a typography token. */
export function cssDeclarations(name, token) {
  const property = `--${name.replace(/\./g, "-")}`;
  if (!CUSTOM_PROPERTY.test(property)) {
    throw invalid(
      `token ${quoted(name)} has a name that is not a custom-property name (letters, digits, "_", "-" and "." only)`,
    );
  }
  if (token.$type === "typography") {
    return typographyParts(token.$value, name).map(([suffix, css]) => [
      `${property}-${suffix}`,
      contained(css, name),
    ]);
  }
  return [[property, cssValue(token, name)]];
}

/** esbuild prints a custom property that is empty once minified as `--name:;` (or `--name: ;`). */
const EMPTY_CUSTOM_PROPERTY = /(--[\w-]+):\s*(?=[;}]|$)/g;

/** One esbuild message as a line that names the custom property it is about (else the file). */
function problemText({ text, location }, file) {
  if (!location) return `${file}: ${text}`;
  const property = /^\s*(--[\w-]+)\s*:/.exec(location.lineText)?.[1];
  return `${property ?? file} (line ${location.line}): ${text}`;
}

/**
 * What is wrong with `css`, one line each: every warning esbuild gives while minifying it as the
 * production bundle does (`loader: "css"`; it warns `css-syntax-error` on a value it cannot parse), and
 * every custom property that is empty once minified. `[]` for clean CSS. esbuild is imported here, not
 * at the top, so a script that only loads the token sets (the contrast gate) does not load it.
 */
export async function cssProblems(css, file) {
  const { transform } = await import("esbuild");
  let result;
  try {
    result = await transform(css, {
      loader: "css",
      minify: true,
      sourcefile: file,
      logLevel: "silent",
    });
  } catch (error) {
    if (!Array.isArray(error?.errors) || error.errors.length === 0) throw error;
    return error.errors.map((message) => problemText(message, file));
  }
  return [
    ...result.warnings.map((message) => problemText(message, file)),
    ...[...result.code.matchAll(EMPTY_CUSTOM_PROPERTY)].map(
      ([, property]) => `${property}: empty once minified`,
    ),
  ];
}

/** Throws TOKENS-E004, naming every offending custom property, unless `css` minifies cleanly. */
export async function checkCss(css, file) {
  const problems = await cssProblems(css, file);
  if (problems.length === 0) return;
  throw invalid(
    `${file} does not minify cleanly (${problems.length}):\n${problems.map((line) => `  ${line}`).join("\n")}`,
  );
}
