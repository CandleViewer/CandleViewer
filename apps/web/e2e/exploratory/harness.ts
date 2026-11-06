import { writeFileSync } from "node:fs";
import { test as base, expect, type Page } from "@playwright/test";
import { guardContextEgress } from "@candleviewer/fixtures/e2e";
import { stubSession, stubSessionsList } from "../support/api";
import { startWsHarness, type WsHarness } from "../support/wsHarness";

// E49-Q02 (#1336) exploratory harness. A session is a scripted exploration, not a regression
// test: it records what it saw in an append-only log and never fails on an observation. It fails
// on one thing only, a request that left the loopback interface (C-13.5, the same egress guard as
// the PR lane). Tier A records video and trace (playwright.explore.config.ts): its pages only ever
// hold stub values. Tier B (`@tier-b` sessions on the seeded stack) records neither.

/** One note in a session log: a step taken, and what an oracle made of it. */
export interface Observation {
  readonly charter: string;
  readonly step: string;
  readonly route: string;
  readonly role: string;
  /** The oracle applied, by its charter id (e.g. `O7.2`), or `none` for a plain step. */
  readonly oracle: string;
  /** `ok`: the oracle held. `suspect`: it did not, or something unexpected showed; triage decides. */
  readonly result: "ok" | "suspect" | "info";
  readonly note: string;
}

export interface SessionLog {
  readonly note: (o: Omit<Observation, "charter">) => void;
  readonly entries: () => readonly Observation[];
}

export type StubRole = "owner" | "manager" | "viewer";

interface Fixtures {
  readonly charter: string;
  readonly log: SessionLog;
  /** The stub session `ws` signs `page` in as: `test.use({ stubRole: "owner" })`. */
  readonly stubRole: StubRole | null;
  /** Opt-in socket stub: a session that names `ws` gets a signed-in `page` with a live gateway. */
  readonly ws: WsHarness;
}

/**
 * Signs `page` in as `role` on stubs and puts the socket stub (`wsHarness.ts`) in front of it, so the
 * shell's connection is live instead of "Reconnecting" (run 1, E49-R1-04), and Security settings has
 * its sessions list. Once per page, before `goto`: the gateway's refresh answer is registered after
 * `stubSession`'s, so it wins, and its longer opaque value is one the socket client accepts.
 */
export async function stubWithGateway(page: Page, role: StubRole): Promise<WsHarness> {
  await stubSession(page, { role });
  await stubSessionsList(page);
  return startWsHarness(page);
}

export const test = base.extend<Fixtures & { egressGuard: void; pageErrors: void }>({
  // A spec sets its charter with `test.use({ charter: "C7" })`.
  charter: ["unset", { option: true }],
  stubRole: [null, { option: true }],
  ws: async ({ page, stubRole }, use) => {
    if (stubRole === null) throw new Error("the ws fixture needs test.use({ stubRole })");
    await use(await stubWithGateway(page, stubRole));
  },
  log: async ({ charter }, use, testInfo) => {
    const entries: Observation[] = [];
    await use({
      note: (o) => entries.push({ charter, ...o }),
      entries: () => entries,
    });
    const path = testInfo.outputPath("session-log.jsonl");
    writeFileSync(path, entries.map((e) => JSON.stringify(e)).join("\n") + "\n");
    await testInfo.attach("session-log", { path, contentType: "application/jsonl" });
  },
  egressGuard: [
    async ({ context }, use) => {
      const guard = await guardContextEgress(context);
      await use();
      expect(guard.hits(), "a request left the loopback interface (C-13.5)").toEqual([]);
    },
    { auto: true },
  ],
  // Every uncaught page error and console error is an observation of its own (oracle O-ALL.1).
  pageErrors: [
    async ({ page, log }, use) => {
      const where = () => new URL(page.url()).pathname;
      page.on("pageerror", (e) =>
        log.note({
          step: "uncaught page error",
          route: where(),
          role: "-",
          oracle: "O-ALL.1",
          result: "suspect",
          note: e.message.slice(0, 200),
        }),
      );
      page.on("console", (m) => {
        if (m.type() === "error")
          log.note({
            step: "console error",
            route: where(),
            role: "-",
            oracle: "O-ALL.1",
            result: "suspect",
            note: m.text().slice(0, 200),
          });
      });
      // The API answers behind a console error: which call, and its status (never a body).
      page.on("response", (r) => {
        const u = new URL(r.url());
        if (u.pathname.startsWith("/api/") && r.status() >= 400)
          log.note({
            step: `api ${r.request().method()} ${u.pathname}`,
            route: where(),
            role: "-",
            oracle: "O-ALL.1",
            result: "info",
            note: `status ${r.status()}`,
          });
      });
      await use();
    },
    { auto: true },
  ],
});
export { expect };

