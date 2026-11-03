/**
 * E42-S04 (#1135): the signed export on SCR-135 (E42-D04 §8, AL-18 to AL-24; the orchestrator's
 * BQ-7), through the page and the stubbed server: the rung-1 dialog over a window of at most 31
 * days, the `audit` step-up through the shipped gate on both the export and its download, the job
 * line from running to ready, the download saved from its bytes, and a failed job with no file.
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { auditExport } from "../../../../src/features/admin/audit/exportJob";
import { auditIntegrity } from "../../../../src/features/admin/audit/integrity";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import { JOB_ID, T0, entries, exportResult, job, json, problem, stepUpRequired } from "./fixtures";
import { flush, mountAuditPage, pagesOf, sessionAs, type Routes } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const EXPORT = "/api/v1/admin/audit/export";
const STEP_UP = "/api/v1/auth/step-up";
const JOBS = `/api/v1/admin/jobs/${JOB_ID}`;
const FILE = `/api/v1/admin/audit/exports/${JOB_ID}`;

const main = (): ReturnType<typeof within> => within(screen.getByRole("main"));
const signedExport = (): HTMLElement => screen.getByRole("button", { name: /Signed export…$/ });
const dialog = (): HTMLElement => screen.getByRole("alertdialog", { name: "Export the audit log" });
const challenge = (): HTMLElement =>
  screen.getByRole("alertdialog", { name: "Confirm with two-factor" });

/** Opens the dialog and waits out CMP-044's 400 ms guard. */
async function openDialog(): Promise<void> {
  fireEvent.click(signedExport());
  await flush(500);
}
async function confirmExport(): Promise<void> {
  fireEvent.click(within(dialog()).getByRole("button", { name: "Export" }));
  await flush();
}
async function passStepUp(): Promise<void> {
  const gate = within(challenge());
  fireEvent.change(gate.getByLabelText("Password"), { target: { value: "pw-audit-export" } });
  fireEvent.change(gate.getByLabelText("Authenticator code"), { target: { value: "123456" } });
  fireEvent.click(gate.getByRole("button", { name: "Confirm" }));
  await flush();
}

/** The export's server: each path's answers in order, the last repeated. */
function server(answers: {
  readonly start?: readonly Response[];
  readonly polls?: readonly Response[];
  readonly file?: readonly Response[];
}): Routes {
  const n = { start: 0, polls: 0, file: 0 };
  const next = (list: readonly Response[] | undefined, at: number): Response =>
    (list?.[Math.min(at, (list?.length ?? 1) - 1)] ?? json(404, {})).clone();
  return {
    audit: pagesOf(entries(3)),
    other: (sent) => {
      const path = new URL(sent.url, "http://cv.test").pathname;
      if (path === EXPORT) return next(answers.start, n.start++);
      if (path === JOBS) return next(answers.polls, n.polls++);
      if (path === FILE) return next(answers.file, n.file++);
      if (path === STEP_UP) {
        return json(200, { elevated_until: "2026-10-22T14:07:11Z", action_class: "audit" });
      }
      return json(404, { code: "not_found" });
    },
  };
}
const accepted = (): Response => json(202, { job_id: JOB_ID, download_url: null });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  clearAnnouncements();
  auditIntegrity.reset();
  auditExport.reset();
  sessionAs("owner");
});

