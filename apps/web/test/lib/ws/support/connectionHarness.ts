// Shared setup of the connection tests: a fake gateway, a scripted token source and the platform
// timers (vitest's fake ones are installed here, so every test starts at the same instant).
import { onTestFinished, vi } from "vitest";
import type { TokenResult } from "../../../../src/lib/ws/api";
import {
  createConnection,
  type ConnectionHooks,
  type ConnectionOptions,
} from "../../../../src/lib/ws/core/connection";
import { platformTimers } from "../../../../src/lib/ws/policy/timers";
import type { Inbound } from "../../../../src/lib/ws/protocol/codec";
import type { EngineEvent } from "../../../../src/lib/ws/state/types";
import { ReachabilityTracker } from "../../../../src/shell/bootstrap/reachability";
import { assertEngineOrder } from "./engineEvents";
import { createFakeGateway, type FakeGatewayOptions } from "./fakeGateway";

export const URL = "wss://cv.test/api/v1/ws";
/** A token of the length `auth` allows (13.4: 20 to 4 096 characters). */
export const tokenOf = (n: number): string => `tok-${n}-${"a".repeat(20)}`;

/** Answers `queue` first, then a fresh token of `ttlMs`. */
export function fakeTokens(ttlMs = 600_000) {
  const queue: TokenResult[] = [];
  let issued = 0;
  return {
    queue,
    getToken: vi.fn(
      async (): Promise<TokenResult> =>
        queue.shift() ?? {
          kind: "ok",
          accessToken: tokenOf((issued += 1)),
          expiresAtMs: Date.now() + ttlMs,
        },
    ),
    invalidate: vi.fn(),
  };
}

export function connectionHarness(
  gatewayOptions?: FakeGatewayOptions,
  overrides: Partial<ConnectionOptions> = {},
) {
  vi.useFakeTimers();
  const gateway = createFakeGateway(gatewayOptions);
  const tokens = fakeTokens();
  const events: EngineEvent[] = [];
  onTestFinished(() => assertEngineOrder(events)); // the order the reducer relies on, in every test
  const frames: Inbound[] = [];
  const hooks = {
    ready: vi.fn(),
    down: vi.fn(),
    frame: vi.fn((frame: Inbound) => void frames.push(frame)),
    malformed: vi.fn(),
  } satisfies ConnectionHooks;
  const connection = createConnection({
    url: URL,
    createSocket: gateway.createSocket,
    tokens,
    client: { version: "1.0.0", shell: "browser", locale: "en-GB" },
    timers: platformTimers,
    wall: () => Date.now(),
    random: () => 0.5, // no jitter: a delay is its row of the 9.2 table
    reachability: new ReachabilityTracker(),
    emit: (event) => void events.push(event),
    hooks,
    ...overrides,
  });
  /** Moves the fake clock; the microtasks (a socket opening, a token) run on the way. */
  const advance = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
  /** Starts the connection and runs the handshake to `ready`: `auth` leaves 40 ms after `hello`. */
  const connect = async () => {
    connection.start();
    await advance(100);
  };
  const types = () => events.map((event) => event.type);
  return { gateway, tokens, events, frames, hooks, connection, advance, connect, types };
}
