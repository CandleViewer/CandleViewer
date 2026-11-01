/**
 * E16-S04, SCR-142's section (E16-D04 §2–§5, §10; E16-D06 KB-14, FM-14, RG-13, SR-27, SR-35, T2-09, T2-12, §13
 * "Reading the picture"; F-05, F-14; BQ-5, BQ-8, BQ-13): the page states as named RTL fixtures, each with axe (no
 * page-state Storybook, BQ-13), over a stubbed `apiFetch` (fetch doubles from `22`'s examples) and fake timers; no
 * network (C-13.5). The section reads `/recording/storage` and `/admin/health` on entry and every 60 s, never a
 * figure computed for it; its one polite region says the turn to stale once.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import {
  registerRecorderExtensions,
  type StoragePanelProps,
} from "../../../../src/features/recorder/extensions";
import type { HealthReport, StorageUsage } from "../../../../src/features/recorder/recorderApi";
import {
  StoragePanel,
  type StoragePanelOptions,
} from "../../../../src/features/recorder/storage/StoragePanel";
import { STORAGE_DECK } from "../../../../src/features/recorder/storage/storageCopy";
import {
  CLOCK,
  HEALTH,
  LEVEL_1,
  LEVEL_2,
  LEVEL_3,
  QUESTDB_DOWN,
  REPORT,
  STATUS,
  VOLUME_REFUSED,
  frameWith,
} from "./storageFixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const HEADING = "cv-recorder-storage";
const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const unavailable = () =>
  json(503, { code: "store_unavailable", status: 503, title: "x", type: "about:blank" });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

type Route = (method: string, url: string) => Response | undefined;
type Answer = () => Response | Promise<Response>;
let storageAnswer: Answer = () => json(200, REPORT);
let healthAnswer: Answer = () => json(200, HEALTH);
/** An answer held until the test lets it land. */
function held(): { readonly answer: Answer; readonly land: (response: Response) => void } {
  let land: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((resolve) => {
    land = resolve;
  });
  return { answer: () => pending, land: (response) => land(response) };
}

/** The section's reads by path; `over` answers first. */
function serve(over: Route = () => undefined) {
  return async (url: string, init?: RequestInit): Promise<Response> => {
    const method = init?.method ?? "GET";
    const first = over(method, url);
    if (first !== undefined) return first;
    const path = url.replace("/api/v1", "");
    if (path === "/recording/storage") return storageAnswer();
    if (path === "/admin/health") return healthAnswer();
    return json(404, { code: "not_found", status: 404, title: "x", type: "about:blank" });
  };
}
const calls = (): string[] =>
  apiFetch.mock.calls.map(
    ([url, init]) => `${init?.method ?? "GET"} ${url.replace("/api/v1", "")}`,
  );

let reported: unknown[] = [];
const onAnalytics = (event: Event): void => void reported.push((event as CustomEvent).detail);

type PanelProps = Partial<StoragePanelProps & StoragePanelOptions>;
const base: StoragePanelProps = {
  headingId: HEADING,
  status: STATUS,
  storage: null,
  frame: frameWith(),
  stale: false,
};

function panel(props: PanelProps = {}) {
  return (
    <MemoryRouter>
      <StoragePanel {...base} {...props} />
      <ShellAnnouncer />
    </MemoryRouter>
  );
}
async function mount(props: PanelProps = {}, over?: Route) {
  apiFetch.mockImplementation(serve(over));
  const view = render(panel(props));
  await flush();
  return view;
}

const section = (): HTMLElement => screen.getByRole("region", { name: "Storage and database" });
/** RG-13: the section's one polite region. */
const region = (): HTMLElement =>
  section().querySelector(':scope > [role="status"][aria-live="polite"]') as HTMLElement;
function utterances(): () => string[] {
  const said: string[] = [];
  const observer = new MutationObserver(() => {
    const text = region().textContent ?? "";
    if (text !== "" && said.at(-1) !== text) said.push(text);
  });
  observer.observe(region(), { childList: true, subtree: true, characterData: true });
  return () => said;
}
const card = (title: string): HTMLElement =>
  screen
    .getByRole("heading", { level: 3, name: new RegExp(`^${title}`) })
    .closest("[data-cmp='CMP-050']") as HTMLElement;
