// E17-T04 S5b (ADR-0005, D13; 23 4.3, 3.6): the port protocol between a tab and the shared worker. Whatever
// arrives on a port is untrusted input (any same-origin script can connect to a shared worker and post to it),
// so `parseClientMessage` returns a new object holding only the fields it checked, or nothing. The version is
// named by the tab's `connect` only (a tab of another build is refused there); what the worker posts back is
// checked for its shape and handed on as it is, which is all a tab of the same worker can need. The access
// token crosses in one message, `token`, from the tab to the worker's memory; no other message carries it and
// none is logged. The value of an option, a fault command and the frames of a `data` message are not checked
// here: the server refuses an unknown option, the fault channel checks its commands, and the engine made the frames.
// A message the worker refuses gets no reply (it only counts it): the client times out on a connect or a consume (S5f).
import type { PaneVisibility, TokenResult, TopicFrame } from "../api";
import { MAX_TOKEN_LENGTH } from "../core/connection";
import type { EngineCounters } from "../core/engine";
import { isTopic, isUuid, type DataBody } from "../protocol/codec";
import type { HelloPayload, SubOptions, SystemUpdate } from "../protocol/frames";
import type { TopicStatus, WsState } from "../state/types";
import type { SubscriptionPriority } from "../../../shell/bootstrap/subscriptionOrder";

export const PORT_PROTOCOL_VERSION = 1;
export type Shell = NonNullable<HelloPayload["shell"]>;

// Tab -> worker.

export interface ConnectMessage {
  readonly t: "connect";
  readonly v: typeof PORT_PROTOCOL_VERSION;
  /** `ws:` or `wss:`; never a token, a userinfo or a query (4.3: a token in the URL is refused). */
  readonly wsUrl: string;
  readonly shell: Shell;
  readonly locale: string;
  readonly clientVersion: string;
}
export interface ConsumeMessage {
  readonly t: "consume";
  /** The tab's own name for this consumer: every later message about it carries it. */
  readonly id: string;
  readonly ch: string;
  readonly rs?: string;
  readonly opts?: SubOptions;
  readonly pane: string;
  readonly priority: SubscriptionPriority;
}
export interface ReleaseMessage {
  readonly t: "release";
  readonly id: string;
}
/** The consumer lost its state (its queue overflowed): void it and ask for a fresh snapshot. */
export interface ResyncMessage {
  readonly t: "resync";
  readonly id: string;
}
export interface PaneMessage {
  readonly t: "pane";
  readonly id: string;
  readonly visibility: PaneVisibility;
  /** A heatmap's size (6.1.1): both or neither. */
  readonly cssWidth?: number;
  readonly dpr?: number;
}
export interface FocusMessage {
  readonly t: "focus";
  readonly id: string | null;
}
export interface VisibilityMessage {
  readonly t: "visibility";
  readonly hidden: boolean;
}
/** The answer to a `tokenRequest`; the only message that carries a token. */
export interface TokenMessage {
  readonly t: "token";
  readonly req: number;
  readonly result: TokenResult;
}
/** This tab is done: its consumers and panes go, and the last tab to leave closes the socket. */
export interface StopMessage {
  readonly t: "stop";
}
/** Dev only: the worker hands it to the fault channel if it has one, else drops it. Checked there. */
export interface FaultMessage {
  readonly t: "fault";
  readonly command: unknown;
}
export type ClientMessage =
  | ConnectMessage
  | ConsumeMessage
  | ReleaseMessage
  | ResyncMessage
  | PaneMessage
  | FocusMessage
  | VisibilityMessage
  | TokenMessage
  | StopMessage
  | FaultMessage;

// Worker -> tab.

export interface StateMessage {
  readonly t: "state";
  readonly state: WsState;
}
/** What one consumer gets: the frames since its last message (in order, buffers transferred), and what its handle reads now. */
export interface DataMessage {
  readonly t: "data";
  readonly id: string;
  readonly frames: readonly TopicFrame[];
  readonly status: TopicStatus;
  readonly effective: Readonly<Record<string, unknown>>;
  readonly source: "live" | "replay";
}
export interface SystemMessage {
  readonly t: "system";
  readonly update: SystemUpdate;
}
export interface TokenRequestMessage {
  readonly t: "tokenRequest";
  readonly req: number;
  /** The token of the last answer was refused (4401): hand out another. */
  readonly invalidate: boolean;
}
export interface HostCounters {
  readonly tabs: number;
  readonly consumers: number;
  readonly queuedFrames: number;
  /** Consumers whose queue overflowed in the worker, and were voided. */
  readonly overflows: number;
  /** Messages from a tab the worker refused: malformed, or not served (a name taken or unknown, past a limit). */
  readonly rejectedMessages: number;
  /** Updates of a `system` kind past the few the host keeps for a tab that joins late (every tab still hears them). */
  readonly droppedSystemUpdates: number;
}
/** E04-S02's diagnostics: in memory, never exported (D8). */
export interface WsDiagnostics {
  readonly engine: EngineCounters;
  readonly host: HostCounters;
  readonly slowConsumerHint: readonly string[];
  readonly clockSkewMs: number | undefined;
}
export interface DiagMessage {
  readonly t: "diag";
  readonly diag: WsDiagnostics;
}
export type WorkerMessage =
  StateMessage | DataMessage | SystemMessage | TokenRequestMessage | DiagMessage;

