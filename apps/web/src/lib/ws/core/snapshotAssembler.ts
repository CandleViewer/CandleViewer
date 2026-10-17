// E17-T04 S2 (23 3.6, 7.2, D17): assembles a chunked `snap`. A snapshot over 4 MiB arrives as frames
// that share one `id`; every one but the last has `s: null` (a binary one also has the `partial`
// header bit, a structured one has no such marker, ruling Q1, #3068) and the last carries the single
// sequence number. The set is handed over whole or not at all: a partial snapshot is never applied.
import type { DataBody } from "../protocol/codec";

/** What the assembler may hold across every set at once; a chunk that would pass it drops its set. */
export const MAX_HELD_BYTES = 32 * 1024 * 1024;
/** Charged per chunk on top of its size, so a flood of tiny chunks is bounded by bytes as well. */
export const FRAME_OVERHEAD_BYTES = 256;

export interface Chunk {
  /** The set's shared id (3.6); a single-frame `snap` has none. */
  readonly id: string | undefined;
  /** `null` on every chunk but the last. */
  readonly s: number | null;
  /** The binary header's `partial` bit; `undefined` for a structured chunk, which has none. */
  readonly partial: boolean | undefined;
  readonly body: DataBody;
  /** The frame's encoded size (`DataFrame.size`). */
  readonly size: number;
  readonly decodeMs: number;
}

export type Assembly =
  | { readonly kind: "pending"; readonly replaced: boolean }
  | {
      readonly kind: "complete";
      readonly seq: number;
      readonly bodies: readonly [DataBody, ...DataBody[]];
      /** Sum of the chunks' encoded sizes. */
      readonly size: number;
      readonly decodeMs: number;
      readonly replaced: boolean;
    }
  /** The chunk contradicts itself (its markers disagree) or names no set to join. It is not kept; `discard` the stream's set. */
  | { readonly kind: "malformed" }
  /** The set passed the held-bytes cap and was dropped. */
  | { readonly kind: "overflow" }
  /** A chunk of a set that was dropped: what remains of it is not a snapshot. */
  | { readonly kind: "ignored" };

interface Held {
  readonly id: string;
  readonly bodies: [DataBody, ...DataBody[]];
  size: number;
  cost: number;
  decodeMs: number;
}

export interface SnapshotAssembler {
  /** Takes one `snap` frame of stream `key`. */
  push(key: string, chunk: Chunk): Assembly;
  /**
   * Drops the held set and refuses the rest of a set: the server does not know it was dropped and
   * keeps sending its chunks, and the last one alone must not pass for a snapshot. `id` names the
   * set whose chunk failed (a new set replaces the held one, 7.2); without it the held set is the
   * one refused. The next `snap` with another id (or none) lifts the refusal.
   */
  discard(key: string, id?: string | undefined): void;
  /** The subscription ended or its state was voided (`unsub_ok`, `revoked`, `resnapshot`): no more chunks of it come. */
  forget(key: string): void;
  /** Bytes held across every set, overhead included. */
  readonly heldBytes: number;
}

export function createSnapshotAssembler(
  options: { readonly maxHeldBytes?: number | undefined } = {},
): SnapshotAssembler {
  const cap = options.maxHeldBytes ?? MAX_HELD_BYTES;
  const sets = new Map<string, Held>();
  const refused = new Map<string, string>(); // stream key -> id of the dropped set
  let heldBytes = 0;

  function drop(key: string): Held | undefined {
    const held = sets.get(key);
    if (held === undefined) return undefined;
    sets.delete(key);
    heldBytes -= held.cost;
    return held;
  }

  return {
    push(key, chunk) {
      const { id, s, body } = chunk;
      // 3.6: the markers agree (`partial` is set exactly on the chunks with `s: null`).
      if (chunk.partial !== undefined && chunk.partial !== (s === null))
        return { kind: "malformed" };
      if (id !== undefined && refused.get(key) === id) return { kind: "ignored" };
      refused.delete(key);
      // D17: a `snap` with a new `id`, or with none, replaces an incomplete set.
      const replaced = sets.get(key)?.id !== id && drop(key) !== undefined;
      if (s !== null && !sets.has(key)) {
        const { size, decodeMs } = chunk;
        return { kind: "complete", seq: s, bodies: [body], size, decodeMs, replaced };
      }
      // A chunk of a set, so it must name the set (the final chunk of a held one does, as it matched).
      if (id === undefined) return { kind: "malformed" };
      const cost = chunk.size + FRAME_OVERHEAD_BYTES;
      if (heldBytes + cost > cap) {
        drop(key);
        refused.set(key, id);
        return { kind: "overflow" };
      }
      let held = sets.get(key);
      if (held === undefined) {
        held = { id, bodies: [body], size: 0, cost: 0, decodeMs: 0 };
        sets.set(key, held);
      } else held.bodies.push(body);
      held.size += chunk.size;
      held.cost += cost;
      held.decodeMs += chunk.decodeMs;
      heldBytes += cost;
      if (s === null) return { kind: "pending", replaced };
      drop(key);
      const { bodies, size, decodeMs } = held;
      return { kind: "complete", seq: s, bodies, size, decodeMs, replaced };
    },
    discard(key, id) {
      const held = drop(key);
      const refuse = id ?? held?.id;
      if (refuse !== undefined) refused.set(key, refuse);
    },
    forget(key) {
      drop(key);
      refused.delete(key);
    },
    get heldBytes() {
      return heldBytes;
    },
  };
}
