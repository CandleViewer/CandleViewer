/**
 * The open machine's live state (E42-S08 §3.4; BQ-7 as recommended, not yet ruled): one WS
 * subscription, `machines.{key}.state` (E17-T08, `23` §6.4), for the open machine only, and only
 * while its environment is the shell's (the topic carries the serving process's machines). No
 * option is sent: the topic takes the universal options alone. Frames are drained once per
 * animation frame, never per arrival (C9, as the tape's feed does), each body vetted as
 * `MachinesEntityState` (an unknown kind, a value off its pattern or another environment's body is
 * dropped, never guessed), and the page hears only a change of `state`, `regions` or `degraded`:
 * React state is never set per message (C-2.20).
 *
 * What a frame does (§3.4): it never starts a REST read. A live state that differs from the saved
 * snapshot is a static line with [Re-read] (the machine view's); the latch seen live, `degraded`
 * false to true, is said once, assertively, per machine and episode (D05:773). The topic's
 * `degraded` never goes back to false after an acknowledgement (`23` §6.4), so a clear is only
 * ever shown from a REST read. A refused or ended subscription (a machine no longer live, a scope
 * refusal) says nothing and shows nothing: the facts stand as read. The client derives no state,
 * transition or latch: it shows what the topic published (C-2.19 to C-2.22).
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import type { TopicFrame, WsClient } from "../../../lib/ws/api";
import { getActiveClient, subscribeActiveClient } from "../../../lib/ws/client/activeClient";
import { useShellSelector } from "../../../shell/useShellSelector";
import { announce, forget } from "../../app-shell/announcer";
import { INSPECTOR_COPY as COPY } from "./copy";
import type { MachineRef } from "./inspectorReads";
import { ROW_KINDS } from "./kinds";

/** The live state the machine view compares with its saved snapshot. */
export interface LiveState {
  /** The published state: the root's active child (the first region's, for a parallel chart). */
  readonly state: string;
  /** Parallel charts only: each region's active state. */
  readonly regions: Readonly<Record<string, string>>;
  /** The `chain_trips` latch as published. */
  readonly degraded: boolean;
  /** `updated_at_ms`: when the reported change happened. */
  readonly at: number;
}

export interface FeedClock {
  readonly raf: (callback: (frameTimeMs: number) => void) => number;
  readonly caf: (handle: number) => void;
}

const browserClock = (): FeedClock => ({
  raf: (callback) => requestAnimationFrame(callback),
  caf: (handle) => cancelAnimationFrame(handle),
});

/** The pane the subscription belongs to: the inspector's page. */
export const FEED_PANE = "admin-statecharts";
/** The assertive key of a machine's latch seen live: one per machine and episode. */
const latchKey = (ref: MachineRef): string => `admin:statecharts:latched:${ref.env}:${ref.key}`;

/** A published name (a state, a region, a region's state) is only shown: up to 200 characters. */
const MAX_NAME = 200;
const HASH = /^[0-9a-f]{64}$/;
const MAX_TAGS = 32;
const MAX_REGIONS = 32;
const KINDS: readonly string[] = ROW_KINDS;

type Json = Record<string, unknown>;
const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);
/** React escapes a shown name and no path is built from one: only its length is bounded. */
const isName = (raw: unknown): raw is string =>
  typeof raw === "string" && raw.length > 0 && raw.length <= MAX_NAME;

/** `regions` as served: each region's id to its active state; `null` when one is no name. */
function regionsOf(raw: unknown): Record<string, string> | null {
  if (raw === undefined) return {};
  if (!isRecord(raw)) return null;
  const entries = Object.entries(raw);
  if (entries.length > MAX_REGIONS) return null;
  const regions: [string, string][] = [];
  for (const [region, state] of entries) {
    if (!isName(region) || !isName(state)) return null;
    regions.push([region, state]);
  }
  return Object.fromEntries(regions);
}

/**
 * A `machines.{entity}.state` body for `ref`'s machine, vetted as `MachinesEntityState`; `null` when
 * any field is off its schema or the body is another environment's.
 */
