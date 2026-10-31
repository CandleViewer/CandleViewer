/**
 * E08-S08 (#4702) test support: the CV `ticker` golden (packages/fixtures/golden/ticker, derived from the recorded
 * captures through the shipped mapper, C-13.5), `TopicFrame` builders, and a fake transport that records each
 * batched `ticker` subscription it is asked for. No network: the golden is read from the repository.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { TopicFrame } from "../../../src/lib/ws/api";
import type { TopicStatus } from "../../../src/lib/ws/state/types";
import type {
  TickerChannel,
  TickerTransport,
} from "../../../src/features/watchlist/ticker/tickerHub";
import type { TickerItem } from "../../../src/features/watchlist/ticker/tickerValues";

interface GoldenLine {
  readonly source: string;
  readonly body: { readonly tickers: readonly TickerItem[] };
}

// jsdom's `import.meta.url` is no file URL: the path is taken from the test's own directory.
const GOLDEN = resolve(
  import.meta.dirname,
  "../../../../../packages/fixtures/golden/ticker/ticker_items.jsonl",
);

function readGolden(): readonly GoldenLine[] {
  return readFileSync(GOLDEN, "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line) as GoldenLine);
}

const lines = readGolden();
const itemOf = (line: GoldenLine): TickerItem => {
  const [item] = line.body.tickers;
  if (item === undefined) throw new Error(`golden line of ${line.source} holds no item`);
  return item;
};

/** The recorded stream's BTCUSDT items, one per frame: its snapshot, then its 19 deltas, 100 ms apart. */
export const BTC_STREAM: readonly TickerItem[] = lines
  .filter((line) => line.source.includes("/ws/recorded_tickers_BTCUSDT.jsonl:"))
  .map(itemOf);

/** The item each recorded REST reply maps to, by symbol (BTCUSDT, ETHUSDT, SOLUSDT). */
export const REST_ITEM: Readonly<Record<string, TickerItem>> = Object.fromEntries(
  lines
    .filter((line) => line.source.includes("/rest/recorded_tickers_"))
    .map((line) => {
      const item = itemOf(line);
      return [item.symbol, item];
    }),
);

export function restItem(symbol: string): TickerItem {
  const item = REST_ITEM[symbol];
  if (item === undefined) throw new Error(`no recorded REST ticker for ${symbol}`);
  return item;
}

export function streamItem(index: number): TickerItem {
  const item = BTC_STREAM[index];
  if (item === undefined) throw new Error(`no recorded stream item ${index}`);
  return item;
}

let seq = 0;
const stamped = (size: number) => ({
  seq: (seq += 1),
  ts: Date.now(),
  sp: undefined,
  decodeMs: 0,
  size,
});

/** A `ticker` snapshot holding `items`, as the WS client hands one over. */
export function snapOf(items: readonly TickerItem[]): TopicFrame {
  return {
    kind: "snap",
    ...stamped(64),
    meta: undefined,
    bodies: [{ e: "j", p: { tickers: [...items] } }],
  };
}

/** A `ticker` delta holding `items` (whole items, last write wins, 23 §8.2). */
export function deltaOf(items: readonly TickerItem[]): TopicFrame {
  return {
    kind: "d",
    ...stamped(64),
    meta: undefined,
    body: { e: "j", p: { tickers: [...items] } },
  };
}

/** One subscription the fake transport opened: its symbols and when, what it still holds, and its controls. */
export interface FakeChannel extends TickerChannel {
  readonly symbols: readonly string[];
  readonly openedAt: number;
  released: boolean;
  /** Queues frames for the hub's next read. */
  push(...frames: TopicFrame[]): void;
  /** The server refuses or ends it: a `revoked` reset, and the handle's status. */
  revoke(): void;
}

export class FakeTransport implements TickerTransport {
  readonly opened: FakeChannel[] = [];

  open(symbols: readonly [string, ...string[]]): TickerChannel {
    const queue: TopicFrame[] = [];
    let status: TopicStatus = "pending";
    const channel: FakeChannel = {
      symbols: [...symbols],
      openedAt: Date.now(),
      released: false,
      get status() {
        return status;
      },
      read() {
        return queue.splice(0, queue.length);
      },
      release() {
        channel.released = true;
      },
      push(...frames) {
        for (const frame of frames) {
          if (frame.kind === "snap") status = "live";
          queue.push(frame);
        }
      },
      revoke() {
        status = "revoked";
        queue.push({ kind: "reset", reason: "revoked" });
      },
    };
    this.opened.push(channel);
    return channel;
  }

  /** The subscription the hub holds now (the last opened one, unless released). */
  get current(): FakeChannel | undefined {
    const last = this.opened.at(-1);
    return last === undefined || last.released ? undefined : last;
  }

  /** The draws (`sub`s) that started in the 60 s before and including `at`. */
  drawsWithin(at: number): number {
    return this.opened.filter((c) => c.openedAt > at - 60_000 && c.openedAt <= at).length;
  }
}
