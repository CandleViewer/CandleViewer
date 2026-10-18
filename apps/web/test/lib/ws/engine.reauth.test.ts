// E17-T04 S4 (23 4.1, 4.3): the token is renewed in place, on the same socket.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TokenResult } from "../../../src/lib/ws/api";
import { onWsError } from "../../../src/lib/ws/errorHandler";
import { assertEngineOrder } from "./support/engineEvents";
import { connectionHarness, tokenOf } from "./support/connectionHarness";

afterEach(() => vi.useRealTimers());

/** `auth_ok` arrives 40 ms into the test (hello, then auth 40 ms later), so the token of 600 s is renewed at 540.04 s. */
const RENEWAL = 540_100;

describe("in-place re-auth (4.1)", () => {
  it("Token refresh does not reconnect", async () => {
    const t = connectionHarness();
    await t.connect();
    const seen = t.events.length;
    await t.advance(RENEWAL - 1_100 - 100);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(1); // not before expires_at - 60 s
    await t.advance(1_100);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(2); // one `getToken` at expiry - 60 s
    const conn = t.gateway.latest;
    expect(conn.of("auth")).toHaveLength(2);
    expect(conn.of("auth")[1]).toMatchObject({ p: { access_token: tokenOf(2) } }); // the same socket
    expect(t.gateway.conns).toHaveLength(1);
    expect(
      conn.received.filter((f) => ["sub", "unsub", "resync"].includes(String(f["t"]))),
    ).toEqual([]);
    expect(t.hooks.ready).toHaveBeenCalledTimes(1); // no resubscription
    expect(t.hooks.down).not.toHaveBeenCalled();
    // The reducer promises: a re-auth is not a new socket, and says nothing of one.
    expect(t.events.slice(seen)).toEqual([
      { type: "auth_ok", killSwitch: { engaged: false, scope: "global" } },
    ]);
    assertEngineOrder(t.events);
  });

  it("counts the server's clock, corrected by the skew", async () => {
    const t = connectionHarness({ skewMs: 120_000 }); // the server is two minutes ahead
    await t.connect();
    await t.advance(RENEWAL - 1_100 - 100);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(1);
    await t.advance(1_100);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(2); // 540 s on our clock, not 660 s
  });

  it("takes the skew from the server's clock when welcome leaves it out", async () => {
    const t = connectionHarness({ skewMs: 120_000, omitSkew: true });
    await t.connect();
    await t.advance(RENEWAL - 1_100 - 100);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(1);
    await t.advance(1_100);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(2);
  });

  it("never loops on a token that expires inside the lead time: it renews every 5 s", async () => {
    const t = connectionHarness({ tokenTtlMs: 30_000 });
    await t.connect();
    await t.advance(20_000);
    expect(t.gateway.latest.of("auth")).toHaveLength(5); // the first, and one at 5, 10, 15 and 20 s
  });

  it("does not send a token that arrives after its connection ended, not even on the next one", async () => {
    const t = connectionHarness();
    await t.connect();
    let answer!: (result: TokenResult) => void;
    t.tokens.getToken.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
    await t.advance(RENEWAL - 100); // the renewal asks and waits
    t.gateway.latest.close(1011);
    await t.advance(600); // the next connection is up and authenticated
    answer({ kind: "ok", accessToken: tokenOf(7), expiresAtMs: Date.now() + 1e6 });
    await t.advance(100);
    expect(t.gateway.conns).toHaveLength(2);
    expect(t.gateway.latest.of("auth")).toHaveLength(1); // its own, and not the late one
    expect(JSON.stringify(t.gateway.latest.received)).not.toContain(tokenOf(7));
  });

  it("a token that expires in days is renewed on a timer that cannot overflow", async () => {
    const t = connectionHarness({ tokenTtlMs: 3_000_000_000 }); // past 2^31 ms: such a timer would fire at once
    await t.connect();
    await t.advance(60_000);
    expect(t.gateway.latest.of("auth")).toHaveLength(1);
  });

  it("keeps asking every 5 s while the source is locked, and stops at the expiry", async () => {
    const t = connectionHarness();
    await t.connect();
    t.tokens.queue.push(...Array.from({ length: 100 }, () => ({ kind: "locked" as const })));
    await t.advance(RENEWAL - 100);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(2);
    await t.advance(5_000);
    expect(t.tokens.getToken).toHaveBeenCalledTimes(3);
    expect(t.gateway.latest.of("auth")).toHaveLength(1);
    await t.advance(70_000); // past the expiry at 600 s: the gateway closes 4401 and the reconnect refreshes
    const asked = t.tokens.getToken.mock.calls.length;
    await t.advance(60_000);
    expect(t.tokens.getToken.mock.calls.length).toBe(asked);
  });
});

