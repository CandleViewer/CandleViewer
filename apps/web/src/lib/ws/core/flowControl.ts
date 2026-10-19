// E17-T04 S4 (23 5.4, 6.1.1, 8.5; C8): what each pane makes of the streams it watches. A hidden tab or
// an off-screen pane slows its topics to 1 000 ms with a `ctl` (and a collapsed one lets them go),
// a resized heatmap pane re-derives its bucket and sends one `ctl` once it settles. The policies are
// the pure ones of S3b; this keeps what they need around them: the panes, what the engine last
// asked of each topic (its intent: never diffed against what the server holds, 8.5), and what the
// server last said. A topic is a stream, `(ch, rs)` (23 11): a live and a replay stream of one `ch` are
// two subscriptions, each with its own intent, wait and latch. Frames leave through the host: nothing
// here owns a socket.
import type { ConsumerSpec, PaneVisibility } from "../api";
import { createCtlDebouncer } from "../policy/ctlDebouncer";
import { desiredThrottles, type ThrottleConsumer } from "../policy/throttlePolicy";
import type { Timers } from "../policy/timers";
import type { CtlPayload, SubOptions } from "../protocol/frames";
import {
  HEATMAP_BUCKETS_MS,
  HEATMAP_FALLBACK_BUCKET_MS,
  selectHeatmapBucket,
  type HeatmapBucketInput,
  type HeatmapBucketMs,
} from "../protocol/heatmapBucket";
import { splitKey, topicKey } from "./sequencer";

export interface PaneState {
  readonly visibility: PaneVisibility;
  /** The tab or window that hosts the pane is hidden (C8). */
  readonly tabHidden: boolean;
  /** The heatmap's size, and the device pixel ratio of the screen it is on. */
  readonly size?: { readonly cssWidth: number; readonly dpr: number } | undefined;
}

export interface FlowHost {
  /** Every consumer of every stream, with the replay session of its stream. */
  consumers(): Iterable<{ readonly spec: ConsumerSpec; readonly rs: string | undefined }>;
  /** Sends one `ctl` for the stream `(ch, rs)`: `rs` is its replay session, none for the live one (5.4). */
  ctl(ch: string, rs: string | undefined, payload: CtlPayload): void;
  /** What the server should hold changed (a `ch` was let go of, or wanted again). */
  changed(): void;
  /** `welcome.limits.min_throttle_ms`. */
  minThrottleMs(): number | undefined;
}

export interface FlowControl {
  setPane(paneId: string, state: PaneState): void;
  removePane(paneId: string): void;
  /** The options a `sub` of `spec` carries, for the stream `rs` of it: a heatmap's `time_bucket_ms` is derived from its pane (6.1.1, rule 2). */
  optionsOf(spec: ConsumerSpec, rs: string | undefined): SubOptions | undefined;
  /** `sub_ok` or `ctl_ok` said what the server holds for the stream `(ch, rs)` (C4): the registry's bounded copy of it, kept as it is. */
  confirmed(ch: string, rs: string | undefined, effective: Readonly<Record<string, unknown>>): void;
  /** The gateway refused a `ctl` of ours: it never applied, so the next pass asks for it again. */
  denied(ch: string, rs: string | undefined): void;
  /**
   * The rebuild budget (SR-193, 8.5) refused a `ctl`, whatever it asked: it never applied, and asking
   * again at once would be refused again. What the engine took for applied is undone now, and
   * nothing is asked of this stream (of any kind: a hide's slow-down waits too, at most 60 s) until a
   * back-off that doubles with every refusal is over. Its twin is not held.
   */
  refused(ch: string, rs: string | undefined): void;
  /** Collapsed everywhere: not wanted on the server (8.5). */
  isReleased(ch: string, rs: string | undefined): boolean;
  /** A consumer came or went. */
  evaluate(): void;
  /** The last consumer of the stream left: what its panes asked is no more. What the server holds stays until it is told (`unsubscribed`), so a consumer that takes the subscription over finds it as it was. */
  forget(ch: string, rs: string | undefined): void;
  /** An `unsub` of the stream went out, or the server ended it: it holds nothing of it, so nothing was confirmed or asked. */
  unsubscribed(ch: string, rs: string | undefined): void;
  /** The connection ended: the server holds nothing, so nothing was confirmed. */
  reset(): void;
  /** How many entries it keeps in all its maps (C-2.18): bounded by the streams wanted or held, and none once there are none. */
  readonly retained: number;
}

const PANE: PaneState = { visibility: "visible", tabHidden: false };
/** The default `window_seconds` of a heatmap (6.1). */
const WINDOW_SECONDS = 900;
/** 8.5: after a refusal of the rebuild budget "a few seconds", then twice as long each time, to the sliding 60 s window it counts over (7.5). */
export const REFUSED_BACKOFF_MS = 5_000;
export const REFUSED_BACKOFF_MAX_MS = 60_000;

const familyOf = (ch: string): string => ch.split(".", 1)[0] ?? ch;
const finite = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;
const bucketOf = (v: unknown): HeatmapBucketMs | undefined =>
  HEATMAP_BUCKETS_MS.find((b) => b === v);