// Checks.

type Rec = Readonly<Record<string, unknown>>;
const isRec = (v: unknown): v is Rec => typeof v === "object" && v !== null && !Array.isArray(v);
const isText = (v: unknown, max: number): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= max;
const oneOf = <T extends string>(list: readonly T[], v: unknown): v is T => list.includes(v as T); // `includes` of an unknown value
const isNat = (v: unknown): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const isBoundedPositive = (v: unknown, max: number): v is number =>
  typeof v === "number" && Number.isFinite(v) && v > 0 && v <= max;
/**
 * A copy of the record `v` made through its JSON text, so what was measured is what is kept (a getter
 * is read once) and a key such as `__proto__` is a plain own property of the copy, never its prototype.
 * What is not a record, a cyclic value (structured clone keeps cycles), a BigInt and a text over `max`
 * characters are refused.
 */
const jsonCopy = (v: unknown, max: number): Rec | undefined => {
  try {
    const text = JSON.stringify(v); // `undefined` for a function: its `length` throws
    const copy: unknown = text.length <= max ? JSON.parse(text) : undefined;
    return isRec(copy) ? copy : undefined; // a list, a text, null: and a `toJSON` may make any of them
  } catch {
    return undefined;
  }
};

const MAX_ID = 64;
const MAX_URL = 512;
const MAX_OPTS_JSON = 4096;
const MAX_PANE_PX = 100_000;
const MAX_DPR = 16;
/**
 * The members of a closed union, each named once: `Record<T, true>` needs every key and refuses any
 * other, so a member added to `T` stops compiling here instead of being refused at run time.
 */
const membersOf = <T extends string>(all: Readonly<Record<T, true>>): readonly T[] =>
  Object.keys(all) as T[]; // cast: the keys of a `Record<T, true>` are exactly the members of `T`
const SHELLS = membersOf<Shell>({ electron: true, browser: true, other: true });
const VISIBILITIES = membersOf<PaneVisibility>({ visible: true, offscreen: true, collapsed: true });
const PRIORITIES = membersOf<SubscriptionPriority>({ private: true, focused: true, other: true });
const STATUSES = membersOf<TopicStatus>({
  pending: true,
  live: true,
  resyncing: true,
  stale: true,
  revoked: true,
});

/** A socket URL the worker may open: `ws(s)`, with no userinfo, query or fragment, so a token can never ride on it. */
export function isWsUrl(v: unknown): v is string {
  if (!isText(v, MAX_URL)) return false;
  try {
    const url = new URL(v);
    const socket = url.protocol === "wss:" || url.protocol === "ws:";
    // `search` and `hash` are empty for a bare `?` or `#`, which is still the start of one
    const bare = !v.includes("?") && !v.includes("#");
    return socket && bare && url.username === "" && url.password === "";
  } catch {
    return false;
  }
}

function parseConnect(m: Rec): ConnectMessage | undefined {
  const { v, wsUrl, shell, locale, clientVersion } = m;
  if (v !== PORT_PROTOCOL_VERSION || !isWsUrl(wsUrl) || !oneOf(SHELLS, shell)) return undefined;
  if (!isText(locale, 16) || !isText(clientVersion, 32)) return undefined; // `hello`'s own limits (13.2)
  return { t: "connect", v, wsUrl, shell, locale, clientVersion };
}

function parseConsume(m: Rec): ConsumeMessage | undefined {
  const { id, ch, rs, opts, pane, priority } = m;
  if (!isText(id, MAX_ID) || !isTopic(ch) || !isText(pane, MAX_ID)) return undefined;
  if (!oneOf(PRIORITIES, priority) || (rs !== undefined && !isUuid(rs))) return undefined;
  const copy = opts === undefined ? undefined : jsonCopy(opts, MAX_OPTS_JSON);
  if (opts !== undefined && copy === undefined) return undefined;
  return {
    t: "consume",
    id,
    ch,
    pane,
    priority,
    ...(rs !== undefined && { rs }),
    // cast: the server checks every option and refuses an unknown one (S12), so the values are not
    // checked here, only kept small and plain: a `__proto__` or `constructor` key is data of the copy
    ...(copy !== undefined && { opts: copy as SubOptions }),
  };
}

function parsePane(m: Rec): PaneMessage | undefined {
  const { id, visibility, cssWidth, dpr } = m;
  if (!isText(id, MAX_ID) || !oneOf(VISIBILITIES, visibility)) return undefined;
  if (cssWidth === undefined && dpr === undefined) return { t: "pane", id, visibility };
  if (!isBoundedPositive(cssWidth, MAX_PANE_PX) || !isBoundedPositive(dpr, MAX_DPR))
    return undefined;
  return { t: "pane", id, visibility, cssWidth, dpr };
}

