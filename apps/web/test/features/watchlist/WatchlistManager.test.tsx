/**
 * E08-S08 (#4702 PR (c)): SCR-101, the watchlist manager (E08-D07 D24, §4.3-§4.5, §6.4-§6.7; `14` SCR-101), through
 * the real REST client over a fake `/watchlists` (E08-T07's rules: `If-Match` versions, 412, 409; no network), a fake
 * instrument index, fake timers and the app's one announcer beside it (the manager owns no live region). Scenario 5 of
 * the ticket and its axe line, then the dialog's paths: the lists (create, rename with F2, duplicate, delete with its
 * confirm), the symbol grid (buttons, Alt+arrows, Del, drag), paste and import with their preview, export, columns,
 * validation, a conflict, the cap, and the read-only session.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { KeymapHost } from "../../../src/keymap/KeymapHost";
import type { IndexSnapshot } from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import type { InstrumentSource } from "../../../src/features/watchlist/instruments";
import type { Watchlist } from "../../../src/features/watchlist/listEdits";
import type { ManagerIntent } from "../../../src/features/watchlist/manager/intent";
import {
  WatchlistManager,
  type ManagerOutcome,
} from "../../../src/features/watchlist/manager/WatchlistManager";
import { createWatchlistSync, type ListChange } from "../../../src/features/watchlist/sync";
import {
  WATCHLISTS_PATH,
  createWatchlistApi,
  etagOf,
} from "../../../src/features/watchlist/watchlistApi";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null }[] }>;
};

// Each test draws the whole dialog in jsdom, which on a loaded runner takes seconds. A test past its budget stops at its
// next step, and `afterEach` waits for its step in flight, which can take as long again.
vi.setConfig({ testTimeout: 30_000, hookTimeout: 30_000 });

const T0 = Date.UTC(2026, 9, 31, 10, 31, 2);
const STAMP = "2026-10-30T10:00:00Z";

const inst = (symbol: string, status: Instrument["status"] = "Trading"): Instrument => ({
  symbol,
  category: "linear",
  status,
  ...(status === "Trading" ? {} : { delisted: true }),
  price_scale: 2,
  tick_size: "0.01",
  qty_step: "0.001",
  base_coin: symbol.slice(0, -4),
  quote_coin: "USDT",
});
/** E08-D07's sample list, Majors, 12 symbols. */
const MAJORS_SYMBOLS = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "XRPUSDT",
  "DOGEUSDT",
  "BNBUSDT",
  "ADAUSDT",
  "AVAXUSDT",
  "LINKUSDT",
  "PEPEUSDT",
  "SUIUSDT",
  "TONUSDT",
];
const TRADING = [...MAJORS_SYMBOLS, "DOTUSDT", "LTCUSDT", "ARBUSDT", "OPUSDT"];
const list = (name: string, symbols: readonly string[], id: string): Watchlist => ({
  id,
  name,
  symbols: [...symbols],
  columns: [],
  version: 1,
  created_at: STAMP,
  updated_at: STAMP,
});
const MAJORS = list("Majors", MAJORS_SYMBOLS, "11111111-1111-4111-8111-111111111111");
const SETUPS = list("My Setups", ["DOTUSDT", "LTCUSDT"], "22222222-2222-4222-8222-222222222222");
const ALTS = list("Alts", ["ARBUSDT"], "33333333-3333-4333-8333-333333333333");

function fakeIndex(): InstrumentSource {
  const snapshot: IndexSnapshot = {
    phase: "ready",
    entries: TRADING.map((s) => toEntry(inst(s))),
    known: [toEntry(inst("LUNAUSDT", "Closed"))],
    unlisted: [],
    loadedAt: 0,
    cacheAgeS: 0,
    staleSince: null,
    refreshing: false,
    retryAt: null,
    failure: null,
  };
  return {
    subscribe: () => () => undefined,
    getSnapshot: () => snapshot,
    learn: () => undefined,
    reread: () => undefined,
  };
}

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

interface Call {
  readonly method: string;
  readonly url: string;
  readonly ifMatch: string | null;
  readonly body: Readonly<Record<string, unknown>> | undefined;
}

/** `/watchlists` as E08-T07 keeps it: versions by `If-Match` (412), unique names (409); `fail` refuses the next write. */
function fakeServer(initial: readonly Watchlist[]) {
  const lists = new Map(initial.map((l): [string, Watchlist] => [l.id, l]));
  const calls: Call[] = [];
  let refuse: number | null = null;
  let seq = 0;
  const fetch = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = (init.method ?? "GET").toUpperCase();
    const ifMatch = new Headers(init.headers).get("If-Match");
    const body =
      typeof init.body === "string"
        ? (JSON.parse(init.body) as Readonly<Record<string, unknown>>)
        : undefined;
    calls.push({ method, url, ifMatch, body });
    if (refuse !== null && method !== "GET") {
      const status = refuse;
      refuse = null;
      return json({ status }, status);
    }
    if (url === WATCHLISTS_PATH && method === "GET") return json({ items: [...lists.values()] });
    const name = String(body?.["name"] ?? "").trim();
    const taken = (id: string): boolean =>
      [...lists.values()].some((l) => l.id !== id && l.name.toLowerCase() === name.toLowerCase());
    if (url === WATCHLISTS_PATH && method === "POST") {
      if (taken("")) return json({ status: 409 }, 409);
      seq += 1;
      const id = `00000000-0000-4000-8000-${String(seq).padStart(12, "0")}`;
      const created: Watchlist = {
        ...list(name, (body?.["symbols"] as string[] | undefined) ?? [], id),
        columns: (body?.["columns"] as string[] | undefined) ?? [],
      };
      lists.set(id, created);
      return json(created, 201);
    }
    const id = decodeURIComponent(url.slice(WATCHLISTS_PATH.length + 1));
    const held = lists.get(id);
    if (held === undefined) return json({ status: 404 }, 404);
    if (method === "DELETE") {
      lists.delete(id);
      return new Response(null, { status: 204 });
    }
    if (method === "PUT") {
      if (ifMatch !== etagOf(held)) return json({ status: 412 }, 412);
      if (taken(id)) return json({ status: 409 }, 409);
      const saved: Watchlist = {
        ...held,
        name,
        symbols: body?.["symbols"] as string[],
        columns: body?.["columns"] as string[],
        version: held.version + 1,
      };
      lists.set(id, saved);
      return json(saved);
    }
    return json({ status: 405 }, 405);
  });
  return {
    fetch,
    calls,
    lists,
    writes: (): Call[] => calls.filter((c) => c.method !== "GET"),
    fail(status: number) {
      refuse = status;
    },
  };
}

let said: string[];
let observer: MutationObserver | undefined;
/** The running test's: `afterEach` aborts it, so a test still running past its timeout stops at its next step. */
let running = new AbortController();
/** The step in flight: `afterEach` waits for it, so nothing of a test that timed out stays open into the next. */
let stepping: Promise<unknown> | null = null;
/** What `afterEach` restores if the test did not (a spy on a prototype, `URL`'s blob functions). */
const undo: (() => void)[] = [];

/**
 * Runs `work` as the step in flight: a step of the fake clock in `act`, or a wait on real time (a find, `waitFor`, a
 * file read, axe). A test that is over goes no further.
 */
