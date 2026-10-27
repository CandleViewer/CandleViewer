// Custom ESLint rule (E05-T06 #271): every icon is referenced by its semantic `IconName`, never by raw
// SVG inline in component code (16-design-system-brief.md §5). An intrinsic JSX <svg> in any file
// outside the registry, packages/ui/src/icons/, is an error that names the file and points at `<Icon>`.
// Only JSX is matched: `createElement("svg")` and SVG markup in a string are not.

import path from "node:path";

/** The registry's directory as a segment of a POSIX path: any file below it may draw raw SVG. */
const REGISTRY = "/packages/ui/src/icons/";

/** A path with `/` separators, so the check and the message read the same on every OS. */
const posix = (file) => file.split(path.sep).join("/");

/** @type {import("eslint").Rule.RuleModule} */
export const noRawSvg = {
  meta: {
    type: "problem",
    docs: {
      description: "Disallow a raw <svg> outside the icon registry, packages/ui/src/icons/.",
    },
    messages: {
      raw: 'Raw <svg> in {{file}}: draw icons with <Icon name="…"> from the icon registry, packages/ui/src/icons/ (16-design-system-brief.md §5); a missing glyph joins registry.ts there, never inline.',
    },
    schema: [],
  },
  create(context) {
    if (posix(context.physicalFilename).includes(REGISTRY)) return {};
    const file = posix(path.relative(context.cwd, context.physicalFilename));
    return {
      JSXOpeningElement(node) {
        // A member (`<x.svg>`) or namespaced (`<svg:g>`) name has no string `name`: <svg> alone matches.
        if (node.name.name === "svg") context.report({ node, messageId: "raw", data: { file } });
      },
    };
  },
};

export default noRawSvg;
