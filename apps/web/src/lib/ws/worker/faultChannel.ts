// E17-T04 S5e (23 4.4, 8.3, 9.4, 9.5; C7, C12; WS-E06): the dev-only fault-injection channel. It wraps the worker's socket
// factory so QA and design QA can force each transport state deterministically: close the connection with a code, drop
// the next delta of a topic (a gap), delay everything the server says, or make the server say something it did not
// (a connection class, a shutdown notice, the kill switch, a revocation, a stale snapshot). What it injects goes through
// the engine like anything from the socket, so what a test or a person sees is what a real fault would show. It is
// loaded only behind `import.meta.env.DEV || __CV_ALLOW_FAULT_INJECTION__` and is absent from the production bundle:
// `faultInjection.bundle.test.ts` builds it and looks for `FAULT_INJECTION_SENTINEL`.
import type { EngineSocket, SocketEvents, SocketFactory } from "../core/connection";
import { isTopic } from "../protocol/codec";

/** In every injected frame and in the reason of a forced close, so a log shows it was not the server. Nothing else may contain it. */
export const FAULT_INJECTION_SENTINEL = "cv-ws-fault-injection";

export type FaultCommand =
  | { readonly kind: "close"; readonly code: number }
  | { readonly kind: "drop"; readonly ch: string }
  | { readonly kind: "delay"; readonly ms: number }
  | {
      readonly kind: "quality";
      readonly class: "healthy" | "lagging" | "saturated" | "overflowing";
    }
  | { readonly kind: "shutdown"; readonly closingInMs: number; readonly downtimeMs: number }
  | { readonly kind: "killSwitch"; readonly engaged: boolean }
  | { readonly kind: "revoke"; readonly ch: string; readonly reason: string }
  | { readonly kind: "staleSnap"; readonly ch: string };

const CLASSES = ["healthy", "lagging", "saturated", "overflowing"] as const;
const MAX_DELAY_MS = 60_000;
const MAX_COUNTDOWN_MS = 3_600_000;
type Rec = Readonly<Record<string, unknown>>;
const isRec = (v: unknown): v is Rec => typeof v === "object" && v !== null && !Array.isArray(v);
const inRange = (v: unknown, min: number, max: number): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= min && v <= max;

/** What the channel makes of a `fault` message: one command of the list, or nothing. */
export function parseFaultCommand(raw: unknown): FaultCommand | undefined {
  if (!isRec(raw)) return undefined;
  switch (raw["kind"]) {
    case "close":
      return inRange(raw["code"], 1000, 4999) ? { kind: "close", code: raw["code"] } : undefined;
    case "drop":
    case "staleSnap":
      return isTopic(raw["ch"]) ? { kind: raw["kind"], ch: raw["ch"] } : undefined;
    case "delay":
      return inRange(raw["ms"], 0, MAX_DELAY_MS) ? { kind: "delay", ms: raw["ms"] } : undefined;
    case "quality": {
      const wanted = CLASSES.find((c) => c === raw["class"]);
      return wanted === undefined ? undefined : { kind: "quality", class: wanted };
    }
    case "shutdown": {
      const { closingInMs, downtimeMs } = raw;
      const ok =
        inRange(closingInMs, 0, MAX_COUNTDOWN_MS) && inRange(downtimeMs, 0, MAX_COUNTDOWN_MS);
      return ok ? { kind: "shutdown", closingInMs, downtimeMs } : undefined;
    }
    case "killSwitch":
      return typeof raw["engaged"] === "boolean"
        ? { kind: "killSwitch", engaged: raw["engaged"] }
        : undefined;
    case "revoke": {
      const { ch, reason } = raw;
      const ok =
        isTopic(ch) && typeof reason === "string" && reason.length > 0 && reason.length <= 64;
      return ok ? { kind: "revoke", ch, reason } : undefined;
    }
    default:
      return undefined;
  }
}

export interface FaultChannel {
  /** The socket factory the engine is to use: the real one, with the channel in between. */
  readonly createSocket: SocketFactory;
  /** One command, as the `fault` message carries it; anything that is not one is ignored. */
  handle(command: unknown): void;
}

/** The socket the engine has now. */
interface Live {
  readonly events: SocketEvents;
  socket: EngineSocket | undefined;
  /** The channel closed it, or the real one did: nothing more is passed on. */
  ended: boolean;
  /** What waits for its delay, in the order the server said it, and when the last of it is due. */
  readonly waiting: unknown[];
  dueAt: number;
  /** Per stream, the number the client last saw and how far injected frames moved the server's numbering, so it never sees a gap it did not cause. */
  readonly seen: Map<string, number>;
  readonly shift: Map<string, number>;
  /** The last structured snapshot body of a stream, which a stale one is made from. */
  readonly bodies: Map<string, Rec>;
}

