// E17-T04 S1b (C12, WS-E06): an exhaustive check of `reduce`. Every state reachable from the initial
// one under a fixed event alphabet is visited once and every event is applied to it, so a change to
// any (state, event) pair is caught, not only the pairs `reducer.test.ts` names. `reference`
// restates the rules field by field; the invariants state the safety rules on their own.
import { isDeepStrictEqual } from "node:util";
import { describe, expect, it } from "vitest";
import type { KillSwitchPayload } from "../../../src/lib/ws/protocol/frames";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type {
  EngineEvent,
  KillSwitchView,
  Link,
  Quality,
  TopicStatus,
  TransportState,
  WsState,
} from "../../../src/lib/ws/state/types";
import {
  OFF,
  ON,
  authOk,
  connecting,
  killSwitch,
  offline,
  quality,
  retry,
  shutdown,
  stream,
  system,
  wire,
} from "./support/engineEvents";

interface Case {
  readonly name: string;
  readonly event: EngineEvent;
  /** The kill switch the event states, written by hand; absent when it states none. */
  readonly claims?: KillSwitchView;
}

const SCOPED: KillSwitchPayload = { ...ON, scope: "accounts", exchange_account_ids: ["a"] };
const PROSE: KillSwitchPayload = { ...ON, engaged_by: "PROSE_USER", reason: "PROSE_REASON" };
const NONE: KillSwitchView = { state: "unknown" };
const V_OFF: KillSwitchView = { state: "disengaged", scope: "global", exchangeAccountIds: [] };
const V_ON: KillSwitchView = { ...V_OFF, state: "engaged" };
const V_SCOPED: KillSwitchView = { ...V_ON, scope: "accounts", exchangeAccountIds: ["a"] };
const STATUSES: readonly TopicStatus[] = ["pending", "live", "resyncing", "stale", "revoked"];

const CASES: readonly Case[] = [
  { name: "connecting", event: connecting },
  { name: "welcome", event: { type: "welcome", connectionId: "ID_A" } },
  { name: "auth_ok off", event: authOk(OFF), claims: V_OFF },
  { name: "auth_ok on, with prose", event: authOk(PROSE), claims: V_ON },
  { name: "auth_ok scoped", event: authOk(SCOPED), claims: V_SCOPED },
  { name: "auth_ok without a kill switch", event: authOk(), claims: NONE },
  { name: "auth_ok malformed", event: authOk(wire({ engaged: "yes" })), claims: NONE },
  { name: "reconnecting 1", event: retry(1) },
  { name: "reconnecting 2", event: retry(2) },
  { name: "offline", event: offline },
  { name: "offline fatal 4403", event: { type: "offline", cause: "fatal", closeCode: 4403 } },
  ...["healthy", "lagging", "saturated", "overflowing", "__proto__"].map((c): Case => ({
    name: `connection_quality ${c}`,
    event: quality(c),
  })),
  { name: "kill_switch off", event: killSwitch(OFF), claims: V_OFF },
  { name: "kill_switch on", event: killSwitch(ON), claims: V_ON },
  { name: "kill_switch scoped", event: killSwitch(SCOPED), claims: V_SCOPED },
  { name: "kill_switch without a payload", event: killSwitch(undefined), claims: NONE },
  { name: "kill_switch malformed", event: killSwitch({ engaged: true }), claims: NONE },
  {
    name: "health with a kill switch",
    event: system({ kind: "health", kill_switch: OFF }),
    claims: V_OFF,
  },
  { name: "health", event: system({ kind: "health", health: "down" }) },
  { name: "shutdown_notice", event: shutdown },
  { name: "shutdown_notice, no countdown", event: system({ kind: "shutdown_notice" }) },
  { name: "notice", event: system({ kind: "notice", message: "PROSE_NOTICE" }) },
  ...STATUSES.map((s): Case => ({ name: `system stream ${s}`, event: stream(s) })),
  { name: "request_id", event: { type: "request_id", requestId: "REQ_A" } },
];

