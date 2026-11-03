/**
 * The one view-as source (E42-S03, SCR-124; `22` `getViewAs` and "View-as session"; `23` §9.6).
 *
 * The banner, its countdown and the read-only state come only from `GET /auth/session/view-as`: the
 * client never infers, starts, extends or ends a context on its own (C-12.4). The state lives in
 * the shell store (`ShellState.viewAs`), so `selectShellMode` stays pure; this module alone writes
 * it: `unknown` until the boot read, then `none` (`204`) or `held` (`200`, `active` or `expired`).
 *
 * - The bootstrap reads it beside `/me` (`bootViewAs`). A read that fails (no answer, a timeout, a
 *   non-`204` refusal or a `200` that is no `ViewAsContext`) fails the boot as `/me`'s does, so the
 *   shell never mounts writable as if no context were held (fail closed).
 * - `startViewAsSync` (one per shell, `startShell`) re-reads it on a `cv.view-as` broadcast
 *   (payload `changed`, posted by `announceChange` after a start or an exit in a sibling tab), when
 *   the countdown reaches `expires_at` on the server's clock, and when the socket leaves `live`
 *   or goes `offline` (a start or an end closes it: `view_as_changed`, `view_as_expired`). A
 *   re-read whose context differs from the page's (none to held, held to none, another target)
 *   reloads the page: only a full load drops every datum of the old scope. A re-read that fails
 *   changes nothing.
 *
 * The context names the target only; the start's reason never reaches this module, the store, a
 * log, storage or the URL.
 */
import type { generated } from "@candleviewer/protocol";
import { HttpError, HttpTimeoutError } from "../../shell/bootstrap/httpClient";
import {
  getShellState,
  setShellState,
  subscribeShellState,
  type HeldViewAs,
  type ViewAsState,
} from "../../shell/bootstrap/store";
import { accessToken } from "./accessToken";

type Wire = generated.rest.components["schemas"]["ViewAsContext"];
/** What a read can answer: no context, or one held. */
export type ViewAsAnswered = Exclude<ViewAsState, { readonly kind: "unknown" }>;
export type ViewAsRead =
  | { readonly ok: true; readonly state: ViewAsAnswered }
  | { readonly ok: false; readonly error: Error };

export const VIEW_AS_PATH = "/api/v1/auth/session/view-as";
/** The same-origin channel the sibling tabs hear a start or an exit on; one message: `changed`. */
export const VIEW_AS_CHANNEL = "cv.view-as";
export const VIEW_AS_CHANGED = "changed";
/** The read's hard timeout, the bootstrap's own (`BOOTSTRAP_TIMEOUT_MS`). */
export const VIEW_AS_READ_TIMEOUT_MS = 10_000;
/** The expiry re-read never runs sooner than this, so a server a second behind is no hot loop. */
export const MIN_REREAD_DELAY_MS = 1_000;
/**
 * While the server still answers live past `expires_at` on its own clock, the expiry re-read backs
 * off from `MIN_REREAD_DELAY_MS`, doubling up to this: a server fault never has every viewing tab
 * polling at 1 Hz.
 */
export const MAX_REREAD_DELAY_MS = 30_000;
const MAX_DELAY_MS = 2 ** 31 - 1;
const NONE: ViewAsAnswered = Object.freeze({ kind: "none" });
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A target's id as `22` declares `target_user_id` (`format: uuid`): the one shape kept here. */
export const isTargetUserId = (value: unknown): value is string =>
  typeof value === "string" && UUID.test(value);

/** A `200` whose body is no `ViewAsContext`: unreadable, never "no context". */
export class ViewAsUnreadableError extends Error {
  constructor() {
    super(`${VIEW_AS_PATH} answered a body that is no view-as context`);
    this.name = "ViewAsUnreadableError";
  }
}

/** The channel's part this module uses: `BroadcastChannel` where the browser has one. */
export interface ViewAsChannel {
  onmessage: ((event: MessageEvent<unknown>) => void) | null;
  postMessage(message: unknown): void;
  close(): void;
}

export interface ViewAsReadPorts {
  /** Test seam; the global `fetch` by default. */
  readonly fetchImpl?: typeof fetch | undefined;
  /** The client clock (epoch ms) the `Date` header's offset is taken against. */
  readonly now?: (() => number) | undefined;
}

export interface ViewAsSyncPorts extends ViewAsReadPorts {
  /** The broadcast channel, or `null` where none exists (then the broadcast is a no-op). */
  readonly openChannel?: (() => ViewAsChannel | null) | undefined;
  /** A full reload of the page: `window.location.reload` by default. */
  readonly reload?: (() => void) | undefined;
}

function openBroadcast(): ViewAsChannel | null {
  const Channel: typeof BroadcastChannel | undefined = globalThis.BroadcastChannel;
  return Channel === undefined ? null : new Channel(VIEW_AS_CHANNEL);
}