/** A card's rows as "term: definition", the definition as read (an aria-hidden "—" left out). */
function rowsOf(host: HTMLElement): Record<string, string> {
  const terms = within(host).getAllByRole("term");
  const defs = within(host).getAllByRole("definition");
  return Object.fromEntries(
    terms.map((term, i) => {
      const def = defs[i]?.cloneNode(true) as HTMLElement;
      def.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
      return [term.textContent ?? "", (def.textContent ?? "").trim()];
    }),
  );
}
/** The definition of a card's row `term`, as rendered (its glyph included). */
function definitionOf(host: HTMLElement, term: string): HTMLElement {
  const at = within(host)
    .getAllByRole("term")
    .findIndex((node) => node.textContent === term);
  return within(host).getAllByRole("definition")[at] as HTMLElement;
}
async function seriousAxe(element: Element): Promise<unknown[]> {
  vi.useRealTimers();
  const res = await axe.run(element, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: CLOCK,
  });
  storageAnswer = () => json(200, REPORT);
  healthAnswer = () => json(200, HEALTH);
  reported = [];
  window.addEventListener("cv:analytics", onAnalytics);
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  act(() => clearAnnouncements());
  apiFetch.mockReset();
  vi.useRealTimers();
});

// A cold first mount takes several seconds on a loaded host; each case gets the axe tests' budget.
const CASE = { timeout: 30_000 } as const;

