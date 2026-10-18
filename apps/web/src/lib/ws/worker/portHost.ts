// E17-T04 S5c, S5d (ADR-0005, D13; 23 4.1, 4.3, 8.5, 9.3; C8, C9, C12; C-2.18): the host of the shared worker. One engine
// serves every tab of the origin, so one socket does (the gateway allows 8 a user). The host is what the engine's sink
// is. S5c: it reduces the engine's events to the state every tab sees (the kill switch goes out the moment it changes),
// keeps the latest `system` update of each kind for a tab that joins late, and asks a tab for the access token, which it
// holds only for as long as `auth` takes. S5d: it fans each stream's frames out to the tabs that consume it, one queue
// and one copy of the buffers per consumer (a transferred buffer reaches one receiver only), holds a newcomer back
// until its own snapshot, voids a consumer that cannot keep up and asks for a fresh snapshot, and turns what the tabs
// show into the engine's panes (a hidden tab slows its topics, a collapsed pane lets go). Platform-free: the socket
// factory and the timers are injected, and a port is anything that posts and listens.
import type { PaneVisibility, TokenResult, TokenSource, TopicFrame } from "../api";
import { TOKEN_WAIT_MS, type SocketFactory } from "../core/connection";
import { createWsEngine, type EngineSink, type WsEngine } from "../core/engine";
import { RESYNC_WINDOW_MS } from "../core/resyncGuard";
import type { PortLike } from "../port/endpoint";
import { topicKey } from "../core/sequencer";
import type { StreamHandle } from "../core/subscriptions";
import { platformTimers, type Timers } from "../policy/timers";
import {
  createFrameQueue,
  DEFAULT_QUEUE_LIMITS,
  type FrameQueue,
  type QueueLimits,
} from "../port/frameQueue";
import {
  copyFrame,
  parseClientMessage,
  transferListOf,
  type ClientMessage,
  type ConnectMessage,
  type HostCounters,
  type WorkerMessage,
  type WsDiagnostics,
} from "../port/messages";
import type { SystemUpdate } from "../protocol/frames";
import { INITIAL_WS_STATE, reduce } from "../state/reducer";
import type { TopicStatus, WsState } from "../state/types";

export type { PortLike };

export interface PortHostOptions {
  readonly createSocket: SocketFactory;
  readonly timers?: Partial<Timers> | undefined;
  readonly wallClock?: (() => number) | undefined;
  readonly random?: (() => number) | undefined;
  readonly limits?: QueueLimits | undefined;
  /** How long frames are collected into one message; defaults to `FLUSH_MS`. */
  readonly flushMs?: number | undefined;
  /** Dev only: where a `fault` message goes. Without one it is dropped. */
  readonly fault?: ((command: unknown) => void) | undefined;
}

export interface PortHost {
  /** Serves the tab at the other end of `port`. Nothing happens until it says `connect`. */
  attach(port: PortLike): void;
  /** Every tab goes, the engine stops, no timer is left. */
  dispose(): void;
  readonly counters: HostCounters;
}

/**
 * A frame waits at most this long in the worker (06 5.1 caps a stage's batching window at one frame, 16 ms);
 * the tab applies what arrived on its next animation frame. The kill switch and the connection state do not
 * wait: they go out the moment they change.
 */
export const FLUSH_MS = 8;
export const DIAG_INTERVAL_MS = 1_000;
export const MAX_TABS = 64;
export const MAX_CONSUMERS_PER_TAB = 512;
export const MAX_PANES_PER_TAB = 64;
/** How often a tab may void its consumers of one `ch`, together (live and replay), in the window the engine's guard counts snapshots in: it keeps one budget of five for both streams of a `ch`, and a gap needs a share of it too. */
export const MAX_RESYNCS_PER_CH = 3;
/** The latest update of each `system` kind is kept for a tab that joins late; a server that invents kinds gets no more room. */
export const MAX_SYSTEM_KINDS = 16;

/**
 * Whether the worker may open a socket to `wsUrl`: `wss:` to any host, cleartext `ws:` only to this machine,
 * so the access token (sent in `auth` once the socket is up) never crosses a network unencrypted. This machine
 * is `localhost`, 127.0.0.0/8 and `[::1]`; the URL parser has already written any other spelling of them
 * (`127.1`, `[0:0:0:0:0:0:0:1]`) in these forms.
 */
export function isSocketAllowed(wsUrl: string): boolean {
  try {
    const { protocol, hostname } = new URL(wsUrl);
    if (protocol === "wss:") return true;
    const here =
      hostname === "localhost" || hostname === "[::1]" || /^127(\.\d{1,3}){3}$/.test(hostname);
    return protocol === "ws:" && here;
  } catch {
    return false;
  }
}

