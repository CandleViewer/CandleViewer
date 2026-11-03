/**
 * Accessibility-tree normaliser for the Q03 snapshot work (E47-Q03 BQ-08 (a)).
 *
 * It masks volatile and sensitive values in `ariaSnapshot()` text before the text is compared or committed,
 * so a diff shows semantic change only and the repository never collects real account data. It is its own
 * module and does not edit the G006 corpus or collector (#1315's files): the journeys call
 * `normaliseTree(captured)` on the collector's output. Overlap with G006: it reads the same text format and
 * should be applied by tree.collect.ts once the corpus owner agrees (recorded in the PR).
 *
 * Mask list, in order (the first match wins for a span): email, UUID, ISO timestamp, clock time, labelled
 * account name, currency amount / balance, decimal or grouped number, long mixed token (ids, keys, order links).
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
    name: "account",
    pattern: /\b(account|acct|sub-?account)(\s*[:#-]?\s+)(?!<)[\w.-]+/gi,
    token: "$1$2<account>",
  },
  {
    name: "amount",
    pattern: /[$€£]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USDT|USDC|USD|BTC|ETH)\b/g,
    token: "<amount>",
  },
  {
    name: "number",
    pattern: /(?<![\w<])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w<])\d+\.\d+/g,
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
