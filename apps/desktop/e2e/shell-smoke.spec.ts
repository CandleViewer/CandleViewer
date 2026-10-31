import { sr112Findings } from "@candleviewer/fixtures/e2e";
import { json, stubSession } from "@candleviewer/fixtures/e2e/stubs";
import { test, expect } from "@playwright/test";
import {
  closeShell,
  launchShell,
  metaCsp,
  sandboxFindings,
  servedCsp,
  SR110,
  webPreferencesOfAll,
} from "./support/shell";

// E10-Q02 Electron main-window smoke (C-9.1 #8; R0 exit criterion 9; plan steps EL-1, EL-2): the
// shell signs in on stubs, reaches /terminal and shows the DEMO badge; SR-110 holds on every web
// contents, the served CSP and its <meta> fallback match SR-112 directive by directive with no
// exchange host (SR-119), the renderers are OS-sandboxed, and nothing leaves the loopback.

test("@plan-EL-1 signs in on stubs, reaches /terminal and shows the environment badge", async () => {
  const shell = await launchShell({ devServer: true });
  const { app, win } = shell;
  await stubSession(win, { role: "owner" });
  await win.route("**/api/v1/auth/login", (r) => r.fulfill(json({ status: "authenticated" })));
  await win.goto(new URL("/login", win.url()).href);
  await win.getByLabel("Username or email").fill("ann");
  await win.getByLabel("Password", { exact: true }).fill("pw-e2e");
  await win.getByRole("button", { name: "Sign in" }).click();
  await expect(win).toHaveURL(/\/terminal\/last$/u);
  await expect(
    win.getByRole("banner").getByRole("img", { name: "Trading environment: Demo" }),
  ).toBeVisible();
  for (const prefs of await webPreferencesOfAll(app))
    expect(prefs).toEqual({ url: prefs.url, ...SR110 });
  await closeShell(shell);
});

test("@plan-EL-2 SR-110 on every web contents, SR-112 header and meta, OS sandbox (app:// load)", async () => {
  const shell = await launchShell();
  const { app, win } = shell;
  await win.waitForURL(/^app:\/\/candleviewer\//u);
  const all = await webPreferencesOfAll(app);
  expect(all.length).toBeGreaterThan(0);
  for (const prefs of all)
    expect(prefs, `SR-110 on ${prefs.url}`).toEqual({ url: prefs.url, ...SR110 });
  expect(sr112Findings(await servedCsp(app, win.url()), { delivery: "header" })).toEqual([]);
  expect(sr112Findings(await metaCsp(win), { delivery: "meta" })).toEqual([]);
  expect(await sandboxFindings(app)).toEqual([]);
  await closeShell(shell);
});
