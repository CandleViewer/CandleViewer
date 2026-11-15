// E13-S01 (#423) S4: the settings dialog's test harness: an injected clock, a deferred preview port
// and a store bound to the fake engine with one `server` (EMA) and one `client_worker`
// (Bollinger) instance. No wall time, no network.
import {
  createFakeEngine,
  type FakeEngine,
} from "../../../src/features/indicators/engine/stub/fakeEngine";
import {
  normaliseDescriptor,
  type CatalogueEntry,
} from "../../../src/features/indicators/model/catalogue";
import type { InstanceId } from "../../../src/features/indicators/model/instances";
import type { Params } from "../../../src/features/indicators/model/types";
import type {
  IndicatorPreviewPort,
  SettingsClock,
} from "../../../src/features/indicators/settings/clock";
import {
  createIndicatorStore,
  type IndicatorStore,
} from "../../../src/features/indicators/store/indicatorStore";
import { BOLLINGER, EMA } from "./fixtures";

export interface FakeClock extends SettingsClock {
  now(): number;
  advance(ms: number): void;
  pending(): number;
}

export function fakeClock(): FakeClock {
  let now = 0;
  const timers: { at: number; fn: () => void; live: boolean }[] = [];
  return {
    after(ms, fn) {
      const timer = { at: now + ms, fn, live: true };
      timers.push(timer);
      return () => {
        timer.live = false;
      };
    },
    now: () => now,
    advance(ms) {
      now += ms;
      for (const t of timers) {
        if (t.live && t.at <= now) {
          t.live = false;
          t.fn();
        }
      }
    },
    pending: () => timers.filter((t) => t.live).length,
  };
}

export interface FakePreview extends IndicatorPreviewPort {
  readonly calls: Params[];
  cleared: number;
  /** Settles the oldest pending preview. */
  land(): Promise<void>;
}

export function fakePreview(): FakePreview {
  const pending: (() => void)[] = [];
  const port: FakePreview = {
    calls: [],
    cleared: 0,
    preview(params) {
      port.calls.push(params);
      return new Promise<void>((resolve) => pending.push(resolve));
    },
    clear() {
      port.cleared += 1;
    },
    async land() {
      pending.shift()?.();
      await Promise.resolve();
    },
  };
  return port;
}

export const emaEntry = normaliseDescriptor(EMA) as CatalogueEntry;
export const bollEntry = normaliseDescriptor(BOLLINGER) as CatalogueEntry;

export interface Charted {
  readonly store: IndicatorStore;
  readonly engine: FakeEngine;
  readonly ema: InstanceId;
  readonly boll: InstanceId;
}

/** A chart "c" with EMA 21 (server) and Bollinger 20 2 (client_worker, a registered plugin). */
export function charted(): Charted {
  const store = createIndicatorStore({ report: () => undefined, hasPlugin: () => true });
  const engine = createFakeEngine();
  store.bind("c", engine);
  const add = (entry: CatalogueEntry): InstanceId => {
    const result = store.add("c", { entry, params: {}, target: "overlay", source: "library" });
    if (!result.ok) throw new Error(`add refused: ${result.reason}`);
    return result.id;
  };
  return { store, engine, ema: add(emaEntry), boll: add(bollEntry) };
}
