import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, test, expect } from "@playwright/test";

// E49-S07 on the Electron shell: the keymap host runs in the sandboxed renderer, the cheatsheet
// opens from the keyboard, and an inert destructive press explains itself once (politely).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MAIN_ENTRY = path.join(__dirname, "../dist/main/index.js");

test.describe("Electron keymap (E49-S07)", () => {
  test("Ctrl+/ opens the cheatsheet; inert destructive press toasts once", async () => {
    // Loads the built web app through the shell's dev-server hook (CV_DEV_SERVER_URL, loopback
    // only) served by `vite preview`; app-protocol.spec.ts covers the default app:// load path.
    const app = await electron.launch({
      args: [MAIN_ENTRY],
      // Without it Playwright prepends `--no-sandbox` on Linux; the renderer stays OS-sandboxed.
      chromiumSandbox: true,
      env: {
        ...process.env,
        CV_DEV_SERVER_URL: process.env["CV_WEB_URL"] ?? "http://127.0.0.1:4173",
      },
    });
    const win = await app.firstWindow();
    await win.waitForLoadState("domcontentloaded");
    await expect(win.getByTestId("toast-host")).toBeAttached();
    // Since #5215 (SCR-015 via CMP-045) the toasts portal to `body` as the "Notifications" region,
    // one group per toast; `toast-host` stays only as the inert-exempt wrapper and holds none.
    const region = win.getByRole("region", { name: "Notifications" });
    // E10-Q02: wait on the condition, not a timer: press until the keymap host has mounted and
    // answered once (an inert press explains itself at most once per 5 s, so a repeat cannot add
    // a second toast).
    await expect(async () => {
      await win.keyboard.press("Control+Shift+X");
      await expect(region.getByRole("group").first()).toBeVisible({ timeout: 250 });
    }).toPass();
    for (let i = 0; i < 2; i++) await win.keyboard.press("Control+Shift+X");
    await expect(region.getByRole("group")).toHaveCount(1);
    await expect(region).toContainText(
      "Cancel all working orders for symbol is not available here",
    );
    await win.keyboard.press("Control+/");
    await expect(win.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
    await app.close();
  });
});