afterEach(() => {
  auditExport.reset();
  auditIntegrity.reset();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the export dialog (D12, AL-18)", () => {
  it("test_export_dialog_names_the_last_24_hours_compress_on_and_its_marker", async () => {
    const page = await mountAuditPage({ routes: server({}) });
    expect(
      main().getByText(
        "Recorded · needs your confirmation — Audit log exported (admin.audit_export)",
      ),
    ).toBeInTheDocument();
    await openDialog();
    const d = within(dialog());
    expect(d.getByRole("checkbox", { name: "Compress (gzip)" })).toBeChecked();
    expect(
      d.getByText(
        "A signed file (NDJSON and its signature) of every entry from 2026-10-21 14:02 to 2026-10-22 14:02 UTC, with the neighbouring entries that link them — not just the rows on screen. Filters don't apply.",
      ),
    ).toBeInTheDocument();
    expect(d.getByText("The file holds personal data (actor IP addresses).")).toBeInTheDocument();
    expect(d.getByText("You'll confirm with your password and a code.")).toBeInTheDocument();
    // described by its whole body and the marker (D04 §12, A-1135P2-07)
    expect(dialog()).toHaveAccessibleDescription(
      expect.stringContaining("not just the rows on screen. Filters don't apply."),
    );
    expect(dialog()).toHaveAccessibleDescription(
      expect.stringContaining("Audit log exported (admin.audit_export)"),
    );
    expect(document.activeElement).toBe(d.getByRole("button", { name: "Cancel" }));
    expect(page.sent.filter((s) => s.method === "POST")).toEqual([]);
    page.unmount();
  });

  it("test_export_window_over_31_days_is_said_under_to_and_sends_nothing", async () => {
    const page = await mountAuditPage({
      routes: server({}),
      search: "?from=2026-08-01T00:00:00Z&to=2026-10-01T00:00:00Z",
    });
    await openDialog();
    await confirmExport();
    expect(within(dialog()).getByText("Choose at most 31 days.")).toBeInTheDocument();
    expect(page.sent.filter((s) => s.method === "POST")).toEqual([]);
    page.unmount();
  });

  it("test_export_refusal_is_said_in_the_dialog_and_keeps_the_window", async () => {
    const page = await mountAuditPage({
      routes: server({ start: [problem(409, "conflict")] }),
    });
    await openDialog();
    await confirmExport();
    expect(
      within(dialog()).getByText("An export or a signing-key change is already running."),
    ).toBeInTheDocument();
    expect(within(dialog()).getByRole("checkbox", { name: "Compress (gzip)" })).toBeChecked();
    page.unmount();
  });

  it("test_export_view_as_refusal_is_not_sent_in_the_dialog", async () => {
    // no view-as context the client can see: the server's `403 view_as_read_only` is T4 (BQ-9)
    const page = await mountAuditPage({
      routes: server({ start: [problem(403, "view_as_read_only")] }),
    });
    await openDialog();
    await confirmExport();
    expect(within(dialog()).getByText("Not sent — your access changed.")).toBeInTheDocument();
    page.unmount();
  });

  it("test_export_no_answer_offers_check_again_resending_the_same_export", async () => {
    let first = true;
    const routes = server({ start: [accepted()] });
    const page = await mountAuditPage({
      routes: {
        ...routes,
        other: (sent) => {
          if (sent.url === EXPORT && first) {
            first = false;
            return Promise.reject(new TypeError("network"));
          }
          return routes.other?.(sent) ?? json(404, {});
        },
      },
    });
    await openDialog();
    await confirmExport();
    expect(
      within(dialog()).getByText("We couldn't tell whether the export started."),
    ).toBeVisible();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Check again" }));
    await flush();
    const keys = page.sent
      .filter((s) => s.url === EXPORT)
      .map((s) => s.headers.get("Idempotency-Key"));
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    page.unmount();
  });
});

