// E11-Q02 (#444, BQ-04): one spec set, two runtimes. Electron is the desktop shell, which apps/desktop's
// playwright.engine.config.ts launches via `launchShell` and hands in as `openShell`, so apps/web
// imports no other app (C-3.5); an Electron failure shows under its own project (AC4). Every test
// runs under the shared egress guard (C-13.5).
import { guardContextEgress } from "@candleviewer/fixtures/e2e";
import { expect, test as base, type Page } from "@playwright/test";
import { EngineHarness } from "./harness";

export { expect };

export interface ShellHandle {
  readonly page: Page;
  readonly close: () => Promise<void>;
}
export interface EngineOptions {
  readonly openShell: (() => Promise<ShellHandle>) | undefined;
}

export const test = base.extend<EngineOptions & { harness: EngineHarness; egress: undefined }>({
  openShell: [undefined, { option: true }],
  page: async ({ page, openShell }, use) => {
    if (openShell === undefined) return use(page);
    const shell = await openShell(); // its own guard asserts at `close`
    await use(shell.page);
    await shell.close();
  },
  egress: [
    async ({ context, openShell }, use) => {
      if (openShell !== undefined) return use(undefined);
      const guard = await guardContextEgress(context);
      await use(undefined);
      expect(guard.hits(), "the page sent a request past the loopback interface").toEqual([]);
    },
    { auto: true },
  ],
  harness: async ({ page, baseURL }, use) => {
    if (baseURL === undefined) throw new Error("engine e2e: baseURL is not set");
    await use(new EngineHarness(page, baseURL));
  },
});
