// Custom ESLint rule (E05 #271): the decorative-vs-meaningful rule of 16-design-system-brief.md
// §5 for CMP-019 `Icon`. `decorative={false}` makes an icon a named image, so it needs a `label`.
// The types enforce this for TypeScript callers; the rule covers the rest (and fails the lint).
// Spread props and computed labels are trusted (not statically knowable; the types cover TypeScript
// callers), and only the JSX name `Icon` is matched: an aliased import is not checked.

/** The value of a JSX attribute: a literal, `true` when bare, undefined when absent or computed. */
function staticValue(opening, name) {
  const found = opening.attributes.find(
    (item) => item.type === "JSXAttribute" && item.name.name === name,
  );
  if (!found) return { present: false };
  if (!found.value) return { present: true, value: true };
  const node = found.value.type === "JSXExpressionContainer" ? found.value.expression : found.value;
  return {
    present: true,
    value: node.type === "Literal" ? node.value : undefined,
    computed: node.type !== "Literal" && !(node.type === "Identifier" && node.name === "undefined"),
  };
}

/** @type {import("eslint").Rule.RuleModule} */
export const iconLabelRequired = {
  meta: {
    type: "problem",
    docs: { description: "Require a non-blank label on an <Icon decorative={false}>." },
    messages: {
      unlabelled:
        "<Icon decorative={false}> is a named image: give it a non-blank `label` (16-design-system-brief.md §5, CMP-019). A decorative icon omits `decorative={false}`.",
    },
    schema: [],
  },
  create(context) {
    return {
      JSXOpeningElement(node) {
        if (node.name.type !== "JSXIdentifier" || node.name.name !== "Icon") return;
        // A spread may carry the label: it cannot be read statically, so it is trusted.
        if (node.attributes.some((item) => item.type === "JSXSpreadAttribute")) return;
        if (staticValue(node, "decorative").value !== false) return;
        const label = staticValue(node, "label");
        const named =
          label.computed || (typeof label.value === "string" && label.value.trim() !== "");
        if (!named) context.report({ node, messageId: "unlabelled" });
      },
    };
  },
};
