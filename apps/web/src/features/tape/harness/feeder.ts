// E22-S01 (#714) BQ-215: the in-page feeder of the dev / Playwright harness. It stands in for the
// WS client's `consume` with a seeded `trades.{symbol}` stream at a fixed rate, shaped as the
// gateway sends it (`23` §6.1, §14.2): a 200-print `snap`, then one structured `d` per 100 ms window
// with that window's prints, oldest first. Its frames go through the panel's real ingest, ring,
// writer and controller; only the socket is absent. Never imported by the app outside the
// flag-gated harness route.
import type { ConsumerSpec, PaneVisibility, TopicFrame, TopicHandle } from "../../../lib/ws/api";
import type { TopicStatus } from "../../../lib/ws/state/types";

/** `23` §6.1: the server's coalescing window. */
export const WINDOW_MS = 100;
/** `23` §6.1: the snapshot is the last 200 prints. */
export const SNAPSHOT_PRINTS = 200;

/** mulberry32: a small seeded PRNG (deterministic runs, C-13.7). */
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

export interface FeederOptions {
  readonly symbol: string;
  /** Prints per second. */
  readonly rate: number;
  readonly seed: number;
  /** Monotonic ms (the panel's clock). */
  readonly now: () => number;
  /** Epoch ms of the first print. */
  readonly startTsMs: number;
  /** Share of prints the "server" flags `is_big_trade` (tier 1). */
  readonly bigShare?: number;
}

export interface Feeder {
  readonly client: {
    consume(spec: ConsumerSpec): TopicHandle;
    setPane(paneId: string, visibility: PaneVisibility): void;
  };
  /** Prints handed to the panel so far. */
  injected(): number;
}

export function createFeeder(options: FeederOptions): Feeder {
  const random = seeded(options.seed);
  const bigShare = options.bigShare ?? 0.002;
  let injected = 0;
  let nextId = 1;
  let price = 65_000;
  let tsMs = options.startTsMs;
  let started: number | null = null;
  let windowsSent = 0;
  let frameSeq = 0;

  const print = () => {
    price = Math.max(1, price + (random() < 0.5 ? -0.5 : 0.5) * Math.floor(random() * 3));
    tsMs += 1;
    injected += 1;
    const size = (0.001 + random() * random() * 4).toFixed(3);
    return {
      id: String(nextId++),
      ts_ms: tsMs,
      price: price.toFixed(1),
      size,
      side: random() < 0.5 ? "buy" : "sell",
      is_big_trade: random() < bigShare,
      cluster_size: 1,
    };
  };
  const batch = (n: number) => ({
    symbol: options.symbol,
    big_trade_threshold: "250000",
    trades: Array.from({ length: n }, print),
  });
  const stamp = () => ({ seq: ++frameSeq, ts: 0, sp: undefined, decodeMs: 0, size: 0 });

  const client = {
    consume(spec: ConsumerSpec): TopicHandle {
      let status: TopicStatus = "pending";
      return {
        ch: spec.ch,
        effective: {},
        source: "live",
        rs: undefined,
        get status() {
          return status;
        },
        read(): readonly TopicFrame[] {
          const now = options.now();
          if (started === null) {
            started = now;
            status = "live";
            return [
              {
                kind: "snap",
                ...stamp(),
                meta: undefined,
                bodies: [{ e: "j", p: batch(SNAPSHOT_PRINTS) }],
              },
            ];
          }
          const due = Math.floor((now - started) / WINDOW_MS);
          const frames: TopicFrame[] = [];
          const perWindow = (options.rate * WINDOW_MS) / 1000;
          while (windowsSent < due) {
            windowsSent += 1;
            // the windows' counts add up to exactly `rate` prints a second
            const n =
              Math.floor(windowsSent * perWindow) - Math.floor((windowsSent - 1) * perWindow);
            frames.push({ kind: "d", ...stamp(), meta: undefined, body: { e: "j", p: batch(n) } });
          }
          return frames;
        },
        release() {
          status = "pending";
        },
      };
    },
    setPane(): void {
      // visibility drives nothing in the harness
    },
  };
  return { client, injected: () => injected };
}
