// E17-T04 S2 (23 7.1, C2): per-stream sequence tracking. A stream's baseline is a complete `snap`;
// every later `d` must carry the next number. A gap, a duplicate or an out-of-order frame voids the
// stream, and every `d` is dropped until the next complete `snap`: a gap is never patched.
import { checkSequence, type SeqCheckResult } from "@candleviewer/protocol";

/**
 * Live and replay data of one `ch` can share a connection (23 11), each with its own sequence, so a
 * stream is `(ch, rs)`. `#` is outside the topic alphabet and a replay session id is a UUID, so the
 * key is unambiguous.
 */
export const topicKey = (ch: string, rs?: string | undefined): string => `${ch}#${rs ?? "live"}`;

/** `pending`: no baseline yet. `resyncing`: the baseline was lost and a new `snap` is awaited. */
export type StreamState = "pending" | "live" | "resyncing";

export type Verdict =
  | { readonly kind: "apply" }
  /** Not live: there is no baseline to apply it to, so it is never applied. */
  | { readonly kind: "drop" }
  /** `lastSeq` is the last frame applied, which is what `resync.last_seq` names (7.5). */
  | {
      readonly kind: "gap";
      readonly check: Exclude<SeqCheckResult, "ok">;
      readonly lastSeq: number;
    };

const APPLY: Verdict = { kind: "apply" };
const DROP: Verdict = { kind: "drop" };

type Stream =
  { state: "live"; last: number } | { state: "pending" | "resyncing"; last: number | null };

export interface Sequencer {
  /** A complete `snap` resets the baseline whatever state the stream was in (7.1, item 4). */
  baseline(key: string, seq: number): void;
  /** Judges the next `d`. Allocation-free unless it reports a gap. */
  accept(key: string, seq: number): Verdict;
  /** The stream's state is void for a reason other than a gap (a bad body, a cap, `resnapshot`). */
  discard(key: string): void;
  state(key: string): StreamState;
  /** Kept across a discard so a `resync` can name it; `null` before the first baseline. */
  lastSeq(key: string): number | null;
  /** The subscription is gone. */
  forget(key: string): void;
}

export function createSequencer(): Sequencer {
  const streams = new Map<string, Stream>();
  return {
    baseline(key, seq) {
      streams.set(key, { state: "live", last: seq });
    },
    accept(key, seq) {
      const stream = streams.get(key);
      if (stream === undefined || stream.state !== "live") return DROP;
      const check = checkSequence(stream.last, seq);
      if (check === "ok") {
        stream.last = seq;
        return APPLY;
      }
      streams.set(key, { state: "resyncing", last: stream.last });
      return { kind: "gap", check, lastSeq: stream.last };
    },
    discard(key) {
      streams.set(key, { state: "resyncing", last: streams.get(key)?.last ?? null });
    },
    state: (key) => streams.get(key)?.state ?? "pending",
    lastSeq: (key) => streams.get(key)?.last ?? null,
    forget(key) {
      streams.delete(key);
    },
  };
}
