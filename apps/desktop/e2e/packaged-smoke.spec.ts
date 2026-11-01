import { sr112Findings } from "@candleviewer/fixtures/e2e";
import { test, expect } from "@playwright/test";
import {
  closeShell,
  launchShell,
  sandboxFindings,
  servedCsp,
  SR110,
  webPreferencesOfAll,
} from "./support/shell";

// E10-Q02 packaged smoke (BQ-07 a; plan step EL-3): the `electron-builder --dir` output, launched as
// it ships (app.isPackaged, so the dev-server hook is refused). The `packaged` project of the config
// runs this file only when CV_PACKAGED_EXECUTABLE names the built executable (the CI job sets it).

const EXECUTABLE = process.env["CV_PACKAGED_EXECUTABLE"] ?? "";

test("@plan-EL-3 the packaged shell boots over app:// with SR-110, SR-112 and its OS sandbox @ga-regression @ga-area-shell", async () => {
  expect(EXECUTABLE, "CV_PACKAGED_EXECUTABLE is not set").not.toBe("");
  const shell = await launchShell({ executablePath: EXECUTABLE });
  const { app, win } = shell;
  expect(await app.evaluate(({ app: a }) => a.isPackaged)).toBe(true);
  await win.waitForURL(/^app:\/\/candleviewer\//u);
  await expect(win.locator("#root main")).toBeVisible();
  for (const prefs of await webPreferencesOfAll(app))
    expect(prefs).toEqual({ url: prefs.url, ...SR110 });
  expect(sr112Findings(await servedCsp(app, win.url()), { delivery: "header" })).toEqual([]);
  expect(await sandboxFindings(app)).toEqual([]);
  await closeShell(shell);
});
