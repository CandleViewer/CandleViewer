/**
 * E16-S04, SCR-142's maintenance (E16-D04 §6, §7, §9; E16-D06 KB-15, FM-13, SR-13, SR-24, SR-28, T2-08, T2-09,
 * T2-11, §13 "A compaction"; BQ-7, BQ-10, BQ-11, BQ-14): Compact Parquet… behind CMP-044 standard (Cancel first,
 * nothing deleted, audited), its job on the shared 2 s poll with the strip's line as the bar's value text, said once at
 * the start and once at the end, never per poll; `409 job_running` as T4 at the control; no Stop control; Purge data…
 * on the QuestDB and Parquet cards handing over to the page's purge (#484 PR 3's dialog); and every write T2 while
 * viewing as, pointing at the one notice. Over the stubbed `apiFetch` and fake timers.
 */
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { recorderApi } from "../../../../src/features/recorder/recorderApi";
import { JOB_POLL_MS } from "../../../../src/features/recorder/useJobPoll";
import {
  HEADING,
  advance,
  card,
  flush,
  json,
  mount,
  panel,
  problem,
  section,
  sent,
  seriousAxe,
  shellSaid,
  utterances,
  writeHeaders,
  writes,
  type Route,
} from "./panelHarness";
import { CLOCK, COMPACT_JOB, LEVEL_3, jobAnswer } from "./storageFixtures";

const NOTICE = "Read-only — read-only while viewing as alex.";
const GUARD_MS = 500;

/** The compaction route: a 202 with its job, then the poll's answers in turn (the last one repeats). */
function compaction(answers: readonly Parameters<typeof jobAnswer>[1][]): Route {
  let polls = 0;
  return (method, url) => {
    if (method === "POST" && url.endsWith("/admin/recorder/compact")) {
      return json(202, { job_id: COMPACT_JOB });
    }
    if (url.endsWith(`/admin/jobs/${COMPACT_JOB}`)) {
      const answer = answers[Math.min(polls, answers.length - 1)];
      polls += 1;
      return json(200, jobAnswer(COMPACT_JOB, answer));
    }
    return undefined;
  };
}
const maintenance = (): HTMLElement => card("Maintenance");
const compactIn = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("button", { name: /Compact Parquet…$/ });

async function openConfirm(host: HTMLElement = maintenance()): Promise<HTMLElement> {
  const opener = compactIn(host);
  act(() => opener.focus());
  fireEvent.click(opener);
  await flush();
  return screen.getByRole("dialog", { name: "Compact Parquet partitions?" });
}
async function confirmCompaction(): Promise<void> {
  const dialog = await openConfirm();
  await advance(GUARD_MS);
  fireEvent.click(within(dialog).getByRole("button", { name: "Compact" }));
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: CLOCK,
  });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  act(() => clearAnnouncements());
  apiFetch.mockReset();
  vi.useRealTimers();
});

const CASE = { timeout: 30_000 } as const;

