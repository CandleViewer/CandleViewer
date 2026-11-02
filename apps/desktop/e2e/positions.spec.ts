import AxeBuilder from "@axe-core/playwright";
import { stubSession } from "@candleviewer/fixtures/e2e/stubs";
import { AXE_GATE_TAGS, stubPositions } from "@candleviewer/fixtures/e2e";
import { expect, test } from "@playwright/test";
import { closeShell, launchShell } from "./support/shell";

// E29-S01 (#911, BQ-20) the Electron smoke of SCR-063 on R-130: the panel in the sandboxed renderer
// paints its rows from the stubbed REST read (first paint, BQ-18; no WS harness here: its SharedWorker
// shim is unproven in this renderer), keyboard reaches the grid, and axe, with the web gate's WCAG 2.2
// A and AA tags (`AXE_GATE_TAGS`), finds no serious or critical violation. The scenario matrix runs on
// the web project; full parity is E29-Q02's. Every wait is a condition, never a timer.

test("SCR-063 in the shell: rows from REST, the grid reached by keyboard, axe clean", async () => {
  const shell = await launchShell({ devServer: true });
  const { win } = shell;
  await stubSession(win, { role: "owner" });
  await stubPositions(win, { role: "owner" });
  await win.goto(new URL("/positions", win.url()).href);
  await expect(win.getByRole("heading", { level: 1, name: "Positions and orders" })).toBeVisible();
  const grid = win.getByRole("treegrid", { name: "Positions" });
  // REST paints first: the goldens' five rows under their account headers, and the totals row
  await expect(grid.getByRole("row", { name: /^[A-Z0-9]+USDT · / })).toHaveCount(5);
  await expect(
    grid.getByRole("row", { name: "BTCUSDT · Long · 0.25 BTC · Main", exact: true }),
  ).toBeVisible();
  await expect(grid.getByRole("rowheader", { name: /^LIVE total/ })).toContainText("5 open");
  // keyboard: from the Positions tab, the toolbar in order, then the grid's one stop, as the web
  // spec has it (`apps/web/e2e/specs/e29-positions/positions.spec.ts`): one Tab and one assertion
  // per stop, so a tab-order drift fails here too
  await win.getByRole("tab", { name: "Positions" }).focus();
  for (const control of [
    win.getByRole("combobox", { name: "Group by" }),
    win.getByRole("button", { name: "Filter" }),
    win.getByRole("button", { name: "Columns" }),
    win.getByRole("button", { name: "Export CSV" }),
  ]) {
    await win.keyboard.press("Tab");
    await expect(control).toBeFocused();
  }
  await win.keyboard.press("Tab");
  await expect(grid.getByRole("rowheader", { name: /^Main · LIVE/ })).toBeFocused();
  await win.keyboard.press("ArrowDown");
  await expect(
    grid
      .getByRole("row", { name: "BTCUSDT · Long · 0.25 BTC · Main", exact: true })
      .getByRole("gridcell")
      .first(),
  ).toBeFocused();
  const scan = await new AxeBuilder({ page: win }).withTags([...AXE_GATE_TAGS]).analyze();
  const serious = scan.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help}`);
  expect(serious).toEqual([]);
  await closeShell(shell);
});
