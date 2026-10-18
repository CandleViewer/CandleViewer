// Shared setup of the engine tests: the fake gateway, scripted tokens, and the sink that every frame
// and every event of the engine leaves through.
import { onTestFinished, vi } from "vitest";
import type { ConsumerSpec, TopicFrame } from "../../../../src/lib/ws/api";
import { createWsEngine, type EngineOptions } from "../../../../src/lib/ws/core/engine";
import type { EngineEvent } from "../../../../src/lib/ws/state/types";
import { assertEngineOrder } from "./engineEvents";
import { fakeTokens, URL } from "./connectionHarness";
import { createFakeGateway, type FakeGatewayOptions, type Json } from "./fakeGateway";

export const BOOK = "book.BTCUSDT.50";
export const RS = "bb000000-0000-4000-8000-000000000001";

export const spec = (ch: string, over: Partial<ConsumerSpec> = {}): ConsumerSpec => ({
  ch,
  paneId: "p1",
  priority: "focused",
  ...over,
});

const summary = (frame: TopicFrame): string =>
  frame.kind === "reset" ? `reset:${frame.reason}` : `${frame.kind}:${frame.seq}`;

export function engineHarness(
  gatewayOptions?: FakeGatewayOptions,
  overrides: Partial<EngineOptions> = {},
) {
  vi.useFakeTimers();
  const gateway = createFakeGateway(gatewayOptions);
  const tokens = fakeTokens();
  const events: EngineEvent[] = [];
  onTestFinished(() => assertEngineOrder(events)); // the order the reducer relies on, in every test
  const delivered = new Map<string, TopicFrame[]>();
  let changes = 0;
  let probe: (() => unknown) | undefined;
  const reads: unknown[] = [];
  const engine = createWsEngine({
    url: URL,
    createSocket: gateway.createSocket,
    tokens,
    sink: {
      event: (event) => void events.push(event),
      deliver: (ch, rs, frame) => {
        const key = `${ch}#${rs ?? "live"}`;
        delivered.set(key, [...(delivered.get(key) ?? []), frame]);
      },
      changed: () => {
        changes += 1;
        if (probe !== undefined) reads.push(probe());
      },
    },
    client: { version: "1.0.0", shell: "browser", locale: "en-GB" },
    random: () => 0.5, // no jitter: a delay is its row of the 9.2 table
    ...overrides,
  });
  /** Moves the fake clock; the microtasks (a socket opening, a token, a flush) run on the way. */
  const advance = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
  /** Starts the engine and runs the handshake and the first round of subscriptions. */
  const start = async () => {
    engine.start();
    await advance(400);
  };
  /** What a stream delivered since the last call, as `snap:100`, `d:101`, `reset:gap`. */
  const got = (ch = BOOK, rs?: string): string[] =>
    (delivered.get(`${ch}#${rs ?? "live"}`)?.splice(0) ?? []).map(summary);
  /** The frames a stream delivered and `got` has not taken yet. */
  const peek = (ch = BOOK, rs?: string): readonly TopicFrame[] =>
    delivered.get(`${ch}#${rs ?? "live"}`) ?? [];
  /** The topics the client subscribed to, in the order its `sub` frames named them. */
  const subscribed = (): string[] =>
    gateway.latest
      .of("sub")
      .flatMap((frame) => ((frame["p"] as Json)["topics"] as { ch: string }[]).map((t) => t.ch));
  return {
    gateway,
    tokens,
    events,
    engine,
    advance,
    start,
    got,
    peek,
    subscribed,
    changes: () => changes,
    /** From now on, what `read` returns each time the sink is told something changed (the state at that moment, not a count). */
    watch: (read: () => unknown): unknown[] => {
      probe = read;
      reads.length = 0;
      return reads;
    },
  };
}