describe("a refused auth (4.3)", () => {
  it("a refused first auth drops the token and reconnects with a fresh one", async () => {
    const t = connectionHarness({ refuseAuths: 1 });
    const errors: string[] = [];
    const off = onWsError((code) => errors.push(code));
    await t.connect();
    off();
    expect(errors).toEqual(["auth_failed"]); // through the one mapping (10.3)
    expect(t.tokens.invalidate).toHaveBeenCalledTimes(1);
    expect(t.gateway.latest.closedByClient).toEqual({ code: 4401, reason: "auth_refused" });
    expect(t.types().at(-1)).toBe("reconnecting");
    await t.advance(500); // 9.2: the first retry
    expect(t.gateway.conns).toHaveLength(2);
    expect(t.gateway.latest.of("auth")[0]).toMatchObject({ p: { access_token: tokenOf(2) } });
    expect(t.connection.ready).toBe(true);
  });

  it("a refused re-auth keeps the identity, drops the token and asks again in 5 s", async () => {
    const t = connectionHarness();
    await t.connect();
    t.gateway.refuseAuths(1);
    await t.advance(RENEWAL - 100);
    const conn = t.gateway.latest;
    expect(conn.of("auth")).toHaveLength(2);
    expect(t.tokens.invalidate).toHaveBeenCalledTimes(1);
    expect(conn.closedByClient).toBeUndefined(); // the prior identity holds until its token expires
    await t.advance(5_000);
    expect(conn.of("auth")).toHaveLength(3);
    expect(conn.of("auth")[2]).toMatchObject({ p: { access_token: tokenOf(3) } });
    expect(t.gateway.conns).toHaveLength(1);
  });
});

describe("an auth answered with an error, whatever it says of the token (4.3, 8.5)", () => {
  it("token_expired blames the token as auth_failed does", async () => {
    const t = connectionHarness({ refuseAuths: 1, authRefusal: "token_expired" });
    await t.connect();
    expect(t.gateway.latest.closedByClient).toEqual({ code: 4401, reason: "auth_refused" });
    expect(t.tokens.invalidate).toHaveBeenCalledTimes(1);
  });

  it("a first auth the gateway dropped for its rate limit ends the socket but keeps the token", async () => {
    const t = connectionHarness({ refuseAuths: 1, authRefusal: "client_rate_limited" });
    await t.connect();
    expect(t.gateway.latest.closedByClient).toEqual({ code: 4001, reason: "auth_error" });
    expect(t.tokens.invalidate).not.toHaveBeenCalled(); // a good token is not spent on it
    await t.advance(500); // 9.2: the first retry
    expect([t.gateway.conns.length, t.connection.ready]).toEqual([2, true]);
  });

  it("a re-auth the gateway dropped for its rate limit keeps the token and asks again in 5 s", async () => {
    const t = connectionHarness({ authRefusal: "client_rate_limited" });
    await t.connect();
    t.gateway.refuseAuths(1);
    await t.advance(RENEWAL - 100);
    const conn = t.gateway.latest;
    expect(conn.of("auth")).toHaveLength(2);
    expect(t.tokens.invalidate).not.toHaveBeenCalled();
    await t.advance(5_000);
    expect(conn.of("auth")).toHaveLength(3);
    expect(conn.closedByClient).toBeUndefined();
  });
});
