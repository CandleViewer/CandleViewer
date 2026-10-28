import { createRequire } from "node:module";
import type { JSX } from "react";
import { act, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RAIL } from "../../../e2e/support/rail";
import { clearAnnouncements } from "../../../src/features/app-shell/announcer";
import {
  deriveShellMode,
  type ShellMode,
  type ShellModeInputs,
} from "../../../src/features/app-shell/shellMode";
import { useShellMode } from "../../../src/features/app-shell/useShellMode";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";
import { buildRoutes } from "../../../src/routes/tree";
import {
  resetShellState,
  setShellState,
  type ConnectionState,
  type Me,
} from "../../../src/shell/bootstrap/store.js";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

type Role = Me["role"];
const KINDS: readonly ShellModeInputs["connection"][] = [
  "connecting",
  "live",
  "reconnecting",
  "offline",
];
const ROLES: readonly (Role | null)[] = ["owner", "manager", "viewer", null];
const BOOLS = [false, true] as const;

/** Every input combination: 4 × 2 × 2 × 2 × 2 × 4 × 2 = 512 rows. */
const ALL: ShellModeInputs[] = KINDS.flatMap((connection) =>
  BOOLS.flatMap((everLive) =>
    BOOLS.flatMap((degraded) =>
      BOOLS.flatMap((frozen) =>
        BOOLS.flatMap((lockout) =>
          ROLES.flatMap((role) =>
            BOOLS.map((viewAs) => ({
              connection,
              everLive,
              degraded,
              frozen,
              lockout,
              role,
              viewAs,
            })),
          ),
        ),
      ),
    ),
  ),
);

/** The precedence, written as the list it is; the first condition that holds names the mode. */
const PRECEDENCE: readonly [ShellMode, (i: ShellModeInputs) => boolean][] = [
  [
    "disconnected",
    (i) =>
      i.connection === "reconnecting" ||
      i.connection === "offline" ||
      (i.connection === "connecting" && i.everLive),
  ],
  ["frozen", (i) => i.frozen],
  ["lockout", (i) => i.lockout],
  ["degraded", (i) => i.degraded],
  ["read-only", (i) => i.viewAs || i.role === "viewer"],
];
const expected = (i: ShellModeInputs): ShellMode =>
  PRECEDENCE.find(([, holds]) => holds(i))?.[0] ?? "normal";

const BASE: ShellModeInputs = {
  connection: "live",
  everLive: true,
  degraded: false,
  frozen: false,
  lockout: false,
  role: "owner",
  viewAs: false,
};

describe("deriveShellMode: the precedence table", () => {
  it("covers all 512 input combinations", () => {
    expect(new Set(ALL.map((i) => JSON.stringify(i))).size).toBe(512);
  });

  it.each(ALL)("%j → the first condition that holds", (i) => {
    const r = deriveShellMode(i);
    expect(r.mode).toBe(expected(i));
    // The overlay is orthogonal (E17-D01 §4): returned under every mode, view-as first (D03 §1.3).
    expect(r.readOnly).toBe(i.viewAs ? "view-as" : i.role === "viewer" ? "role" : null);
  });

  it.each<[string, Partial<ShellModeInputs>, ShellMode, "view-as" | "role" | null]>([
    ["cell 1 normal · owner", {}, "normal", null],
    ["cell 2 disconnected · owner", { connection: "reconnecting" }, "disconnected", null],
    ["cell 3 degraded · owner", { degraded: true }, "degraded", null],
    ["cell 4 frozen · owner", { frozen: true }, "frozen", null],
    ["cell 5 lockout · owner", { lockout: true }, "lockout", null],
    ["cell 6 read-only · owner (view-as)", { viewAs: true }, "read-only", "view-as"],
    ["cell 7 normal · manager", { role: "manager" }, "normal", null],
    ["cell 13 normal · viewer is read-only", { role: "viewer" }, "read-only", "role"],
    [
      "cell 14 disconnected · viewer",
      { role: "viewer", connection: "offline" },
      "disconnected",
      "role",
    ],
    ["cell 15 degraded · viewer", { role: "viewer", degraded: true }, "degraded", "role"],
    ["cell 16 frozen · viewer", { role: "viewer", frozen: true }, "frozen", "role"],
    ["cell 17 lockout · viewer", { role: "viewer", lockout: true }, "lockout", "role"],
    [
      "the boot's first connect is not a loss",
      { connection: "connecting", everLive: false },
      "normal",
      null,
    ],
    ["a reconnect's handshake is", { connection: "connecting" }, "disconnected", null],
    [
      "kill-switch state is unknown while down",
      { connection: "reconnecting", frozen: true },
      "disconnected",
      null,
    ],
    ["frozen before lockout (PROPOSED)", { frozen: true, lockout: true }, "frozen", null],
    ["lockout before degraded", { lockout: true, degraded: true }, "lockout", null],
  ])("D03 §4 %s", (_name, patch, mode, readOnly) => {
    expect(deriveShellMode({ ...BASE, ...patch })).toEqual({ mode, readOnly });
  });
});