describe(
  "SCR-142/healthy: reading the picture (AC 1, AC 2; D06 §13 'Reading the picture')",
  CASE,
  () => {
    it("the heading names the section; the stamp names the sample; two meters name their denominators", async () => {
      const { container } = await mount();
      expect(
        screen.getByRole("heading", { level: 2, name: "Storage and database" }),
      ).toHaveAttribute("id", HEADING);
      expect(section()).toHaveTextContent("Sampled 10:31:03 UTC (every 60 s)");
      expect(screen.getByRole("meter", { name: "Recording budget" })).toHaveAttribute(
        "aria-valuetext",
        "1,188.0 GB of 2,000.0 GB (59.4 %)",
      );
      expect(screen.getByRole("meter", { name: "Disk volume" })).toHaveAttribute(
        "aria-valuetext",
        "1.2 TB of 4.0 TB (30.1 %), 2.8 TB free",
      );
      expect(section()).toHaveTextContent("Growing · auto-record pauses in about 422 days");
      expect(section()).toHaveTextContent(STORAGE_DECK["storage.projection"][1]);
      expect(section()).toHaveTextContent(STORAGE_DECK["storage.formula"][1]);
      expect(section()).toHaveTextContent(STORAGE_DECK["storage.scale"][0]);
      expect(section()).not.toHaveTextContent("Recording pauses before trading is affected.");
      expect(section().querySelector("[data-cmp='CMP-239']")).toBeNull();
      expect(await seriousAxe(container)).toEqual([]);
    });

    it("growth 0 after days of the page's history reads Steady, as SCR-140's card does (C-486P3-02)", async () => {
      const flat = frameWith({ daily_growth_bytes: 0, projected_full_at_ms: null });
      const view = await mount({ frame: flat, historySinceMs: CLOCK - 3 * 86_400_000 });
      expect(section()).toHaveTextContent("Steady · usage is not growing");
      expect(section()).not.toHaveTextContent("Too early to project");
      view.rerender(panel({ frame: flat, historySinceMs: CLOCK - 30 * 60_000 }));
      expect(section()).toHaveTextContent("Too early to project");
    });

    it("three tier cards with size, share, retention, the all-tiers fallbacks and health as text, every figure with its unit", async () => {
      await mount();
      expect(rowsOf(card("QuestDB · hot"))).toEqual({
        Size: "640.0 GB",
        "Share of budget": "32.0 %",
        Retention: "7 d",
        "Growth/day": "all tiers 1.45 GB/day",
        "Projected full": "all tiers 2028-03-27",
        Health: "healthy",
        Ingestion: "Ingest 18,400 msg/s, backlog 0 rows, lag —",
      });
      expect(rowsOf(card("Parquet/DuckDB · cold"))).toEqual({
        Size: "548.0 GB",
        "Share of budget": "27.4 %",
        Retention: "30 d",
        "Growth/day": "all tiers 1.45 GB/day",
        "Projected full": "all tiers 2028-03-27",
        Health: "healthy",
        "Last compaction": "weekly, Sundays 03:00 UTC",
      });
      expect(rowsOf(card("Postgres · relational"))).toEqual({
        Size: "16.0 GB",
        "Share of budget": "not counted",
        Retention: "no value",
        "Growth/day": "all tiers 1.45 GB/day",
        "Projected full": "all tiers 2028-03-27",
        Health: "healthy",
        "Last vacuum": "no value",
        Migration: "1.0.0",
      });
      expect(section()).toHaveTextContent("Row counts by table are not produced yet");
      expect(section()).toHaveTextContent("Slowest queries are not produced yet");
      // AC 1: health is a word with its glyph, never colour alone (C-486P3-06).
      for (const title of ["QuestDB · hot", "Parquet/DuckDB · cold", "Postgres · relational"]) {
        const glyph = definitionOf(card(title), "Health").querySelector("svg[data-icon]");
        expect(glyph).toHaveAttribute("data-icon", "success");
      }
    });

    it("the per-symbol table and its attribution line (D04 §4 TIER/per-symbol; D04-CG3)", async () => {
      await mount();
      const table = screen.getByRole("table", { name: "Per-symbol breakdown for the hot tier" });
      expect(
        within(table)
          .getAllByRole("columnheader")
          .map((h) => h.textContent),
      ).toEqual(["Symbol", "Size", "Growth/day", "Share of budget", "Pinned"]);
      const [, btc, eth] = within(table).getAllByRole("row");
      expect(btc).toHaveTextContent("BTCUSDT812.3 GB780 MB/day40.6 %pinned");
      expect(eth).toHaveTextContent("ETHUSDT1.2 GB520 MB/day0.1 %");
      expect(within(eth as HTMLElement).getByText("not pinned")).toHaveClass("cv-visually-hidden");
      expect(within(table).queryByRole("button")).toBeNull();
      expect(section()).toHaveTextContent(STORAGE_DECK["storage.symbols.attributed"][1]);
    });

    it("the System health link and no store console (E16-D06 §20.3 (ix))", async () => {
      await mount();
      const link = screen.getByRole("link", { name: "System health →" });
      expect(link).toHaveAttribute("href", "/admin/health");
      const hrefs = within(section())
        .queryAllByRole("link")
        .map((a) => a.getAttribute("href"));
      expect(hrefs).toEqual(["/admin/health"]);
      expect(section().innerHTML).not.toMatch(/:\d{4,5}\b|questdb:\/\/|postgres(ql)?:\/\/|jdbc:/i);
    });

    it("reports the panel once per entry (D04-D10)", async () => {
      const view = await mount();
      view.rerender(panel({ frame: frameWith({ used_bytes: 1189000000000 }) }));
      await flush();
      expect(reported).toEqual([{ name: "storage.panel_viewed" }]);
    });
  },
);

