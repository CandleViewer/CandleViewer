// E22-S01 (#714) BQ-216 (RULED): the `Tape/SCR-053` stories, one per state S01 owns (D05 §4.3:
// St01-St12, St14-St16, St21, St22; S13, S17-S20 and S23 are E22-S02/S04/S05's). Each story is a
// state fixture: a fake `trades.BTCUSDT` client and a manual clock drive the real panel (ingest,
// ring, writer, controller) into the state, then stop, so the story is static and deterministic.
// `apps/web` has no Storybook runner yet; `test/features/tape/stories.test.tsx` renders every story
// with Testing Library and axe, so the fixtures are exercised in CI either way.
import { useState, type JSX } from "react";
import type { ConsumerSpec, TopicFrame, TopicHandle } from "../../../lib/ws/api";
import type { TransportState, TopicStatus } from "../../../lib/ws/state/types";
import type { TradesQuery } from "../model/history";
import type { TapeClock } from "../model/tapeFeed";
import { TapePanel } from "./TapePanel";
import type { TapeController } from "./tapeController";

/** Epoch ms of the fixtures' first print: 2026-10-31 14:02:11.000 UTC. */
export const T0 = Date.UTC(2026, 9, 31, 14, 2, 11);
export const FRAME_MS = 20;

export interface FixtureHandle extends TopicHandle {
  queue: TopicFrame[];
  status: TopicStatus;
}

export interface FixtureContext {
  readonly handle: FixtureHandle;
  readonly controller: TapeController;
  /** Runs `n` animation frames of `FRAME_MS`. */
  frames(n?: number): void;
  /** Moves the wall clock (ages) without a frame. */
  advanceWall(ms: number): void;
  /** Queues prints `from..to` as one `d` (or `snap`). */
  push(from: number, to: number, kind?: "d" | "snap", over?: Partial<Print>): void;
  reset(): void;
  /** The grid element. */
  grid(): HTMLElement;
}

export interface Print {
  id: string;
  ts_ms: number;
  price: string;
  size: string;
  side: "buy" | "sell";
  is_big_trade: boolean;
  cluster_size: number;
  is_liquidation: boolean;
}

/** A recorded-shape print (`23` §14.2): every 7th is big, every 11th a liquidation. */
export const print = (n: number, over: Partial<Print> = {}): Print => ({
  id: `p${n}`,
  ts_ms: T0 + n * 5,
  price: (64_000 + (n % 40) / 2).toFixed(1),
  size: (0.01 + (n % 13) * 0.37).toFixed(2),
  side: n % 3 === 0 ? "sell" : "buy",
  is_big_trade: n % 7 === 0,
  cluster_size: 1,
  is_liquidation: n % 11 === 0,
  ...over,
});

export interface Fixture {
  readonly transport?: TransportState;
  readonly viewAs?: { readonly user: string };
  readonly capacity?: number;
  /** REST `/market/trades` pages, by call. */
  readonly pages?: (query: TradesQuery) => readonly unknown[];
  readonly run: (ctx: FixtureContext) => void;
}

const restPrint = (n: number) => ({
  id: `r${n}`,
  ts: new Date(T0 + n * 5).toISOString(),
  price: (64_000 + (n % 40) / 2).toFixed(1),
  size: "0.25",
  side: n % 2 === 0 ? "buy" : "sell",
  is_big_trade: false,
  is_block_trade: false,
  is_liquidation: false,
  cluster_size: 1,
});

const streaming = (ctx: FixtureContext, from = 1, to = 200): void => {
  ctx.handle.status = "live";
  ctx.push(from, to, "snap");
  ctx.frames(1);
  // 40 prints a frame for 30 frames: a steady 2 000 prints/s
  for (let k = 0; k < 30; k += 1) {
    ctx.push(to + 1 + k * 40, to + 40 + k * 40);
    ctx.frames(1);
  }
};