/** A frozen state or event makes any write inside `reduce` throw, so purity is checked everywhere. */
function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}
const UP = new Set<TransportState>(["connected", "degraded:lagging", "degraded:saturated"]);
const TRUSTED = new Set<TopicStatus>(["pending", "live"]);
const known = (k: KillSwitchView): boolean => k.state !== "unknown";
const trustable = (s: WsState): boolean => UP.has(s.transport) && TRUSTED.has(s.systemStream);
const isFresh = (s: WsState, e: EngineEvent): boolean =>
  e.type === "auth_ok" && s.link.kind !== "up";
const isNotice = (e: EngineEvent): boolean =>
  e.type === "system" && e.update.kind === "shutdown_notice";
const classToQuality = (c: unknown): Quality | undefined =>
  c === "healthy" || c === "lagging"
    ? c
    : c === "saturated" || c === "overflowing"
      ? "saturated"
      : undefined;

function referenceLink(s: WsState, e: EngineEvent): Link {
  switch (e.type) {
    case "connecting":
      return { kind: "connecting" };
    case "auth_ok":
      return { kind: "up" };
    case "reconnecting":
      return { kind: "reconnecting", attempt: e.attempt, nextAttemptAtMs: e.nextAttemptAtMs };
    case "offline":
      return { kind: "offline", cause: e.cause, closeCode: e.closeCode };
    default:
      return s.link;
  }
}

/** The next state, one rule per field, each written from the protocol and ruling text. */
function reference(s: WsState, { event: e, claims }: Case): WsState {
  const u = e.type === "system" ? e.update : undefined;
  const fresh = isFresh(s, e);
  const link = referenceLink(s, e);
  const notice = u?.kind === "shutdown_notice" ? u : undefined;
  const pending = fresh
    ? null
    : notice
      ? { closingInMs: notice.closing_in_ms, expectedDowntimeMs: notice.expected_downtime_ms }
      : s.shutdown;
  const reported = u?.kind === "connection_quality" ? classToQuality(u.class) : undefined;
  const klass: Quality = e.type === "connecting" || fresh ? "healthy" : (reported ?? s.quality);
  const restarted = ["connecting", "reconnecting", "offline"].includes(e.type) || fresh;
  const topic = e.type === "system_stream" ? e.status : restarted ? "pending" : s.systemStream;
  const transport: TransportState =
    link.kind !== "up"
      ? link.kind
      : pending !== null
        ? "shutdown_pending"
        : klass === "healthy"
          ? "connected"
          : `degraded:${klass}`;
  const kill = UP.has(transport) && TRUSTED.has(topic) ? (claims ?? s.killSwitch) : NONE;
  const order = (k: KillSwitchView): WsState["orderEntry"] =>
    k.state === "engaged"
      ? { enabled: false, reason: "kill_switch_engaged" }
      : pending !== null
        ? { enabled: false, reason: "shutdown_pending" }
        : k.state === "unknown"
          ? { enabled: false, reason: "kill_switch_unknown" }
          : { enabled: true, reason: null };
  return {
    transport,
    transitionSeq: s.transitionSeq + (transport === s.transport ? 0 : 1),
    link,
    quality: klass,
    shutdown: pending,
    systemStream: topic,
    killSwitch: kill,
    orderEntry: order(kill),
    diagnostics: {
      connectionId: e.type === "welcome" ? e.connectionId : s.diagnostics.connectionId,
      requestId: e.type === "request_id" ? e.requestId : s.diagnostics.requestId,
    },
  };
}
type Holds = (state: WsState, next: WsState, c: Case) => boolean;
const same = isDeepStrictEqual;

