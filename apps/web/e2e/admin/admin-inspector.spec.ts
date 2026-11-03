import AxeBuilder from "@axe-core/playwright";
import { test, expect, type Page } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { json, stubSession } from "../support/api";
import {
  inspectorReads,
  LATCHED_DETAIL,
  LATCHED_KEY,
  LATCHED_ROW,
  ORDER_HASH,
  STATECHART_LIST,
  STATECHART_PATHS,
  stubAdminReads,
} from "../support/admin";
import { seriousAxe } from "../support/axe";
import { firstPixel, rgbOf } from "../support/pixel";
import { installWsHarness } from "../support/wsHarness";

// E42-S08 (#1137) admin-inspector.spec: the statechart inspector at R-357 /admin/statecharts (BQ-1 as ruled;
// E42-D05 §11), its reads answered at the network layer (no backend, C-13.5). A deployed stack opens no snapshot seal
// yet (#2701), so it lists nothing: AD-S08-01 and AD-S08-04 are proven here, on stubs, over the SC-CHAIN-TRIPS world
// (`e2e/support/admin.ts`). The acknowledge is T2 and sends nothing (BQ-5); the live state is the open machine's topic
// (BQ-7), through the fake gateway. What jsdom cannot see is here: paint order under SCR-159's page, the diagram's
// measured Tab stop, cut cells, and axe in each theme.

// E42-D05's frame: 1280 × 800, where both tables read as tables (cards are 200 %'s, D05 §4.2).
test.use({ viewport: { width: 1280, height: 800 } });

const PAGE = "/admin/statecharts";
const RENDER_MEASURE = "cv_admin_statecharts_render_ms";
const ADMIN_CHUNK = /\/AdminArea-[^/]+\.js$/u;
const ADMIN_API = /^\/api\/v1\/admin(\/|$)/u;

/** The page alone: the shell's announcer, outside it, repeats some of its lines. */
const main = (page: Page) => page.getByRole("main");
const grid = (page: Page) => page.getByRole("grid", { name: "Machines" });
const row = (page: Page, key: string) => grid(page).locator(`tr[data-machine-row="${key}@demo"]`);

/** Every `/api/` call the page makes from now on, as "METHOD /path?query". */
function watchApi(page: Page): string[] {
  const asked: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/"))
      asked.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  return asked;
}

/** The preference the server holds → the root's `data-theme` the theme runtime writes. */
const THEMES = [
  ["dark", { theme: "dark" }],
  ["light", { theme: "light" }],
  ["high-contrast", { theme: "dark", high_contrast: true }],
] as const;
type Appearance = (typeof THEMES)[number][1];

/** The owner on the inspector with its world answered; `replies` replace a path's answer. */
async function openInspector(
  page: Page,
  replies: Readonly<Record<string, { status: number; body: unknown }>> = {},
  appearance?: Appearance,
): Promise<string[]> {
  const asked = watchApi(page);
  await stubSession(page, { role: "owner" });
  if (appearance !== undefined) {
    await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({ appearance })));
  }
  await stubAdminReads(page, { ...inspectorReads(), ...replies });
  await page.goto(PAGE);
  // The admin area's code loads on demand: its first page can take a while on a busy runner.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Statechart inspector", {
    timeout: 15_000,
  });
  return asked;
}

/** Opens the latched order from its row with the keyboard: the grid's first row, then ↓ and Enter. */
async function openLatched(page: Page): Promise<void> {
  await expect(row(page, LATCHED_KEY)).toBeVisible();
  await row(page, "kill_switch").locator("th").focus(); // a press would open that row's machine
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { level: 2, name: `${LATCHED_KEY} · DEMO` }),
  ).toBeFocused();
}

