// The parser limits rule-editor-core enforces (SR-E36-13): the table of
// docs/security/threat-models/e36-rule-form-editor.md §5.1, checked in its order, each before the
// step it protects. A refusal names its reason and its limit, and nothing past it runs. Every
// number equals the server's own (`api/rule_body.py`, `rules/compiler/common.py`,
// `rules/ir/models.py`), so the client never sends a body the server refuses and a stored rule
// always reopens. Everything here is iterative: no input depth can exhaust the stack.

/** The §5.1 numbers. The import file and byte counts are E36-S06's; it calls the checks here. */
export const RULE_LIMITS = Object.freeze({
  /** Files in one import selection. */
  importFiles: 100,
  /** Bytes in one import selection, the sum of the file sizes, before any file is read. */
  importBytes: 20_000_000,
  /** UTF-8 bytes in one request body or one file: the server's `MAX_RULE_BODY_BYTES`. */
  bodyBytes: 2_000_000,
  /** Levels of objects and arrays in an `ir`, its root counted as level 1. */
  irDepth: 65,
  /** The same in a bundle file, whose wrapper adds one level. */
  bundleDepth: 66,
  /** Values in an `ir`, every object, array and scalar counted once: the server's `MAX_ITEMS`. */
  values: 20_000,
  /** Actions per rule: `MAX_ACTIONS`. */
  actions: 10,
  /** Children of one boolean node: `MAX_BOOLEAN_CHILDREN`. */
  booleanChildren: 32,
  /** Condition nodes the form edits; past it the rule opens read-only. */
  editableConditionNodes: 200,
  /** Condition nodes a rule may hold: `MAX_CONDITION_NODES`. */
  storableConditionNodes: 1_000,
  /** The one `ir_version` the client maps; any other is refused by name (#1063 BQ-04). */
  irVersion: 1,
});

/** Why a document was refused, in the §5.1 order. */
export type LimitReason =
  | "import_files"
  | "import_bytes"
  | "import_size"
  | "body_bytes"
  | "depth"
  | "malformed_json"
  | "unencodable"
  | "values"
  | "not_an_object"
  | "ir_version"
  | "actions"
  | "boolean_children"
  | "condition_nodes";

/** A refusal: its reason, the limit it passed (`null` where none applies) and what was measured. */
export interface LimitRefusal {
  readonly reason: LimitReason;
  readonly limit: number | null;
  readonly measured: number | string | null;
}

export type LimitResult<T> =
  { readonly ok: true; readonly value: T } | { readonly ok: false; readonly refusal: LimitRefusal };

const refuse = (
  reason: LimitReason,
  limit: number | null,
  measured: number | string | null,
): { readonly ok: false; readonly refusal: LimitRefusal } => ({
  ok: false,
  refusal: { reason, limit, measured },
});

/**
 * An import selection, refused by its count, then by its summed size, before any file is read.
 * A size that is not a non-negative safe integer (`NaN`, negative, infinite, fractional) is
 * refused as `import_size`, so it can neither slip past nor cancel the byte ceiling.
 */
export function checkImportSelection(sizes: readonly number[]): LimitResult<null> {
  if (sizes.length > RULE_LIMITS.importFiles) {
    return refuse("import_files", RULE_LIMITS.importFiles, sizes.length);
  }
  for (const size of sizes) {
    if (!Number.isSafeInteger(size) || size < 0) return refuse("import_size", null, String(size));
  }
  let total = 0;
  for (const size of sizes) total += size;
  if (total > RULE_LIMITS.importBytes)
    return refuse("import_bytes", RULE_LIMITS.importBytes, total);
  return { ok: true, value: null };
}

/**
 * The UTF-8 length of `text` without encoding it, so a 2 MB body is never copied. A lone
 * surrogate counts 3 bytes, as the U+FFFD an encoder writes for it.
 */
export function utf8ByteLength(text: string): number {
  let bytes = 0;
  for (let i = 0; i < text.length; i += 1) {
    const unit = text.charCodeAt(i);
    if (unit < 0x80) bytes += 1;
    else if (unit < 0x800) bytes += 2;
    else if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        bytes += 4;
        i += 1;
      } else bytes += 3;
    } else bytes += 3;
  }
  return bytes;
}

/** The UTF-8 length of `text` when it is over `limit`, else `null`. */
function bytesExceed(text: string, limit: number): number | null {
  if (text.length * 3 <= limit) return null; // a UTF-16 unit is at most three UTF-8 bytes
  const bytes = utf8ByteLength(text);
  return bytes > limit ? bytes : null;
}

/**
 * Whether `text` nests `[` / `{` deeper than `limit`: a linear, string-aware scan, the server's
 * `json_depth_exceeds` (`ws/limits.py`), so a hostile document never reaches `JSON.parse`.
 */
export function jsonDepthExceeds(text: string, limit: number): boolean {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text.charCodeAt(i);
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === 0x5c)
        escaped = true; // backslash
      else if (ch === 0x22) inString = false; // quote
    } else if (ch === 0x22) inString = true;
    else if (ch === 0x5b || ch === 0x7b) {
      depth += 1;
      if (depth > limit) return true;
    } else if (ch === 0x5d || ch === 0x7d) depth -= 1;
  }
  return false;
}

/**
 * The values in `doc` as the server's `check_bounds` counts them, stopping at the first count past
 * `limit` (then `limit + 1`). A container is counted with its pending children before they are
 * stacked, so the stack never holds more than `limit` entries.
 */