/** The fixtures by D02 state id. */
export const FIXTURES: Readonly<Record<string, Fixture>> = {
  S1: { run: (ctx) => streaming(ctx) },
  S2: {
    run: (ctx) => {
      streaming(ctx);
      ctx.controller.pointerEnter();
      ctx.frames(10); // 200 ms at rest
      ctx.controller.pointerMove();
      ctx.push(1_401, 1_812);
      ctx.frames(30);
    },
  },
  S3: {
    run: (ctx) => {
      streaming(ctx);
      ctx.grid().scrollTop = 72;
      ctx.controller.scrolled(72);
      ctx.push(1_401, 1_812);
      ctx.frames(30);
    },
  },
  S4: {
    run: (ctx) => {
      streaming(ctx);
      ctx.controller.togglePause("button");
      ctx.push(1_401, 1_812);
      ctx.frames(30);
    },
  },
  S5: {
    run: (ctx) => {
      streaming(ctx);
      ctx.controller.togglePause("button");
      ctx.push(1_401, 1_812);
      ctx.frames(2);
      ctx.controller.togglePause("button");
      ctx.frames(30);
    },
  },
  S6: {
    run: (ctx) => {
      streaming(ctx);
      const cell = ctx.grid().querySelector('[role="row"][aria-rowindex="6"] [role="gridcell"]');
      if (cell !== null) ctx.controller.clickRow(cell);
      ctx.frames(30);
    },
  },
  S7: { transport: "degraded:saturated", run: (ctx) => streaming(ctx) },
  S8: {
    run: (ctx) => {
      streaming(ctx);
      ctx.handle.status = "stale";
      ctx.advanceWall(12_000);
      ctx.frames(30);
    },
  },
  S9: {
    run: (ctx) => {
      streaming(ctx);
      ctx.handle.status = "stale";
      ctx.advanceWall(12_000);
      ctx.frames(30);
      ctx.advanceWall(17_400); // 30.6 s since the last print
      ctx.frames(30);
    },
  },
  S10: {
    transport: "offline",
    run: (ctx) => {
      streaming(ctx);
      ctx.advanceWall(12_000);
      ctx.frames(30);
    },
  },
  S11: { run: (ctx) => ctx.frames(3) },
  S12: {
    pages: () => [restPrint(-400)],
    run: (ctx) => {
      ctx.handle.status = "live";
      ctx.handle.queue.push({
        kind: "snap",
        seq: 1,
        ts: 0,
        sp: undefined,
        decodeMs: 0,
        size: 0,
        meta: undefined,
        bodies: [{ e: "j", p: { symbol: "BTCUSDT", big_trade_threshold: "250000", trades: [] } }],
      });
      ctx.frames(3);
    },
  },
  S14: {
    pages: () => [],
    run: (ctx) => {
      ctx.handle.status = "live";
      ctx.push(1, 40, "snap");
      ctx.frames(2);
      ctx.controller.jumpOldest();
      ctx.frames(2);
    },
  },
  S15: {
    run: (ctx) => {
      streaming(ctx, 1, 200);
      ctx.reset();
      ctx.push(1_301, 1_420, "snap"); // the reseed repeats 100 held prints and brings 20 new
      ctx.frames(30);
    },
  },
  S16: {
    pages: () => [restPrint(1_250), restPrint(1_260), restPrint(1_270)],
    run: (ctx) => {
      streaming(ctx, 1, 200);
      ctx.reset();
      ctx.push(1_301, 1_420, "snap");
      ctx.frames(2);
      ctx.controller.loadMissed();
      ctx.frames(2);
    },
  },
  S21: { viewAs: { user: "Dana" }, run: (ctx) => streaming(ctx) },
  S22: {
    capacity: 100,
    run: (ctx) => {
      streaming(ctx, 1, 200);
      ctx.controller.togglePause("button");
      ctx.push(1_401, 3_400);
      ctx.frames(30);
    },
  },
};

function manualClock(): { clock: TapeClock; tick: () => void } {
  const requested = new Map<number, (t: number) => void>();
  let id = 0;
  let now = 0;
  return {
    clock: {
      raf: (callback) => {
        id += 1;
        requested.set(id, callback);
        return id;
      },
      caf: (h) => void requested.delete(h),
      now: () => now,
    },
    tick: () => {
      now += FRAME_MS;
      const callbacks = [...requested.values()];
      requested.clear();
      for (const callback of callbacks) callback(now);
    },
  };
}

export interface TapeStateFixtureProps {
  readonly state: keyof typeof FIXTURES;
  /** Calls to the REST port, for the tests. */
  readonly onFetch?: (query: TradesQuery) => void;
  readonly onLocate?: (request: { symbol: string; tsMs: number; price: number }) => void;
}