async function step<T>(work: () => PromiseLike<T>): Promise<T> {
  const { signal } = running;
  signal.throwIfAborted();
  // `act` answers a bare thenable: made a promise, so that `afterEach` can wait for it however it ends.
  const inFlight = Promise.resolve(work());
  stepping = inFlight;
  try {
    const value = await inFlight;
    signal.throwIfAborted();
    return value;
  } finally {
    if (stepping === inFlight) stepping = null;
  }
}

/** Advances the fake clock `ms` in `act`, the promises settled after each timer it fires. */
const flush = (ms = 0): Promise<void> =>
  step(() =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    }),
  );

/** Records each message the app's two regions say (polite and assertive), once per change, into `said`. */
function hear(): void {
  observer?.disconnect();
  const last = new Map<Element, string>();
  observer = new MutationObserver(() => {
    for (const region of document.querySelectorAll("[aria-live][data-cv-inert-exempt]")) {
      const text = region.textContent ?? "";
      if (text !== "" && last.get(region) !== text) said.push(text);
      last.set(region, text);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}

interface Mount {
  readonly readOnly?: boolean;
  readonly intent?: ManagerIntent;
  readonly initialListId?: string;
  readonly server?: ReturnType<typeof fakeServer>;
  readonly instruments?: InstrumentSource;
}

function mount(lists: readonly Watchlist[], extra: Mount = {}) {
  const server = extra.server ?? fakeServer(lists);
  const api = createWatchlistApi(server.fetch);
  const sync = createWatchlistSync();
  const heard: ListChange[] = [];
  sync.subscribe((change) => heard.push(change));
  const onClose = vi.fn<(outcome: ManagerOutcome) => void>();
  const view = render(
    <>
      <WatchlistManager
        api={api}
        sync={sync}
        instruments={extra.instruments ?? fakeIndex()}
        initialListId={extra.initialListId ?? lists[0]?.id}
        {...(extra.intent === undefined ? {} : { intent: extra.intent })}
        readOnly={extra.readOnly ?? false}
        onClose={onClose}
        now={() => Date.now()}
      />
      <ShellAnnouncer />
    </>,
  );
  hear();
  return { ...view, server, heard, onClose };
}

const dialog = (): HTMLElement => screen.getByRole("dialog", { name: "Watchlists" });
const grid = (): HTMLElement => within(dialog()).getByRole("grid");
const order = (): string[] =>
  within(grid())
    .getAllByRole("rowheader")
    .map((h) => h.textContent ?? "");
const symbolCell = (symbol: string): HTMLElement =>
  within(grid()).getByRole("rowheader", { name: symbol });
const option = (name: RegExp | string): HTMLElement =>
  within(dialog()).getByRole("option", { name });
const button = (name: RegExp | string): HTMLElement =>
  within(dialog()).getByRole("button", { name });

beforeEach(() => {
  running = new AbortController();
  vi.useFakeTimers({ now: T0, shouldAdvanceTime: false });
  apiFetch.mockReset();
  apiFetch.mockImplementation(async () => json({ status: 404 }, 404));
  said = [];
});

afterEach(async () => {
  // A test past its timeout is still running. Its next step throws; the step in flight runs out (its clock emptied) and
  // ends here, its `act` closed and its wait over, before the next test starts. Its spy is restored here too.
  running.abort();
  if (stepping !== null) {
    vi.clearAllTimers();
    await stepping.catch(() => undefined);
  }
  for (const restore of undo.splice(0)) restore();
  observer?.disconnect();
  clearAnnouncements();
  document.documentElement.removeAttribute("data-theme");
  vi.useRealTimers();
});

describe("Scenario 5: reorder by keyboard persists, and a failed save rolls back", () => {
  it("Alt+Down on BTCUSDT says 'BTCUSDT moved to position 2 of 12.', saves with PUT on the version read, and holds after a reload", async () => {
    const view = mount([MAJORS, SETUPS]);
    await flush();
    expect(option("Majors, 12 symbols")).toHaveAttribute("aria-selected", "true");
    act(() => symbolCell("BTCUSDT").focus());
    fireEvent.keyDown(symbolCell("BTCUSDT"), { key: "ArrowDown", altKey: true });
    await flush();
    expect(said).toEqual(["BTCUSDT moved to position 2 of 12."]);
    expect(order().slice(0, 3)).toEqual(["ETHUSDT", "BTCUSDT", "SOLUSDT"]);
    // focus stays on the moved row
    expect(document.activeElement).toBe(symbolCell("BTCUSDT"));
    const [put] = view.server.writes();
    expect(put).toMatchObject({
      method: "PUT",
      url: `${WATCHLISTS_PATH}/${MAJORS.id}`,
      ifMatch: `W/"${MAJORS.id}:1"`,
    });
    expect((put?.body?.["symbols"] as string[]).slice(0, 2)).toEqual(["ETHUSDT", "BTCUSDT"]);
    expect(within(dialog()).getByText("Saved 10:31:02 UTC")).toBeInTheDocument();
    // a reload: the manager opened again reads the order stored
    view.unmount();
    mount([], { server: view.server, initialListId: MAJORS.id });
    await flush();
    expect(order().slice(0, 2)).toEqual(["ETHUSDT", "BTCUSDT"]);
  });

  it("a failed save rolls the order back, with an inline error and Retry, which saves it", async () => {
    const view = mount([MAJORS]);
    await flush();
    view.server.fail(503);
    act(() => symbolCell("BTCUSDT").focus());
    fireEvent.keyDown(symbolCell("BTCUSDT"), { key: "ArrowDown", altKey: true });
    await flush();
    expect(order().slice(0, 2)).toEqual(["BTCUSDT", "ETHUSDT"]);
    expect(
      within(dialog()).getByText("Could not save Majors. Your last change was undone."),
    ).toBeInTheDocument();
    expect(said).toEqual([
      "BTCUSDT moved to position 2 of 12.",
      "Could not save Majors. Your last change was undone.",
    ]);
    fireEvent.click(button("Retry"));
    await flush();
    expect(order().slice(0, 2)).toEqual(["ETHUSDT", "BTCUSDT"]);
    expect(view.server.lists.get(MAJORS.id)?.symbols.slice(0, 2)).toEqual(["ETHUSDT", "BTCUSDT"]);
    expect(within(dialog()).queryByText(/Could not save/)).toBeNull();
    // Retry goes with the error it answered: focus to the grid, never to the page
    expect(grid().contains(document.activeElement)).toBe(true);
  });

  // jsdom's axe over the whole dialog takes seconds on a loaded runner.
  it.each(["dark", "light"])(
    "axe finds no serious or critical issue in SCR-101 in the %s theme",
    { timeout: 30_000 },
    async (theme) => {
      document.documentElement.setAttribute("data-theme", theme);
      mount([MAJORS, SETUPS, ALTS]);
      await flush();
      vi.useRealTimers();
      const { violations } = await step(() =>
        axe.run(document.body, {
          rules: { "color-contrast": { enabled: false } }, // jsdom has no layout: CI's a11y gate measures contrast
        }),
      );
      expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
        [],
      );
    },
  );
});

/** The element with focus (the body when none). */
const active = (): Element => document.activeElement ?? document.body;
const fileInput = (): HTMLInputElement => {
  const input = dialog().querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) throw new Error("no file input");
  return input;
};
const pick = (file: File): void => {
  fireEvent.change(fileInput(), { target: { files: [file] } });
};
const textFile = (text: string, name: string, type = "text/plain"): File =>
  new File([text], name, { type });
/** A preview group's symbols: the words after its term. */
const group = (scope: HTMLElement, term: string): string =>
  within(scope).getByText(term).nextElementSibling?.textContent ?? "";

describe("the lists (§4.3 Lists, §6.5)", () => {
  it("a listbox of 'Majors, 12 symbols'; focus starts on the list shown; the arrows select as they move; Enter is inert", async () => {
    const view = mount([MAJORS, SETUPS, ALTS], { initialListId: SETUPS.id });
    await flush();
    const setups = option("My Setups, 2 symbols");
    expect(active()).toBe(setups);
    expect(setups).toHaveAttribute("aria-selected", "true");
    expect(
      within(dialog()).getByRole("heading", { name: "My Setups · 2 symbols" }),
    ).toBeInTheDocument();
    fireEvent.keyDown(setups, { key: "ArrowDown" });
    await flush();
    expect(active()).toBe(option("Alts, 1 symbol"));
    expect(option("Alts, 1 symbol")).toHaveAttribute("aria-selected", "true");
    expect(order()).toEqual(["ARBUSDT"]);
    fireEvent.keyDown(option("Alts, 1 symbol"), { key: "Enter" });
    fireEvent.keyDown(option("Alts, 1 symbol"), { key: "Home" });
    await flush();
    expect(active()).toBe(option("Majors, 12 symbols"));
    expect(view.onClose).not.toHaveBeenCalled();
  });

  it("F2 renames in place: Enter saves the name with the list (PUT) and focus goes back to the list", async () => {
    const view = mount([MAJORS, SETUPS]);
    await flush();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "F2" });
    await flush();
    const field = within(dialog()).getByRole("textbox", { name: "Watchlist name" });
    expect(active()).toBe(field);
    expect(field).toHaveValue("Majors");
    fireEvent.change(field, { target: { value: " Core " } });
    fireEvent.keyDown(field, { key: "Enter" });
    await flush();
    expect(view.server.writes()[0]).toMatchObject({
      method: "PUT",
      ifMatch: `W/"${MAJORS.id}:1"`,
      body: { name: "Core", symbols: MAJORS_SYMBOLS },
    });
    expect(active()).toBe(option("Core, 12 symbols"));
    expect(view.heard).toContainEqual({
      kind: "stored",
      list: expect.objectContaining({ id: MAJORS.id, name: "Core", version: 2 }),
    });
  });

  it("Esc cancels a rename and keeps the dialog open; the next Esc closes it, telling the page the lists", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "F2" });
    await flush();
    const field = within(dialog()).getByRole("textbox", { name: "Watchlist name" });
    fireEvent.change(field, { target: { value: "Core" } });
    fireEvent.keyDown(field, { key: "Escape" });
    await flush();
    expect(within(dialog()).queryByRole("textbox", { name: "Watchlist name" })).toBeNull();
    expect(active()).toBe(option("Majors, 12 symbols"));
    expect(view.onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(active(), { key: "Escape" });
    await flush();
    expect(view.onClose).toHaveBeenCalledWith({ listIds: [MAJORS.id], selectedId: MAJORS.id });
    expect(view.server.writes()).toEqual([]);
  });

  it("names are 1-80 characters and unique (trimmed, case-insensitive): the field says why and keeps focus", async () => {
    const view = mount([MAJORS, SETUPS]);
    await flush();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "F2" });
    await flush();
    const field = within(dialog()).getByRole("textbox", { name: "Watchlist name" });
    for (const [value, words] of [
      ["  ", "Name the watchlist."],
      ["x".repeat(81), "Use 80 characters or fewer."],
      [" my setups ", "A watchlist named my setups already exists."],
    ] as const) {
      fireEvent.change(field, { target: { value } });
      fireEvent.keyDown(field, { key: "Enter" });
      await flush();
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveAccessibleDescription(expect.stringContaining(words));
      expect(active()).toBe(field);
    }
    expect(view.server.writes()).toEqual([]);
  });

  it("'+ New watchlist' adds 'Watchlist' in rename mode; Enter creates it (POST), selected, focus kept on it", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(button("New watchlist"));
    await flush();
    const field = within(dialog()).getByRole("textbox", { name: "Watchlist name" });
    expect(field).toHaveValue("Watchlist");
    expect(active()).toBe(field);
    fireEvent.change(field, { target: { value: "Breakouts" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await flush();
    expect(view.server.writes()[0]).toMatchObject({
      method: "POST",
      url: WATCHLISTS_PATH,
      body: { name: "Breakouts", symbols: [] },
    });
    const created = option("Breakouts, 0 symbols");
    expect(created).toHaveAttribute("aria-selected", "true");
    expect(active()).toBe(created);
    expect(within(dialog()).getByText("No symbols on Breakouts")).toBeInTheDocument();
    expect(view.heard).toContainEqual({
      kind: "stored",
      list: expect.objectContaining({ name: "Breakouts", version: 1 }),
    });
  });

  it("a create that fails is rolled back with the error and Retry, which creates it", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(button("New watchlist"));
    await flush();
    view.server.fail(503);
    fireEvent.keyDown(within(dialog()).getByRole("textbox", { name: "Watchlist name" }), {
      key: "Escape",
    });
    await flush();
    expect(within(dialog()).queryByRole("option", { name: /^Watchlist/ })).toBeNull();
    expect(
      within(dialog()).getByText("Could not save Watchlist. Your last change was undone."),
    ).toBeInTheDocument();
    expect(said).toEqual(["Could not save Watchlist. Your last change was undone."]);
    fireEvent.click(button("Retry"));
    await flush();
    expect(option("Watchlist, 0 symbols")).toHaveAttribute("aria-selected", "true");
  });

  it("'Actions for Majors' > Duplicate creates 'Majors copy' with its symbols and columns", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(button("Actions for Majors"));
    await flush();
    fireEvent.click(screen.getByRole("menuitem", { name: "Duplicate" }));
    await flush();
    expect(view.server.writes()[0]).toMatchObject({
      method: "POST",
      body: { name: "Majors copy", symbols: MAJORS_SYMBOLS, columns: [] },
    });
    expect(option("Majors copy, 12 symbols")).toHaveAttribute("aria-selected", "true");
  });

  it("Del on a list asks 'Delete Majors?' with Cancel focused; Delete removes it and focus goes to the next list", async () => {
    const view = mount([MAJORS, SETUPS]);
    await flush();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "Delete" });
    await flush();
    let confirm = screen.getByRole("alertdialog", { name: "Delete Majors?" });
    expect(confirm).toHaveAccessibleDescription(
      expect.stringContaining(
        "The list and its 12 symbols are removed. Recordings, charts and alerts are not affected.",
      ),
    );
    expect(active()).toBe(within(confirm).getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    await flush();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "Delete" });
    await flush(500); // CMP-044's guard: no press counts in its first 400 ms
    confirm = screen.getByRole("alertdialog", { name: "Delete Majors?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete Majors" }));
    await flush();
    expect(view.server.writes()).toEqual([
      expect.objectContaining({ method: "DELETE", url: `${WATCHLISTS_PATH}/${MAJORS.id}` }),
    ]);
    expect(within(dialog()).queryByRole("option", { name: /^Majors/ })).toBeNull();
    expect(active()).toBe(option("My Setups, 2 symbols"));
  });

  it("deleting the last list leaves 'No watchlists yet' and focus on '+ New watchlist'", async () => {
    mount([ALTS]);
    await flush();
    fireEvent.keyDown(option("Alts, 1 symbol"), { key: "Delete" });
    await flush(500);
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete Alts" }),
    );
    await flush();
    expect(
      within(dialog()).getByRole("heading", { name: "No watchlists yet" }),
    ).toBeInTheDocument();
    expect(within(dialog()).queryByRole("listbox")).toBeNull();
    expect(active()).toBe(button("New watchlist"));
  });
});

