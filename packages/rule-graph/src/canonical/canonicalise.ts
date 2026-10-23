/**
 * The client mirror of the server's canonical rule IR and hash (E37-T01, AC1), for display only:
 * the server's `ir_hash` (rules/ir/canonical.py) is the authority, the client's is never stored or
 * sent as one, and a disagreement shows as "server differs", never resolved here. Hash what you
 * send, never re-hash what you load: compile returns a Decimal const as its text (`1E-7`, C-Q1),
 * which re-hashes as text, and save hashes the sent `version` with its own `rule_id`, `mode` and
 * `enabled` and stores another `version`. So compare with compile's `ir_hash`, never save's.
 */
import { sha256Hex } from "../sha256.js";
import { type Canonical, dump } from "./schema.js";

// canonical.py:26-28, top level only: free-form `params` never lose a key.
const STRIPPED = ["graph_layout", "editor", "created_by", "created_at", "updated_at"];
const OPAQUE = new Set(["params", "const"]); // canonical.py:75: never renumbered

/** Code point order, as Python sorts keys: lifting the surrogates above U+E000-U+FFFF does it. */
export function byCodePoint(a: string, b: string): number {
  const lift = (u: number) => (u < 0xd800 ? u : u < 0xe000 ? u + 0x2000 : u - 0x800);
  for (let i = 0; i < a.length && i < b.length; i++) {
    const d = lift(a.charCodeAt(i)) - lift(b.charCodeAt(i));
    if (d !== 0) return d;
  }
  return a.length - b.length;
}

// No `ref` rewrite (canonical.py:102): no field is named ref; free-form maps are opaque or stripped.
/** Compact sorted JSON (canonical.py:158), numbering node ids in `_renumber`'s order (:78-113). */
function emit(value: Canonical, ids: Map<string, string>, opaque: boolean): string {
  if (typeof value !== "object" || value === null) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => emit(item, ids, opaque)).join(",")}]`;
  // Pre-order over sorted keys: a node's own id is numbered before its children's.
  const own = value.get("node_id");
  if (!opaque && typeof own === "string" && !ids.has(own)) ids.set(own, `n${ids.size + 1}`);
  const members = [...value.keys()].sort(byCodePoint).map((key) => {
    const item = value.get(key) as Canonical;
    const out =
      !opaque && key === "node_id"
        ? JSON.stringify(ids.get(item as string))
        : emit(item, ids, opaque || OPAQUE.has(key));
    return `${JSON.stringify(key)}:${out}`;
  });
  return `{${members.join(",")}}`;
}

/** The canonical JSON text of the rule IR `ir`, as the server hashes it. */
export function canonicalise(ir: unknown): string {
  const view = dump(ir);
  for (const key of STRIPPED) view.delete(key);
  return emit(view, new Map(), false);
}

/** The lowercase hex sha256 of `canonicalise(ir)`, which the server's `ir_hash` should equal. */
export const hash = (ir: unknown): string => sha256Hex(canonicalise(ir));

/** "match" only for the same sha256 digest, else "mismatch". It never picks a winner. */
export function compareWithServer(clientHash: unknown, serverHash: unknown): "match" | "mismatch" {
  const digest = typeof clientHash === "string" && /^[\da-f]{64}$/.test(clientHash);
  return digest && clientHash === serverHash ? "match" : "mismatch";
}