const streamOf = (frame: Rec): string | undefined => {
  const { ch, rs } = frame;
  return typeof ch === "string" ? `${ch}#${typeof rs === "string" ? rs : "live"}` : undefined;
};

export function installFaultChannel(inner: SocketFactory): FaultChannel {
  let current: Live | undefined;
  let delayMs = 0;
  const drops = new Set<string>();

  /** To the engine, now or after the delay, in the order the server said it: a frame is never due before one that waits, whatever the delay was when it was said. */
  function pass(live: Live, data: unknown): void {
    const now = Date.now();
    live.dueAt = Math.max(now + delayMs, live.dueAt);
    if (live.dueAt <= now && live.waiting.length === 0) return live.events.message(data);
    live.waiting.push(data);
    setTimeout(() => {
      const next = live.waiting.shift();
      if (!live.ended) live.events.message(next);
    }, live.dueAt - now);
  }

  function inbound(live: Live, data: unknown): void {
    if (live.ended) return;
    let frame: unknown;
    try {
      frame = typeof data === "string" ? JSON.parse(data) : undefined;
    } catch {
      frame = undefined; // not JSON: the engine will say so
    }
    const key = isRec(frame) ? streamOf(frame) : undefined;
    if (!isRec(frame) || key === undefined || typeof frame["s"] !== "number")
      return pass(live, data);
    if (frame["t"] === "d" && drops.delete(String(frame["ch"]))) return; // the client never sees it
    const shown = frame["s"] + (live.shift.get(key) ?? 0);
    live.seen.set(key, shown);
    const body = frame["p"];
    if (frame["t"] === "snap") {
      // a binary snapshot's body is text, not a record: there is nothing a stale one could be made of
      if (isRec(body)) live.bodies.set(key, body);
      else live.bodies.delete(key);
    }
    pass(live, shown === frame["s"] ? data : JSON.stringify({ ...frame, s: shown }));
  }

  /** A frame of a stream the server did not send: it takes the next number, and every real frame after it moves up by one. */
  function inject(live: Live, ch: string, frame: Rec): void {
    const key = `${ch}#live`;
    const s = (live.seen.get(key) ?? 0) + 1;
    live.shift.set(key, (live.shift.get(key) ?? 0) + 1);
    live.seen.set(key, s);
    pass(live, JSON.stringify({ ch, s, ts: Date.now(), e: "j", ...frame }));
  }

  const system = (live: Live, p: Rec): void => inject(live, "system", { t: "d", p });

  const createSocket: SocketFactory = (url, protocols, events) => {
    const live: Live = {
      events,
      socket: undefined,
      ended: false,
      waiting: [],
      dueAt: 0,
      seen: new Map(),
      shift: new Map(),
      bodies: new Map(),
    };
    current = live;
    live.socket = inner(url, protocols, {
      open: () => !live.ended && events.open(),
      message: (data) => inbound(live, data),
      close: (code) => {
        if (live.ended) return;
        live.ended = true;
        events.close(code);
      },
    });
    return live.socket;
  };

  function handle(raw: unknown): void {
    const command = parseFaultCommand(raw);
    if (command === undefined) return;
    if (command.kind === "delay") delayMs = command.ms;
    else if (command.kind === "drop") drops.add(command.ch);
    const live = current;
    if (live === undefined || live.ended) return;
    switch (command.kind) {
      case "close":
        live.ended = true;
        try {
          live.socket?.close(1000, FAULT_INJECTION_SENTINEL);
        } catch {
          // already closing
        }
        live.events.close(command.code);
        break;
      case "quality":
        system(live, {
          kind: "connection_quality",
          class: command.class,
          message: FAULT_INJECTION_SENTINEL,
        });
        break;
      case "shutdown":
        system(live, {
          kind: "shutdown_notice",
          reason: FAULT_INJECTION_SENTINEL,
          message: FAULT_INJECTION_SENTINEL,
          closing_in_ms: command.closingInMs,
          expected_downtime_ms: command.downtimeMs,
        });
        break;
      case "killSwitch":
        system(live, {
          kind: "kill_switch",
          kill_switch: {
            engaged: command.engaged,
            scope: "global",
            reason: FAULT_INJECTION_SENTINEL,
          },
        });
        break;
      case "revoke":
        pass(
          live,
          JSON.stringify({
            t: "revoked",
            ch: command.ch,
            p: { reason: command.reason, message: FAULT_INJECTION_SENTINEL },
          }),
        );
        break;
      case "staleSnap": {
        const body = live.bodies.get(`${command.ch}#live`);
        if (body !== undefined) {
          const meta = { reason: FAULT_INJECTION_SENTINEL, source: "live" }; // a reason the client does not know is a routine re-snapshot (7.4)
          inject(live, command.ch, { t: "snap", p: { ...body, stale: true }, meta });
        }
        break;
      }
      default:
        break; // `delay` and `drop` were recorded above
    }
  }

  return { createSocket, handle };
}