export function vetMachineState(raw: unknown, ref: MachineRef): LiveState | null {
  if (!isRecord(raw)) return null;
  const kind = raw["machine_kind"];
  const state = raw["state"];
  const tags = raw["tags"];
  const degraded = raw["degraded"];
  const hash = raw["machine_hash"];
  const at = raw["updated_at_ms"];
  if (typeof kind !== "string" || !KINDS.includes(kind)) return null;
  if (!isName(state)) return null;
  if (!Array.isArray(tags) || tags.length > MAX_TAGS || tags.some((t) => typeof t !== "string")) {
    return null;
  }
  if (typeof degraded !== "boolean" || typeof hash !== "string" || !HASH.test(hash)) return null;
  if (raw["environment"] !== ref.env) return null;
  if (typeof at !== "number" || !Number.isSafeInteger(at) || at < 0) return null;
  const regions = regionsOf(raw["regions"]);
  return regions === null ? null : { state, regions, degraded, at };
}

/** The structured body a frame carries, if it carries one (a binary body is never sent here). */
function bodyOf(frame: TopicFrame): unknown {
  if (frame.kind === "reset") return undefined;
  const body = frame.kind === "snap" ? frame.bodies[frame.bodies.length - 1] : frame.body;
  return body?.e === "j" ? body.p : undefined;
}

/** Whether two live states show the same: `at` alone changing is no news. */
const sameLive = (a: LiveState | null, b: LiveState | null): boolean =>
  a === b ||
  (a !== null &&
    b !== null &&
    a.state === b.state &&
    a.degraded === b.degraded &&
    JSON.stringify(a.regions) === JSON.stringify(b.regions));

/**
 * Subscribes to `ref`'s topic on `client` and drains it once per animation frame; `onLive` hears
 * each change, `null` once a reset voids what was shown. Returns the stop: it releases the
 * subscription and ends the loop, and is idempotent.
 */
export function startMachineFeed(
  client: Pick<WsClient, "consume">,
  ref: MachineRef,
  onLive: (live: LiveState | null) => void,
  clock: FeedClock = browserClock(),
): () => void {
  const handle = client.consume({
    ch: `machines.${ref.key}.state`,
    paneId: FEED_PANE,
    priority: "other",
  });
  let shown: LiveState | null = null;
  let frame: number | undefined;
  let stopped = false;
  const tick = (): void => {
    frame = undefined;
    if (stopped) return;
    let next = shown;
    for (const item of handle.read()) {
      if (item.kind === "reset") {
        next = null; // the state held is void; a snapshot follows unless the subscription ended
        continue;
      }
      const live = vetMachineState(bodyOf(item), ref);
      if (live !== null) next = live;
    }
    if (!sameLive(next, shown)) {
      shown = next;
      onLive(next);
    }
    frame = clock.raf(tick);
  };
  frame = clock.raf(tick);
  return () => {
    if (stopped) return;
    stopped = true;
    if (frame !== undefined) clock.caf(frame);
    frame = undefined;
    handle.release();
  };
}

/** What the saved snapshot shows, for the comparison and the latch's baseline. */
export interface SavedState {
  readonly state: string;
  readonly degraded: boolean;
}

/**
 * The open machine's live state while the calling view is mounted, or `null`: no client, another
 * environment, nothing published yet, or a subscription that ended. A change of machine or
 * environment, or the unmount, releases the subscription. The latch seen live while the saved
 * snapshot shows it clear is said once, assertively (`machine.latched_now`).
 */
export function useMachineFeed(
  ref: MachineRef,
  saved: SavedState | undefined,
  clock?: FeedClock,
): LiveState | null {
  const shellEnv = useShellSelector((s) => s.environment);
  const client = useSyncExternalStore(subscribeActiveClient, getActiveClient, getActiveClient);
  const { key, env } = ref;
  const [held, setHeld] = useState<{ readonly id: string; readonly live: LiveState } | null>(null);
  const id = `${env}:${key}`;
  useEffect(() => {
    if (client === null || shellEnv !== env) return undefined;
    const stop = startMachineFeed(
      client,
      { key, env },
      (live) => setHeld(live === null ? null : { id: `${env}:${key}`, live }),
      clock,
    );
    return () => {
      stop();
      setHeld(null);
    };
  }, [client, shellEnv, key, env, clock]);
  const live = held !== null && held.id === id ? held.live : null;
  const latched = live?.degraded === true && saved?.degraded === false;
  useEffect(() => {
    if (latched) announce("assertive", COPY.view.latchedNow(key), latchKey({ key, env }));
  }, [latched, key, env]);
  // The episode ends with the view: a machine opened again is read again (its REST latch with it).
  useEffect(() => () => forget(latchKey({ key, env })), [key, env]);
  return live;
}
