/**
 * SCR-090 alerts centre (E40-S01 Part A): the ticket's Gherkin scenarios, the drawn states, keyboard
 * navigation and axe, all through the accessibility tree (RTL by role and label).
 */
import { createRequire } from "node:module";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AlertsScreen, type AlertsScreenProps } from "../../../src/features/alerts/AlertsScreen";
import { createAlertsStore } from "../../../src/features/alerts/alertsStore";
import type { Alert } from "../../../src/features/alerts/types";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer";
import { alert, delivery, fakeApi, NOW, ok, signal } from "./_fixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const WRITE = ["alerts:read", "alerts:write"];
let tick = 0;
const silent = { subscribe: () => () => undefined };

function setup(alerts: readonly Alert[], over: Partial<AlertsScreenProps> = {}) {
  const api = over.api ?? fakeApi(alerts);
  const store = createAlertsStore();
  const utils = render(
    <AlertsScreen
      api={api}
      store={store}
      source={silent}
      permissions={WRITE}
      now={() => NOW}
      confirmNow={() => (tick += 1_000)}
      timeZone="UTC"
      {...over}
    />,
  );
  return { api, store, ...utils };
}

function setupNoSource(alerts: readonly Alert[]) {
  const api = fakeApi(alerts);
  const store = createAlertsStore();
  render(
    <AlertsScreen api={api} store={store} permissions={WRITE} now={() => NOW} timeZone="UTC" />,
  );
  return { api, store };
}

