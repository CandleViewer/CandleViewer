// Custom ESLint rule: a story file's default export (its CSF meta) carries a static `title` under a
// band of docs/plan/15-component-catalogue.md §0.3 rule 8, or under `Foundations/` for what is not a
// catalogue component. A title derived from the file path is outside every band: an error too.

/** The catalogue's six bands (§0.3 rule 8), then the one root for non-catalogue pages. */
export const STORY_BANDS = [
  "Atoms",
  "Molecules",
  "Organisms",
  "Trading",
  "RuleEngine",
  "ChartEngine",
  "Foundations",
];
const ALLOWED = STORY_BANDS.map((band) => `${band}/*`).join(", ");
const WRAPPERS = new Set(["TSAsExpression", "TSSatisfiesExpression", "TSTypeAssertion"]);

/** The expression under `as Meta`, `satisfies Meta` or `<Meta>`. */
function unwrap(node) {
  let inner = node;
  while (inner && WRAPPERS.has(inner.type)) inner = inner.expression;
  return inner;
}

/** The meta object a default export names: inline, or a variable declared in the module. */
function metaObject(context, node) {
  const value = unwrap(node);
  if (value?.type !== "Identifier") return value?.type === "ObjectExpression" ? value : null;
  for (let scope = context.sourceCode.getScope(node); scope; scope = scope.upper) {
    const variable = scope.set.get(value.name);
    if (!variable) continue;
    const init = unwrap(variable.defs.find((def) => def.type === "Variable")?.node.init);
    return init?.type === "ObjectExpression" ? init : null;
  }
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

const isTitle = (property) =>
  property.type === "Property" &&
  !property.computed &&
  (property.key.name === "title" || property.key.value === "title");

/** @type {import("eslint").Rule.RuleModule} */
export const storyTitleBands = {
  meta: {
    type: "problem",
    docs: {
      description: "Require story titles under the catalogue's Storybook bands.",
    },
    messages: {
      band: "Story title '{{title}}' is outside the Storybook bands: use {{allowed}} (15-component-catalogue.md §0.3 rule 8; Foundations/* is for pages that are not catalogue components).",
      missing:
        "A story file's default export needs a static `title` under {{allowed}}: a title derived from the file path is outside every band.",
    },
    schema: [],
  },
  create(context) {
    let exported = false;
    return {
      ExportDefaultDeclaration(node) {
        exported = true;
        const property = metaObject(context, node.declaration)?.properties.find(isTitle);
        const title = staticString(property?.value);
        if (title === null) {
          context.report({
            node: property ?? node,
            messageId: "missing",
            data: { allowed: ALLOWED },
          });
          return;
        }
        const [band, ...path] = title.split("/");
        if (!STORY_BANDS.includes(band) || path.length === 0 || path.some((part) => !part.trim())) {
          context.report({
            node: property.value,
            messageId: "band",
            data: { title, allowed: ALLOWED },
          });
        }
      },
      "Program:exit"(node) {
        if (!exported) context.report({ node, messageId: "missing", data: { allowed: ALLOWED } });
      },
    };
  },
};

export default storyTitleBands;