describe("the symbol grid (§6.4, §6.5)", () => {
  it("the arrows reach Move up, Move down and Remove as cells, focus on their buttons; one Tab stop", async () => {
    mount([MAJORS]);
    await flush();
    act(() => symbolCell("BTCUSDT").focus());
    fireEvent.keyDown(active(), { key: "ArrowRight" });
    expect(active()).toBe(button("Move BTCUSDT up"));
    fireEvent.keyDown(active(), { key: "ArrowRight" });
    expect(active()).toBe(button("Move BTCUSDT down"));
    fireEvent.keyDown(active(), { key: "ArrowRight" });
    expect(active()).toBe(button("Remove BTCUSDT"));
    fireEvent.keyDown(active(), { key: "ArrowDown" });
    expect(active()).toBe(button("Remove ETHUSDT"));
    expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
  });

  it("'Move BTCUSDT down' moves the row and keeps focus on the pressed button, so a second press moves it again", async () => {
    const view = mount([MAJORS]);
    await flush();
    act(() => button("Move BTCUSDT down").focus());
    fireEvent.click(button("Move BTCUSDT down"));
    await flush();
    expect(order().slice(0, 2)).toEqual(["ETHUSDT", "BTCUSDT"]);
    expect(active()).toBe(button("Move BTCUSDT down"));
    fireEvent.click(active());
    await flush();
    expect(order().slice(0, 3)).toEqual(["ETHUSDT", "SOLUSDT", "BTCUSDT"]);
    expect(said).toEqual([
      "BTCUSDT moved to position 2 of 12.",
      "BTCUSDT moved to position 3 of 12.",
    ]);
    expect(view.server.writes()).toHaveLength(2);
  });

  it("the ends are T2: the name and focus stay, 'Already first.' is said once and nothing moves", async () => {
    const view = mount([MAJORS]);
    await flush();
    const up = button("Move BTCUSDT up");
    expect(up).toHaveAttribute("aria-disabled", "true");
    expect(up).toHaveAccessibleDescription("Already first.");
    expect(button("Move TONUSDT down")).toHaveAccessibleDescription("Already last.");
    act(() => up.focus());
    fireEvent.click(up);
    await flush();
    expect(said).toEqual(["Already first."]);
    fireEvent.keyDown(up, { key: "ArrowUp", altKey: true });
    await flush();
    expect(order()[0]).toBe("BTCUSDT");
    expect(active()).toBe(up);
    expect(view.server.writes()).toEqual([]);
  });

  it("Del removes the row, says so once, and focus goes to the next row", async () => {
    const view = mount([MAJORS]);
    await flush();
    act(() => symbolCell("SOLUSDT").focus());
    fireEvent.keyDown(symbolCell("SOLUSDT"), { key: "Delete" });
    await flush();
    expect(order()).not.toContain("SOLUSDT");
    expect(said).toEqual(["Removed SOLUSDT."]);
    expect(active()).toBe(symbolCell("XRPUSDT"));
    expect(view.server.writes()[0]?.body?.["symbols"]).toHaveLength(11);
  });

  it("a row dropped on another takes its place, said once (the drag handle is aria-hidden)", async () => {
    mount([MAJORS]);
    await flush();
    const handle = symbolCell("BTCUSDT").closest("tr")?.querySelector('[draggable="true"]');
    if (!(handle instanceof HTMLElement)) throw new Error("no drag handle");
    expect(handle).toHaveAttribute("aria-hidden", "true");
    // the press that starts a drag is the handle's: the grid neither takes it nor prevents it
    expect(fireEvent.mouseDown(handle)).toBe(true);
    const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
    fireEvent.dragStart(handle, { dataTransfer });
    const target = symbolCell("XRPUSDT").closest("tr");
    if (target === null) throw new Error("no row");
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    await flush();
    expect(order().slice(0, 4)).toEqual(["ETHUSDT", "SOLUSDT", "XRPUSDT", "BTCUSDT"]);
    expect(said).toEqual(["BTCUSDT moved to position 4 of 12."]);
  });

  // 200 rows of five cells: jsdom draws them slowly on a loaded runner.
  it(
    "at 200 symbols '+ Add symbol' is T2 with 'Watching 200 symbols — remove some to add more' before any attempt",
    { timeout: 30_000 },
    async () => {
      const full = list(
        "Big",
        Array.from({ length: 200 }, (_, i) => `A${String(i).padStart(3, "0")}USDT`),
        "44444444-4444-4444-8444-444444444444",
      );
      mount([full]);
      await flush();
      const add = button(/Add symbol/);
      expect(add).toHaveAttribute("aria-disabled", "true");
      expect(add).toHaveAccessibleDescription("Watching 200 symbols — remove some to add more");
    },
  );
});

