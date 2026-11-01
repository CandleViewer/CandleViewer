/**
 * E16-S04, SCR-142's job lines (E16-D04 §6, §8, §14; E16-D06 SR-13, SR-24 to SR-26, §16.4 rows 9, 16, 17; G-08;
 * BQ-4, BQ-11): the strip's started, queued and running words, a compaction's and an import's terminal lines, the
 * import form's range rule (at most 366 days, `22` `importTradeArchive`), its progress in days, and its summary
 * from the served `ArchiveImportResult` (BQ-4: the served names, the skip codes routed to E16-D04's sentences).
 */
import { describe, expect, it } from "vitest";
import type {
  CompactionRunResult,
  RefusalRoute,
} from "../../../../src/features/recorder/recorderApi";
import {
  IMPORT_MAX_DAYS,
  compactOutcome,
  importOutcome,
  importProgress,
  importReason,
  importSummary,
  progressLine,
  rangeDays,
  refusalFor,
  skipReasonText,
  startedLine,
} from "../../../../src/features/recorder/storage/storageJobs";
import { STORAGE_DECK } from "../../../../src/features/recorder/storage/storageCopy";
import type { JobView } from "../../../../src/features/recorder/useJobPoll";
import { importJanuary, importResult } from "../fixtures";
import { COMPACT_JOB, IMPORT_JOB, jobAnswer } from "./storageFixtures";

/** The poll's view (#5309's `useJobPoll`): no lost-job route and no refused poll unless a case sets them. */
const viewOf = (phase: JobView["phase"], pct: number, job: JobView["job"]): JobView => ({
  phase,
  pct,
  job,
  route: null,
  pollRefusal: null,
});
const running = (pct: number, status: "queued" | "running" = "running"): JobView =>
  viewOf("running", pct, jobAnswer(COMPACT_JOB, { status, progress_pct: pct }));
const ended = (patch: Parameters<typeof jobAnswer>[1], phase: JobView["phase"]): JobView =>
  viewOf(phase, 100, jobAnswer(IMPORT_JOB, patch));

describe("the jobs strip's lines (D04 §6 `JOB/strip-running`; G-08)", () => {
  it("test_started_lines_are_the_decks", () => {
    expect([startedLine("compact"), startedLine("import")]).toEqual(
      STORAGE_DECK["storage.job.started"].slice(1),
    );
  });

  it("test_running_line_is_the_verb_and_the_whole_percentage", () => {
    expect(progressLine("compact", running(42))).toBe(STORAGE_DECK["storage.job.running"][1]);
    expect(progressLine("import", running(38.71))).toBe(STORAGE_DECK["storage.job.running"][2]);
    expect(progressLine("compact", running(99.9))).toBe("Compaction running · 99 %");
  });

  it("test_a_queued_job_reads_the_served_status_word", () => {
    expect(progressLine("compact", running(0, "queued"))).toBe("Compaction queued");
    expect(progressLine("import", viewOf("running", 0, null))).toBe("Import queued");
  });
});

describe("a compaction's terminal line (D04 §6 `JOB/outcomes`; E16-D02 §3.2)", () => {
  it.each([
    [
      "succeeded",
      { status: "succeeded", finished_at: "2026-09-14T10:42:00Z" },
      { text: "Compacted at 10:42 UTC", tone: "success", assertive: false },
    ],
    [
      "failed",
      { status: "failed", error: "io_error" },
      {
        text: "Compaction failed (io_error); nothing was deleted.",
        tone: "danger",
        assertive: false,
      },
    ],
    [
      "cancelled",
      { status: "cancelled" },
      { text: "Compaction cancelled; nothing was deleted.", tone: "warning", assertive: false },
    ],
  ] as const)("test_compaction_%s_reads_its_line", (phase, patch, outcome) => {
    expect(compactOutcome(ended(patch, phase), Date.parse("2026-09-14T10:43:00Z"))).toEqual(
      outcome,
    );
  });

  it("test_a_lost_compaction_reads_the_unknown_line_and_a_running_one_none", () => {
    expect(compactOutcome(viewOf("unknown", 42, null), 0)).toEqual({
      text: "Compaction status is no longer available on the server.",
      tone: "warning",
      assertive: false,
    });
    expect(compactOutcome(running(42), 0)).toBeNull();
  });

  it("test_a_success_without_its_finish_time_takes_the_clock", () => {
    expect(
      compactOutcome(
        ended({ status: "succeeded", finished_at: null }, "succeeded"),
        Date.parse("2026-09-14T10:44:30Z"),
      )?.text,
    ).toBe("Compacted at 10:44 UTC");
  });

  describe("C-486P3-05: the served result's partitions left as they were, as counts only", () => {
    const succeeded = (result: CompactionRunResult): JobView =>
      viewOf(
        "succeeded",
        100,
        jobAnswer(COMPACT_JOB, {
          status: "succeeded",
          finished_at: "2026-09-14T10:42:00Z",
          result,
        }),
      );
    const KEYS = ["BTCUSDT/2026-09-01", "ETHUSDT/2026-09-02", "SOLUSDT/2026-09-03"];

    it.each([
      [
        "failed",
        { compacted: 12, skipped: 3, deferred: [], failed: KEYS.slice(0, 2) },
        "Partitions not compacted: 2 failed the row-count check.",
      ],
      [
        "deferred",
        { compacted: 12, skipped: 3, deferred: KEYS.slice(2), failed: [] },
        "Partitions not compacted: 1 in use by a replay.",
      ],
      [
        "both",
        { compacted: 12, skipped: 3, deferred: KEYS.slice(2), failed: KEYS.slice(0, 2) },
        "Partitions not compacted: 2 failed the row-count check, 1 in use by a replay.",
      ],
    ] as const)("test_a_success_with_%s_partitions_adds_their_counts", (_, result, detail) => {
      const outcome = compactOutcome(
        succeeded({ ...result, deferred: [...result.deferred], failed: [...result.failed] }),
        0,
      );
      expect(outcome).toEqual({
        text: "Compacted at 10:42 UTC",
        tone: "success",
        assertive: false,
        detail,
      });
      for (const key of KEYS) expect(outcome?.detail).not.toContain(key);
    });

    it("test_a_clean_success_or_a_result_of_another_shape_adds_nothing", () => {
      const clean = { compacted: 12, skipped: 3, deferred: [], failed: [] };
      expect(compactOutcome(succeeded(clean), 0)).not.toHaveProperty("detail");
      expect(
        compactOutcome(ended({ status: "succeeded", result: null }, "succeeded"), 0),
      ).not.toHaveProperty("detail");
    });
  });
});