export function createFlowControl(host: FlowHost, timers: Timers): FlowControl {
  const panes = new Map<string, PaneState>();
  // Everything below is keyed by `topicKey(ch, rs)`: the twins of a `ch` are apart (#3439).
  /** What the engine asked of each confirmed stream, a throttle in ms: the one `sub_ok` gave, then its own `ctl`s. */
  const intents = new Map<string, number>();
  /** What the server ran each confirmed stream at when it was confirmed: its throttle, a heatmap's bucket. */
  const natural = new Map<string, number>();
  const confirmedOptions = new Map<string, Readonly<Record<string, unknown>>>();
  const released = new Set<string>();
  /** The geometry each heatmap was last derived from. */
  const derivedFrom = new Map<string, string>();
  /** How long the last refusal of each stream made it wait, and the timer of that wait while it runs. */
  const backoffs = new Map<string, number>();
  const holds = new Map<string, unknown>();
  /** The streams whose last `ctl` was refused for rate and asked for again: one more refusal and nothing is asked until a reply (8.5). */
  const latched = new Set<string>();
  const debouncer = createCtlDebouncer({
    emit: (key, bucket) => {
      const { ch, rs } = splitKey(key);
      host.ctl(ch, rs, { time_bucket_ms: bucket });
    },
    timers,
  });

  const paneOf = (spec: ConsumerSpec): PaneState => panes.get(spec.paneId) ?? PANE;
  /** Every stream any map keeps something of: one confirmed with options that name no throttle is in no `natural`. */
  function known(): Set<string> {
    const keys = new Set(latched);
    for (const map of [intents, natural, confirmedOptions, derivedFrom, backoffs, holds]) {
      for (const key of map.keys()) keys.add(key);
    }
    return keys;
  }

  /** One geometry per stream: with several panes on a heatmap the widest decides, or each resize would flip the bucket back and forth (6.1.1). */
  function geometry(ch: string, rs: string | undefined): HeatmapBucketInput {
    let widest = { cssWidth: 0, dpr: 0 };
    let userBucketMs: HeatmapBucketMs | undefined;
    let windowSeconds: number | undefined;
    for (const { spec, rs: of } of host.consumers()) {
      if (spec.ch !== ch || of !== rs) continue;
      userBucketMs ??= bucketOf(spec.opts?.time_bucket_ms);
      windowSeconds ??= finite(spec.opts?.window_seconds);
      const { size, visibility } = paneOf(spec);
      if (size !== undefined && visibility !== "collapsed") {
        if (size.cssWidth * size.dpr > widest.cssWidth * widest.dpr) widest = size;
      }
    }
    windowSeconds =
      finite(confirmedOptions.get(topicKey(ch, rs))?.["window_seconds"]) ?? windowSeconds;
    return { windowSeconds: windowSeconds ?? WINDOW_SECONDS, ...widest, userBucketMs };
  }

  const requested = (spec: ConsumerSpec, rs: string | undefined): number =>
    finite(spec.opts?.throttle_ms) ?? natural.get(topicKey(spec.ch, rs)) ?? 0;

  function evaluate(): void {
    const bySession = new Map<string | undefined, ThrottleConsumer[]>(); // the policy keys by `ch`: it runs once for each stream of it
    const heatmaps = new Set<string>();
    for (const { spec, rs } of host.consumers()) {
      const { visibility, tabHidden } = paneOf(spec);
      const wish = { ch: spec.ch, visibility, tabHidden, requestedMs: requested(spec, rs) };
      bySession.set(rs, [...(bySession.get(rs) ?? []), wish]);
      if (familyOf(spec.ch) === "heatmap") heatmaps.add(topicKey(spec.ch, rs));
    }
    let moved = false;
    for (const [rs, consumers] of bySession) {
      for (const [ch, want] of desiredThrottles(consumers, host.minThrottleMs())) {
        const key = topicKey(ch, rs);
        if (want.kind === "release") {
          moved ||= !released.has(key);
          released.add(key);
          forgetServerState(key);
          continue;
        }
        moved ||= released.delete(key);
        if (holds.has(key)) continue; // a refusal of the rebuild budget: nothing is asked of this stream until its wait is over
        // Acted on by difference to the last intent: a hide and a show before the first `ctl_ok` must still send the restore.
        const last = intents.get(key);
        if (last === undefined || last === want.throttleMs) continue;
        intents.set(key, want.throttleMs);
        host.ctl(ch, rs, { throttle_ms: want.throttleMs });
      }
    }
    // Whatever moved (a pane, its size, a consumer), the bucket is derived from the panes that are left.
    for (const key of heatmaps) rederive(key);
    if (moved) host.changed();
  }

  function forgetServerState(key: string): void {
    intents.delete(key);
    natural.delete(key);
    confirmedOptions.delete(key);
    debouncer.forget(key);
    derivedFrom.delete(key);
    backoffs.delete(key);
    latched.delete(key);
    endHold(key);
  }

  /** Ends the wait that follows a refusal: its timer is stopped, never cleared with a handle it does not hold. */
  function endHold(key: string): void {
    const timer = holds.get(key);
    if (timer !== undefined) timers.clearTimeout(timer);
    holds.delete(key);
  }

  /**
   * The bucket after `time_bucket_ms` is re-derived from the pane's size: the debouncer sends it once the pane stops moving.
   * A geometry that is as it was leaves the debounce alone, or any pass at all (a reply, another pane) would keep a settled resize waiting.
   * A heatmap that waits out a refusal is not derived: the wait ends with a derivation from the geometry of that moment.
   */
  function rederive(key: string): void {
    if (holds.has(key)) return;
    const { ch, rs } = splitKey(key);
    const input = geometry(ch, rs);
    const seen = JSON.stringify(input);
    if (derivedFrom.get(key) === seen) return;
    derivedFrom.set(key, seen);
    debouncer.resize(key, input);
  }

  /** The bucket the server holds for `ch` is known: what was derived from the panes is to be compared with it again. */
  function activate(key: string, bucket: HeatmapBucketMs): void {
    debouncer.activate(key, bucket);
    derivedFrom.delete(key);
  }

  /** What the server runs a confirmed heatmap at: the bucket it named, else its default (rule 3). */
  const heldBucket = (key: string): HeatmapBucketMs | undefined =>
    familyOf(splitKey(key).ch) === "heatmap" && confirmedOptions.has(key)
      ? (bucketOf(confirmedOptions.get(key)?.["time_bucket_ms"]) ?? HEATMAP_FALLBACK_BUCKET_MS)
      : undefined;

  /** What the server last confirmed is what it runs: what was taken for applied since is not. */
  function undo(key: string): void {
    const held = finite(confirmedOptions.get(key)?.["throttle_ms"]);
    if (held !== undefined) intents.set(key, held);
    const bucket = heldBucket(key);
    if (bucket !== undefined) activate(key, bucket);
  }

  function denied(key: string): void {
    if (!confirmedOptions.has(key)) return; // let go, or lost with its connection, since the `ctl` left: no latch for a dead key
    undo(key);
    if (latched.has(key)) return; // asked again once and refused again: a server that keeps refusing is not fed
    latched.add(key);
    evaluate();
  }

  return {
    setPane(paneId, state) {
      panes.set(paneId, state);
      evaluate();
    },

    removePane(paneId) {
      panes.delete(paneId);
      evaluate();
    },

    optionsOf(spec, rs) {
      const opts = spec.opts;
      if (familyOf(spec.ch) !== "heatmap") return opts;
      const input = geometry(spec.ch, rs);
      if (input.cssWidth * input.dpr <= 0) return opts; // no size yet: the server's 500 ms (rule 3)
      return { ...opts, time_bucket_ms: selectHeatmapBucket(input) };
    },

    confirmed(ch, rs, effective) {
      const key = topicKey(ch, rs);
      latched.delete(key);
      confirmedOptions.set(key, effective);
      const heatmap = familyOf(ch) === "heatmap";
      const bucket = bucketOf(effective["time_bucket_ms"]) ?? HEATMAP_FALLBACK_BUCKET_MS;
      const before = natural.get(key);
      const now = heatmap ? bucket : (before ?? finite(effective["throttle_ms"]));
      if (now !== undefined) {
        natural.set(key, now);
        // Not dimmed (or not yet known): the server runs at what it says, which for a heatmap can be a throttle of its own and not its bucket.
        const running = finite(effective["throttle_ms"]) ?? now;
        if (!intents.has(key) || intents.get(key) === before) intents.set(key, running);
      }
      if (heatmap) {
        if (bucket !== before) backoffs.delete(key); // a bucket was applied: the next refusal starts from the first wait
        activate(key, bucket);
      }
      evaluate();
    },

    denied: (ch, rs) => denied(topicKey(ch, rs)),

    refused(ch, rs) {
      const key = topicKey(ch, rs);
      if (!confirmedOptions.has(key)) return; // let go, or the connection was lost, since the `ctl` left: nothing is held to ask for again
      const wait = Math.min(
        (backoffs.get(key) ?? REFUSED_BACKOFF_MS / 2) * 2,
        REFUSED_BACKOFF_MAX_MS,
      );
      backoffs.set(key, wait);
      endHold(key); // a second refusal replaces the wait of the first
      holds.set(
        key,
        timers.setTimeout(() => {
          holds.delete(key);
          evaluate(); // asks again for whatever is wanted now: a throttle too, from the geometry of this moment
        }, wait),
      );
      debouncer.forget(key); // a settle that is still running would send inside the wait
      undo(key);
    },

    isReleased: (ch, rs) => released.has(topicKey(ch, rs)),
    evaluate,

    forget(ch, rs) {
      released.delete(topicKey(ch, rs));
      derivedFrom.delete(topicKey(ch, rs)); // a heatmap that never got its sub has no other time to lose it
    },

    unsubscribed: (ch, rs) => forgetServerState(topicKey(ch, rs)),

    reset() {
      for (const key of known()) forgetServerState(key);
    },

    get retained() {
      let count = latched.size + released.size;
      for (const map of [intents, natural, confirmedOptions, derivedFrom, backoffs, holds]) {
        count += map.size;
      }
      return count;
    },
  };
}