/** The server's clock minus the client's at receipt, from the `Date` header; 0 without one. */
function offsetOf(date: string | null, receivedAtMs: number): number {
  const server = date === null ? Number.NaN : Date.parse(date);
  return Number.isFinite(server) ? server - receivedAtMs : 0;
}

const timeOf = (value: unknown): number =>
  typeof value === "string" ? Date.parse(value) : Number.NaN;

/**
 * A served `ViewAsContext`, narrowed to what the shell reads, or `null` when any member is missing
 * or unknown: an unknown `state` is unreadable, never a default.
 */
export function vetViewAs(body: unknown, offsetMs: number): HeldViewAs | null {
  if (typeof body !== "object" || body === null) return null;
  // every member is read as `unknown` and narrowed below: the cast types no value, it names them
  const wire = body as { readonly [K in keyof Wire]?: unknown };
  const { target_user_id: id, target_username: username, target_display_name: display } = wire;
  const { started_at: started, expires_at: expires, read_only: readOnly, state } = wire;
  if (!isTargetUserId(id)) return null;
  if (typeof username !== "string" || username.trim() === "") return null;
  if (display !== null && typeof display !== "string") return null;
  const startedAtMs = timeOf(started);
  const expiresAtMs = timeOf(expires);
  if (!Number.isFinite(startedAtMs) || !Number.isFinite(expiresAtMs)) return null;
  if (readOnly !== true || (state !== "active" && state !== "expired")) return null;
  const targetName = typeof display === "string" && display.trim() !== "" ? display : username;
  return { kind: "held", targetId: id, targetName, startedAtMs, expiresAtMs, state, offsetMs };
}

async function codeOf(res: Response): Promise<string | undefined> {
  try {
    // a problem body or anything else: `code` is read as `unknown` and kept only as a string
    const code = ((await res.json()) as { code?: unknown } | null)?.code;
    return typeof code === "string" ? code : undefined;
  } catch {
    return undefined;
  }
}

/** One `GET /auth/session/view-as` with the tab's bearer. Never rejects: a failure is answered. */
export async function readViewAs(ports: ViewAsReadPorts = {}): Promise<ViewAsRead> {
  const { fetchImpl = fetch, now = Date.now } = ports;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), VIEW_AS_READ_TIMEOUT_MS);
  try {
    const init: RequestInit = {
      method: "GET",
      credentials: "include",
      signal: controller.signal,
      headers: { accept: "application/json" },
    };
    const res = await accessToken.send(VIEW_AS_PATH, init, (sent) => fetchImpl(VIEW_AS_PATH, sent));
    if (res.status === 204) return { ok: true, state: NONE };
    if (res.status !== 200) {
      const message = `${VIEW_AS_PATH} responded ${res.status}`;
      return { ok: false, error: new HttpError(res.status, message, await codeOf(res)) };
    }
    const receivedAtMs = now();
    const body: unknown = await res.json().catch(() => undefined);
    const held = vetViewAs(body, offsetOf(res.headers.get("date"), receivedAtMs));
    return held === null
      ? { ok: false, error: new ViewAsUnreadableError() }
      : { ok: true, state: held };
  } catch (error) {
    if (controller.signal.aborted) {
      const message = `${VIEW_AS_PATH} timed out after ${VIEW_AS_READ_TIMEOUT_MS}ms`;
      return { ok: false, error: new HttpTimeoutError(message) };
    }
    return { ok: false, error: error instanceof Error ? error : new Error("view-as read failed") };
  } finally {
    clearTimeout(timeout);
  }
}

/** The scope a context puts the page in: a change of it is a reload. */
const scopeOf = (state: ViewAsAnswered): string =>
  state.kind === "none" ? "none" : `held:${state.targetId}:${state.startedAtMs}`;

/** The page's scope, from its boot read; `null` until one answered. */
let pageScope: string | null = null;
let expiry: ReturnType<typeof setTimeout> | undefined;
/** Re-arms the expiry re-read; set while a sync runs. */
let onExpiry: (() => void) | null = null;
/** The expiry re-reads in a row that found the context still live past `expires_at`. */
let overshoots = 0;

function armExpiry(state: ViewAsAnswered, now: () => number): void {
  clearTimeout(expiry);
  expiry = undefined;
  if (onExpiry === null || state.kind !== "held" || state.state !== "active") {
    overshoots = 0;
    return;
  }
  const left = state.expiresAtMs - (now() + state.offsetMs);
  let delay = Math.min(MAX_DELAY_MS, Math.max(MIN_REREAD_DELAY_MS, left));
  if (left > 0) overshoots = 0;
  else {
    // past `expires_at` and still live: 1 s, 2 s, 4 s … up to MAX_REREAD_DELAY_MS
    delay = Math.min(MAX_REREAD_DELAY_MS, MIN_REREAD_DELAY_MS * 2 ** Math.min(overshoots, 15));
    overshoots += 1;
  }
  const fire = onExpiry;
  expiry = setTimeout(() => fire(), delay);
}

/**
 * The bootstrap's read: the context the page boots in. Its answer is the page's scope and goes to
 * the store; a failure leaves both alone, and the bootstrap fails closed on it.
 */
