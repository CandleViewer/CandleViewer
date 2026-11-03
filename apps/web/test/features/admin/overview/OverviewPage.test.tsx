/**
 * E42-S01 (#1022): SCR-120 at R-300, inside the admin area (E42-D03 §6; the amended Gherkin). The
 * nine tiles resolve each on its own read (AC3), a degraded backend leaves the last-known values
 * marked stale with Retry and the shell usable (AC5), a `403` withdraws the area (BQ-8), the page
 * re-reads the overview every 30 s only while visible (BQ-5 as ruled for #5330), keeps focus a
 * re-read takes away inside its tile or strip, re-renders only what changed, and tears down.
 */
import { createRequire } from "node:module";
import type { JSX } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import {
  adminReads,
  CYCLE_READS,
  REREAD_MS,
} from "../../../../src/features/admin/overview/readStore";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { RENDER_MEASURE } from "../../../../src/features/admin/overview/OverviewPage";
import { AdminArea } from "../../../../src/features/admin/shell/AdminArea";
import { THEME_ANALYTICS_EVENT } from "../../../../src/shell/bootstrap/themeStore";
import { resetShellState, setShellState, type Me } from "../../../../src/shell/bootstrap/store";

// axe-core is a transitive dependency of @axe-core/playwright (as in AdminArea.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const AT = "2026-10-22T14:02:11Z";
const OVERVIEW = {
  generated_at: AT,
  users: { status: "ok", generated_at: AT, total: 9, active: 6, without_mfa: 1 },
  accounts: {
    status: "ok",
    generated_at: AT,
    total: 5,
    enabled: 5,
    keys_expiring_30d: 0,
    keys_invalid: 0,
  },
  recorder: { status: "error", detail: "timed out after 300 ms", generated_at: AT },
  storage: { status: "ok", generated_at: AT, used_bytes: 1e9, free_bytes: 9e9, days_until_full: 9 },
  trading: {
    status: "ok",
    generated_at: AT,
    live_enabled: false,
    kill_switch_engaged: false,
    open_positions: 0,
  },
  incidents: { status: "ok", generated_at: AT, open: 0 },
};
const BODIES: Readonly<Record<string, unknown>> = {
  "/api/v1/admin/overview": OVERVIEW,
  "/api/v1/admin/capacity": {
    subaccounts: { status: "ok", tier: "regular", cap: 5, used: 3, tier_source: "recorded" },
  },
  "/api/v1/admin/health": {
    overall: "healthy",
    server_time: AT,
    components: [{ name: "postgres", state: "healthy" }],
  },
  "/api/v1/admin/feature-flags": {
    resolution: "stored",
    items: [
      { key: "maintenance.mode", value: true, updated_at: "2026-10-22T14:00:00Z" },
      { key: "rules.graph_editor", value: true },
    ],
  },
  "/api/v1/admin/audit?limit=3": {
    chain_verified: true,
    items: [
      {
        id: 41,
        ts: AT,
        action: "admin.area_entered",
        outcome: "success",
        severity: "info",
        actor_username: "basiltt",
        subject_id: null,
        subject_type: null,
        detail: {},
      },
    ],
  },
  "/api/v1/admin/backups?limit=1": { code: "not_implemented" },
  "/api/v1/users/invites": { items: [{}] },
};
const STATUS: Readonly<Record<string, number>> = { "/api/v1/admin/backups?limit=1": 501 };

interface Wire {
  /** Each request's path and query, in order. */
  readonly paths: string[];
  /** The newest request's signal for `path`. */
  readonly signalOf: (path: string) => AbortSignal | undefined;
  /** Replies the next calls to `path` with `status` (and `body`), until changed. */
  readonly set: (path: string, status: number, body?: unknown) => void;
  /** Holds `path`'s answers until `release` is called. */
  readonly hold: (path: string) => () => void;
}

