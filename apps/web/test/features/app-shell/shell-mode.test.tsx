import { createRequire } from "node:module";
import type { JSX } from "react";
import { act, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
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

async function renderShell(role: Role): Promise<void> {
  setMeClaims({ authenticated: true, role, permissions: [] });
  set({ connection: LIVE, me: me(role) });
  const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/journal"] });
  render(
    <>
      <RouterProvider router={router} />
      <ModeProbe />
    </>,
  );
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

  it("announces entering disconnected once (the chip's row 1), with no second node from the mode", async () => {
    await renderShell("owner");
    expect(assertiveSeq()).toBeNull();
    set({ connection: retry(1) });
    const first = assertiveSeq();
    expect(first).not.toBeNull();
    set({ connection: retry(2) });
    set({ connection: retry(3) });
    set({ latency: toLatencyIndicator(40) });
    expect(assertiveSeq()).toBe(first);
    expect(document.querySelectorAll('[aria-live="assertive"] p')).toHaveLength(1);
  });
});