const me = (role: Role): Me => ({
  accounts: [],
  permissions: [],
  role,
  user: {
    email: "user@example.test",
    id: "00000000-0000-4000-8000-000000000001",
    roles: [role],
    status: "active",
    username: "user",
  },
});
const LIVE: ConnectionState = { kind: "live" };
const retry = (attempt: number): ConnectionState => ({
  kind: "reconnecting",
  attempt,
  nextAttemptAtMs: 4_000 * attempt,
});
const FEED_DOWN = { asserted: { exchangeFeedDown: 1 }, privateHandedOver: false } as const;
const set = (patch: Parameters<typeof setShellState>[0]): void => act(() => setShellState(patch));

const renders = { n: 0 };
function ModeProbe(): JSX.Element {
  renders.n += 1;
  const { mode, readOnly } = useShellMode();
  return <output aria-label="Shell mode">{`${mode}:${readOnly ?? "-"}`}</output>;
}
const probe = (): string | null => screen.getByRole("status", { name: "Shell mode" }).textContent;

afterEach(() => {
  act(() => {
    resetShellState();
    clearAnnouncements();
  });
  renders.n = 0;
});

describe("useShellMode", () => {
  it("reads normal on the boot's first connect, then disconnected once a live link is lost", () => {
    render(<ModeProbe />);
    expect(probe()).toBe("normal:-");
    set({ connection: LIVE });
    set({ connection: { kind: "connecting" } });
    expect(probe()).toBe("disconnected:-");
  });

  it("reads disconnected when it mounts mid-outage, and two consumers agree", () => {
    set({ connection: LIVE });
    set({ connection: { kind: "connecting" } });
    render(<ModeProbe />);
    render(<ModeProbe />);
    const probes = screen.getAllByRole("status", { name: "Shell mode" });
    expect(probes.map((p) => p.textContent)).toEqual(["disconnected:-", "disconnected:-"]);
  });

  it("forgets the live latch on resetShellState (logout), so the next boot's connect is normal", () => {
    set({ connection: LIVE });
    act(() => resetShellState());
    set({ connection: { kind: "connecting" } });
    render(<ModeProbe />);
    expect(probe()).toBe("normal:-");
  });

  it("re-renders on a mode change only: never on the latency tick or a retry attempt", () => {
    set({ connection: LIVE, me: me("owner") });
    render(<ModeProbe />);
    const base = renders.n;
    for (let ms = 10; ms < 70; ms += 1) set({ latency: toLatencyIndicator(ms) });
    expect(renders.n).toBe(base);
    set({ connection: retry(1) });
    expect(renders.n).toBe(base + 1);
    set({ connection: retry(2) });
    set({ connection: retry(3) });
    set({ degraded: { asserted: { exchangeFeedDown: 2 }, privateHandedOver: false } });
    expect(renders.n).toBe(base + 1);
    expect(probe()).toBe("disconnected:-");
  });

  it("maps the store's degraded rows and the Viewer role", () => {
    set({ connection: LIVE, me: me("viewer") });
    render(<ModeProbe />);
    expect(probe()).toBe("read-only:role");
    set({ degraded: FEED_DOWN });
    expect(probe()).toBe("degraded:role");
    set({ connection: retry(1) });
    expect(probe()).toBe("disconnected:role");
  });
});