test("E42-S08 AD-S08-01 a latched machine: its row, the banner, the rowless line, — not received", async ({
  page,
}) => {
  await openInspector(page);
  await expect(page.getByRole("region", { name: "Admin area" })).toHaveText(
    "◆ Admin area · Statechart inspector",
  );
  await expect(row(page, LATCHED_KEY)).toContainText("Latched — chain trips: 2");
  await expect(row(page, LATCHED_KEY)).toContainText(
    `${ORDER_HASH.slice(0, 8)} · matches the lock`,
  );
  await expect(row(page, "kill_switch")).not.toContainText("Latched");
  await expect(
    main(page).getByText(
      "A latched machine refuses order-path commands until its latch is acknowledged.",
    ),
  ).toBeVisible();
  await expect(
    main(page).getByText(
      "position_protection (B8) · DEMO: 1 latched — this kind has no public id yet, so it can't be opened or acknowledged here",
    ),
  ).toBeVisible();
  const counters = page.getByRole("table", { name: "Machines by kind" });
  await expect(counters.getByText("— not received")).toHaveCount(3);
  await expect(
    main(page).getByText("Metrics unavailable — metrics timed out after 300 ms"),
  ).toBeVisible();
  await expect(grid(page).locator("tr[data-machine-row]")).toHaveCount(2); // B8 has no row
  await expect(page.locator('[data-cmp="CMP-049"][data-layout="stacked"]')).toHaveCount(0);
  // One render measure, once the list answered; its budget is E42-Q03's, on its own runner.
  const measured = await page.evaluate(
    (name) => performance.getEntriesByName(name).length,
    RENDER_MEASURE,
  );
  expect(measured).toBe(1);
});

test("E42-S08 Latched only is a switch that reads degraded=true", async ({ page }) => {
  const asked = await openInspector(page);
  await expect(grid(page).locator("tr[data-machine-row]")).toHaveCount(2);
  await page.getByRole("switch", { name: "Latched only" }).click();
  await expect(grid(page).locator("tr[data-machine-row]")).toHaveCount(1);
  await expect(row(page, LATCHED_KEY)).toBeVisible();
  expect(asked).toContain(`GET ${STATECHART_PATHS.latchedOnly}`);
});

test("E42-S08 AD-S08-04 Enter opens the machine: its facts, the chart and its list mark the configuration", async ({
  page,
}) => {
  await openInspector(page);
  await openLatched(page);
  expect(new URL(page.url()).search).toBe(`?machine=${encodeURIComponent(LATCHED_KEY)}&env=demo`);
  const view = page.getByRole("region", { name: `${LATCHED_KEY} · DEMO` });
  await expect(view).toContainText("order (B1)");
  await expect(view).toContainText(`${ORDER_HASH} · matches the lock`);
  // The text list is the normative equivalent (D35, D45): B01's 23 states, the configuration's leaves current.
  const list = view
    .getByRole("heading", { name: "States" })
    .locator("xpath=following-sibling::ul[1]");
  await expect(list.locator("li")).toHaveCount(23);
  const current = await list.locator("li").evaluateAll((items) =>
    items
      .map((item) => {
        const own = item.cloneNode(true) as Element; // the item's own words, without its children
        own.querySelectorAll("ul").forEach((nested) => nested.remove());
        return (own.textContent ?? "").trim();
      })
      .filter((words) => words.includes("(current)")),
  );
  expect(current).toEqual(["triggered (current)", "sl_present (current)"]);
  const drawing = view.getByRole("region", { name: "State diagram: order (B1)" });
  await expect(drawing.locator("rect[data-current]")).toHaveCount(2);
  // The drawing outgrows its region at 1280, so the region, measured as it resizes, is a Tab stop.
  await expect(drawing).toHaveAttribute("tabindex", "0");
  // Back to machines closes the view and gives focus back to the row.
  await view.getByRole("button", { name: "Back to machines" }).click();
  await expect(page).toHaveURL(/\/admin\/statecharts$/u);
  await expect(view).toHaveCount(0);
  await expect
    .poll(() => row(page, LATCHED_KEY).evaluate((tr) => tr.contains(document.activeElement)))
    .toBe(true);
});

test("E42-S08 the acknowledge is T2: its reason shows and a press sends nothing (BQ-5)", async ({
  page,
}) => {
  const asked = await openInspector(page);
  await openLatched(page);
  const ack = page.getByRole("button", { name: /Acknowledge latch/u });
  await expect(ack).toHaveAttribute("aria-disabled", "true");
  await expect(ack).toHaveAccessibleDescription("Acknowledging isn't built yet.");
  const before = asked.length;
  await ack.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Space");
  await expect(ack).toBeFocused();
  // Nothing is sent: no write after the presses, and none to the admin area at all.
  expect(asked.slice(before).filter((call) => !call.startsWith("GET "))).toEqual([]);
  expect(
    asked.filter((call) => !call.startsWith("GET ") && call.includes("/api/v1/admin")),
  ).toEqual([]);
});

