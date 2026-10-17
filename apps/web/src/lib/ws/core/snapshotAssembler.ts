// E17-T04 S2 (23 3.6, 7.2, D17): assembles a chunked `snap`. A snapshot over 4 MiB arrives as frames
// that share one `id`; every one but the last has `s: null` (a binary one also has the `partial`
// header bit, a structured one has no such marker, #3068) and the last carries the single sequence
// number. The set is handed over whole or not at all: a partial snapshot is never applied.
import type { DataBody } from "../protocol/codec";

/** What the assembler may hold across every set at once (charged as below); a chunk that would pass it drops its set. */
export const MAX_HELD_BYTES = 64 * 1024 * 1024;
/** What one set may hold, so a set that never completes cannot starve the other streams. */
export const MAX_SET_BYTES = 32 * 1024 * 1024;
/** Chunks one set may have: far above any snapshot (3.6 splits at 4 MiB) and far below what tiny chunks reach under the byte caps. */
export const MAX_SET_CHUNKS = 4096;
/** Charged per chunk on top of its size, so a flood of tiny chunks is bounded by bytes as well. */
export const FRAME_OVERHEAD_BYTES = 256;
/**
 * A structured chunk is held as a parsed value, which takes several times its JSON text (`[[],[],...]`
 * parses to about 8 times), so it is charged that much; a binary chunk is charged its message length,
 * which is above the bytes it keeps. One set can then hold about 4 MiB of structured text at most
 * (`MAX_SET_BYTES` over this). The snapshots that reach megabytes are binary (book, trades, bars, footprint
 * and heatmap, 3.4 and 6.1), so a structured set that large is not expected; one that comes is dropped
 * and asked for again (guard-bounded).
 */
export const JSON_HEAP_FACTOR = 8;

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
  | { readonly kind: "pending" }
  | {
      readonly kind: "complete";
      readonly seq: number;
      readonly bodies: readonly [DataBody, ...DataBody[]];
      /** Sum of the chunks' encoded sizes. */
      readonly size: number;
      readonly decodeMs: number;
    }
  /**
   * The chunk contradicts itself (its markers disagree), names no set, or is the last of a set that is
   * not held (a single-frame `snap` has no id, 13.1). Nothing held changes: the caller `discard`s the
   * stream's set, so its tail is refused.
   */
  | { readonly kind: "malformed" }
  /** The set passed a cap and was dropped. */
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
  /** A set of this stream is incomplete. */
  holds(key: string): boolean;
  /** Bytes held across every set, as charged. */
  readonly heldBytes: number;
}

export function createSnapshotAssembler(
  options: {
    readonly maxHeldBytes?: number | undefined;
    readonly maxSetBytes?: number | undefined;
  } = {},
): SnapshotAssembler {
  const cap = options.maxHeldBytes ?? MAX_HELD_BYTES;
  const setCap = options.maxSetBytes ?? MAX_SET_BYTES;
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
      // Whatever can reject a frame is judged before anything is touched, so a bad frame leaves the
      // held set as it was (the caller then `discard`s it): a replaced set must not let its tail pass.
      // 3.6: the markers agree (`partial` is set exactly on the chunks with `s: null`).
      if (chunk.partial !== undefined && chunk.partial !== (s === null))
        return { kind: "malformed" };
      if (id === undefined) {
        if (s === null) return { kind: "malformed" }; // a chunk of no set
        // A single-frame `snap` replaces an incomplete set (D17) and completes alone.
        drop(key);
        refused.delete(key);
        const { size, decodeMs } = chunk;
        return { kind: "complete", seq: s, bodies: [body], size, decodeMs };
      }
      if (refused.get(key) === id) return { kind: "ignored" };
      const held = sets.get(key);
      if (s !== null && held?.id !== id) return { kind: "malformed" }; // the last chunk completes the set it names
      refused.delete(key);
      const replaced = held !== undefined && held.id !== id; // D17: a new `id` replaces an incomplete set
      if (replaced) drop(key);
      let set = replaced ? undefined : held;
      const cost = chunk.size * (body.e === "j" ? JSON_HEAP_FACTOR : 1) + FRAME_OVERHEAD_BYTES;
      if (
        (set?.bodies.length ?? 0) >= MAX_SET_CHUNKS ||
        (set?.cost ?? 0) + cost > setCap ||
        heldBytes + cost > cap
      ) {
        drop(key);
        refused.set(key, id);
        return { kind: "overflow" };
      }
      if (set === undefined) {
        set = { id, bodies: [body], size: 0, cost: 0, decodeMs: 0 };
        sets.set(key, set);
      } else set.bodies.push(body);
      set.size += chunk.size;
      set.cost += cost;
      set.decodeMs += chunk.decodeMs;
      heldBytes += cost;
      if (s === null) return { kind: "pending" };
      drop(key);
      const { bodies, size, decodeMs } = set;
      return { kind: "complete", seq: s, bodies, size, decodeMs };
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
    holds: (key) => sets.has(key),
    get heldBytes() {
      return heldBytes;
    },
  };
}
