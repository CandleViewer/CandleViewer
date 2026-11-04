// E14-T02 (#400): the client DrawingStore's types. Wire shapes come from the generated protocol only
// (C-4.16); everything else here is local model.
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];

export type Drawing = Schemas["Drawing"];
export type DrawingInput = Schemas["DrawingInput"];
export type DrawingBatchRequest = Schemas["DrawingBatchRequest"];
export type DrawingBatchResult = Schemas["DrawingBatchResult"];
export type DrawingBatchOp = DrawingBatchRequest["operations"][number];
export type Problem = Schemas["Problem"];
/** One `listDrawings` 200 body: a `Page` of drawings. */
export type DrawingsPage =
  generated.rest.operations["listDrawings"]["responses"][200]["content"]["application/json"];

/**
 * A drawing's stable local identity. The server id changes when an undone delete re-creates the
 * object (an id stays unavailable for 90 days, `22` batchUpsertDrawings; D07 §8.2), so commands
 * name the handle and the record maps it to the current id.
 */
export type Handle = string & { readonly __brand: "DrawingHandle" };
export const asHandle = (value: string): Handle => value as Handle;

/** One drawing as the client holds it. Records are replaced, never mutated. */
export interface LocalDrawing {
  readonly handle: Handle;
  /** The current server id (client-minted UUIDv7 for a create). */
  readonly id: string;
  /** `updated_at` as received, echoed byte-exact as `if_match`; `null` until the create is confirmed. */
  readonly token: string | null;
  readonly input: DrawingInput;
  /** The last content the server confirmed; `null` for an unconfirmed create. */
  readonly base: DrawingInput | null;
  /** `conflict`: the server's version was adopted over a local one ("changed elsewhere", D02:501). */
  readonly tag: "conflict" | null;
}

/** An undoable command (one history entry). `batch` is a group move, a delete-all or a clone. */
export type Command =
  | { readonly kind: "create"; readonly handle: Handle; readonly input: DrawingInput }
  | {
      readonly kind: "update";
      readonly handle: Handle;
      readonly before: DrawingInput;
      readonly after: DrawingInput;
    }
  | { readonly kind: "delete"; readonly handle: Handle; readonly input: DrawingInput }
  | { readonly kind: "batch"; readonly commands: readonly Command[] };

/** A write the reducer asks the persistence layer to make, keyed by server id. */
export type Mutation =
  | { readonly op: "create"; readonly id: string; readonly input: DrawingInput }
  | { readonly op: "update"; readonly id: string; readonly input: DrawingInput }
  | { readonly op: "delete"; readonly id: string };

/** `saved | pending | unsaved | conflict` drives the "changes not saved" chip (D07:214, :532). */
export type SaveStatus =
  | { readonly kind: "saved" }
  | { readonly kind: "pending" }
  | { readonly kind: "unsaved"; readonly retryable: boolean }
  | { readonly kind: "conflict" };

/** A one-off user-facing fact; the announcer (PR-B / S10) turns it into D02 copy, once per episode. */
export type Notice =
  | { readonly kind: "changed_elsewhere"; readonly symbol: string; readonly ids: readonly string[] }
  | { readonly kind: "removed_elsewhere"; readonly symbol: string; readonly ids: readonly string[] }
  | { readonly kind: "quota_exceeded"; readonly symbol: string; readonly ids: readonly string[] }
  | { readonly kind: "undo_unavailable"; readonly symbol: string };

/** Content of a server row as a write payload, so it compares with local edits. */
export function inputOf(d: Drawing): DrawingInput {
  return {
    symbol: d.symbol,
    tool: d.tool,
    layout_id: d.layout_id,
    geometry: d.geometry,
    style: d.style,
    label: d.label,
    locked: d.locked,
    visible: d.visible,
    z_index: d.z_index,
  };
}

/** Structural equality of two payloads (plain JSON data only). */
export function sameInput(a: DrawingInput, b: DrawingInput): boolean {
  return canonical(a) === canonical(b);
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
