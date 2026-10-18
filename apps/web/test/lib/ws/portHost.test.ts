// E17-T04 S5c (ADR-0005, D13; 23 4.1, 4.3; C12): the host of the shared worker, the half that serves tabs, against a
// fake gateway and fake tabs. One engine serves every tab; the connection state and the kill switch reach every tab
// the moment they change; the access token goes from the tab that was asked to the `auth` frame and nowhere else.
import { afterEach, describe, expect, it, vi } from "vitest";
import { isSocketAllowed, MAX_TABS } from "../../../src/lib/ws/worker/portHost";
import { tokenOf } from "./support/connectionHarness";
import { CONNECT, FakeTab, hostHarness } from "./support/hostHarness";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** Two tabs on a connection that is up. */
async function connected() {
  const t = hostHarness();
  const a = t.tab();
  const b = t.tab();
  await t.advance(400);
  return { t, a, b, conn: t.gateway.latest };
}

describe("joining", () => {
  it("the first tab starts the engine and is asked for the token; the tab hears the state it joined at, then the connection", async () => {
    const t = hostHarness();
    const a = t.tab();
    expect(a.of("tokenRequest")).toEqual([{ t: "tokenRequest", req: 1, invalidate: false }]);
    expect(a.last("state").state).toMatchObject({
      transport: "connecting",
      orderEntry: { enabled: false },
    });
    await t.advance(400);
    expect(t.gateway.latest.of("auth")).toHaveLength(1);
    const { state } = a.last("state");
    expect([state.transport, state.orderEntry.enabled, state.diagnostics.connectionId]).toEqual([
      "connected",
      true,
      "ws_1",
    ]);
  });

  it("a second tab shares the socket and is told the state at once", async () => {
    const t = hostHarness();
    const a = t.tab();
    await t.advance(400);
    const b = t.tab();
    expect([t.gateway.conns.length, b.last("state").state.transport]).toEqual([1, "connected"]);
    t.gateway.latest.close(1011);
    expect([a, b].map((tab) => tab.last("state").state.transport)).toEqual([
      "reconnecting",
      "reconnecting",
    ]);
  });

  it("refuses a second connect, a tab that wants another gateway, and a tab over the limit", async () => {
    const t = hostHarness();
    const a = t.tab();
    a.say(CONNECT);
    const other = t.tab(true, { ...CONNECT, wsUrl: "wss://other.test/api/v1/ws" });
    for (let i = 1; i < MAX_TABS; i += 1) t.tab();
    const over = t.tab(); // the 65th
    await t.advance(400);
    expect(t.gateway.conns).toHaveLength(1);
    expect([other.sent, over.sent]).toEqual([[], []]); // told nothing: they never joined
    expect(t.host.counters).toEqual({ tabs: MAX_TABS, rejectedMessages: 3 });
  });

  it("takes nothing but connect from a tab that has not said it, even when the engine is up", async () => {
    const t = hostHarness();
    t.tab();
    const x = new FakeTab(true);
    t.host.attach(x);
    const first = {
      t: "consume",
      id: "k1",
      ch: "book.BTCUSDT.50",
      pane: "p1",
      priority: "focused",
    };
    for (const message of [first, { t: "visibility", hidden: true }, { t: "stop" }]) x.say(message);
    x.say({ t: "tokenRequest" }); // not a message of the protocol
    expect(x.sent).toEqual([]);
    expect(t.host.counters).toEqual({ tabs: 1, rejectedMessages: 4 });
    await t.advance(400);
    expect(t.gateway.conns).toHaveLength(1);
  });

  it("does not serve streams yet: a consume of a tab that has joined is refused (S5d)", async () => {
    const t = hostHarness();
    const a = t.tab();
    a.say({ t: "consume", id: "k1", ch: "book.BTCUSDT.50", pane: "p1", priority: "focused" });
    expect(t.host.counters.rejectedMessages).toBe(1);
  });
});

