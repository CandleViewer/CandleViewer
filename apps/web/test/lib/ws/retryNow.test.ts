// E10-S01 (#304) S10, BQ-07 (b): CMP-077 `Retry now` through the WS client: one handshake now in
// place of the backoff wait, never a loop, never after a 4403 (E17-D02 §6 `session-ended`).
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TokenResult, TokenSource } from "../../../src/lib/ws/api";
import { createWsClient, mayRetry } from "../../../src/lib/ws/client/createWsClient";
import { RETRY_NOW_MIN_INTERVAL_MS } from "../../../src/lib/ws/core/connection";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { WsState } from "../../../src/lib/ws/state/types";
import { connectionHarness } from "./support/connectionHarness";
import { FakePort } from "./support/fakePort";
import { fakePage } from "./support/fakePage";
import { hostHarness } from "./support/hostHarness";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Connection.retryNow", () => {
  it("dials at once in place of the backoff wait, and only once", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.close(1011); // reconnecting, attempt 1, 500 ms away
    await t.advance(100);
    expect(t.gateway.conns).toHaveLength(1);
    expect(t.connection.retryNow()).toBe(true);
    await t.advance(0);
    expect(t.gateway.conns).toHaveLength(2);
    // a second press while that dial is under way is refused, and the cleared wait never fires
    expect(t.connection.retryNow()).toBe(false);
    await t.advance(1_000);
    expect(t.gateway.conns).toHaveLength(2);
    expect(t.connection.ready).toBe(true);
  });

  it("is refused while up", async () => {
    const t = connectionHarness();
    await t.connect();
    expect(t.connection.retryNow()).toBe(false);
    expect(t.gateway.conns).toHaveLength(1);
  });

  it("is refused within the minimum interval of the last one", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.close(1002); // fatal: no wait of its own runs meanwhile
    expect(t.connection.retryNow()).toBe(true);
    await t.advance(100);
    t.gateway.latest.close(1002); // the manual dial ended fatally too
    expect(t.connection.retryNow()).toBe(false);
    await t.advance(RETRY_NOW_MIN_INTERVAL_MS);
    const before = t.gateway.conns.length;
    expect(t.connection.retryNow()).toBe(true);
    await t.advance(0);
    expect(t.gateway.conns).toHaveLength(before + 1);
  });

  it("dials once after a fatal close other than 4403, and stops again if it is fatal again", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.close(1002);
    expect(t.events.at(-1)).toEqual({ type: "offline", cause: "fatal", closeCode: 1002 });
    expect(t.connection.retryNow()).toBe(true);
    await t.advance(100);
    expect(t.gateway.conns).toHaveLength(2);
    t.gateway.latest.close(1002);
    await t.advance(600_000);
    expect(t.gateway.conns).toHaveLength(2); // never a loop
  });

  it("stays offline and schedules nothing when a manual dial after a fatal close finds no token", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.close(1002);
    t.tokens.queue.push({ kind: "unavailable" });
    expect(t.connection.retryNow()).toBe(true);
    await t.advance(600_000);
    expect(t.gateway.conns).toHaveLength(1); // never back on the backoff schedule
    expect(t.events.at(-1)).toEqual({ type: "offline", cause: "fatal", closeCode: 1002 });
  });

  it("is refused after a 4403: the session ended", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.latest.close(4403);
    await t.advance(RETRY_NOW_MIN_INTERVAL_MS);
    expect(t.connection.retryNow()).toBe(false);
    await t.advance(600_000);
    expect(t.gateway.conns).toHaveLength(1);
  });

  it("is refused once stopped", async () => {
    const t = connectionHarness();
    await t.connect();
    t.connection.stop();
    expect(t.connection.retryNow()).toBe(false);
  });
});

describe("the worker's `retry` message", () => {
  it("dials at once, and a refused one is counted, not served", async () => {
    const t = hostHarness();
    const tab = t.tab();
    await t.advance(100);
    t.gateway.latest.close(1011);
    tab.say({ t: "retry" });
    await t.advance(0);
    expect(t.gateway.conns).toHaveLength(2);
    expect(t.host.counters.rejectedMessages).toBe(0);
    tab.say({ t: "retry" }); // a dial is under way
    expect(t.host.counters.rejectedMessages).toBe(1);
  });

  it("is refused after a 4403", async () => {
    const t = hostHarness();
    const tab = t.tab();
    await t.advance(100);
    t.gateway.latest.close(4403);
    await t.advance(RETRY_NOW_MIN_INTERVAL_MS);
    tab.say({ t: "retry" });
    await t.advance(600_000);
    expect(t.gateway.conns).toHaveLength(1);
    expect(t.host.counters.rejectedMessages).toBe(1);
  });
});

const KILL = { engaged: false, scope: "global" } as const;
const UP = reduce(INITIAL_WS_STATE, { type: "auth_ok", killSwitch: KILL });
const down = (event: Parameters<typeof reduce>[1]): WsState => reduce(UP, event);

describe("WsClient.retryNow", () => {
  function rig() {
    vi.useFakeTimers();
    const port = new FakePort();
    const tokens: TokenSource = {
      getToken: vi.fn(async (): Promise<TokenResult> => ({ kind: "unavailable" })),
      invalidate: vi.fn(),
    };
    const client = createWsClient({
      wsUrl: "wss://cv.test/api/v1/ws",
      tokens,
      shell: "browser",
      locale: "en-GB",
      clientVersion: "1.0.0",
      port,
      page: fakePage().page,
    });
    return { client, port };
  }

  it.each<[string, WsState, boolean]>([
    ["up", UP, false],
    ["connecting", down({ type: "connecting" }), false],
    ["reconnecting", down({ type: "reconnecting", attempt: 2, nextAttemptAtMs: 9e12 }), true],
    ["shell-cause offline", down({ type: "offline", cause: "backend_unreachable" }), true],
    ["fatal 1002", down({ type: "offline", cause: "fatal", closeCode: 1002 }), true],
    ["session ended (4403)", down({ type: "offline", cause: "fatal", closeCode: 4403 }), false],
  ])("%s: offered %s", (_name, state, offered) => {
    expect(mayRetry(state)).toBe(offered);
    const { client, port } = rig();
    port.say({ t: "state", state });
    expect(client.retryNow()).toBe(offered);
    expect(port.of("retry")).toHaveLength(offered ? 1 : 0);
  });

  it("posts nothing once stopped", () => {
    const { client, port } = rig();
    port.say({ t: "state", state: down({ type: "reconnecting", attempt: 1, nextAttemptAtMs: 1 }) });
    client.stop();
    expect(client.retryNow()).toBe(false);
    expect(port.of("retry")).toHaveLength(0);
  });
});