test("E42-S08 the timeline: three events, newest first, the fault in words", async ({ page }) => {
  await openInspector(page);
  await openLatched(page);
  const timeline = page.getByRole("table", { name: "Events, newest first" });
  const rows = timeline.locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("PRICE_TRIGGERED");
  await expect(rows.nth(1)).toContainText("FILL");
  await expect(rows.nth(1)).toContainText("faulted");
  await expect(rows.nth(2)).toContainText("SUBMITTED");
  // Every cell whole at 1280: the narrow columns have widths, and "From → to" wraps (A-1137-08).
  const cut = await timeline
    .locator(".cv-table__text")
    .evaluateAll((cells) =>
      cells.filter((cell) => cell.scrollWidth > cell.clientWidth + 1).map((c) => c.textContent),
    );
  expect(cut).toEqual([]);
});

/** The world's list with each kind's `by_state` and each row's state as given (live charts' names). */
function namedList(
  kinds: Readonly<Record<string, Readonly<Record<string, number>>>>,
  states: Readonly<Record<string, string>> = {},
) {
  // `Page`'s `items` widens the generated element type to `unknown`; these are its machines.
  const items: readonly generated.rest.components["schemas"]["StatechartMachine"][] =
    STATECHART_LIST.items;
  return {
    ...STATECHART_LIST,
    items: items.map((m) => ({ ...m, state: states[m.machine_kind] ?? m.state })),
    kinds: STATECHART_LIST.kinds.map((k) => {
      const byState = kinds[k.machine_kind];
      if (byState === undefined) return k;
      const machines = Object.values(byState).reduce((sum, n) => sum + n, 0);
      return { ...k, machines, by_state: byState };
    }),
  };
}

test("E42-S08 long served state names wrap at 1280: no counters cell cut, no grid cell overrun (A-1137-d02)", async ({
  page,
}) => {
  // The kill switch's own `engaged_incomplete`, and an order kind in three states.
  const list = namedList(
    {
      kill_switch: { engaged_incomplete: 1 },
      order: { triggered: 1, partially_filled: 3, cancel_pending: 2 },
    },
    { kill_switch: "engaged_incomplete" },
  );
  await openInspector(page, { [STATECHART_PATHS.list]: { status: 200, body: list } });
  await expect(row(page, "kill_switch")).toContainText("engaged_incomplete");
  const counters = page.getByRole("table", { name: "Machines by kind" });
  await expect(
    counters.getByText("triggered 1 · partially_filled 3 · cancel_pending 2"),
  ).toBeVisible();
  await expect(page.locator('[data-cmp="CMP-049"][data-layout="stacked"]')).toHaveCount(0);
  const cut = await counters
    .locator(".cv-table__text")
    .evaluateAll((cells) =>
      cells.filter((cell) => cell.scrollWidth > cell.clientWidth + 1).map((c) => c.textContent),
    );
  expect(cut).toEqual([]);
  // No cell's text runs past its own box into the next one.
  const overrun = await grid(page)
    .locator("tr[data-machine-row] > *")
    .evaluateAll((cells) =>
      cells
        .filter((cell) => {
          const text = document.createRange();
          text.selectNodeContents(cell);
          return text.getBoundingClientRect().right > cell.getBoundingClientRect().right + 1;
        })
        .map((cell) => cell.textContent),
    );
  expect(overrun).toEqual([]);
});