describe("paste (D25, §4.4)", () => {
  it("Preview groups the tokens and takes focus; 'Add 2 symbols' adds them at the end, focus on the first", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(button("Paste symbols"));
    await flush();
    const area = within(dialog()).getByRole("textbox", {
      name: "Paste symbols, one per line or separated by commas or spaces",
    });
    expect(active()).toBe(area);
    fireEvent.change(area, {
      target: { value: "dotusdt, BTCUSDT; LUNAUSDT nope\n# a note\nltcusdt FOOUSDT" },
    });
    fireEvent.click(button("Preview"));
    await flush();
    const heading = within(dialog()).getByRole("heading", { name: "Preview" });
    expect(active()).toBe(heading);
    const preview = heading.closest("section");
    if (preview === null) throw new Error("no preview");
    expect(group(preview, "To add")).toBe("DOTUSDT, LTCUSDT");
    expect(group(preview, "Already on Majors")).toBe("BTCUSDT");
    expect(group(preview, "Delisted by the exchange")).toBe("LUNAUSDT");
    expect(group(preview, "Not found on Bybit USDT perps")).toBe("FOOUSDT");
    expect(group(preview, "Not a USDT perpetual symbol")).toBe("NOPE");
    fireEvent.click(within(preview).getByRole("button", { name: "Add 2 symbols" }));
    await flush();
    expect(order().slice(-2)).toEqual(["DOTUSDT", "LTCUSDT"]);
    expect(said).toEqual(["Added 2 symbols to Majors."]);
    expect(active()).toBe(symbolCell("DOTUSDT"));
    expect(view.server.writes()).toHaveLength(1);
  });
});

