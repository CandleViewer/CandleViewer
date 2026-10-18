// E17-T04 S4 (23 5.4, 8.5; C8): what each pane makes of the streams it watches. A hidden tab or
// an off-screen pane slows its topics to 1 000 ms with a `ctl`, and a collapsed one lets them go.
// The policy is the pure one of S3b; this keeps what it needs around it: the panes, what the engine
// last asked of each topic (its intent: never diffed against what the server holds, 8.5), and what
// the server last said. Frames leave through the host: nothing here owns a socket.
import type { ConsumerSpec, PaneVisibility } from "../api";
import { desiredThrottles, type ThrottleConsumer } from "../policy/throttlePolicy";
import type { CtlPayload } from "../protocol/frames";

export interface PaneState {
  readonly visibility: PaneVisibility;
  /** The tab or window that hosts the pane is hidden (C8). */
  readonly tabHidden: boolean;
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

const finite = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;

export function createFlowControl(host: FlowHost): FlowControl {
  const panes = new Map<string, PaneState>();
  /** What the engine asked of each confirmed `ch`, a throttle in ms: the one `sub_ok` gave, then its own `ctl`s. */
  const intents = new Map<string, number>();
  /** What the server ran each confirmed `ch` at when it was confirmed: its throttle, a heatmap's bucket. */
  const natural = new Map<string, number>();
  const confirmedOptions = new Map<string, Readonly<Record<string, unknown>>>();
  const released = new Set<string>();

  const paneOf = (spec: ConsumerSpec): PaneState => panes.get(spec.paneId) ?? PANE;

  const requested = (spec: ConsumerSpec): number =>
    finite(spec.opts?.throttle_ms) ?? natural.get(spec.ch) ?? 0;

  function evaluate(): void {
    const consumers: ThrottleConsumer[] = [];
    for (const { spec } of host.consumers()) {
      const { visibility, tabHidden } = paneOf(spec);
      consumers.push({ ch: spec.ch, visibility, tabHidden, requestedMs: requested(spec) });
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
    if (moved) host.changed();
  }

  function forgetServerState(ch: string): void {
    intents.delete(ch);
    natural.delete(ch);
    confirmedOptions.delete(ch);
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

    confirmed(ch, effective) {
      confirmedOptions.set(ch, effective);
      const before = natural.get(ch);
      const now = before ?? finite(effective["throttle_ms"]);
      if (now !== undefined) {
        natural.set(ch, now);
        // Not dimmed (or not yet known): the server runs at what it says, which for a heatmap can be a throttle of its own and not its bucket.
        const running = finite(effective["throttle_ms"]) ?? now;
        if (!intents.has(ch) || intents.get(ch) === before) intents.set(ch, running);
      }
      evaluate();
    },

    denied(ch) {
      const held = finite(confirmedOptions.get(ch)?.["throttle_ms"]);
      if (held !== undefined) intents.set(ch, held);
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