test("E42-S08 a 120-character served state at 320 px never widens the canvas (A-1137-d07)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 800 }); // 400 % of E42-D05's 1280 frame
  const long = "waiting_for_the_exchange_".repeat(5).slice(0, 120);
  const list = namedList({ order: { [long]: 1 } });
  await openInspector(page, { [STATECHART_PATHS.list]: { status: 200, body: list } });
  const counters = page.getByRole("table", { name: "Machines by kind" });
  await expect(counters.getByText(`${long} 1`)).toBeAttached();
  await expect(page.locator('[data-cmp="CMP-049"][data-layout="stacked"]')).toHaveCount(2);
  const canvas = page.locator("[data-shell-canvas]");
  const { scroll, client } = await canvas.evaluate((el) => ({
    scroll: el.scrollWidth,
    client: el.clientWidth,
  }));
  expect(scroll).toBeLessThanOrEqual(client);
});

test("E42-S08 unreadable snapshots, today's deployed state, read machine.unreadable with no rows", async ({
  page,
}) => {
  const unreadable = {
    ...STATECHART_LIST,
    items: [],
    kinds: [],
    meta: { next_cursor: null, has_more: false, count: 0 },
    snapshots: { status: "unavailable", detail: "snapshots: no provider wired" },
  };
  await openInspector(page, { [STATECHART_PATHS.list]: { status: 200, body: unreadable } });
  await expect(main(page).getByText("Machine snapshots can't be read right now.")).toBeVisible();
  await expect(page.getByRole("grid")).toHaveCount(0);
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("E42-S08 a manager's /admin/statecharts is the 404: no admin code, no admin request", async ({
  page,
}) => {
  const paths: string[] = [];
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  await stubSession(page, { role: "manager" });
  await page.route(
    (url) => ADMIN_API.test(url.pathname),
    (r) => r.fulfill(json({ items: [] })),
  );
  await page.goto(PAGE);
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  expect(paths).toContain("/api/v1/me"); // positive control: the watcher sees the SPA's reads
  expect(paths.filter((p) => ADMIN_CHUNK.test(p))).toEqual([]);
  expect(paths.filter((p) => ADMIN_API.test(p))).toEqual([]);
});

for (const [name, appearance] of THEMES)
  test(`E42-S08 the list and the open machine have no serious axe violation in ${name}`, async ({
    page,
  }) => {
    test.setTimeout(60_000); // two axe passes over the list and a large open machine
    await openInspector(page, {}, appearance);
    await expect(page.locator("html")).toHaveAttribute("data-theme", name);
    await expect(row(page, LATCHED_KEY)).toBeVisible();
    expect(await seriousAxe(page)).toEqual([]);
    await openLatched(page);
    await expect(page.getByRole("heading", { name: "Transitions" })).toBeVisible();
    expect(await seriousAxe(page)).toEqual([]);
  });

/** Axe's `heading-order` (best practice, moderate: `seriousAxe` drops it), as `id: targets`. */
async function headingOrder(page: Page): Promise<string[]> {
  const res = await new AxeBuilder({ page }).withRules(["heading-order"]).analyze();
  return res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

test("E42-S08 nothing running, or no list served: an h2 under the h1, no axe violation", async ({
  page,
}) => {
  test.setTimeout(60_000); // two page loads and four axe runs
  const empty = {
    ...STATECHART_LIST,
    items: [],
    kinds: [],
    meta: { next_cursor: null, has_more: false, count: 0 },
    metrics: { status: "ok" },
  };
  await openInspector(page, { [STATECHART_PATHS.list]: { status: 200, body: empty } });
  await expect(
    main(page).getByRole("heading", { level: 2, name: "No machine has a saved snapshot yet." }),
  ).toBeVisible();
  expect(await seriousAxe(page)).toEqual([]);
  expect(await headingOrder(page)).toEqual([]);
  // The same page where the list is not served (501): its line is an h2 as well.
  await page.route(
    (url) => url.pathname === "/api/v1/admin/statecharts",
    (r) => r.fulfill(json({ code: "not_implemented" }, 501)),
  );
  await page.reload();
  await expect(
    main(page).getByRole("heading", {
      level: 2,
      name: "The machine list isn't available on this server.",
    }),
  ).toBeVisible();
  expect(await seriousAxe(page)).toEqual([]);
  expect(await headingOrder(page)).toEqual([]);
});

/** Two colours alike within the screenshot's rounding. */
const alike = (a: readonly number[], b: readonly number[]): boolean =>
  a.length === b.length && a.every((v, i) => Math.abs(v - (b[i] ?? Number.NaN)) <= 2);

test("E42-S08 SCR-159's offline page covers the tables' sticky headers (A-1137-01)", async ({
  page,
}) => {
  test.setTimeout(60_000); // the liveness probe's failure is confirmed before the page shows
  await openInspector(page);
  await expect(grid(page).locator("tr[data-machine-row]")).toHaveCount(2);
  const header = page.locator(".cv-table__header").first();
  const box = await header.boundingBox();
  if (box === null) throw new Error("no table header on screen");
  // Its end, clear of its start-aligned label, half way down.
  const x = Math.round(box.x + box.width - 6);
  const clip = { x, y: Math.round(box.y + box.height / 2), width: 1, height: 1 };
  // The control: with nothing over it, the sample is the header's own surface.hover.
  const own = rgbOf(await header.evaluate((node) => getComputedStyle(node).backgroundColor));
  expect(alike(firstPixel(await page.screenshot({ clip })), own)).toBe(true);
  // The backend stops answering its liveness probe: SCR-159's page takes the canvas.
  await page.route(
    (url) => url.pathname === "/api/v1/health/live",
    (r) => r.abort("connectionrefused"),
  );
  const offline = page.getByRole("heading", { level: 1, name: "Not connected to the tailnet" });
  await expect(offline).toBeVisible({ timeout: 15_000 });
  // `elementFromPoint` answers nothing under an inert canvas, so the pixel is read. The page's
  // words are hidden for it, its ground kept: what shows is surface.app, or what paints over it.
  const pane = page.locator('main > [data-shell-slot="canvas-overlay"] > *').first();
  const { ground, app } = await pane.evaluate((node) => {
    for (const child of node.children) {
      if (child instanceof HTMLElement) child.style.visibility = "hidden";
    }
    const token = document.createElement("div");
    token.style.background = "var(--color-surface-app)";
    document.body.append(token);
    const colours = {
      ground: getComputedStyle(node).backgroundColor,
      app: getComputedStyle(token).backgroundColor,
    };
    token.remove();
    return colours;
  });
  expect(ground).toBe(app); // the page's ground is surface.app
  expect(alike(own, rgbOf(app))).toBe(false); // the grounds differ: the sample tells them apart
  const seen = firstPixel(await page.screenshot({ clip }));
  expect(alike(seen, rgbOf(app)), `${seen.join(",")} under the header, surface.app ${app}`).toBe(
    true,
  );
});

test("E42-S08 the latch seen live: a line with Re-read and one assertive announcement (BQ-7)", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  const harness = await installWsHarness(page);
  // The saved snapshot shows the latch clear; the topic then publishes it set.
  const clear = { ...LATCHED_ROW, degraded: false, chain_trips: 0 };
  await stubAdminReads(page, {
    ...inspectorReads(),
    [STATECHART_PATHS.detail]: { status: 200, body: { ...LATCHED_DETAIL, machine: clear } },
  });
  await page.goto(PAGE);
  await openLatched(page);
  const ch = `machines.${LATCHED_KEY}.state`;
  await expect
    .poll(() =>
      harness.frames.some(({ frame }) => frame.t === "sub" && JSON.stringify(frame).includes(ch)),
    )
    .toBe(true);
  // 23 §15.10's payload, typed by the generated schema: the fake gateway sends nothing the contract refuses.
  const published: generated.ws.MachinesEntityState = {
    machine_kind: "order",
    state: "triggered",
    regions: { lifecycle: "triggered", protection: "sl_present" },
    tags: ["protected"],
    degraded: true,
    machine_hash: ORDER_HASH,
    environment: "demo",
    updated_at_ms: Date.parse("2026-10-15T18:00:09Z"),
  };
  harness.sendData(ch, published);
  const view = page.getByRole("region", { name: `${LATCHED_KEY} · DEMO` });
  await expect(
    view.getByText(
      /^Live: triggered, latched at 18:00:09 UTC\. The saved snapshot shows it clear\./u,
    ),
  ).toBeVisible();
  await expect(page.locator('[aria-live="assertive"] > p')).toHaveText(`${LATCHED_KEY} latched.`);
});
