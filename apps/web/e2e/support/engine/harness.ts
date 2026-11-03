// E11-Q02 (#444): the page object of the engine harness page. A spec learns about the chart only
// from `window.__engineEvents` (public engine events), and every wait is on an event or a frame:
// no timers (ESLint bans them in this folder and in specs/e11-chart).
import type { Page } from "@playwright/test";
import "../../engine-harness/events"; // types `window.__engineEvents`
import { buildFixture, type FixtureName } from "./fixtures";
import { encodeFrame, encodeHeader } from "./frame";

export interface Viewport {
  readonly timeStart: number;
  readonly timeEnd: number;
  readonly barSpacing: number;
}

/** The gutters the engine reserves (layout-engine.ts): the price axis on the right, the time axis below. */
export const GUTTER = { price: 64, time: 24 } as const;
/** The chart box the harness renders (engine-harness/main.tsx). */
export const CHART_SIZE = { width: 900, height: 520 } as const;
const CHART = '[data-testid="engine-harness-chart"]';

export class EngineHarness {
  constructor(
    readonly page: Page,
    private readonly baseURL: string,
  ) {}

  /** Serves `fixture` from a faked feed (`routeWebSocket`: no socket leaves the page) and waits for it. */
  async open(
    fixture: FixtureName,
    opts: { runMode?: "worker" | "inline"; motion?: "reduce"; panes?: 2 } = {},
  ): Promise<void> {
    const bars = buildFixture(fixture);
    await this.page.routeWebSocket(/\/__engine-feed$/u, (ws) => {
      ws.onMessage(() => {
        ws.send(JSON.stringify(encodeHeader(bars)));
        ws.send(Buffer.from(encodeFrame(bars)));
      });
    });
    const query = `fixture=${fixture}&runMode=${opts.runMode ?? "worker"}${opts.motion ? `&motion=${opts.motion}` : ""}${opts.panes ? `&panes=${opts.panes}` : ""}`;
    await this.page.goto(new URL(`/?${query}`, this.baseURL).href);
    await this.page.waitForFunction(() =>
      window.__engineEvents?.log.some((e) => e.type === "fixtureLoaded"),
    );
  }

  get chart(): ReturnType<Page["locator"]> {
    return this.page.locator(CHART);
  }

  async viewport(): Promise<Viewport> {
    return this.page.evaluate(() => {
      const last = window.__engineEvents?.log.filter((e) => e.type === "viewportChanged").pop();
      if (last === undefined) throw new Error("no viewportChanged recorded");
      return last.payload as Viewport;
    });
  }

  /** Resolves with the first `viewportChanged` recorded after `action` starts (the seq is read before it runs). */
  async viewportAfter(action: () => Promise<void>): Promise<Viewport> {
    const from = await this.page.evaluate(() => window.__engineEvents?.seq ?? 0);
    await action();
    await this.page.waitForFunction(
      (seq) => window.__engineEvents?.log.some((e) => e.seq > seq && e.type === "viewportChanged"),
      from,
    );
    return this.page.evaluate((seq) => {
      const e = window.__engineEvents?.log.find((x) => x.seq > seq && x.type === "viewportChanged");
      return e?.payload as Viewport;
    }, from);
  }

  /** Waits `n` animation frames (the page's own clock: no timer). */
  async frames(n: number): Promise<void> {
    await this.page.evaluate(async (count) => {
      for (let i = 0; i < count; i += 1) await new Promise((r) => requestAnimationFrame(r));
    }, n);
  }

  /** The newest viewport once none has been reported for `quietFrames` frames (momentum has rested). */
  async settle(quietFrames = 20, maxRounds = 200): Promise<Viewport> {
    for (let round = 0; round < maxRounds; round += 1) {
      const seq = await this.page.evaluate(() => window.__engineEvents?.seq ?? 0);
      await this.frames(quietFrames);
      const moved = await this.page.evaluate(
        (from) =>
          window.__engineEvents?.log.some((e) => e.seq > from && e.type === "viewportChanged") ??
          false,
        seq,
      );
      if (!moved) return this.viewport();
    }
    throw new Error(
      `engine harness: viewport still changing after ${maxRounds} quiet-frame rounds`,
    );
  }

  async box(): Promise<{ x: number; y: number; width: number; height: number }> {
    const b = await this.chart.boundingBox();
    if (b === null) throw new Error("engine harness chart is not laid out");
    return b;
  }

  /** How many events of `type` the page has recorded. */
  async count(type: string): Promise<number> {
    return this.page.evaluate(
      (t) => window.__engineEvents?.log.filter((e) => e.type === t).length ?? 0,
      type,
    );
  }

  /** A client-space point `dx`/`dy` in from the top-left of the plot, price gutter or time gutter. */
  async at(
    region: "plot" | "price" | "time",
    dx: number,
    dy: number,
  ): Promise<{ x: number; y: number }> {
    const b = await this.box();
    const left = region === "price" ? CHART_SIZE.width - GUTTER.price : 0;
    const top = region === "time" ? CHART_SIZE.height - GUTTER.time : 0;
    return { x: b.x + left + dx, y: b.y + top + dy };
  }

  /** Focuses the chart without a pointer (`element.focus()`): its Tab stop is E11-S13's, pending. */
  async focusChart(): Promise<void> {
    await this.chart.getByRole("figure", { name: "Engine harness chart" }).focus();
  }
}