describe("the gateway a tab names (4.3)", () => {
  const OTHER = { ...CONNECT, wsUrl: "wss://other.test/api/v1/ws" };

  it.each([
    "wss://cv.test/api/v1/ws",
    "ws://127.0.0.1:8000/api/v1/ws",
    "ws://127.9.9.9/api/v1/ws",
    "ws://localhost:8000/api/v1/ws",
    "ws://[::1]:8000/api/v1/ws",
    "ws://127.1/api/v1/ws", // the parser writes it 127.0.0.1
  ])("opens a socket to %s", async (wsUrl) => {
    const t = hostHarness();
    const tab = t.tab(true, { ...CONNECT, wsUrl });
    await t.advance(400);
    expect(t.host.counters).toMatchObject({ tabs: 1, rejectedMessages: 0 });
    expect(t.gateway.conns).toHaveLength(1);
    expect(tab.last("state").state.transport).toBe("connected");
  });

  it.each([
    "ws://cv.test/api/v1/ws",
    "ws://100.64.0.1:8000/api/v1/ws", // a Tailscale address is another machine
    "ws://0.0.0.0:8000/api/v1/ws",
    "ws://localhost.evil.test/api/v1/ws",
    "ws://127.0.0.1.evil.test/api/v1/ws",
    "ws://[::ffff:7f00:1]/api/v1/ws",
  ])(
    "never sends a token in the clear to %s: refused and counted, no socket, no token asked",
    async (wsUrl) => {
      const t = hostHarness();
      const tab = t.tab(true, { ...CONNECT, wsUrl });
      await t.advance(400);
      expect(t.host.counters).toMatchObject({ tabs: 0, rejectedMessages: 1 });
      expect([t.gateway.conns, tab.sent]).toEqual([[], []]);
    },
  );

  it("allows cleartext to this machine and nothing else of what a URL can be", () => {
    expect(isSocketAllowed("ws://localhost/ws")).toBe(true);
    expect(isSocketAllowed("wss://cv.test/ws")).toBe(true);
    expect(isSocketAllowed("wss://localhost/ws")).toBe(true);
    for (const url of [
      "http://localhost/ws",
      "https://cv.test/ws",
      "ftp://127.0.0.1/ws",
      "not a url",
      "",
    ]) {
      expect(isSocketAllowed(url)).toBe(false);
    }
  });

  it("is the one the first connect named, for as long as a tab is there; the next connect after the last left may name another", async () => {
    const t = hostHarness();
    const a = t.tab();
    await t.advance(400);
    const b = t.tab(true, OTHER);
    expect(t.host.counters).toMatchObject({ tabs: 1, rejectedMessages: 1 });
    expect(b.sent).toEqual([]);
    expect(t.gateway.conns.map((conn) => conn.url)).toEqual([CONNECT.wsUrl]);
    a.say({ t: "stop" });
    const c = t.tab(true, OTHER);
    await t.advance(400);
    expect(t.gateway.conns.map((conn) => conn.url)).toEqual([CONNECT.wsUrl, OTHER.wsUrl]);
    expect(t.host.counters).toMatchObject({ tabs: 1, rejectedMessages: 1 });
    expect(c.last("state").state.transport).toBe("connected");
  });
});

