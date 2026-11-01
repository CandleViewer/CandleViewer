/**
 * E16-S01, SCR-140's page (E16-D02 §1–§3, §5.2, §8, §9.3; E16-D06 §13 "Reading the page", §18's state ids, KB-01,
 * FM-14, RG-07 to RG-11, SR-01, SR-05 to SR-08, SR-15, BG-01, BG-05; F-05, F-07; Q-04; BQ-11, BQ-12): the page states
 * as named RTL fixtures, each with axe (no Storybook for page states, BQ-12), over a stubbed `apiFetch` and a fake
 * socket whose animation frame the test steps; every timer fake, no network (C-13.5).
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { GatedAnnounceProvider } from "@candleviewer/ui";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import {
  registerRecorderExtensions,
  type RetentionEditorProps,
  type StoragePanelProps,
} from "../../../src/features/recorder/extensions";
import type { RecorderFrame } from "../../../src/features/recorder/model";
import { RECORDER_H1_ID, RecorderScreen } from "../../../src/features/recorder/RecorderScreen";
import { useRecorderData } from "../../../src/features/recorder/useRecorderData";
import { NOW } from "./gridFixtures";
import { POLICY } from "./modelFixtures";
import { LIST, STATUS, STORAGE, fakeSocket, frameOf, router } from "./screenFixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
let clock = { now: NOW };
let reported: unknown[] = [];
const onAnalytics = (event: Event): void => void reported.push((event as CustomEvent).detail);

interface MountOptions {
  readonly route?: Parameters<typeof router>[0];
  /** The first frame; `null` sends none. */
  readonly frame?: RecorderFrame | null;
}

async function mountPage({ route, frame }: MountOptions = {}) {
  apiFetch.mockImplementation(router(route));
  const socket = fakeSocket(clock);
  const view = render(
    <>
      <RecorderScreen data={socket.options} instruments={["SOLUSDT", "DOGEUSDT"]} />
      <ShellAnnouncer />
    </>,
  );
  await flush();
  if (frame !== null) {
    socket.push(frame ?? frameOf());
    act(() => socket.step(0));
  }
  await flush();
  return { ...view, socket };
}

/** RG-10: the page's one polite region (the summary's), its words now. */
const region = (): HTMLElement =>
  document.querySelector('.cv-visually-hidden[role="status"][aria-live="polite"]') as HTMLElement;
/** Each utterance re-keys the region's node: the words of every batch said so far. */
function batches(): () => string[] {
  const said: string[] = [];
  const observer = new MutationObserver(() => {
    const text = region().textContent ?? "";
    if (text !== "" && said.at(-1) !== text) said.push(text);
  });
  observer.observe(region(), { childList: true, subtree: true, characterData: true });
  return () => said;
}
/** The page's one assertive node (RG-11's `alert`): the words of each write said so far. */
function alerts(): () => string[] {
  const node = document.querySelector('[role="alert"]') as HTMLElement;
  const said: string[] = [];
  const observer = new MutationObserver(() => {
    const text = node.textContent ?? "";
    if (text !== "") said.push(text);
  });
  observer.observe(node, { childList: true, subtree: true, characterData: true });
  return () => said;
}
/** The shell announcer's polite region (RG-17): its words now. */
const shellPolite = (): string =>
  document.querySelector('[aria-live="polite"][data-cv-inert-exempt]')?.textContent ?? "";
const step = async (socket: ReturnType<typeof fakeSocket>, ms: number): Promise<void> => {
  act(() => socket.step(ms));
  await flush();
};
const level3 = (used: number) =>
  frameOf({}, { level: 3, used_bytes: used, write_gate: "closed", write_gate_reason: "disk_halt" });

async function seriousAxe(element: Element): Promise<unknown[]> {
  vi.useRealTimers();
  const res = await axe.run(element, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: NOW,
  });
  clock = { now: NOW };
  reported = [];
  window.addEventListener("cv:analytics", onAnalytics);
});
afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  act(() => clearAnnouncements());
  apiFetch.mockReset();
  vi.useRealTimers();
});

// A cold first mount takes about 9 s on a loaded host; each case gets the axe tests' budget.
const CASE = { timeout: 20_000 } as const;

