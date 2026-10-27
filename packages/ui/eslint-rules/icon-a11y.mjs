// Custom ESLint rules (E05 #271): the decorative-vs-meaningful rule of 16-design-system-brief.md §5
// for CMP-019 `Icon` and CMP-002 `IconButton`. `decorative={false}` makes an icon a named image, so
// it needs a `label`; an icon-only control needs a name of its own; an icon beside visible text stays
// decorative. The types enforce what they can for TypeScript callers; the rules cover the rest (and
// fail the lint). Spread props and computed values are trusted (not statically knowable), and only
// the plain JSX names are matched (`Icon`, `IconButton`, `button`, `a`): an aliased import is not.

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

/** Whether an attribute supplies a name: a non-blank string, or a computed value (trusted). */
function names(opening, attribute) {
  const found = staticValue(opening, attribute);
  return found.computed || (typeof found.value === "string" && found.value.trim() !== "");
}

/** A spread may carry any prop: it cannot be read statically, so the element is trusted. */
const hasSpread = (opening) =>
  opening.attributes.some((item) => item.type === "JSXSpreadAttribute");

/** Whether a spread may set the prop: one follows it, or it is absent and there is a spread. */
function spreadMaySet(opening, name) {
  const at = opening.attributes.findIndex(
    (item) => item.type === "JSXAttribute" && item.name.name === name,
  );
  return opening.attributes.slice(at + 1).some((item) => item.type === "JSXSpreadAttribute");
}

/** Visible text: a JSX text child that is not whitespace alone. */
const isText = (child) => child.type === "JSXText" && child.value.trim() !== "";

/** A child that renders something: neither whitespace alone nor an empty `{}` (or a JSX comment). */
const rendered = (child) =>
  child.type === "JSXText"
    ? isText(child)
    : child.type !== "JSXExpressionContainer" || child.expression.type !== "JSXEmptyExpression";

/** Icons alone: an <Icon>, or only icons in `{…}`, `c && …`, `c ? … : …` or `<>…</>`. */
function iconOnly(node) {
  switch (node.type) {
    case "JSXElement":
      return node.openingElement.name.name === "Icon";
    case "JSXFragment":
      return iconChildren(node.children);
    case "JSXExpressionContainer":
      return iconOnly(node.expression);
    case "LogicalExpression":
      return node.operator === "&&" && iconOnly(node.right);
    case "ConditionalExpression":
      return iconOnly(node.consequent) && iconOnly(node.alternate);
    default:
      return false;
  }
}

/** Children that render at least one icon and nothing else. */
function iconChildren(children) {
  const content = children.filter(rendered);
  return content.length > 0 && content.every(iconOnly);
}

/** The expressions an element renders through into its parent's children. */
const RENDERS_THROUGH = new Set([
  "JSXExpressionContainer",
  "LogicalExpression",
  "ConditionalExpression",
]);

/** Where an element renders: its parent, past any `{…}`, `c && …` or `c ? … : …` around it. */
function host(element) {
  let { parent } = element;
  while (RENDERS_THROUGH.has(parent.type)) parent = parent.parent;
  return parent;
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
        if (hasSpread(node)) return;
        if (staticValue(node, "decorative").value !== false) return;
        if (!names(node, "label")) context.report({ node, messageId: "unlabelled" });
      },
    };
  },
};

/** @type {import("eslint").Rule.RuleModule} */
export const iconOnlyControlLabel = {
  meta: {
    type: "problem",
    docs: { description: "Require a name on an icon-only control: IconButton, <button> or <a>." },
    messages: {
      iconButton:
        "<IconButton> is icon-only, so it needs a name: a non-blank `label`, which becomes its `aria-label`, or `aria-labelledby` (CMP-002, 16-design-system-brief.md §5). Its `label` overwrites an `aria-label` prop.",
      control:
        "An icon-only <{{tag}}> needs a name of its own: a non-blank `aria-label` or `aria-labelledby`, not `title` (16-design-system-brief.md §5). The <Icon> in it stays aria-hidden.",
    },
    schema: [],
  },
  create(context) {
    return {
      JSXOpeningElement(node) {
        const tag = node.name.name;
        if (tag === "IconButton") {
          // IconButton.tsx renders `aria-label={label}` after its rest props: `label` is the name.
          // A spread may set it, unless a static `label` follows the spread (`{...rest} label=""`).
          if (spreadMaySet(node, "label")) return;
          if (!names(node, "label") && !names(node, "aria-labelledby")) {
            context.report({ node, messageId: "iconButton" });
          }
          return;
        }
        if ((tag !== "button" && tag !== "a") || hasSpread(node)) return;
        if (!iconChildren(node.parent.children)) return;
        if (!["aria-label", "aria-labelledby"].some((name) => names(node, name))) {
          context.report({ node, messageId: "control", data: { tag } });
        }
      },
    };
  },
};

/** @type {import("eslint").Rule.RuleModule} */
export const iconBesideTextHidden = {
  meta: {
    type: "problem",
    docs: {
      description: "Disallow <Icon decorative={false}> beside visible text, which names it.",
    },
    messages: {
      besideText:
        "An <Icon> beside visible text is decorative: drop `decorative={false}` and its `label`, so it stays aria-hidden and the text alone names it (16-design-system-brief.md §5, CMP-019).",
    },
    schema: [],
  },
  create(context) {
    return {
      JSXOpeningElement(node) {
        if (node.name.name !== "Icon" || hasSpread(node)) return;
        if (staticValue(node, "decorative").value !== false) return;
        // Its siblings where it renders, through `{…}`, `c && …` and `c ? … : …`: a JSX element's
        // or fragment's children; any other host (an attribute, a variable) has none.
        const { children = [] } = host(node.parent);
        if (children.some(isText)) context.report({ node, messageId: "besideText" });
      },
    };
  },
};
