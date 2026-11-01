/**
 * E16-S04, SCR-142's archive import (US-REC-007; E16-D04 §8, §10; E16-D06 KB-17, FM-13, SR-24 to SR-26, SR-28,
 * T2-09, T2-10, §13 "An import that skips a file"; BQ-4, BQ-12; AC 6): the card's form is the confirm (BQ-12), its
 * range at most 366 days behind the validity look (a press moves focus to the reason), Enter moving From → To →
 * Import archives; the job on the shared 2 s poll, "{done} of {n} days · {pct} %" in the card and the strip's line,
 * "Import started" and the finished line once each, a skipped file never announced; the summary from the served
 * `ArchiveImportResult` (BQ-4); a failure inside the card, `role="alert"` once; refusals at the control; view-as T2.
 */
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import type { ArchiveImportResult, Job } from "../../../../src/features/recorder/recorderApi";
import { JOB_POLL_MS } from "../../../../src/features/recorder/useJobPoll";
import {
  advance,
  card,
  flush,
  json,
  mount,
  panel,
  problem,
  rowsOf,
  section,
  sent,
  seriousAxe,
  shellSaid,
  utterances,
  writeHeaders,
  writes,
  type Route,
} from "./panelHarness";
import { CLOCK, IMPORT_JOB, jobAnswer } from "./storageFixtures";

const REASON = "Choose a range of at most 366 days.";
/** The January import's one write, as sent. */
const JANUARY_WRITE =
  'POST /admin/recorder/import {"symbol":"BTCUSDT","from":"2026-01-01","to":"2026-01-31"}';
const NOTICE = "Read-only — read-only while viewing as alex.";

/** E16-D04's fixture run, as served (BQ-4): 31 days, 29 written, one checksum skip, one download failure. */
const JANUARY: ArchiveImportResult = {
  symbol: "BTCUSDT",
  from: "2026-01-01",
  to: "2026-01-31",
  files_total: 31,
  files_processed: 29,
  files_already_imported: 0,
  files_skipped: [
    { file: "BTCUSDT2026-01-14.csv.gz", reason: "import_checksum_failed" },
    { file: "BTCUSDT2026-01-31.csv.gz", reason: "import_download_failed" },
  ],
  rows_written: 2756160000,
  rows_discarded_overlap: 660000,
  rows_discarded_duplicate: 0,
  overlap: [{ from: "2026-01-20T10:00:00Z", to: "2026-01-20T10:10:00Z" }],
  bytes_downloaded: 1048576,
  already_imported: { rows_written: 0, rows_discarded_overlap: 0, rows_discarded_duplicate: 0 },
  streams: ["trades"],
  source: "archive",
};

/** The import route: a 202 with its job, then the poll's answers in turn (the last one repeats). */
function importing(answers: readonly Partial<Job>[]): Route {
  let polls = 0;
  return (method, url) => {
    if (method === "POST" && url.endsWith("/admin/recorder/import")) {
      return json(202, { job_id: IMPORT_JOB });
    }
    if (url.endsWith(`/admin/jobs/${IMPORT_JOB}`)) {
      const answer = answers[Math.min(polls, answers.length - 1)];
      polls += 1;
      return json(200, jobAnswer(IMPORT_JOB, { kind: "archive_import", ...answer }));
    }
    return undefined;
  };
}

const importCard = (): HTMLElement => card("Import archives");
const importButton = (): HTMLElement =>
  within(importCard()).getByRole("button", { name: /Import archives$/ });
const field = (name: "From" | "To"): HTMLElement =>
  within(importCard()).getByRole("textbox", { name });

