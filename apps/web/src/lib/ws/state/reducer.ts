// E17-T04 S1b: the pure state reducer. No I/O, timers or clock: `reduce(state, event)` depends on
// its arguments alone, so every transition is reviewed and tested without a socket.
import type { KillSwitchPayload, SystemUpdate } from "../protocol/frames";
import type {
  EngineEvent,
  KillSwitchView,
  OrderEntry,
  Quality,
  TransportState,
  WsState,
} from "./types";

/** Deep freeze. States share sub-objects, so one write through any of them must not reach the rest. */
function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

const UNKNOWN_KILL_SWITCH = deepFreeze<KillSwitchView>({ state: "unknown" });

export const INITIAL_WS_STATE = deepFreeze<WsState>({
  transport: "connecting",
  transitionSeq: 0,
  link: { kind: "connecting" },
  quality: "healthy",
  shutdown: null,
  systemStream: "pending",
  killSwitch: UNKNOWN_KILL_SWITCH,
  orderEntry: { enabled: false, reason: "kill_switch_unknown" },
  diagnostics: { connectionId: null, requestId: null },
});

type Patch = { -readonly [K in keyof WsState]?: WsState[K] };

/**
 * `overflowing` (23 8.3) is folded into `saturated`. The wire is untrusted, so any other value is
 * ignored. A `switch`, not a table lookup: a key such as `__proto__` is not a connection class.
 */
function qualityOf(wireClass: unknown): Quality | undefined {
  switch (wireClass) {
    case "healthy":
    case "lagging":
    case "saturated":
      return wireClass;
    case "overflowing":
      return "saturated";
    default:
      return undefined;
  }
}

const isScope = (v: unknown): v is KillSwitchPayload["scope"] => v === "global" || v === "accounts";
const isStringArray = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string");

/**
 * Strict, as the codec is for `auth_ok` (C12): only a well-formed payload is a known state, and
 * anything else must never read as "not killed". Server prose (`reason`, `engaged_by`) is dropped.
 */
function viewOf(k: KillSwitchPayload | undefined): KillSwitchView {
  const ids: unknown = k?.exchange_account_ids;
  if (typeof k?.engaged !== "boolean" || !isScope(k.scope)) return UNKNOWN_KILL_SWITCH;
  if (ids !== undefined && !isStringArray(ids)) return UNKNOWN_KILL_SWITCH;
  const exchangeAccountIds = ids === undefined ? [] : [...ids]; // a copy: no aliasing of the event
  return { state: k.engaged ? "engaged" : "disengaged", scope: k.scope, exchangeAccountIds };
}

/** A finite number or nothing: no payload value reaches the state unless it was vetted. */
const finite = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;

/** A kill-switch fact counts whatever `system` kind carries it (a snapshot carries it on `health`). */
function systemPatch(u: SystemUpdate): Patch {
  const patch: Patch = {};
  if (typeof u !== "object" || u === null || Array.isArray(u)) return patch; // not a payload at all
  if (u.kill_switch !== undefined || u.kind === "kill_switch") {
    patch.killSwitch = viewOf(u.kill_switch);
  }
  if (u.kind === "connection_quality") {
    const quality = qualityOf(u.class);
    if (quality !== undefined) patch.quality = quality;
  }
  if (u.kind === "shutdown_notice") {
    patch.shutdown = {
      closingInMs: finite(u.closing_in_ms),
      expectedDowntimeMs: finite(u.expected_downtime_ms),
    };
  }
  return patch;
}

function patchFor(prev: WsState, e: EngineEvent): Patch {
  switch (e.type) {
    case "connecting":
      return { link: { kind: "connecting" }, quality: "healthy", systemStream: "pending" };
    case "welcome":
      if (typeof e.connectionId !== "string") return {};
      return { diagnostics: { ...prev.diagnostics, connectionId: e.connectionId } };
    case "auth_ok":
      // On a live socket `auth_ok` is an in-place re-auth (23 4.1): the same connection, so a pending
      // shutdown, the quality class and the `system` stream carry over, and no kill switch keeps the
      // last fact. Only a socket announced by `connecting` starts afresh; after `reconnecting` or
      // `offline` the engine broke its promise and the event is ignored.
      if (prev.link.kind === "up") {
        return e.killSwitch === undefined ? {} : { killSwitch: viewOf(e.killSwitch) };
      }
      if (prev.link.kind !== "connecting") return {};
      return {
        link: { kind: "up" },
        quality: "healthy",
        shutdown: null,
        systemStream: "pending",
        killSwitch: viewOf(e.killSwitch),
      };
    case "reconnecting":
      return {
        link: { kind: "reconnecting", attempt: e.attempt, nextAttemptAtMs: e.nextAttemptAtMs },
        systemStream: "pending",
      };
    case "offline":
      return {
        link: { kind: "offline", cause: e.cause, closeCode: e.closeCode },
        systemStream: "pending",
      };
    case "system":
      return systemPatch(e.update);
    case "system_stream":
      return { systemStream: e.status };
    case "request_id":
      if (typeof e.requestId !== "string") return {};
      return { diagnostics: { ...prev.diagnostics, requestId: e.requestId } };
  }
}

function transportOf(s: WsState): TransportState {
  if (s.link.kind !== "up") return s.link.kind;
  if (s.shutdown !== null) return "shutdown_pending";
  return s.quality === "healthy" ? "connected" : `degraded:${s.quality}`;
}

/** C12: enabled only while the kill switch is known to be disengaged and no shutdown is pending. */
function orderEntryOf(killSwitch: KillSwitchView, shuttingDown: boolean): OrderEntry {
  if (killSwitch.state === "engaged") return { enabled: false, reason: "kill_switch_engaged" };
  if (shuttingDown) return { enabled: false, reason: "shutdown_pending" };
  if (killSwitch.state === "unknown") return { enabled: false, reason: "kill_switch_unknown" };
  return { enabled: true, reason: null };
}

/** Structural equality of the plain data in `WsState` (primitives, arrays, plain objects). */
function isSame(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  const entries = Object.entries(a);
  return (
    entries.length === Object.keys(b).length &&
    entries.every(([key, value]) => Object.hasOwn(b, key) && isSame(value, Reflect.get(b, key)))
  );
}

/**
 * WS-E06 (Q6): the kill switch is `unknown`, never "not killed", while the transport is not
 * `connected`/`degraded:*` or the `system` stream is not trustworthy (resyncing, stale, revoked);
 * the value is discarded, not kept. `transitionSeq` moves once per change of `transport`. An event
 * that changes nothing returns `prev` itself, so a store that compares by reference does not
 * notify. Total over the wire: only vetted values enter the (frozen) state.
 */
export function reduce(prev: WsState, event: EngineEvent): WsState {
  const s: WsState = { ...prev, ...patchFor(prev, event) };
  const transport = transportOf(s);
  const isUp = transport === "connected" || transport.startsWith("degraded:");
  const trusted = s.systemStream === "pending" || s.systemStream === "live";
  const killSwitch = isUp && trusted ? s.killSwitch : UNKNOWN_KILL_SWITCH;
  const next: WsState = {
    ...s,
    transport,
    killSwitch,
    orderEntry: orderEntryOf(killSwitch, s.shutdown !== null),
    transitionSeq: prev.transitionSeq + (transport === prev.transport ? 0 : 1),
  };
  return isSame(prev, next) ? prev : deepFreeze(next);
}