describe("import and export (D14, §4.4)", () => {
  /** CMP-067 reads a file through `FileReader` (jsdom's `Blob` has no `arrayBuffer`), which runs on real time. */
  const WAIT = { timeout: 5_000 };
  const readBlob = (blob: Blob): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error ?? new Error("read failed"));
      reader.readAsText(blob);
    });

  it(
    "a file's preview offers a new list named after it and 'Add to Majors', which adds the new symbols",
    { timeout: 20_000 },
    async () => {
      mount([MAJORS]);
      await flush();
      vi.useRealTimers();
      pick(textFile("# my picks\nBTCUSDT, DOTUSDT\nLUNAUSDT\n", "Breakouts.txt"));
      const heading = await step(() =>
        within(dialog()).findByRole("heading", { name: "Preview of Breakouts.txt" }, WAIT),
      );
      await step(() => waitFor(() => expect(active()).toBe(heading), WAIT));
      expect(group(dialog(), "Already on Majors")).toBe("BTCUSDT");
      expect(group(dialog(), "Delisted by the exchange")).toBe("LUNAUSDT");
      expect(button('Import into a new list "Breakouts"')).toBeInTheDocument();
      fireEvent.click(button("Add to Majors"));
      await step(() => waitFor(() => expect(order().at(-1)).toBe("DOTUSDT"), WAIT));
      expect(said).toEqual(["Added 1 symbol to Majors."]);
      await step(() => waitFor(() => expect(active()).toBe(symbolCell("DOTUSDT")), WAIT));
    },
  );

  it(
    "'Import into a new list' creates it with the file's symbols, selected",
    { timeout: 20_000 },
    async () => {
      const view = mount([MAJORS]);
      await flush();
      vi.useRealTimers();
      pick(textFile("BTCUSDT\nDOTUSDT\n", "Majors.csv", "text/csv"));
      fireEvent.click(
        await step(() =>
          within(dialog()).findByRole(
            "button",
            { name: 'Import into a new list "Majors 2"' },
            WAIT,
          ),
        ),
      );
      await step(() =>
        waitFor(
          () =>
            expect(view.server.writes()[0]).toMatchObject({
              method: "POST",
              body: { name: "Majors 2", symbols: ["BTCUSDT", "DOTUSDT"] },
            }),
          WAIT,
        ),
      );
      await step(() =>
        waitFor(
          () => expect(option("Majors 2, 2 symbols")).toHaveAttribute("aria-selected", "true"),
          WAIT,
        ),
      );
      expect(said).toEqual(["Imported 2 symbols into Majors 2."]);
    },
  );

  it(
    "refuses a file over 64 KB, one that is not text, and one with no symbols",
    { timeout: 20_000 },
    async () => {
      const view = mount([MAJORS]);
      await flush();
      vi.useRealTimers();
      const shows = (words: string) => step(() => within(dialog()).findByText(words, {}, WAIT));
      pick(textFile("x".repeat(65 * 1024), "big.txt"));
      expect(
        await shows("This file is 65 KB. A watchlist file can be at most 64 KB."),
      ).toBeVisible();
      pick(new File([new Uint8Array([0xff, 0xfe, 0xfd])], "odd.txt", { type: "text/plain" }));
      expect(await shows("This file isn't plain text.")).toBeVisible();
      pick(textFile("# nothing here\n\n", "empty.txt"));
      expect(await shows("This file has no symbols.")).toBeVisible();
      pick(textFile("BTCUSDT", "list.png", "image/png"));
      expect(await shows("This file isn't plain text.")).toBeVisible();
      expect(view.server.writes()).toEqual([]);
    },
  );

  it("'Export Majors' saves Majors.txt: one header line, then the symbols in order", async () => {
    mount([MAJORS]);
    await flush();
    const saved: Blob[] = [];
    const names: string[] = [];
    // The environment's own functions, put back as they were (C-5335-10: not deleted).
    const created = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const revoked = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    const revoke = vi.fn<(url: string) => void>();
    Object.assign(URL, {
      createObjectURL: vi.fn((blob: Blob) => {
        saved.push(blob);
        return "blob:watchlist";
      }),
      revokeObjectURL: revoke,
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      names.push(this.download);
    });
    // Once only: vi's restore puts the original back over whatever is there, the next test's spy included.
    let restored = false;
    const restore = (): void => {
      if (restored) return;
      restored = true;
      click.mockRestore();
      for (const [name, held] of [
        ["createObjectURL", created],
        ["revokeObjectURL", revoked],
      ] as const) {
        if (held === undefined) Reflect.deleteProperty(URL, name);
        else Object.defineProperty(URL, name, held);
      }
    };
    undo.push(restore);
    try {
      fireEvent.click(button("Export Majors"));
      await flush();
      expect(names).toEqual(["Majors.txt"]);
      // the link's blob is let go once the click has taken it (S-5335-03)
      expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:watchlist");
      const [blob] = saved;
      if (blob === undefined) throw new Error("nothing was saved");
      expect(blob.type).toBe("text/plain;charset=utf-8");
      vi.useRealTimers();
      expect(await step(() => readBlob(blob))).toBe(
        `# CandleViewer watchlist "Majors", 12 symbols, exported 2026-10-31 10:31 UTC\n${MAJORS_SYMBOLS.join("\n")}\n`,
      );
    } finally {
      restore();
    }
  });
});

describe("columns (CMP-056)", () => {
  it("every column listed, Symbol locked; showing one and moving one save the list's columns", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(within(dialog()).getByRole("tab", { name: "Columns" }));
    await flush();
    const symbol = within(dialog()).getByRole("checkbox", { name: /Symbol/ });
    expect(symbol).toBeChecked();
    expect(symbol).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(within(dialog()).getByRole("checkbox", { name: "Mark" }));
    await flush();
    const defaults = [
      "symbol",
      "last",
      "chg_24h_pct",
      "turnover_24h",
      "funding_rate",
      "next_funding",
      "oi_chg_24h_pct",
      "spread_bps",
      "rec",
    ];
    expect(view.server.writes()[0]?.body?.["columns"]).toEqual([...defaults, "mark_price"]);
    fireEvent.click(button("Move Last down"));
    await flush();
    expect((view.server.writes()[1]?.body?.["columns"] as string[]).slice(0, 3)).toEqual([
      "symbol",
      "chg_24h_pct",
      "last",
    ]);
    expect(said).toEqual(["Last moved to position 3 of 17."]);
  });
});

describe("read-only: no workspaces:write (D13, §4.3)", () => {
  it("one notice under the title; every write T2 pointing at it; F2, Del and Alt+arrows change nothing and say why", async () => {
    const view = mount([MAJORS, SETUPS], { readOnly: true });
    await flush();
    const notice = within(dialog()).getByText("Read-only — your role can't save workspaces.");
    for (const name of [
      /New watchlist/,
      /Add symbol/,
      /Paste symbols/,
      /Import…/,
      /^Move ETHUSDT up/,
      /^Remove BTCUSDT/,
    ]) {
      const control = button(name);
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control.getAttribute("aria-describedby")).toContain(notice.id);
    }
    expect(button("Export Majors")).not.toHaveAttribute("aria-disabled");
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "F2" });
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "Delete" });
    act(() => symbolCell("ETHUSDT").focus());
    fireEvent.keyDown(symbolCell("ETHUSDT"), { key: "ArrowUp", altKey: true });
    fireEvent.keyDown(symbolCell("ETHUSDT"), { key: "Delete" });
    await flush();
    expect(within(dialog()).queryByRole("textbox", { name: "Watchlist name" })).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(order()).toEqual(MAJORS_SYMBOLS);
    expect(said).toEqual(["Your role can't save workspaces."]);
    expect(view.server.writes()).toEqual([]);
  });

  it("no list: the sentence form, which '+ New watchlist' and 'Import…' point at", async () => {
    mount([], { readOnly: true });
    await flush();
    expect(within(dialog()).getByRole("heading", { name: "No watchlists" })).toBeInTheDocument();
    const sentence = within(dialog()).getByText("Your role can't save workspaces.");
    expect(button(/New watchlist/).getAttribute("aria-describedby")).toContain(sentence.id);
    expect(button(/Import…/).getAttribute("aria-describedby")).toContain(sentence.id);
    expect(within(dialog()).queryByRole("button", { name: "Create watchlist" })).toBeNull();
  });
});

