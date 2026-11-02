/**
 * E16-S01 PR 3, Keep forever and a retention change (E16-D02 §6.4, §6.7, §12; E16-D06 KB-07, FM-04, SD-02, SD-03,
 * §16.4 rows 5 and 6; frozen rows (i) and (iii)) through the grid and its row detail, over a stubbed `apiFetch`
 * (no network, C-13.5); and the accelerated Retention cell (D02 §2, §3 `paused`).
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import type { FilterBarFilter } from "@candleviewer/ui";
import { rowData, type GridSort } from "../../../src/features/recorder/grid";
import type { RecordedSymbol, RecorderRow } from "../../../src/features/recorder/model";
import {
  RecorderGrid,
  type GridWrite,
  type RecorderGridProps,
} from "../../../src/features/recorder/RecorderGrid";
import { problem, stepUpRequired } from "./fixtures";
import { CONTEXT, D02_ROWS, NOW, row } from "./gridFixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
/** The writes sent, in order (the coverage reads left out). */
const writes = () =>
  apiFetch.mock.calls
    .filter(([, init]) => (init?.method ?? "GET") !== "GET")
    .map(([url, init]) => ({
      url,
      method: init?.method,
      body: typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined,
      idemp: new Headers(init?.headers).get("Idempotency-Key"),
    }));
const settle = () => act(async () => void (await Promise.resolve()));
const settleAll = async (): Promise<void> => {
  for (let i = 0; i < 4; i += 1) await settle();
};
/** CMP-044's guard ignores a press in its first 400 ms (E30-D03 D3 (2)). */
const pastGuard = () => act(() => void vi.advanceTimersByTime(500));
const press = (control: HTMLElement): void => {
  act(() => control.focus());
  fireEvent.click(control);
};
const type = (field: HTMLElement, value: string): void =>
  void fireEvent.change(field, { target: { value } });

/** BTCUSDT's one stream, recorded since 1 Aug: the estimate's coverage (illustrative, D02 §6.4). */
const COVERAGE = {
  symbol: "BTCUSDT",
  streams: [
    {
      stream: "trades",
      intervals: [
        { from: "2026-08-01T00:00:00Z", to: "2026-09-14T10:00:00Z", rows: 1_000, tier: "parquet" },
      ],
      gaps: [],
    },
  ],
};
const answered = (row: Partial<RecordedSymbol> & { symbol: string }): RecordedSymbol => ({
  id: `id-${row.symbol.toLowerCase()}`,
  reason: "manual",
  state: "recording",
  ...row,
});

/** Answers the coverage reads, then the writes in `replies`' order. */
function route(...replies: Response[]): void {
  apiFetch.mockImplementation(async (url, init) => {
    if ((init?.method ?? "GET") === "GET" && url.includes("/market/data-coverage")) {
      return json(200, COVERAGE);
    }
    return replies.shift() ?? json(500, problem(500, "internal_error"));
  });
}

interface HarnessProps extends Partial<Omit<RecorderGridProps, "rows">> {
  readonly rows?: readonly RecorderRow[];
}

function Harness({ rows = D02_ROWS, ...props }: HarnessProps): JSX.Element {
  const [filters, setFilters] = useState<readonly FilterBarFilter[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<GridSort | undefined>(undefined);
  const [detail, setDetail] = useState<string | null>(null);
  return (
    <RecorderGrid
      rows={rows}
      context={CONTEXT}
      listed={new Map()}
      frameAtMs={NOW}
      filters={filters}
      onFiltersChange={setFilters}
      query={query}
      onQueryChange={setQuery}
      sort={sort}
      onSortChange={setSort}
      say={() => undefined}
      readBack={() => undefined}
      onOpenDetail={setDetail}
      detail={detail}
      onDetailClose={() => setDetail(null)}
      {...props}
    />
  );
}

/** A first mount transforms the screen's whole module graph: slow under load, never a flake (C-9.3). */
const CASE = { timeout: 30_000 } as const;
const confirmDialog = (name: string): HTMLElement => screen.getByRole("alertdialog", { name });

let reported: unknown[] = [];
const onAnalytics = (event: Event): void => void reported.push((event as CustomEvent).detail);
const scroll = Element.prototype.scrollIntoView;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "performance"], now: NOW });
  Element.prototype.scrollIntoView = vi.fn();
  reported = [];
  window.addEventListener("cv:analytics", onAnalytics);
});
afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  Element.prototype.scrollIntoView = scroll;
  apiFetch.mockReset();
  vi.useRealTimers();
});

