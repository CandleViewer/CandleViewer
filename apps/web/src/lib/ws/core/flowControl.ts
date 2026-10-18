// E17-T04 S4 (23 5.4, 6.1.1, 8.5; C8): what each pane makes of the streams it watches. A hidden tab or
// an off-screen pane slows its topics to 1 000 ms with a `ctl` (and a collapsed one lets them go),
// a resized heatmap pane re-derives its bucket and sends one `ctl` once it settles. The policies are
// the pure ones of S3b; this keeps what they need around them: the panes, what the engine last
// asked of each topic (its intent: never diffed against what the server holds, 8.5), and what the
// server last said. Frames leave through the host: nothing here owns a socket.
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
  /** Sends one `ctl` for `ch`. */
  ctl(ch: string, payload: CtlPayload): void;
  /** What the server should hold changed (a `ch` was let go of, or wanted again). */
  changed(): void;
  /** `welcome.limits.min_throttle_ms`. */
  minThrottleMs(): number | undefined;
}

export interface FlowControl {
  setPane(paneId: string, state: PaneState): void;
  removePane(paneId: string): void;
  /** The options a `sub` of `spec` carries: a heatmap's `time_bucket_ms` is derived from its pane (6.1.1, rule 2). */
  optionsOf(spec: ConsumerSpec): SubOptions | undefined;
  /** `sub_ok` or `ctl_ok` said what the server holds for `ch` (C4): the registry's bounded copy of it, kept as it is. */
  confirmed(ch: string, effective: Readonly<Record<string, unknown>>): void;
  /** The gateway refused a `ctl` of ours: it never applied, so the next pass asks for it again. */
  denied(ch: string): void;
  /** Collapsed everywhere: not wanted on the server (8.5). */
  isReleased(ch: string): boolean;
  /** A consumer came or went. */
  evaluate(): void;
  /** The last consumer of `ch` left: what its panes asked is no more. What the server holds stays until it is told (`unsubscribed`), so a consumer that takes the subscription over finds it as it was. */
  forget(ch: string): void;
  /** An `unsub` of `ch` went out, or the server ended it: it holds nothing of it, so nothing was confirmed or asked. */
  unsubscribed(ch: string): void;
  /** The connection ended: the server holds nothing, so nothing was confirmed. */
  reset(): void;
}

const PANE: PaneState = { visibility: "visible", tabHidden: false };
/** The default `window_seconds` of a heatmap (6.1). */
const WINDOW_SECONDS = 900;

const familyOf = (ch: string): string => ch.split(".", 1)[0] ?? ch;
const finite = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;
const bucketOf = (v: unknown): HeatmapBucketMs | undefined =>
  HEATMAP_BUCKETS_MS.find((b) => b === v);

