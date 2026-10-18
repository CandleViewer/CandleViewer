// E17-T04 S5f-3 (ADR-0005, D13; C8, C9, C12; WS-I07): the whole path in one thread, over real message ports. The fake gateway is the
// server, the host is the worker's, and each tab is a client at the far end of its own `MessageChannel`, so a transferred buffer
// really is detached at the sender and structured-cloned at the receiver. The timers are real: a message port delivers on the
// event loop, which fake timers do not run.
import { onTestFinished, describe, expect, it, vi } from "vitest";
import { createWsClient } from "../../../src/lib/ws/client/createWsClient";
import { portOf } from "../../../src/lib/ws/port/endpoint";
import type { WorkerMessage } from "../../../src/lib/ws/port/messages";
import type { TopicFrame, TopicHandle } from "../../../src/lib/ws/api";
import { createPortHost } from "../../../src/lib/ws/worker/portHost";
import { tokenOf, URL } from "./support/connectionHarness";
import { b64, bookSnapshot } from "./support/cvwb";
import { BOOK } from "./support/engineHarness";
import { createFakeGateway } from "./support/fakeGateway";
import { fakePage } from "./support/fakePage";

const WAIT = { timeout: 5_000, interval: 10 };

/** The worker's host over the fake gateway, and tabs that reach it through message channels. */
function shim() {
  const gateway = createFakeGateway();
  const host = createPortHost({ createSocket: gateway.createSocket, random: () => 0.5 });
  /** What the host posted to a tab, and the size of each buffer it transferred, as it was once the post returned. */
  const posted: { tab: number; message: WorkerMessage; detached: number[] }[] = [];
  let tabs = 0;
  onTestFinished(() => host.dispose());

  function tab() {
    const index = (tabs += 1);
    const channel = new MessageChannel();
    const hostEnd = portOf(channel.port1);
    host.attach({
      listen: hostEnd.listen,
      postMessage(message, transfer) {
        hostEnd.postMessage(message, transfer);
        posted.push({
          tab: index,
          message: message as WorkerMessage,
          detached: transfer.map((b) => b.byteLength),
        });
      },
    });
    const page = fakePage();
    let issued = 0;
    const client = createWsClient({
      wsUrl: URL,
      tokens: {
        getToken: async () => ({
          kind: "ok",
          accessToken: tokenOf((issued += 1)),
          expiresAtMs: Date.now() + 600_000,
        }),
        invalidate: () => undefined,
      },
      shell: "browser",
      locale: "en-GB",
      clientVersion: "1.0.0",
      port: portOf(channel.port2),
      page: page.page,
    });
    onTestFinished(() => {
      client.stop();
      channel.port1.close();
      channel.port2.close();
    });
    return { client, page };
  }
  return { gateway, tab, posted };
}

const spec = (ch: string) => ({ ch, paneId: "p1", priority: "focused" }) as const;
/** What a handle has had to read since the start, kept as it is read. */
const reader = (handle: TopicHandle) => {
  const seen: TopicFrame[] = [];
  return {
    seen,
    pull: () => {
      seen.push(...handle.read());
      return seen;
    },
  };
};
const bytesOf = (frame: TopicFrame | undefined): number[] => {
  const body = frame?.kind === "snap" ? frame.bodies[0] : undefined;
  return body?.e === "b64" ? [...new Uint8Array(body.bytes)] : [];
};