describe("the access token (4.3)", () => {
  it("is asked of the tab that is seen, passed to the auth frame, and found nowhere else", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const store = vi.spyOn(Storage.prototype, "setItem");
    const t = hostHarness();
    const hidden = t.tab();
    await t.advance(400); // the first call went to the only tab there was
    hidden.say({ t: "visibility", hidden: true });
    const seen = t.tab();
    t.gateway.latest.close(1011); // the next connection asks again
    await t.advance(1_000);
    expect([hidden.of("tokenRequest").length, seen.of("tokenRequest").length]).toEqual([1, 1]);
    expect(t.gateway.conns).toHaveLength(2);
    const token = tokenOf(1);
    for (const socket of t.gateway.conns) {
      expect(socket.of("auth")).toEqual([expect.objectContaining({ p: { access_token: token } })]);
      expect(socket.url).not.toContain(token);
      expect(JSON.stringify(socket.received.filter((f) => f["t"] !== "auth"))).not.toContain(token);
    }
    for (const tab of [hidden, seen]) expect(JSON.stringify(tab.sent)).not.toContain(token);
    expect(JSON.stringify(spies.flatMap((spy) => spy.mock.calls))).not.toContain(token);
    expect(store).not.toHaveBeenCalled();
  });

  it("is asked of the tab that is seen, not of the last to join when that one is hidden", async () => {
    const t = hostHarness();
    const seen = t.tab();
    await t.advance(400);
    const hidden = t.tab();
    hidden.say({ t: "visibility", hidden: true });
    t.gateway.latest.close(1011);
    await t.advance(1_000);
    expect([seen.of("tokenRequest").length, hidden.of("tokenRequest").length]).toEqual([2, 0]);
  });

  it("is asked for again with invalidate once the server refused it (4401), and only that once", async () => {
    const t = hostHarness({ refuseAuths: 1, tokenTtlMs: 150_000 });
    const a = t.tab();
    await t.advance(3_000);
    expect(a.last("state").state.transport).toBe("connected");
    await t.advance(100_000); // the token is renewed in place, before it expires
    expect(a.of("tokenRequest").map((m) => m.invalidate)).toEqual([false, true, false]);
  });

  it("is taken from the tab that was asked and from no other, and only for a request that is open", async () => {
    const t = hostHarness();
    const a = t.tab(false);
    const b = t.tab(false);
    expect([a.of("tokenRequest").length, b.of("tokenRequest").length]).toEqual([1, 0]);
    const token = { kind: "ok", accessToken: tokenOf(7), expiresAtMs: Date.now() + 60_000 };
    b.say({ t: "token", req: 1, result: token }); // b was not asked
    a.say({ t: "token", req: 99, result: token }); // nothing open under that number
    await t.advance(400);
    expect(t.gateway.conns).toEqual([]);
    a.say({ t: "token", req: 1, result: token });
    await t.advance(400);
    expect(t.gateway.latest.of("auth")).toEqual([
      expect.objectContaining({ p: { access_token: tokenOf(7) } }),
    ]);
    expect(t.host.counters.rejectedMessages).toBe(2);
  });

  it("passes over a tab that did not answer in time: the next call goes to another, and to it again only if there is none", async () => {
    const t = hostHarness();
    const silent = t.tab(false);
    const live = t.tab(true);
    expect([silent.of("tokenRequest").length, live.of("tokenRequest").length]).toEqual([1, 0]);
    await t.advance(12_000); // the call is given up on after 10 s, and the connection asks again
    expect(live.of("tokenRequest")).toHaveLength(1);
    expect(t.gateway.latest.of("auth")).toHaveLength(1);
    const alone = hostHarness();
    const only = alone.tab(false);
    await alone.advance(60_000);
    expect(only.of("tokenRequest").length).toBeGreaterThan(1);
  });

  it("asks a tab that spoke again before one that stayed silent", async () => {
    const t = hostHarness();
    const a = t.tab(false);
    const b = t.tab(false);
    await t.advance(21_000); // a timed out after 10 s and b after 20.5 s: both are passed over now
    expect([a.of("tokenRequest").length, b.of("tokenRequest").length]).toEqual([1, 1]);
    a.say({ t: "visibility", hidden: false }); // a is there
    await t.advance(1_000);
    expect([a.of("tokenRequest").length, b.of("tokenRequest").length]).toEqual([2, 1]);
  });
});

