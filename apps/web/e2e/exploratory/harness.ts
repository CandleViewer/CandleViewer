import { writeFileSync } from "node:fs";
import { test as base, expect, type Page } from "@playwright/test";
import { guardContextEgress } from "@candleviewer/fixtures/e2e";

// E49-Q02 (#1336) exploratory harness. A session is a scripted exploration, not a regression
// test: it records what it saw in an append-only log and never fails on an observation. It fails
// on one thing only, a request that left the loopback interface (C-13.5, the same egress guard as
// the PR lane). Video and trace are always on (playwright.explore.config.ts); the pages only ever
// hold stub values, so no credential can reach them.

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

interface Fixtures {
  readonly charter: string;
  readonly log: SessionLog;
}

export const test = base.extend<Fixtures & { egressGuard: void; pageErrors: void }>({
  // A spec sets its charter with `test.use({ charter: "C7" })`.
  charter: ["unset", { option: true }],
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
