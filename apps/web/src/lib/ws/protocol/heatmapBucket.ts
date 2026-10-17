// E17-T04 S1: `heatmap.time_bucket_ms` derivation (23 6.1.1). The formula, the ladder clamp and
// rule 1 are normative and asserted by the `heatmap_bucket_selection` unit test.

export const HEATMAP_BUCKETS_MS = [100, 250, 500, 1000, 5000] as const;
export type HeatmapBucketMs = (typeof HEATMAP_BUCKETS_MS)[number];
/** Rule 3: what the server applies when the option is absent; also our answer to an unusable window. */
export const HEATMAP_FALLBACK_BUCKET_MS: HeatmapBucketMs = 500;

export interface HeatmapBucketInput {
  readonly windowSeconds: number;
  readonly cssWidth: number;
  readonly dpr: number;
  /** Rule 1: an explicit user choice is used verbatim and never auto-changed. */
  readonly userBucketMs?: HeatmapBucketMs | undefined;
}

/** `window_seconds * 1000 / (css width * dpr / 3)`: the `/3` targets a 3 device-pixel column. */
export function idealBucketMs(windowSeconds: number, cssWidth: number, dpr: number): number {
  const devicePx = cssWidth * dpr;
  if (!Number.isFinite(devicePx) || devicePx <= 0) return Infinity; // no width: nothing to draw
  return (windowSeconds * 1000) / (devicePx / 3);
}

/**
 * Rule 1, else the formula (rule 2, the normal path) with the ladder clamp: the smallest rung at
 * or above `ideal_ms`, but never above 1 000 ms while `ideal_ms <= 2 500`; only a smaller pane
 * takes 5 000 ms.
 */
export function selectHeatmapBucket(input: HeatmapBucketInput): HeatmapBucketMs {
  const { windowSeconds, cssWidth, dpr, userBucketMs } = input;
  if (userBucketMs !== undefined) return userBucketMs;
  if (!Number.isFinite(windowSeconds) || windowSeconds <= 0) return HEATMAP_FALLBACK_BUCKET_MS;
  const ideal = idealBucketMs(windowSeconds, cssWidth, dpr);
  if (ideal > 2500) return 5000;
  return HEATMAP_BUCKETS_MS.find((b) => b >= ideal && b <= 1000) ?? 1000;
}
