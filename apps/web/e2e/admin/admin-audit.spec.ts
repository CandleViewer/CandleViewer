import { test, expect, type Page } from "@playwright/test";
import { stubSession } from "../support/api";
import { stubAdminReads, stubAuditLog } from "../support/admin";
import { seriousAxe } from "../support/axe";

// E42-S04 (#1135) admin-audit.spec: SCR-135 and SCR-136 (E42-D04 §4 to §8) in a real browser, every
// call answered at the network layer (C-13.5: no backend): the owner's log inside CMP-087.

const main = (page: Page) => page.getByRole("main");
const row = (page: Page, id: number) => page.locator(`tr[data-entry="${id}"]`);
const pager = (page: Page) => page.getByRole("navigation", { name: "Pagination" });
const expander = (page: Page, id: number) =>
  page.getByRole("button", { name: `Record ${id.toLocaleString("en-US")}`, exact: true });

/** The owner on R-360, SCR-120's strip reads and SCR-135's answered. */
async function openAsOwner(page: Page, options: Parameters<typeof stubAuditLog>[1] = {}) {
  await stubSession(page, { role: "owner" });
  await stubAdminReads(page);
  const wire = await stubAuditLog(page, options);
  await page.goto("/admin/audit");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Audit log");
  await expect(row(page, 1_204_300)).toBeVisible();
  return wire;
}

test("E42-S04 the filter round trip and cursor paging, with the first-page measures", async ({
  page,
}) => {
  const wire = await openAsOwner(page);
  await pager(page).getByRole("button", { name: "Older" }).click();
  await expect(row(page, 1_204_297)).toBeVisible();
  await expect(main(page).getByText("No older entries.")).toBeVisible();
  await pager(page)
    .getByRole("button", { name: /Newest$/ })
    .click();
  await expect(row(page, 1_204_300)).toBeVisible();
  const subject = page.getByRole("textbox", { name: "Subject id" });
  await subject.fill("0a000000-0000-4000-8000-000000000001");
  await subject.press("Enter");
  await expect(page).toHaveURL(/subject_id=0a000000-0000-4000-8000-000000000001/u);
  await expect(row(page, 1_204_299)).toBeVisible();
  await expect(row(page, 1_204_300)).toHaveCount(0);
  expect(wire.reads).toEqual([
    "?limit=200",
    "?cursor=c1&limit=200", // the contract's order: the cursor first
    "?limit=200",
    "?limit=200&subject_id=0a000000-0000-4000-8000-000000000001",
  ]);
  const measures = await page.evaluate(() =>
    ["cv_audit_first_page_ms", "cv_audit_filter_roundtrip_ms"].map(
      (name) => performance.getEntriesByName(name).length,
    ),
  );
  expect(measures).toEqual([1, 1]);
});

test("E42-S04 a row opens SCR-136: the correlation line, Previous and Next, no request", async ({
  page,
}) => {
  await openAsOwner(page);
  const requests: string[] = [];
  page.on("request", (r) => requests.push(new URL(r.url()).pathname));
  await row(page, 1_204_299).click();
  const drawer = page.getByRole("dialog", { name: "Record 1,204,299" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("Linked records can't be listed yet.")).toBeVisible();
  await drawer.getByRole("button", { name: /Next$/ }).click();
  await expect(page.getByRole("dialog", { name: "Record 1,204,298" })).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Previous$/ })
    .click();
  await expect(page.getByRole("dialog", { name: "Record 1,204,299" })).toBeVisible();
  expect(requests.filter((p) => p.startsWith("/api/v1/admin/audit"))).toEqual([]);
  expect(await seriousAxe(page)).toEqual([]); // the page with the drawer open
  // A-1135P2-05: the grid's sticky header stays under the drawer, never over its text
  const header = await page.locator(".cv-table__header").first().boundingBox();
  const panel = await page.getByRole("dialog").boundingBox();
  if (header === null || panel === null) throw new Error("no header or drawer box");
  const onTop = await page.evaluate(
    ([x, y]) => document.elementFromPoint(x ?? 0, y ?? 0)?.closest("[role='dialog']") !== null,
    [panel.x + 24, header.y + header.height / 2],
  );
  expect(onTop).toBe(true);
});

test("E42-S04 SCR-136 without a mouse: Next, then Esc closes it on that row; the arrows stop at Action", async ({
  page,
}) => {
  await openAsOwner(page);
  await expander(page, 1_204_300).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Record 1,204,300" })).toBeVisible();
  // D04 D1 (A-1135P2-04): with the drawer open, → stops at Action, End goes there
  await expander(page, 1_204_300).focus();
  for (let n = 0; n < 9; n += 1) await page.keyboard.press("ArrowRight");
  const column = () =>
    page.evaluate(() => document.activeElement?.closest("[data-cv-c]")?.getAttribute("data-cv-c"));
  expect(await column()).toBe("4");
  await page.getByRole("dialog").getByRole("button", { name: /Next$/ }).click();
  await expect(page.getByRole("dialog", { name: "Record 1,204,299" })).toBeVisible();
  // A-1135P2-01: Esc closes it for good, focus on the row it showed last
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(expander(page, 1_204_299)).toBeFocused(); // a re-opened drawer would hold focus
});

