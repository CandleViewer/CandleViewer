import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { resetSharedThemeStores } from "@candleviewer/ui";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { buildRoutes } from "../../src/routes/tree";
import { setMeClaims, resetMeClaims } from "../../src/lib/auth/meCache";
import {
  DragOnly,
  KeyboardEquivalent,
  PanelResizeControl,
  PreferencesProvider,
  createEngineFlagsChannel,
  resolveFlags,
  DEFAULT_PREFERENCES,
  useDefaultPanelView,
} from "../../src/features/a11y-preferences";

function reply(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}
afterEach(() => {
  vi.unstubAllGlobals();
  resetMeClaims();
  resetSharedThemeStores(); // the provider's flags follow the app's theme store (#3436)
});

function Probe(): JSX.Element {
  const [v, setV] = [useDefaultPanelView(), 0] as const;
  void setV;
  return (
    <div>
      <span data-testid="view">{v}</span>
      <DragOnly>
        <span>drag-only-handle</span>
      </DragOnly>
      <KeyboardEquivalent>
        <span>form-equivalent</span>
      </KeyboardEquivalent>
    </div>
  );
}

describe("keyboard-only mode and table preference consumers", () => {
  it("hides drag-only affordances and reveals equivalents; tables become default", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          reply(200, { accessibility: { keyboard_only: true, always_show_tables: true } }),
        ),
    );
    render(
      <PreferencesProvider>
        <Probe />
      </PreferencesProvider>,
    );
    expect(screen.getByText("drag-only-handle")).toBeInTheDocument();
    expect(screen.getByTestId("view")).toHaveTextContent("chart");
    await waitFor(() => expect(screen.getByText("form-equivalent")).toBeInTheDocument());
    expect(screen.queryByText("drag-only-handle")).toBeNull();
    expect(screen.getByTestId("view")).toHaveTextContent("table");
  });

  it("panel resize offers keyboard nudge + numeric field in keyboard-only mode", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(reply(200, { accessibility: { keyboard_only: true } })),
    );
    const onChange = vi.fn();
    render(
      <PreferencesProvider>
        <PanelResizeControl
          label="Panel width"
          value={300}
          min={100}
          max={320}
          onChange={onChange}
        />
      </PreferencesProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Increase Panel width" }));
    expect(onChange).toHaveBeenLastCalledWith(310);
    fireEvent.change(screen.getByLabelText("Panel width (px)"), { target: { value: "999" } });
    expect(onChange).toHaveBeenLastCalledWith(320);
    expect(screen.queryByRole("separator")).toBeNull();
  });
});

describe("engine flags channel", () => {
  it("a render loop reading flags does no animation work after disabling, within one frame", () => {
    const ch = createEngineFlagsChannel();
    let work = 0;
    const frame = (): void => {
      const f = ch.get();
      if (f === null || f.animate) work += 1000; // stand-in for transition/fade/inertia work
      work += 1;
    };
    ch.publish(resolveFlags(DEFAULT_PREFERENCES, "safe"));
    frame();
    const animating = work;
    work = 0;
    ch.publish(resolveFlags({ ...DEFAULT_PREFERENCES, disable_canvas_animation: true }, "safe"));
    frame();
    expect(work).toBeLessThan(animating);
    expect(work).toBe(1);
  });
});

describe("SCR-117 routed in the real app", () => {
  it("renders at /settings/appearance and a toggle publishes engine flags", async () => {
    const f = vi
      .fn()
      .mockImplementation(async (_u: string, init?: { method?: string }) =>
        init?.method === "PUT"
          ? reply(200, { accessibility: { disable_canvas_animation: true } })
          : reply(200, {}),
      );
    vi.stubGlobal("fetch", f);
    setMeClaims({ authenticated: true, role: "owner", permissions: [], elevatedAt: null });
    const flags = vi.fn();
    const router = createMemoryRouter(buildRoutes(), { initialEntries: ["/settings/appearance"] });
    render(
      <PreferencesProvider onEngineFlags={flags}>
        <RouterProvider router={router} />
      </PreferencesProvider>,
    );
    fireEvent.click(await screen.findByLabelText("Disable canvas animation"));
    expect(flags).toHaveBeenLastCalledWith(expect.objectContaining({ animate: false }));
    expect(screen.getByRole("heading", { level: 2, name: "Accessibility" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Keyboard shortcuts/ })).toHaveAttribute(
      "href",
      "/settings/hotkeys",
    );
  });
});

describe("engine flags binding and accessible panel", () => {
  it("bindEngineFlags forwards disable-canvas-animation to the real engine", async () => {
    const { createEngine } = await import("@candleviewer/chart-engine");
    const { bindEngineFlags } = await import("../../src/features/a11y-preferences");
    const ch = createEngineFlagsChannel();
    const engine = createEngine();
    const off = bindEngineFlags(engine, ch);
    ch.publish(resolveFlags({ ...DEFAULT_PREFERENCES, disable_canvas_animation: true }, "safe"));
    expect(engine.getFlags()).toEqual({
      animate: false,
      heatmapFade: false,
      inertia: false,
      flashOnTick: false,
    });
    off();
    engine.dispose();
  });

  it("AccessiblePanel defaults to the table when always_show_tables is on", async () => {
    const { AccessiblePanel } = await import("../../src/features/a11y-preferences");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(reply(200, { accessibility: { always_show_tables: true } })),
    );
    render(
      <PreferencesProvider>
        <AccessiblePanel
          title="Depth"
          chart={<span>chart-view</span>}
          table={<span>table-view</span>}
        />
      </PreferencesProvider>,
    );
    await waitFor(() => expect(screen.getByText("table-view")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Show chart" }));
    expect(screen.getByText("chart-view")).toBeInTheDocument();
  });
});