interface Pane {
  visibility: PaneVisibility;
  size?: { readonly cssWidth: number; readonly dpr: number };
  idle?: boolean; // every consumer that read it has left: it gives way to a new pane at the tab's limit, and not before
}

interface Session {
  readonly id: string;
  readonly port: PortLike;
  hidden: boolean;
  joined: boolean;
  /** It did not answer its last token request in time; any message from it says it is there. */
  silent: boolean;
  readonly panes: Map<string, Pane>;
  readonly consumers: Map<string, Consumer>;
  /** By `ch`: when the tab voided its consumers of it, within the last window, whichever consumers they were and whether they are still there. */
  readonly resyncs: Map<string, number[]>;
}

/** What a tab was last told a consumer reads: a change goes out even when no frame carries it. */
interface Told {
  readonly status: TopicStatus;
  readonly effective: Readonly<Record<string, unknown>>;
  readonly source: "live" | "replay";
}

interface Consumer {
  readonly id: string;
  readonly session: Session;
  readonly ch: string;
  readonly rs: string | undefined;
  readonly pane: string; // the tab's name for the pane it reads in
  readonly handle: StreamHandle;
  readonly queue: FrameQueue;
  /** No baseline of its own yet (a newcomer, or voided): deltas are not for it, a snapshot is. */
  gated: boolean;
  /** Voided because it could not keep up: reads `resyncing` until its snapshot. */
  voided: boolean;
  told: Told | undefined;
}

const sameTold = (a: Told | undefined, b: Told): boolean =>
  a !== undefined && a.status === b.status && a.effective === b.effective && a.source === b.source;

const holdsPane = (session: Session, pane: string): boolean =>
  [...session.consumers.values()].some((consumer) => consumer.pane === pane);

