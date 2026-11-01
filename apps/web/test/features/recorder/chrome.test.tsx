/**
 * E16-S01, SCR-140's chrome parts (E16-D02 §3, §3.2, §6.6, §10.2; E16-D06 RG-08, RG-11, SR-07 to SR-09, SR-13, BG-02,
 * BG-05; #485/#486 BQ-6): the banner slot's priority and its purge line said once; the extension registry; the gap
 * table's words; Compact now's terminal lines on the 2 s job poll. A stubbed `apiFetch`, fake timers, no network.
 */
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { CompactNow } from "../../../src/features/recorder/CompactNow";
import {
  registerRecorderExtensions,
  useRecorderExtensions,
} from "../../../src/features/recorder/extensions";
import { BannerSlot, GapTable, focusLanding } from "../../../src/features/recorder/RecorderChrome";
import { JOB_POLL_MS, useJobPoll } from "../../../src/features/recorder/useJobPoll";
import { NOW } from "./gridFixtures";

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
const JOB = "19000000-0000-4000-8000-000000000001";
const LEVEL_3 =
  "Recording stopped: the recording budget is 95 % used (190.4 GB of 200 GB). Data for symbols without an open position is being dropped and recorded as gaps; open positions keep recording.";
const INCIDENT = {
  symbol: "ETHUSDT",
  dropped: 1204,
  fromMs: Date.parse("2026-09-14T10:14:03Z"),
  toMs: Date.parse("2026-09-14T10:14:41Z"),
};
const PURGE = {
  phase: "running",
  symbol: "ADAUSDT",
  beforeMs: Date.parse("2026-10-01T00:00:00Z"),
  pct: 42,
  pollRefused: null,
} as const;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"], now: NOW });
});
afterEach(() => {
  act(() => clearAnnouncements());
  apiFetch.mockReset();
  vi.useRealTimers();
});