/** Types a day into a range well and commits it (CMP-047 commits on blur). */
function typeDay(name: "From" | "To", day: string): void {
  const input = field(name);
  fireEvent.change(input, { target: { value: day } });
  fireEvent.blur(input);
}
async function fillJanuary(): Promise<void> {
  typeDay("From", "2026-01-01");
  typeDay("To", "2026-01-31");
  await flush();
}
async function submit(): Promise<void> {
  fireEvent.click(importButton());
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

describe("IMPORT/form: the form is the confirm (BQ-12; D04 §8)", CASE, () => {
  it("states what an import does, labels it archive-derived, and offers a known symbol and a range", async () => {
    const { container } = await mount({ instruments: ["SOLUSDT", "BTCUSDT"] });
    const host = importCard();
    expect(host).toHaveTextContent(
      "Imports Bybit's public daily trade archives (trades only, no book data). Recorded data wins where they overlap. Re-running skips finished days.",
    );
    expect(within(host).getByText("Archive-derived · trades only · no book data")).toBeVisible();
    expect(within(host).getByRole("combobox", { name: "Symbol" })).toHaveTextContent("BTCUSDT");
    expect(within(host).getByRole("group", { name: "Date range" })).toBeVisible();
    expect(field("From")).toHaveValue("");
    expect(field("To")).toHaveValue("");
    expect(within(host).queryByRole("textbox", { name: /url|path|file/i })).toBeNull();
    expect(await seriousAxe(container)).toEqual([]);
  });

  it("the symbols are the recorder's and the instrument index's, in order", async () => {
    await mount({ instruments: ["SOLUSDT", "BTCUSDT"] });
    fireEvent.click(within(importCard()).getByRole("combobox", { name: "Symbol" }));
    await flush();
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      "BTCUSDT",
      "ETHUSDT",
      "SOLUSDT",
    ]);
  });

  it("the preselected symbol stays put as the instrument index grows (C-486P3-11)", async () => {
    const view = await mount({ instruments: ["SOLUSDT"] });
    const symbol = (): HTMLElement =>
      within(importCard()).getByRole("combobox", { name: "Symbol" });
    expect(symbol()).toHaveTextContent("BTCUSDT");
    view.rerender(panel({ instruments: ["1000BONKUSDT", "SOLUSDT"] }));
    await flush();
    expect(symbol()).toHaveTextContent("BTCUSDT");
  });
});

describe("IMPORT/form-validity: at most 366 days, the validity look (T2-10; FM-13)", CASE, () => {
  it("an empty range keeps the reason under Import archives; a press sends nothing and moves focus to it", async () => {
    await mount();
    const button = importButton();
    const reason = within(importCard()).getByText(REASON);
    expect(button.getAttribute("aria-describedby")?.split(" ")).toContain(reason.id);
    expect(button).not.toHaveAttribute("disabled");
    act(() => button.focus());
    await submit();
    expect(reason).toHaveFocus();
    expect(writes()).toEqual([]);
  });

  it.each([
    ["inverted", "2026-01-31", "2026-01-01"],
    ["367 days", "2025-01-01", "2026-01-02"],
  ])("a %s range keeps the reason", async (_, from, to) => {
    await mount();
    typeDay("From", from);
    typeDay("To", to);
    await flush();
    expect(importCard()).toHaveTextContent(REASON);
    await submit();
    expect(writes()).toEqual([]);
  });

  it("a range of 366 days clears it", async () => {
    await mount();
    typeDay("From", "2025-01-01");
    typeDay("To", "2026-01-01");
    await flush();
    expect(importCard()).not.toHaveTextContent(REASON);
  });

  it("the pick ends today, UTC: a later day is the field's own error and is not taken", async () => {
    await mount();
    typeDay("From", "2026-09-01");
    typeDay("To", "2026-09-15");
    await flush();
    expect(importCard()).toHaveTextContent("Choose a date on or before 2026-09-14.");
    expect(importCard()).toHaveTextContent(REASON);
  });

  it("a typed end the field rejects is never sent: a press moves focus to it (C-486P3-03 (b), probe A)", async () => {
    await mount({}, importing([{ status: "running", progress_pct: 0 }]));
    await fillJanuary();
    typeDay("To", "2026-09-30"); // after today, 2026-09-14: kept with its error, nothing committed
    await flush();
    expect(field("To")).toHaveValue("2026-09-30");
    expect(field("To")).toHaveAttribute("aria-invalid", "true");
    await submit();
    expect(writes()).toEqual([]);
    expect(field("To")).toHaveFocus();
  });

  it("Enter in a field the well rejected stays there (C-486P3-03 (c))", async () => {
    await mount();
    typeDay("From", "2026-09-01");
    await flush();
    const to = field("To");
    act(() => to.focus());
    fireEvent.change(to, { target: { value: "2026-09-30" } });
    fireEvent.keyDown(to, { key: "Enter" });
    await flush();
    expect(to).toHaveFocus();
    expect(to).toHaveAttribute("aria-invalid", "true");
    // Once the well takes the entry, Enter moves on (KB-17).
    fireEvent.change(to, { target: { value: "2026-09-10" } });
    fireEvent.keyDown(to, { key: "Enter" });
    await flush();
    expect(importButton()).toHaveFocus();
  });

  it("Enter in From moves to To, and in To to Import archives (KB-17)", async () => {
    await mount();
    const from = field("From");
    act(() => from.focus());
    fireEvent.change(from, { target: { value: "2026-01-01" } });
    fireEvent.keyDown(from, { key: "Enter" });
    await flush();
    expect(field("To")).toHaveFocus();
    fireEvent.change(field("To"), { target: { value: "2026-01-31" } });
    fireEvent.keyDown(field("To"), { key: "Enter" });
    await flush();
    expect(importButton()).toHaveFocus();
    expect(importCard()).not.toHaveTextContent(REASON);
  });
});