describe("SCR-140's states (E16-D06 §18; D02 §3, §3.1)", CASE, () => {
  it("running: the H1 and its action, the statement, the card, the summary; no banner", async () => {
    const { container } = await mountPage();
    expect(screen.getByRole("heading", { level: 1, name: "Recorder" })).toHaveAttribute(
      "id",
      RECORDER_H1_ID,
    );
    expect(screen.getAllByRole("button", { name: "Record a symbol" })[0]).toBeVisible();
    expect(container).toHaveTextContent(
      "A symbol is recorded only while you have added it here, its chart has been open for 60 s,",
    );
    expect(container).toHaveTextContent("Auto-record on chart open is on.");
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Growing · auto-record pauses in about 128 days",
      }),
    ).toBeVisible();
    const bar = screen.getByRole("progressbar", { name: "Recording budget" });
    expect(bar).toHaveAttribute("aria-valuetext", "61.4 GB of 200 GB (31 %)");
    expect(container).toHaveTextContent(
      "80 % warning · 90 % auto-record pauses · 95 % recording stops (open positions keep writing)",
    );
    expect(container).toHaveTextContent("Recording 4 symbols · 2 auto-recorded · Recorder healthy");
    expect(container).toHaveTextContent("updated 10:31:02 UTC");
    expect(screen.getByRole("alert")).toBeEmptyDOMElement(); // the page's one assertive region, silent
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("starting: the new row's words and the summary's '· 1 starting'", async () => {
    const frame = frameOf();
    const doge = { symbol: "DOGEUSDT", state: "starting", reason: "manual" } as const;
    const { container } = await mountPage({
      frame: { ...frame, symbols: [...frame.symbols, doge] },
    });
    expect(container).toHaveTextContent("· 1 starting");
    expect(screen.getByText("Starting · initial book snapshot")).toBeVisible();
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("degraded: the incident banner once, the row's gap count, the gap table, View gaps to its caption", async () => {
    const gap = { from: "2026-09-14T10:14:03Z", to: "2026-09-14T10:14:41Z", reason: "seq_jump" };
    const { container } = await mountPage({
      route: (method, url) =>
        url.includes("data-coverage") && url.includes("ETHUSDT")
          ? json(200, { symbol: "ETHUSDT", streams: [{ stream: "trades", gaps: [gap] }] })
          : undefined,
      frame: {
        ...frameOf({ ETHUSDT: { state: "degraded", dropped_messages: 1204 } }),
        overall: "degraded",
      },
    });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "Incident: 1 204 messages were dropped on ETHUSDT between 10:14:03 and 10:14:41 UTC.",
    );
    expect(container).toHaveTextContent("Degraded · stream unhealthy · 1 gap in 24 h");
    expect(container).toHaveTextContent("Recorder degraded");
    const table = screen.getByRole("table", { name: "Gaps recorded (last 24 h)" });
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent(
      "10:14:0310:14:4138 ssequence jump",
    );
    fireEvent.click(screen.getByRole("button", { name: "View gaps" }));
    expect(table.querySelector("caption")).toHaveFocus();
    expect(table.querySelector("caption")).toHaveClass("cv-focus-ring", "cv-focus-ring--inset");
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("disk warning (level 1): the headline names the way back; the share in words; no banner", async () => {
    const { container } = await mountPage({
      frame: frameOf({}, { level: 1, used_bytes: 161e9 }),
    });
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Near limit · auto-record pauses in about 20 days · clears below 75 %",
      }),
    ).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Recording budget" })).toHaveAttribute(
      "aria-valuetext",
      "Recording budget 80.5 % used (161.0 GB of 200 GB)",
    );
    expect(container).toHaveTextContent("34.8 GB · 0.71/d · 17 % of budget");
    expect(screen.getByRole("button", { name: "Unpin" })).toBeVisible();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement(); // the page's one assertive region, silent
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("paused (level 2): the headline and the halt's runway; Unpin and Reduce depth filter the grid", async () => {
    const { container } = await mountPage({ frame: frameOf({}, { level: 2, used_bytes: 181e9 }) });
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Auto-record paused · resumes below 85 % of the budget with 20 % of the volume free",
      }),
    ).toBeVisible();
    // (95 % × 200 GB − 181.0 GB) ÷ 0.93 GB/day ≈ 9.7, nearest day (the model's rule, D02 §1).
    expect(container).toHaveTextContent("Recording stops at 95 % in about 10 days.");
    fireEvent.click(screen.getByRole("button", { name: "Unpin" }));
    expect(screen.getByRole("group", { name: "Active filters" })).toHaveTextContent("Pinned: Yes");
    expect(screen.getAllByRole("rowheader").map((c) => c.textContent)).toEqual(["BTCUSDT"]);
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("disk critical (level 3): the banner as an alert, gated rows, the position row recording", async () => {
    const { container } = await mountPage({
      frame: frameOf(
        {},
        { level: 3, used_bytes: 190.4e9, write_gate: "closed", write_gate_reason: "disk_halt" },
      ),
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Recording stopped: the recording budget is 95 % used (190.4 GB of 200 GB).",
    );
    expect(screen.getAllByText("Gated · data dropped")).toHaveLength(3);
    expect(screen.getByText("Recording · position")).toBeVisible();
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("empty: CMP-026 replaces the grid; the card reads Nothing recorded", async () => {
    const { container } = await mountPage({
      route: (method, url) =>
        url.includes("/recording/symbols?")
          ? json(200, { items: [], meta: { count: 0, has_more: false } })
          : url.endsWith("/recording/status")
            ? json(200, { ...STATUS, symbols: [] })
            : url.endsWith("/recording/storage")
              ? json(200, { ...STORAGE, tiers: [], symbols: [] })
              : undefined,
      frame: { ...frameOf({}, { used_bytes: 0 }), symbols: [] },
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "Nothing is recorded yet" }),
    ).toBeVisible();
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Nothing recorded" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Record a symbol" })).toHaveLength(2);
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("stop-confirm: the confirmation over the page, its default Keep recording focused", async () => {
    await mountPage();
    const stop = screen.getByRole("button", { name: "Stop recording ETHUSDT" });
    act(() => stop.focus());
    fireEvent.click(stop);
    const dialog = screen.getByRole("alertdialog", { name: "Stop recording ETHUSDT?" });
    expect(within(dialog).getByRole("button", { name: "Keep recording" })).toHaveFocus();
    expect(await seriousAxe(dialog)).toEqual([]);
  });

  it("loading: skeletons and a busy grid; the header, the action live", async () => {
    apiFetch.mockImplementation(() => new Promise<Response>(() => undefined));
    const socket = fakeSocket(clock);
    const { container } = render(<RecorderScreen data={socket.options} instruments={[]} />);
    await flush();
    expect(screen.getByRole("heading", { level: 1, name: "Recorder" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Record a symbol" })).toBeVisible();
    expect(screen.getByRole("grid", { name: /Recorded symbols/ })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(container.querySelectorAll('[aria-busy="true"]').length).toBeGreaterThanOrEqual(2);
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("unavailable: the failed part named with Retry; a Retry that loads restores focus to the H1 (F-05)", async () => {
    let fail = true;
    const { container } = await mountPage({
      route: (method, url) =>
        fail && url.endsWith("/recording/status")
          ? json(503, {
              code: "not_deployed",
              status: 503,
              title: "x",
              type: "about:blank",
              detail: "server detail",
            })
          : undefined,
      frame: null,
    });
    // CMP-028: the title, then the body.
    expect(container).toHaveTextContent(
      /Recorder status could not be loaded\.\s*This page cannot show what is being recorded right now\./,
    );
    expect(container).not.toHaveTextContent("server detail");
    expect(screen.getByRole("alert")).toBeEmptyDOMElement(); // the page's one assertive region, silent
    expect(await seriousAxe(container)).toEqual([]);
    vi.useFakeTimers({
      toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
      now: clock.now,
    });
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(screen.getByRole("heading", { level: 1, name: "Recorder" })).toHaveFocus();
    expect(container).not.toHaveTextContent("Recorder status could not be loaded.");
  });

  it("unavailable, disk: the disk figures' variant; the rows stay", async () => {
    const { container } = await mountPage({
      route: (method, url) =>
        url.endsWith("/recording/storage") ? json(503, { code: "not_deployed" }) : undefined,
      frame: null,
    });
    expect(container).toHaveTextContent("Disk figures could not be loaded.");
    expect(screen.getAllByRole("rowheader")).toHaveLength(5);
  });

  it("stale: 2 s without a frame; the summary's words, each row's tag, said once", async () => {
    const { container, socket } = await mountPage();
    const said = batches();
    act(() => socket.step(2_500));
    await flush();
    expect(container).toHaveTextContent("Status stale since 10:31:02 UTC");
    expect(screen.getAllByText("stale")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Stop recording ETHUSDT" })).not.toHaveAttribute(
      "aria-disabled",
    );
    expect(said()).toEqual(["Status stale since 10:31:02 UTC"]);
    act(() => socket.step(1_000));
    await advance(11_000);
    expect(said()).toEqual(["Status stale since 10:31:02 UTC"]);
    expect(await seriousAxe(container)).toEqual([]);
  });
});

describe("Feature: Reading the page (E16-D06 §13; KB-01, KB-02, RG-02, RG-03, SR-01)", CASE, () => {
  it("Scenario: the grid's row is named; 1 Hz values never move focus or speak; a change is one batch", async () => {
    const { socket } = await mountPage();
    const said = batches();
    const grid = screen.getByRole("grid", { name: "Recorded symbols" });
    const stop = grid.querySelector('[tabindex="0"]') as HTMLElement;
    act(() => stop.focus());
    expect(stop.closest('[role="row"], tr')).toHaveAccessibleName(
      "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on",
    );
    socket.push(frameOf({ BTCUSDT: { disk_bytes: 35.1e9 } }, { used_bytes: 61.7e9 }));
    act(() => socket.step(1_000));
    await flush();
    expect(stop).toHaveFocus();
    expect(said()).toEqual([]);
    socket.push(frameOf({ ETHUSDT: { state: "degraded" }, SOLUSDT: { state: "stopped" } }));
    act(() => socket.step(1_000));
    await flush();
    expect(said()).toEqual(["ETHUSDT degraded; SOLUSDT stopped recording"]);
    expect(stop).toHaveFocus();
  });

  it("the budget: at most one polite summary per 10 s, the window's changes one batch (BG-01)", async () => {
    const { socket } = await mountPage();
    const said = batches();
    socket.push(frameOf({ ETHUSDT: { state: "degraded" } }));
    act(() => socket.step(1_000));
    await flush();
    socket.push(frameOf({ ETHUSDT: { state: "degraded" }, SOLUSDT: { state: "stopped" } }));
    act(() => socket.step(1_000));
    await flush();
    socket.push(
      frameOf({
        ETHUSDT: { state: "degraded" },
        SOLUSDT: { state: "stopped" },
        XRPUSDT: { state: "error" },
      }),
    );
    act(() => socket.step(1_000));
    await flush();
    expect(said()).toEqual(["ETHUSDT degraded"]);
    await advance(10_000);
    expect(said()).toEqual(["ETHUSDT degraded", "SOLUSDT stopped recording; XRPUSDT error"]);
  });

  it("a level crossing speaks the card's headline once in the batch (F-07)", async () => {
    const { socket } = await mountPage();
    const said = batches();
    socket.push(frameOf({}, { level: 1, used_bytes: 161e9 }));
    act(() => socket.step(1_000));
    await flush();
    expect(said()).toEqual([
      "Near limit · auto-record pauses in about 20 days · clears below 75 %",
    ]);
  });
});

describe("the page's entries and analytics (D02 §5.2, §6.6, §12; BQ-11)", CASE, () => {
  it("reports the view once; '2 auto-recorded' applies Reason: Auto and reports the review", async () => {
    await mountPage();
    fireEvent.click(screen.getByRole("button", { name: "2 auto-recorded" }));
    expect(screen.getByRole("group", { name: "Active filters" })).toHaveTextContent("Reason: Auto");
    expect(screen.getAllByRole("rowheader").map((c) => c.textContent)).toEqual([
      "SOLUSDT",
      "XRPUSDT",
    ]);
    expect(reported).toEqual([
      { name: "recorder.screen_viewed" },
      { name: "recorder.auto_review_opened", source: "summary" },
    ]);
  });

  it("Retention policy and Storage details show only once registered; each reaches its part", async () => {
    await mountPage();
    expect(screen.queryByRole("button", { name: "Retention policy" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Storage details" })).toBeNull();
    const editor = vi.fn((props: RetentionEditorProps) =>
      props.open ? <p>retention editor open</p> : null,
    );
    const panel = (props: StoragePanelProps) => <h2 id={props.headingId}>Storage and database</h2>;
    let off = (): void => undefined;
    act(() => {
      off = registerRecorderExtensions({ RetentionEditor: editor, StoragePanel: panel });
    });
    fireEvent.click(screen.getByRole("button", { name: "Retention policy" }));
    expect(screen.getByText("retention editor open")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Storage details" }));
    expect(screen.getByRole("heading", { name: "Storage and database" })).toHaveFocus();
    act(() => off());
    expect(screen.queryByRole("button", { name: "Retention policy" })).toBeNull();
  });

  it("Compact now: busy with its percentage, then the card's line once; a 409 its T4", async () => {
    const JOB = "19000000-0000-4000-8000-000000000001";
    let polls = 0;
    let refuse = false;
    await mountPage({
      route: (method, url) => {
        if (url.endsWith("/admin/recorder/compact")) {
          return refuse
            ? json(409, { code: "job_running", status: 409, title: "x", type: "about:blank" })
            : json(202, { job_id: JOB });
        }
        if (url.endsWith(`/admin/jobs/${JOB}`)) {
          polls += 1;
          return polls < 2
            ? json(200, { id: JOB, status: "running", progress_pct: 42 })
            : json(200, {
                id: JOB,
                status: "succeeded",
                progress_pct: 100,
                finished_at: "2026-09-14T10:42:00Z",
              });
        }
        return undefined;
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));
    await flush();
    const busy = screen.getByRole("button", { name: /Compacting · 42 %/ });
    expect(busy).toHaveAttribute("aria-busy", "true");
    await advance(2_000);
    expect(screen.getByRole("button", { name: "Compact now" })).toHaveAccessibleDescription(
      "Compacted at 10:42 UTC",
    );
    refuse = true;
    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));
    await flush();
    expect(screen.getByRole("button", { name: "Compact now" })).toHaveAccessibleDescription(
      "A compaction is already running. (job_running)",
    );
  });

  it("Record a symbol opens the add on its combobox; the server's row lands in the grid", async () => {
    const doge = { ...LIST[1], id: "id-dogeusdt", symbol: "DOGEUSDT", state: "starting" };
    let added = false;
    await mountPage({
      route: (method, url) => {
        if (!url.endsWith("/recording/symbols")) return undefined;
        if (method === "POST") {
          added = true;
          return json(201, { ...doge, estimate: { daily_bytes_estimate: 0.6e9 } });
        }
        const items = added ? [...LIST, doge] : LIST;
        return json(200, { items, meta: { count: items.length, has_more: false } });
      },
    });
    const record = screen.getAllByRole("button", { name: "Record a symbol" })[0] as HTMLElement;
    act(() => record.focus());
    fireEvent.click(record);
    const dialog = screen.getByRole("dialog", { name: "Record a symbol" });
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Symbol" }), {
      target: { value: "DOGEUSDT" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start recording" }));
    await flush();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(record).toHaveFocus();
    expect(screen.getAllByRole("rowheader").map((c) => c.textContent)).toContain("DOGEUSDT");
  });
});

describe(
  "the assertive banners: once per condition (C-5309-01, D-5309-01, BG-05, BG-06)",
  CASE,
  () => {
    it("level 3: two frames with other figures are one write; once it ends, a new level 3 is said again", async () => {
      const { socket, container } = await mountPage({ frame: null });
      const said = alerts();
      socket.push(level3(190.4e9));
      await step(socket, 0);
      socket.push(level3(190.9e9)); // a purge or the 1 Hz figure: the sentence's numbers move
      await step(socket, 1_000);
      expect(container).toHaveTextContent("95.5 % used (190.9 GB of 200 GB)"); // the banner draws them
      expect(said()).toEqual([
        "Recording stopped: the recording budget is 95 % used (190.4 GB of 200 GB). Data for symbols without an open position is being dropped and recorded as gaps; open positions keep recording. Free space to resume: purge data, shorten retention or raise the budget.",
      ]);
      socket.push(frameOf());
      await step(socket, 1_000);
      await advance(10_000);
      socket.push(level3(191e9));
      await step(socket, 1_000);
      await advance(10_000);
      expect(said()).toHaveLength(2);
    });

    it("level 3 held by the volume says so, never the budget (A-5309-04)", async () => {
      const { socket } = await mountPage({ frame: null });
      const said = alerts();
      socket.push(level3(80e9));
      await step(socket, 0);
      expect(said()[0]).toMatch(/^Recording stopped: the disk volume has less than 5 % free\./);
    });

    it("an incident: a climbing count is one write; its gap landing later adds the interval, said no more (C-5309-07)", async () => {
      let gap = false;
      const { socket, container } = await mountPage({
        frame: null,
        route: (method, url) =>
          url.includes("data-coverage") && url.includes("ETHUSDT")
            ? json(200, {
                symbol: "ETHUSDT",
                streams: gap
                  ? [
                      {
                        stream: "trades",
                        gaps: [{ from: "2026-09-14T10:14:03Z", to: "2026-09-14T10:14:41Z" }],
                      },
                    ]
                  : [],
              })
            : undefined,
      });
      const said = alerts();
      socket.push(frameOf({ ETHUSDT: { state: "degraded", dropped_messages: 1204 } }));
      await step(socket, 0);
      expect(container).toHaveTextContent(
        "Incident: 1 204 messages were dropped on ETHUSDT. The lost",
      );
      socket.push(frameOf({ ETHUSDT: { state: "degraded", dropped_messages: 1300 } }));
      await step(socket, 1_000);
      gap = true;
      await advance(60_000); // the coverage read lands the gap
      socket.push(frameOf({ ETHUSDT: { state: "degraded", dropped_messages: 1420 } }));
      await step(socket, 1_000);
      expect(container).toHaveTextContent(
        "Incident: 1 420 messages were dropped on ETHUSDT between 10:14:03",
      );
      expect(said()).toEqual([
        "Incident: 1 204 messages were dropped on ETHUSDT. The lost interval is recorded as a gap; charts and replay show it as a gap.",
      ]);
    });
  },
);

describe(
  "the page's focus and its one voice (C-5309-02 to C-5309-05; D-5309-04 to D-5309-06)",
  CASE,
  () => {
    it("in the shell, Start recording at the limit says its reason once, through the page's provider", async () => {
      apiFetch.mockImplementation(router());
      const socket = fakeSocket(clock);
      const ignore = (): void => undefined; // ShellLayout's provider: surfaces own their gated announcement (#5135)
      render(
        <GatedAnnounceProvider announce={ignore}>
          <RecorderScreen data={socket.options} instruments={["SOLUSDT", "DOGEUSDT"]} />
          <ShellAnnouncer />
        </GatedAnnounceProvider>,
      );
      await flush();
      socket.push({ ...frameOf(), policy: { ...POLICY, max_symbols: 4 } });
      await step(socket, 0);
      fireEvent.click(screen.getAllByRole("button", { name: "Record a symbol" })[0] as HTMLElement);
      const dialog = screen.getByRole("dialog", { name: "Record a symbol" });
      fireEvent.change(within(dialog).getByRole("combobox", { name: "Symbol" }), {
        target: { value: "DOGEUSDT" },
      });
      const start = within(dialog).getByRole("button", { name: "Not available Start recording" });
      act(() => start.focus());
      fireEvent.click(start);
      expect(shellPolite()).toBe("The symbol limit is reached.");
      expect(apiFetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    });

    it("the first add from the empty state's CTA leaves focus on the header's Record a symbol", async () => {
      const doge = { ...LIST[1], id: "id-dogeusdt", symbol: "DOGEUSDT", state: "starting" };
      await mountPage({
        route: (method, url) =>
          url.includes("/recording/symbols") && method === "POST"
            ? json(201, doge)
            : url.includes("/recording/symbols") && method === "GET"
              ? json(200, { items: [], meta: { count: 0, has_more: false } })
              : url.endsWith("/recording/status")
                ? json(200, { ...STATUS, symbols: [] })
                : undefined,
        frame: { ...frameOf({}, { used_bytes: 0 }), symbols: [] },
      });
      const [header, cta] = screen.getAllByRole("button", { name: "Record a symbol" });
      act(() => cta?.focus());
      fireEvent.click(cta as HTMLElement);
      const dialog = screen.getByRole("dialog", { name: "Record a symbol" });
      fireEvent.change(within(dialog).getByRole("combobox", { name: "Symbol" }), {
        target: { value: "DOGEUSDT" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Start recording" }));
      await flush();
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(cta).not.toBeInTheDocument();
      expect(header).toHaveFocus();
    });

    it("the summary's auto link keeps its element and focus as its count changes", async () => {
      const { socket } = await mountPage();
      const link = screen.getByRole("button", { name: "2 auto-recorded" });
      act(() => link.focus());
      socket.push(frameOf({ ETHUSDT: { reason: "chart_open" } }));
      await step(socket, 1_000);
      expect(screen.getByRole("button", { name: "3 auto-recorded" })).toBe(link);
      expect(link).toHaveFocus();
    });

    it("a Retry that brings back one of two failed parts lands focus on the H1", async () => {
      let statusFails = true;
      await mountPage({
        route: (method, url) =>
          (statusFails && url.endsWith("/recording/status")) || url.endsWith("/recording/storage")
            ? json(503, { code: "not_deployed" })
            : undefined,
        frame: null,
      });
      statusFails = false;
      const retry = screen.getAllByRole("button", { name: "Retry" })[0] as HTMLElement;
      act(() => retry.focus());
      fireEvent.click(retry);
      await flush();
      expect(retry).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 1, name: "Recorder" })).toHaveFocus();
    });
  },
);

describe("the page's reads (A-5309-01, C-5309-08 to C-5309-13)", CASE, () => {
  const session = (symbol: string, endedAt: string) => ({
    symbol,
    started_at: "2026-09-13T00:00:00Z",
    ended_at: endedAt,
    state: "stopped",
  });

  it("a row the server stops while the page is open reads its stop's date", async () => {
    const { socket, container } = await mountPage({
      route: (method, url) =>
        url.includes("/recording/sessions") && url.includes("ETHUSDT")
          ? json(200, {
              items: [session("ETHUSDT", "2026-09-14T10:31:00Z")],
              meta: { count: 1, has_more: false },
            })
          : undefined,
    });
    socket.push(frameOf({ ETHUSDT: { state: "stopped" } }));
    await step(socket, 1_000);
    expect(container).toHaveTextContent("Stopped 14 Sep · gone by 14 Oct");
  });

  it("stop, record again, stop: the second stop's date, not the first", async () => {
    let ended = "2026-09-12T09:00:00Z";
    const { socket, container } = await mountPage({
      route: (method, url) =>
        url.includes("/recording/sessions")
          ? json(200, { items: [session("ADAUSDT", ended)], meta: { count: 1, has_more: false } })
          : undefined,
    });
    expect(container).toHaveTextContent("Stopped 12 Sep · gone by 12 Oct");
    socket.push(frameOf({ ADAUSDT: { state: "recording" } }));
    await step(socket, 1_000);
    ended = "2026-09-14T10:31:00Z";
    socket.push(frameOf({ ADAUSDT: { state: "stopped" } }));
    await step(socket, 1_000);
    expect(container).toHaveTextContent("Stopped 14 Sep · gone by 14 Oct");
  });

  it("an unmount releases the topic, clears every timer and sends nothing more", async () => {
    const { socket, unmount } = await mountPage();
    const calls = apiFetch.mock.calls.length;
    unmount();
    expect(socket.handle.release).toHaveBeenCalledTimes(1);
    await advance(130_000);
    expect(apiFetch.mock.calls.length).toBe(calls);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("re-reads the disk figures every 60 s (D02 §2)", async () => {
    await mountPage();
    const reads = (): number =>
      apiFetch.mock.calls.filter(([url]) => url.endsWith("/recording/storage")).length;
    expect(reads()).toBe(1);
    await advance(60_000);
    expect(reads()).toBe(2);
  });

  it("a write's re-read of the list waits out the 5 s gap (BQ-7)", async () => {
    const doge = { ...LIST[1], id: "id-dogeusdt", symbol: "DOGEUSDT", state: "starting" };
    const { socket } = await mountPage({
      route: (method, url) =>
        url.endsWith("/recording/symbols") && method === "POST" ? json(201, doge) : undefined,
    });
    const lists = (): number =>
      apiFetch.mock.calls.filter(
        ([url, init]) => url.includes("/recording/symbols?") && (init?.method ?? "GET") === "GET",
      ).length;
    const before = lists();
    fireEvent.click(screen.getAllByRole("button", { name: "Record a symbol" })[0] as HTMLElement);
    const dialog = screen.getByRole("dialog", { name: "Record a symbol" });
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Symbol" }), {
      target: { value: "DOGEUSDT" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start recording" }));
    await flush();
    expect(screen.getAllByRole("rowheader").map((c) => c.textContent)).toContain("DOGEUSDT");
    await step(socket, 1_000);
    expect(lists()).toBe(before);
    await step(socket, 4_000); // 5 s since the first paint's reads
    expect(lists()).toBe(before + 1);
  });

  it("reads the gaps of the active rows only, never a stopped one's (BQ-10)", async () => {
    await mountPage();
    const coverage = apiFetch.mock.calls
      .map(([url]) => url)
      .filter((url) => url.includes("data-coverage"));
    expect(coverage.filter((url) => url.includes("ETHUSDT"))).toHaveLength(1);
    expect(coverage.some((url) => url.includes("ADAUSDT"))).toBe(false);
  });

  it("an older list read landing after an add keeps the added row", async () => {
    let release = (): void => undefined;
    let hold = false;
    apiFetch.mockImplementation(async (url, init) => {
      if (hold && url.includes("/recording/symbols?") && (init?.method ?? "GET") === "GET") {
        await new Promise<void>((resolve) => (release = resolve));
      }
      return router()(url, init);
    });
    const socket = fakeSocket(clock);
    const { result } = renderHook(() => useRecorderData(socket.options));
    await flush();
    hold = true;
    socket.push(frameOf());
    await step(socket, 0);
    socket.push({ ...frameOf(), symbols: [...frameOf().symbols].slice(1) }); // a row left: the list is read
    await step(socket, 5_000);
    const doge = {
      id: "id-dogeusdt",
      symbol: "DOGEUSDT",
      reason: "manual",
      state: "starting",
    } as const;
    act(() => result.current.merge(doge));
    act(() => release());
    await flush();
    expect(result.current.list.data?.map((row) => row.symbol)).toContain("DOGEUSDT");
  });
});

describe("the page's clock is the server's (C-5309-11, A-5309-08)", CASE, () => {
  it("a browser clock 90 s ahead flips no row to silent: the frame's `ts` is the clock", async () => {
    const { socket } = await mountPage({ frame: null });
    clock.now = NOW + 90_000;
    socket.push(frameOf(), NOW); // sent at the server's NOW; the rows wrote a second before it
    await step(socket, 0);
    expect(screen.queryByText(/^No writes since/)).toBeNull();
  });

  it("a row that has written nothing is silent 60 s after the page first saw it", async () => {
    /** A frame sent at `ts`: every row wrote a second before it, XRPUSDT nothing yet. */
    const quiet = (ts: number): ReturnType<typeof frameOf> => {
      const frame = frameOf();
      for (const row of frame.symbols) row.last_event_at_ms = ts - 1_000;
      const xrp = frame.symbols.find((row) => row.symbol === "XRPUSDT");
      if (xrp !== undefined) delete xrp.last_event_at_ms;
      return frame;
    };
    const { socket } = await mountPage({ frame: null });
    socket.push(quiet(NOW), NOW);
    await step(socket, 0);
    socket.push(quiet(NOW + 60_000), NOW + 60_000);
    await step(socket, 1_000);
    expect(screen.queryByText(/^No writes since/)).toBeNull();
    socket.push(quiet(NOW + 61_000), NOW + 61_000);
    await step(socket, 1_000);
    expect(screen.getByText("No writes since 10:31:02")).toBeVisible();
  });
});

describe("the page's other answers (A-5309-03, C-5309-13, #5309 A cross-scope)", CASE, () => {
  it("a growth of 0 with rows recording for days reads Steady, not too early", async () => {
    await mountPage({
      route: (method, url) =>
        url.endsWith("/recording/storage")
          ? json(200, { ...STORAGE, daily_growth_bytes: 0 })
          : undefined,
      frame: frameOf({}, { daily_growth_bytes: 0 }),
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "Steady · usage is not growing" }),
    ).toBeVisible();
  });

  it("'2 auto-recorded' replaces a Reason chip already applied, never ORs with it", async () => {
    await mountPage();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Reason" }));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Manual" }));
    fireEvent.click(screen.getByRole("button", { name: "2 auto-recorded" }));
    const chips = screen.getByRole("group", { name: "Active filters" });
    expect(chips).toHaveTextContent("Reason: Auto");
    expect(chips).not.toHaveTextContent("Reason: Manual");
    expect(screen.getAllByRole("rowheader").map((c) => c.textContent)).toEqual([
      "SOLUSDT",
      "XRPUSDT",
    ]);
  });

  it("not deployed: no policy served, so no statement and no skeleton once the status has loaded", async () => {
    const { container } = await mountPage({
      route: (method, url) =>
        url.endsWith("/recording/status")
          ? json(200, { overall: "not_deployed", symbols: [], generated_at: STATUS.generated_at })
          : undefined,
      frame: null,
    });
    expect(container).not.toHaveTextContent("Nothing is recorded by default.");
    expect(container).toHaveTextContent("Recorder not deployed");
    expect(container.querySelector('[data-cmp="CMP-015"]')).toBeNull(); // no skeleton is left spinning
  });
});
