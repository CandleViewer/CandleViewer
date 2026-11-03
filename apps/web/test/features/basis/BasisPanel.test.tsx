// E24-S08 (#783) slice 2: the basis panel by role: the retry band with the last successful time, the
// unavailable L/S row, the table alternative with all values and units, and axe over every story.
import { createRequire } from "node:module";
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createBasisAnalytics } from "../../../src/features/basis/analytics";
import { BasisPanel } from "../../../src/features/basis/ui/BasisPanel";
import * as stories from "../../../src/features/basis/ui/BasisPanel.stories";
import { ConnectedBasisPanel } from "../../../src/features/basis/ui/ConnectedBasisPanel";
import { useBasisFeed } from "../../../src/features/basis/useBasisFeed";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { fakeClient } from "../tape/fakeFeed";
import { recordedTickerItems, tickerSnap } from "./support/basisFixtures";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

async function serious(): Promise<string[]> {
  // jsdom has no canvas; contrast is the Storybook / Playwright axe run's
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);
}

const panel = () => screen.getByRole("region", { name: "Basis panel, BTCUSDT" });

afterEach(() => {
  act(() => setActiveClient(null));
});

describe("basis panel: states", () => {
  it("says the L/S ratio source is unavailable, with no series or timestamp", () => {
    render(stories.Populated.render());
    expect(within(panel()).getByText("L/S ratio · source unavailable")).toBeTruthy();
    expect(panel().querySelector("canvas, svg")).toBeNull();
  });

  it("shows the retry band with the last successful time and keeps the values", () => {
    render(stories.SourceFailed.render());
    // the visible title lives in the band; the polite region repeats it once, for the announcement
    const band = within(panel()).getByRole("group", { name: "Couldn't load basis" });
    expect(within(band).getByText("Couldn't load basis")).toBeTruthy();
    expect(within(band).getByText("Last loaded 09:14:02 UTC")).toBeTruthy();
    expect(within(band).getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(within(panel()).getByRole("status", { name: "Basis state" }).textContent).toBe(
      "Couldn't load basis",
    );
    expect(panel().textContent).toContain("82,782.37 USDT");
  });

  it("invents no timestamp when nothing ever loaded", () => {
    render(stories.FailedNeverLoaded.render());
    expect(within(panel()).getByRole("group", { name: "Couldn't load basis" })).toBeTruthy();
    expect(within(panel()).getByText("Nothing loaded yet.")).toBeTruthy();
    expect(panel().textContent).not.toContain("Last loaded");
  });

  it("calls retry and keeps focus in the panel", () => {
    const onRetry = vi.fn();
    render(
      <BasisPanel
        symbol="BTCUSDT"
        source="last"
        onSourceChange={() => undefined}
        onRetry={onRetry}
        snapshot={{
          feed: "revoked",
          source: { state: "failed", status: "revoked", lastSuccessAtMs: 1 },
          latest: null,
          stale: { tier: "fresh", ageMs: 0, lastTsMs: null },
        }}
      />,
    );
    const retry = within(panel()).getByRole("button", { name: "Retry" });
    retry.focus();
    fireEvent.click(retry);
    expect(document.activeElement).toBe(within(panel()).getByRole("heading", { name: "Basis" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("basis panel: the table alternative", () => {
  it("is hidden until asked and toggles with aria-expanded", () => {
    render(stories.Populated.render());
    const toggle = within(panel()).getByRole("button", { name: "Show table" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(within(panel()).queryByRole("table")).toBeNull();
    fireEvent.click(toggle);
    expect(within(panel()).getByRole("button", { name: "Hide table" })).toBeTruthy();
    expect(
      within(panel()).getByRole("table", { name: "Basis, BTCUSDT, latest values" }),
    ).toBeTruthy();
  });

  it("covers mark, index, basis, basis %, source and the ratio with units", () => {
    render(stories.TableOpen.render());
    const table = within(panel()).getByRole("table");
    const heads = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(heads).toEqual([
      "Time (UTC)",
      "Mark (USDT)",
      "Index (USDT)",
      "Basis (USDT)",
      "Basis %",
      "Source",
    ]);
    const cells = within(table).getAllByRole("row")[1]?.querySelectorAll("td");
    expect([...(cells ?? [])].map((c) => c.textContent)).toEqual([
      "2026-10-21 09:14:02",
      "82,751.20",
      "82,782.37",
      "−31.17",
      "−0.038 %",
      "last",
    ]);
    expect(within(table).getByText("L/S ratio · source unavailable")).toBeTruthy();
  });

  it("says so when there is no value yet", () => {
    render(stories.TableEmpty.render());
    expect(within(panel()).getByText("No basis values yet.")).toBeTruthy();
  });
});

describe("basis panel: connected", () => {
  const install = () => {
    const fake = fakeClient();
    act(() => setActiveClient(fake.client as unknown as WsClientHandle));
    return fake;
  };
  const clock = () => {
    const pending: (() => void)[] = [];
    return {
      clock: {
        raf: (cb: (t: number) => void) => (pending.push(() => cb(0)), pending.length),
        caf: () => undefined,
        now: () => 0,
        wallNow: () => 0,
      },
      run: () => act(() => pending.splice(0).forEach((cb) => cb())),
    };
  };

  it("subscribes on the active client, holds the source in memory and reports the toggle", () => {
    const fake = install();
    const c = clock();
    const report = vi.fn();
    render(
      <ConnectedBasisPanel
        symbol="BTCUSDT"
        paneId="p"
        clock={c.clock}
        analytics={createBasisAnalytics(report)}
      />,
    );
    expect(fake.specs[0]?.ch).toBe("ticker.BTCUSDT");
    expect(screen.getByRole("radio", { name: "last" }).getAttribute("aria-checked")).toBe("true");
    const item = recordedTickerItems()[0];
    if (item === undefined) throw new Error("fixture");
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("handle");
    handle.queue.push(tickerSnap([item]));
    handle.status = "live";
    c.run();
    expect(panel().textContent).toContain("82,782.37 USDT");
    fireEvent.click(screen.getByRole("radio", { name: "mark" }));
    expect(panel().textContent).toContain("basis, mark − index");
    expect(localStorage.length).toBe(0);
    expect(report).toHaveBeenCalledWith({ name: "basis.source_toggled", source: "mark" });
  });

  const snapOf = (failed: boolean) => ({
    feed: failed ? ("revoked" as const) : ("pending" as const),
    source: failed
      ? { state: "failed" as const, status: "revoked" as const, lastSuccessAtMs: 1 }
      : { state: "ok" as const },
    latest: null,
    stale: { tier: "fresh" as const, ageMs: 0, lastTsMs: null },
  });
  const ui = (failed: boolean, over: Record<string, unknown> = {}) => (
    <BasisPanel
      symbol="BTCUSDT"
      source="last"
      onSourceChange={() => undefined}
      onRetry={() => undefined}
      snapshot={snapOf(failed)}
      {...over}
    />
  );

  it("keeps one polite status region mounted before the failure and fills the same node", () => {
    const { rerender } = render(ui(false));
    const region = within(panel()).getByRole("status", { name: "Basis state" });
    expect(region?.textContent).toBe("");
    rerender(ui(true));
    const after = within(panel()).getByRole("status", { name: "Basis state" });
    expect(after).toBe(region);
    expect(after?.textContent).toBe("Couldn't load basis");
    rerender(ui(false));
    expect(within(panel()).getByRole("status", { name: "Basis state" })?.textContent).toBe("");
  });

  it("returns focus to the new Retry button when the retry fails again", () => {
    const { rerender } = render(ui(true));
    fireEvent.click(within(panel()).getByRole("button", { name: "Retry" }));
    expect(document.activeElement).toBe(within(panel()).getByRole("heading", { name: "Basis" }));
    rerender(ui(false)); // reloading: the band goes
    rerender(ui(true)); // failed again: a new band, a new button
    expect(document.activeElement).toBe(within(panel()).getByRole("button", { name: "Retry" }));
  });

  it("does not take focus back when the user moved on before the next failure", () => {
    const { rerender } = render(ui(true));
    fireEvent.click(within(panel()).getByRole("button", { name: "Retry" }));
    const toggle = within(panel()).getByRole("button", { name: "Show table" });
    toggle.focus(); // the heading blurs
    rerender(ui(false));
    rerender(ui(true));
    expect(document.activeElement).toBe(toggle);
  });

  it("takes its heading level from the host, default 3", () => {
    const { rerender } = render(ui(false));
    expect(within(panel()).getByRole("heading", { level: 3, name: "Basis" })).toBeTruthy();
    rerender(ui(false, { headingLevel: 4 }));
    expect(within(panel()).getByRole("heading", { level: 4, name: "Basis" })).toBeTruthy();
  });

  it("retries through the feed when the topic is revoked", () => {
    const fake = install();
    const c = clock();
    render(<ConnectedBasisPanel symbol="BTCUSDT" paneId="p" clock={c.clock} />);
    const handle = fake.handles[0];
    if (handle === undefined) throw new Error("handle");
    handle.status = "revoked";
    c.run();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(handle.release).toHaveBeenCalledTimes(1);
    expect(fake.handles).toHaveLength(2);
  });

  it("starts no feed for a non-USDT symbol or without a client", () => {
    const fake = install();
    const { result } = renderHook(() => useBasisFeed("BTCUSD", { paneId: "p" }));
    expect(result.current).toBeNull();
    expect(fake.client.consume).not.toHaveBeenCalled();
    act(() => setActiveClient(null));
    const none = renderHook(() => useBasisFeed("BTCUSDT", { paneId: "p" }));
    expect(none.result.current).toBeNull();
  });
});

describe("basis panel: accessibility", () => {
  it("has no serious axe violation in any story", { timeout: 30_000 }, async () => {
    for (const story of Object.values(stories).filter(
      (v): v is { render: () => ReactElement } =>
        typeof v === "object" && v !== null && "render" in v,
    )) {
      const { unmount } = render(story.render());
      expect(await serious()).toEqual([]);
      unmount();
    }
  });
});
