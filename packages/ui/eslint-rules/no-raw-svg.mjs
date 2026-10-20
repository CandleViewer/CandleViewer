// Custom ESLint rule (E05-T06): component code draws no raw `<svg>` (16-design-system-brief.md §5).
// Every glyph is an entry of the icon registry, `src/icons/registry.ts`, rendered by its generated
// component. The registry's own modules (`src/icons/**`) draw the one `<svg>`: eslint.config.mjs
// wires this rule outside them. `createElement("svg")` and the JSX runtime's `jsx("svg")` count too.

import path from "node:path";

/** Functions that create an element from a tag name: React's, and the JSX runtime's. */
const CREATORS = new Set(["createElement", "jsx", "jsxs", "jsxDEV"]);

/** The name a call's callee ends in: `createElement` for `React.createElement`. */
function calleeName(callee) {
  if (callee.type === "Identifier") return callee.name;
  if (callee.type === "MemberExpression" && !callee.computed) return callee.property.name;
  return null;
}

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
    },
    schema: [],
  },
  create(context) {
    const file = path.relative(context.cwd, context.filename).split(path.sep).join("/");
    const report = (node) => context.report({ node, messageId: "raw", data: { file } });
    return {
      JSXOpeningElement(node) {
        if (node.name.type === "JSXIdentifier" && node.name.name === "svg") report(node);
      },
      CallExpression(node) {
        if (CREATORS.has(calleeName(node.callee)) && staticString(node.arguments[0]) === "svg") {
          report(node);
        }
      },
    };
  },
};

export default noRawSvg;
