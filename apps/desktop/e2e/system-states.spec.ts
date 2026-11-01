import { json, stubSession } from "@candleviewer/fixtures/e2e/stubs";
import { test, expect } from "@playwright/test";
import { closeShell, launchShell } from "./support/shell";

// E10-Q02 system states in the shell (plan step SS-4; BQ-14: three of five states, the two forced
// crashes deferred). GPU unavailable is desktop-only: main's `child-process-gone` for the GPU process
// sends `cv:gpu:crashed` and SCR-159's GPU page takes the canvas. The GPU process is killed from main
// through `app.evaluate`, so no test-only hook is added to the shell (BQ-08).

test("@plan-SS-4 GPU process killed: the GPU page takes the canvas, the badge stays", async () => {
  const shell = await launchShell({ devServer: true });
  const { app, win } = shell;
  await stubSession(win, { role: "owner" });
  await win.route("**/api/v1/auth/login", (r) => r.fulfill(json({ status: "authenticated" })));
  await win.goto(new URL("/login", win.url()).href);
  await win.getByLabel("Username or email").fill("ann");
  await win.getByLabel("Password", { exact: true }).fill("pw-e2e");
  await win.getByRole("button", { name: "Sign in" }).click();
  await expect(win).toHaveURL(/\/terminal\/last$/u);
  const killed = await app.evaluate(({ app: a }) => {
    const gpu = a.getAppMetrics().find((m) => m.type === "GPU");
    if (gpu !== undefined) process.kill(gpu.pid, "SIGKILL");
    return gpu?.pid ?? null;
  });
  expect(killed, "a GPU process to kill").not.toBeNull();
  await expect(
    win.getByRole("heading", { level: 1, name: "Hardware acceleration is off" }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(
    win.getByRole("banner").getByRole("img", { name: "Trading environment: Demo" }),
  ).toBeVisible();
  await closeShell(shell);
});
