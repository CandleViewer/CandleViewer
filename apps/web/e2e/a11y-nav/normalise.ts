/**
 * Accessibility-tree normaliser (E47-Q03 BQ-08 (a)): masks volatile and sensitive values in `ariaSnapshot()`
 * text so a diff shows semantic change only and no account data is committed. Its own module: it does not
 * edit the G006 corpus or collector (#1315's files), only reads their text format; tree.collect.ts applies it
 * once the corpus owner agrees. Masks run in list order.
 */
export interface Mask {
  readonly name: string;
  readonly pattern: RegExp;
  readonly token: string;
}

export const MASKS: readonly Mask[] = [
  { name: "email", pattern: /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, token: "<email>" },
  {
    name: "uuid",
    pattern: /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi,
    token: "<id>",
  },
  {
    name: "iso-timestamp",
    pattern: /\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?/g,
    token: "<time>",
  },
  { name: "clock", pattern: /\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?\b/g, token: "<time>" },
  {
    // Needs an id-like value: a `:` or `#` separator, or a bare value holding a digit or hyphen.
    // "Account settings" and "Create account" are UI text and survive.
    name: "account",
    pattern:
      /\b(account|acct|sub-?account)(?:(\s*[:#]\s*)(?!<)[\w.-]+|(\s+)(?!<)(?=[\w.-]*[\d-])[\w.-]+)/gi,
    token: "$1$2$3<account>",
  },
  {
    name: "amount",
    pattern: /[$€£]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USDT|USDC|USD|BTC|ETH)\b/g,
    token: "<amount>",
  },
  {
    // A decimal is a price or size, except a standard's or section's number: "WCAG 2.2", "SC 1.4.11".
    name: "number",
    pattern:
      /(?<![\w<])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w<.])(?<!(?:WCAG|ARIA|HTML|[Vv]ersion)\s)\d+\.\d+(?!\.?\d)/g,
    token: "<num>",
  },
  {
    name: "token",
    pattern: /\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,}\b/g,
    token: "<id>",
  },
];

/** Mask every volatile or sensitive value in an ARIA snapshot. Idempotent. */
export function normaliseTree(tree: string): string {
  let out = tree;
  for (const m of MASKS) out = out.replace(m.pattern, m.token);
  return out;
}

export interface TreeDiff {
  readonly changed: boolean;
  /** Reviewer-readable lines: `- removed`, `+ added`, and `! NAME LOST` for a role that kept no name. */
  readonly lines: readonly string[];
  readonly nameLosses: readonly string[];
}

const NODE = /^(\s*-\s+)([\w-]+)(?:\s+"((?:[^"\\]|\\.)*)")?/;

/** Roles whose accessible name matters: losing it is the regression the gate exists for. */
const NAMED_ROLES = new Set([
  "button",
  "link",
  "textbox",
  "checkbox",
  "radio",
  "switch",
  "combobox",
  "tab",
  "menuitem",
  "searchbox",
  "slider",
  "spinbutton",
]);

/**
 * Line diff of two normalised trees, plus the named-role check: a role that carried a name in `base` and
 * appears in `next` at the same ordinal for that role with no name is a name loss (the icon-only refactor).
 */
export function diffTrees(base: string, next: string): TreeDiff {
  const a = base.trimEnd().split("\n");
  const b = next.trimEnd().split("\n");
  const lines: string[] = [];
  const left = new Map<string, number>();
  for (const l of a) left.set(l, (left.get(l) ?? 0) + 1);
  const right = new Map<string, number>();
  for (const l of b) right.set(l, (right.get(l) ?? 0) + 1);
  for (const l of a) {
    if ((right.get(l) ?? 0) > 0) right.set(l, (right.get(l) ?? 0) - 1);
    else lines.push(`- ${l}`);
  }
  for (const l of b) {
    if ((left.get(l) ?? 0) > 0) left.set(l, (left.get(l) ?? 0) - 1);
    else lines.push(`+ ${l}`);
  }
  const named = (rows: readonly string[]): Map<string, string[]> => {
    const byRole = new Map<string, string[]>();
    for (const r of rows) {
      const m = NODE.exec(r);
      const role = m?.[2];
      if (role === undefined || !NAMED_ROLES.has(role)) continue;
      byRole.set(role, [...(byRole.get(role) ?? []), m?.[3] ?? ""]);
    }
    return byRole;
  };
  const was = named(a);
  const now = named(b);
  const nameLosses: string[] = [];
  for (const [role, names] of was) {
    const after = now.get(role) ?? [];
    names.forEach((n, i) => {
      if (n !== "" && after[i] === "" && after.length === names.length) {
        nameLosses.push(`${role} "${n}" lost its accessible name`);
      }
    });
  }
  return {
    changed: lines.length > 0,
    lines: [...lines, ...nameLosses.map((l) => `! NAME LOST: ${l}`)],
    nameLosses,
  };
}
