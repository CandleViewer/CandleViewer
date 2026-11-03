/**
 * E28-S01 (#971) BQ-09 as ruled: R-330 mounts SCR-130 only when the mirrored `admin.account_profiles`
 * flag (WS system frames, `23` §15.9) reads on; off (the default), unread, absent or not boolean, the
 * route keeps the stub naming its owner, so no unfinished screen ships (C-4.13).
 */
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { adminReads } from "../../../../src/features/admin/overview/readStore";
import { PROFILES_FLAG } from "../../../../src/features/admin/profiles/flags";
import { AdminArea } from "../../../../src/features/admin/shell/AdminArea";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import type { SystemUpdate } from "../../../../src/lib/ws/protocol/frames.js";
import { applySystemUpdate, resetShellState } from "../../../../src/shell/bootstrap/store";

const WAIT = { timeout: 5_000 } as const;

/** Every admin read answers an empty list; the flag never comes from REST. */
function serve(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
}

const push = (flags: unknown): void =>
  act(() =>
    applySystemUpdate({ kind: "feature_flags", feature_flags: flags } as unknown as SystemUpdate),
  );

beforeEach(() => {
  adminReads.reset();
  clearAnnouncements();
  serve();
});

afterEach(() => {
  adminReads.reset();
  clearAnnouncements();
  resetShellState();
  vi.unstubAllGlobals();
});

function area(): void {
  render(
    <MemoryRouter>
      <InShellProvider>
        <main tabIndex={-1}>
          <AdminArea routeId="R-330" owner="E18" />
        </main>
      </InShellProvider>
    </MemoryRouter>,
  );
}

const stub = { level: 1, name: "R-330 — owned by E18" } as const;
const page = { level: 1, name: "Account profiles" } as const;

describe("R-330 behind its mirrored flag", () => {
  it("test_r330_keeps_its_stub_while_the_flag_is_unread", async () => {
    area();
    expect(await screen.findByRole("heading", stub, WAIT)).toBeInTheDocument();
    expect(screen.queryByRole("heading", page)).toBeNull();
  });

  it.each([
    ["off", { [PROFILES_FLAG]: false }],
    ["absent", { "trading.trade_groups": true }],
    ["non_boolean", { [PROFILES_FLAG]: "true" }],
  ])("test_r330_keeps_its_stub_while_the_flag_is_%s", async (_, flags) => {
    area();
    push(flags);
    expect(await screen.findByRole("heading", stub, WAIT)).toBeInTheDocument();
    expect(screen.queryByRole("heading", page)).toBeNull();
  });

  it("test_r330_mounts_scr130_when_the_flag_is_on", async () => {
    area();
    push({ [PROFILES_FLAG]: true });
    expect(await screen.findByRole("heading", page, WAIT)).toBeInTheDocument();
  });

  it("test_r330_returns_to_the_stub_when_the_flag_turns_off", async () => {
    area();
    push({ [PROFILES_FLAG]: true });
    expect(await screen.findByRole("heading", page, WAIT)).toBeInTheDocument();
    push({ [PROFILES_FLAG]: false });
    expect(await screen.findByRole("heading", stub, WAIT)).toBeInTheDocument();
  });

  /** A Manager's mirror: the server cuts the set to what its role may see (`23` §15.9). */
  it("test_r330_opens_under_a_managers_mirror_that_carries_the_flag", async () => {
    area();
    expect(await screen.findByRole("heading", stub, WAIT)).toBeInTheDocument();
    act(() =>
      applySystemUpdate({
        kind: "health",
        health: "healthy",
        feature_flags: { [PROFILES_FLAG]: true, "trading.one_click": false },
      } as unknown as SystemUpdate),
    );
    expect(await screen.findByRole("heading", page, WAIT)).toBeInTheDocument();
  });

  it("test_r330_swaps_stub_for_list_when_the_snapshot_lands_with_one_heading_and_stable_focus", async () => {
    area();
    const main = screen.getByRole("main");
    act(() => main.focus());
    expect(await screen.findByRole("heading", stub, WAIT)).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(main).toHaveFocus();
    push({ [PROFILES_FLAG]: true });
    expect(await screen.findByRole("heading", page, WAIT)).toBeInTheDocument();
    expect(screen.queryByRole("heading", stub)).toBeNull();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(main).toHaveFocus();
  });
});