describe("the import form's range (D04 §1.3 validity look; `22` `importTradeArchive`)", () => {
  it("test_range_days_are_inclusive", () => {
    expect(rangeDays("2026-01-01", "2026-01-31")).toBe(31);
    expect(rangeDays("2026-01-01", "2026-01-01")).toBe(1);
    expect(rangeDays("2026-01-31", "2026-01-01")).toBe(-29);
  });

  const TODAY = "2027-06-30";

  it("test_a_range_that_is_empty_inverted_or_over_366_days_has_the_reason", () => {
    const reason = STORAGE_DECK["storage.import.range.reason"][0];
    expect(IMPORT_MAX_DAYS).toBe(366);
    expect(importReason("BTCUSDT", { start: null, end: null }, TODAY)).toBe(reason);
    expect(importReason("BTCUSDT", { start: "2026-01-01", end: null }, TODAY)).toBe(reason);
    expect(importReason("BTCUSDT", { start: "2026-01-31", end: "2026-01-01" }, TODAY)).toBe(reason);
    expect(importReason("BTCUSDT", { start: "2026-01-01", end: "2027-01-02" }, TODAY)).toBe(reason);
    expect(
      importReason("BTCUSDT", { start: "2026-01-01", end: "2027-01-01" }, TODAY),
    ).toBeUndefined();
    expect(
      importReason("BTCUSDT", { start: "2026-01-01", end: "2026-01-31" }, TODAY),
    ).toBeUndefined();
  });

  it("test_a_range_ending_after_today_has_its_own_reason_c03", () => {
    // An archive exists for past days only: the end is at most today, UTC, whatever the picker allowed.
    const today = "2026-09-14";
    expect(importReason("BTCUSDT", { start: "2026-09-01", end: "2026-09-15" }, today)).toBe(
      "Choose a range ending on or before 2026-09-14.",
    );
    expect(importReason("BTCUSDT", { start: "2026-09-01", end: today }, today)).toBeUndefined();
    // The deck's rule is first: a range that is also too long reads the deck's reason.
    expect(importReason("BTCUSDT", { start: "2025-01-01", end: "2026-09-15" }, today)).toBe(
      STORAGE_DECK["storage.import.range.reason"][0],
    );
  });

  it("test_no_symbol_has_its_own_reason", () => {
    expect(importReason("", { start: "2026-01-01", end: "2026-01-31" }, TODAY)).toBe(
      "Choose a symbol.",
    );
  });
});

