// `engine.pick.*` (E11-S08, BQ-139): internal, read by tests; not on §8's FrameStats (G-24).

/** The grid's kinds; `cell` and `axis` are structural (BQ-132) and never stored in it. */
export const PICK_KINDS = [
  "drawing",
  "order-line",
  "position-line",
  "alert-line",
  "bubble",
] as const;
export type PickKind = (typeof PICK_KINDS)[number];

/** Upper bounds of the `pickDurationUs` histogram's buckets; the last one is open. */
export const PICK_BUCKETS_US = [25, 50, 100, 250, 500, 1_000, 2_000, Infinity] as const;

export class HitCounters {
  /** `engine.pick.duration_us`: counts per `PICK_BUCKETS_US` bucket (an injected clock only). */
  readonly pickDurationUs = new Uint32Array(PICK_BUCKETS_US.length);
  /** `engine.pick.candidates_tested`, summed; `lastCandidates` is the latest pick's alone. */
  candidatesTested = 0;
  lastCandidates = 0;
  /** `engine.pick.index_rebuilds`: full O(N) re-insertions (scale drift, `replace`). */
  indexRebuilds = 0;
  /** `engine.pick.objects_registered{kind}`. */
  readonly registered = Object.fromEntries(PICK_KINDS.map((k) => [k, 0])) as Record<
    PickKind,
    number
  >;

  observe(us: number): void {
    let i = 0;
    while (us > (PICK_BUCKETS_US[i] as number)) i += 1;
    this.pickDurationUs[i] = (this.pickDurationUs[i] as number) + 1;
  }
}
