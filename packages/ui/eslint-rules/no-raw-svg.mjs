// Custom ESLint rule (E05-T06): component code draws no raw `<svg>` (16-design-system-brief.md §5).
// Every glyph is an entry of the icon registry, `src/icons/registry.ts`, rendered by its generated
// component. The grid, `src/icons/IconSvg.tsx`, draws the one `<svg>`: eslint.config.mjs wires
// this rule everywhere else. `createElement("svg")`, the JSX runtime's `jsx("svg")`, the DOM's
// `createElementNS(ns, "svg")` and an SVG data URL in a string (an <img> source, a CSS background)
// count too; markup strings are `react/no-danger`'s. The rule reads names as written, so a tag
// computed at runtime (`const Tag = "svg"`) or a creator under another name
// (`const h = createElement; h("svg")`) is not read statically: review catches those.

import path from "node:path";

/** An SVG document as a data URL, whatever its encoding (`;base64`, `;utf8`, percent-encoded). */
const SVG_DATA_URL = /data:image\/svg\+xml/i;
/** Functions that create an element, by the argument holding its tag: React's, the JSX runtime's
 * and the DOM's namespaced one. */
const CREATORS = new Map([
  ["createElement", 0],
  ["jsx", 0],
  ["jsxs", 0],
  ["jsxDEV", 0],
  ["createElementNS", 1],
]);

/** The name a call's callee ends in: `createElement` for `React.createElement`. */
function calleeName(callee) {
  if (callee.type === "Identifier") return callee.name;
  if (callee.type === "MemberExpression" && !callee.computed) return callee.property.name;
  return null;
}

/** A tag's local name: `svg` for `svg`, and for the qualified `svg:svg`. */
const localName = (tag) => tag.slice(tag.lastIndexOf(":") + 1);

/** A string literal or an expression-free template literal; anything else is not static. */
function staticString(node) {
  if (node?.type === "Literal" && typeof node.value === "string") return node.value;
  if (node?.type === "TemplateLiteral" && node.expressions.length === 0) {
    return node.quasis[0].value.cooked;
  }
  return null;
}

/** @type {import("eslint").Rule.RuleModule} */
export const noRawSvg = {
  meta: {
    type: "problem",
    docs: {
      description: "Disallow raw <svg> outside the icon registry; render a registry icon instead.",
    },
    messages: {
      raw: 'Raw <svg> in {{file}}: icons come from the icon registry, packages/ui/src/icons/registry.ts. Render the icon\'s component (e.g. <CloseIcon />), or add the glyph there (packages/ui/README.md, "Icons").',
      dataUrl:
        'SVG data URL in {{file}}: icons come from the icon registry, packages/ui/src/icons/registry.ts. Render the icon\'s component (e.g. <CloseIcon />), or add the glyph there (packages/ui/README.md, "Icons").',
    },
    schema: [],
  },
  create(context) {
    const file = path.relative(context.cwd, context.filename).split(path.sep).join("/");
    const report = (node, messageId = "raw") => context.report({ node, messageId, data: { file } });
    return {
      JSXOpeningElement(node) {
        if (node.name.type === "JSXIdentifier" && node.name.name === "svg") report(node);
      },
      CallExpression(node) {
        const tagAt = CREATORS.get(calleeName(node.callee));
        const tag = tagAt === undefined ? null : staticString(node.arguments[tagAt]);
        if (tag !== null && localName(tag) === "svg") report(node);
      },
      Literal(node) {
        if (typeof node.value === "string" && SVG_DATA_URL.test(node.value)) {
          report(node, "dataUrl");
        }
      },
      TemplateElement(node) {
        if (SVG_DATA_URL.test(node.value.cooked ?? node.value.raw)) report(node, "dataUrl");
      },
    };
  },
};

export default noRawSvg;