describe("an import's progress and terminal line (D04 §8; SR-24 to SR-26)", () => {
  it("test_progress_counts_the_days_of_the_requested_range", () => {
    expect(importProgress(running(38.71), importJanuary)).toEqual({
      text: "12 of 31 days · 38 %",
      value: 38.71,
    });
    expect(importProgress(running(96.77), importJanuary).text).toBe(
      STORAGE_DECK["storage.import.progress"][2],
    );
    expect(importProgress(viewOf("running", 0, null), importJanuary).text).toBe(
      "0 of 31 days · 0 %",
    );
  });

  it("test_success_names_the_symbol_and_range", () => {
    expect(importOutcome(ended({ status: "succeeded" }, "succeeded"), importJanuary)).toEqual({
      text: STORAGE_DECK["storage.import.finished"][1],
      tone: "success",
      assertive: false,
    });
  });

  it("test_a_failure_is_assertive_with_its_code", () => {
    expect(
      importOutcome(ended({ status: "failed", error: "download_failed" }, "failed"), importJanuary),
    ).toEqual({
      text: STORAGE_DECK["storage.import.failed"][1],
      tone: "danger",
      assertive: true,
    });
  });

  it("test_cancelled_and_lost_imports_read_their_lines", () => {
    expect(importOutcome(ended({ status: "cancelled" }, "cancelled"), importJanuary)).toEqual({
      text: "Import cancelled. Finished days are kept.",
      tone: "warning",
      assertive: false,
    });
    expect(importOutcome(viewOf("unknown", 0, null), importJanuary)).toEqual({
      text: STORAGE_DECK["storage.import.unknown"][0],
      tone: "warning",
      assertive: false,
    });
    expect(importOutcome(running(10), importJanuary)).toBeNull();
  });
});

describe("the import summary from the served result (AC 6; BQ-4; `22` `ArchiveImportResult`)", () => {
  const summary = importSummary(importResult);

  it("test_summary_states_files_processed_rows_written_overlap_and_skips", () => {
    expect(summary.rows).toEqual([
      { label: "Files processed", value: "27 of 30" },
      { label: "Already imported", value: "1" },
      { label: "Rows written", value: "648" },
      { label: "Rows discarded as overlap", value: "264" },
      { label: "Files skipped", value: "2" },
    ]);
  });

  it("test_overlap_is_reported_with_recorded_data_winning", () => {
    expect(summary.overlap).toBe(
      "264 rows inside recorded windows were discarded — recorded data wins.",
    );
  });

  it("test_each_skipped_file_names_its_day_status_and_reason", () => {
    expect(summary.skipped).toEqual([
      {
        file: "BTCUSDT2026-06-07.csv.gz",
        day: "2026-06-07",
        status: "skipped",
        reason: "Checksum did not match; the file was skipped. (import_checksum_failed)",
      },
      {
        file: "BTCUSDT2026-06-09.csv.gz",
        day: "2026-06-09",
        status: "skipped",
        reason: "The file could not be read; it was skipped. (import_parse_failed)",
      },
    ]);
    expect(summary.resume).toBe(STORAGE_DECK["storage.import.resume"][0]);
  });

  it("test_a_download_failure_is_an_error_row_and_an_unknown_code_its_token", () => {
    const other = importSummary({
      ...importResult,
      files_already_imported: 0,
      rows_discarded_overlap: 0,
      files_skipped: [
        { file: "BTCUSDT2026-06-10.csv.gz", reason: "import_download_failed" },
        { file: "archive.bin", reason: "import_file_not_found" },
      ],
    });
    expect(other.rows.map((r) => r.label)).not.toContain("Already imported");
    expect(other.overlap).toBeNull();
    expect(other.skipped).toEqual([
      {
        file: "BTCUSDT2026-06-10.csv.gz",
        day: "2026-06-10",
        status: "error",
        reason:
          "The file could not be downloaded; run the import again to retry it. (import_download_failed)",
      },
      {
        file: "archive.bin",
        day: "archive.bin",
        status: "skipped",
        reason: "import_file_not_found",
      },
    ]);
  });

  it("test_a_clean_import_has_no_skips_and_no_resume_line", () => {
    const clean = importSummary({ ...importResult, files_skipped: [] });
    expect(clean.skipped).toEqual([]);
    expect(clean.resume).toBeNull();
  });

  it.each([
    [
      "import_checksum_failed",
      "Checksum did not match; the file was skipped. (import_checksum_failed)",
    ],
    ["import_file_too_large", "import_file_too_large"],
    ["import_reason_new_to_this_build", "import_reason_new_to_this_build"],
  ])("test_skip_reason_%s", (code, text) => {
    expect(skipReasonText(code)).toBe(text);
  });
});

describe("a refusal at the point of action (E16-D06 §16.4 rows 9, 15, 16; T4)", () => {
  const running409: RefusalRoute = {
    kind: "deck",
    key: "storage.job.refused.running",
    code: "job_running",
    serverTime: null,
  };

  it("test_a_running_slot_names_the_action", () => {
    expect(refusalFor("compact", running409)).toBe(
      "A compaction is already running. (job_running)",
    );
    expect(refusalFor("import", running409)).toBe("An import is already running. (job_running)");
  });

  it("test_any_other_refusal_is_the_generic_t4_with_its_code", () => {
    const route: RefusalRoute = {
      kind: "t4",
      code: "import_range_invalid",
      field: null,
      status: 422,
    };
    expect(refusalFor("import", route)).toBe(
      "Not started: the server refused it. (import_range_invalid)",
    );
    const offline: RefusalRoute = { kind: "t4", code: null, field: null, status: 0 };
    expect(refusalFor("compact", offline)).toBe("Cannot reach the server. Try again.");
  });
});