describe("Keep forever (E16-D02 §6.4; KB-07, SD-02, SD-03)", CASE, () => {
  it("on: the switch opens the typed confirm on Cancel; Confirm keeps the validity look until the symbol is typed", async () => {
    const written: GridWrite[] = [];
    route(json(200, answered({ symbol: "ETHUSDT", pinned: true, retention_days: null })));
    render(<Harness onWritten={(write) => written.push(write)} />);
    const toggle = screen.getByRole("switch", { name: "Keep ETHUSDT data forever" });
    press(toggle);
    const dialog = confirmDialog("Keep ETHUSDT data forever?");
    expect(dialog).toHaveAccessibleDescription(
      "Retention is removed and nothing is deleted automatically. Type ETHUSDT to confirm.",
    );
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    const confirm = within(dialog).getByRole("button", { name: "Keep ETHUSDT data forever" });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAccessibleDescription("Type ETHUSDT exactly to confirm.");
    expect(dialog).toHaveTextContent("You'll confirm with your password and a code.");
    expect(dialog).toHaveTextContent("This action is audited.");
    const field = within(dialog).getByRole("textbox", { name: "Type ETHUSDT to confirm" });
    expect(field).toHaveValue("");
    pastGuard();
    press(confirm);
    expect(fireEvent.keyDown(field, { key: "Enter" })).toBe(false);
    expect(writes()).toEqual([]);
    type(field, "ETHUSDT");
    pastGuard();
    press(confirm);
    await settleAll();
    expect(writes()).toEqual([
      {
        url: "/api/v1/recording/symbols/id-ethusdt/pin",
        method: "PUT",
        body: { pinned: true },
        idemp: expect.any(String),
      },
    ]);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(toggle).toHaveFocus();
    expect(written).toEqual([{ kind: "updated", row: expect.objectContaining({ pinned: true }) }]);
    expect(reported).toEqual([{ name: "recorder.pin_toggled", symbol: "ETHUSDT", pinned: true }]);
  });

  it("off: destructive, it states about how much becomes eligible and from when; the default retention is sent", async () => {
    route(json(200, answered({ symbol: "BTCUSDT", pinned: false, retention_days: 30 })));
    render(<Harness />);
    press(screen.getByRole("switch", { name: "Keep BTCUSDT data forever" }));
    await settleAll();
    const dialog = confirmDialog("Stop keeping BTCUSDT forever?");
    // 1 000 rows from 1 Aug to 14 Sep, of 34.8 GB: the share before 15 Aug 10:31 (C-5: an estimate).
    expect(dialog).toHaveAccessibleDescription(
      "Retention returns to 30 days, so about 11.3 GB recorded before 2026-08-15 becomes eligible for deletion at the next retention run. Type BTCUSDT to confirm.",
    );
    const confirm = within(dialog).getByRole("button", { name: "Stop keeping BTCUSDT forever" });
    expect(confirm).toHaveAttribute("data-variant", "danger");
    type(within(dialog).getByRole("textbox", { name: "Type BTCUSDT to confirm" }), "BTCUSDT");
    pastGuard();
    press(confirm);
    await settleAll();
    expect(writes()).toMatchObject([
      { method: "PUT", body: { pinned: false, retention_days: 30 } },
    ]);
    expect(reported).toEqual([{ name: "recorder.pin_toggled", symbol: "BTCUSDT", pinned: false }]);
  });

  it("the recorder step-up: Esc leaves Not sent, the symbol kept and focus on Confirm; a grant re-sends once with the key", async () => {
    route(
      json(403, stepUpRequired),
      json(403, stepUpRequired),
      json(200, { action_class: "recorder" }),
      json(200, answered({ symbol: "ETHUSDT", pinned: true })),
    );
    render(<Harness />);
    press(screen.getByRole("switch", { name: "Keep ETHUSDT data forever" }));
    const dialog = confirmDialog("Keep ETHUSDT data forever?");
    const field = within(dialog).getByRole("textbox", { name: "Type ETHUSDT to confirm" });
    type(field, "ETHUSDT");
    pastGuard();
    const confirm = within(dialog).getByRole("button", { name: "Keep ETHUSDT data forever" });
    press(confirm);
    await settleAll();
    let challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.keyDown(within(challenge).getByLabelText("Password"), { key: "Escape" });
    expect(screen.queryByRole("alertdialog", { name: "Confirm with two-factor" })).toBeNull();
    expect(dialog).toHaveTextContent("Not sent");
    expect(field).toHaveValue("ETHUSDT");
    expect(confirm).toHaveFocus();
    // Pressed again: a new request (a new key), challenged, granted, then re-sent unchanged.
    pastGuard();
    press(confirm);
    await settleAll();
    challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.change(within(challenge).getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(within(challenge).getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(within(challenge).getByRole("button", { name: "Confirm" }));
    await settleAll();
    const sent = writes().filter((w) => w.url?.endsWith("/pin"));
    expect(sent).toHaveLength(3);
    expect(sent[0]?.idemp).not.toBe(sent[1]?.idemp);
    expect(sent[2]?.idemp).toBe(sent[1]?.idemp);
    expect(sent[2]?.body).toEqual(sent[1]?.body);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("a server refusal is the T4 at the confirm with its code (frozen row (i)); nothing else changes", async () => {
    route(json(403, problem(403, "forbidden", { detail: "server detail" })));
    const written: GridWrite[] = [];
    render(<Harness onWritten={(write) => written.push(write)} />);
    press(screen.getByRole("switch", { name: "Keep ETHUSDT data forever" }));
    const dialog = confirmDialog("Keep ETHUSDT data forever?");
    type(within(dialog).getByRole("textbox", { name: "Type ETHUSDT to confirm" }), "ETHUSDT");
    pastGuard();
    press(within(dialog).getByRole("button", { name: "Keep ETHUSDT data forever" }));
    await settleAll();
    expect(dialog).toHaveTextContent("Not changed: the server refused it. (forbidden)");
    expect(dialog).not.toHaveTextContent("server detail");
    expect(written).toEqual([]);
    expect(reported).toEqual([]);
  });

  it("has no serious axe violation, open", { timeout: 20_000 }, async () => {
    route();
    render(<Harness />);
    press(screen.getByRole("switch", { name: "Keep ETHUSDT data forever" }));
    vi.useRealTimers();
    const res = await axe.run(confirmDialog("Keep ETHUSDT data forever?"), {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

describe("Retention from the row detail (E16-D02 §6.4, §6.7)", CASE, () => {
  function choose(symbol: string, option: string): void {
    press(screen.getByRole("button", { name: symbol }));
    const dialog = screen.getByRole("dialog", { name: `${symbol} recording` });
    fireEvent.click(within(dialog).getByRole("combobox", { name: "Retention" }));
    fireEvent.click(screen.getByRole("option", { name: option }));
  }

  it("shortening states what becomes eligible and sends retention_days alone", async () => {
    route(json(200, answered({ symbol: "ETHUSDT", retention_days: 7 })));
    render(<Harness />);
    choose("ETHUSDT", "7 days");
    await settleAll();
    const dialog = confirmDialog("Shorten ETHUSDT retention to 7 days?");
    expect(dialog).toHaveAccessibleDescription(
      /^Retention becomes 7 days, so about .+ recorded before 2026-09-07 becomes eligible for deletion at the next retention run\. Type ETHUSDT to confirm\.$/,
    );
    type(within(dialog).getByRole("textbox", { name: "Type ETHUSDT to confirm" }), "ETHUSDT");
    pastGuard();
    press(within(dialog).getByRole("button", { name: "Shorten retention to 7 days" }));
    await settleAll();
    expect(writes()).toMatchObject([
      { url: "/api/v1/recording/symbols/id-ethusdt", method: "PATCH", body: { retention_days: 7 } },
    ]);
  });

  it("lengthening deletes nothing: its confirm says so, no estimate is read", () => {
    route();
    render(<Harness />);
    choose("ETHUSDT", "90 days");
    const dialog = confirmDialog("Lengthen ETHUSDT retention to 90 days?");
    expect(dialog).toHaveAccessibleDescription(
      "Retention becomes 90 days, and nothing is deleted. Type ETHUSDT to confirm.",
    );
    expect(
      within(dialog).getByRole("button", { name: "Lengthen retention to 90 days" }),
    ).toHaveAttribute("data-variant", "primary");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("a pinned row's choice unpins it to that retention", async () => {
    route(json(200, answered({ symbol: "BTCUSDT", pinned: false, retention_days: 90 })));
    render(<Harness />);
    choose("BTCUSDT", "90 days");
    await settleAll();
    const dialog = confirmDialog("Stop keeping BTCUSDT forever?");
    expect(dialog).toHaveAccessibleDescription(/^Retention returns to 90 days, so about /);
    type(within(dialog).getByRole("textbox", { name: "Type BTCUSDT to confirm" }), "BTCUSDT");
    pastGuard();
    press(within(dialog).getByRole("button", { name: "Stop keeping BTCUSDT forever" }));
    await settleAll();
    expect(writes()).toMatchObject([
      { method: "PUT", body: { pinned: false, retention_days: 90 } },
    ]);
  });

  it("Custom… shows only with SCR-141 registered and opens it without a confirm (BQ-11)", () => {
    route();
    const custom = vi.fn();
    const view = render(<Harness />);
    press(screen.getByRole("button", { name: "ETHUSDT" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Retention" }));
    expect(screen.queryByRole("option", { name: "Custom…" })).toBeNull();
    view.unmount();
    render(<Harness onCustomRetention={custom} />);
    choose("ETHUSDT", "Custom…");
    expect(custom).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("accelerated retention in the grid (E16-D02 §2, §3 paused)", CASE, () => {
  it("an unpinned row reads its halved retention while accelerate_retention holds; a pinned row stays Forever", () => {
    const [btc, eth] = D02_ROWS;
    const ctx = { ...CONTEXT, accelerated: true };
    expect(rowData(eth as RecorderRow, ctx)?.retentionAcceleratedDays).toBe(15);
    expect(rowData(btc as RecorderRow, ctx)?.retentionAcceleratedDays).toBeNull();
    expect(rowData(eth as RecorderRow, CONTEXT)?.retentionAcceleratedDays).toBeNull();
    render(<Harness context={ctx} />);
    expect(screen.getByRole("row", { name: /^ETHUSDT/ })).toHaveTextContent(
      "30 d → 15 d (accelerated)",
    );
    expect(screen.getByRole("row", { name: /^BTCUSDT/ })).toHaveTextContent("Forever");
  });
});

describe(
  "a confirm keeps its view on the wire and hands focus on (S-5353-01, H22; A-5347-03, FM-02, FM-04)",
  CASE,
  () => {
    /** ADAUSDT stopped and kept forever: unpinning it lets the server drop the row (`22`). */
    const ROWS = D02_ROWS.map((r) =>
      r.symbol === "ADAUSDT" ? { ...r, pinned: true, retentionDays: null } : r,
    );
    const UNPINNED = answered({
      symbol: "ADAUSDT",
      state: "stopped",
      pinned: false,
      retention_days: 30,
    });

    it("Esc and Cancel while its PUT is on the wire keep the confirm; the answer closes it, focus on the switch", async () => {
      let release: (response: Response) => void = () => undefined;
      apiFetch.mockImplementation(async (url, init) => {
        if ((init?.method ?? "GET") === "GET") return json(200, COVERAGE);
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      });
      render(<Harness />);
      const toggle = screen.getByRole("switch", { name: "Keep ETHUSDT data forever" });
      press(toggle);
      const dialog = confirmDialog("Keep ETHUSDT data forever?");
      type(within(dialog).getByRole("textbox", { name: "Type ETHUSDT to confirm" }), "ETHUSDT");
      pastGuard();
      press(within(dialog).getByRole("button", { name: "Keep ETHUSDT data forever" }));
      await settleAll();
      fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
      press(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(confirmDialog("Keep ETHUSDT data forever?")).toBeInTheDocument();
      release(json(200, answered({ symbol: "ETHUSDT", pinned: true, retention_days: null })));
      await settleAll();
      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(toggle).toHaveFocus();
    });

    it("its row gone from the grid while it was open, the answer hands focus to the grid's next row, never body", async () => {
      route(json(200, UNPINNED));
      const view = render(<Harness rows={ROWS} />);
      press(screen.getByRole("switch", { name: "Keep ADAUSDT data forever" }));
      await settleAll();
      const dialog = confirmDialog("Stop keeping ADAUSDT forever?");
      type(within(dialog).getByRole("textbox", { name: "Type ADAUSDT to confirm" }), "ADAUSDT");
      view.rerender(<Harness rows={ROWS.filter((r) => r.symbol !== "ADAUSDT")} />);
      pastGuard();
      press(within(dialog).getByRole("button", { name: "Stop keeping ADAUSDT forever" }));
      await settleAll();
      expect(screen.queryByRole("alertdialog")).toBeNull();
      const now = document.activeElement;
      expect(now).not.toBe(document.body);
      expect(now?.closest("table")).not.toBeNull();
    });

    it("from the drawer, its switch gone with the row's controls: focus lands on the drawer's heading", async () => {
      route(json(200, UNPINNED));
      const view = render(<Harness rows={ROWS} />);
      press(screen.getByRole("button", { name: "ADAUSDT" }));
      const drawer = screen.getByRole("dialog", { name: "ADAUSDT recording" });
      press(within(drawer).getByRole("switch", { name: "Keep ADAUSDT data forever" }));
      await settleAll();
      const dialog = confirmDialog("Stop keeping ADAUSDT forever?");
      type(within(dialog).getByRole("textbox", { name: "Type ADAUSDT to confirm" }), "ADAUSDT");
      // The frame lists it untracked now: no id, so the drawer's Depth, Retention and switch go.
      view.rerender(
        <Harness
          rows={ROWS.map((r) => (r.symbol === "ADAUSDT" ? row("ADAUSDT", { ...r, id: null }) : r))}
        />,
      );
      expect(within(drawer).queryByRole("switch")).toBeNull();
      pastGuard();
      press(within(dialog).getByRole("button", { name: "Stop keeping ADAUSDT forever" }));
      await settleAll();
      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(
        within(drawer).getByRole("heading", { level: 2, name: "ADAUSDT recording" }),
      ).toHaveFocus();
    });
  },
);