/** Elements reachable by Tab, in document order (jsdom has no real Tab traversal). */
const tabStops = (): HTMLElement[] =>
  [...document.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), [tabindex]")].filter(
    (el) => el.tabIndex >= 0,
  );
const overlay = (): HTMLElement => {
  const el = document.querySelector<HTMLElement>('[data-shell-slot="canvas-overlay"]');
  if (el === null) throw new Error("no canvas overlay slot");
  return el;
};
const assertiveSeq = (): string | null =>
  document.querySelector('[aria-live="assertive"] p')?.getAttribute("data-seq") ?? null;

/**
 * The store as the app's boot leaves it for the router, which `main.tsx` renders only after the
 * bootstrap: the claims, `/me`, an environment and the live link. The app's `runBootstrap` writes
 * `/me` and the environment its session names in one update; this fixture's `/me` names none, so
 * the environment is seeded here, before the first render, as the boot would leave it.
 */
function bootShell(role: Role): void {
  setMeClaims({ authenticated: true, role, permissions: [] });
  set({ connection: LIVE, me: me(role), environment: "live" });
}

/**
 * The router at R-180, beside the probe. The router renders the shell later, in a transition
 * outside act; the shell's store subscriptions are that commit's passive effects, which the
 * scheduler runs in a task of their own.
 */
function mountShell(): void {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/journal"] });
  render(
    <>
      <RouterProvider router={router} />
      <ModeProbe />
    </>,
  );
}

async function renderShell(role: Role): Promise<void> {
  bootShell(role);
  mountShell();
  await screen.findByRole("heading", { name: /R-180/ });
}

/** Every mode the store can reach today; frozen and lockout have no source (#304 gap 13). */
const REACHABLE: readonly [ShellMode, Role, Parameters<typeof setShellState>[0]][] = [
  ["normal", "owner", {}],
  ["disconnected", "owner", { connection: retry(1) }],
  ["degraded", "owner", { degraded: FEED_DOWN }],
  ["read-only", "viewer", {}],
];