describe("no list, a failed read, a conflict", () => {
  it("no list: 'No watchlists yet' and 'Create watchlist', which starts a new list", async () => {
    mount([]);
    await flush();
    expect(active()).toBe(button("New watchlist"));
    fireEvent.click(button("Create watchlist"));
    await flush();
    expect(within(dialog()).getByRole("textbox", { name: "Watchlist name" })).toHaveValue(
      "Watchlist",
    );
  });

  it("a failed read: 'Watchlists could not be loaded.' with Retry, said once as an alert", async () => {
    const server = fakeServer([MAJORS]);
    const read = server.fetch.getMockImplementation();
    server.fetch.mockImplementationOnce(async () => json({ status: 503 }, 503));
    mount([], { server });
    await flush();
    expect(within(dialog()).getByText("Watchlists could not be loaded.")).toBeInTheDocument();
    expect(said).toEqual(["Watchlists could not be loaded."]);
    if (read !== undefined) server.fetch.mockImplementation(read);
    fireEvent.click(button("Retry"));
    await flush();
    expect(option("Majors, 12 symbols")).toBeInTheDocument();
  });

  it("another window saved Majors first: 'Majors changed in another window.'; Reload shows it as stored", async () => {
    const view = mount([MAJORS]);
    await flush();
    view.server.lists.set(MAJORS.id, { ...MAJORS, symbols: MAJORS_SYMBOLS.slice(1), version: 2 });
    act(() => symbolCell("XRPUSDT").focus());
    fireEvent.keyDown(symbolCell("XRPUSDT"), { key: "Delete" });
    await flush();
    expect(within(dialog()).getByText("Majors changed in another window.")).toBeInTheDocument();
    expect(said.at(-1)).toBe("Majors changed in another window.");
    fireEvent.click(button("Reload Majors"));
    await flush();
    expect(order()).toEqual(MAJORS_SYMBOLS.slice(1));
    expect(within(dialog()).queryByText(/changed in another window/)).toBeNull();
    expect(view.heard).toContainEqual({
      kind: "stored",
      list: expect.objectContaining({ id: MAJORS.id, version: 2 }),
    });
  });

  it("'Overwrite with my version' saves the change undone against the version stored now", async () => {
    const view = mount([MAJORS]);
    await flush();
    view.server.lists.set(MAJORS.id, { ...MAJORS, symbols: MAJORS_SYMBOLS.slice(1), version: 2 });
    act(() => symbolCell("XRPUSDT").focus());
    fireEvent.keyDown(symbolCell("XRPUSDT"), { key: "Delete" });
    await flush();
    fireEvent.click(button("Overwrite with my version"));
    await flush();
    const put = view.server.writes().at(-1);
    expect(put).toMatchObject({ method: "PUT", ifMatch: `W/"${MAJORS.id}:2"` });
    expect(put?.body?.["symbols"]).toEqual(MAJORS_SYMBOLS.filter((s) => s !== "XRPUSDT"));
    expect(view.server.lists.get(MAJORS.id)?.version).toBe(3);
  });
});

describe("the paths that open it (the intent)", () => {
  it("rename: the name field on that list", async () => {
    mount([MAJORS, SETUPS], { intent: { kind: "rename", listId: SETUPS.id } });
    await flush();
    const field = within(dialog()).getByRole("textbox", { name: "Watchlist name" });
    expect(field).toHaveValue("My Setups");
    expect(active()).toBe(field);
  });

  it("delete: the confirm on that list, Cancel focused", async () => {
    mount([MAJORS, SETUPS], { intent: { kind: "delete", listId: SETUPS.id } });
    await flush();
    const confirm = screen.getByRole("alertdialog", { name: "Delete My Setups?" });
    expect(active()).toBe(within(confirm).getByRole("button", { name: "Cancel" }));
  });

  it("paste: the text area on that list; import: the Import… button; create: a new list's name", async () => {
    const one = mount([MAJORS], { intent: { kind: "paste", listId: MAJORS.id } });
    await flush();
    expect(active()).toBe(
      within(dialog()).getByRole("textbox", { name: /^Paste symbols, one per line/ }),
    );
    one.unmount();
    const two = mount([MAJORS], { intent: { kind: "import", listId: MAJORS.id } });
    await flush();
    expect(active()).toBe(button("Import…"));
    two.unmount();
    mount([MAJORS], { intent: { kind: "create" } });
    await flush();
    expect(active()).toBe(within(dialog()).getByRole("textbox", { name: "Watchlist name" }));
  });

  it("duplicate: the copy, selected", async () => {
    const view = mount([MAJORS], { intent: { kind: "duplicate", listId: MAJORS.id } });
    await flush();
    expect(view.server.writes()[0]).toMatchObject({
      method: "POST",
      body: { name: "Majors copy" },
    });
    expect(active()).toBe(option("Majors copy, 12 symbols"));
  });
});

