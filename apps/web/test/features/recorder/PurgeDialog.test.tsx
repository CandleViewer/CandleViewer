/**
 * E16-S01 PR 3, Purge data… (E16-D02 §6.5; E16-D04 §1.3, §7; E16-D06 §13 "The purge dialog", KB-07, SD-01 to SD-03,
 * T2-10, §16.4 rows 2, 3 and 9 to 15; frozen rows (ii), (iii) and (viii)) over a stubbed `apiFetch` (no network,
 * C-13.5). The `22` examples' clock: 2026-09-14 10:31:02 UTC.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import type { StorageUsage } from "../../../src/features/recorder/model";
import {
  purgeTargets,
  type PurgeJob,
  type PurgeTarget,
} from "../../../src/features/recorder/purge";
import { PurgeDialog, type PurgeDialogProps } from "../../../src/features/recorder/PurgeDialog";
import { problem, purgeAnchoredBound, purgeJobRunning, stepUpRequired } from "./fixtures";
import { NOW, row } from "./gridFixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const JOB = "19000000-0000-4000-8000-000000000042";
const TARGETS: readonly PurgeTarget[] = [
  {
    symbol: "ADAUSDT",
    pinned: false,
    retentionDays: 30,
    diskBytes: 11e9,
    startedAt: "2026-07-16T10:31:02Z",
  },
  { symbol: "BTCUSDT", pinned: true, retentionDays: null, diskBytes: 34.8e9, startedAt: null },
];
/** ADAUSDT recorded evenly over 60 days from 16 Jul: before 15 Aug is 30 of them, half of 11 GB. */
const COVERAGE = {
  symbol: "ADAUSDT",
  streams: [
    {
      stream: "trades",
      intervals: [
        { from: "2026-07-16T00:00:00Z", to: "2026-09-14T00:00:00Z", rows: 6_000, tier: "parquet" },
      ],
      gaps: [],
    },
  ],
};
const BODY =
  "This deletes about 5.5 GB recorded from 2026-07-16 to 2026-08-15 from QuestDB and Parquet. It cannot be undone, and replay, footprint history and the journal lose this range. Shared QuestDB day partitions are freed by the nightly roll-off.";
const PURGE_STEP_UP = {
  ...stepUpRequired,
  action_class: "recorder_purge",
  action_summary: "Purge ADAUSDT data",
};

const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const writes = () =>
  apiFetch.mock.calls
    .filter(([, init]) => (init?.method ?? "GET") !== "GET")
    .map(([url, init]) => ({
      url,
      body: typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined,
      idemp: new Headers(init?.headers).get("Idempotency-Key"),
    }));
function route(...replies: Response[]): void {
  apiFetch.mockImplementation(async (url, init) => {
    if ((init?.method ?? "GET") === "GET" && url.includes("/market/data-coverage")) {
      return json(200, COVERAGE);
    }
    return replies.shift() ?? json(500, problem(500, "internal_error"));
  });
}
const settle = () => act(async () => void (await Promise.resolve()));
const settleAll = async (): Promise<void> => {
  for (let i = 0; i < 4; i += 1) await settle();
};
const pastGuard = () => act(() => void vi.advanceTimersByTime(500));
const press = (control: HTMLElement): void => {
  act(() => control.focus());
  fireEvent.click(control);
};
const type = (field: HTMLElement, value: string): void =>
  void fireEvent.change(field, { target: { value } });

let started: PurgeJob[] = [];
/** The page closing the dialog by a path of its own (no Cancel): the host is cleared all the same. */
let shut: () => void = () => undefined;
function Host(props: Partial<PurgeDialogProps>): JSX.Element {
  const [open, setOpen] = useState(false);
  shut = () => setOpen(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Purge…
      </button>
      <PurgeDialog
        open={open}
        symbol="ADAUSDT"
        symbols={TARGETS}
        onClose={() => setOpen(false)}
        onStarted={(job) => {
          started.push(job);
          setOpen(false);
        }}
        readBack={() => undefined}
        {...props}
      />
    </>
  );
}
/** A first mount transforms the screen's whole module graph: slow under load, never a flake (C-9.3). */
const CASE = { timeout: 30_000 } as const;
const dialog = (symbol = "ADAUSDT"): HTMLElement =>
  screen.getByRole("dialog", { name: `Purge ${symbol} data?` });