const INVARIANTS: Readonly<Record<string, Holds>> = {
  "matches the field-by-field reference": (s, n, c) => same(n, reference(s, c)),
  "is deterministic": (s, n, c) => same(reduce(s, c.event), n),
  "WS-E06: a known kill switch needs an up transport and a pending or live stream": (_, n) =>
    !known(n.killSwitch) || trustable(n),
  "WS-E06: a known kill switch is the event's claim or the value it had": (s, n, c) =>
    !known(n.killSwitch) || same(n.killSwitch, c.claims) || same(n.killSwitch, s.killSwitch),
  "a claim is taken whenever the transport is up and the stream pending or live": (_, n, c) =>
    c.claims === undefined || !trustable(n) || same(n.killSwitch, c.claims),
  "an event without a claim keeps a known kill switch or drops it": (s, n, c) =>
    c.claims !== undefined ||
    !known(s.killSwitch) ||
    !known(n.killSwitch) ||
    same(n.killSwitch, s.killSwitch),
  "C12: order entry is enabled exactly when disengaged and not shutting down": (_, n) =>
    n.orderEntry.enabled === (n.killSwitch.state === "disengaged" && n.shutdown === null),
  "C12: a disabled order entry names its reason, engaged first, then shutdown": (_, n) =>
    n.orderEntry.reason ===
    (n.orderEntry.enabled
      ? null
      : n.killSwitch.state === "engaged"
        ? "kill_switch_engaged"
        : n.shutdown !== null
          ? "shutdown_pending"
          : "kill_switch_unknown"),
  "transitionSeq moves by one exactly when the transport changes": (s, n) =>
    n.transitionSeq === s.transitionSeq + (n.transport === s.transport ? 0 : 1),
  "a shutdown is set by shutdown_notice and cleared by a new connection's auth_ok": (s, n, c) =>
    (s.shutdown !== null || n.shutdown === null || isNotice(c.event)) &&
    (s.shutdown === null || n.shutdown !== null || isFresh(s, c.event)) &&
    (!isFresh(s, c.event) || n.shutdown === null),
  "the quality class moves only on connecting, a new auth_ok or connection_quality": (s, n, c) =>
    n.quality === s.quality ||
    isFresh(s, c.event) ||
    c.event.type === "connecting" ||
    (c.event.type === "system" && c.event.update.kind === "connection_quality"),
  "an event that changes nothing returns the same object": (s, n) => (n === s) === same(n, s),
  "ids and server prose stay out of every user-facing field": (_, n) =>
    !/ID_|REQ_|PROSE/.test(JSON.stringify({ ...n, diagnostics: null })),
};

const MAX_STATES = 20_000;
const key = (s: WsState): string => JSON.stringify({ ...s, transitionSeq: 0 });

/** Breadth-first to closure: the alphabet is finite and `transitionSeq`, the only counter, is not in the key. */
function sweep() {
  const checks = Object.entries(INVARIANTS).map(([name, holds]) => ({
    name,
    holds,
    failures: new Array<string>(),
  }));
  const states = [deepFreeze(INITIAL_WS_STATE)];
  const seen = new Set([key(INITIAL_WS_STATE)]);
  let claimsTaken = 0;
  for (const state of states) {
    for (const c of CASES) {
      const next = reduce(state, c.event);
      if (c.claims !== undefined && known(next.killSwitch)) claimsTaken += 1;
      for (const check of checks) {
        if (check.holds(state, next, c) || check.failures.length >= 3) continue;
        check.failures.push(`after "${c.name}" from ${key(state)}`);
      }
      const id = key(next);
      if (seen.has(id)) continue;
      seen.add(id);
      states.push(deepFreeze(next));
      if (states.length > MAX_STATES) throw new Error("the reachable state space does not close");
    }
  }
  return { checks, states, claimsTaken };
}

CASES.forEach(deepFreeze);
const SWEEP = sweep();

describe("reduce over every reachable state and event", () => {
  it("reaches every transport row and every kill-switch outcome", () => {
    const reached = (pick: (s: WsState) => unknown) => new Set(SWEEP.states.map(pick));
    expect(reached((s) => s.transport)).toEqual(
      new Set<TransportState>([...UP, "connecting", "reconnecting", "offline", "shutdown_pending"]),
    );
    expect(reached((s) => s.killSwitch.state)).toEqual(
      new Set(["unknown", "engaged", "disengaged"]),
    );
    expect(reached((s) => s.orderEntry.enabled)).toEqual(new Set([true, false]));
    expect(SWEEP.claimsTaken).toBeGreaterThan(0);
    expect(SWEEP.states.length).toBeGreaterThan(100);
  });

  it.each(SWEEP.checks)("$name", ({ failures }) => {
    expect(failures).toEqual([]);
  });
});
