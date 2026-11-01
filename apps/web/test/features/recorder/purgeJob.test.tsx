/**
 * E16-S01 PR 3, a purge on SCR-140's page (E16-D02 §3, §3.2, §6.5, §6.7; E16-D06 §13 "The purge dialog", RG-11,
 * SR-09 to SR-12, BG-02, BG-05; F-08; G-02; §16.4 row 10; #5309's lens D-5309-11): the entry points, the job on
 * PR 2's 2 s poll, the banner's line and bar, the card's line while level 3 holds the slot, the busy controls and
 * the poll's teardown. Every line is said once through the shell's announcer, whose regions stay live under the
 * row detail's modal drawer (A-5347-04): the running line and the polite outcomes politely, a failure assertively;
 * the page's own callouts say nothing. A stubbed `apiFetch`, a fake socket, fake timers; no network (C-13.5).
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import type { RecorderFrame } from "../../../src/features/recorder/model";
import { RecorderScreen } from "../../../src/features/recorder/RecorderScreen";
import { problem, stepUpRequired } from "./fixtures";
import { NOW } from "./gridFixtures";
import { STORAGE, fakeSocket, frameOf, router } from "./screenFixtures";

const JOB = "19000000-0000-4000-8000-000000000042";
const JOB2 = "19000000-0000-4000-8000-000000000043";
const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
const job = (patch: Record<string, unknown>) => ({
  id: JOB,
  kind: "retention_purge",
  status: "running",
  progress_pct: 0,
  started_at: "2026-09-14T10:31:05Z",
  finished_at: null,
  result: null,
  error: null,
  ...patch,
});
const RUNNING =
  "Purging ADAUSDT data recorded before 2026-08-15. Recording continues. Deleted data cannot be restored.";
const FAILED =
  "Purge of ADAUSDT failed (io_error). Some data may already be deleted: check ADAUSDT's size and gaps.";
const LEVEL_3 = {
  level: 3,
  write_gate: "closed",
  write_gate_reason: "disk_halt",
  used_bytes: 190.4e9,
} as const;

let clock = { now: NOW };
/** Each job's poll answers, in order; a job with none left answers running at 50 %. */
let polls: Record<string, Response[]> = {};
/** The job ids the purge POSTs answer with, in order. */
let accepted: string[] = [];
let purgeReplies: ((url: string) => Response | Promise<Response>)[] = [];
/** Symbols the storage report lists beyond the page's (data kept after its row left). */
let storageExtra: NonNullable<typeof STORAGE.symbols> = [];
const jobReads = (id = JOB): number =>
  apiFetch.mock.calls.filter(([url]) => url.includes(`/admin/jobs/${id}`)).length;
const storageReads = (): number =>
  apiFetch.mock.calls.filter(([url]) => url.endsWith("/recording/storage")).length;

async function mountPage(frame: RecorderFrame = frameOf()) {
  apiFetch.mockImplementation(
    router((method, url) => {
      if (method === "POST" && url.endsWith("/auth/step-up")) {
        return json(200, { action_class: "recorder_purge" });
      }
      if (method === "GET" && url.endsWith("/recording/storage") && storageExtra.length > 0) {
        return json(200, { ...STORAGE, symbols: [...(STORAGE.symbols ?? []), ...storageExtra] });
      }
      if (method === "POST" && url.endsWith("/admin/recorder/purge")) {
        const reply = purgeReplies.shift();
        if (reply !== undefined) return reply(url) as Response;
        return json(202, { job_id: accepted.shift() ?? JOB });
      }
      const at = url.indexOf("/admin/jobs/");
      if (at >= 0) {
        const id = url.slice(at + "/admin/jobs/".length);
        return polls[id]?.shift() ?? json(200, job({ progress_pct: 50 }));
      }
      return undefined;
    }),
  );
  const socket = fakeSocket(clock);
  const view = render(
    <>
      <RecorderScreen data={socket.options} instruments={["SOLUSDT"]} />
      <ShellAnnouncer />
    </>,
  );
  await flush();
  socket.push(frame);
  act(() => socket.step(0));
  await flush();
  return { ...view, socket };
}