function parseTokenResult(r: unknown): TokenResult | undefined {
  if (!isRec(r)) return undefined;
  const { kind, accessToken, expiresAtMs } = r; // each read once: what is checked is what is returned
  if (kind === "locked" || kind === "unavailable") return { kind };
  // `auth` takes 20 to 4 096 characters (13.4): the connection checks the least, and the port the most it takes
  if (kind !== "ok" || !isText(accessToken, MAX_TOKEN_LENGTH)) return undefined;
  if (typeof expiresAtMs !== "number" || !Number.isFinite(expiresAtMs)) return undefined;
  return { kind, accessToken, expiresAtMs };
}

/**
 * `undefined` for anything that is not exactly one message of the protocol; the result holds the fields
 * checked and no others. Each field is read once, so what was checked is what is returned.
 */
export function parseClientMessage(data: unknown): ClientMessage | undefined {
  if (!isRec(data)) return undefined;
  const { t } = data;
  switch (t) {
    case "connect":
      return parseConnect(data);
    case "consume":
      return parseConsume(data);
    case "release":
    case "resync": {
      const { id } = data;
      return isText(id, MAX_ID) ? { t, id } : undefined;
    }
    case "pane":
      return parsePane(data);
    case "focus": {
      const { id } = data;
      return id === null || isText(id, MAX_ID) ? { t, id } : undefined;
    }
    case "visibility": {
      const { hidden } = data;
      return typeof hidden === "boolean" ? { t, hidden } : undefined;
    }
    case "token": {
      const { req, result } = data;
      const checked = parseTokenResult(result);
      return isNat(req) && checked !== undefined ? { t, req, result: checked } : undefined;
    }
    case "stop":
      return { t };
    case "fault": {
      const { command } = data;
      return { t, command };
    }
    default:
      return undefined;
  }
}

/** What the tab makes of a message from the worker: the shape the worker builds, nothing deeper (its own frames are the engine's). */
export function parseWorkerMessage(data: unknown): WorkerMessage | undefined {
  if (!isRec(data)) return undefined;
  switch (data["t"]) {
    case "state": {
      const state = data["state"];
      // cast: `reduce` made it; the tab only refuses what is not a state at all
      return isRec(state) && typeof state["transport"] === "string" && isNat(state["transitionSeq"])
        ? { t: "state", state: state as unknown as WsState }
        : undefined;
    }
    case "data": {
      const { id, frames, status, effective, source } = data;
      const ok =
        isText(id, MAX_ID) &&
        Array.isArray(frames) &&
        oneOf(STATUSES, status) &&
        isRec(effective) &&
        (source === "live" || source === "replay");
      // cast: every frame is the engine's, validated there; `Array.isArray` is all that is checked of the list
      return ok
        ? { t: "data", id, frames: frames as TopicFrame[], status, effective, source }
        : undefined;
    }
    case "system": {
      const update = data["update"];
      // cast: the host posts the engine's own `SystemUpdate`; the tab refuses what is not a record with a kind, and no more
      return isRec(update) && typeof update["kind"] === "string"
        ? { t: "system", update: update as unknown as SystemUpdate }
        : undefined;
    }
    case "tokenRequest": {
      const { req, invalidate } = data;
      return isNat(req) && typeof invalidate === "boolean"
        ? { t: "tokenRequest", req, invalidate }
        : undefined;
    }
    case "diag": {
      const diag = data["diag"];
      // cast: the host builds `WsDiagnostics`; the tab refuses what is not a record holding the two counter records
      return isRec(diag) && isRec(diag["engine"]) && isRec(diag["host"])
        ? { t: "diag", diag: diag as unknown as WsDiagnostics }
        : undefined;
    }
    default:
      return undefined;
  }
}

// Moving frames between threads. A transferred buffer is detached at the sender (ADR-0005: zero-copy) and
// reaches one receiver only, so the first consumer of a frame takes the buffers themselves and every other
// one a copy, made before the first is sent.

const copyBody = (body: DataBody): DataBody =>
  body.e === "b64" ? { e: "b64", bytes: body.bytes.slice(0) } : body;

/** The same frame with buffers of its own. A structured body is data nobody mutates, and a `reset` has none. */
export function copyFrame(frame: TopicFrame): TopicFrame {
  switch (frame.kind) {
    case "snap":
      // cast: `map` keeps the length, which is at least one
      return { ...frame, bodies: frame.bodies.map(copyBody) as [DataBody, ...DataBody[]] };
    case "d":
      return { ...frame, body: copyBody(frame.body) };
    case "reset":
      return frame;
  }
}

/** The buffers `postMessage` is to transfer with `frames`, each once. */
export function transferListOf(frames: readonly TopicFrame[]): ArrayBuffer[] {
  const buffers = new Set<ArrayBuffer>();
  for (const frame of frames) {
    if (frame.kind === "reset") continue;
    for (const body of frame.kind === "snap" ? frame.bodies : [frame.body]) {
      if (body.e === "b64") buffers.add(body.bytes);
    }
  }
  return [...buffers];
}