const confirm = (symbol = "ADAUSDT"): HTMLElement =>
  within(dialog(symbol)).getByRole("button", { name: `Purge ${symbol} data` });
const typed = (): HTMLElement =>
  within(dialog()).getByRole("textbox", { name: "Type the symbol to confirm" });
const reason = (): HTMLElement =>
  within(dialog()).getByRole("textbox", { name: "Reason (required, 3–280 characters)" });
async function openAndFill(props: Partial<PurgeDialogProps> = {}): Promise<void> {
  render(<Host {...props} />);
  press(screen.getByRole("button", { name: "Purge…" }));
  await settleAll();
  type(reason(), "  space for the import  ");
  type(typed(), "ADAUSDT");
  pastGuard();
}

const scroll = Element.prototype.scrollIntoView;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "performance"], now: NOW });
  Element.prototype.scrollIntoView = vi.fn();
  started = [];
});
afterEach(() => {
  Element.prototype.scrollIntoView = scroll;
  act(() => clearAnnouncements());
  apiFetch.mockReset();
  vi.useRealTimers();
});

describe("Feature: The purge dialog (E16-D06 §13; KB-07, SD-01 to SD-03)", CASE, () => {
  it("is read by role with its title and its consequence, focus on Cancel, the typed field empty (frozen (ii), (viii))", async () => {
    route();
    render(<Host />);
    press(screen.getByRole("button", { name: "Purge…" }));
    await settleAll();
    expect(dialog()).toHaveAccessibleDescription(BODY);
    expect(within(dialog()).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(
      within(dialog()).getByRole("button", { name: "Close Purge ADAUSDT data?" }),
    ).toBeInTheDocument();
    expect(typed()).toHaveValue("");
    expect(within(dialog()).getByRole("combobox", { name: "Symbol" })).toHaveTextContent("ADAUSDT");
    const before = within(dialog()).getByRole("textbox", { name: "Delete data recorded before" });
    expect(before).toHaveValue("2026-08-15");
    expect(before).toHaveAccessibleDescription(
      expect.stringContaining("Data recorded at or after this time is kept."),
    );
    expect(dialog()).toHaveTextContent("You'll confirm with your password and a code.");
    expect(dialog()).toHaveTextContent("This action is audited (high severity).");
    expect(within(dialog()).queryByRole("checkbox")).toBeNull(); // Include pinned: a pinned symbol's only
  });

  it("Confirm keeps the validity look, one reason in order: the typed symbol, the bound, then the reason", async () => {
    route();
    render(<Host />);
    press(screen.getByRole("button", { name: "Purge…" }));
    await settleAll();
    const purge = confirm();
    expect(purge).toBeEnabled();
    expect(purge).toHaveAttribute("aria-disabled", "true");
    expect(purge).toHaveAccessibleDescription("Type ADAUSDT exactly to confirm.");
    type(typed(), "adausdt");
    expect(purge).toHaveAccessibleDescription("Type ADAUSDT exactly to confirm.");
    type(typed(), "ADAUSDT");
    const before = within(dialog()).getByRole("textbox", { name: "Delete data recorded before" });
    type(before, "2026-12-01");
    fireEvent.blur(before);
    expect(purge).toHaveAccessibleDescription("Choose a time no later than now.");
    type(before, "2026-09-01");
    fireEvent.blur(before);
    expect(purge).toHaveAccessibleDescription("Give a reason of at least 3 characters.");
    type(reason(), "ok");
    expect(purge).toHaveAttribute("aria-disabled", "true");
    type(reason(), "space for the import");
    expect(purge).not.toHaveAttribute("aria-disabled");
    // Enter in the reason field and the typed field confirms nothing.
    expect(fireEvent.keyDown(reason(), { key: "Enter" })).toBe(false);
    expect(fireEvent.keyDown(typed(), { key: "Enter" })).toBe(false);
    expect(writes()).toEqual([]);
  });

  it("sends the purge once: the trimmed reason, the bound with its offset, its key; the 202 hands the job over", async () => {
    route(json(202, { job_id: JOB }));
    await openAndFill();
    press(confirm());
    await settleAll();
    expect(writes()).toEqual([
      {
        url: "/api/v1/admin/recorder/purge",
        body: {
          symbol: "ADAUSDT",
          confirm_symbol: "ADAUSDT",
          reason: "space for the import",
          before: "2026-08-15T00:00:00Z",
          include_pinned: false,
        },
        idemp: expect.any(String),
      },
    ]);
    expect(started).toEqual([
      { jobId: JOB, symbol: "ADAUSDT", beforeMs: Date.parse("2026-08-15T00:00:00Z") },
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Purge…" })).toHaveFocus();
  });

  it("a pinned symbol offers Include pinned: ticked, it says so and is sent", async () => {
    route(json(202, { job_id: JOB }));
    render(<Host symbol="BTCUSDT" />);
    press(screen.getByRole("button", { name: "Purge…" }));
    await settleAll();
    const box = within(dialog("BTCUSDT")).getByRole("checkbox", { name: "Include pinned data" });
    expect(dialog("BTCUSDT")).not.toHaveTextContent("Pinned data is deleted too.");
    fireEvent.click(box);
    expect(dialog("BTCUSDT")).toHaveTextContent("Pinned data is deleted too.");
    type(
      within(dialog("BTCUSDT")).getByRole("textbox", {
        name: "Reason (required, 3–280 characters)",
      }),
      "space",
    );
    type(
      within(dialog("BTCUSDT")).getByRole("textbox", { name: "Type the symbol to confirm" }),
      "BTCUSDT",
    );
    pastGuard();
    press(confirm("BTCUSDT"));
    await settleAll();
    expect(writes()[0]?.body).toMatchObject({ symbol: "BTCUSDT", include_pinned: true });
  });

  it("another symbol retitles the dialog and moves the typed token", async () => {
    route();
    render(<Host />);
    press(screen.getByRole("button", { name: "Purge…" }));
    await settleAll();
    type(typed(), "ADAUSDT");
    fireEvent.click(within(dialog()).getByRole("combobox", { name: "Symbol" }));
    fireEvent.click(screen.getByRole("option", { name: "BTCUSDT" }));
    expect(confirm("BTCUSDT")).toHaveAccessibleDescription("Type BTCUSDT exactly to confirm.");
  });

  it("has no serious axe violation, open", { timeout: 20_000 }, async () => {
    route();
    render(<Host />);
    press(screen.getByRole("button", { name: "Purge…" }));
    await settleAll();
    vi.useRealTimers();
    const res = await axe.run(dialog(), { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

describe("refusals at the confirm (E16-D06 §16.4; D04 §7)", CASE, () => {
  it.each([
    [
      "a 409 job_running: §6.5's sentence",
      json(409, purgeJobRunning),
      "A purge is running. (job_running)",
    ],
    [
      "a 422 before_in_future: the server's time, re-written",
      json(
        422,
        problem(422, "validation_failed", {
          errors: [
            { field: "before", rule: "before_in_future", message: "now is 2026-09-14T10:31:03Z" },
          ],
        }),
      ),
      "Not started: the time is later than the server's (2026-09-14 10:31:03 UTC). Choose a time at or before it. (validation_failed)",
    ],
    [
      "a 422 retention_pinned_refused",
      json(422, problem(422, "retention_pinned_refused")),
      "Pinned data is excluded. Tick Include pinned to delete it too. (retention_pinned_refused)",
    ],
    [
      "a 503 audit_unavailable",
      json(503, problem(503, "audit_unavailable")),
      "Not started: the audit record could not be written. (audit_unavailable)",
    ],
    [
      "a 409 idempotency_key_reuse: the generic T4, the anchored bound never shown",
      json(409, purgeAnchoredBound),
      "Not started: the server refused it. (idempotency_key_reuse)",
    ],
  ])("%s", async (_, answer, words) => {
    route(answer);
    await openAndFill();
    press(confirm());
    await settleAll();
    expect(dialog()).toHaveTextContent(words);
    expect(dialog()).not.toHaveTextContent("anchored before");
    expect(dialog()).not.toHaveTextContent("server detail");
    expect(reason()).toHaveValue("  space for the import  ");
    expect(typed()).toHaveValue("ADAUSDT");
    expect(confirm()).not.toHaveAttribute("aria-busy");
    expect(started).toEqual([]);
  });
});

describe("the recorder_purge step-up (E16-D02 §6.4, §6.5; frozen row (iii))", CASE, () => {
  it("Esc leaves Not sent, the inputs kept; a grant re-sends the held purge once with its key and body", async () => {
    route(
      json(403, PURGE_STEP_UP),
      json(403, PURGE_STEP_UP),
      json(200, { action_class: "recorder_purge" }),
      json(202, { job_id: JOB }),
    );
    await openAndFill();
    press(confirm());
    await settleAll();
    let challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.keyDown(within(challenge).getByLabelText("Password"), { key: "Escape" });
    expect(dialog()).toHaveTextContent("Not sent");
    expect(typed()).toHaveValue("ADAUSDT");
    expect(confirm()).toHaveFocus();
    pastGuard();
    press(confirm());
    await settleAll();
    challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.change(within(challenge).getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(within(challenge).getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(within(challenge).getByRole("button", { name: "Confirm" }));
    await settleAll();
    const purges = writes().filter((w) => w.url === "/api/v1/admin/recorder/purge");
    expect(purges).toHaveLength(3);
    expect(purges[2]?.idemp).toBe(purges[1]?.idemp);
    expect(purges[2]?.body).toEqual(purges[1]?.body);
    expect(started).toEqual([expect.objectContaining({ jobId: JOB })]);
  });
});

describe(
  "on the wire and at the edges (S-5347-03 to -05; S-5353-01; C-5347-03, C-5347-08; A-5347-08)",
  CASE,
  () => {
    /** Coverage reads answered; each purge POST held until the test releases it. */
    function holdPurge(): (response: Response) => void {
      let release: (response: Response) => void = () => undefined;
      apiFetch.mockImplementation(async (url, init) => {
        if ((init?.method ?? "GET") === "GET") return json(200, COVERAGE);
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      });
      return (response) => release(response);
    }
    const purges = () => writes().filter((w) => w.url === "/api/v1/admin/recorder/purge");
    const polite = (): HTMLElement =>
      document.querySelector(
        '[data-cv-inert-exempt][aria-live="polite"]:not([role])',
      ) as HTMLElement;

    it("while its purge is on the wire the inputs are locked, and Esc, Cancel and its close button keep the dialog", async () => {
      const release = holdPurge();
      render(<Host symbol="BTCUSDT" />);
      press(screen.getByRole("button", { name: "Purge…" }));
      await settleAll();
      const box = dialog("BTCUSDT");
      type(
        within(box).getByRole("textbox", { name: "Reason (required, 3–280 characters)" }),
        "space",
      );
      type(within(box).getByRole("textbox", { name: "Type the symbol to confirm" }), "BTCUSDT");
      pastGuard();
      press(confirm("BTCUSDT"));
      await settleAll();
      expect(within(box).getByRole("combobox", { name: "Symbol" })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
      expect(
        within(box).getByRole("textbox", { name: "Delete data recorded before" }),
      ).toHaveAttribute("readonly");
      expect(
        within(box).getByRole("textbox", { name: "Reason (required, 3–280 characters)" }),
      ).toHaveAttribute("readonly");
      expect(within(box).getByRole("checkbox", { name: "Include pinned data" })).toBeDisabled();
      fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
      press(within(box).getByRole("button", { name: "Cancel" }));
      press(within(box).getByRole("button", { name: "Close Purge BTCUSDT data?" }));
      expect(dialog("BTCUSDT")).toBeInTheDocument();
      release(json(202, { job_id: JOB }));
      await settleAll();
      expect(started).toEqual([expect.objectContaining({ jobId: JOB, symbol: "BTCUSDT" })]);
    });

    it("closed by the page while its purge is on the wire, the challenge is dropped: Not sent once, no SCR-006 later", async () => {
      const release = holdPurge();
      render(
        <>
          <Host />
          <ShellAnnouncer />
        </>,
      );
      press(screen.getByRole("button", { name: "Purge…" }));
      await settleAll();
      type(reason(), "space for the import");
      type(typed(), "ADAUSDT");
      pastGuard();
      press(confirm());
      await settleAll();
      act(() => shut());
      release(json(403, PURGE_STEP_UP));
      await settleAll();
      expect(screen.queryByRole("alertdialog", { name: "Confirm with two-factor" })).toBeNull();
      expect(polite()).toHaveTextContent("Not sent");
      press(screen.getByRole("button", { name: "Purge…" }));
      await settleAll();
      expect(dialog()).toBeInTheDocument();
      expect(screen.queryByRole("alertdialog", { name: "Confirm with two-factor" })).toBeNull();
      expect(purges()).toHaveLength(1);
      expect(started).toEqual([]);
    });

    it("a re-send that gets no answer: Outcome pending points at the Recording budget, which is read again", async () => {
      const readBack = vi.fn();
      let sent = 0;
      apiFetch.mockImplementation(async (url, init) => {
        if ((init?.method ?? "GET") === "GET") return json(200, COVERAGE);
        if (url.endsWith("/auth/step-up")) return json(200, { action_class: "recorder_purge" });
        sent += 1;
        if (sent === 1) return json(403, PURGE_STEP_UP);
        throw new TypeError("Failed to fetch"); // the held purge's re-send: no answer
      });
      await openAndFill({ readBack });
      press(confirm());
      await settleAll();
      const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
      fireEvent.change(within(challenge).getByLabelText("Password"), { target: { value: "pw" } });
      fireEvent.change(within(challenge).getByLabelText("Authenticator code"), {
        target: { value: "123456" },
      });
      fireEvent.click(within(challenge).getByRole("button", { name: "Confirm" }));
      await settleAll();
      expect(dialog()).toHaveTextContent("Outcome pending, see Recording budget");
      expect(readBack).toHaveBeenCalledTimes(1);
    });

    it("a 2xx with no job id is the T4 at the confirm, never a silent close", async () => {
      route(json(202, {}));
      await openAndFill();
      press(confirm());
      await settleAll();
      expect(dialog()).toHaveTextContent("Not started: the server refused it.");
      expect(started).toEqual([]);
      expect(reason()).toHaveValue("  space for the import  ");
      expect(confirm()).not.toHaveAttribute("aria-busy");
    });

    it("the reason counts characters as the server does: an emoji is one", async () => {
      route();
      render(<Host />);
      press(screen.getByRole("button", { name: "Purge…" }));
      await settleAll();
      type(typed(), "ADAUSDT");
      type(reason(), "😀a");
      expect(confirm()).toHaveAccessibleDescription("Give a reason of at least 3 characters.");
      type(reason(), "😀ab");
      expect(confirm()).not.toHaveAttribute("aria-disabled");
    });

    it("a date that does not parse, committed, marks the field invalid with its own words; Confirm still waits", async () => {
      route();
      render(<Host />);
      press(screen.getByRole("button", { name: "Purge…" }));
      await settleAll();
      type(typed(), "ADAUSDT");
      type(reason(), "space for the import");
      const before = within(dialog()).getByRole("textbox", { name: "Delete data recorded before" });
      type(before, "not-a-date");
      fireEvent.blur(before);
      expect(before).toHaveAttribute("aria-invalid", "true");
      expect(before).toHaveAccessibleDescription(expect.stringContaining("Enter a date as"));
    });

    it("the symbols it offers carry the page's live size, the storage report's only for what no row has", () => {
      const rows = [
        row("ETHUSDT", { diskBytes: 2.0e9 }),
        row("XRPUSDT", { diskBytes: null }),
        row("DOGEUSDT", { id: null, state: "refused", diskBytes: null }),
      ];
      const storage = {
        symbols: [
          { symbol: "ETHUSDT", used_bytes: 15.6e9 },
          { symbol: "XRPUSDT", used_bytes: 6.9e6 },
          { symbol: "ADAUSDT", used_bytes: 11.0e9, pinned: false },
        ],
      } as unknown as StorageUsage;
      expect(purgeTargets(rows, storage).map((t) => [t.symbol, t.diskBytes])).toEqual([
        ["ETHUSDT", 2.0e9],
        ["XRPUSDT", 6.9e6],
        ["ADAUSDT", 11.0e9],
      ]);
    });
  },
);