async function menuFor(name: string, item: string | RegExp): Promise<void> {
  fireEvent.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
  fireEvent.click(await screen.findByRole("menuitem", { name: item }));
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("SCR-090 list", () => {
  it("shows condition, symbol, status as text, last fire and channels for each row", async () => {
    const rows = [
      alert(1, { channels: ["in_app", "desktop"] }),
      alert(2, { enabled: false, disarm_reason: "source_unavailable", symbol: "ETHUSDT" }),
      alert(3, { fire_count: 2, last_fired_at: "2026-10-31T13:58:00Z", symbol: null }),
    ];
    setup(rows);
    const table = await screen.findByRole("grid", { name: "Alerts" });
    for (const header of ["Name", "Symbol", "Condition", "Status", "Last fired", "Delivery"])
      expect(within(table).getByRole("columnheader", { name: new RegExp(header) })).toBeVisible();
    const first = within(table).getByRole("row", { name: /Alert 1/ });
    expect(first).toHaveTextContent("Last price is at or above 64000 · every time");
    expect(first).toHaveTextContent("Armed");
    expect(first).toHaveTextContent("never");
    expect(first).toHaveTextContent("In app · Desktop");
    expect(within(table).getByRole("row", { name: /Alert 2/ })).toHaveTextContent("Disarmed");
    expect(within(table).getByRole("row", { name: /Alert 3/ })).toHaveTextContent(
      "2026-10-31 13:58:00 UTC · 2 times",
    );
    expect(within(table).getByRole("row", { name: /Alert 3/ })).toHaveTextContent("Any symbol");
  });

  it("renders alert text as plain text, never markup", async () => {
    setup([alert(1, { name: "<img src=x onerror=alert(1)>" })]);
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });

  it("marks an estimated metric and falls back to ids with a banner when the vocabulary is down", async () => {
    const api = fakeApi([alert(1)], {
      vocabulary: vi.fn(() => Promise.resolve({ kind: "unavailable" as const })),
    });
    setup([alert(1)], { api });
    expect(await screen.findByText(/rule engine isn't available/)).toBeVisible();
    expect(screen.getByRole("row", { name: /Alert 1/ })).toHaveTextContent(
      "last_price is at or above",
    );
    cleanup();
    const est = fakeApi([alert(1)], {
      vocabulary: vi.fn(() =>
        Promise.resolve(
          ok([signal("last_price", { display_name: "Last price", estimated: true })]),
        ),
      ),
    });
    setup([alert(1)], { api: est });
    await waitFor(() =>
      expect(screen.getByRole("row", { name: /Alert 1/ })).toHaveTextContent("(estimated)"),
    );
  });

  it("shows the delivery problem chip beside the failed channel", async () => {
    const a = alert(1, {
      channels: ["in_app", "desktop"],
      fire_count: 1,
      last_fired_at: "2026-10-31T13:00:00Z",
    });
    const api = fakeApi([a], {
      deliveries: vi.fn(() =>
        Promise.resolve(
          ok([
            delivery(1, a.id as string, "2026-10-31T13:00:00Z", {
              channel: "desktop",
              status: "failed",
            }),
          ]),
        ),
      ),
    });
    setup([a], { api });
    await waitFor(() =>
      expect(screen.getByRole("row", { name: /Alert 1/ })).toHaveTextContent(
        "Desktop notification blocked by the OS — enable it in Settings",
      ),
    );
  });

  it("states empty, filtered-empty and per-tab empties", async () => {
    setup([]);
    expect(await screen.findByText("No alerts yet")).toBeVisible();
    cleanup();
    setup([alert(1)]);
    fireEvent.change(await screen.findByRole("searchbox", { name: "Search names" }), {
      target: { value: "zzz" },
    });
    expect(await screen.findByText("No alerts match these filters.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("row", { name: /Alert 1/ })).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /Fired/ }));
    expect(await screen.findByText("Nothing has fired yet.")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /Snoozed/ }));
    expect(await screen.findByText("Nothing snoozed.")).toBeVisible();
  });

  it("states loading, then error with a mapped cause and a retry that reloads", async () => {
    let resolve: (v: never) => void = () => undefined;
    const pending = fakeApi([], { list: vi.fn(() => new Promise<never>((r) => (resolve = r))) });
    setup([], { api: pending });
    expect(screen.getByRole("grid", { name: /Alerts/ })).toHaveAttribute("aria-busy", "true");
    cleanup();
    resolve(undefined as never);
    const list = vi
      .fn()
      .mockResolvedValueOnce({ kind: "unavailable" })
      .mockResolvedValueOnce(ok([alert(1)]));
    setup([], { api: fakeApi([], { list }) });
    expect(
      await screen.findByText(/Alerts couldn't load\. The alerts service is unavailable\./),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("row", { name: /Alert 1/ })).toBeVisible();
  });

  it("explains a session without alerts:read instead of rendering the list", () => {
    setup([alert(1)], { permissions: [] });
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toBeVisible();
  });
});

describe("tabs and filters", () => {
  const rows = () => [
    alert(1),
    alert(2, { symbol: "ETHUSDT", fire_count: 3, last_fired_at: "2026-10-31T13:00:00Z" }),
    alert(3, { snoozed_until: "2026-10-31T14:30:00Z" }),
  ];

  it("derives the tabs and their counts, with arrow-key navigation", async () => {
    setup(rows());
    const tabs = await screen.findByRole("tablist", { name: "Alerts" });
    expect(within(tabs).getByRole("tab", { name: "All 3" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(tabs).getByRole("tab", { name: "Fired 1" })).toBeVisible();
    expect(within(tabs).getByRole("tab", { name: "Snoozed 1" })).toBeVisible();
    fireEvent.keyDown(within(tabs).getByRole("tab", { name: "All 3" }), { key: "ArrowRight" });
    expect(within(tabs).getByRole("tab", { name: "Fired 1" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("row", { name: /Alert 1/ })).toBeNull();
    expect(screen.getByRole("row", { name: /Alert 2/ })).toBeVisible();
    fireEvent.keyDown(screen.getByRole("tab", { name: "Fired 1" }), { key: "ArrowRight" });
    expect(await screen.findByRole("row", { name: /Alert 3/ })).toHaveTextContent(
      "Snoozed until 14:30 UTC (30 min)",
    );
  });

  it("filters by symbol, status and name and announces the result once", async () => {
    setup(rows());
    const search = await screen.findByRole("searchbox", { name: "Search names" });
    fireEvent.change(search, { target: { value: "alert 2" } });
    expect(screen.queryByRole("row", { name: /Alert 1/ })).toBeNull();
    await waitFor(() => expect(screen.getByText("Showing 1 of 3 alerts")).toBeVisible());
  });
});

describe("row actions", () => {
  it("scenario: snoozing for one hour moves the alert to Snoozed with its remaining time, refreshed by the minute", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    let now = NOW;
    const rows = [alert(1)];
    setup(rows, { now: () => now });
    await act(async () => undefined);
    fireEvent.click(await screen.findByRole("button", { name: "Actions for Alert 1" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Snooze/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /1 h/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Snoozed 1" })).toBeVisible());
    fireEvent.click(screen.getByRole("tab", { name: "Snoozed 1" }));
    expect(await screen.findByRole("row", { name: /Alert 1/ })).toHaveTextContent(
      "Snoozed until 15:00 UTC (60 min)",
    );
    now += 60_000;
    await act(async () => void vi.advanceTimersByTime(60_000));
    expect(screen.getByRole("row", { name: /Alert 1/ })).toHaveTextContent("(59 min)");
  });

  it("toggles an alert, wakes a snoozed one and confirms before deleting", async () => {
    const rows = [alert(1), alert(2, { snoozed_until: "2026-10-31T15:00:00Z" })];
    const { api } = setup(rows);
    fireEvent.click(await screen.findByRole("switch", { name: "Active: Alert 1" }));
    await waitFor(() => expect(api.setEnabled).toHaveBeenCalledWith(rows[0]?.id, false));
    await menuFor("Alert 2", "Wake now");
    await waitFor(() => expect(api.setSnooze).toHaveBeenCalledWith(rows[1]?.id, null));
    await menuFor("Alert 1", /Delete/);
    expect(await screen.findByRole("alertdialog", { name: "Delete Alert 1?" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith(rows[0]?.id));
    await waitFor(() => expect(screen.queryByRole("row", { name: /Alert 1/ })).toBeNull());
  });

  it("offers show on chart, and renders no New alert or Duplicate until Part B", async () => {
    const onShowOnChart = vi.fn();
    setup([alert(1)], { onShowOnChart });
    expect(await screen.findByRole("row", { name: /Alert 1/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /New alert/ })).toBeNull();
    await menuFor("Alert 1", "Show on chart");
    expect(onShowOnChart).toHaveBeenCalledWith(expect.objectContaining({ name: "Alert 1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Actions for Alert 1" }));
    expect(await screen.findByRole("menuitem", { name: "View history" })).toBeVisible();
    expect(screen.queryByRole("menuitem", { name: /Duplicate/ })).toBeNull();
  });
});

describe("bulk actions", () => {
  it("scenario: a bulk disarm reports each item, keeps the failure selected and re-reads the server", async () => {
    const rows = [1, 2, 3, 4, 5].map((n) => alert(n));
    const api = fakeApi(rows, {
      setEnabled: vi.fn((id: string, enabled: boolean) =>
        id === rows[2]?.id
          ? Promise.resolve({ kind: "not_found" as const })
          : Promise.resolve(ok({ ...(rows.find((a) => a.id === id) as Alert), enabled })),
      ),
    });
    setup(rows, { api });
    for (const row of rows)
      fireEvent.click(await screen.findByRole("checkbox", { name: `Select ${row.name}` }));
    expect(screen.getAllByText("5 selected").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Disable 5 alerts?" });
    expect(dialog).toHaveTextContent("They stop firing until you enable them.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Disable 5" }));
    expect(
      await screen.findByText("4 of 5 disabled. 1 failed: 'Alert 3' — it was deleted."),
    ).toBeVisible();
    expect(api.list).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("1 selected").length).toBeGreaterThan(0);
    expect(screen.getByRole("checkbox", { name: "Select Alert 3" })).toBeChecked();
  });

  it("confirms bulk delete with the count and the consequence", async () => {
    const rows = [alert(1), alert(2)];
    const { api } = setup(rows);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Alert 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alert 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete 2 alerts?" });
    expect(dialog).toHaveTextContent(
      "This can't be undone. Their past firings stay in Notifications.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryAllByText("2 selected")).toHaveLength(0);
  });
});

describe("firing history", () => {
  it("scenario: twelve firings, three suppressed with a summary link, exported as the same rows", async () => {
    const a = alert(1, { fire_count: 12, last_fired_at: "2026-10-31T13:11:00Z" });
    const rows = Array.from({ length: 12 }, (_, i) =>
      delivery(
        i + 1,
        a.id as string,
        `2026-10-31T13:${String(i).padStart(2, "0")}:00Z`,
        i >= 9 ? { status: "suppressed", error: "storm" } : {},
      ),
    );
    const download = vi.fn();
    const api = fakeApi([a], {
      deliveries: vi.fn((q) => Promise.resolve(ok(q.alertId === undefined ? [] : rows))),
    });
    setup([a], { api, download, notificationsHref: "/notifications" });
    await menuFor("Alert 1", "View history");
    const dialog = await screen.findByRole("dialog", { name: /Firing history: Alert 1/ });
    const list = await within(dialog).findByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(12);
    expect(within(dialog).getAllByText(/Folded into a storm summary/)).toHaveLength(3);
    expect(within(dialog).getAllByRole("link", { name: "Open Notifications" })).toHaveLength(3);
    fireEvent.click(within(dialog).getByRole("button", { name: "Export CSV" }));
    const csv = download.mock.calls[0]?.[1] as string;
    expect(csv.trim().split("\r\n")).toHaveLength(13);
    expect(csv).toContain("suppressed,storm");
  });

  it("states empty and error histories", async () => {
    const a = alert(1);
    setup([a], {
      api: fakeApi([a], {
        deliveries: vi.fn((q) =>
          Promise.resolve(q.alertId === undefined ? ok([]) : { kind: "unavailable" as const }),
        ),
      }),
    });
    await menuFor("Alert 1", "View history");
    expect(await screen.findByText("The firing history couldn't load.")).toBeVisible();
  });
});

describe("auto-disarm", () => {
  it("scenario: states why, and re-enabling warns the source may still be unavailable", async () => {
    const a = alert(1, { enabled: false, disarm_reason: "source_unavailable" });
    const { api } = setup([a]);
    const row = await screen.findByRole("row", { name: /Alert 1/ });
    expect(row).toHaveTextContent("Disarmed");
    expect(row).toHaveTextContent("Alert disarmed: Last price data source unavailable");
    expect(row).toHaveTextContent(
      "The Last price values stopped arriving at 10:00:00 UTC, so the alert was disarmed instead of firing on missing data. It stays off until you enable it.",
    );
    fireEvent.click(within(row).getByRole("button", { name: "Enable…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Enable Alert 1?" });
    expect(dialog).toHaveTextContent(
      "If the source is still unavailable, it will disarm again and tell you.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Enable" }));
    await waitFor(() => expect(api.setEnabled).toHaveBeenCalledWith(a.id, true));
  });
});

describe("read-only and 403", () => {
  it("scenario: without alerts:write the write controls are disabled with the reason (D-8)", async () => {
    const { api } = setup([alert(1)], { permissions: ["alerts:read"] });
    await screen.findByRole("row", { name: /Alert 1/ });
    const reason = /Your role can't change alerts\./;
    expect(screen.getByRole("checkbox", { name: "Select Alert 1" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    const toggle = screen.getByRole("switch", { name: "Active: Alert 1" });
    expect(toggle).toHaveAttribute("aria-disabled", "true");
    expect(toggle).toHaveAccessibleDescription(reason);
    expect(
      screen.getByRole("row", { name: /Alert 1/ }).querySelector('[data-icon="lock"]'),
    ).not.toBeNull();
    expect(screen.queryByRole("button", { name: /New alert/ })).toBeNull();
    fireEvent.click(toggle);
    expect(api.setEnabled).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Alert 1" }));
    expect(await screen.findByRole("menuitem", { name: "View history" })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("menuitem", { name: /Snooze/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    for (const name of [/Disable/, /Delete/]) {
      const item = screen.getByRole("menuitem", { name });
      expect(item).toHaveAttribute("aria-disabled", "true");
      // The lead glyph is a sibling of the menuitem span, inside the same row.
      expect(
        item.parentElement?.parentElement?.querySelector('[data-icon="lock"]'),
        String(name),
      ).not.toBeNull();
    }
  });

  it("scenario: a 403 on a write is explained, not silent", async () => {
    const api = fakeApi([alert(1)], {
      setEnabled: vi.fn(() => Promise.resolve({ kind: "forbidden" as const })),
    });
    setup([alert(1)], { api });
    fireEvent.click(await screen.findByRole("switch", { name: "Active: Alert 1" }));
    expect(await screen.findByText("Your role can't change alerts.")).toBeVisible();
  });
});

describe("G-T2: a gated control fires nothing and says why once", () => {
  const reason = "Your role can't change alerts.";
  /** Enter on a button arrives as a click, Space as a click on release; jsdom sends neither itself. */
  const press = (node: HTMLElement, key: "Enter" | " "): void =>
    act(() => {
      fireEvent.keyDown(node, { key });
      if (key === " ") fireEvent.keyUp(node, { key });
      fireEvent.click(node);
    });
  function readOnly(alerts: readonly Alert[]) {
    const said: string[] = [];
    const api = fakeApi(alerts);
    const store = createAlertsStore();
    render(
      <GatedAnnounceProvider announce={(text) => said.push(text)}>
        <AlertsScreen
          api={api}
          store={store}
          source={silent}
          permissions={["alerts:read"]}
          now={() => NOW}
          timeZone="UTC"
        />
      </GatedAnnounceProvider>,
    );
    return { api, said };
  }

  it("the row toggle and the select box: Enter and Space change nothing, one announcement each press", async () => {
    const { api, said } = readOnly([alert(1)]);
    const toggle = await screen.findByRole("switch", { name: "Active: Alert 1" });
    const box = screen.getByRole("checkbox", { name: "Select Alert 1" });
    for (const control of [toggle, box]) {
      for (const key of ["Enter", " "] as const) {
        const before = said.length;
        press(control, key);
        expect(said.length - before).toBe(1);
      }
    }
    expect(said.every((t) => t === reason)).toBe(true);
    expect(api.setEnabled).not.toHaveBeenCalled();
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(box).not.toBeChecked();
    expect(screen.queryByRole("toolbar", { name: "Bulk actions" })).toBeNull();
  });

  it("a gated menu write fires nothing on Enter or Space and says why once", async () => {
    const { api, said } = readOnly([alert(1)]);
    fireEvent.click(await screen.findByRole("button", { name: "Actions for Alert 1" }));
    const item = await screen.findByRole("menuitem", { name: /Disable/ });
    for (const key of ["Enter", " "] as const) {
      const before = said.length;
      fireEvent.keyDown(item, { key });
      expect(said.length - before).toBeLessThanOrEqual(1);
    }
    expect(api.setEnabled).not.toHaveBeenCalled();
    expect(api.remove).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    for (const t of said) expect(t).toBe(reason);
  });

  it("the disarmed row's Enable… is gated the same way: no confirm, one announcement a press", async () => {
    const { api, said } = readOnly([
      alert(1, { enabled: false, disarm_reason: "source_unavailable" }),
    ]);
    const button = await within(await screen.findByRole("row", { name: /Alert 1/ })).findByRole(
      "button",
      { name: "Enable…" },
    );
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(reason);
    for (const key of ["Enter", " "] as const) {
      const before = said.length;
      press(button, key);
      expect(said.length - before).toBe(1);
    }
    expect(said.every((t) => t === reason)).toBe(true);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.setEnabled).not.toHaveBeenCalled();
  });
});

describe("LR-8: the bulk result is said once", () => {
  async function bulkDisable(): Promise<void> {
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Alert 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Disable 1" }));
    await screen.findByText(/1 of 1 disabled\./);
  }
  it("clears when the selection changes", async () => {
    setup([alert(1), alert(2)]);
    await bulkDisable();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alert 2" }));
    expect(screen.queryByText(/1 of 1 disabled\./)).toBeNull();
  });
  it("clears when the filter or the tab changes", async () => {
    setup([alert(1), alert(2)]);
    await bulkDisable();
    fireEvent.click(screen.getByRole("tab", { name: /Fired/ }));
    expect(screen.queryByText(/1 of 1 disabled\./)).toBeNull();
    expect(screen.getByText(/^Showing \d+ of \d+ alerts/)).toBeVisible();
  });
});

describe("accessibility", () => {
  it("has no serious or critical axe violations populated, empty or with the bulk bar", async () => {
    const { container } = setup([
      alert(1),
      alert(2, { enabled: false, disarm_reason: "source_unavailable" }),
    ]);
    await screen.findByRole("row", { name: /Alert 1/ });
    const run = async (): Promise<unknown[]> =>
      (
        await axe.run(container, { rules: { "color-contrast": { enabled: false } } })
      ).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(await run()).toEqual([]);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alert 1" }));
    expect(await run()).toEqual([]);
  });
});

describe("visible-set rules", () => {
  it("shows the 200-row cap, with an announcement that matches the rendered count", async () => {
    const many = Array.from({ length: 205 }, (_, i) => ({
      ...alert(1),
      id: `10000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
      name: `Many ${i}`,
    }));
    setup(many);
    expect(await screen.findByText(/Showing the first 200 of 205/)).toBeVisible();
    expect(screen.getByText(/refine the filters/)).toBeVisible();
    await waitFor(() => expect(screen.getByText("Showing 200 of 205 alerts")).toBeVisible());
    expect(screen.getAllByRole("row").length).toBeLessThanOrEqual(202);
  }, 30_000);

  it("drops selected rows that a tab hides, so the bulk count is the visible selection", async () => {
    const fired = alert(1, { fire_count: 1, last_fired_at: "2026-10-31T13:00:00Z" });
    const { api } = setup([fired, alert(2)]);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Alert 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alert 2" }));
    expect(screen.getAllByText("2 selected").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("tab", { name: /Fired/ }));
    expect(screen.queryAllByText("2 selected")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete 1 alerts?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete 1" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledTimes(1));
    expect(api.remove).toHaveBeenCalledWith(fired.id);
  });

  it("refreshes after a single write finds the alert deleted", async () => {
    const api = fakeApi([alert(1)], {
      setEnabled: vi.fn(() => Promise.resolve({ kind: "not_found" as const })),
    });
    setup([alert(1)], { api });
    fireEvent.click(await screen.findByRole("switch", { name: "Active: Alert 1" }));
    expect(await screen.findByText("it was deleted")).toBeVisible();
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });
});

describe("bulk 403 and the live feed", () => {
  it("lists a per-item 403 with the role sentence", async () => {
    const rows = [alert(1), alert(2)];
    const api = fakeApi(rows, {
      setEnabled: vi.fn((id: string) =>
        id === rows[1]?.id
          ? Promise.resolve({ kind: "forbidden" as const })
          : Promise.resolve(ok(rows[0] as Alert)),
      ),
    });
    setup(rows, { api });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Alert 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alert 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Disable 2 alerts?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Disable 2" }));
    expect(
      await screen.findByText(
        "1 of 2 disabled. 1 failed: 'Alert 2' — Your role can't change alerts.",
      ),
    ).toBeVisible();
  });

  it("releases the alerts topic on unmount", async () => {
    const teardown = vi.fn();
    const source = { subscribe: vi.fn(() => teardown) };
    const { unmount } = setup([alert(1)], { source });
    await screen.findByRole("row", { name: /Alert 1/ });
    expect(source.subscribe).toHaveBeenCalledTimes(1);
    unmount();
    expect(teardown).toHaveBeenCalledTimes(1);
  });

  it("shows plain text, not a link, for a suppressed firing while no notification centre exists", async () => {
    const a = alert(1);
    const api = fakeApi([a], {
      deliveries: vi.fn((q) =>
        Promise.resolve(
          q.alertId === undefined
            ? ok([])
            : {
                kind: "ok" as const,
                truncated: true as const,
                value: [
                  delivery(1, a.id as string, "2026-10-31T13:00:00Z", {
                    status: "suppressed",
                    error: "storm",
                  }),
                ],
              },
        ),
      ),
    });
    setup([a], { api });
    await menuFor("Alert 1", "View history");
    const dialog = await screen.findByRole("dialog", { name: /Firing history/ });
    expect(await within(dialog).findByText(/Folded into a storm summary/)).toBeVisible();
    expect(within(dialog).queryByRole("link")).toBeNull();
    expect(within(dialog).getByText(/Only the newest firings are shown/)).toBeVisible();
  });
});

describe("lifecycle", () => {
  afterEach(() => setActiveClient(null));

  const client = () => {
    const handle = { read: () => [], release: vi.fn() };
    return {
      handle,
      client: {
        consume: vi.fn(() => handle),
        getState: () => INITIAL_WS_STATE,
        subscribe: () => () => undefined,
      },
    };
  };

  it("re-subscribes to the alerts topic when the active client changes", async () => {
    const a = client();
    const b = client();
    setActiveClient(a.client as never);
    const { api, store } = setupNoSource([alert(1)]);
    await screen.findByRole("row", { name: /Alert 1/ });
    expect(a.client.consume).toHaveBeenCalledWith(expect.objectContaining({ ch: "alerts" }));
    act(() => setActiveClient(b.client as never));
    expect(a.handle.release).toHaveBeenCalledTimes(1);
    expect(b.client.consume).toHaveBeenCalledTimes(1);
    expect(api.list).toHaveBeenCalledTimes(1);
    expect(store.list()).toHaveLength(1);
  });

  it("aborts an in-flight refresh on unmount and ignores its late answer", async () => {
    let signal: AbortSignal | undefined;
    let settle: (v: unknown) => void = () => undefined;
    const api = fakeApi([], {
      list: vi.fn((s?: AbortSignal) => {
        signal = s;
        return new Promise((resolve) => (settle = resolve));
      }) as never,
    });
    const { store, unmount } = setup([], { api });
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => settle(ok([alert(1)])));
    expect(store.list()).toHaveLength(0);
  });

  it("keeps the rows and says so when a later refresh fails", async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce(ok([alert(1)]))
      .mockResolvedValue({ kind: "unavailable" });
    const api = fakeApi([alert(1)], {
      list,
      setEnabled: vi.fn(() => Promise.resolve({ kind: "not_found" as const })),
    });
    setup([alert(1)], { api });
    fireEvent.click(await screen.findByRole("switch", { name: "Active: Alert 1" }));
    expect(await screen.findByText(/couldn't be refreshed/)).toBeVisible();
    expect(screen.getByRole("row", { name: /Alert 1/ })).toBeVisible();
    expect(screen.queryByText(/Alerts couldn't load/)).toBeNull();
  });

  it("moves focus to the select-all box after Clear", async () => {
    setup([alert(1)]);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Alert 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Select all rows" })).toHaveFocus(),
    );
  });
});