describe("#5335's lens round (SCR-101)", () => {
  const field = (): HTMLElement =>
    within(dialog()).getByRole("textbox", { name: "Watchlist name" });
  /** A style a logical property holds, read as jsdom keeps it (its parser may not know the property). */
  const styleOf = (node: HTMLElement, property: string): string =>
    (node.style as unknown as Readonly<Record<string, string | undefined>>)[property] ?? "";

  it("A-5335-01: Enter in a new list's name field creates it once (its blur sends nothing more), focus on the new list", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(button("New watchlist"));
    await flush();
    fireEvent.change(field(), { target: { value: "Breakouts" } });
    fireEvent.keyDown(field(), { key: "Enter" });
    await flush();
    expect(view.server.writes()).toHaveLength(1);
    expect(active()).toBe(option("Breakouts, 0 symbols"));
  });

  it("A-5335-01: a 503 on that create rolls it back, said once; nothing is created behind the error", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(button("New watchlist"));
    await flush();
    view.server.fail(503);
    fireEvent.change(field(), { target: { value: "Breakouts" } });
    fireEvent.keyDown(field(), { key: "Enter" });
    await flush();
    expect(view.server.writes()).toHaveLength(1);
    expect(view.server.lists.size).toBe(1);
    expect(said).toEqual(["Could not save Breakouts. Your last change was undone."]);
  });

  it("A-5335-05: a list's visible words stay apart ('Majors 12'), so its name holds them (label-content-name-mismatch)", async () => {
    mount([MAJORS, SETUPS]);
    await flush();
    expect(option("Majors, 12 symbols").textContent).toBe("Majors 12");
    expect(option("My Setups, 2 symbols").textContent).toBe("My Setups 2");
  });

  it("A-5335-06: Space on a list is inert, never a scroll; PageDown and PageUp move ten lists, the selection following", async () => {
    const many = Array.from({ length: 14 }, (_, i) =>
      list(`List ${i + 1}`, [], `${String(i + 1).padStart(8, "0")}-1111-4111-8111-111111111111`),
    );
    mount(many);
    await flush();
    const first = option("List 1, 0 symbols");
    expect(fireEvent.keyDown(first, { key: " " })).toBe(false); // its default prevented
    expect(first).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(first, { key: "PageDown" });
    await flush();
    expect(active()).toBe(option("List 11, 0 symbols"));
    expect(option("List 11, 0 symbols")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(active(), { key: "PageDown" });
    await flush();
    expect(active()).toBe(option("List 14, 0 symbols"));
    fireEvent.keyDown(active(), { key: "PageUp" });
    await flush();
    expect(active()).toBe(option("List 4, 0 symbols"));
  });

  it("A-5335-07: only the selected list draws the selection bar (forced colours keep a border, so the others draw none)", async () => {
    mount([MAJORS, SETUPS]);
    await flush();
    const on = option("Majors, 12 symbols");
    const off = option("My Setups, 2 symbols");
    expect(styleOf(on, "borderInlineStart")).toBe("2px solid var(--color-border-selected)");
    expect(styleOf(off, "borderInlineStart")).toBe("");
    // the bar's width is padding on the others, so no text moves as the selection does
    expect(styleOf(off, "paddingInlineStart")).toBe("calc(var(--space-2) + 2px)");
    expect(styleOf(on, "paddingInlineStart")).toBe("var(--space-2)");
  });

  it("A-5335-09: Alt+↓ then Del removes the moved row, and focus goes to the row after its new place", async () => {
    mount([MAJORS]);
    await flush();
    act(() => symbolCell("BTCUSDT").focus());
    fireEvent.keyDown(symbolCell("BTCUSDT"), { key: "ArrowDown", altKey: true });
    await flush();
    expect(order().slice(0, 3)).toEqual(["ETHUSDT", "BTCUSDT", "SOLUSDT"]);
    fireEvent.keyDown(symbolCell("BTCUSDT"), { key: "Delete" });
    await flush();
    expect(order().slice(0, 2)).toEqual(["ETHUSDT", "SOLUSDT"]);
    expect(active()).toBe(symbolCell("SOLUSDT"));
  });

  it("A-5335-11: the delete path's confirm hands focus back to that list on Cancel, never to the dialog's title", async () => {
    mount([MAJORS, SETUPS], { intent: { kind: "delete", listId: SETUPS.id } });
    await flush();
    const confirm = screen.getByRole("alertdialog", { name: "Delete My Setups?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    await flush();
    expect(active()).toBe(option("My Setups, 2 symbols"));
  });

  it("A-5335-12: the name field's error and key hint are in the flow: its list grows to hold them", async () => {
    // jsdom has no layout: the field (its input, error and hint) measures 72 px
    const height = vi
      .spyOn(HTMLElement.prototype, "offsetHeight", "get")
      .mockImplementation(function (this: HTMLElement) {
        return this.hasAttribute("data-name-field") ? 72 : 24;
      });
    undo.push(() => height.mockRestore());
    mount([MAJORS, SETUPS]);
    await flush();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "F2" });
    await flush();
    expect(field()).toHaveAccessibleDescription(/^\s*Enter saves the name; Esc cancels\.$/);
    expect(styleOf(option("Majors, 12 symbols"), "minBlockSize")).toBe(
      "max(var(--size-row-height), 72px)",
    );
    fireEvent.change(field(), { target: { value: " my setups " } });
    fireEvent.keyDown(field(), { key: "Enter" });
    await flush();
    expect(field()).toHaveAccessibleDescription(
      /^\s*A watchlist named my setups already exists\.\s+Enter saves the name; Esc cancels\.$/,
    );
  });

  it("C-5335-01: Duplicate leaves out a symbol that no longer trades (a create refuses it), and says so", async () => {
    const old = list("Old", ["BTCUSDT", "LUNAUSDT"], "55555555-5555-4555-8555-555555555555");
    const view = mount([old]);
    await flush();
    fireEvent.click(button("Actions for Old"));
    await flush();
    fireEvent.click(screen.getByRole("menuitem", { name: "Duplicate" }));
    await flush();
    expect(view.server.writes()[0]).toMatchObject({
      method: "POST",
      body: { name: "Old copy", symbols: ["BTCUSDT"] },
    });
    expect(said).toEqual(["Old copy leaves out LUNAUSDT: not trading on Bybit."]);
    expect(option("Old copy, 1 symbol")).toHaveAttribute("aria-selected", "true");
  });

  it("C-5335-03: a create rolled back is said once, however the dialog changes after it", async () => {
    const view = mount([MAJORS, SETUPS]);
    await flush();
    const writes = new Set<string>();
    const watch = new MutationObserver(() => {
      for (const node of document.querySelectorAll("[data-cv-inert-exempt] [data-seq]"))
        writes.add(node.getAttribute("data-seq") ?? "");
    });
    watch.observe(document.body, { childList: true, subtree: true });
    undo.push(() => watch.disconnect());
    view.server.fail(503);
    fireEvent.click(button("New watchlist"));
    await flush();
    fireEvent.keyDown(field(), { key: "Escape" });
    await flush();
    expect(said).toEqual(["Could not save Watchlist. Your last change was undone."]);
    const once = writes.size;
    for (const name of ["My Setups, 2 symbols", "Majors, 12 symbols", "My Setups, 2 symbols"]) {
      fireEvent.click(option(name));
      await flush();
    }
    expect(writes.size).toBe(once);
  });

  it("C-5335-04: Overwrite runs once: its buttons step aside while it runs, so a second press sends nothing", async () => {
    const view = mount([MAJORS]);
    await flush();
    view.server.lists.set(MAJORS.id, { ...MAJORS, symbols: MAJORS_SYMBOLS.slice(1), version: 2 });
    act(() => symbolCell("XRPUSDT").focus());
    fireEvent.keyDown(symbolCell("XRPUSDT"), { key: "Delete" });
    await flush();
    const overwrite = button("Overwrite with my version");
    fireEvent.click(overwrite);
    expect(
      within(dialog()).queryByRole("button", { name: "Overwrite with my version" }),
    ).toBeNull();
    expect(within(dialog()).queryByRole("button", { name: "Reload Majors" })).toBeNull();
    fireEvent.click(overwrite);
    await flush();
    // the refused save, then the one overwrite
    expect(view.server.writes().filter((w) => w.method === "PUT")).toHaveLength(2);
    expect(view.server.lists.get(MAJORS.id)?.version).toBe(3);
  });

  it("C-5335-05: the list deleted in another window: Reload says so, and focus goes to the next list", async () => {
    const view = mount([MAJORS, SETUPS]);
    await flush();
    view.server.lists.delete(MAJORS.id); // its save answers 404: a conflict
    act(() => symbolCell("XRPUSDT").focus());
    fireEvent.keyDown(symbolCell("XRPUSDT"), { key: "Delete" });
    await flush();
    fireEvent.click(button("Reload Majors"));
    await flush();
    expect(within(dialog()).queryByRole("option", { name: /^Majors/ })).toBeNull();
    expect(said.at(-1)).toBe("Majors was deleted in another window.");
    expect(active()).toBe(option("My Setups, 2 symbols"));
  });

  it("C-5335-05: a re-read that fails keeps the conflict, with its buttons, and says 'Could not reload Majors.'", async () => {
    const view = mount([MAJORS]);
    await flush();
    view.server.lists.set(MAJORS.id, { ...MAJORS, symbols: MAJORS_SYMBOLS.slice(1), version: 2 });
    act(() => symbolCell("XRPUSDT").focus());
    fireEvent.keyDown(symbolCell("XRPUSDT"), { key: "Delete" });
    await flush();
    const read = view.server.fetch.getMockImplementation();
    view.server.fetch.mockImplementationOnce(async () => json({ status: 503 }, 503));
    fireEvent.click(button("Reload Majors"));
    await flush();
    if (read !== undefined) view.server.fetch.mockImplementation(read);
    expect(said.at(-1)).toBe("Could not reload Majors.");
    expect(within(dialog()).getByText("Majors changed in another window.")).toBeInTheDocument();
    expect(button("Reload Majors")).toBeInTheDocument();
  });

  it("C-5335-07: a column move that leaves the shown order as it is saves nothing, and the list keeps it where it said", async () => {
    const view = mount([MAJORS]);
    await flush();
    fireEvent.click(within(dialog()).getByRole("tab", { name: "Columns" }));
    await flush();
    fireEvent.click(button("Move Rec down")); // the last shown column, past the first hidden one
    await flush();
    expect(view.server.writes()).toEqual([]);
    expect(said).toEqual(["Rec moved to position 10 of 17."]);
    const ids = (): (string | undefined)[] =>
      within(dialog())
        .getAllByRole("checkbox")
        .map((box) => box.closest<HTMLElement>("[data-column]")?.dataset["column"]);
    expect(ids().slice(7, 10)).toEqual(["spread_bps", "volume_24h", "rec"]);
    // shown now, the column lands where it stands: before Rec
    fireEvent.click(within(dialog()).getByRole("checkbox", { name: "Volume 24h" }));
    await flush();
    expect((view.server.writes()[0]?.body?.["columns"] as string[]).slice(-3)).toEqual([
      "spread_bps",
      "volume_24h",
      "rec",
    ]);
  });

  it("C-5335-11: closing mid-read lets the read go; a save in flight still lands and reaches the panel; no timer stays, the confirm open too", async () => {
    const pending = fakeServer([MAJORS]);
    let signal: AbortSignal | undefined;
    const answer = pending.fetch.getMockImplementation();
    pending.fetch.mockImplementationOnce(async (_url: RequestInfo | URL, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      // as `fetch` does: no answer until the signal aborts it
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    const reading = mount([], { server: pending });
    await flush();
    reading.unmount();
    expect(signal?.aborted).toBe(true);
    if (answer !== undefined) pending.fetch.mockImplementation(answer);

    const view = mount([MAJORS]);
    await flush();
    let land: (() => void) | undefined;
    const store = view.server.fetch.getMockImplementation();
    view.server.fetch.mockImplementationOnce(async (url: RequestInfo | URL, init?: RequestInit) => {
      await new Promise<void>((resolve) => {
        land = resolve;
      });
      return store === undefined ? json({ status: 500 }, 500) : store(url, init);
    });
    act(() => symbolCell("BTCUSDT").focus());
    fireEvent.keyDown(symbolCell("BTCUSDT"), { key: "ArrowDown", altKey: true });
    await flush();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "Delete" }); // the confirm open as it closes
    await flush();
    view.unmount();
    land?.();
    await flush();
    expect(view.heard).toContainEqual({
      kind: "stored",
      list: expect.objectContaining({ id: MAJORS.id, version: 2 }),
    });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("C-5335-12: Preview of a text with no symbol says so under the field instead of a bare preview", async () => {
    mount([MAJORS]);
    await flush();
    fireEvent.click(button("Paste symbols"));
    await flush();
    const area = within(dialog()).getByRole("textbox", { name: /^Paste symbols/ });
    fireEvent.change(area, { target: { value: "  # nothing here\n" } });
    fireEvent.click(button("Preview"));
    await flush();
    expect(within(dialog()).queryByRole("heading", { name: "Preview" })).toBeNull();
    expect(area).toHaveAttribute("aria-invalid", "true");
    expect(area).toHaveAccessibleDescription("This text has no symbols.");
    expect(said).toEqual(["This text has no symbols."]);
  });

  it("C-5335-02 / S-5335-01: a paste of 300 unknown symbols asks at most 20 lookups; a text past 64 KB is refused", async () => {
    // An index that learns a lookup's answer, as E08-S09's does: each "not listed" leaves the missing ones.
    let snapshot = fakeIndex().getSnapshot();
    const told = new Set<() => void>();
    const learning: InstrumentSource = {
      subscribe: (listener) => (told.add(listener), () => void told.delete(listener)),
      getSnapshot: () => snapshot,
      learn: (lookup) => {
        if (lookup.kind !== "not_listed") return;
        snapshot = { ...snapshot, unlisted: [...snapshot.unlisted, lookup.symbol] };
        told.forEach((listener) => listener());
      },
      reread: () => undefined,
    };
    mount([MAJORS], { instruments: learning });
    await flush();
    fireEvent.click(button("Paste symbols"));
    await flush();
    const area = within(dialog()).getByRole("textbox", { name: /^Paste symbols/ });
    expect(area).toHaveAttribute("maxlength", String(64 * 1024));
    const unknown = Array.from({ length: 300 }, (_, i) => `ZZ${String(i).padStart(3, "0")}USDT`);
    fireEvent.change(area, { target: { value: unknown.join("\n") } });
    fireEvent.click(button("Preview"));
    for (let i = 0; i < 20; i += 1) await flush(); // every lookup answered, and any it starts
    const lookups = apiFetch.mock.calls.filter(([url]) => url.startsWith("/api/v1/instruments/"));
    expect(lookups.length).toBeGreaterThan(0);
    expect(lookups.length).toBeLessThanOrEqual(20);
    fireEvent.change(area, { target: { value: "A".repeat(64 * 1024 + 1) } });
    fireEvent.click(button("Preview"));
    await flush();
    expect(said.at(-1)).toBe("Paste at most 64 KB of text.");
    expect(within(dialog()).queryByRole("heading", { name: "Preview" })).toBeNull();
  });

  it("A-5335-03: Tab from the paste preview's heading goes on to 'Add 2 symbols', never back to the dialog's first stop", async () => {
    mount([MAJORS]);
    await flush();
    fireEvent.click(button("Paste symbols"));
    await flush();
    fireEvent.change(within(dialog()).getByRole("textbox", { name: /^Paste symbols/ }), {
      target: { value: "DOTUSDT LTCUSDT" },
    });
    fireEvent.click(button("Preview"));
    await flush();
    const heading = within(dialog()).getByRole("heading", { name: "Preview" });
    expect(active()).toBe(heading);
    fireEvent.keyDown(heading, { key: "Tab" });
    expect(active()).toBe(button("Add 2 symbols"));
  });

  it("A-5335-02: keys typed in the manager never reach the window keymap: F2, Del and Alt+↓ raise no toast and say only the manager's words", async () => {
    render(<KeymapHost />);
    mount([MAJORS, SETUPS]);
    await flush();
    fireEvent.keyDown(option("Majors, 12 symbols"), { key: "F2" });
    await flush();
    expect(field()).toHaveValue("Majors");
    fireEvent.keyDown(field(), { key: "Escape" });
    await flush();
    act(() => symbolCell("BTCUSDT").focus());
    fireEvent.keyDown(symbolCell("BTCUSDT"), { key: "ArrowDown", altKey: true });
    await flush();
    fireEvent.keyDown(button("Paste symbols"), { key: "Delete" });
    fireEvent.keyDown(button("Paste symbols"), { key: "ArrowUp", altKey: true });
    await flush();
    expect(said).toEqual(["BTCUSDT moved to position 2 of 12."]);
    // SCR-015's region (portalled, outside the inert page): no toast at all
    expect(
      screen.queryByRole("region", { name: "Notifications", hidden: true })?.textContent ?? "",
    ).toBe("");
  });
});