describe("the banner slot (D02 §3: level 3, then an incident, then a purge)", () => {
  const slot = (props: Partial<Parameters<typeof BannerSlot>[0]>) => (
    <BannerSlot
      levelThree={null}
      incident={null}
      purge={null}
      onViewGaps={() => undefined}
      {...props}
    />
  );

  it("holds one banner by priority; level 3 and an incident draw their words, which the page says (C-5309-01)", () => {
    const { rerender, container } = render(
      slot({ levelThree: LEVEL_3, incident: INCIDENT, purge: PURGE }),
    );
    expect(container).toHaveTextContent("Recording stopped: the recording budget is 95 %");
    // No live role of their own: a figure that moves never speaks the sentence again (BG-04, BG-05).
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container).not.toHaveTextContent("Incident");
    rerender(slot({ incident: INCIDENT, purge: PURGE }));
    expect(container).toHaveTextContent(
      "Incident: 1 204 messages were dropped on ETHUSDT between 10:14:03 and 10:14:41 UTC.",
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container).not.toHaveTextContent("Purging");
    rerender(slot({}));
    expect(container).toBeEmptyDOMElement();
  });

  it("an incident before its gap is on record names no interval (C-5309-07)", () => {
    const { container } = render(slot({ incident: { ...INCIDENT, fromMs: null, toMs: null } }));
    // CMP-028: the title, then the body.
    expect(container).toHaveTextContent(
      /^Incident: 1 204 messages were dropped on ETHUSDT\.\s*The lost interval is recorded as a gap; charts and replay show it as a gap\./,
    );
  });

  it("an incident offers View gaps once its gap is on record, not before: there is no table to land on (C-5309-d03)", () => {
    const onViewGaps = vi.fn();
    const { rerender } = render(
      slot({ incident: { ...INCIDENT, fromMs: null, toMs: null }, onViewGaps }),
    );
    expect(screen.queryByRole("button", { name: "View gaps" })).toBeNull();
    rerender(slot({ incident: INCIDENT, onViewGaps }));
    fireEvent.click(screen.getByRole("button", { name: "View gaps" }));
    expect(onViewGaps).toHaveBeenCalledTimes(1);
  });

  it("level 3 offers Retention policy only once SCR-141 is registered", () => {
    const open = vi.fn();
    const { rerender } = render(slot({ levelThree: LEVEL_3 }));
    expect(screen.queryByRole("button", { name: "Retention policy" })).toBeNull();
    rerender(slot({ levelThree: LEVEL_3, onRetentionPolicy: open }));
    fireEvent.click(screen.getByRole("button", { name: "Retention policy" }));
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("a purge running: info, its bar named for the purge, no region of its own (SR-09, BG-02; D-5309-11)", () => {
    // The line is said once through the shell's announcer (`usePurge`, A-5347-04), never by a node that mounts
    // with its words; the percentage is never spoken.
    const { rerender, container } = render(slot({ purge: PURGE }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(container).toHaveTextContent("Purging ADAUSDT data recorded before 2026-10-01: 42 %.");
    expect(screen.getByRole("progressbar", { name: "Purge of ADAUSDT" })).toHaveAttribute(
      "aria-valuenow",
      "42",
    );
    rerender(slot({ purge: { ...PURGE, pct: 43 } }));
    expect(screen.getByRole("progressbar", { name: "Purge of ADAUSDT" })).toHaveAttribute(
      "aria-valuenow",
      "43",
    );
  });
});

describe("the extension registry (#485/#486 BQ-6)", () => {
  it("a removal takes away only the parts it set, unless replaced since", () => {
    const seen: string[][] = [];
    function Probe() {
      seen.push(Object.keys(useRecorderExtensions()).sort());
      return null;
    }
    render(<Probe />);
    const editor = () => null;
    const panel = () => null;
    const other = () => null;
    let offA = (): void => undefined;
    let offB = (): void => undefined;
    act(() => {
      offA = registerRecorderExtensions({ RetentionEditor: editor, StoragePanel: panel });
    });
    act(() => {
      offB = registerRecorderExtensions({ StoragePanel: other, openRowDetail: () => undefined });
    });
    act(() => offA());
    expect(seen.at(-1)).toEqual(["StoragePanel", "openRowDetail"]);
    act(() => offB());
    expect(seen.at(-1)).toEqual([]);
  });
});

describe("the gap table (D02 §1, §2, §10.2; RG-08)", () => {
  it("lists start, end, duration and reason, each reason in words, an unknown one a gap", () => {
    const at = (time: string): number => Date.parse(`2026-09-14T${time}Z`);
    const gaps = [
      {
        symbol: "ETHUSDT",
        fromMs: at("10:14:03"),
        toMs: at("10:14:41"),
        reason: "backpressure_drop",
      },
      { symbol: "ETHUSDT", fromMs: at("09:00:00"), toMs: at("09:02:00"), reason: "something_new" },
      { symbol: "BTCUSDT", fromMs: at("08:00:00"), toMs: at("08:00:05"), reason: null },
    ];
    render(<GapTable gaps={gaps} nowMs={NOW} hostRef={createRef<HTMLDivElement>()} />);
    const table = screen.getByRole("table", { name: "Gaps recorded (last 24 h)" });
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.textContent);
    expect(rows).toEqual([
      "10:14:0310:14:4138 swrite gate (disk full)",
      "09:00:0009:02:002 mingap",
      "08:00:0008:00:055 sgap",
    ]);
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Start", "End", "Duration", "Reason"]);
  });

  it("a gap on an earlier UTC day carries its date (C-5309-13)", () => {
    const gaps = [
      {
        symbol: "ETHUSDT",
        fromMs: Date.parse("2026-09-13T23:10:00Z"),
        toMs: Date.parse("2026-09-14T00:00:05Z"),
        reason: null,
      },
    ];
    render(<GapTable gaps={gaps} nowMs={NOW} hostRef={createRef<HTMLDivElement>()} />);
    const row = within(screen.getByRole("table")).getAllByRole("row")[1];
    expect(row).toHaveTextContent("2026-09-13 23:10:0000:00:05");
  });

  it("renders nothing without a gap", () => {
    const { container } = render(
      <GapTable gaps={[]} nowMs={NOW} hostRef={createRef<HTMLDivElement>()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Compact now's terminal lines (D02 §3.2; SR-13)", () => {
  /** The line drawn under the button: its description (the shell's region says it, C-5347-d07). */
  const lineOf = (): HTMLElement => {
    const button = screen.getByRole("button", { name: /^(Compact now|Compacting)/ });
    return document.getElementById(button.getAttribute("aria-describedby") ?? "") as HTMLElement;
  };
  const run = async (answer: () => Response) => {
    apiFetch.mockImplementation(async (url) =>
      url.endsWith("/admin/recorder/compact") ? json(202, { job_id: JOB }) : answer(),
    );
    render(<CompactNow />);
    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));
    await flush();
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS)));
    return lineOf();
  };

  it("a failed job names its code; nothing was deleted", async () => {
    const line = await run(() => json(200, { id: JOB, status: "failed", error: "io_error" }));
    expect(line).toHaveTextContent("Compaction failed (io_error); nothing was deleted.");
  });

  it("a cancelled job", async () => {
    const line = await run(() => json(200, { id: JOB, status: "cancelled" }));
    expect(line).toHaveTextContent("Compaction cancelled; nothing was deleted.");
  });

  it("a lost job with no deck sentence ends the poll too, its T4 kept for the host to word", async () => {
    // A 404 whose body names no stable code routes to the generic T4, never a deck row: it is lost all the same.
    apiFetch.mockImplementation(async () => json(404));
    const { result, unmount } = renderHook(() => useJobPoll(JOB, "compact"));
    await flush();
    expect(result.current).toMatchObject({
      phase: "unknown",
      route: { kind: "t4", code: null, status: 404 },
    });
    const calls = apiFetch.mock.calls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS * 3)));
    expect(apiFetch.mock.calls.length).toBe(calls);
    unmount();
  });

  it("a second job starts running at 0 %, never on the last job's end (C-5347-01)", async () => {
    const SECOND = "19000000-0000-4000-8000-000000000002";
    apiFetch.mockImplementation(
      (url) =>
        url.endsWith(JOB)
          ? Promise.resolve(json(200, { id: JOB, status: "succeeded", progress_pct: 100 }))
          : new Promise<Response>(() => undefined), // the second job's first poll has not answered
    );
    const seen: string[] = [];
    const { rerender, unmount } = renderHook(
      ({ id }: { id: string }) => {
        const view = useJobPoll(id, "compact");
        seen.push(`${id} ${view?.phase ?? "none"} ${view?.pct ?? "-"}`);
        return view;
      },
      { initialProps: { id: JOB } },
    );
    await flush();
    expect(seen.at(-1)).toBe(`${JOB} succeeded 100`);
    rerender({ id: SECOND });
    await flush();
    // Every render of the second job, its first included, is running at 0 %: no frame shows the last job's end.
    expect(new Set(seen.filter((line) => line.startsWith(SECOND)))).toEqual(
      new Set([`${SECOND} running 0`]),
    );
    unmount();
  });

  it("a poll answered 503 shows the T4 with its code under the line; polling goes on (§16.4 row 10)", async () => {
    let answer = (): Response => json(200, { id: JOB, status: "running", progress_pct: 42 });
    apiFetch.mockImplementation(async (url) =>
      url.endsWith("/admin/recorder/compact") ? json(202, { job_id: JOB }) : answer(),
    );
    render(<CompactNow />);
    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));
    await flush();
    const busy = screen.getByRole("button", { name: /Compacting · 42 %/ });
    answer = () =>
      json(503, { code: "audit_unavailable", status: 503, title: "x", type: "about:blank" });
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS)));
    expect(lineOf()).toHaveTextContent(
      "Status not updated: the server refused it. (audit_unavailable)",
    );
    expect(busy).toHaveAccessibleName(/Compacting · 42 %/); // the last line kept, still busy
    const calls = apiFetch.mock.calls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS)));
    expect(apiFetch.mock.calls.length).toBe(calls + 1); // it polls on
    answer = () => json(200, { id: JOB, status: "running", progress_pct: 50 });
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS)));
    expect(lineOf()).toHaveTextContent(/^$/); // an answer clears it
    expect(busy).toHaveAccessibleName(/Compacting · 50 %/);
  });

  it("each line is said once through the shell's polite region, never a live region of its own (C-5347-d07)", async () => {
    let refuse = false;
    apiFetch.mockImplementation(async (url) => {
      if (!url.endsWith("/admin/recorder/compact"))
        return json(200, { id: JOB, status: "cancelled" });
      return refuse
        ? json(409, { code: "job_running", status: 409, title: "x", type: "about:blank" })
        : json(202, { job_id: JOB });
    });
    render(
      <>
        <CompactNow />
        <ShellAnnouncer />
      </>,
    );
    const region = document.querySelector(
      '[data-cv-inert-exempt][aria-live="polite"]',
    ) as HTMLElement;
    const said: string[] = [];
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) said.push(node.textContent ?? "");
      }
    }).observe(region, { childList: true });
    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));
    await flush();
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS * 3)));
    const CANCELLED = "Compaction cancelled; nothing was deleted.";
    expect(lineOf()).toHaveTextContent(CANCELLED);
    // Under the row detail's modal a region in the page is inert: the line has none (the A-5347-04 class).
    expect(lineOf().closest('[role="status"], [aria-live]')).toBeNull();
    expect(said).toEqual([CANCELLED]);
    refuse = true;
    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));
    await flush();
    const REFUSED = "A compaction is already running. (job_running)";
    expect(lineOf()).toHaveTextContent(REFUSED);
    expect(said).toEqual([CANCELLED, REFUSED]);
  });

  it("an unmount mid-job stops the poll: no request after it (C-5309-09)", async () => {
    apiFetch.mockImplementation(async (url) =>
      url.endsWith("/admin/recorder/compact")
        ? json(202, { job_id: JOB })
        : json(200, { id: JOB, status: "running", progress_pct: 42 }),
    );
    const { unmount } = render(<CompactNow />);
    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));
    await flush();
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS)));
    const calls = apiFetch.mock.calls.length;
    unmount();
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS * 5)));
    expect(apiFetch.mock.calls.length).toBe(calls);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a job lost to a restart (404 job_unknown) is the unknown line, and the poll stops", async () => {
    const line = await run(() =>
      json(404, {
        code: "not_found",
        status: 404,
        title: "x",
        type: "about:blank",
        errors: [{ rule: "job_unknown" }],
      }),
    );
    expect(line).toHaveTextContent("Compaction status is no longer available on the server.");
    const calls = apiFetch.mock.calls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(JOB_POLL_MS * 3)));
    expect(apiFetch.mock.calls.length).toBe(calls);
    expect(screen.getByRole("button", { name: "Compact now" })).not.toHaveAttribute("aria-busy");
  });
});

describe("a landing focus (D-5309-10)", () => {
  it("takes the design system's inset ring while it holds focus, and gives it back on blur", () => {
    render(
      <table>
        <caption>Gaps recorded (last 24 h)</caption>
      </table>,
    );
    const caption = document.querySelector("caption") as HTMLElement;
    focusLanding(caption);
    expect(caption).toHaveFocus();
    expect(caption).toHaveClass("cv-focus-ring", "cv-focus-ring--inset");
    expect(caption).toHaveAttribute("tabindex", "-1");
    act(() => caption.blur());
    expect(caption).not.toHaveClass("cv-focus-ring");
    expect(caption).not.toHaveAttribute("tabindex");
  });
});