function serve(): Wire {
  const paths: string[] = [];
  const signals = new Map<string, AbortSignal>();
  const replies = new Map<string, { status: number; body: unknown }>();
  const held = new Map<string, Promise<void>>();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = String(input);
      paths.push(path);
      const signal = init.signal ?? undefined;
      if (signal) signals.set(path, signal);
      // A held answer waits, and rejects as a browser's fetch does once its signal aborts.
      const gate = held.get(path);
      if (gate) {
        const aborted = new Promise<never>((_resolve, reject) =>
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            {
              once: true,
            },
          ),
        );
        await Promise.race([gate, aborted]);
      }
      signal?.throwIfAborted();
      const reply = replies.get(path) ?? { status: STATUS[path] ?? 200, body: BODIES[path] };
      return new Response(JSON.stringify(reply.body ?? {}), {
        status: reply.status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return {
    paths,
    signalOf: (path) => signals.get(path),
    set: (path, status, body) => replies.set(path, { status, body }),
    hold: (path) => {
      let release = (): void => undefined;
      held.set(path, new Promise<void>((resolve) => (release = resolve)));
      return () => {
        held.delete(path);
        release();
      };
    },
  };
}

const OWNER = { role: "owner", permissions: [], accounts: [], user: { username: "owner.one" } };
const analytics: unknown[] = [];
const record = (event: Event): void => void analytics.push((event as CustomEvent).detail);

beforeEach(() => {
  adminReads.reset();
  clearAnnouncements();
  analytics.length = 0;
  window.addEventListener(THEME_ANALYTICS_EVENT, record);
  setShellState({ me: OWNER as unknown as Me, environment: "demo" });
});

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  window.removeEventListener(THEME_ANALYTICS_EVENT, record);
  adminReads.reset();
  clearAnnouncements();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** R-300 (or another admin route) as the shell holds it: inside its `main`, a router around it. */
function Overview({ routeId = "R-300" }: { readonly routeId?: string }): JSX.Element {
  return (
    <MemoryRouter>
      <InShellProvider>
        <main tabIndex={-1}>
          <AdminArea routeId={routeId} owner={null} />
        </main>
      </InShellProvider>
    </MemoryRouter>
  );
}

/** A route's render under host load can take seconds: each wait gets 5 s, each test 30 s. */
const WAIT = { timeout: 5_000 } as const;
const tile = (name: string | RegExp): HTMLElement => screen.getByRole("region", { name });
const findTile = (name: string | RegExp): Promise<HTMLElement> =>
  screen.findByRole("region", { name }, WAIT);
/** Lets every pending read answer and React render it, under fake timers. */
const flush = (ms = 0): Promise<void> =>
  act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
/** The analytics events of one name, in order. */
const events = (name: string): unknown[] =>
  analytics.filter((e) => (e as { name: string }).name === name);
/** The strip's region, or null when no strip is drawn. */
const stripRegion = (): HTMLElement | null =>
  screen.queryByRole("region", { name: "Needs your action" });
/** An audit entry as the server pins it (the overview's own read writes such rows). */
const auditEntry = (id: number) => ({
  id,
  ts: AT,
  action: "admin.area_entered",
  outcome: "success",
  severity: "info",
  actor_username: "basiltt",
  subject_id: null,
  subject_type: null,
  detail: {},
});
/** The overview as the server answers at `ms`: it and every slice stamped with that time. */
const overviewAt = (ms: number): Record<string, unknown> => {
  const stamp = new Date(ms).toISOString();
  const body: Record<string, unknown> = { generated_at: stamp };
  for (const [name, slice] of Object.entries(OVERVIEW)) {
    if (typeof slice === "object") body[name] = { ...slice, generated_at: stamp };
  }
  return body;
};
/** The CMP-036 row labelled `label` in `host`. */
const rowOf = (host: HTMLElement, label: string): HTMLElement => {
  const row = within(host)
    .getByText(label, { selector: "dt" })
    .closest<HTMLElement>('[data-cmp="CMP-036"]');
  if (row === null) throw new Error(`"${label}" has no row`);
  return row;
};

describe("SCR-120 at R-300 (E42-S01)", { timeout: 30_000 }, () => {
  it("renders the overview in the admin area: its h1 and as-of, three bands, nine tiles, the strip", async () => {
    serve();
    render(<Overview />);
    const users = await findTile("Users");
    await waitFor(() => expect(within(users).getByText("Total")).toBeInTheDocument(), WAIT);
    const main = screen.getByRole("main");
    expect(within(main).getByRole("region", { name: "Admin area" })).toHaveTextContent(
      "◆ Admin area · Overview",
    );
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual([
      "Overview",
    ]);
    await waitFor(
      () => expect(screen.getByText("All times UTC · as of 14:02:11")).toBeInTheDocument(),
      WAIT,
    );
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Right now",
      "People and access",
      "Evidence and controls",
    ]);
    expect(main.querySelectorAll('[data-cmp="CMP-178"]')).toHaveLength(9);
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent?.replace(/\s+/g, " ")),
    ).toEqual([
      "Trading safety DEMO",
      "Health",
      "Recorder and storage",
      "Users",
      "Accounts and keys DEMO",
      "Profiles and limits",
      "Audit",
      "Security and backups",
      "Flags",
    ]);
    // The strip names the one served item, and the footer says the entry was recorded (D27).
    const strip = within(main).getByRole("region", { name: "Needs your action" });
    expect(within(strip).getByRole("link")).toHaveAccessibleName(
      "Attention: 1 active user without two-factor → Users",
    );
    expect(within(strip).getByRole("link")).toHaveAttribute("href", "/admin/users");
    expect(
      screen.getByText("Entering this area was recorded — Area entered (admin.area_entered)"),
    ).toBeInTheDocument();
  });

  it("resolves each tile on its own read: the recorder errs, the rest read, Health still waits (AC3)", async () => {
    const wire = serve();
    const releaseHealth = wire.hold("/api/v1/admin/health");
    render(<Overview />);
    const recorder = await findTile("Recorder and storage");
    await waitFor(() => expect(recorder).toHaveTextContent("Error — timed out after 300 ms"), WAIT);
    expect(within(recorder).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    // Every other tile has its value while Health's read is still out.
    expect(tile("Users")).toHaveTextContent("Total9");
    expect(tile(/^Trading safety/)).toHaveTextContent("Kill switchoff");
    expect(tile(/^Accounts and keys/)).toHaveTextContent("3 of 5 sub-accounts used · Regular tier");
    expect(tile("Flags")).toHaveTextContent("Enabled2");
    expect(tile("Audit")).toHaveTextContent("Area entered (admin.area_entered)");
    expect(tile("Health").closest('[data-cmp="CMP-178"]')).toHaveAttribute("aria-busy", "true");
    expect(analytics).toContainEqual({ name: "admin.overview_viewed" });
    expect(
      analytics.filter((e) => (e as { name: string }).name === "admin.overview_rendered"),
    ).toEqual([]);
    // jsdom's Performance may lack User Timing: an own stub shadows whatever it has.
    const measure = vi.fn();
    Object.defineProperty(performance, "measure", { value: measure, configurable: true });
    releaseHealth();
    await waitFor(() => expect(tile("Health")).toHaveTextContent("ok"), WAIT);
    await waitFor(
      () =>
        expect(analytics).toContainEqual({
          name: "admin.overview_rendered",
          ms: expect.any(Number),
        }),
      WAIT,
    );
    expect(measure).toHaveBeenCalledWith(
      RENDER_MEASURE,
      expect.objectContaining({ start: expect.any(Number), end: expect.any(Number) }),
    );
    Reflect.deleteProperty(performance, "measure");
  });

  it("keeps the last-known values marked stale with Retry when the overview answers 503 (AC5)", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    const wire = serve();
    render(<Overview />);
    await flush();
    expect(tile("Users")).toHaveTextContent("Total9");
    wire.set("/api/v1/admin/overview", 503, { code: "audit_unavailable" });
    await flush(REREAD_MS);
    const users = tile("Users");
    expect(users).toHaveTextContent("stale since 14:02:41");
    expect(users).toHaveTextContent("Total9"); // the value stays, marked old (D02 D4)
    // The tile's own "as of" gives way to "stale since"; the pending-invites line, read once per
    // entry, keeps its own read time (the tile's "as of" is the one without "UTC", C-5330-11).
    expect(users).not.toHaveTextContent(/as of \d\d:\d\d:\d\d(?! UTC)/);
    expect(rowOf(users, "Invites pending")).toHaveTextContent("as of 14:02:11 UTC");
    expect(within(users).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    // Trading safety keeps no switch state from an old read.
    expect(tile(/^Trading safety/)).toHaveTextContent("Error — the server answered 503");
    expect(tile(/^Trading safety/)).toHaveTextContent("Kill switchunknown");
    // The strip shows nothing from the kept counts: no item it can't mark old, no all-clear (A-06).
    expect(stripRegion()).toBeNull();
    // The shell stays usable: the band, its links and the page's other tiles.
    expect(screen.getByRole("region", { name: "Admin area" })).toBeInTheDocument();
    expect(tile("Flags")).toHaveTextContent("Enabled2");
    // Retry reads again now, this tile shown loading, and a good answer clears the stale mark.
    wire.set("/api/v1/admin/overview", 200, OVERVIEW);
    const before = wire.paths.length;
    await act(async () => {
      fireEvent.click(within(users).getByRole("button", { name: "Retry" }));
    });
    expect(wire.paths.slice(before)).toEqual(["/api/v1/admin/overview"]);
    await flush();
    expect(tile("Users")).toHaveTextContent("as of 14:02:11");
    expect(within(stripRegion() ?? document.body).getByRole("link")).toHaveAttribute(
      "href",
      "/admin/users",
    );
  });

  it("keeps a pressed Retry focused and busy through its read; the heading link only after a good one", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    const wire = serve();
    wire.set("/api/v1/admin/overview", 503, { code: "audit_unavailable" });
    render(<Overview />);
    await flush();
    const users = tile("Users");
    const retry = within(users).getByRole("button", { name: "Retry" });
    act(() => retry.focus());
    // A failed answer: the same Retry stays, busy while its read runs, and keeps focus (A-5330-01).
    let release = wire.hold("/api/v1/admin/overview");
    await act(async () => {
      fireEvent.click(retry);
    });
    expect(users.closest('[data-cmp="CMP-178"]')).toHaveAttribute("aria-busy", "true");
    expect(retry).toHaveAttribute("aria-busy", "true");
    expect(document.activeElement).toBe(retry);
    release();
    await flush();
    expect(tile("Users")).toHaveTextContent("Error — the server answered 503");
    expect(document.activeElement).toBe(retry);
    // A good answer drops Retry: only now does its focus go to the tile's heading link.
    wire.set("/api/v1/admin/overview", 200, OVERVIEW);
    release = wire.hold("/api/v1/admin/overview");
    await act(async () => {
      fireEvent.click(retry);
    });
    expect(document.activeElement).toBe(retry);
    release();
    await flush();
    expect(within(tile("Users")).queryByRole("button", { name: "Retry" })).toBeNull();
    expect(document.activeElement).toBe(within(tile("Users")).getByRole("link", { name: "Users" }));
  });

  it("gives a tile's heading link the focus of a row a re-read takes out (A-5330-02)", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    const wire = serve();
    const audit = (ids: number[]) => ({ chain_verified: true, items: ids.map(auditEntry) });
    wire.set("/api/v1/admin/audit?limit=3", 200, audit([41, 42, 43]));
    render(<Overview />);
    await flush();
    // An audit row: a re-read answers three new entries (no tile shows it loading).
    const rows = within(tile("Audit")).getAllByRole("link");
    expect(rows).toHaveLength(4);
    act(() => rows[2]?.focus());
    wire.set("/api/v1/admin/audit?limit=3", 200, audit([51, 52, 53]));
    await act(async () => adminReads.retry(["audit"], "test"));
    await flush();
    expect(document.activeElement).toBe(within(tile("Audit")).getByRole("link", { name: "Audit" }));
    // The maintenance link, when a re-read finds the flag off.
    const trading = tile(/^Trading safety/);
    act(() =>
      within(trading)
        .getByRole("link", { name: /Maintenance/ })
        .focus(),
    );
    wire.set("/api/v1/admin/feature-flags", 200, { resolution: "stored", items: [] });
    await act(async () => adminReads.retry(["flags"], "test"));
    await flush();
    expect(document.activeElement).toBe(
      within(trading).getByRole("link", { name: "Trading safety" }),
    );
  });

  it("gives the strip's focus to the next pill, then to its line, as a re-read clears items", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    const wire = serve();
    const overview = (withoutMfa: number, keysInvalid: number) => ({
      ...OVERVIEW,
      users: { ...OVERVIEW.users, without_mfa: withoutMfa },
      accounts: { ...OVERVIEW.accounts, keys_invalid: keysInvalid },
    });
    wire.set("/api/v1/admin/overview", 200, overview(1, 1));
    render(<Overview />);
    await flush();
    const [first] = within(stripRegion() ?? document.body).getAllByRole("link");
    act(() => first?.focus());
    wire.set("/api/v1/admin/overview", 200, overview(0, 1));
    await flush(REREAD_MS);
    const [next, ...rest] = within(stripRegion() ?? document.body).getAllByRole("link");
    expect(rest).toEqual([]);
    expect(next).toHaveAccessibleName(/^Attention: 1 key rejected by Bybit/);
    expect(document.activeElement).toBe(next);
    wire.set("/api/v1/admin/overview", 200, overview(0, 0));
    await flush(REREAD_MS);
    expect(document.activeElement).toBe(screen.getByText("Nothing needs your action"));
  });

  it("withdraws the area on a 403: the band unmounts and 'Your access changed' links back", async () => {
    const wire = serve();
    wire.set("/api/v1/admin/health", 403, {
      code: "forbidden",
      instance: "urn:cv:req:5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f",
    });
    render(<Overview />);
    const h1 = await screen.findByRole("heading", { level: 1, name: "Your access changed" }, WAIT);
    expect(screen.queryByRole("region", { name: "Admin area" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Needs your action" })).toBeNull();
    expect(screen.getByRole("link", { name: "Back to your workspace" })).toHaveAttribute(
      "href",
      "/terminal",
    );
    expect(screen.getByText("Ref urn:cv:req:5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f")).toBeVisible();
    expect(document.activeElement).toBe(h1);
    expect(analytics).toContainEqual({ name: "error.403_shown", variant: "withdrawn" });
  });

  it("tabs through the strip, then each tile: heading link, its rows' links, Retry; no tab index", async () => {
    serve();
    render(<Overview />);
    await waitFor(() => expect(tile("Recorder and storage")).toHaveTextContent("Error"), WAIT);
    await waitFor(() => expect(tile("Audit")).toHaveTextContent("Area entered"), WAIT);
    const main = screen.getByRole("main");
    const stops = [...main.querySelectorAll<HTMLElement>("a[href], button")].map(
      (el) => el.textContent?.replace(/\s+/g, " ").trim() ?? "",
    );
    expect(main.querySelector("[tabindex]:not([tabindex='-1'])")).toBeNull();
    expect(stops).toEqual([
      "Attention: 1 active user without two-factor → Users",
      "Trading safety",
      "ON since 14:00 UTC → Maintenance",
      "Health",
      "Recorder and storage",
      "Retry",
      "Users",
      "Accounts and keys",
      "Profiles and limits",
      "Audit",
      expect.stringMatching(/^2026-10-22 14:02:11 UTC · basiltt · Area entered/),
      "Security and backups",
      "Flags",
    ]);
  });

  it.each(["dark", "light"])(
    "has no serious axe violation in the %s theme",
    { timeout: 60_000 },
    async (theme) => {
      document.documentElement.setAttribute("data-theme", theme);
      serve();
      render(<Overview />);
      await waitFor(() => expect(tile("Audit")).toHaveTextContent("Area entered"), WAIT);
      // jsdom has no layout: contrast is the real-browser collectors' (e2e/admin, e2e/a11y)
      const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
      expect(
        res.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
    },
  );
});

describe("SCR-120's re-read (BQ-5)", { timeout: 30_000 }, () => {
  // The orchestrator's ruling on BQ-5 for #5330 (S-5330-02, C-5330-03): the cycle is the overview's;
  // every other read is asked once per entry and on Retry.
  it("re-reads the overview every 30 s in one chained timer, and nothing else", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    const wire = serve();
    render(<Overview />);
    await flush();
    expect(wire.paths.slice().sort()).toEqual(Object.keys(BODIES).sort());
    expect(vi.getTimerCount()).toBe(1);
    const before = wire.paths.length;
    await flush(REREAD_MS - 1);
    expect(wire.paths.length).toBe(before);
    await flush(1);
    expect(wire.paths.slice(before)).toEqual(["/api/v1/admin/overview"]);
    await flush(REREAD_MS);
    expect(wire.paths.slice(before)).toEqual(["/api/v1/admin/overview", "/api/v1/admin/overview"]);
    expect(vi.getTimerCount()).toBe(1);
  });

  // C-5330-11: Maintenance (`flags`), Invites pending (`invites`) and the capacity line (`capacity`)
  // are entry snapshots under tiles whose "as of" is the cycled overview's. Each prints its own read
  // time, "as of hh:mm:ss UTC"; the cycle, still the overview alone (one `admin.area_entered` row
  // per tick), never moves it, and only that read's own answer does.
  it("prints each entry-snapshot line's own read time, which the cycle leaves where it was", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT)); // 14:02:11
    const wire = serve();
    render(<Overview />);
    await flush();
    const capacity = (): HTMLElement =>
      within(tile(/^Accounts and keys/)).getByText(/^3 of 5 sub-accounts used/);
    const own = (hms: string): void => {
      const mark = `as of ${hms} UTC`;
      expect(rowOf(tile(/^Trading safety/), "Maintenance")).toHaveTextContent(mark);
      expect(rowOf(tile("Users"), "Invites pending")).toHaveTextContent(mark);
      expect(capacity()).toHaveTextContent(`3 of 5 sub-accounts used · Regular tier ${mark}`);
    };
    own("14:02:11");
    // Five minutes: the overview answers ten more times, each stamped as the server stamps it.
    const before = wire.paths.length;
    for (let tick = 0; tick < 10; tick += 1) {
      wire.set("/api/v1/admin/overview", 200, overviewAt(Date.now() + REREAD_MS));
      await flush(REREAD_MS);
    }
    expect(CYCLE_READS).toEqual(["overview"]);
    expect(wire.paths.slice(before)).toEqual(
      Array.from({ length: 10 }, () => "/api/v1/admin/overview"),
    );
    // The tiles' own "as of" is the overview's, now 14:07:11; the three lines keep their own.
    expect(tile("Users")).toHaveTextContent(/as of 14:07:11(?! UTC)/);
    expect(tile(/^Trading safety/)).toHaveTextContent(/as of 14:07:11(?! UTC)/);
    expect(tile(/^Accounts and keys/)).toHaveTextContent(/as of 14:07:11(?! UTC)/);
    own("14:02:11");
    // A line's own read answering again moves its time, and only its own.
    await act(async () => adminReads.retry(["flags"], "test"));
    await flush();
    expect(rowOf(tile(/^Trading safety/), "Maintenance")).toHaveTextContent("as of 14:07:11 UTC");
    expect(rowOf(tile("Users"), "Invites pending")).toHaveTextContent("as of 14:02:11 UTC");
    expect(capacity()).toHaveTextContent("Regular tier as of 14:02:11 UTC");
  });

  it("pauses while the document is hidden and reads at once when it shows again", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    const wire = serve();
    render(<Overview />);
    await flush();
    const before = wire.paths.length;
    let shown: DocumentVisibilityState = "hidden";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => shown });
    try {
      document.dispatchEvent(new Event("visibilitychange"));
      expect(vi.getTimerCount()).toBe(0);
      await flush(REREAD_MS * 3);
      expect(wire.paths.length).toBe(before);
      shown = "visible";
      document.dispatchEvent(new Event("visibilitychange"));
      await flush();
      expect(wire.paths.slice(before)).toEqual(["/api/v1/admin/overview"]);
    } finally {
      Reflect.deleteProperty(document, "visibilityState");
    }
  });

  it("measures no render for a return within the area: its answers were there (C-5330-02)", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    serve();
    const view = render(<Overview />);
    await flush();
    expect(events("admin.overview_rendered")).toHaveLength(1);
    view.rerender(<Overview routeId="R-301" />); // the strip still holds the area's reads
    await flush();
    view.rerender(<Overview />);
    await flush();
    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(events("admin.overview_viewed")).toHaveLength(2);
    expect(events("admin.overview_rendered")).toHaveLength(1);
  });

  it("drops every answer on leaving the area: the next visit loads, reads and measures afresh", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse(AT));
    const wire = serve();
    const first = render(<Overview />);
    await flush();
    first.unmount();
    await flush();
    expect(adminReads.getState().overview).toEqual({ phase: "idle", inFlight: false });
    const before = wire.paths.length;
    const release = wire.hold("/api/v1/admin/overview");
    render(<Overview />);
    await flush();
    // Cold: Trading safety loads, showing no "off" from the last visit, and every read is asked.
    expect(tile(/^Trading safety/).closest('[data-cmp="CMP-178"]')).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(wire.paths.slice(before).sort()).toEqual(Object.keys(BODIES).sort());
    release();
    await flush();
    expect(tile(/^Trading safety/)).toHaveTextContent("Kill switchoff");
    expect(events("admin.overview_rendered")).toHaveLength(2);
  });

  it("tears down on leaving: the read in flight aborts, and no timer is left", async () => {
    vi.useFakeTimers();
    const wire = serve();
    wire.hold("/api/v1/admin/health");
    const view = render(<Overview />);
    await flush();
    expect(wire.signalOf("/api/v1/admin/health")?.aborted).toBe(false);
    view.unmount();
    await flush();
    expect(wire.signalOf("/api/v1/admin/health")?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    const count = wire.paths.length;
    await flush(REREAD_MS * 2);
    expect(wire.paths.length).toBe(count);
  });
});