describe("JOB/confirm-compact: CMP-044 standard, Cancel first (KB-15; BQ-10)", CASE, () => {
  it("opens on Cancel with what it does, the audit line and its three exits", async () => {
    const { container } = await mount();
    const dialog = await openConfirm();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(dialog).toHaveTextContent(
      "Merges small files into partitions of at most 512 MiB. Nothing is deleted. Replay is paused on partitions it touches.",
    );
    expect(dialog).toHaveTextContent("This action is audited.");
    expect(within(dialog).queryByRole("textbox")).toBeNull();
    expect(
      within(dialog).getByRole("button", { name: "Close Compact Parquet partitions?" }),
    ).toBeVisible();
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("Cancel sends nothing and returns focus to the button that opened it (FM-13)", async () => {
    await mount();
    const opener = compactIn(maintenance());
    const dialog = await openConfirm();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await flush();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    expect(writes()).toEqual([]);
  });

  it("Compact Parquet… sits on the Parquet card and in the maintenance card, opening the one dialog", async () => {
    await mount();
    expect(within(card("QuestDB · hot")).queryByRole("button", { name: /Compact/ })).toBeNull();
    const dialog = await openConfirm(card("Parquet/DuckDB · cold"));
    expect(dialog).toBeVisible();
  });
});

describe(
  "a compaction runs as a job (AC 5; D04 §6 JOB/strip-running, JOB/outcomes; SR-13, SR-24)",
  CASE,
  () => {
    it("Compact sends one compaction with its key; the strip's line is its bar's value text; both buttons busy", async () => {
      await mount(
        {},
        compaction([
          { status: "running", progress_pct: 42 },
          { status: "running", progress_pct: 43 },
          { status: "succeeded", progress_pct: 100, finished_at: "2026-09-14T10:42:00Z" },
        ]),
      );
      await confirmCompaction();
      expect(writes()).toEqual(["POST /admin/recorder/compact"]);
      expect(writeHeaders(0).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
      const bar = within(maintenance()).getByRole("progressbar", { name: "Compaction" });
      expect(bar).toHaveAttribute("aria-valuetext", "Compaction running · 42 %");
      expect(maintenance()).toHaveTextContent("Compaction running · 42 %");
      expect(compactIn(maintenance())).toHaveAttribute("aria-busy", "true");
      expect(compactIn(card("Parquet/DuckDB · cold"))).toHaveAttribute("aria-busy", "true");
      expect(await seriousAxe(section())).toEqual([]);
    });

    it("polls every 2 s and says the start and the end once each", async () => {
      await mount(
        {},
        compaction([
          { status: "running", progress_pct: 42 },
          { status: "running", progress_pct: 43 },
          { status: "succeeded", progress_pct: 100, finished_at: "2026-09-14T10:42:00Z" },
        ]),
      );
      const said = utterances();
      await confirmCompaction();
      await advance(JOB_POLL_MS);
      expect(
        within(maintenance()).getByRole("progressbar", { name: "Compaction" }),
      ).toHaveAttribute("aria-valuetext", "Compaction running · 43 %");
      await advance(JOB_POLL_MS);
      expect(maintenance()).toHaveTextContent("Compacted at 10:42 UTC");
      expect(within(maintenance()).queryByRole("progressbar")).toBeNull();
      expect(said()).toEqual(["Compaction started", "Compacted at 10:42 UTC"]);
      expect(compactIn(maintenance())).not.toHaveAttribute("aria-busy");
      expect(within(section()).queryByRole("alert")).toBeNull();
    });

    it("a press while it runs opens nothing (busy, not T2)", async () => {
      await mount({}, compaction([{ status: "queued", progress_pct: 0 }]));
      await confirmCompaction();
      expect(maintenance()).toHaveTextContent("Compaction queued");
      fireEvent.click(compactIn(maintenance()));
      await flush();
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(compactIn(maintenance())).not.toHaveAttribute("aria-disabled");
    });

    it.each([
      [
        "failed",
        { status: "failed", error: "io_error" },
        "Compaction failed (io_error); nothing was deleted.",
      ],
      ["cancelled", { status: "cancelled" }, "Compaction cancelled; nothing was deleted."],
    ] as const)(
      "a %s compaction reads its line once, politely, inside the card",
      async (_, answer, line) => {
        await mount({}, compaction([answer]));
        const said = utterances();
        await confirmCompaction();
        expect(maintenance()).toHaveTextContent(line);
        expect(said()).toEqual(["Compaction started", line]);
        expect(within(section()).queryByRole("alert")).toBeNull();
      },
    );

    it("a success that left partitions as they were says how many, with its line, once (C-486P3-05)", async () => {
      const result = {
        compacted: 12,
        skipped: 3,
        deferred: ["SOLUSDT/2026-09-03"],
        failed: ["BTCUSDT/2026-09-01", "ETHUSDT/2026-09-02"],
      };
      await mount(
        {},
        compaction([{ status: "succeeded", finished_at: "2026-09-14T10:42:00Z", result }]),
      );
      const said = utterances();
      await confirmCompaction();
      const detail =
        "Partitions not compacted: 2 failed the row-count check, 1 in use by a replay.";
      expect(maintenance()).toHaveTextContent("Compacted at 10:42 UTC");
      expect(maintenance()).toHaveTextContent(detail);
      expect(said()).toEqual(["Compaction started", `Compacted at 10:42 UTC. ${detail}`]);
      expect(maintenance()).not.toHaveTextContent("BTCUSDT/2026-09-01");
      await advance(JOB_POLL_MS * 3);
      expect(said()).toHaveLength(2);
    });

    it("a lost job (404 job_unknown) reads the unknown line", async () => {
      await mount({}, (method, url) =>
        method === "POST" && url.endsWith("/admin/recorder/compact")
          ? json(202, { job_id: COMPACT_JOB })
          : url.endsWith(`/admin/jobs/${COMPACT_JOB}`)
            ? problem(404, "job_unknown")
            : undefined,
      );
      await confirmCompaction();
      expect(maintenance()).toHaveTextContent(
        "Compaction status is no longer available on the server.",
      );
    });

    it("a lost job's 404 with no code ends the poll on the unknown line too (C-486P3-01)", async () => {
      await mount({}, (method, url) =>
        method === "POST" && url.endsWith("/admin/recorder/compact")
          ? json(202, { job_id: COMPACT_JOB })
          : url.endsWith(`/admin/jobs/${COMPACT_JOB}`)
            ? json(404)
            : undefined,
      );
      const said = utterances();
      await confirmCompaction();
      const lost = "Compaction status is no longer available on the server.";
      expect(maintenance()).toHaveTextContent(lost);
      const polls = (): number => sent().filter((line) => line.includes("/admin/jobs/")).length;
      const before = polls();
      await advance(JOB_POLL_MS * 3);
      expect(polls()).toBe(before);
      expect(said()).toEqual(["Compaction started", lost]);
      expect(compactIn(maintenance())).not.toHaveAttribute("aria-busy");
    });

    it("a poll the server refuses shows its T4 under the strip's line, said once; an answer clears it (§16.4 row 10; C-486P3-01)", async () => {
      let answer = (): Response =>
        json(200, jobAnswer(COMPACT_JOB, { status: "running", progress_pct: 42 }));
      const say = vi.fn<(text: string) => void>();
      await mount({ say }, (method, url) =>
        method === "POST" && url.endsWith("/admin/recorder/compact")
          ? json(202, { job_id: COMPACT_JOB })
          : url.endsWith(`/admin/jobs/${COMPACT_JOB}`)
            ? answer()
            : undefined,
      );
      await confirmCompaction();
      const bar = (): HTMLElement =>
        within(maintenance()).getByRole("progressbar", { name: "Compaction" });
      const T4 = "Status not updated: the server refused it. (audit_unavailable)";
      answer = () => problem(503, "audit_unavailable");
      await advance(JOB_POLL_MS);
      await advance(JOB_POLL_MS); // a second refused poll is no second word
      expect(bar()).toHaveAttribute("aria-valuetext", "Compaction running · 42 %"); // the last line kept
      const error = within(maintenance()).getByText(T4);
      // CMP-027 inline under the line, no live role of its own: said once, through the shell announcer.
      expect(error.closest("[data-cmp='CMP-027']")).not.toBeNull();
      expect(error.closest("[role='alert'], [role='status'], [aria-live]")).toBeNull();
      expect(say.mock.calls).toEqual([[T4]]);
      expect(compactIn(maintenance())).toHaveAttribute("aria-busy", "true");
      expect(section()).not.toHaveTextContent("never rendered");
      answer = () => json(200, jobAnswer(COMPACT_JOB, { status: "running", progress_pct: 50 }));
      await advance(JOB_POLL_MS);
      expect(maintenance()).not.toHaveTextContent(T4);
      expect(bar()).toHaveAttribute("aria-valuetext", "Compaction running · 50 %");
      expect(say.mock.calls).toEqual([[T4]]);
    });

    it("a 2xx with no job id reads the generic T4 at the control, which stays usable (C-486P3-09)", async () => {
      await mount({}, (method, url) =>
        method === "POST" && url.endsWith("/admin/recorder/compact") ? json(202, {}) : undefined,
      );
      await confirmCompaction();
      expect(maintenance()).toHaveTextContent("Not started: the server refused it.");
      expect(compactIn(maintenance())).not.toHaveAttribute("aria-busy");
    });

    it("a send that throws leaves the control usable, with the app's words (C-486P3-09)", async () => {
      const spy = vi.spyOn(recorderApi, "compact").mockRejectedValueOnce(new Error("boom"));
      try {
        await mount();
        await confirmCompaction();
        expect(compactIn(maintenance())).not.toHaveAttribute("aria-busy");
        expect(maintenance()).toHaveTextContent("Cannot reach the server. Try again.");
      } finally {
        spy.mockRestore();
      }
    });

    it("stops polling once unmounted (teardown)", async () => {
      const view = await mount({}, compaction([{ status: "running", progress_pct: 42 }]));
      await confirmCompaction();
      view.unmount();
      apiFetch.mockClear();
      await advance(10 * JOB_POLL_MS);
      expect(apiFetch.mock.calls.filter(([url]) => url.includes("/admin/jobs/"))).toEqual([]);
    });
  },
);

describe("JOB/strip-refused-409: a refusal at the point of action (T4; SR-28)", CASE, () => {
  it("409 job_running reads under the control that was pressed, said once; it stays enabled", async () => {
    const { container } = await mount({}, (method, url) =>
      method === "POST" && url.endsWith("/admin/recorder/compact")
        ? problem(409, "job_running")
        : undefined,
    );
    const parquet = card("Parquet/DuckDB · cold");
    const dialog = await openConfirm(parquet);
    await advance(GUARD_MS);
    fireEvent.click(within(dialog).getByRole("button", { name: "Compact" }));
    await flush();
    expect(parquet).toHaveTextContent("A compaction is already running. (job_running)");
    expect(maintenance()).not.toHaveTextContent("already running");
    expect(shellSaid()).toBe("A compaction is already running. (job_running)");
    expect(section()).not.toHaveTextContent("never rendered");
    expect(compactIn(parquet)).not.toHaveAttribute("aria-disabled");
    expect(compactIn(parquet)).not.toHaveAttribute("aria-busy");
    await advance(10 * JOB_POLL_MS); // nothing is re-sent (C-486P3-06)
    expect(writes()).toEqual(["POST /admin/recorder/compact"]);
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("any other refusal is the generic T4 with its code", async () => {
    await mount({}, (method, url) =>
      method === "POST" && url.endsWith("/admin/recorder/compact")
        ? problem(503, "audit_unavailable")
        : undefined,
    );
    await confirmCompaction();
    expect(maintenance()).toHaveTextContent(
      "Not started: the server refused it. (audit_unavailable)",
    );
    await advance(10 * JOB_POLL_MS);
    expect(writes()).toEqual(["POST /admin/recorder/compact"]);
  });

  it("no answer reads the app's words at the control; nothing is re-sent (C-486P3-06)", async () => {
    await mount({}, (method, url) => {
      if (method === "POST" && url.endsWith("/admin/recorder/compact")) {
        throw new TypeError("Failed to fetch");
      }
      return undefined;
    });
    await confirmCompaction();
    expect(maintenance()).toHaveTextContent("Cannot reach the server. Try again.");
    expect(compactIn(maintenance())).not.toHaveAttribute("aria-disabled");
    await advance(10 * JOB_POLL_MS);
    expect(writes()).toEqual(["POST /admin/recorder/compact"]);
  });

  it("no Stop control exists: a started job runs to its end (D04-G10)", async () => {
    await mount({}, compaction([{ status: "running", progress_pct: 42 }]));
    await confirmCompaction();
    expect(within(section()).queryByRole("button", { name: /Stop|Cancel/ })).toBeNull();
  });
});

describe("the section's polite region under a modal (A-486P3-05; E05-D02 H23)", CASE, () => {
  /** What a modal does to the page under it: `inert`, or `aria-hidden` where the engine has none. */
  const outOfTheTree = (element: Element): boolean =>
    element.closest('[inert], [aria-hidden="true"]') !== null;
  /** The region found without the accessibility tree, which the modal prunes. */
  const live = (): Element =>
    document.querySelector(`section[aria-labelledby="${HEADING}"] > [role="status"]`) as Element;

  it("stays exposed under the compaction confirm, as the shell's regions do; a line said then is there", async () => {
    await mount();
    await openConfirm();
    expect(live()).toHaveAttribute("data-cv-inert-exempt", "");
    expect(outOfTheTree(live())).toBe(false);
    // The rest of the section is under the modal's inert, as it was.
    const h2 = screen.getByRole("heading", {
      level: 2,
      name: "Storage and database",
      hidden: true,
    });
    expect(outOfTheTree(h2)).toBe(true);
    await advance(121_000); // the turn to stale is said while the confirm is open
    expect(live()).toHaveTextContent("Storage figures are stale");
    expect(outOfTheTree(live())).toBe(false);
  });
});

describe("Purge data… hands over to the page's purge (D04 §7; BQ-7, BQ-9)", CASE, () => {
  it("sits on the QuestDB and Parquet cards only and opens the page's one dialog", async () => {
    const open = vi.fn();
    await mount({ purge: { busy: false, open } });
    const questdb = within(card("QuestDB · hot")).getByRole("button", { name: "Purge data…" });
    expect(
      within(card("Parquet/DuckDB · cold")).getByRole("button", { name: "Purge data…" }),
    ).toBeVisible();
    expect(
      within(card("Postgres · relational")).queryByRole("button", { name: /Purge/ }),
    ).toBeNull();
    expect(within(maintenance()).queryByRole("button", { name: /Purge/ })).toBeNull();
    fireEvent.click(questdb);
    expect(open).toHaveBeenCalledWith();
  });

  it("is busy while the page's purge runs, and absent until the page hands it over", async () => {
    const open = vi.fn();
    const view = await mount({ purge: { busy: true, open } });
    const button = within(card("QuestDB · hot")).getByRole("button", { name: "Purge data…" });
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(open).not.toHaveBeenCalled();
    view.rerender(panel({}));
    expect(within(section()).queryByRole("button", { name: /Purge/ })).toBeNull();
  });
});

describe("writes stay enabled in every state (BQ-14, BQ-15)", CASE, () => {
  it("at level 3 Compact Parquet… and Purge data… open as usual", async () => {
    const open = vi.fn();
    await mount({ frame: null, purge: { busy: false, open } }, (_, url) =>
      url.endsWith("/recording/storage") ? json(200, LEVEL_3) : undefined,
    );
    expect(section()).toHaveTextContent("Recording pauses before trading is affected.");
    fireEvent.click(
      within(card("Parquet/DuckDB · cold")).getByRole("button", { name: "Purge data…" }),
    );
    expect(open).toHaveBeenCalled();
    const dialog = await openConfirm();
    expect(dialog).toBeVisible();
  });
});

describe("SCR-142/view-as: every write T2, one notice (T2-09; G-T2.1–G-T2.5)", CASE, () => {
  it("each write keeps its label with the lock, aria-disabled, described by the notice", async () => {
    const { container } = await mount({
      viewAs: { user: "alex" },
      purge: { busy: false, open: vi.fn() },
    });
    const notice = within(section()).getByText(NOTICE);
    const gated = within(section()).getAllByRole("button", { name: /^Not available/ });
    expect(gated.map((b) => b.textContent)).toEqual([
      "Purge data…",
      "Compact Parquet…",
      "Purge data…",
      "Compact Parquet…",
      "Import archives",
    ]);
    for (const button of gated) {
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).not.toHaveAttribute("disabled");
      expect(button.getAttribute("aria-describedby")?.split(" ")).toContain(notice.id);
    }
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("a press re-shows the reason once and opens nothing", async () => {
    const open = vi.fn();
    await mount({ viewAs: { user: "alex" }, purge: { busy: false, open } });
    fireEvent.click(compactIn(maintenance()));
    await flush();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(shellSaid()).toBe("Read-only while viewing as alex.");
    fireEvent.click(within(card("QuestDB · hot")).getByRole("button", { name: /Purge data…$/ }));
    expect(open).not.toHaveBeenCalled();
    expect(writes()).toEqual([]);
  });

  it("a running job keeps updating while viewing as", async () => {
    const view = await mount(
      {},
      compaction([
        { status: "running", progress_pct: 42 },
        { status: "running", progress_pct: 60 },
      ]),
    );
    await confirmCompaction();
    view.rerender(panel({ viewAs: { user: "alex" } }));
    await advance(JOB_POLL_MS);
    expect(within(maintenance()).getByRole("progressbar", { name: "Compaction" })).toHaveAttribute(
      "aria-valuetext",
      "Compaction running · 60 %",
    );
  });
});
