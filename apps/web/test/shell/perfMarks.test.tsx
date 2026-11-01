import { act, render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { beforeEach, describe, expect, it } from "vitest";
import { SHELL_PERF_MARKS, createShellPerfMarks } from "../../src/shell/perfMarks.js";
import { runBootstrap } from "../../src/shell/bootstrap/bootstrap.js";
import { resetShellState, setShellState } from "../../src/shell/bootstrap/store.js";
import { resetMeClaims, setMeClaims } from "../../src/lib/auth/meCache.js";
import { buildRoutes } from "../../src/routes/tree.js";

const NAMES = Object.values(SHELL_PERF_MARKS) as string[];

/** The shell's marks on this page's timeline, in time order. */
const shellMarks = (): string[] =>
  performance
    .getEntriesByType("mark")
    .map((entry) => entry.name)
    .filter((name) => NAMES.includes(name));

function sink(): { names: string[]; mark: (name: string) => void } {
  const names: string[] = [];
  return { names, mark: (name) => names.push(name) };
}

describe("createShellPerfMarks", () => {
  it("uses the agreed names", () => {
    expect(SHELL_PERF_MARKS).toEqual({
      bootstrapReady: "shell_bootstrap_ms",
      wsLive: "ws_live",
      routeMounted: "route_mounted",
      interactive: "shell_cold_start_ms",
    });
  });

  it("marks each stage once, then shell interactive right after the last, in any order", () => {
    const out = sink();
    const mark = createShellPerfMarks(out);
    mark("ws_live");
    mark("route_mounted");
    mark("ws_live");
    expect(out.names).toEqual(["ws_live", "route_mounted"]);
    mark("shell_bootstrap_ms");
    mark("route_mounted");
    mark("shell_bootstrap_ms");
    expect(out.names).toEqual([
      "ws_live",
      "route_mounted",
      "shell_bootstrap_ms",
      "shell_cold_start_ms",
    ]);
  });

  it("never marks shell interactive while a stage is missing", () => {
    const out = sink();
    const mark = createShellPerfMarks(out);
    mark("shell_bootstrap_ms");
    mark("route_mounted");
    expect(out.names).not.toContain("shell_cold_start_ms");
  });
});

const ME = {
  user: { id: "u1", username: "owner", email: "o@example.com", roles: ["owner"], status: "active" },
  role: "owner",
  permissions: [],
  accounts: [],
  session: { session_id: "s1", environment: "demo", elevated_until: null },
};

/** `/me` answers ME; preferences and keymap answer empty bodies. */
const fetchImpl: typeof fetch = (input) =>
  Promise.resolve(
    new Response(JSON.stringify(input === "/api/v1/me" ? ME : {}), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );

describe("the shell's boot marks the stages on the page's timeline", () => {
  beforeEach(() => {
    resetShellState();
    resetMeClaims();
    setMeClaims({ authenticated: true, role: "owner", permissions: [] });
  });

  it("bootstrap ready, route mounted, first WS live, then shell interactive, each once", async () => {
    expect(shellMarks()).toEqual([]);
    await runBootstrap({ fetchImpl });
    expect(shellMarks()).toEqual(["shell_bootstrap_ms"]);

    render(
      <RouterProvider router={createMemoryRouter(buildRoutes(), { initialEntries: ["/risk"] })} />,
    );
    await screen.findByRole("heading", { name: /R-150/ });
    await act(async () => {});
    expect(shellMarks()).toEqual(["shell_bootstrap_ms", "route_mounted"]);

    act(() => setShellState({ connection: { kind: "live" } }));
    const boot = ["shell_bootstrap_ms", "route_mounted", "ws_live", "shell_cold_start_ms"];
    expect(shellMarks()).toEqual(boot);

    // A re-login (the store reset, live again) and a second bootstrap move no stage.
    resetShellState();
    act(() => setShellState({ connection: { kind: "live" } }));
    await runBootstrap({ fetchImpl });
    expect(shellMarks()).toEqual(boot);
  });
});
