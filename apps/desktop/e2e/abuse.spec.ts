import { ROUTE_EXPECTATIONS, expectSettledOutcome, type Role } from "@candleviewer/fixtures/e2e";
import { stubSession } from "@candleviewer/fixtures/e2e/stubs";
import { test, expect } from "@playwright/test";
import { closeShell, launchShell } from "./support/shell";

// E10-Q02, the Electron half of the per-PR abuse subset absorbed from E10-X03 (plan steps AB-5,
// RM-2). Titles name the control each test holds; failures name it too.

test("@abuse @plan-AB-5 context isolation: the renderer reaches no Node global and no raw IPC", async () => {
  const shell = await launchShell();
  const reach = await shell.win.evaluate(() => {
    const g = globalThis as unknown as Record<string, unknown>;
    const cv = (g["cv"] ?? {}) as Record<string, unknown>;
    return {
      globals: ["require", "process", "module", "Buffer", "ipcRenderer", "electron"].filter(
        (name) => typeof g[name] !== "undefined",
      ),
      bridge: Object.keys(cv).filter((k) => /ipc|invoke|send|require|exec/iu.test(k)),
      bridgeNonFunctions: Object.keys(cv).filter((k) => typeof cv[k] !== "function"),
    };
  });
  expect(reach.globals, "SR-110: Node globals reachable from the renderer").toEqual([]);
  expect(reach.bridge, "SR-111: a generic IPC member on window.cv").toEqual([]);
  expect(reach.bridgeNonFunctions, "SR-111: window.cv exposes a non-function").toEqual([]);
  await closeShell(shell);
});

/** One route per access class (the full 66 × 3 sweep is the web lane's role-matrix.spec.ts). */
const SUBSET: readonly (readonly [string, string])[] = [
  ["R-130", "/positions"], // every role
  ["R-150", "/risk"], // owner only: 403
  ["R-160", "/rules"], // owner and manager: 403 for a viewer
  ["R-301", "/admin/users"], // owner-hat: 404
  ["R-360", "/admin/audit"], // under /admin, owner and manager: 403 for a viewer
];

for (const role of ["owner", "manager", "viewer"] as const satisfies readonly Role[])
  test(`@abuse @plan-RM-2 route guard in the shell as ${role}: one route per access class`, async () => {
    const shell = await launchShell({ devServer: true });
    await stubSession(shell.win, { role });
    for (const [id, path] of SUBSET) {
      await shell.win.goto(new URL(path, shell.win.url()).href);
      await expectSettledOutcome(
        shell.win,
        path,
        ROUTE_EXPECTATIONS[id]?.[role],
        `route guard for ${id} as ${role}`,
      );
    }
    await closeShell(shell);
  });