/** What the shell's two regions say from now on, each message once as it lands. */
function listen(): { readonly polite: string[]; readonly assertive: string[] } {
  const said = { polite: [] as string[], assertive: [] as string[] };
  for (const politeness of ["polite", "assertive"] as const) {
    const region = document.querySelector(
      `[data-cv-inert-exempt][aria-live="${politeness}"]:not([role])`,
    ) as HTMLElement;
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) said[politeness].push(node.textContent ?? "");
      }
    }).observe(region, { childList: true });
  }
  return said;
}
/** The purge's own lines among what was said ("Purging", "Purged", "Purge of", "The purge's"). */
const about = (words: readonly string[], symbol = "ADAUSDT"): string[] =>
  words.filter((text) => text.includes(symbol) && /urg/i.test(text));

/** Fills and confirms the open purge dialog for `symbol`. */
async function confirmPurge(symbol: string): Promise<void> {
  const dialog = screen.getByRole("dialog", { name: `Purge ${symbol} data?` });
  fireEvent.change(
    within(dialog).getByRole("textbox", { name: "Reason (required, 3–280 characters)" }),
    { target: { value: "space for the import" } },
  );
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Type the symbol to confirm" }), {
    target: { value: symbol },
  });
  await advance(500);
  const confirm = within(dialog).getByRole("button", { name: `Purge ${symbol} data` });
  act(() => confirm.focus());
  fireEvent.click(confirm);
  await flush();
  await flush();
}

/** ADAUSDT's Purge… from its row detail, the dialog filled and confirmed; the detail closed again unless kept. */
async function purgeAda({ running = true, keepDrawer = false } = {}): Promise<HTMLElement> {
  const symbol = screen.getByRole("button", { name: "ADAUSDT" });
  act(() => symbol.focus());
  fireEvent.click(symbol);
  const detail = screen.getByRole("dialog", { name: "ADAUSDT recording" });
  const open = within(detail).getByRole("button", { name: "Purge…" });
  act(() => open.focus());
  fireEvent.click(open);
  await flush();
  await confirmPurge("ADAUSDT");
  expect(screen.queryByRole("dialog", { name: "Purge ADAUSDT data?" })).toBeNull();
  // Focus is back on the opener, busy while the job runs (FM-04: "Purge data…, now busy").
  expect(open).toHaveFocus();
  if (running) expect(open).toHaveAttribute("aria-busy", "true");
  if (!keepDrawer) {
    fireEvent.keyDown(open, { key: "Escape" });
    await flush();
  }
  return detail;
}

/** The page's own assertive region (PR 2's RG-11 node): always in the DOM, and empty here. */
const pageAlert = (): string =>
  [...document.querySelectorAll('[role="alert"]')].map((n) => n.textContent ?? "").join("");

const scroll = Element.prototype.scrollIntoView;
beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: NOW,
  });
  clock = { now: NOW };
  polls = {};
  accepted = [];
  purgeReplies = [];
  storageExtra = [];
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  Element.prototype.scrollIntoView = scroll;
  act(() => clearAnnouncements());
  apiFetch.mockReset();
  vi.useRealTimers();
});

const CASE = { timeout: 30_000 } as const;

