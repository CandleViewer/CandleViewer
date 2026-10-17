// E17-T04 S3b (23 8.5, C8): how hard each topic is throttled, decided from who is looking at it. Pure:
// the engine (S4) lists its consumers across every tab and acts on the difference between this result
// and the last one it acted on (its last intent). It must not diff against what the server holds: a
// hide and a show before the first `ctl_ok` is back would find the held value unchanged, and the
// restore would never be sent. A heatmap with no explicit `throttle_ms` is throttled at its
// `time_bucket_ms` by the server (the heatmap branch of the effective options in `ws/topics.py`), so
// after a bucket `ctl_ok` its `requestedMs` is the new bucket: list the consumers and run this again.
import type { PaneVisibility } from "../api";

/** The families a pane draws (6.1). Every other topic (`system`, orders, positions, ...) is never retuned or released. */
const VISUAL_FAMILIES: ReadonlySet<string> = new Set([
  "book",
  "trades",
  "bars",
  "footprint",
  "heatmap",
  "profile",
  "metrics",
  "ticker",
  "liquidations",
]);
/** C8: a hidden window and an off-screen pane both go to at least this. */
export const HIDDEN_THROTTLE_MS = 1_000;
/** The top of the `ctl` `throttle_ms` range (13.6). */
export const MAX_THROTTLE_MS = 60_000;
/** The protocol's minimum throttle (16.2), used until `welcome` says what this server's is. */
export const DEFAULT_MIN_THROTTLE_MS = 50;

/**
 * One pane's interest in one topic. Topics are keyed by `ch` alone, as `ctl`, `unsub` and `resync` are
 * on the wire: 23 11 lets a live and a replay subscription share a `ch` (told apart by `sub_id`, and
 * replay frames carry `rs`) while those frames carry no `sub_id`, so S4 decides how a replay one is
 * keyed (a #572 candidate).
 */
export interface ThrottleConsumer {
  readonly ch: string;
  readonly visibility: PaneVisibility;
  /** The tab or window that hosts the pane is hidden. */
  readonly tabHidden: boolean;
  /**
   * What the pane asked for: `opts.throttle_ms`, else the throttle the server applies now (C4): a
   * heatmap's follows its bucket (see the top of the file), so read it again after a bucket `ctl_ok`.
   * Clamped to 0 to 60 000 and rounded up to a whole millisecond (the schema takes an integer);
   * anything that is not a finite number counts as the fastest the server allows, so a bug shows as
   * traffic, never as NaN.
   */
  readonly requestedMs: number;
}

export type TopicThrottle =
  | { readonly kind: "throttle"; readonly throttleMs: number }
  /** Every consumer is collapsed: unsubscribe (refcount 0). */
  | { readonly kind: "release" };

const RELEASE: TopicThrottle = Object.freeze({ kind: "release" as const }); // one shared value

export function isVisualTopic(ch: string): boolean {
  return ch.split(".", 1).some((family) => VISUAL_FAMILIES.has(family));
}

/**
 * The desired state of every visual topic that has a consumer. A topic runs at the fastest of its
 * consumers' wishes, so a visible pane in one tab keeps its cadence while another tab is hidden.
 * Each wish is the requested value floored at `min_throttle_ms`, and at 1 000 ms while the pane is
 * off-screen or its tab hidden: that is also the restore value once the pane is seen again. A
 * collapsed pane wants nothing, and a topic with no other consumer is released.
 */
export function desiredThrottles(
  consumers: Iterable<ThrottleConsumer>,
  minThrottleMs: number | undefined,
): ReadonlyMap<string, TopicThrottle> {
  const floor =
    typeof minThrottleMs === "number" && Number.isFinite(minThrottleMs)
      ? minThrottleMs
      : DEFAULT_MIN_THROTTLE_MS;
  const desired = new Map<string, TopicThrottle>();
  for (const consumer of consumers) {
    if (!isVisualTopic(consumer.ch)) continue;
    const seen = desired.get(consumer.ch);
    if (consumer.visibility === "collapsed") {
      if (seen === undefined) desired.set(consumer.ch, RELEASE);
      continue;
    }
    const dimmed = consumer.tabHidden || consumer.visibility === "offscreen";
    const asked = Number.isFinite(consumer.requestedMs) ? consumer.requestedMs : 0;
    const requested = Math.min(Math.max(asked, floor), MAX_THROTTLE_MS);
    const wanted = Math.ceil(dimmed ? Math.max(requested, HIDDEN_THROTTLE_MS) : requested);
    const throttleMs = seen?.kind === "throttle" ? Math.min(seen.throttleMs, wanted) : wanted;
    desired.set(consumer.ch, { kind: "throttle", throttleMs });
  }
  return desired;
}