export function createPortHost(options: PortHostOptions): PortHost {
  const timers: Timers = { ...platformTimers, ...options.timers };
  const limits = options.limits ?? DEFAULT_QUEUE_LIMITS;
  const flushMs = options.flushMs ?? FLUSH_MS;
  /** Tabs that said `connect`, oldest first. */
  const sessions = new Set<Session>();
  const byStream = new Map<string, Set<Consumer>>();
  const systemKinds = new Map<string, SystemUpdate>();
  const tokenCalls = new Map<
    number,
    {
      readonly session: Session;
      resolve(result: TokenResult): void;
      readonly timer: unknown;
      /** It carried the order to hand out another token (the server refused the last). */
      readonly invalidate: boolean;
    }
  >();
  const counters = { overflows: 0, rejectedMessages: 0, droppedSystemUpdates: 0 };
  let engine: WsEngine | undefined;
  let engineUrl: string | undefined;
  let state: WsState = INITIAL_WS_STATE;
  let flushTimer: unknown;
  let diagAt = -Infinity;
  let diagJson = "";
  let diagTimer: unknown;
  let tabs = 0;
  let tokenCalled = 0;
  let invalidated = false;
  let focusOwner: Session | undefined;

  const scoped = (session: Session, pane: string): string => `${session.id}:${pane}`;

  /** A port that cannot be written to is a tab that is gone: it is let go of, whatever it held. */
  function post(session: Session, message: WorkerMessage, transfer: ArrayBuffer[] = []): void {
    try {
      session.port.postMessage(message, transfer);
    } catch {
      detach(session);
    }
  }
  const broadcast = (message: WorkerMessage): void => {
    for (const session of [...sessions]) post(session, message);
  };

  // The access token: asked of one tab, handed to the connection, never kept or posted.
  const tokens: TokenSource = {
    getToken: () =>
      new Promise<TokenResult>((resolve) => {
        // One tab is asked: the last one that is seen, else the last to join. A tab that did not answer
        // its last call is passed over (a frozen tab must not keep every call to itself) unless it is the only one.
        const heard = [...sessions].filter((session) => !session.silent);
        let asked: Session | undefined;
        for (const session of heard.length > 0 ? heard : sessions) {
          if (!session.hidden || asked === undefined || asked.hidden) asked = session;
        }
        if (asked === undefined) return resolve({ kind: "unavailable" });
        tokenCalled += 1;
        const req = tokenCalled;
        const session = asked;
        const invalidate = invalidated;
        invalidated = false;
        const timer = timers.setTimeout(() => {
          session.silent = true;
          abandon(req);
        }, TOKEN_WAIT_MS); // the connection has stopped waiting by then, and must be able to ask again
        tokenCalls.set(req, { session, resolve, timer, invalidate });
        post(session, { t: "tokenRequest", req, invalidate });
      }),
    invalidate: () => {
      invalidated = true;
    },
  };
  function settle(req: number, result: TokenResult): void {
    const call = tokenCalls.get(req);
    if (call === undefined) return;
    tokenCalls.delete(req);
    timers.clearTimeout(call.timer);
    call.resolve(result);
  }
  /** The tab asked went silent or left: the call is given up, and the order it carried is the next call's (another tab's). */
  function abandon(req: number): void {
    if (tokenCalls.get(req)?.invalidate === true) invalidated = true;
    settle(req, { kind: "unavailable" });
  }

  const sink: EngineSink = {
    event(event) {
      if (
        event.type === "connecting" ||
        event.type === "reconnecting" ||
        event.type === "offline"
      ) {
        systemKinds.clear(); // what a gone connection said is not what a tab that joins now should read
      }
      const next = reduce(state, event);
      if (next !== state) {
        state = next;
        broadcast({ t: "state", state }); // the kill switch is on its way to every tab before anything else is done
      }
      if (event.type === "system") {
        const { kind } = event.update;
        if (systemKinds.has(kind) || systemKinds.size < MAX_SYSTEM_KINDS)
          systemKinds.set(kind, event.update);
        else counters.droppedSystemUpdates += 1; // every tab hears it now, a tab that joins late does not
        broadcast({ t: "system", update: event.update });
      }
      scheduleFlush(); // the counters moved
    },
    deliver: fanOut,
    changed: scheduleFlush,
  };

  function scheduleFlush(): void {
    flushTimer ??= timers.setTimeout(flush, flushMs);
  }

  /** The frame goes to every consumer of its stream that can take it: the last takes the buffers, the others copies made first. */
  function fanOut(ch: string, rs: string | undefined, frame: TopicFrame): void {
    const takers = [...(byStream.get(topicKey(ch, rs)) ?? [])].filter(
      (consumer) => frame.kind === "snap" || !consumer.gated, // a newcomer holds no state a delta or a reset could change
    );
    const voided: Consumer[] = [];
    for (const [i, consumer] of takers.entries()) {
      if (frame.kind === "snap") consumer.gated = consumer.voided = false;
      const own = i === takers.length - 1 ? frame : copyFrame(frame);
      if (consumer.queue.push(own) === "overflow") {
        overflow(consumer);
        voided.push(consumer);
      }
    }
    // One snapshot is asked for, however many consumers could not keep up, and none while another is owed one (7.5: five a minute)
    if (voided.length > 0 && !awaiting(ch, rs, voided)) engine?.rebaseline(ch, rs);
    if (takers.length > 0) scheduleFlush();
  }

  /** Whether a consumer of the stream but `except` is voided and waits for a snapshot: one is asked for (or deferred by the resync guard), and it is every consumer's. */
  function awaiting(ch: string, rs: string | undefined, except: readonly Consumer[] = []): boolean {
    for (const consumer of byStream.get(topicKey(ch, rs)) ?? [])
      if (consumer.voided && !except.includes(consumer)) return true;
    return false;
  }

  /** It cannot keep up (C-2.18): what it held is gone, it is told so, and it waits for a snapshot. */
  function overflow(consumer: Consumer): void {
    counters.overflows += 1;
    consumer.gated = consumer.voided = true;
    consumer.queue.push({ kind: "reset", reason: "overflow" });
  }

  function toldOf(consumer: Consumer): Told {
    const { handle } = consumer;
    const status =
      handle.status === "revoked"
        ? "revoked"
        : consumer.voided
          ? "resyncing"
          : consumer.gated
            ? "pending"
            : handle.status;
    return { status, effective: handle.effective, source: handle.source };
  }

  function flush(): void {
    flushTimer = undefined;
    for (const session of [...sessions]) {
      for (const consumer of [...session.consumers.values()]) {
        if (!sessions.has(session)) break; // a post failed: the tab is gone
        const frames = consumer.queue.drain();
        const told = toldOf(consumer);
        if (frames.length === 0 && sameTold(consumer.told, told)) continue;
        consumer.told = told;
        post(session, { t: "data", id: consumer.id, frames, ...told }, transferListOf(frames));
      }
    }
    postDiag();
  }

  function counts(): HostCounters {
    let consumers = 0;
    let queuedFrames = 0;
    for (const session of sessions) {
      consumers += session.consumers.size;
      for (const consumer of session.consumers.values()) queuedFrames += consumer.queue.size;
    }
    return { tabs: sessions.size, consumers, queuedFrames, ...counters };
  }

  /** Counters are posted when they moved, at most once a second: a move inside the second is posted when it is over. */
  function postDiag(): void {
    if (engine === undefined) return;
    const diag: WsDiagnostics = {
      engine: engine.counters,
      host: counts(),
      slowConsumerHint: engine.slowConsumerHint,
      clockSkewMs: engine.clockSkewMs,
    };
    const json = JSON.stringify(diag);
    if (json === diagJson) return;
    const wait = diagAt + DIAG_INTERVAL_MS - timers.now();
    if (wait > 0) {
      diagTimer ??= timers.setTimeout(() => {
        diagTimer = undefined;
        postDiag();
      }, wait);
      return;
    }
    diagAt = timers.now();
    diagJson = json;
    broadcast({ t: "diag", diag });
  }

  function applyPane(session: Session, id: string): void {
    const pane = session.panes.get(id);
    if (pane === undefined) return;
    const { visibility, size } = pane;
    engine?.setPane(scoped(session, id), {
      visibility,
      tabHidden: session.hidden,
      ...(size !== undefined && { size }),
    });
  }

  /**
   * A tab holds at most `MAX_PANES_PER_TAB` panes (C-2.18). For a new one, a pane no consumer holds any more gives way,
   * the first created first, and not before: a switch of symbol is a release and a consume, and the tab does not describe the pane again.
   */
  function makeRoomForPane(session: Session, id: string): boolean {
    if (session.panes.has(id) || session.panes.size < MAX_PANES_PER_TAB) return true;
    for (const [name, pane] of session.panes) {
      if (pane.idle !== true) continue;
      session.panes.delete(name);
      engine?.removePane(scoped(session, name));
      return true;
    }
    return false;
  }

  /** Whether the tab may void a consumer of this `ch` now: `MAX_RESYNCS_PER_CH` in the window, for all its consumers of it together, and not only while they are there. */
  function mayVoid({ ch, session: { resyncs } }: Consumer): boolean {
    const at = timers.now();
    for (const [name, stamps] of resyncs) {
      const recent = stamps.filter((stamp) => at - stamp < RESYNC_WINDOW_MS);
      if (recent.length === 0)
        resyncs.delete(name); // none of its votes counts any more: the map holds what does
      else resyncs.set(name, recent);
    }
    const votes = resyncs.get(ch) ?? [];
    if (
      votes.length >= MAX_RESYNCS_PER_CH ||
      (votes.length === 0 && resyncs.size >= MAX_CONSUMERS_PER_TAB)
    )
      return false;
    resyncs.set(ch, [...votes, at]);
    return true;
  }

  function drop(consumer: Consumer): void {
    consumer.handle.release();
    const { session } = consumer;
    session.consumers.delete(consumer.id);
    const key = topicKey(consumer.ch, consumer.rs);
    const group = byStream.get(key);
    group?.delete(consumer);
    if (group?.size === 0) byStream.delete(key);
    const pane = session.panes.get(consumer.pane);
    if (pane !== undefined && !holdsPane(session, consumer.pane)) pane.idle = true;
  }

  function detach(session: Session): void {
    if (!sessions.delete(session)) return;
    session.joined = false;
    for (const consumer of [...session.consumers.values()]) drop(consumer);
    for (const id of session.panes.keys()) engine?.removePane(scoped(session, id));
    session.panes.clear(); // a tab that connects again describes its panes afresh
    for (const [req, call] of tokenCalls) if (call.session === session) abandon(req);
    if (focusOwner === session) {
      focusOwner = undefined;
      engine?.focusPane(null);
    }
    if (sessions.size === 0) teardown();
    else scheduleFlush(); // so the count of tabs is posted
  }

  /** The last tab left: the socket closes, and the next `connect` starts afresh. */
  function teardown(): void {
    engine?.stop();
    engine = engineUrl = undefined;
    state = INITIAL_WS_STATE;
    systemKinds.clear();
    byStream.clear();
    invalidated = false;
    diagAt = -Infinity;
    diagJson = "";
    for (const timer of [flushTimer, diagTimer])
      if (timer !== undefined) timers.clearTimeout(timer);
    flushTimer = diagTimer = undefined;
  }

  function join(session: Session, message: ConnectMessage): boolean {
    if (session.joined || sessions.size >= MAX_TABS) return false;
    if (!isSocketAllowed(message.wsUrl)) return false; // a token in the clear to another machine: refused, and counted
    if (engine !== undefined && engineUrl !== message.wsUrl) return false; // one socket, one gateway, fixed by the first connect: a tab that wants another is refused
    session.joined = true;
    sessions.add(session);
    if (engine === undefined) {
      engineUrl = message.wsUrl;
      engine = createWsEngine({
        url: message.wsUrl,
        createSocket: options.createSocket,
        tokens,
        sink,
        client: { version: message.clientVersion, shell: message.shell, locale: message.locale },
        timers: options.timers,
        wallClock: options.wallClock,
        random: options.random,
      });
      engine.start();
    }
    post(session, { t: "state", state });
    for (const update of systemKinds.values()) post(session, { t: "system", update });
    return true;
  }

  function onMessage(session: Session, data: unknown): void {
    const message = parseClientMessage(data);
    if (message !== undefined) session.silent = false;
    if (message !== undefined && dispatch(session, message)) return;
    counters.rejectedMessages += 1;
    scheduleFlush(); // so the count is posted
  }

  /** `false`: the message made no sense now (not joined, nothing open under that number, not served): it is counted, and changes nothing. */
  function dispatch(session: Session, message: ClientMessage): boolean {
    if (message.t === "connect") return join(session, message);
    if (message.t === "stop") {
      const wasJoined = session.joined;
      detach(session);
      return wasJoined; // a tab that never joined has nothing to leave
    }
    if (!session.joined || engine === undefined) return false;
    switch (message.t) {
      case "consume": {
        if (session.consumers.has(message.id) || session.consumers.size >= MAX_CONSUMERS_PER_TAB)
          return false;
        if (!makeRoomForPane(session, message.pane)) return false;
        const pane = session.panes.get(message.pane);
        if (pane === undefined) {
          session.panes.set(message.pane, { visibility: "visible" }); // a pane that was never described is in view
          applyPane(session, message.pane);
        } else pane.idle = false;
        const handle = engine.consume(
          {
            ch: message.ch,
            paneId: scoped(session, message.pane),
            priority: message.priority,
            ...(message.opts !== undefined && { opts: message.opts }),
          },
          message.rs,
        );
        const consumer: Consumer = {
          id: message.id,
          session,
          ch: message.ch,
          rs: message.rs,
          pane: message.pane,
          handle,
          queue: createFrameQueue(limits),
          gated: true,
          voided: false,
          told: undefined,
        };
        session.consumers.set(message.id, consumer);
        const key = topicKey(message.ch, message.rs);
        byStream.set(key, (byStream.get(key) ?? new Set()).add(consumer));
        scheduleFlush(); // the tab hears what it reads at once, `pending`
        return true;
      }
      case "release":
      case "resync": {
        const consumer = session.consumers.get(message.id);
        if (consumer === undefined) return false;
        if (message.t === "release") {
          drop(consumer);
          return true;
        }
        if (!mayVoid(consumer)) return false; // refused and counted: a tab that voids it over and over is not served
        const owed = awaiting(consumer.ch, consumer.rs); // before this one is voided too
        consumer.gated = consumer.voided = true; // the tab voided it: it waits for a snapshot like a newcomer
        consumer.queue.clear();
        if (!owed) engine.rebaseline(consumer.ch, consumer.rs);
        scheduleFlush();
        return true;
      }
      case "pane": {
        if (!makeRoomForPane(session, message.id)) return false;
        const size =
          message.cssWidth === undefined || message.dpr === undefined
            ? undefined
            : { cssWidth: message.cssWidth, dpr: message.dpr };
        session.panes.set(message.id, {
          visibility: message.visibility,
          ...(size !== undefined && { size }),
          ...(session.panes.get(message.id)?.idle === true && { idle: true }), // said again, still read by none
        });
        applyPane(session, message.id);
        return true;
      }
      case "focus":
        if (message.id !== null) {
          focusOwner = session;
          engine.focusPane(scoped(session, message.id));
        } else if (focusOwner === session) {
          focusOwner = undefined;
          engine.focusPane(null);
        }
        return true;
      case "visibility":
        session.hidden = message.hidden;
        for (const id of session.panes.keys()) applyPane(session, id);
        return true;
      case "token": {
        const call = tokenCalls.get(message.req);
        if (call?.session !== session) return false; // only the tab that was asked can answer
        settle(message.req, message.result);
        return true;
      }
      case "fault":
        options.fault?.(message.command);
        return true;
    }
  }

  return {
    attach(port) {
      tabs += 1;
      const session: Session = {
        id: `t${tabs}`,
        port,
        hidden: false,
        joined: false,
        silent: false,
        panes: new Map(),
        consumers: new Map(),
        resyncs: new Map(),
      };
      port.listen((data) => onMessage(session, data));
    },
    dispose() {
      for (const session of [...sessions]) detach(session);
    },
    get counters() {
      return counts();
    },
  };
}