export async function bootViewAs(ports: ViewAsReadPorts = {}): Promise<ViewAsRead> {
  const read = await readViewAs(ports);
  if (read.ok) {
    pageScope = scopeOf(read.state);
    setShellState({ viewAs: read.state });
    armExpiry(read.state, ports.now ?? Date.now);
  }
  return read;
}

interface Sync {
  readonly ports: ViewAsSyncPorts;
  readonly stop: () => void;
  stopped: boolean;
  reading: Promise<void> | null;
  again: boolean;
  channel: ViewAsChannel | null;
}
let sync: Sync | null = null;

/**
 * Applies a re-read: the same scope updates the store; another reloads the page into its own, once:
 * the sync stops first, so no later trigger reloads again before the page goes.
 */
function apply(active: Sync, state: ViewAsAnswered): boolean {
  setShellState({ viewAs: state });
  armExpiry(state, active.ports.now ?? Date.now);
  if (scopeOf(state) === pageScope) return false;
  active.stop();
  (active.ports.reload ?? (() => window.location.reload()))();
  return true;
}

/**
 * One re-read at a time: a trigger during one asks for one more after it, never a second. The latch
 * is let go however the loop ends, a store listener that throws included.
 */
function reRead(active: Sync): Promise<void> {
  if (active.stopped || pageScope === null) return Promise.resolve();
  if (active.reading !== null) {
    active.again = true;
    return active.reading;
  }
  active.reading = (async () => {
    try {
      do {
        active.again = false;
        const read = await readViewAs(active.ports);
        if (active.stopped) break;
        if (read.ok && apply(active, read.state)) break; // reloading: nothing more to read here
      } while (active.again);
    } finally {
      active.reading = null;
    }
  })();
  return active.reading;
}

/**
 * Starts the re-read triggers for this page (the broadcast, the expiry timer, the socket); one at a
 * time, so a second start keeps the first. Returns the stop, which `startShell` calls on teardown.
 */
export function startViewAsSync(ports: ViewAsSyncPorts = {}): () => void {
  if (sync !== null) return sync.stop;
  const channel = (ports.openChannel ?? openBroadcast)();
  let unsubscribe = (): void => undefined;
  const active: Sync = {
    ports,
    stopped: false,
    reading: null,
    again: false,
    channel,
    stop: () => {
      if (active.stopped) return; // `stopViewAsSync`, then `startShell`'s own teardown
      active.stopped = true;
      unsubscribe();
      if (channel !== null) {
        channel.onmessage = null;
        channel.close();
      }
      clearTimeout(expiry);
      expiry = undefined;
      onExpiry = null;
      if (sync === active) sync = null;
    },
  };
  // a re-read that throws (a store listener did) is over; the next trigger reads again
  const trigger = (): void => void reRead(active).catch(() => undefined);
  let last = getShellState().connection.kind;
  unsubscribe = subscribeShellState(() => {
    const next = getShellState().connection.kind;
    if (next === last) return;
    const left = last === "live";
    last = next;
    // a start or an end closes the socket (`23` §9.6): it leaves live, or never reaches it
    if (left || next === "offline") trigger();
  });
  if (channel !== null) {
    channel.onmessage = (event) => {
      if (event.data === VIEW_AS_CHANGED) trigger();
    };
  }
  sync = active;
  onExpiry = trigger;
  const current = getShellState().viewAs;
  if (current.kind !== "unknown") armExpiry(current, ports.now ?? Date.now);
  return active.stop;
}

/**
 * The page leaves on its own (Exit's load; the start's, in part 5): its sync stops here, after the
 * broadcast, so a re-read the leave itself causes (the socket's `bye view_as_changed`) can never
 * reload over that load.
 */
export function stopViewAsSync(): void {
  sync?.stop();
}

/** Tells the sibling tabs that this tab started or ended a context; with no channel, nothing. */
export function announceChange(): void {
  sync?.channel?.postMessage(VIEW_AS_CHANGED);
}

/** The session's context as last read (`unknown` before the boot read). */
export const getViewAs = (): ViewAsState => getShellState().viewAs;

/** A context is held, live or ended: every write is the server's to refuse. */
export const isViewing = (): boolean => getShellState().viewAs.kind === "held";

/** The target's display name, else its username; `null` while no context is held. */
export function viewAsTargetName(): string | null {
  const state = getShellState().viewAs;
  return state.kind === "held" ? state.targetName : null;
}

/** Calls `listener` when the context changes, never on another change of the shell's state. */
export function subscribeViewAs(listener: () => void): () => void {
  let seen = getShellState().viewAs;
  return subscribeShellState(() => {
    const next = getShellState().viewAs;
    if (next === seen) return;
    seen = next;
    listener();
  });
}

/** Test-only: stops the sync and forgets the page's scope. */
export function resetViewAs(): void {
  sync?.stop();
  clearTimeout(expiry);
  expiry = undefined;
  onExpiry = null;
  overshoots = 0;
  pageScope = null;
}
