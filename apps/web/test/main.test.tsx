import { describe, expect, it, vi } from "vitest";

const stop = vi.fn();
const startShell = vi.fn((o: { wsUrl: string }) => ({ stop, ready: Promise.resolve(), opts: o }));
const render = vi.fn();
/** What happened, in order: R-902's diversion must come before the router (App) is imported. */
const order: string[] = [];
vi.mock("../src/shell/startShell", () => ({ startShell }));
vi.mock("../src/features/system-states/bootOffline", () => ({
  divertUnreachableBoot: () => order.push("divert") > 0,
}));
vi.mock("../src/App", () => {
  order.push("import App");
  return { App: () => null };
});
// The held page itself is pinned by ViewAsBanner.test.tsx; here, only that main.tsx chooses it.
vi.mock("../src/features/view-as/heldBoot", () => {
  order.push("import heldBoot");
  return { showHeldBoot: (root: { render: (node: unknown) => void }) => root.render(null) };
});
vi.mock("react-dom/client", () => ({ createRoot: () => ({ render }) }));

describe("main.tsx", () => {
  it("calls startShell and renders only after bootstrap resolves", async () => {
    document.body.innerHTML = '<div id="root"></div>';
    await import("../src/main");
    expect(startShell).toHaveBeenCalledTimes(1);
    expect(startShell.mock.calls[0]![0]).toMatchObject({
      wsUrl: expect.stringMatching(/^wss?:\/\/.+\/api\/v1\/ws$/),
    });
    await vi.waitFor(() => expect(render).toHaveBeenCalledTimes(1));
    expect(render).toHaveBeenCalledTimes(1);
    expect(order).toEqual(["divert", "import App"]); // the router reads the URL when it is made
  });

  // E42-S03 V-8: a load into a view-as context the server ended mounts SCR-124's banner, never the
  // router: `/me` is refused then, and no route, claim or datum may mount
  it("renders the held page, and neither diverts nor imports the router, on a held boot", async () => {
    vi.resetModules();
    order.length = 0;
    render.mockClear();
    const { setShellState } = await import("../src/shell/bootstrap/store");
    setShellState({ bootstrap: { kind: "held" } });
    document.body.innerHTML = '<div id="root"></div>';
    await import("../src/main");
    await vi.waitFor(() => expect(render).toHaveBeenCalledTimes(1));
    expect(order).toEqual(["import heldBoot"]);
  });
});
