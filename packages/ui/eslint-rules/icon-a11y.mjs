// Custom ESLint rules (E05-T06): the decorative-vs-meaningful icon rule of
// 16-design-system-brief.md §5, which CMP-002 IconButton and CMP-019 Icon rely on.
//   icon-only-control-label  a control whose only content is icons carries an aria-label (or
//                            aria-labelledby; IconButton's `label` prop becomes its aria-label)
//   icon-beside-text-hidden  an icon beside visible text stays aria-hidden: the text names it
// An icon is a registry component (`Icon`, `<Name>Icon`) or a raw <svg>. A registry icon is
// aria-hidden unless it is given a name (aria-label, aria-labelledby, role="img"; CMP-019's
// `decorative={false}`); a raw <svg> is hidden only by aria-hidden="true". Spread props and
// computed values cannot be read statically, so they are trusted, never guessed at.

const ICON = /^(?:[A-Z][\dA-Za-z]*)?Icon$/;
const BUTTON = /^(?:[A-Z][\dA-Za-z]*)?Button$/;
/** The attributes that name a control; IconButton's `label` prop becomes its aria-label. */
const NAMING = ["aria-label", "aria-labelledby"];
/** Roles that make an element a control that needs an accessible name. */
const CONTROL_ROLES = new Set([
  "button",
  "link",
  "menuitem",
  "menuitemcheckbox",
  "menuitemradio",
  "option",
  "switch",
  "tab",
]);
const UNKNOWN = Symbol("unknown");

/** An element's tag: `button`, `CloseIcon`, or `Button` for `<Toolbar.Button>`. */
function tagName(opening) {
  const { name } = opening;
  if (name.type === "JSXIdentifier") return name.name;
  if (name.type === "JSXMemberExpression") return name.property.name;
  return `${name.namespace.name}:${name.name.name}`;
}

const isIcon = (node) =>
  node.type === "JSXElement" &&
  (tagName(node.openingElement) === "svg" || ICON.test(tagName(node.openingElement)));

function attribute(opening, name) {
  return opening.attributes.find(
    (item) =>
      item.type === "JSXAttribute" && item.name.type === "JSXIdentifier" && item.name.name === name,
  );
}

const hasSpread = (opening) =>
  opening.attributes.some((item) => item.type === "JSXSpreadAttribute");

/** An attribute's static value (`true` when bare), UNKNOWN for a computed one, undefined if absent. */
function valueOf(opening, name) {
  const found = attribute(opening, name);
  if (!found) return undefined;
  if (!found.value) return true;
  const value =
    found.value.type === "JSXExpressionContainer" ? found.value.expression : found.value;
  if (value.type === "Literal") return value.value;
  if (value.type === "TemplateLiteral" && value.expressions.length === 0) {
    return value.quasis[0].value.cooked;
  }
  return UNKNOWN;
}

/** A name a control can carry: a computed one is trusted, a static one must not be blank. */
const isName = (value) => value === UNKNOWN || (typeof value === "string" && value.trim() !== "");

/** Children that render: whitespace-only text and `{/* comments *\/}` drop out. */
const contentOf = (element) =>
  element.children.filter(
    (child) =>
      !(child.type === "JSXText" && !/\S/.test(child.value)) &&
      !(child.type === "JSXExpressionContainer" && child.expression.type === "JSXEmptyExpression"),
  );

/** Visible text: a text node, a string or template literal, or an element that holds one. */
function isText(child) {
  if (child.type === "JSXText") return /\S/.test(child.value);
  if (child.type === "JSXExpressionContainer") {
    const { expression } = child;
    return (
      expression.type === "TemplateLiteral" ||
      (expression.type === "Literal" &&
        typeof expression.value === "string" &&
        /\S/.test(expression.value))
    );
  }
  if (child.type === "JSXFragment") return child.children.some(isText);
  return child.type === "JSXElement" && !isIcon(child) && child.children.some(isText);
}

function isControl(opening) {
  const tag = tagName(opening);
  const role = valueOf(opening, "role");
  return (
    tag === "button" ||
    tag === "a" ||
    BUTTON.test(tag) ||
    (typeof role === "string" && CONTROL_ROLES.has(role))
  );
}

/** Whether an icon is exposed to assistive technology, as far as its attributes say. */
function isExposed(opening) {
  const hidden = valueOf(opening, "aria-hidden");
  if (hidden === UNKNOWN || hidden === true || hidden === "true") return false;
  if (hidden === false || hidden === "false") return true;
  const tag = tagName(opening);
  if (tag === "svg") return true;
  return (
    valueOf(opening, "role") === "img" ||
    NAMING.some((name) => attribute(opening, name) !== undefined) ||
    (tag === "Icon" && valueOf(opening, "decorative") === false)
  );
}

/** @type {import("eslint").Rule.RuleModule} */
export const iconOnlyControlLabel = {
  meta: {
    type: "problem",
    docs: { description: "Require an aria-label on a control whose only content is icons." },
    messages: {
      unlabelled:
        "Icon-only <{{control}}> has no accessible name: give it {{label}}. Its icons are aria-hidden (16-design-system-brief.md §5, CMP-002).",
    },
    schema: [],
  },
  create(context) {
    return {
      JSXElement(node) {
        const opening = node.openingElement;
        if (!isControl(opening) || hasSpread(opening)) return;
        const tag = tagName(opening);
        const content = contentOf(node);
        // IconButton (CMP-002) takes its icon as a prop: with no children it is icon-only.
        if (content.length === 0 ? tag !== "IconButton" : !content.every(isIcon)) return;
        const names = tag === "IconButton" ? ["label", ...NAMING] : NAMING;
        if (names.some((name) => isName(valueOf(opening, name)))) return;
        const label =
          tag === "IconButton"
            ? "a label (its aria-label) or an aria-label"
            : "an aria-label (or aria-labelledby)";
        context.report({ node: opening, messageId: "unlabelled", data: { control: tag, label } });
      },
    };
  },
};

/** @type {import("eslint").Rule.RuleModule} */
export const iconBesideTextHidden = {
  meta: {
    type: "problem",
    docs: { description: "Require an icon beside visible text to stay aria-hidden." },
    messages: {
      exposed:
        "<{{icon}}> beside visible text must stay aria-hidden: the text already names it, so a named icon is read twice (16-design-system-brief.md §5).",
    },
    schema: [],
  },
  create(context) {
    return {
      JSXElement(node) {
        const { parent } = node;
        if (!isIcon(node) || (parent.type !== "JSXElement" && parent.type !== "JSXFragment")) {
          return;
        }
        const opening = node.openingElement;
        if (hasSpread(opening) || !parent.children.some((child) => isText(child))) return;
        if (isExposed(opening)) {
          context.report({ node: opening, messageId: "exposed", data: { icon: tagName(opening) } });
        }
      },
    };
  },
};