describe("what every tab hears at once", () => {
  it("a kill switch disables order entry in the task its frame arrives in, for every tab, with no REST call", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { a, b, conn } = await connected();
    expect([a, b].map((tab) => tab.last("state").state.orderEntry.enabled)).toEqual([true, true]);
    conn.delta("system", { kind: "kill_switch", kill_switch: { engaged: true, scope: "global" } });
    // no timer has run: the state is posted from inside the frame
    const disabled = { enabled: false, reason: "kill_switch_engaged" };
    expect([a, b].map((tab) => tab.last("state").state.orderEntry)).toEqual([disabled, disabled]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("system updates reach every tab; the latest of each kind is kept for a tab that joins late, until the connection goes", async () => {
    const t = hostHarness();
    const a = t.tab();
    await t.advance(400);
    t.gateway.latest.delta("system", { kind: "notice", message: "one" });
    t.gateway.latest.delta("system", { kind: "notice", message: "two" });
    expect(a.of("system").map((m) => m.update.kind)).toEqual(["health", "notice", "notice"]);
    const late = t.tab();
    expect(late.of("system").map((m) => m.update)).toEqual([
      expect.objectContaining({ kind: "health" }),
      expect.objectContaining({ message: "two" }),
    ]);
    t.gateway.latest.close(1011);
    expect(t.tab().of("system")).toEqual([]);
  });

  it("keeps the latest update of a few kinds, however many the server invents", async () => {
    const t = hostHarness();
    t.tab();
    await t.advance(400);
    for (let i = 0; i < 40; i += 1) t.gateway.latest.delta("system", { kind: `invented_${i}` });
    expect(t.tab().of("system").length).toBeLessThanOrEqual(16);
  });
});

describe("leaving", () => {
  it("the last tab to stop closes the socket and forgets everything; the next one starts afresh", async () => {
    const { t, a, b, conn } = await connected();
    a.say({ t: "stop" });
    expect(conn.closedByClient).toBeUndefined(); // another tab is still here
    b.say({ t: "stop" });
    expect(conn.closedByClient).toEqual({ code: 1000, reason: "client_stop" });
    expect(t.host.counters.rejectedMessages).toBe(0); // a stop of a tab that joined is no refusal
    const c = t.tab();
    expect(c.last("state").state.transport).toBe("connecting"); // not the state of the engine that was
    await t.advance(400);
    expect(t.gateway.conns).toHaveLength(2);
  });

  it("a tab that is gone is let go of when the worker cannot write to it, and the others hear on", async () => {
    const { t, a, b, conn } = await connected();
    a.dead = true;
    conn.close(1011);
    expect(b.last("state").state.transport).toBe("reconnecting");
    expect(t.host.counters.tabs).toBe(1);
    a.dead = false;
    const before = a.sent.length;
    await t.advance(1_000);
    expect(a.sent).toHaveLength(before); // nothing more is posted to it
  });

  it("a tab whose token request cannot be posted is gone, and the connection is told there is no token", async () => {
    const t = hostHarness();
    const a = new FakeTab(true);
    a.dead = true;
    t.host.attach(a);
    a.say(CONNECT); // joins; its first call finds the port dead
    await t.advance(400);
    expect(t.host.counters.tabs).toBe(0);
  });

  it("a tab that leaves before it answered lets the call go: nothing connects without a token", async () => {
    const t = hostHarness();
    const a = t.tab(false);
    expect(a.of("tokenRequest")).toHaveLength(1);
    a.say({ t: "stop" });
    await t.advance(60_000);
    expect(t.gateway.conns).toEqual([]);
    expect(t.host.counters.tabs).toBe(0);
  });

  it("a tab that leaves while it is asked for the token lets the call go: another is asked, not after 10 s", async () => {
    const t = hostHarness();
    const a = t.tab(false);
    const b = t.tab(true);
    a.say({ t: "stop" });
    await t.advance(1_500); // not the 10 s the call would have taken
    expect(b.of("tokenRequest")).toHaveLength(1);
    expect(t.gateway.latest.of("auth")).toHaveLength(1);
  });

  it("dispose lets every tab go and closes the socket", async () => {
    const { t, conn } = await connected();
    t.host.dispose();
    expect(conn.closedByClient).toEqual({ code: 1000, reason: "client_stop" });
    expect(t.host.counters.tabs).toBe(0);
  });
});

describe("a fault (dev only)", () => {
  it("goes to the fault channel if there is one, and is dropped, not refused, if there is not", () => {
    const seen: unknown[] = [];
    const t = hostHarness(undefined, { fault: (command) => seen.push(command) });
    t.tab().say({ t: "fault", command: { kind: "close", code: 1011 } });
    expect(seen).toEqual([{ kind: "close", code: 1011 }]);
    const bare = hostHarness();
    bare.tab().say({ t: "fault", command: { kind: "close" } });
    expect(bare.host.counters.rejectedMessages).toBe(0);
  });
});
