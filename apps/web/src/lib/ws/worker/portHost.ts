// E17-T04 S5c (ADR-0005, D13; 23 4.1, 4.3, C12): the host of the shared worker, the half that serves tabs. One engine
// serves every tab of the origin, so one socket does (the gateway allows 8 a user). The host is what the engine's sink
// is: it reduces the engine's events to the state every tab sees (the kill switch goes out the moment it changes),
// keeps the latest `system` update of each kind for a tab that joins late, and asks a tab for the access token,
// which it holds only for as long as `auth` takes. Streams, panes and diagnostics are S5d's. Platform-free: the socket
// factory and the timers are injected, and a port is anything that posts and listens.
import type { TokenResult, TokenSource } from "../api";
import { TOKEN_WAIT_MS, type SocketFactory } from "../core/connection";
import { createWsEngine, type EngineSink, type WsEngine } from "../core/engine";
import { platformTimers, type Timers } from "../policy/timers";
import {
  parseClientMessage,
  type ClientMessage,
  type ConnectMessage,
  type HostCounters,
  type WorkerMessage,
} from "../port/messages";
import type { SystemUpdate } from "../protocol/frames";
import { INITIAL_WS_STATE, reduce } from "../state/reducer";
import type { WsState } from "../state/types";

/** What the host needs of a tab's end of the port (`MessagePort`, a dedicated worker's scope, a test's fake). */
export interface PortLike {
  postMessage(message: unknown, transfer: ArrayBuffer[]): void;
  /** Starts delivery of the port's messages: `handler` gets each message's data. */
  listen(handler: (data: unknown) => void): void;
}

export interface PortHostOptions {
  readonly createSocket: SocketFactory;
  readonly timers?: Partial<Timers> | undefined;
  readonly wallClock?: (() => number) | undefined;
  readonly random?: (() => number) | undefined;
  /** Dev only: where a `fault` message goes. Without one it is dropped. */
  readonly fault?: ((command: unknown) => void) | undefined;
}

export interface PortHost {
  /** Serves the tab at the other end of `port`. Nothing happens until it says `connect`. */
  attach(port: PortLike): void;
  /** Every tab goes, the engine stops, no timer is left. */
  dispose(): void;
  readonly counters: Pick<HostCounters, "tabs" | "rejectedMessages">;
}

export const MAX_TABS = 64;
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

interface Session {
  readonly id: string;
  readonly port: PortLike;
  hidden: boolean;
  joined: boolean;
  /** It did not answer its last token request in time; any message from it says it is there. */
  silent: boolean;
}

export function createPortHost(options: PortHostOptions): PortHost {
  const timers: Timers = { ...platformTimers, ...options.timers };
  /** Tabs that said `connect`, oldest first. */
  const sessions = new Set<Session>();
  const systemKinds = new Map<string, SystemUpdate>();
  const tokenCalls = new Map<
    number,
    { readonly session: Session; resolve(result: TokenResult): void; readonly timer: unknown }
  >();
  let rejectedMessages = 0;
  let engine: WsEngine | undefined;
  let engineUrl: string | undefined;
  let state: WsState = INITIAL_WS_STATE;
  let tabs = 0;
  let tokenCalled = 0;
  let invalidated = false;

  /** A port that cannot be written to is a tab that is gone: it is let go of, whatever it held. */
  function post(session: Session, message: WorkerMessage): void {
    try {
      session.port.postMessage(message, []);
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
        const timer = timers.setTimeout(() => {
          session.silent = true;
          settle(req, { kind: "unavailable" });
        }, TOKEN_WAIT_MS); // the connection has stopped waiting by then, and must be able to ask again
        tokenCalls.set(req, { session, resolve, timer });
        const invalidate = invalidated;
        invalidated = false;
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
        broadcast({ t: "system", update: event.update });
      }
    },
    deliver: () => undefined, // no tab consumes a stream yet (S5d)
  };

  function detach(session: Session): void {
    if (!sessions.delete(session)) return;
    session.joined = false;
    for (const [req, call] of tokenCalls)
      if (call.session === session) settle(req, { kind: "unavailable" });
    if (sessions.size === 0) teardown();
  }

  /** The last tab left: the socket closes, and the next `connect` starts afresh. */
  function teardown(): void {
    engine?.stop();
    engine = engineUrl = undefined;
    state = INITIAL_WS_STATE;
    systemKinds.clear();
    invalidated = false;
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
    if (message === undefined || !dispatch(session, message)) rejectedMessages += 1;
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
      case "visibility":
        session.hidden = message.hidden;
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
      default:
        return false; // streams and panes: S5d
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
      };
      port.listen((data) => onMessage(session, data));
    },
    dispose() {
      for (const session of [...sessions]) detach(session);
    },
    get counters() {
      return { tabs: sessions.size, rejectedMessages };
    },
  };
}
