// E17-T04 S2 (23 3.6, 7.2, D17): assembles a chunked `snap`. A snapshot over 4 MiB arrives as frames
// that share one `id`; every one but the last has `s: null` (a binary one also has the `partial`
// header bit, a structured one has no such marker, #3068) and the last carries the single sequence
// number. The set is handed over whole or not at all: a partial snapshot is never applied.
import type { DataBody } from "../protocol/codec";

/** What the assembler may hold across every set at once (charged as below); a chunk that would pass it drops its set. */
export const MAX_HELD_BYTES = 128 * 1024 * 1024;
/**
 * What one set may hold, so a set that never completes cannot starve the other streams. A structured
 * snapshot is split only when its JSON passes the 4 MiB frame limit (3.6), into chunks of nearly that
 * size each, so a real set is several full chunks: the budget has to sit well above the chunk size.
 * At `JSON_HEAP_FACTOR` this holds four of them, about 16 MiB of structured text.
 */
export const MAX_SET_BYTES = 64 * 1024 * 1024;
/** Chunks one set may have: far above any snapshot (3.6 splits at 4 MiB) and far below what tiny chunks reach under the byte caps. */
export const MAX_SET_CHUNKS = 4096;
/** Charged per chunk on top of its size, so a flood of tiny chunks is bounded by bytes as well. */
export const FRAME_OVERHEAD_BYTES = 256;
/**
 * A structured chunk is held as a parsed value. That takes about its own text for a realistic payload
 * and ten to thirty times as much for a degenerate one (runs of empty arrays), so no factor is an upper
 * bound: 4 is a middle charge. What bounds the heap is the per-set cap and the size of one message,
 * which the engine is to check against the 4 MiB frame limit before it parses (S4). A binary chunk is
 * charged its message length, which is above the bytes it keeps. A structured set above what the caps
 * allow is dropped and asked for again (the registry stops asking when it comes back the same).
 */
export const JSON_HEAP_FACTOR = 4;

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
   * Drops the held set and refuses the rest of it and of the set `id` names: the server does not
   * know they were dropped and keeps sending their chunks, and the last one alone must not pass for
   * a snapshot. `id` is the set whose chunk failed; a new set replaces the held one (7.2), and
   * either might still be coming, so both are refused. The next `snap` with another id (or none)
   * lifts the refusal.
   */
  discard(key: string, id?: string | undefined): void;
  /**
   * The stream is gone (released, ended by `unsub_ok` or `revoked`, or the socket replaced): nothing
   * of it comes any more, so nothing is held or refused for it. A stream that goes on (`resnapshot`,
   * a narrowed scope) is `discard`ed instead: the tail of its set still comes and must be refused.
   */
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
  const refused = new Map<string, readonly string[]>(); // stream key -> ids of the sets dropped
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
      if (refused.get(key)?.includes(id)) return { kind: "ignored" };
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
        refused.set(key, replaced ? [id, held.id] : [id]);
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
      const ids = [held?.id, id].filter((v): v is string => v !== undefined);
      if (ids.length > 0) refused.set(key, [...new Set(ids)]);
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