describe("the reads: sampled, never computed on request (AC 2; D04 §3; C-w)", CASE, () => {
  it("reads storage and health on entry and every 60 s, and nothing else", async () => {
    await mount();
    expect(calls()).toEqual(["GET /recording/storage", "GET /admin/health"]);
    await advance(60_000);
    expect(calls()).toEqual([
      "GET /recording/storage",
      "GET /admin/health",
      "GET /recording/storage",
      "GET /admin/health",
    ]);
  });

  it("a new sample replaces the figures and the stamp silently", async () => {
    await mount();
    const said = utterances();
    storageAnswer = () =>
      json(200, {
        ...REPORT,
        generated_at: "2026-09-14T10:32:03.000Z",
        tiers: [
          { tier: "questdb", used_bytes: 641000000000, retention_days: 7 },
          ...(REPORT.tiers ?? []).slice(1),
        ],
      } satisfies StorageUsage);
    await advance(60_000);
    expect(section()).toHaveTextContent("Sampled 10:32:03 UTC (every 60 s)");
    expect(rowsOf(card("QuestDB · hot")).Size).toBe("641.0 GB");
    expect(said()).toEqual([]);
  });

  it("the page's first read seeds the section and a newer own read wins", async () => {
    await mount({ storage: { ...REPORT, generated_at: "2026-09-14T10:30:03.000Z" } });
    expect(section()).toHaveTextContent("Sampled 10:31:03 UTC (every 60 s)");
  });

  it("stops reading once unmounted (teardown)", async () => {
    const view = await mount();
    view.unmount();
    apiFetch.mockClear();
    await advance(180_000);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("the storage answer shows as it lands, while health is still unanswered (C-486P3-07)", async () => {
    healthAnswer = held().answer;
    await mount();
    expect(screen.getByRole("meter", { name: "Recording budget" })).toBeVisible();
    expect(section()).toHaveTextContent("Sampled 10:31:03 UTC (every 60 s)");
    expect(rowsOf(card("QuestDB · hot"))["Health"]).toBe("not reported");
  });

  it("an older answer landing late never steps the sample back (C-486P3-07)", async () => {
    storageAnswer = unavailable;
    await mount();
    await advance(55_000);
    const late = held();
    storageAnswer = late.answer;
    fireEvent.click(within(section()).getByRole("button", { name: "Retry" }));
    await flush();
    storageAnswer = () => json(200, { ...REPORT, generated_at: "2026-09-14T10:33:03.000Z" });
    await advance(5_000); // the 60 s read is answered first
    expect(section()).toHaveTextContent("Sampled 10:33:03 UTC (every 60 s)");
    await act(async () => late.land(json(200, REPORT)));
    await flush();
    expect(section()).toHaveTextContent("Sampled 10:33:03 UTC (every 60 s)");
    expect(section()).not.toHaveTextContent("Disk figures could not be loaded.");
  });

  it("a failed health read keeps the last words, tagged stale, until one is answered (C-486P3-07)", async () => {
    await mount();
    healthAnswer = unavailable;
    await advance(60_000);
    for (const title of ["QuestDB · hot", "Parquet/DuckDB · cold", "Postgres · relational"]) {
      expect(rowsOf(card(title))["Health"]).toBe("healthy stale");
    }
    healthAnswer = () => json(200, HEALTH);
    await advance(60_000);
    expect(rowsOf(card("QuestDB · hot"))["Health"]).toBe("healthy");
  });

  it("a stale topic tags what the section takes from its frame (C-486P3-08)", async () => {
    const view = await mount();
    view.rerender(panel({ stale: true }));
    await flush();
    expect(rowsOf(card("QuestDB · hot"))["Ingestion"]).toBe(
      "Ingest 18,400 msg/s, backlog 0 rows, lag — stale",
    );
    // The meters' tag and the Ingestion row's: the sample's own figures are current.
    expect(within(section()).getAllByText("stale")).toHaveLength(2);
    view.rerender(panel({ stale: false }));
    await flush();
    expect(within(section()).queryByText("stale")).toBeNull();
  });
});

describe("SCR-142/loading and SCR-142/unavailable (D04 §5)", CASE, () => {
  it("loading: 'Sampling…', the region busy, nothing claimed", async () => {
    apiFetch.mockImplementation(() => new Promise<Response>(() => undefined));
    const { container } = render(panel());
    await flush();
    expect(section()).toHaveTextContent("Sampling…");
    expect(section().querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("unavailable: the banner names the part with Retry; the health cards stay; the last stamp in its stale form", async () => {
    storageAnswer = unavailable;
    const { container } = await mount({ storage: REPORT });
    expect(section()).toHaveTextContent("Disk figures could not be loaded.");
    expect(section()).toHaveTextContent("Sampled 10:31:03 UTC, stale (1 s old)");
    expect(within(section()).queryByRole("alert")).toBeNull();
    expect(section().querySelectorAll('[role="status"]')).toHaveLength(1);
    expect(rowsOf(card("QuestDB · hot")).Health).toBe("healthy");
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("unavailable with no report: the banner, no stamp, no figures; Retry's success lands on the heading", async () => {
    storageAnswer = unavailable;
    await mount();
    expect(section()).toHaveTextContent("Disk figures could not be loaded.");
    expect(section()).not.toHaveTextContent("Sampled");
    expect(screen.queryByRole("meter")).toBeNull();
    storageAnswer = () => json(200, REPORT);
    const retry = within(section()).getByRole("button", { name: "Retry" });
    act(() => retry.focus());
    fireEvent.click(retry);
    await flush();
    expect(section()).not.toHaveTextContent("Disk figures could not be loaded.");
    expect(screen.getByRole("heading", { level: 2, name: "Storage and database" })).toHaveFocus();
  });

  it("unavailable with no report: axe (C-486P3-06)", async () => {
    storageAnswer = unavailable;
    const { container } = await mount();
    expect(section()).toHaveTextContent("Disk figures could not be loaded.");
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("a first read that fails says so once; a failed Retry says nothing more (A-486P3-07)", async () => {
    storageAnswer = unavailable;
    apiFetch.mockImplementation(serve());
    render(panel());
    const said = utterances();
    await flush();
    expect(said()).toEqual(["Disk figures could not be loaded."]);
    fireEvent.click(within(section()).getByRole("button", { name: "Retry" }));
    await flush();
    expect(said()).toEqual(["Disk figures could not be loaded."]);
    storageAnswer = () => json(200, REPORT);
    await advance(60_000);
    expect(section()).not.toHaveTextContent("Disk figures could not be loaded.");
    expect(said()).toEqual(["Disk figures could not be loaded."]);
    expect(region()).toBeEmptyDOMElement();
  });

  it("a later failed read keeps the figures and turns the stamp stale, said once", async () => {
    await mount();
    const said = utterances();
    storageAnswer = unavailable;
    await advance(60_000);
    expect(section()).toHaveTextContent("Sampled 10:31:03 UTC, stale (1 min old)");
    expect(rowsOf(card("QuestDB · hot")).Size).toBe("640.0 GB");
    expect(said()).toEqual(["Storage figures are stale"]);
  });
});

describe("SCR-142/stale-sample: figures never silently go stale (AC 7; SR-27; FM-14)", CASE, () => {
  it("past two samples the stamp reads stale with its age, Retry first, the tags, said once", async () => {
    const { container } = await mount();
    const said = utterances();
    await advance(121_000);
    expect(section()).toHaveTextContent("Sampled 10:31:03 UTC, stale (2 min old)");
    await advance(60_000);
    expect(section()).toHaveTextContent("Sampled 10:31:03 UTC, stale (3 min old)");
    expect(said()).toEqual(["Storage figures are stale"]);
    // CMP-239 `stale` on the stamp (C-486P3-04 (b)): drawn beside its words, which already read the state and age.
    const marker = section().querySelector("[data-cmp='CMP-239']");
    expect(marker).toHaveAttribute("data-state", "stale");
    expect(marker?.textContent).toMatch(/^Stale 3m/);
    expect(marker?.closest("[aria-hidden='true']")).not.toBeNull();
    const focusable = section().querySelectorAll("button, a[href], [tabindex='0']");
    expect(focusable[0]).toHaveAccessibleName("Retry");
    expect(within(section()).getAllByText("stale").length).toBeGreaterThanOrEqual(4);
    expect(rowsOf(card("Parquet/DuckDB · cold")).Size).toBe("548.0 GB");
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("Retry with a fresh sample clears the stale state and lands on the heading", async () => {
    await mount();
    await advance(121_000);
    storageAnswer = () => json(200, { ...REPORT, generated_at: "2026-09-14T10:33:03.000Z" });
    const retry = within(section()).getByRole("button", { name: "Retry" });
    act(() => retry.focus());
    fireEvent.click(retry);
    await flush();
    expect(section()).toHaveTextContent("Sampled 10:33:03 UTC (every 60 s)");
    expect(within(section()).queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Storage and database" })).toHaveFocus();
    // The stale line leaves the region with its condition: browse mode never reads it as present.
    expect(region()).toBeEmptyDOMElement();
  });

  it("Retry that brings the same sample keeps focus on Retry", async () => {
    await mount();
    await advance(121_000);
    const retry = within(section()).getByRole("button", { name: "Retry" });
    act(() => retry.focus());
    fireEvent.click(retry);
    await flush();
    expect(retry).toHaveFocus();
  });
});

describe("SCR-142/tier-unreachable-questdb (AC 4; D04 §5; F-05, FM-14)", CASE, () => {
  it("the down tier's card shows its error with Retry; the others render; no page banner, no alert", async () => {
    healthAnswer = () => json(200, QUESTDB_DOWN);
    const { container } = await mount();
    const questdb = card("QuestDB · hot");
    expect(questdb).toHaveTextContent("QuestDB unreachable since 10:24:03 UTC");
    expect(within(questdb).getByRole("button", { name: "Retry" })).toBeVisible();
    expect(within(questdb).getByText("stale")).toBeVisible();
    expect(rowsOf(questdb).Health).toBe("down");
    expect(rowsOf(card("Parquet/DuckDB · cold")).Size).toBe("548.0 GB");
    expect(rowsOf(card("Postgres · relational")).Size).toBe("16.0 GB");
    expect(within(section()).queryByRole("alert")).toBeNull();
    expect(section()).not.toHaveTextContent("Disk figures could not be loaded.");
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("a successful Retry restores focus to the card's heading; a failed one keeps it on Retry", async () => {
    healthAnswer = () => json(200, QUESTDB_DOWN);
    await mount();
    let retry = within(card("QuestDB · hot")).getByRole("button", { name: "Retry" });
    act(() => retry.focus());
    fireEvent.click(retry);
    await flush();
    expect(retry).toHaveFocus();
    healthAnswer = () => json(200, HEALTH);
    retry = within(card("QuestDB · hot")).getByRole("button", { name: "Retry" });
    fireEvent.click(retry);
    await flush();
    expect(card("QuestDB · hot")).not.toHaveTextContent("unreachable");
    expect(screen.getByRole("heading", { level: 3, name: "QuestDB · hot" })).toHaveFocus();
  });

  it("health that cannot be read reads 'not reported' on every card", async () => {
    healthAnswer = () =>
      json(403, { code: "forbidden", status: 403, title: "x", type: "about:blank" });
    await mount();
    for (const title of ["QuestDB · hot", "Parquet/DuckDB · cold", "Postgres · relational"]) {
      expect(rowsOf(card(title)).Health).toBe("not reported");
    }
  });
});

describe("disk pressure states what stops first (AC 3; D04 §1.4, §5; R-5)", CASE, () => {
  const levels: readonly (readonly [string, StorageUsage, readonly string[], string])[] = [
    [
      "low-disk-warning",
      LEVEL_1,
      ["Near limit · auto-record pauses in about 131 days · clears below 75 %"],
      "warning",
    ],
    [
      "autostop",
      LEVEL_2,
      ["Recording stops at 95 % in about 69 days", "Retention accelerated"],
      "warning",
    ],
    [
      "read-only-disk-full",
      LEVEL_3,
      [
        "Recording stopped · resumes below 90 % with 10 % of the volume free",
        "Open positions keep recording; other symbols' data is dropped and recorded as gaps.",
      ],
      "danger",
    ],
    [
      "volume-refused",
      VOLUME_REFUSED,
      [
        "The recording volume was refused at start-up; the gate opens once it is fixed",
        "1,188.0 GB of 2,000.0 GB (59.4 %)",
      ],
      "danger",
    ],
  ];

  it.each(levels)(
    "SCR-142/%s: the banner says recording pauses before trading, with its detail",
    async (_, report, more, glyph) => {
      storageAnswer = () => json(200, report);
      const { container } = await mount({ frame: null });
      expect(section()).toHaveTextContent("Recording pauses before trading is affected.");
      expect(section()).toHaveTextContent(STORAGE_DECK["storage.degradation.detail"][0]);
      for (const text of more) expect(section()).toHaveTextContent(text);
      // The budget meter's tone is never colour alone: its glyph is drawn (C-486P3-06).
      const meter = screen.getByRole("meter", { name: "Recording budget" });
      const icon = meter.closest("[data-cmp='CMP-023']")?.querySelector("svg[data-icon]");
      expect(icon).toHaveAttribute("data-icon", glyph);
      expect(within(section()).queryByRole("alert")).toBeNull();
      expect(await seriousAxe(container)).toEqual([]);
    },
  );

  it("the level is read from the report, never derived from the bytes", async () => {
    storageAnswer = () => json(200, VOLUME_REFUSED);
    await mount({ frame: null });
    const meter = screen.getByRole("meter", { name: "Recording budget" });
    expect(meter.closest("[data-cmp='CMP-023']")).toHaveAttribute("data-tone", "danger");
    expect(section()).toHaveTextContent("Recording stopped");
  });

  it("the live frame's level wins over the sample's", async () => {
    await mount({ frame: frameWith({ level: 1, used_bytes: 1610000000000 }) });
    expect(section()).toHaveTextContent("Recording pauses before trading is affected.");
    expect(screen.getByRole("meter", { name: "Recording budget" })).toHaveAttribute(
      "aria-valuetext",
      "1,610.0 GB of 2,000.0 GB (80.5 %)",
    );
  });

  it("the suggested actions hand off to SCR-141 and SCR-140 (D04 §5: links, T1)", async () => {
    storageAnswer = () => json(200, LEVEL_1);
    const openRetention = vi.fn();
    const onSuggested = vi.fn();
    await mount({ frame: null, openRetention, onSuggested });
    fireEvent.click(within(section()).getByRole("button", { name: "Shorten retention" }));
    fireEvent.click(within(section()).getByRole("button", { name: "Reduce depth" }));
    fireEvent.click(within(section()).getByRole("button", { name: "Unpin" }));
    expect(openRetention).toHaveBeenCalledTimes(1);
    expect(onSuggested.mock.calls).toEqual([["Reduce depth"], ["Unpin"]]);
  });

  it("without SCR-141, Shorten retention is the page's own; without the page's hand-offs, none", async () => {
    storageAnswer = () => json(200, LEVEL_1);
    const onSuggested = vi.fn();
    const view = await mount({ frame: null, onSuggested });
    fireEvent.click(within(section()).getByRole("button", { name: "Shorten retention" }));
    expect(onSuggested).toHaveBeenCalledWith("Shorten retention");
    view.rerender(panel({ frame: null }));
    expect(within(section()).queryByRole("button", { name: "Unpin" })).toBeNull();
  });
});

describe("SCR-142/lag-warning (D04 §5; D04-D8, D04-Q4)", CASE, () => {
  it("a backlog of five batches over two frames raises the banner; one frame does not", async () => {
    const view = await mount();
    view.rerender(panel({ frame: frameWith({}, { backlog: 25000 }) }));
    await flush();
    expect(section()).not.toHaveTextContent("writes are behind the feed");
    view.rerender(panel({ frame: frameWith({}, { backlog: 25000 }) }));
    await flush();
    expect(section()).toHaveTextContent(STORAGE_DECK["storage.lag.banner"][1]);
    expect(rowsOf(card("QuestDB · hot")).Ingestion).toBe(
      "Ingest 18,400 msg/s, backlog 25,000 rows, lag —",
    );
    expect(within(section()).queryByRole("alert")).toBeNull();
    expect(await seriousAxe(view.container)).toEqual([]);
  });

  it("before a frame the status's numbers stand in", async () => {
    await mount({ frame: null });
    expect(rowsOf(card("QuestDB · hot")).Ingestion).toBe(
      "Ingest 18,422 msg/s, backlog 0 rows, lag —",
    );
  });

  it("the QuestDB card reads 'warning' with its glyph, and the threshold stands in the banner (C-486P3-04 (a))", async () => {
    const view = await mount();
    view.rerender(panel({ frame: frameWith({}, { backlog: 25000 }) }));
    await flush();
    expect(rowsOf(card("QuestDB · hot"))["Health"]).toBe("healthy");
    expect(section()).not.toHaveTextContent("Threshold:");
    view.rerender(panel({ frame: frameWith({}, { backlog: 25000 }) }));
    await flush();
    const questdb = card("QuestDB · hot");
    expect(rowsOf(questdb)["Health"]).toBe("warning");
    expect(definitionOf(questdb, "Health").querySelector("svg[data-icon]")).toHaveAttribute(
      "data-icon",
      "warning",
    );
    expect(rowsOf(card("Parquet/DuckDB · cold"))["Health"]).toBe("healthy");
    expect(section()).toHaveTextContent(
      "Ingestion backlog 25,000 rows — writes are behind the feed" +
        "Threshold: 5 batches of 5,000 rows for two samples",
    );
    view.rerender(panel({ frame: frameWith({}, { backlog: 0 }) }));
    await flush();
    expect(rowsOf(card("QuestDB · hot"))["Health"]).toBe("healthy");
  });
});

describe("SCR-142/view-as: the one T2 leg, dormant (BQ-8; D04 §9; T2-09; G-T2.5)", CASE, () => {
  it("one notice under the header; the reads keep updating", async () => {
    const { container } = await mount({ viewAs: { user: "alex" } });
    expect(section()).toHaveTextContent("Read-only — read-only while viewing as alex.");
    expect(screen.getByRole("meter", { name: "Recording budget" })).toBeVisible();
    await advance(60_000);
    expect(calls().filter((c) => c === "GET /recording/storage")).toHaveLength(2);
    expect(await seriousAxe(container)).toEqual([]);
  });
});

describe(
  "the per-symbol row's detail (D04-D3: SCR-140's row detail holds Purge… and the pin)",
  CASE,
  () => {
    it("each Symbol opens the row's detail once SCR-140 registers it", async () => {
      const openRowDetail = vi.fn();
      const off = registerRecorderExtensions({ openRowDetail });
      try {
        await mount();
        const table = screen.getByRole("table", { name: "Per-symbol breakdown for the hot tier" });
        // Its name starts with the visible symbol and names what it opens, a dialog (A-486P3-06; SC 2.5.3).
        const button = within(table).getByRole("button", { name: "ETHUSDT: open row detail" });
        expect(button).toHaveTextContent(/^ETHUSDT$/);
        expect(button).toHaveAttribute("aria-haspopup", "dialog");
        // The cell clips at its edge: the ring is drawn inside the button (A-486P3-01, the DS's H8).
        expect(button).toHaveClass("cv-focus-ring", "cv-focus-ring--inset");
        fireEvent.click(button);
        expect(openRowDetail).toHaveBeenCalledWith("ETHUSDT");
      } finally {
        act(() => off());
      }
    });

    it("a symbol the page does not list is text, never a dead button (C-486P3-12)", async () => {
      const openRowDetail = vi.fn();
      const off = registerRecorderExtensions({ openRowDetail });
      try {
        const frame = frameWith();
        await mount({
          frame: { ...frame, symbols: (frame.symbols ?? []).filter((s) => s.symbol === "BTCUSDT") },
          status: {
            ...STATUS,
            symbols: (STATUS.symbols ?? []).filter((s) => s.symbol === "BTCUSDT"),
          },
        });
        const table = screen.getByRole("table", { name: "Per-symbol breakdown for the hot tier" });
        expect(
          within(table).getByRole("button", { name: "BTCUSDT: open row detail" }),
        ).toBeVisible();
        expect(within(table).queryByRole("button", { name: /ETHUSDT/ })).toBeNull();
        expect(within(table).getByText("ETHUSDT")).toBeVisible();
      } finally {
        act(() => off());
      }
    });
  },
);

describe("health input never leaks (E16-D06 §20.3; R-I1)", CASE, () => {
  it("a component's detail is never rendered", async () => {
    healthAnswer = () =>
      json(200, {
        ...HEALTH,
        components: (HEALTH.components ?? []).map((c) => ({
          ...c,
          detail: "server detail, never rendered",
        })),
      } satisfies HealthReport);
    await mount();
    expect(section()).not.toHaveTextContent("server detail, never rendered");
  });
});
