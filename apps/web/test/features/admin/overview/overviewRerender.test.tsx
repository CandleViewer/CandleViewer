/**
 * E42-S01 (#1022): the 30 s re-read must not re-render a tile whose words did not change (data never
 * flows through React per answer). CMP-178 is wrapped here to count each tile's renders: the module
 * mock is this file's alone.
 */
import { createElement, type JSX } from "react";
import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Ui from "@candleviewer/ui";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import { adminReads, REREAD_MS } from "../../../../src/features/admin/overview/readStore";
import { AdminArea } from "../../../../src/features/admin/shell/AdminArea";
import { resetShellState, setShellState, type Me } from "../../../../src/shell/bootstrap/store";

const renders = vi.hoisted(() => new Map<string, number>());
vi.mock("@candleviewer/ui", async (importOriginal) => {
  const ui = await importOriginal<typeof Ui>();
  function CountedTile(props: Ui.SystemHealthTileProps): JSX.Element {
    renders.set(props.label, (renders.get(props.label) ?? 0) + 1);
    return createElement(ui.SystemHealthTile, props);
  }
  return { ...ui, SystemHealthTile: CountedTile };
});

const AT = "2026-10-22T14:02:11Z";
const USERS = { status: "ok", generated_at: AT, total: 9, active: 6, without_mfa: 0 };
const overview = (users: object) => ({
  generated_at: AT,
  users,
  accounts: { status: "ok", generated_at: AT, total: 1, keys_expiring_30d: 0, keys_invalid: 0 },
  trading: { status: "unavailable", detail: "trading: no provider wired", generated_at: AT },
});
let overviewBody: unknown = overview(USERS);
const BODIES: Readonly<Record<string, () => unknown>> = {
  "/api/v1/admin/overview": () => overviewBody,
  "/api/v1/admin/capacity": () => ({ subaccounts: { status: "ok", tier_source: "recorded" } }),
  "/api/v1/admin/health": () => ({ overall: "healthy", server_time: AT, components: [] }),
  "/api/v1/admin/feature-flags": () => ({ resolution: "stored", items: [] }),
  "/api/v1/admin/audit?limit=3": () => ({ chain_verified: true, items: [] }),
  "/api/v1/admin/backups?limit=1": () => ({ items: [] }),
  "/api/v1/users/invites": () => ({ items: [] }),
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.parse(AT));
  adminReads.reset();
  renders.clear();
  overviewBody = overview(USERS);
  setShellState({
    me: { role: "owner", permissions: [], accounts: [] } as unknown as Me,
    environment: "live",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const body = BODIES[String(input)]?.() ?? {};
      return new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  adminReads.reset();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const flush = (ms = 0): Promise<void> =>
  act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

describe("SCR-120's re-read renders only what changed", () => {
  it("leaves a tile alone when its read answered the same words, and renders the one that changed", async () => {
    render(
      <MemoryRouter>
        <InShellProvider>
          <main>
            <AdminArea routeId="R-300" owner={null} />
          </main>
        </InShellProvider>
      </MemoryRouter>,
    );
    await flush();
    const settled = new Map(renders);
    expect(settled.size).toBe(9);
    await flush(REREAD_MS);
    // The cycle re-reads the overview alone (the ruling on BQ-5 for #5330), and it answered the same
    // words: not one tile renders again, Audit and Flags included (their reads were not repeated).
    for (const label of settled.keys()) {
      expect(renders.get(label), label).toBe(settled.get(label));
    }
    // A changed slice renders its tile, and only the tiles that read it changed words.
    overviewBody = overview({ ...USERS, without_mfa: 2 });
    const before = new Map(renders);
    await flush(REREAD_MS);
    expect(renders.get("Users")).toBe((before.get("Users") ?? 0) + 1);
    expect(renders.get("Profiles and limits")).toBe(before.get("Profiles and limits"));
    expect(renders.get("Trading safety")).toBe(before.get("Trading safety"));
  });
});