describe("tabs over message ports", () => {
  it("two tabs share one socket and one subscription, and each gets the frames: the buffer goes to one tab, a copy to the other", async () => {
    const { gateway, tab, posted } = shim();
    const [a, b] = [tab(), tab()];
    const ha = a.client.consume(spec(BOOK));
    const hb = b.client.consume(spec(BOOK));
    const ra = reader(ha);
    const rb = reader(hb);
    await vi.waitFor(() => expect([ra.pull().length, rb.pull().length]).toEqual([1, 1]), WAIT); // the first snapshot
    gateway.latest.snap(BOOK, "client_resync", undefined, { e: "b64", p: b64(bookSnapshot()) });
    gateway.latest.delta(BOOK);
    await vi.waitFor(() => expect([ra.pull().length, rb.pull().length]).toEqual([3, 3]), WAIT);
    expect(gateway.conns).toHaveLength(1); // one socket for two tabs
    expect(gateway.latest.subs().filter((s) => s.ch === BOOK)).toHaveLength(1);
    expect(ra.seen.map((f) => (f.kind === "reset" ? "reset" : `${f.kind}:${f.seq}`))).toEqual([
      "snap:1",
      "snap:2",
      "d:3",
    ]);
    const [ka, kb] = [ra.seen[1], rb.seen[1]];
    expect(bytesOf(ka).length).toBeGreaterThan(0);
    expect(bytesOf(ka)).toEqual(bytesOf(kb)); // the same bytes in both tabs
    const buffers = posted.filter((p) => p.detached.length > 0);
    expect(new Set(buffers.map((p) => p.tab))).toEqual(new Set([1, 2])); // each tab was sent its own
    for (const { detached } of buffers) expect(detached.every((length) => length === 0)).toBe(true); // detached at the sender
    await vi.waitFor(() => expect([ha.status, hb.status]).toEqual(["live", "live"]), WAIT);
  });

  it("Kill-switch disables order entry without a REST call", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    onTestFinished(() => {
      vi.unstubAllGlobals();
    });
    const { gateway, tab, posted } = shim();
    const [a, b] = [tab(), tab()];
    await vi.waitFor(
      () =>
        expect([a, b].map((t) => t.client.getState().transport)).toEqual([
          "connected",
          "connected",
        ]),
      WAIT,
    );
    const heard: boolean[] = [];
    a.client.subscribe(() => heard.push(a.client.getState().orderEntry.enabled));
    expect(a.client.getState().orderEntry.enabled).toBe(true);
    gateway.latest.delta("system", {
      kind: "kill_switch",
      kill_switch: { engaged: true, scope: "global" },
    });
    // in the worker, in the task the frame arrives in: the state is posted to every tab before this line
    const states = posted.filter((p) => p.message.t === "state").slice(-2);
    expect(states.map((p) => p.tab).sort()).toEqual([1, 2]);
    for (const { message } of states) {
      expect(message).toMatchObject({
        state: { orderEntry: { enabled: false, reason: "kill_switch_engaged" } },
      });
    }
    await vi.waitFor(
      () =>
        expect([a, b].map((t) => t.client.getState().orderEntry.enabled)).toEqual([false, false]),
      WAIT,
    );
    expect(heard[0]).toBe(false); // the state was already the new one when the subscriber heard of it
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("a page that is hidden slows its topics: visibilitychange reaches the gateway as a ctl", async () => {
    const { gateway, tab } = shim();
    const a = tab();
    const handle = a.client.consume(spec("trades.BTCUSDT"));
    await vi.waitFor(
      () => expect(gateway.latest.subs().map((s) => s.ch)).toContain("trades.BTCUSDT"),
      WAIT,
    );
    expect(gateway.latest.of("ctl")).toEqual([]);
    a.page.show(true);
    await vi.waitFor(
      () =>
        expect(gateway.latest.of("ctl")).toEqual([
          expect.objectContaining({
            ch: "trades.BTCUSDT",
            p: expect.objectContaining({ throttle_ms: 1_000 }),
          }),
        ]),
      WAIT,
    );
    handle.release();
  });

  it("a page that goes away leaves: the last tab to leave closes the socket", async () => {
    const { gateway, tab } = shim();
    const a = tab();
    await vi.waitFor(() => expect(a.client.getState().transport).toBe("connected"), WAIT);
    a.page.leave();
    await vi.waitFor(() => expect(gateway.latest.closedByClient).toBeDefined(), WAIT);
  });
});