describe(
  "an import runs as a job (AC 6; D04 §8 IMPORT/running, running-with-skips; SR-24)",
  CASE,
  () => {
    it("sends the symbol and the inclusive range once, then shows its days and the strip's line", async () => {
      await mount({}, importing([{ status: "running", progress_pct: 38.71 }]));
      const said = utterances();
      await fillJanuary();
      await submit();
      expect(writes()).toEqual([
        'POST /admin/recorder/import {"symbol":"BTCUSDT","from":"2026-01-01","to":"2026-01-31"}',
      ]);
      expect(writeHeaders(0).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
      expect(within(importCard()).getByRole("progressbar", { name: "Import" })).toHaveAttribute(
        "aria-valuetext",
        "12 of 31 days · 38 %",
      );
      expect(
        within(card("Maintenance")).getByRole("progressbar", { name: "Import" }),
      ).toHaveAttribute("aria-valuetext", "Import running · 38 %");
      expect(importButton()).toHaveAttribute("aria-busy", "true");
      expect(said()).toEqual(["Import started"]);
      expect(await seriousAxe(section())).toEqual([]);
    });

    it("the chosen symbol is the one sent", async () => {
      await mount({}, importing([{ status: "running", progress_pct: 0 }]));
      fireEvent.click(within(importCard()).getByRole("combobox", { name: "Symbol" }));
      await flush();
      fireEvent.click(screen.getByRole("option", { name: "ETHUSDT" }));
      await fillJanuary();
      await submit();
      expect(writes()[0]).toContain('"symbol":"ETHUSDT"');
    });

    it("progress moves without a word; a skip is never a page error or an announcement", async () => {
      await mount(
        {},
        importing([
          { status: "running", progress_pct: 38.71 },
          { status: "running", progress_pct: 96.77 },
        ]),
      );
      const said = utterances();
      await fillJanuary();
      await submit();
      await advance(JOB_POLL_MS);
      expect(within(importCard()).getByRole("progressbar", { name: "Import" })).toHaveAttribute(
        "aria-valuetext",
        "30 of 31 days · 96 %",
      );
      expect(said()).toEqual(["Import started"]);
      expect(within(section()).queryByRole("alert")).toBeNull();
    });

    it("a poll the server refuses shows its T4 under the bar and the strip's line, said once; an answer clears it (§16.4 row 10; C-486P3-01)", async () => {
      let answer = (): Response =>
        json(
          200,
          jobAnswer(IMPORT_JOB, { kind: "archive_import", status: "running", progress_pct: 38.71 }),
        );
      const say = vi.fn<(text: string) => void>();
      await mount({ say }, (method, url) =>
        method === "POST" && url.endsWith("/admin/recorder/import")
          ? json(202, { job_id: IMPORT_JOB })
          : url.endsWith(`/admin/jobs/${IMPORT_JOB}`)
            ? answer()
            : undefined,
      );
      await fillJanuary();
      await submit();
      const T4 = "Status not updated: the server refused it. (audit_unavailable)";
      answer = () => problem(503, "audit_unavailable");
      await advance(JOB_POLL_MS);
      await advance(JOB_POLL_MS);
      const bar = (): HTMLElement =>
        within(importCard()).getByRole("progressbar", { name: "Import" });
      expect(bar()).toHaveAttribute("aria-valuetext", "12 of 31 days · 38 %"); // the last line kept
      for (const host of [importCard(), card("Maintenance")]) {
        const error = within(host).getByText(T4);
        expect(error.closest("[data-cmp='CMP-027']")).not.toBeNull();
        expect(error.closest("[role='alert'], [role='status'], [aria-live]")).toBeNull();
      }
      expect(say.mock.calls).toEqual([[T4]]);
      answer = () =>
        json(
          200,
          jobAnswer(IMPORT_JOB, { kind: "archive_import", status: "running", progress_pct: 50 }),
        );
      await advance(JOB_POLL_MS);
      expect(section()).not.toHaveTextContent(T4);
      expect(bar()).toHaveAttribute("aria-valuetext", "16 of 31 days · 50 %");
    });

    it("a lost import's 404 with no code ends the poll on the unknown line (C-486P3-01)", async () => {
      await mount({}, (method, url) =>
        method === "POST" && url.endsWith("/admin/recorder/import")
          ? json(202, { job_id: IMPORT_JOB })
          : url.endsWith(`/admin/jobs/${IMPORT_JOB}`)
            ? json(404)
            : undefined,
      );
      const said = utterances();
      await fillJanuary();
      await submit();
      const line =
        "The import's status is no longer available on the server. Run it again: finished days are skipped.";
      expect(importCard()).toHaveTextContent(line);
      const polls = (): number => sent().filter((call) => call.includes("/admin/jobs/")).length;
      const before = polls();
      await advance(JOB_POLL_MS * 3);
      expect(polls()).toBe(before);
      expect(said()).toEqual(["Import started", line]);
      expect(importButton()).not.toHaveAttribute("aria-busy");
    });

    it("stops polling once unmounted (teardown)", async () => {
      const view = await mount({}, importing([{ status: "running", progress_pct: 10 }]));
      await fillJanuary();
      await submit();
      view.unmount();
      apiFetch.mockClear();
      await advance(10 * JOB_POLL_MS);
      expect(apiFetch).not.toHaveBeenCalled();
    });
  },
);

describe("IMPORT/summary: the import reports honestly (AC 6; BQ-4; SR-25)", CASE, () => {
  it("states files processed, rows written, overlap discarded and each skipped file with its reason", async () => {
    await mount(
      {},
      importing([
        { status: "running", progress_pct: 50 },
        { status: "succeeded", progress_pct: 100, result: JANUARY },
      ]),
    );
    const said = utterances();
    await fillJanuary();
    await submit();
    await advance(JOB_POLL_MS);
    const host = importCard();
    expect(host).toHaveTextContent("Import finished: BTCUSDT, 2026-01-01 → 2026-01-31");
    expect(said()).toEqual(["Import started", "Import finished: BTCUSDT, 2026-01-01 → 2026-01-31"]);
    expect(rowsOf(host)).toEqual({
      "Files processed": "29 of 31",
      "Rows written": "2,756,160,000",
      "Rows discarded as overlap": "660,000",
      "Files skipped": "2",
    });
    expect(host).toHaveTextContent(
      "660,000 rows inside recorded windows were discarded — recorded data wins.",
    );
    expect(within(host).getAllByText("Archive-derived · trades only · no book data").length).toBe(
      2,
    );
    const table = within(host).getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Day", "Status", "Reason"]);
    const [, first, second] = within(table).getAllByRole("row");
    expect(first).toHaveTextContent(
      "2026-01-14 skippedChecksum did not match; the file was skipped. (import_checksum_failed)",
    );
    expect(second).toHaveTextContent(
      "2026-01-31 errorThe file could not be downloaded; run the import again to retry it. (import_download_failed)",
    );
    expect(host).toHaveTextContent("Run it again to resume: finished days are skipped.");
    expect(importButton()).not.toHaveAttribute("aria-busy");
    expect(within(section()).queryByRole("alert")).toBeNull();
    // Day and Status take their words' widths, and the reason the rest: never cut (A-486P3-02).
    const widths = [...table.querySelectorAll("col")].map((col) => col.style.width);
    expect(widths).toEqual(["8em", "9em", ""]);
    expect(await seriousAxe(section())).toEqual([]);
  });
});

describe("IMPORT/failed: inside the card, an alert once (SR-26; R-9)", CASE, () => {
  it("a failed import reads its line as an alert inside its card, never a page banner", async () => {
    await mount({}, importing([{ status: "failed", error: "download_failed" }]));
    const said = utterances();
    await fillJanuary();
    await submit();
    const alert = within(importCard()).getByRole("alert");
    await flush();
    expect(alert).toHaveTextContent(
      "Import failed (download_failed). Finished days are kept; run it again to resume.",
    );
    expect(within(section()).getAllByRole("alert")).toHaveLength(1);
    expect(said()).toEqual(["Import started"]);
    expect(importButton()).not.toHaveAttribute("aria-busy");
    expect(await seriousAxe(section())).toEqual([]);
  });

  it("a lost import reads the unknown line once, politely", async () => {
    await mount({}, (method, url) =>
      method === "POST" && url.endsWith("/admin/recorder/import")
        ? json(202, { job_id: IMPORT_JOB })
        : url.endsWith(`/admin/jobs/${IMPORT_JOB}`)
          ? problem(404, "job_unknown")
          : undefined,
    );
    const said = utterances();
    await fillJanuary();
    await submit();
    const line =
      "The import's status is no longer available on the server. Run it again: finished days are skipped.";
    expect(importCard()).toHaveTextContent(line);
    expect(said()).toEqual(["Import started", line]);
  });

  it("a cancelled import keeps its finished days", async () => {
    await mount({}, importing([{ status: "cancelled" }]));
    await fillJanuary();
    await submit();
    expect(importCard()).toHaveTextContent("Import cancelled. Finished days are kept.");
  });
});

describe("refusals at the point of action (T4; E16-D06 §16.4 rows 9, 16)", CASE, () => {
  it.each([
    [409, "job_running", "An import is already running. (job_running)"],
    [422, "import_range_invalid", "Not started: the server refused it. (import_range_invalid)"],
  ] as const)(
    "%i %s reads under Import archives, said once; it stays enabled",
    async (status, code, text) => {
      await mount({}, (method, url) =>
        method === "POST" && url.endsWith("/admin/recorder/import")
          ? problem(status, code)
          : undefined,
      );
      await fillJanuary();
      await submit();
      expect(importCard()).toHaveTextContent(text);
      expect(shellSaid()).toBe(text);
      expect(section()).not.toHaveTextContent("never rendered");
      expect(importButton()).not.toHaveAttribute("aria-disabled");
      await advance(10 * JOB_POLL_MS); // nothing is re-sent (C-486P3-06)
      expect(writes()).toEqual([JANUARY_WRITE]);
    },
  );

  it("no answer reads the app's words under Import archives; nothing is re-sent (C-486P3-06)", async () => {
    await mount({}, (method, url) => {
      if (method === "POST" && url.endsWith("/admin/recorder/import")) {
        throw new TypeError("Failed to fetch");
      }
      return undefined;
    });
    await fillJanuary();
    await submit();
    expect(importCard()).toHaveTextContent("Cannot reach the server. Try again.");
    expect(importButton()).not.toHaveAttribute("aria-busy");
    await advance(10 * JOB_POLL_MS);
    expect(writes()).toEqual([JANUARY_WRITE]);
  });
});

describe("SCR-142/view-as: Import archives is T2; the form reads on (T2-09)", CASE, () => {
  it("keeps its label with the lock, points at the notice, says its reason once and sends nothing", async () => {
    const { container } = await mount({ viewAs: { user: "alex" } });
    await fillJanuary();
    const button = within(importCard()).getByRole("button", {
      name: "Not available Import archives",
    });
    expect(button).toHaveAttribute("aria-disabled", "true");
    const notice = within(section()).getByText(NOTICE);
    expect(button.getAttribute("aria-describedby")?.split(" ")).toContain(notice.id);
    fireEvent.click(button);
    await flush();
    expect(shellSaid()).toBe("Read-only while viewing as alex.");
    expect(writes()).toEqual([]);
    expect(field("From")).toHaveValue("2026-01-01");
    expect(await seriousAxe(container)).toEqual([]);
  });
});
