import { createRequire } from "node:module";
import { stubSession } from "@candleviewer/fixtures/e2e/stubs";
import { stubPositions } from "@candleviewer/fixtures/e2e";
import { expect, test, type Page } from "@playwright/test";
import { closeShell, launchShell } from "./support/shell";

// E29-S01 (#911, BQ-20) the Electron smoke of SCR-063 on R-130: the panel in the sandboxed renderer
// paints its rows from the stubbed REST read (first paint, BQ-18; no WS harness here: its SharedWorker
// shim is unproven in this renderer), keyboard reaches the grid, and axe finds no serious or critical
// violation. The scenario matrix runs on the web project; full parity is E29-Q02's. Every wait is a
// condition, never a timer.

interface AxeResults {
  readonly violations: readonly {
    readonly id: string;
    readonly help: string;
    readonly impact?: string | null;
  }[];
}
type AxeBuilderClass = new (options: { readonly page: Page }) => { analyze(): Promise<AxeResults> };

/**
 * axe, as the web suite runs it: `@axe-core/playwright` comes with `@candleviewer/web`, this package's own
 * devDependency (the renderer it ships), and is resolved through it, so no second copy is declared here.
 */
async function axeBuilder(): Promise<AxeBuilderClass> {
  const web = createRequire(
    createRequire(import.meta.url).resolve("@candleviewer/web/package.json"),
  );
  const mod = (await import(web.resolve("@axe-core/playwright"))) as { default: AxeBuilderClass };
  return mod.default;
}

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
    grid.getByRole("row", { name: "BTCUSDT · Long · 0.250 BTC · Main", exact: true }),
  ).toBeVisible();
  await expect(grid.getByRole("rowheader", { name: /^LIVE total/ })).toContainText("5 open");
  // keyboard: from the Positions tab, through the toolbar, to the grid's one stop
  await win.getByRole("tab", { name: "Positions" }).focus();
  await expect(async () => {
    await win.keyboard.press("Tab");
    await expect(grid.getByRole("rowheader", { name: /^Main · LIVE/ })).toBeFocused({
      timeout: 250,
    });
  }).toPass();
  await win.keyboard.press("ArrowDown");
  await expect(
    grid
      .getByRole("row", { name: "BTCUSDT · Long · 0.250 BTC · Main", exact: true })
      .getByRole("gridcell")
      .first(),
  ).toBeFocused();
  const AxeBuilder = await axeBuilder();
  const scan = await new AxeBuilder({ page: win }).analyze();
  const serious = scan.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help}`);
  expect(serious).toEqual([]);
  await closeShell(shell);
});