describe("step-up, the job and the download (X1 to X10, AL-19, AL-21 to AL-23)", () => {
  it("test_export_step_up_then_running_then_ready_then_a_step_up_download_saves_the_file", async () => {
    const created = vi.fn(() => "blob:cv-test");
    const revoked = vi.fn();
    const { createObjectURL, revokeObjectURL } = URL;
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked });
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const page = await mountAuditPage({
      routes: server({
        start: [stepUpRequired(), accepted()],
        polls: [
          json(200, { id: JOB_ID, kind: "audit_export", status: "queued" }),
          json(200, job({ progress_pct: 42 })),
          json(200, job({ status: "succeeded", progress_pct: 100, result: exportResult() })),
        ],
        file: [
          stepUpRequired(),
          new Response("{}\n", {
            status: 200,
            headers: {
              "Content-Type": "application/gzip",
              "Content-Disposition": 'attachment; filename="audit-2026-10-22.ndjson.gz"',
            },
          }),
        ],
      }),
    });
    await openDialog();
    await confirmExport();
    expect(challenge()).toBeInTheDocument(); // SCR-006, the `audit` class
    await passStepUp();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(main().getByText("Preparing the export… · job 19000000")).toBeInTheDocument();
    expect(signedExport()).toHaveAttribute("aria-busy", "true");
    expect(signedExport()).not.toHaveAttribute("aria-disabled");
    await flush(2_000);
    expect(main().getByText("Preparing the export… · job 19000000")).toBeInTheDocument();
    await flush(3_000);
    expect(main().getByText("Preparing the export… 42 % · job 19000000")).toBeInTheDocument();
    expect(main().getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
    await flush(4_000);
    expect(
      main().getByText(
        "Export ready — 851,204 entries (the chain span for 2026-08-14 00:00 to 2026-09-14 00:00 UTC), 44.1 MB",
      ),
    ).toBeInTheDocument();
    fireEvent.click(main().getByRole("button", { name: "Download" }));
    await flush();
    await passStepUp();
    expect(created).toHaveBeenCalledTimes(1);
    expect(clicked).toHaveBeenCalledTimes(1);
    const posts = page.sent.filter((s) => s.url === STEP_UP);
    expect(posts).toHaveLength(2); // the export's step-up and the download's
    const starts = page.sent.filter((s) => s.url === EXPORT);
    expect(starts[1]?.headers.get("Idempotency-Key")).toBe(
      starts[0]?.headers.get("Idempotency-Key"),
    );
    clicked.mockRestore();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    page.unmount();
  });

  it("test_export_failed_job_says_why_offers_no_file_and_signed_export_again", async () => {
    const page = await mountAuditPage({
      routes: server({
        start: [accepted()],
        polls: [json(200, job({ status: "failed", error: "export_too_large" }))],
      }),
    });
    await openDialog();
    await confirmExport();
    await flush(2_000);
    expect(
      main().getByText("Too many entries for one file — choose a shorter window."),
    ).toBeInTheDocument();
    expect(main().queryByRole("button", { name: "Download" })).toBeNull();
    expect(signedExport()).not.toHaveAttribute("aria-busy");
    expect(signedExport()).not.toHaveAttribute("aria-disabled");
    page.unmount();
  });

  it("test_export_download_410_replaces_the_ready_line_and_takes_focus", async () => {
    const page = await mountAuditPage({
      routes: server({
        start: [accepted()],
        polls: [json(200, job({ status: "succeeded", result: exportResult() }))],
        file: [problem(410, "gone")],
      }),
    });
    await openDialog();
    await confirmExport();
    await flush(2_000);
    const download = main().getByRole("button", { name: "Download" });
    download.focus();
    fireEvent.click(download);
    await flush();
    const line = main().getByText(
      "The export expired at 2026-09-15 10:39 UTC and its file was deleted.",
    );
    expect(document.activeElement).toBe(line);
    expect(main().queryByRole("button", { name: "Download" })).toBeNull();
    page.unmount();
  });

  it("test_export_download_410_leaves_focus_where_the_user_went_meanwhile", async () => {
    // A-1135P2-15: the replaced line takes focus only from the ready line, never from elsewhere
    const page = await mountAuditPage({
      routes: server({
        start: [accepted()],
        polls: [json(200, job({ status: "succeeded", result: exportResult() }))],
        file: [problem(410, "gone")],
      }),
    });
    await openDialog();
    await confirmExport();
    await flush(2_000);
    const download = main().getByRole("button", { name: "Download" });
    download.focus();
    fireEvent.click(download);
    const subject = screen.getByRole("textbox", { name: "Subject id" });
    subject.focus(); // the user moves on while the request runs
    await flush();
    expect(
      main().getByText("The export expired at 2026-09-15 10:39 UTC and its file was deleted."),
    ).toBeInTheDocument();
    expect(document.activeElement).toBe(subject);
    page.unmount();
  });

  it("test_export_leaving_the_page_closes_an_open_gate_and_keeps_no_old_request", async () => {
    // C-1135P2-19: a later visit opens the dialog over its own window
    const page = await mountAuditPage({ routes: server({ start: [stepUpRequired()] }) });
    await openDialog();
    await confirmExport();
    expect(challenge()).toBeInTheDocument();
    expect(auditExport.getState().phase.kind).toBe("step_up");
    page.unmount();
    expect(auditExport.getState().phase.kind).toBe("idle");
  });
});