test("E42-S04 SCR-135 reflows at 200 % and 400 %: no sideways scroll, the grid stacks", async ({
  page,
}) => {
  // A-1135P2-03 (AL-28, WCAG 1.4.10): 640 and 320 CSS px wide are 1280 at 200 % and 400 %
  await stubSession(page, { role: "owner" });
  await stubAdminReads(page);
  await stubAuditLog(page);
  for (const width of [640, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/admin/audit");
    await expect(row(page, 1_204_300)).toBeVisible();
    const canvas = page.locator("[data-shell-canvas]");
    const widths = await canvas.evaluate((el) => [el.scrollWidth, el.clientWidth]);
    expect(widths[0]).toBeLessThanOrEqual(widths[1] ?? 0);
    await expect(page.locator(".cv-table[data-layout='stacked']")).toHaveCount(1);
    const action = await row(page, 1_204_300).locator("[data-cv-c='4']").boundingBox();
    expect(action?.width ?? 0).toBeGreaterThan(0);
  }
});

test("E42-S04 the empty state under Environment: an h2, Clear filters back to row 1, axe clean", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  await stubAdminReads(page);
  const wire = await stubAuditLog(page);
  await page.goto("/admin/audit?environment=testnet");
  const empty = page.getByRole("heading", { level: 2, name: "No records match these filters." });
  await expect(empty).toBeVisible();
  expect(await seriousAxe(page)).toEqual([]); // A-1135P2-08: no skipped heading level
  await page.getByRole("grid").getByRole("button", { name: "Clear filters" }).click();
  await expect(expander(page, 1_204_300)).toBeFocused(); // C-1135P2-10
  expect(wire.reads).toEqual(["?limit=200"]); // Environment sends no read (D7)
});

test("E42-S04 an expand at 200 rows: its scripting time, BQ-11's 8 ms check", async ({ page }) => {
  // C-1135P2-12: measured, not asserted; the number is in the run's annotations
  await stubSession(page, { role: "owner" });
  await stubAdminReads(page);
  await stubAuditLog(page, { rows: 200 });
  const opened = Date.now();
  await page.goto("/admin/audit");
  // 200 rows drawn whole (BQ-11) take seconds on a loaded host: the wait is the measure, not a bound
  await expect(row(page, 1_204_101)).toBeAttached({ timeout: 30_000 });
  const drawn = Date.now() - opened;
  await expander(page, 1_204_300).focus();
  const ms = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        const start = performance.now();
        // the expander is a native button: a synthetic Space never activates it, its click does
        (document.activeElement as HTMLElement).click();
        requestAnimationFrame(() => resolve(performance.now() - start));
      }),
  );
  await expect(expander(page, 1_204_300)).toHaveAttribute("aria-expanded", "true");
  test.info().annotations.push({ type: "cv_audit_expand_ms", description: ms.toFixed(1) });
  test.info().annotations.push({ type: "cv_audit_200_rows_drawn_ms", description: String(drawn) });
});

test("E42-S04 no control on the page, a row or the drawer changes a record", async ({ page }) => {
  await openAsOwner(page);
  const expander = page.getByRole("button", { name: "Record 1,204,300" });
  await expander.press(" "); // the diff row (AL-3)
  await expander.press("Enter"); // and SCR-136
  await expect(page.getByRole("dialog")).toBeVisible();
  const names = await page
    .locator("button, a[href], [role='menuitem']")
    .evaluateAll((els) =>
      els.map((el) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim()),
    );
  const mutation = /\b(edit|delete|correct|archive|repair|re-?hash|purge|modify|update)\b/iu;
  expect(names.filter((name) => mutation.test(name))).toEqual([]);
  await expect(
    main(page).getByText("Records can only be added, never edited or deleted. Kept indefinitely."),
  ).toBeVisible();
  expect(await seriousAxe(page)).toEqual([]);
});

test("E42-S04 an open chain break is the critical banner, with the halt line", async ({ page }) => {
  await openAsOwner(page, { broken: true });
  const alert = page
    .getByRole("alert")
    .filter({ hasText: "Tamper check FAILED at entry 1,204,118" });
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("treat this as a security incident");
  await expect(alert).toContainText("New orders that open or add to a position are halted");
  await expect(main(page).getByRole("button", { name: /Retry|Dismiss|Acknowledge/u })).toHaveCount(
    0,
  );
  expect(await seriousAxe(page)).toEqual([]);
});