describe("the shell in each mode (D03 §4; D02 :59)", () => {
  beforeEach(() => resetMeClaims());

  it.each(REACHABLE)(
    "%s: nothing covers the canvas, the chrome stays reachable, no serious axe violation",
    async (mode, role, patch) => {
      await renderShell(role);
      set(patch);
      expect(probe()?.startsWith(`${mode}:`)).toBe(true);
      // D02 :59 supersedes the canvas scrim for frozen, the shell-wide scrim for lockout and the
      // centred reconnect overlay; D03 §4 draws panel scrims (disconnected) and dims (degraded)
      // in the panels, "no scrim" for degraded and lockout. The shell's overlay layer stays empty.
      expect(overlay()).toBeEmptyDOMElement();
      const stops = tabStops();
      expect(stops[0]).toHaveAccessibleName("Skip to main content");
      expect(stops).toContain(
        within(screen.getByRole("banner")).getByRole("button", { name: /^Connection:/ }),
      );
      for (const link of within(screen.getByRole("navigation", { name: "Primary" })).getAllByRole(
        "link",
      )) {
        expect(stops).toContain(link);
      }
      const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
      expect(
        res.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
    },
  );

  it("adds no announcement of its own on entering disconnected (row 1 belongs to the connection region)", async () => {
    // Since #306 slice 4b the connection region (CMP-077) is the one writer of E17-D02 §11 row 1,
    // driven by the WS layer's state and covered by its own tests; the chip and the mode say nothing.
    await renderShell("owner");
    expect(assertiveSeq()).toBeNull();
    set({ connection: retry(1) });
    set({ connection: retry(2) });
    set({ connection: retry(3) });
    set({ latency: toLatencyIndicator(40) });
    expect(assertiveSeq()).toBeNull();
    expect(document.querySelectorAll('[aria-live="assertive"] p')).toHaveLength(0);
  });
});

/** The state × role matrix (#304 test plan: axe on every state × role; S9). */
const STATES: readonly [ShellMode, Parameters<typeof setShellState>[0]][] = [
  ["normal", {}],
  ["disconnected", { connection: retry(1) }],
  ["degraded", { degraded: FEED_DOWN }],
];
const MATRIX_ROLES = ["owner", "manager", "viewer"] as const;
const MATRIX = STATES.flatMap(([mode, patch]) =>
  MATRIX_ROLES.map((role) => [mode, role, patch] as const),
);
const MATRIX_TITLE =
  "%s × %s: the badge shows, Admin only for the owner, the read-only overlay for a viewer, axe-clean";

/**
 * A matrix case once the shell has rendered: its mode's write, then every check that takes no wait.
 * The environment is the boot's (`bootShell`), so the badge never waits for the shell's store
 * subscriptions; a mode's write moves the probe, whose render runs any pending effect first.
 */
function checkShellMatrix(
  mode: ShellMode,
  role: (typeof MATRIX_ROLES)[number],
  patch: Parameters<typeof setShellState>[0],
): void {
  set(patch);
  // A viewer's normal shell is read-only; under any other mode the overlay rides along.
  const expected = role === "viewer" && mode === "normal" ? "read-only" : mode;
  expect(probe()).toBe(`${expected}:${role === "viewer" ? "role" : "-"}`);
  const bar = screen.getByRole("banner");
  expect(within(bar).getByRole("img", { name: "Trading environment: Live" })).toBeVisible();
  const nav = screen.getByRole("navigation", { name: "Primary" });
  expect(
    within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent),
  ).toEqual([...RAIL[role]]);
  expect(within(nav).queryByRole("link", { name: "Admin" }) !== null).toBe(role === "owner");
  expect(screen.getAllByRole("main")).toHaveLength(1);
}

async function shellMatrixCase(
  mode: ShellMode,
  role: (typeof MATRIX_ROLES)[number],
  patch: Parameters<typeof setShellState>[0],
): Promise<void> {
  await renderShell(role);
  checkShellMatrix(mode, role, patch);
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
}

describe("the shell matrix: every reachable state × role (S9)", () => {
  beforeEach(() => resetMeClaims());

  it.each(MATRIX)(MATRIX_TITLE, shellMatrixCase);

  // #4875: `renderShell` can return after the router's commit of the shell and before that
  // commit's effects subscribe the shell to the store, as on a loaded run. The checks must hold
  // there. The scheduler's clock jumps 6 ms on every read, so it yields after every task: the
  // effects wait for a later task, and a mutation callback, a microtask, runs the checks first.
  it.each(MATRIX_ROLES)(
    "normal × %s: the checks hold before the shell's first commit has run its effects",
    async (role) => {
      bootShell(role);
      let now = performance.now();
      const clock = vi.spyOn(performance, "now").mockImplementation(() => (now += 6));
      let seen: MutationObserver | undefined;
      try {
        const checked = new Promise<void>((resolve, reject) => {
          seen = new MutationObserver(() => {
            if (screen.queryByRole("heading", { name: /R-180/ }) === null) return;
            seen?.disconnect();
            try {
              checkShellMatrix("normal", role, {});
              resolve();
            } catch (error) {
              reject(error instanceof Error ? error : new Error(String(error)));
            }
          });
          seen.observe(document.body, { childList: true, subtree: true });
        });
        mountShell();
        await checked;
      } finally {
        seen?.disconnect();
        clock.mockRestore();
      }
    },
  );
});