/** The level-1 heading the page settles on, or "" (no fixed sleep: Playwright's own wait). */
export async function heading(page: Page): Promise<string> {
  const h1 = page.getByRole("heading", { level: 1 }).first();
  await h1.waitFor({ timeout: 10_000 }).catch(() => undefined);
  return ((await h1.textContent().catch(() => null)) ?? "").trim();
}

/**
 * What has keyboard focus: a per-page element number (so two controls with one name stay two
 * stops), tag, role, a short name, and whether a focus style shows.
 */
export async function focused(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (el === null || el === document.body) return "body";
    const w = globalThis as unknown as { __cvFocus?: { ids: WeakMap<Element, number>; n: number } };
    w.__cvFocus ??= { ids: new WeakMap(), n: 0 };
    const f = w.__cvFocus;
    let id = f.ids.get(el);
    if (id === undefined) {
      f.n += 1;
      id = f.n;
      f.ids.set(el, id);
    }
    const style = getComputedStyle(el);
    const ring = style.outlineStyle !== "none" || style.boxShadow !== "none";
    const label = el.getAttribute("aria-label") ?? (el.textContent ?? "").trim().slice(0, 40);
    const name = label.replace(/\s+/gu, " ");
    return `#${id} ${el.tagName.toLowerCase()}[${el.getAttribute("role") ?? ""}] "${name}"${ring ? "" : " (no ring)"}`;
  });
}

/** What a Tab sweep saw (the keyboard-only segment, 03 §12). */
export interface TabSweep {
  /** The focused element after each press, as `focused` names it. */
  readonly stops: readonly string[];
  /** Presses until focus came back to the first stop, or null when it never did within `max`. */
  readonly cycle: number | null;
  /** Focus held on one stop for three presses, or a loop that never reaches the first stop. */
  readonly trap: string | null;
  readonly unique: number;
  readonly noRing: readonly string[];
}

/** Where a sweep's notes go: the session log, under the route and role swept. */
export interface SweepAt {
  readonly log: Pick<SessionLog, "note">;
  readonly route: string;
  readonly role: string;
}

/** The shortest period the tail of `stops` repeats with, twice over, or 0. */
function tailLoop(stops: readonly string[]): number {
  for (let p = 1; p * 2 <= stops.length; p += 1) {
    const tail = stops.slice(-p).join("\n");
    if (tail === stops.slice(-2 * p, -p).join("\n")) return p;
  }
  return 0;
}

/**
 * Presses Tab up to `max` times from where focus is, and records the cycle back to the first stop
 * and any trap as `O-KB.1` and `O-KB.2` notes when `at` is given (one shared copy for every run).
 */
export async function tabSweep(page: Page, max: number, at?: SweepAt): Promise<TabSweep> {
  const stops: string[] = [];
  let cycle: number | null = null;
  let held = 0;
  let trap: string | null = null;
  for (let i = 0; i < max; i += 1) {
    await page.keyboard.press("Tab");
    const f = await focused(page);
    held = f === stops.at(-1) ? held + 1 : 0;
    if (held >= 2 && trap === null) trap = `held on ${f} for ${held + 1} presses`;
    stops.push(f);
    if (stops.length > 1 && f === stops[0]) {
      cycle = stops.length - 1;
      break;
    }
  }
  const loop = cycle === null ? tailLoop(stops) : 0;
  if (trap === null && loop > 1) trap = `loop of ${loop} stops without the first`;
  const unique = new Set(stops);
  const sweep: TabSweep = {
    stops,
    cycle,
    trap,
    unique: unique.size,
    noRing: [...unique].filter((f) => f.endsWith("(no ring)")),
  };
  if (at !== undefined) {
    const { log, route, role } = at;
    const order = stops.join(" > ").slice(0, 2000);
    log.note({ step: "focus order", route, role, oracle: "none", result: "info", note: order });
    const kb1 = trap !== null || cycle === null || sweep.unique < 2;
    log.note({
      step: `Tab x${stops.length}`,
      route,
      role,
      oracle: "O-KB.1",
      result: kb1 ? "suspect" : "ok",
      note: `${sweep.unique} stops, cycle ${cycle ?? "none"}, trap ${trap ?? "none"}`,
    });
    const rings = sweep.noRing;
    log.note({
      step: "visible focus at each stop",
      route,
      role,
      oracle: "O-KB.2",
      result: rings.length > 0 ? "suspect" : "ok",
      note: rings.length > 0 ? `no ring: ${rings.slice(0, 3).join(" | ")}` : "all stops ringed",
    });
  }
  return sweep;
}