export function createFlowControl(host: FlowHost, timers: Timers): FlowControl {
  const panes = new Map<string, PaneState>();
  /** What the engine asked of each confirmed `ch`, a throttle in ms: the one `sub_ok` gave, then its own `ctl`s. */
  const intents = new Map<string, number>();
  /** What the server ran each confirmed `ch` at when it was confirmed: its throttle, a heatmap's bucket. */
  const natural = new Map<string, number>();
  const confirmedOptions = new Map<string, Readonly<Record<string, unknown>>>();
  const released = new Set<string>();
  /** The geometry each heatmap was last derived from. */
  const derivedFrom = new Map<string, string>();
  const debouncer = createCtlDebouncer({
    emit: (ch, bucket) => host.ctl(ch, { time_bucket_ms: bucket }),
    timers,
  });

  const paneOf = (spec: ConsumerSpec): PaneState => panes.get(spec.paneId) ?? PANE;

  /** One geometry per `ch`: with several panes on a heatmap the widest decides, or each resize would flip the bucket back and forth (6.1.1). */
  function geometry(ch: string): HeatmapBucketInput {
    let widest = { cssWidth: 0, dpr: 0 };
    let userBucketMs: HeatmapBucketMs | undefined;
    let windowSeconds: number | undefined;
    for (const { spec } of host.consumers()) {
      if (spec.ch !== ch) continue;
      userBucketMs ??= bucketOf(spec.opts?.time_bucket_ms);
      windowSeconds ??= finite(spec.opts?.window_seconds);
      const { size, visibility } = paneOf(spec);
      if (size !== undefined && visibility !== "collapsed") {
        if (size.cssWidth * size.dpr > widest.cssWidth * widest.dpr) widest = size;
      }
    }
    windowSeconds = finite(confirmedOptions.get(ch)?.["window_seconds"]) ?? windowSeconds;
    return { windowSeconds: windowSeconds ?? WINDOW_SECONDS, ...widest, userBucketMs };
  }

  const requested = (spec: ConsumerSpec): number =>
    finite(spec.opts?.throttle_ms) ?? natural.get(spec.ch) ?? 0;

  function evaluate(): void {
    const consumers: ThrottleConsumer[] = [];
    const heatmaps = new Set<string>();
    for (const { spec } of host.consumers()) {
      const { visibility, tabHidden } = paneOf(spec);
      consumers.push({ ch: spec.ch, visibility, tabHidden, requestedMs: requested(spec) });
      if (familyOf(spec.ch) === "heatmap") heatmaps.add(spec.ch);
    }
    let moved = false;
    for (const [ch, want] of desiredThrottles(consumers, host.minThrottleMs())) {
      if (want.kind === "release") {
        moved ||= !released.has(ch);
        released.add(ch);
        forgetServerState(ch);
        continue;
      }
      moved ||= released.delete(ch);
      // Acted on by difference to the last intent: a hide and a show before the first `ctl_ok` must still send the restore.
      const last = intents.get(ch);
      if (last === undefined || last === want.throttleMs) continue;
      intents.set(ch, want.throttleMs);
      host.ctl(ch, { throttle_ms: want.throttleMs });
    }
    // Whatever moved (a pane, its size, a consumer), the bucket is derived from the panes that are left.
    for (const ch of heatmaps) rederive(ch);
    if (moved) host.changed();
  }

  function forgetServerState(ch: string): void {
    intents.delete(ch);
    natural.delete(ch);
    confirmedOptions.delete(ch);
    debouncer.forget(ch);
    derivedFrom.delete(ch);
  }

  /**
   * The bucket after `time_bucket_ms` is re-derived from the pane's size: the debouncer sends it once the pane stops moving.
   * A geometry that is as it was leaves the debounce alone, or any pass at all (a reply, another pane) would keep a settled resize waiting.
   */
  function rederive(ch: string): void {
    const input = geometry(ch);
    const seen = JSON.stringify(input);
    if (derivedFrom.get(ch) === seen) return;
    derivedFrom.set(ch, seen);
    debouncer.resize(ch, input);
  }

  /** The bucket the server holds for `ch` is known: what was derived from the panes is to be compared with it again. */
  function activate(ch: string, bucket: HeatmapBucketMs): void {
    debouncer.activate(ch, bucket);
    derivedFrom.delete(ch);
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

    optionsOf(spec) {
      const opts = spec.opts;
      if (familyOf(spec.ch) !== "heatmap") return opts;
      const input = geometry(spec.ch);
      if (input.cssWidth * input.dpr <= 0) return opts; // no size yet: the server's 500 ms (rule 3)
      return { ...opts, time_bucket_ms: selectHeatmapBucket(input) };
    },

    confirmed(ch, effective) {
      confirmedOptions.set(ch, effective);
      const heatmap = familyOf(ch) === "heatmap";
      const bucket = bucketOf(effective["time_bucket_ms"]) ?? HEATMAP_FALLBACK_BUCKET_MS;
      const before = natural.get(ch);
      const now = heatmap ? bucket : (before ?? finite(effective["throttle_ms"]));
      if (now !== undefined) {
        natural.set(ch, now);
        // Not dimmed (or not yet known): the server runs at what it says, which for a heatmap can be a throttle of its own and not its bucket.
        const running = finite(effective["throttle_ms"]) ?? now;
        if (!intents.has(ch) || intents.get(ch) === before) intents.set(ch, running);
      }
      if (heatmap) activate(ch, bucket);
      evaluate();
    },

    denied(ch) {
      const held = finite(confirmedOptions.get(ch)?.["throttle_ms"]);
      if (held !== undefined) intents.set(ch, held);
      const bucket = bucketOf(confirmedOptions.get(ch)?.["time_bucket_ms"]);
      if (bucket !== undefined) activate(ch, bucket);
      evaluate();
    },

    isReleased: (ch) => released.has(ch),
    evaluate,

    forget(ch) {
      released.delete(ch);
    },

    unsubscribed: forgetServerState,

    reset() {
      for (const ch of [...natural.keys()]) forgetServerState(ch);
    },
  };
}