export function countValues(doc: unknown, limit: number = RULE_LIMITS.values): number {
  const stack: unknown[] = [doc];
  let count = 0;
  while (stack.length > 0) {
    const cur = stack.pop();
    count += 1;
    const children: readonly unknown[] = Array.isArray(cur)
      ? cur
      : typeof cur === "object" && cur !== null
        ? Object.values(cur)
        : [];
    if (count + stack.length + children.length > limit) return limit + 1;
    for (const child of children) stack.push(child);
  }
  return count;
}

/** What the document is: a rule's `ir`, or an import bundle file whose wrapper adds one level. */
export type DocumentKind = "ir" | "bundle";

/**
 * Parse server- or user-supplied rule JSON under the §5.1 limits: bytes, then depth, both before
 * `JSON.parse`; then the value count, before any walk. Never throws: a syntax error is a refusal.
 */
export function parseRuleJson(text: string, kind: DocumentKind = "ir"): LimitResult<unknown> {
  const bytes = bytesExceed(text, RULE_LIMITS.bodyBytes);
  if (bytes !== null) return refuse("body_bytes", RULE_LIMITS.bodyBytes, bytes);
  const depth = kind === "ir" ? RULE_LIMITS.irDepth : RULE_LIMITS.bundleDepth;
  if (jsonDepthExceeds(text, depth)) return refuse("depth", depth, null);
  let value: unknown;
  try {
    value = JSON.parse(text) as unknown;
  } catch (err) {
    return refuse("malformed_json", null, err instanceof Error ? err.message : null);
  }
  const values = countValues(value);
  if (values > RULE_LIMITS.values) return refuse("values", RULE_LIMITS.values, values);
  return { ok: true, value };
}

/**
 * `JSON.stringify` without throwing: a cyclic or `BigInt` value, or one with no JSON text
 * (`undefined`, a function, a symbol), comes back as `{ error }` instead of a string.
 */
function stringify(value: unknown): string | { readonly error: string } {
  try {
    const text = JSON.stringify(value) as string | undefined;
    return typeof text === "string" ? text : { error: `no JSON text for ${typeof value}` };
  } catch (err) {
    return { error: err instanceof Error ? err.message : "not encodable" };
  }
}

/**
 * The encoded request body of a save, validate or compile (`ir` with `name`, `scope` and `note`),
 * refused past the server's byte ceiling before it is sent: the same bytes the server measures.
 * A body with no JSON text (cyclic, `BigInt`, `undefined`) is refused as `unencodable`.
 */
export function encodeRequestBody(body: unknown): LimitResult<string> {
  const text = stringify(body);
  if (typeof text !== "string") return refuse("unencodable", null, text.error);
  const bytes = bytesExceed(text, RULE_LIMITS.bodyBytes);
  if (bytes !== null) return refuse("body_bytes", RULE_LIMITS.bodyBytes, bytes);
  return { ok: true, value: text };
}

/** The verdict on a parsed rule's shape: its condition nodes, and whether the form may edit it. */
export interface RuleShape {
  readonly conditionNodes: number;
  /** False past `editableConditionNodes`: the rule opens read-only, with JSON export. */
  readonly editable: boolean;
}

type Tree = Readonly<Record<string, unknown>>;
const isTree = (v: unknown): v is Tree => typeof v === "object" && v !== null && !Array.isArray(v);
/** An own member only, as `pointer.ts` reads: an inherited one is never part of the rule. */
const own = (tree: Tree, key: string): unknown =>
  Object.hasOwn(tree, key) ? tree[key] : undefined;

/**
 * The form model's bounds on a parsed `ir`, before any model is built: the `ir_version` the
 * client maps (refused by name, never mapped), then actions, boolean children and condition
 * nodes, each condition node counted once at each place it occurs, as the server's
 * `count_condition_nodes`: every object reached from `conditions` through `children` and `child`.
 * Members are read as own properties only, so a polluted prototype cannot add or hide one.
 */
export function checkRuleShape(ir: unknown): LimitResult<RuleShape> {
  if (!isTree(ir)) return refuse("not_an_object", null, Array.isArray(ir) ? "array" : typeof ir);
  const version = own(ir, "ir_version");
  if (version !== undefined && version !== RULE_LIMITS.irVersion) {
    const shown = stringify(version);
    return refuse("ir_version", RULE_LIMITS.irVersion, typeof shown === "string" ? shown : null);
  }
  const actions = own(ir, "actions");
  if (Array.isArray(actions) && actions.length > RULE_LIMITS.actions) {
    return refuse("actions", RULE_LIMITS.actions, actions.length);
  }
  const stack: unknown[] = [own(ir, "conditions")];
  let nodes = 0;
  while (stack.length > 0) {
    const node = stack.pop();
    if (!isTree(node)) continue;
    nodes += 1;
    if (nodes > RULE_LIMITS.storableConditionNodes) {
      return refuse("condition_nodes", RULE_LIMITS.storableConditionNodes, nodes);
    }
    stack.push(own(node, "child"));
    const children = own(node, "children");
    if (Array.isArray(children)) {
      if (children.length > RULE_LIMITS.booleanChildren) {
        return refuse("boolean_children", RULE_LIMITS.booleanChildren, children.length);
      }
      for (const child of children as unknown[]) stack.push(child);
    }
  }
  return {
    ok: true,
    value: { conditionNodes: nodes, editable: nodes <= RULE_LIMITS.editableConditionNodes },
  };
}