describe("a purge on the page (E16-D02 §3, §3.2, §6.5)", CASE, () => {
  it("the card's Purge data… opens the dialog on the first symbol", async () => {
    await mountPage();
    fireEvent.click(screen.getByRole("button", { name: "Purge data…" }));
    await flush();
    expect(screen.getByRole("dialog", { name: "Purge BTCUSDT data?" })).toBeInTheDocument();
  });

  it("running: the banner's line and its bar named for the purge; the line said once, its percentage never", async () => {
    polls = { [JOB]: [json(200, job({ progress_pct: 42 })), json(200, job({ progress_pct: 43 }))] };
    await mountPage();
    const said = listen();
    await purgeAda();
    expect(
      screen.getByText(/^Purging ADAUSDT data recorded before 2026-08-15: 42 %\./),
    ).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Purge of ADAUSDT" })).toHaveAttribute(
      "aria-valuenow",
      "42",
    );
    expect(about(said.polite)).toEqual([RUNNING]);
    expect(said.assertive).toEqual([]);
    expect(pageAlert()).toBe("");
    const card = screen.getByRole("button", { name: "Purge data…" });
    expect(card).toHaveAttribute("aria-busy", "true");
    fireEvent.click(card); // busy: a press opens nothing
    expect(screen.queryByRole("dialog")).toBeNull();
    await advance(2_000);
    expect(screen.getByRole("progressbar", { name: "Purge of ADAUSDT" })).toHaveAttribute(
      "aria-valuenow",
      "43",
    );
    expect(about(said.polite)).toEqual([RUNNING]);
  });

  it("succeeded: the card states what was freed, said once (F-08); the banner goes and nothing is busy", async () => {
    polls = {
      [JOB]: [
        json(200, job({ progress_pct: 42 })),
        json(
          200,
          job({
            status: "succeeded",
            progress_pct: 100,
            result: { deleted: 12, freed_bytes: 5.5e9 },
          }),
        ),
      ],
    };
    await mountPage();
    const said = listen();
    await purgeAda();
    const storage = storageReads();
    await advance(2_000);
    // The end changes the disk figures: the storage report is read again, once (C-5347-03).
    expect(storageReads()).toBe(storage + 1);
    expect(screen.queryByRole("progressbar", { name: "Purge of ADAUSDT" })).toBeNull();
    const card = screen
      .getByRole("heading", { level: 2, name: /^Growing/ })
      .closest('[data-cmp="CMP-050"]');
    expect(card).toHaveTextContent("Purged 5.5 GB of ADAUSDT data");
    expect(about(said.polite)).toEqual([RUNNING, "Purged 5.5 GB of ADAUSDT data"]);
    expect(screen.getByRole("button", { name: "Purge data…" })).not.toHaveAttribute("aria-busy");
    const reads = jobReads();
    await advance(10_000);
    expect(jobReads()).toBe(reads); // a terminal state ends the poll
  });

  it("failed: CMP-028 danger with no live role of its own, said once and assertively; Open ADAUSDT opens its detail", async () => {
    polls = { [JOB]: [json(200, job({ status: "failed", error: "io_error" }))] };
    await mountPage();
    const said = listen();
    await purgeAda({ running: false });
    // CMP-028 sets the sentence's first full stop as its title, the rest as its body.
    const callout = screen
      .getByText("Purge of ADAUSDT failed (io_error).")
      .closest('[data-cmp="CMP-028"]') as HTMLElement;
    expect(callout).toHaveTextContent(
      "Some data may already be deleted: check ADAUSDT's size and gaps.",
    );
    expect(callout.querySelector("[role], [aria-live]")).toBeNull();
    expect(said.assertive).toEqual([FAILED]);
    expect(about(said.polite)).toEqual([RUNNING]); // the start, then the failure: never politely
    fireEvent.click(screen.getByRole("button", { name: "Open ADAUSDT" }));
    expect(screen.getByRole("dialog", { name: "ADAUSDT recording" })).toBeInTheDocument();
  });

  it("a lost job (404 job_unknown): the unknown line, polite, once", async () => {
    polls = {
      [JOB]: [
        json(404, {
          code: "not_found",
          status: 404,
          title: "Not found",
          errors: [{ rule: "job_unknown" }],
        }),
      ],
    };
    await mountPage();
    const said = listen();
    await purgeAda({ running: false });
    const line =
      "The purge's status is no longer available on the server. Check ADAUSDT's size and gaps.";
    const banner = document.querySelector('[data-cmp="CMP-028"][data-tone="info"]') as HTMLElement;
    expect(banner).toHaveTextContent("The purge's status is no longer available on the server.");
    expect(banner).toHaveTextContent("Check ADAUSDT's size and gaps.");
    expect(about(said.polite)).toEqual([RUNNING, line]);
    expect(said.assertive).toEqual([]);
    expect(pageAlert()).toBe("");
  });

  it("cancelled: the info line, polite, once (C-5347-d06)", async () => {
    polls = { [JOB]: [json(200, job({ status: "cancelled" }))] };
    await mountPage();
    const said = listen();
    await purgeAda({ running: false });
    const line = "Purge of ADAUSDT was cancelled. Data deleted before the cancel is gone.";
    const banner = document.querySelector('[data-cmp="CMP-028"][data-tone="info"]') as HTMLElement;
    expect(banner).toHaveTextContent("Purge of ADAUSDT was cancelled.");
    expect(banner).toHaveTextContent("Data deleted before the cancel is gone.");
    expect(about(said.polite)).toEqual([RUNNING, line]);
    expect(said.assertive).toEqual([]);
  });

  it("failed for a symbol the page has no row for: no Open {symbol}, which would open nothing (C-5347-d04)", async () => {
    storageExtra = [{ symbol: "DOGEUSDT", used_bytes: 2e9, daily_growth_bytes: 0, pinned: false }];
    polls = { [JOB]: [json(200, job({ status: "failed", error: "io_error" }))] };
    await mountPage();
    fireEvent.click(screen.getByRole("button", { name: "Purge data…" }));
    await flush();
    const first = screen.getByRole("dialog", { name: "Purge BTCUSDT data?" });
    fireEvent.click(within(first).getByRole("combobox", { name: "Symbol" }));
    fireEvent.click(screen.getByRole("option", { name: "DOGEUSDT" }));
    await flush();
    await confirmPurge("DOGEUSDT");
    await flush();
    expect(screen.getByText("Purge of DOGEUSDT failed (io_error).")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open DOGEUSDT" })).toBeNull();
  });

  it("a failure whose error is no code token reads failed, never the server's words (C-5347-d08)", async () => {
    polls = {
      [JOB]: [json(200, job({ status: "failed", error: "Disk on fire: /var/lib/questdb" }))],
    };
    await mountPage();
    const said = listen();
    await purgeAda({ running: false });
    expect(screen.getByText("Purge of ADAUSDT failed (failed).")).toBeInTheDocument();
    expect(said.assertive).toEqual([FAILED.replace("(io_error)", "(failed)")]);
    expect(document.body).not.toHaveTextContent("Disk on fire");
  });

  it("level 3 holds the slot: the purge's line and bar in the card; the banner's Purge data… busy", async () => {
    polls = { [JOB]: [json(200, job({ progress_pct: 42 }))] };
    await mountPage(frameOf({}, LEVEL_3));
    await purgeAda();
    const banner = document.querySelector(
      '[data-cmp="CMP-028"][data-tone="danger"]',
    ) as HTMLElement;
    expect(banner).toHaveTextContent("Recording stopped");
    expect(within(banner).getByRole("button", { name: "Purge data…" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    const card = screen
      .getByRole("heading", { level: 2, name: /^Recording stopped/ })
      .closest('[data-cmp="CMP-050"]');
    expect(card).toHaveTextContent("Purging ADAUSDT data recorded before 2026-08-15: 42 %.");
    expect(
      within(card as HTMLElement).getByRole("progressbar", { name: "Purge of ADAUSDT" }),
    ).toBeInTheDocument();
  });

  it("an unmount mid-purge stops the poll (teardown)", async () => {
    polls = { [JOB]: [json(200, job({ progress_pct: 42 }))] };
    const page = await mountPage();
    await purgeAda();
    const reads = jobReads();
    page.unmount();
    await advance(20_000);
    expect(jobReads()).toBe(reads);
  });
});

describe("what a purge says, and where (A-5347-04; C-5347-01 to -05; S-5347-03)", CASE, () => {
  it("ended with the row detail open, its line is heard from the shell's region under the modal, once", async () => {
    polls = {
      [JOB]: [
        json(200, job({ status: "succeeded", progress_pct: 100, result: { freed_bytes: 5.5e9 } })),
      ],
    };
    await mountPage();
    const said = listen();
    const detail = await purgeAda({ running: false, keepDrawer: true });
    expect(detail).toBeInTheDocument();
    expect(about(said.polite)).toEqual([RUNNING, "Purged 5.5 GB of ADAUSDT data"]);
    const region = document.querySelector('[data-cv-inert-exempt][aria-live="polite"]:not([role])');
    expect(region?.closest("[inert]")).toBeNull();
    // Only the shell's regions carry the purge's words: none of the page's own live regions does.
    const live = [...document.querySelectorAll('[aria-live], [role="status"], [role="alert"]')];
    expect(
      live.filter(
        (n) =>
          n.closest("[data-cv-inert-exempt]:not([role])") === null &&
          /urg/i.test(n.textContent ?? ""),
      ),
    ).toEqual([]);
  });

  it("a failure at level 3 is said once, whichever slot it is drawn in as level 3 ends (BG-05)", async () => {
    polls = { [JOB]: [json(200, job({ status: "failed", error: "io_error" }))] };
    const { socket } = await mountPage(frameOf({}, LEVEL_3));
    const said = listen();
    await purgeAda({ running: false });
    const card = screen
      .getByRole("heading", { level: 2, name: /^Recording stopped/ })
      .closest('[data-cmp="CMP-050"]');
    expect(card).toHaveTextContent("Purge of ADAUSDT failed (io_error).");
    socket.push(frameOf());
    act(() => socket.step(1_000));
    await flush();
    expect(document.querySelector('[data-cmp="CMP-028"][data-tone="danger"]')).toHaveTextContent(
      "Purge of ADAUSDT failed (io_error).",
    );
    // Its words wait out the level-3 alert's 5 s in the shell's region, then are said once (A-5347-d05).
    await advance(5_000);
    expect(said.assertive).toEqual([FAILED]);
  });

  it("a poll the server refuses: the T4 with its code under the running line, said once; the poll goes on", async () => {
    polls = {
      [JOB]: [
        json(503, problem(503, "audit_unavailable")),
        json(503, problem(503, "audit_unavailable")),
        json(200, job({ progress_pct: 60 })),
      ],
    };
    await mountPage();
    const said = listen();
    await purgeAda();
    const T4 = "Status not updated: the server refused it. (audit_unavailable)";
    /** The T4 drawn under the line (the shell's region holds the spoken copy). */
    const drawn = (): HTMLElement[] =>
      screen.queryAllByText(T4).filter((node) => node.closest("[data-cv-inert-exempt]") === null);
    expect(
      screen.getByText(/^Purging ADAUSDT data recorded before 2026-08-15: 0 %\./),
    ).toBeVisible();
    expect(drawn()).toHaveLength(1);
    await advance(2_000);
    expect(said.polite.filter((text) => text === T4)).toEqual([T4]);
    await advance(2_000);
    expect(drawn()).toEqual([]);
    expect(screen.getByRole("progressbar", { name: "Purge of ADAUSDT" })).toHaveAttribute(
      "aria-valuenow",
      "60",
    );
  });

  it("a second purge is its own from its first frame: never the last job's outcome", async () => {
    accepted = [JOB, JOB2];
    polls = {
      [JOB]: [
        json(200, job({ status: "succeeded", progress_pct: 100, result: { freed_bytes: 5.5e9 } })),
      ],
      [JOB2]: [json(200, job({ id: JOB2, progress_pct: 10 }))],
    };
    await mountPage();
    await purgeAda({ running: false });
    const said = listen();
    const seen: string[] = [];
    const watch = new MutationObserver(() => void seen.push(document.body.textContent ?? ""));
    watch.observe(document.body, { childList: true, subtree: true, characterData: true });
    fireEvent.click(screen.getByRole("button", { name: "Purge data…" }));
    await flush();
    await confirmPurge("BTCUSDT");
    watch.disconnect();
    expect(seen.filter((text) => /Purged [^.]* of BTCUSDT data/.test(text))).toEqual([]);
    expect(about(said.polite, "BTCUSDT")).toEqual([
      "Purging BTCUSDT data recorded before 2026-08-15. Recording continues. Deleted data cannot be restored.",
    ]);
  });

  it("a job that ends with partitions left is the failed line (partial); one with no figure, finished", async () => {
    polls = {
      [JOB]: [
        json(
          200,
          job({ status: "succeeded", progress_pct: 100, result: { freed_bytes: 5e9, failed: 2 } }),
        ),
      ],
    };
    let page = await mountPage();
    let said = listen();
    await purgeAda({ running: false });
    expect(said.assertive).toEqual([
      "Purge of ADAUSDT failed (partial). Some data may already be deleted: check ADAUSDT's size and gaps.",
    ]);
    expect(about(said.polite)).toEqual([RUNNING]);
    page.unmount();
    act(() => clearAnnouncements());
    polls = {
      [JOB2]: [json(200, job({ id: JOB2, status: "succeeded", progress_pct: 100, result: {} }))],
    };
    accepted = [JOB2];
    page = await mountPage();
    said = listen();
    await purgeAda({ running: false });
    expect(about(said.polite)).toEqual([RUNNING, "Purge of ADAUSDT finished."]);
    expect(screen.queryByText(/Purged — of ADAUSDT data/)).toBeNull();
  });

  it("a held purge whose re-send gets no answer: Outcome pending names the Recording budget, which is read again", async () => {
    purgeReplies = [
      () =>
        json(403, {
          ...stepUpRequired,
          action_class: "recorder_purge",
          action_summary: "Purge ADAUSDT data",
        }),
      () => Promise.reject(new TypeError("Failed to fetch")),
    ];
    await mountPage();
    const symbol = screen.getByRole("button", { name: "ADAUSDT" });
    fireEvent.click(symbol);
    const detail = screen.getByRole("dialog", { name: "ADAUSDT recording" });
    fireEvent.click(within(detail).getByRole("button", { name: "Purge…" }));
    await flush();
    await confirmPurge("ADAUSDT");
    const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.change(within(challenge).getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(within(challenge).getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    const reads = storageReads();
    fireEvent.click(within(challenge).getByRole("button", { name: "Confirm" }));
    await flush();
    await flush();
    expect(screen.getByRole("dialog", { name: "Purge ADAUSDT data?" })).toHaveTextContent(
      "Outcome pending, see Recording budget",
    );
    expect(storageReads()).toBe(reads + 1);
  });
});