/** Renders SCR-053 driven into one D02 state. */
export function TapeStateFixture({ state, onFetch, onLocate }: TapeStateFixtureProps): JSX.Element {
  const fixture = FIXTURES[state] as Fixture;
  const [setup] = useState(() => {
    const { clock, tick } = manualClock();
    let wall = T0 + 2_000;
    let frameSeq = 0;
    const handles: FixtureHandle[] = [];
    const client = {
      consume(spec: ConsumerSpec): TopicHandle {
        const handle: FixtureHandle = {
          ch: spec.ch,
          queue: [],
          status: "pending",
          effective: {},
          source: "live",
          rs: undefined,
          read() {
            const out = handle.queue;
            handle.queue = [];
            return out;
          },
          release() {
            handle.status = "pending";
          },
        };
        handles.push(handle);
        return handle;
      },
      setPane() {
        // no visibility throttling in a fixture
      },
    };
    const frames = (n = 1): void => {
      for (let k = 0; k < n; k += 1) {
        wall += FRAME_MS;
        tick();
      }
    };
    const run = (controller: TapeController, grid: () => HTMLElement): void => {
      const handle = handles[handles.length - 1];
      if (handle === undefined) return;
      fixture.run({
        handle,
        controller,
        frames,
        advanceWall: (ms) => {
          wall += ms;
        },
        push: (from, to, kind = "d", over = {}) => {
          const trades = Array.from({ length: to - from + 1 }, (_, k) => print(from + k, over));
          const p = { symbol: "BTCUSDT", big_trade_threshold: "250000", trades };
          const stamp = { seq: ++frameSeq, ts: 0, sp: undefined, decodeMs: 0, size: 0 };
          handle.queue.push(
            kind === "snap"
              ? { kind: "snap", ...stamp, meta: undefined, bodies: [{ e: "j", p }] }
              : { kind: "d", ...stamp, meta: undefined, body: { e: "j", p } },
          );
        },
        reset: () => handle.queue.push({ kind: "reset", reason: "reconnect" }),
        grid,
      });
    };
    return { clock, client, run, wall: () => wall };
  });
  return (
    <div style={{ width: "400px", height: "736px" }}>
      <TapePanel
        symbol="BTCUSDT"
        enabled
        client={setup.client}
        clock={setup.clock}
        wallNow={setup.wall}
        capacity={fixture.capacity}
        transport={fixture.transport ?? "connected"}
        viewAs={fixture.viewAs ?? null}
        registerKeys={false}
        locate={onLocate}
        fetchTrades={(query) => {
          onFetch?.(query);
          return Promise.resolve(fixture.pages?.(query) ?? []);
        }}
        onController={(controller) => {
          if (controller === null) return;
          setup.run(controller, () => {
            const grid = document.querySelector('[data-testid="tape-grid"]');
            if (!(grid instanceof HTMLElement)) throw new Error("no tape grid");
            return grid;
          });
        }}
      />
    </div>
  );
}

const meta = {
  title: "Tape/SCR-053",
  component: TapeStateFixture,
  parameters: { layout: "fullscreen" },
};
export default meta;

export const St01Streaming = { args: { state: "S1" } };
export const St02SoftPaused = { args: { state: "S2" } };
export const St03ScrollAwayPaused = { args: { state: "S3" } };
export const St04HardPaused = { args: { state: "S4" } };
export const St05Resumed = { args: { state: "S5" } };
export const St06ClickToLocate = { args: { state: "S6" } };
export const St07Delayed = { args: { state: "S7" } };
export const St08StaleT1 = { args: { state: "S8" } };
export const St09StaleT2 = { args: { state: "S9" } };
export const St10Disconnected = { args: { state: "S10" } };
export const St11Loading = { args: { state: "S11" } };
export const St12Empty = { args: { state: "S12" } };
export const St14PartialHistory = { args: { state: "S14" } };
export const St15ReconnectBackfillBefore = { args: { state: "S15" } };
export const St16ReconnectBackfillAfter = { args: { state: "S16" } };
export const St21ViewAsReadOnly = { args: { state: "S21" } };
export const St22PausedBufferFull = { args: { state: "S22" } };
