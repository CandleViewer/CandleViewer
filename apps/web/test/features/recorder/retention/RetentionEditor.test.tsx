/**
 * E16-S03 (#485), SCR-141 whole (E16-D03 §4–§10; E16-D06 §13's SCR-141 Feature, KB-09, KB-12, KB-13, FM-11, FM-12,
 * RG-12, SR-18 to SR-23, T2-06 to T2-08, §16.4, §20.3 (iii), (iv), (viii)): the dialog's states as named RTL
 * fixtures, each with axe (no Storybook for page states, BQ-13), and #485's scenarios as the design amends them, over
 * a stubbed `apiFetch` answering from the `22` examples (no network, C-13.5) on fake timers.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type JSX } from "react";
import { flushSync } from "react-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  registerRecorderExtensions,
  type RetentionEditorProps,
} from "../../../../src/features/recorder/extensions";
import {
  RetentionEditor,
  type RetentionEditorOptions,
} from "../../../../src/features/recorder/retention/RetentionEditor";
import { jobStateOf } from "../../../../src/features/recorder/retention/RetentionFooter";
import type { RefusalRoute } from "../../../../src/features/recorder/recorderApi";
import type { JobView } from "../../../../src/features/recorder/useJobPoll";
import { problem, statusHealthy, stepUpRequired } from "../fixtures";
import { NOW } from "../gridFixtures";
import { frameOf } from "../screenFixtures";
import { POLICIES_DEFAULTS, STORAGE_USAGE } from "./fixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const JOB = "19000000-0000-4000-8000-000000000002";
const REASON = "Read-only while viewing as alex.";
const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });
/** `stepUpRequired` with its own challenge id: each answer a new challenge (SCR-006 keys on it). */
const challenge = (n: number): Response =>
  json(403, {
    ...stepUpRequired,
    challenge_id: `6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a${String(n).padStart(2, "0")}`,
  });
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

/** The answers a test sets; each is called per request, so a body is never read twice. */
interface Routes {
  list?: () => Response | Promise<Response>;
  storage?: () => Response;
  put?: (n: number) => Response | Promise<Response>;
  job?: (n: number) => Response;
  stepUp?: () => Response;
}
let routes: Routes = {};
const count = { put: 0, job: 0 };
function route(url: string, init?: RequestInit): Promise<Response> | Response {
  const method = init?.method ?? "GET";
  const path = url.replace("/api/v1", "");
  if (path.startsWith("/recording/retention-policies")) {
    if (method === "PUT") {
      count.put += 1;
      return routes.put?.(count.put) ?? json(200, { items: POLICIES_DEFAULTS.items, job_id: null });
    }
    return routes.list?.() ?? json(200, POLICIES_DEFAULTS);
  }
  if (path === "/recording/storage") return routes.storage?.() ?? json(200, STORAGE_USAGE);
  if (path.startsWith("/admin/jobs/")) {
    count.job += 1;
    return routes.job?.(count.job) ?? json(200, { id: JOB, status: "queued" });
  }
  if (path === "/auth/step-up") return routes.stepUp?.() ?? json(200, { action_class: "recorder" });
  return json(404, problem(404, "not_found"));
}
/** The PUTs sent: URL, body and key. */
const puts = () =>
  apiFetch.mock.calls
    .filter(([, init]) => init?.method === "PUT")
    .map(([url, init]) => ({
      url,
      body: typeof init?.body === "string" ? (JSON.parse(init.body) as { items: unknown[] }) : null,
      key: new Headers(init?.headers).get("Idempotency-Key"),
    }));

let say = vi.fn<(text: string) => void>();
let reported: unknown[] = [];
const onAnalytics = (event: Event): void => void reported.push((event as CustomEvent).detail);

type Props = Partial<RetentionEditorProps & RetentionEditorOptions>;
function Host(props: Props): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Retention policy
      </button>
      <RetentionEditor
        open={open}
        onClose={() => setOpen(false)}
        status={null}
        storage={STORAGE_USAGE}
        frame={null}
        stale={false}
        say={say}
        {...props}
      />
    </>
  );
}
const press = (control: HTMLElement): void => {
  act(() => control.focus());
  fireEvent.click(control);
};
async function openEditor(props: Props = {}, settle = true) {
  const view = render(<Host {...props} />);
  press(screen.getByRole("button", { name: "Retention policy" }));
  if (settle) await flush();
  return view;
}
const dialog = (): HTMLElement => screen.getByRole("dialog", { name: "Retention policy" });
const row = (name: string): HTMLElement => within(dialog()).getByRole("group", { name });
const field = (name: string): HTMLInputElement =>
  within(row(name)).getByRole("spinbutton") as HTMLInputElement;
const apply = (): HTMLElement => within(dialog()).getByRole("button", { name: "Apply" });
function type(input: HTMLElement, text: string): void {
  act(() => input.focus());
  fireEvent.change(input, { target: { value: text } });
  fireEvent.blur(input);
}
function choose(combobox: HTMLElement, option: string): void {
  fireEvent.click(combobox);
  fireEvent.click(screen.getByRole("option", { name: option }));
}
/** Trades 30 → 7 days with the Action set to Delete after: D03's worked reduction (K1). */
function reduceTrades(): void {
  type(field("Trades"), "7");
  choose(within(row("Trades")).getByRole("combobox", { name: "Trades Action" }), "Delete after");
}
async function previewNow(): Promise<void> {
  press(within(dialog()).getByRole("button", { name: "Preview changes" }));
  await flush();
}
/** Opens the confirm from a valid Apply, past CMP-044's 400 ms guard. */
async function openConfirm(): Promise<HTMLElement> {
  press(apply());
  await advance(500);
  return screen.getAllByRole("dialog").at(-1) as HTMLElement;
}
/** D03's worked K1 confirm with its word typed, past CMP-044's guard (it rearms on the match). */
async function typedConfirm(): Promise<{ confirm: HTMLElement; destroy: HTMLElement }> {
  const confirm = await openConfirm();
  fireEvent.change(within(confirm).getByRole("textbox", { name: "Type trades to confirm" }), {
    target: { value: "trades" },
  });
  await advance(500);
  const destroy = within(confirm).getByRole("button", {
    name: "Apply · delete eligible data at the next run",
  });
  return { confirm, destroy };
}
/** SCR-006 answered with a password and a matching code. */
async function grant(): Promise<void> {
  const gate = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
  fireEvent.change(within(gate).getByLabelText("Password"), { target: { value: "pw" } });
  fireEvent.change(within(gate).getByLabelText("Authenticator code"), {
    target: { value: "123456" },
  });
  fireEvent.click(within(gate).getByRole("button", { name: "Confirm" }));
  await flush();
  await flush();
}
/**
 * Esc as a browser delivers a user's key: a microtask checkpoint follows each listener, so React's update from the
 * capture phase commits before the bubble phase (A-5353-02); a capture listener on the cell does it here, outside
 * `act`, since a scripted event in jsdom never does.
 */
function userEscape(target: HTMLElement): KeyboardEvent {
  const cell = target.closest("td") as HTMLElement;
  const flushNow = (): void => flushSync(() => undefined);
  const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean | undefined };
  const was = env.IS_REACT_ACT_ENVIRONMENT;
  env.IS_REACT_ACT_ENVIRONMENT = false;
  cell.addEventListener("keydown", flushNow, true);
  const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  try {
    target.dispatchEvent(event);
  } finally {
    cell.removeEventListener("keydown", flushNow, true);
    env.IS_REACT_ACT_ENVIRONMENT = was;
  }
  return event;
}
/** A PUT answered when the test says so. */
function held(): { put: () => Promise<Response>; answer: (r: Response) => void } {
  let answer: (r: Response) => void = () => undefined;
  return {
    put: () => new Promise<Response>((resolve) => (answer = resolve)),
    answer: (r) => answer(r),
  };
}
const K1_TITLE = "Delete trades after 7 days?";
async function seriousAxe(element: Element): Promise<unknown[]> {
  vi.useRealTimers();
  const res = await axe.run(element, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

beforeAll(() => {
  // CMP-009 keeps its active option in view; jsdom lays nothing out.
  Element.prototype.scrollIntoView = vi.fn();
});
beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    now: NOW,
  });
  routes = {};
  count.put = 0;
  count.job = 0;
  apiFetch.mockImplementation(async (url, init) => route(url, init));
  say = vi.fn();
  reported = [];
  window.addEventListener("cv:analytics", onAnalytics);
});
afterEach(() => {
  window.removeEventListener("cv:analytics", onAnalytics);
  apiFetch.mockReset();
  vi.useRealTimers();
});

// A cold first mount takes seconds on a loaded host; each case gets the axe tests' budget.
const CASE = { timeout: 30_000 } as const;
const NOTHING_BEFORE =
  "Nothing recorded before 2026-09-07 exists yet (about 0 GB now; recording started about 2026-09-12), so the first run deletes nothing.";
const EFFECT =
  "Shorter retention removes history from replay, footprint and profile look-backs and from journal back-fill after the cut-off date";

describe("SCR-141's states (D03 §4, §8, §9; D06 §18)", CASE, () => {
  it("loading: Loading retention policy… with skeleton rows, Cancel only, busy until the set answers", async () => {
    routes.list = () => new Promise<Response>(() => undefined);
    await openEditor();
    expect(dialog()).toHaveAttribute("aria-busy", "true");
    expect(within(dialog()).getByText("Loading retention policy…")).toBeVisible();
    expect(within(dialog()).queryByRole("spinbutton")).toBeNull();
    expect(within(dialog()).getByRole("button", { name: "Cancel" })).toBeVisible();
    expect(within(dialog()).queryByRole("button", { name: "Apply" })).toBeNull();
    expect(await seriousAxe(dialog())).toEqual([]);
  });

  it("editing-clean: the anatomy on the 22 set; first focus on Trades; Apply's reason 'No changes to apply.'", async () => {
    await openEditor();
    expect(
      within(dialog()).getByRole("spinbutton", { name: "Trades Retention (days)" }),
    ).toHaveFocus();
    expect(dialog()).toHaveTextContent(
      "A symbol's rule wins over the global default. Pinned symbols are exempt.",
    );
    expect(dialog()).toHaveTextContent(
      "Under this policy the fast store settles at most about 189.8 GB (9 % of 2,000 GB), plus pinned data.",
    );
    expect(dialog()).toHaveTextContent(
      "Non-pinned growth 520 MB/day × the longest window 365 days ≈ 189.8 GB.",
    );
    expect(dialog()).toHaveTextContent(
      "Nothing becomes eligible: this policy keeps data as long as today.",
    );
    expect(dialog()).toHaveTextContent("Next retention run: daily at 03:00 UTC");
    expect(within(dialog()).getByRole("grid", { name: "Per-symbol overrides" })).toHaveTextContent(
      "ETHUSDT",
    );
    expect(
      within(dialog()).getByRole("region", { name: "Pinned symbols (exempt)" }),
    ).toHaveTextContent("BTCUSDT· 812.3 GB· Exempt (pinned)");
    expect(apply()).toHaveAccessibleDescription("No changes to apply.");
    expect(
      within(dialog()).queryByText("Unsaved changes — Cancel or Esc discards them."),
    ).toBeNull();
    expect(await seriousAxe(dialog())).toEqual([]);
  });

  it("editing-dirty-lengthen: trades 30 → 90 keeps data longer; Apply is ready", async () => {
    await openEditor();
    type(field("Trades"), "90");
    expect(within(row("Trades")).getByRole("button", { name: "Reset to default" })).toBeVisible();
    expect(dialog()).toHaveTextContent("Nothing becomes eligible: this change keeps data longer.");
    expect(dialog()).toHaveTextContent("Unsaved changes — Cancel or Esc discards them.");
    expect(apply()).not.toHaveAccessibleDescription();
    expect(await seriousAxe(dialog())).toEqual([]);
  });

  it("editing-dirty-reduce: the inline consequence and the pinned line; Apply waits for the preview", async () => {
    await openEditor();
    reduceTrades();
    expect(dialog()).toHaveTextContent(
      "Trades for ETHUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. " +
        NOTHING_BEFORE,
    );
    expect(dialog()).toHaveTextContent("BTCUSDT is pinned and is not affected.");
    expect(apply()).toHaveAccessibleDescription("Preview the change first.");
    expect(await seriousAxe(dialog())).toEqual([]);
  });

  it("view-as: one notice; every write T2 pointing at it; the preview still works (T2-06)", async () => {
    await openEditor({ viewAs: { user: "alex" } });
    // The one visible notice; each field's own copy of the reason is visually hidden (CMP-008, CMP-009).
    const [notice] = within(dialog()).getAllByText(REASON);
    expect(notice).toBeVisible();
    const locked = within(dialog()).getByRole("button", { name: "Not available Apply" });
    expect(locked).toHaveAttribute("aria-disabled", "true");
    expect(locked).toHaveAccessibleDescription(REASON);
    expect(within(dialog()).getByRole("checkbox", { name: /Apply now/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(field("Trades")).toHaveAttribute("aria-disabled", "true");
    press(locked);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(say.mock.calls).toEqual([[REASON]]);
    press(within(dialog()).getByRole("button", { name: "Preview changes" }));
    await flush();
    expect(
      within(dialog()).getByRole("heading", { name: "What becomes eligible for deletion" }),
    ).toHaveFocus();
    expect(await seriousAxe(dialog())).toEqual([]);
  });

  it("the set cannot be read: the dialog says so with Retry, which reads it again", async () => {
    let fail = true;
    routes.list = () =>
      fail ? json(503, problem(503, "service_unavailable")) : json(200, POLICIES_DEFAULTS);
    await openEditor();
    expect(within(dialog()).getByText("Retention policy could not be loaded.")).toBeVisible();
    fail = false;
    press(within(dialog()).getByRole("button", { name: "Retry" }));
    await flush();
    expect(field("Trades")).toHaveValue("30");
  });
});

describe("#485 scenarios as amended (scout §8; D06 §13's SCR-141 Feature)", CASE, () => {
  it("1. a reduction shows its cost before anything is applied; a later edit resets the preview", async () => {
    await openEditor();
    reduceTrades();
    press(apply());
    const summary = within(dialog()).getByRole("heading", { name: "Preview the change first." });
    expect(summary).toHaveFocus();
    await previewNow();
    const panel = within(dialog()).getByRole("region", {
      name: "What becomes eligible for deletion",
    });
    const heading = within(panel).getByRole("heading", {
      name: "What becomes eligible for deletion",
    });
    expect(heading).toHaveFocus();
    expect(heading).toHaveAccessibleDescription("About 0 GB now across 1 symbol");
    const table = within(panel).getByRole("table", { name: "What becomes eligible for deletion" });
    expect(
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.textContent),
    ).toEqual([
      "ETHUSDTTrades——about 0 GB now (recorded since about 2026-09-12)",
      "BTCUSDTTrades——Exempt (pinned)",
    ]);
    expect(panel).toHaveTextContent(
      "Estimated from the storage report, per symbol across its recorded streams; the retention run's audit record carries the exact figures.",
    );
    expect(apply()).not.toHaveAccessibleDescription();
    expect(puts()).toEqual([]);
    expect(reported).toContainEqual({ name: "retention.preview_requested", kind: "K1" });
    type(field("Trades"), "6");
    expect(
      within(dialog()).queryByRole("region", { name: "What becomes eligible for deletion" }),
    ).toBeNull();
    expect(apply()).toHaveAccessibleDescription("Preview the change first.");
  });

  it("2. lowering the hot window without shortening the total deletes nothing: the plain confirm", async () => {
    await openEditor();
    type(field("Trades"), "7");
    expect(dialog()).toHaveTextContent(
      "Moves trades older than 7 days to Parquet sooner; it is still kept for 24 months. This change deletes nothing.",
    );
    const confirm = await openConfirm();
    expect(confirm).toHaveAccessibleName("Apply the retention changes?");
    expect(confirm).toHaveAccessibleDescription(
      expect.stringContaining(
        "Nothing is deleted. Moves trades older than 7 days to Parquet sooner; it is still kept for 24 months.",
      ),
    );
    expect(within(confirm).queryByRole("textbox")).toBeNull();
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(confirm).not.toHaveTextContent(EFFECT);
  });

  it("3. the typed confirm gates destruction: Cancel first, the exact word, nothing sent until it matches", async () => {
    await openEditor();
    reduceTrades();
    await previewNow();
    const confirm = await openConfirm();
    expect(confirm).toHaveAccessibleName("Delete trades after 7 days?");
    expect(confirm).toHaveAccessibleDescription(
      expect.stringContaining(
        "Trades for ETHUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC)",
      ),
    );
    expect(confirm).toHaveTextContent(
      "It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
    );
    expect(confirm).toHaveTextContent("Bars built from these trades can no longer be rebuilt.");
    // C-5353-06: the effect on replay and journal back-fill, once (D03 :315 `SCR-141/effect`).
    expect(within(confirm).getAllByText(EFFECT, { exact: false })).toHaveLength(1);
    expect(confirm).toHaveTextContent("BTCUSDT is pinned and is not affected.");
    expect(confirm).toHaveTextContent("You'll confirm with your password and a code.");
    expect(confirm).toHaveTextContent("This action is audited.");
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    const word = within(confirm).getByRole("textbox", { name: "Type trades to confirm" });
    const destroy = within(confirm).getByRole("button", {
      name: "Apply · delete eligible data at the next run",
    });
    expect(word).toHaveValue("");
    expect(destroy).toBeDisabled();
    fireEvent.change(word, { target: { value: "Trades" } });
    fireEvent.keyDown(word, { key: "Enter" });
    expect(destroy).toBeDisabled();
    fireEvent.change(word, { target: { value: "trades" } });
    expect(destroy).toBeEnabled();
    expect(puts()).toEqual([]);
    await advance(500); // CMP-044's guard rearms when the word matches
    press(destroy);
    await flush();
    const [sent] = puts();
    expect(sent?.url).toBe("/api/v1/recording/retention-policies");
    expect(sent?.body?.items).toHaveLength(9);
    expect(sent?.body?.items[0]).toEqual({
      stream: "trades",
      retain_days: 7,
      action: "drop",
      symbol: null,
      applies_to_pinned: false,
    });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    const outcome = within(dialog()).getByText(
      "Retention policy saved. Audited as retention.change.",
    );
    expect(outcome).toHaveFocus();
    expect(within(dialog()).getByRole("button", { name: "Close" })).toBeVisible();
    expect(dialog()).toHaveTextContent("Next retention run: daily at 03:00 UTC");
  });

  it("3. a per-symbol rule types its symbol (K3, F3): Add override ETHUSDT trades 14 d Delete after", async () => {
    await openEditor();
    press(within(dialog()).getByRole("button", { name: "Add override" }));
    const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
    fireEvent.change(within(grid).getByRole("combobox", { name: "Symbol" }), {
      target: { value: "ETHUSDT" },
    });
    type(within(grid).getByRole("spinbutton", { name: "Retention (days)" }), "14");
    choose(within(grid).getByRole("combobox", { name: "Action" }), "Delete after");
    await previewNow();
    const confirm = await openConfirm();
    expect(confirm).toHaveAccessibleName("Delete ETHUSDT trades after 14 days?");
    expect(within(confirm).getByRole("textbox", { name: "Type ETHUSDT to confirm" })).toBeVisible();
  });

  it("4. the step-up is a flow: Esc leaves 'Not sent' with the word kept and one request sent", async () => {
    routes.put = () => json(403, stepUpRequired);
    await openEditor();
    reduceTrades();
    await previewNow();
    const confirm = await openConfirm();
    const word = within(confirm).getByRole("textbox", { name: "Type trades to confirm" });
    fireEvent.change(word, { target: { value: "trades" } });
    const destroy = within(confirm).getByRole("button", {
      name: "Apply · delete eligible data at the next run",
    });
    await advance(500);
    press(destroy);
    await flush();
    const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.keyDown(within(challenge).getByLabelText("Password"), { key: "Escape" });
    await flush();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(confirm).toHaveTextContent("Not sent");
    expect(word).toHaveValue("trades");
    expect(destroy).toHaveFocus();
    expect(puts()).toHaveLength(1);
  });

  it("4. a granted step-up re-sends the held PUT once, unchanged, with its key (C-2.10)", async () => {
    routes.put = (n) =>
      n === 1
        ? json(403, stepUpRequired)
        : json(200, { items: POLICIES_DEFAULTS.items, job_id: null });
    await openEditor();
    reduceTrades();
    await previewNow();
    const confirm = await openConfirm();
    fireEvent.change(within(confirm).getByRole("textbox", { name: "Type trades to confirm" }), {
      target: { value: "trades" },
    });
    await advance(500);
    press(
      within(confirm).getByRole("button", { name: "Apply · delete eligible data at the next run" }),
    );
    await flush();
    const challenge = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    fireEvent.change(within(challenge).getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(within(challenge).getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(within(challenge).getByRole("button", { name: "Confirm" }));
    await flush();
    await flush();
    const [first, again] = puts();
    expect(puts()).toHaveLength(2);
    expect(again?.key).toBe(first?.key);
    expect(again?.body).toEqual(first?.body);
    expect(
      within(dialog()).getByText("Retention policy saved. Audited as retention.change."),
    ).toHaveFocus();
  });

  it.each([
    ["no answer", () => Promise.reject(new TypeError("offline"))],
    ["a 200 it cannot read", () => new Response("<html>proxy</html>", { status: 200 })],
  ] as const)(
    "4. %s may have applied: the outcome is pending, the set is read back, nothing is re-sent (C-5353-12)",
    async (_case, put) => {
      routes.put = put;
      let lists = 0;
      routes.list = () => {
        lists += 1;
        return json(200, POLICIES_DEFAULTS);
      };
      await openEditor();
      type(field("Trades"), "90");
      const confirm = await openConfirm();
      press(within(confirm).getByRole("button", { name: "Apply" }));
      await flush();
      await advance(10_000);
      expect(puts()).toHaveLength(1);
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
      expect(
        within(dialog()).getByRole("heading", { name: "Outcome pending, see Retention policy" }),
      ).toHaveFocus();
      expect(dialog()).not.toHaveTextContent("Not sent");
      expect(dialog()).not.toHaveTextContent("Cannot reach the server");
      expect(lists).toBe(2);
      expect(field("Trades")).toHaveValue("30");
    },
  );

  it.each([
    [
      json(422, problem(422, "retention_invalid_policy")),
      "Bars can't be deleted before the ticks they came from are kept — adjust the tiers.",
    ],
    [json(409, problem(409, "job_running")), "A retention run is already running."],
    [json(409, problem(409, "conflict")), "Retention runs are off on this server."],
    [
      json(503, problem(503, "audit_unavailable")),
      "Not saved: the audit record could not be written.",
    ],
    [
      json(422, problem(422, "validation_failed")),
      "Something in this form is not accepted by the server.",
    ],
    [json(403, problem(403, "forbidden")), "Not saved: the server refused it. (forbidden)"],
  ])(
    "5. a refusal %# shows at the point of action: the summary takes focus, no alert, nothing re-sent",
    async (answer, words) => {
      routes.put = () => answer.clone();
      await openEditor();
      type(field("Trades"), "90");
      const confirm = await openConfirm();
      press(within(confirm).getByRole("button", { name: "Apply" }));
      await flush();
      const heading = within(dialog()).getByRole("heading", { name: words });
      expect(heading).toHaveFocus();
      expect(heading.closest('[role="alert"], [aria-live]')).toBeNull();
      expect(dialog()).not.toHaveTextContent("server detail, never rendered");
      expect(field("Trades")).not.toHaveAttribute("aria-disabled");
      expect(puts()).toHaveLength(1);
    },
  );

  it("5. field errors: Apply says 'Fix 2 fields.'; a press moves focus to the summary and its links", async () => {
    await openEditor();
    type(field("Trades"), "0");
    const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
    type(within(grid).getByRole("spinbutton"), "4000");
    expect(apply()).toHaveAccessibleDescription("Fix 2 fields.");
    press(apply());
    const heading = within(dialog()).getByRole("heading", {
      name: "Fix 2 fields before applying.",
    });
    expect(heading).toHaveFocus();
    expect(heading.closest('[role="alert"], [aria-live]')).toBeNull();
    press(
      within(dialog()).getByRole("button", {
        name: "Trades · Retention (days): Keep at least 1 day.",
      }),
    );
    expect(field("Trades")).toHaveFocus();
    expect(
      within(dialog()).getByRole("button", {
        name: "ETHUSDT · Order-book deltas · Retention (days): At most 3650 days (10 years).",
      }),
    ).toBeVisible();
    expect(puts()).toEqual([]);
    expect(await seriousAxe(dialog())).toEqual([]);
  });

  it("6. pinned symbols are exempt; Manage pin in Recorder closes the dialog onto SCR-140's row detail", async () => {
    const openRowDetail = vi.fn();
    let off = (): void => undefined;
    act(() => {
      off = registerRecorderExtensions({ openRowDetail });
    });
    await openEditor();
    const pinned = within(dialog()).getByRole("region", { name: "Pinned symbols (exempt)" });
    expect(within(pinned).queryByRole("button", { name: /Unpin|Keep forever/ })).toBeNull();
    press(within(pinned).getByRole("button", { name: "Manage pin in Recorder" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(openRowDetail).toHaveBeenCalledWith("BTCUSDT");
    act(() => off());
  });

  it("7. Apply now: the sweep is queued, runs and ends; said once at the start and once at the end (F-09)", async () => {
    const result = {
      deleted: 3,
      freed_bytes: 1_200_000_000,
      skipped: 0,
      failed: 0,
      skipped_locked: false,
    };
    routes.put = () => json(200, { items: POLICIES_DEFAULTS.items, job_id: JOB });
    routes.job = (n) =>
      n === 1
        ? json(200, { id: JOB, kind: "retention_sweep", status: "running", progress_pct: 42 })
        : n === 2
          ? json(200, { id: JOB, kind: "retention_sweep", status: "running", progress_pct: 63 })
          : json(200, {
              id: JOB,
              kind: "retention_sweep",
              status: "succeeded",
              progress_pct: 100,
              result,
            });
    await openEditor();
    type(field("Trades"), "90");
    press(within(dialog()).getByRole("checkbox", { name: "Apply now (start a retention run)" }));
    // The footer's polite region, there from its first paint: every utterance it makes from here on.
    const region = within(dialog())
      .getAllByRole("status")
      .filter(
        (r) => r.getAttribute("aria-live") === "polite" && r.getAttribute("aria-atomic") === "true",
      )
      .at(-1) as HTMLElement;
    const said: string[] = [];
    const observer = new MutationObserver(() => {
      const text = region.textContent ?? "";
      if (text !== "" && said.at(-1) !== text) said.push(text);
    });
    observer.observe(region, { childList: true, subtree: true, characterData: true });
    const confirm = await openConfirm();
    expect(confirm).toHaveAccessibleDescription(
      expect.stringContaining(
        "This change deletes nothing more. The retention run that starts now still deletes",
      ),
    );
    press(within(confirm).getByRole("button", { name: "Apply" }));
    await flush();
    expect(puts()[0]?.url).toBe("/api/v1/recording/retention-policies?apply_now=true");
    const box = within(dialog()).getByRole("checkbox", {
      name: "Apply now (start a retention run)",
    });
    expect(box).toHaveAttribute("aria-busy", "true");
    expect(box).not.toBeChecked();
    await flush();
    expect(within(dialog()).getByRole("progressbar")).toHaveAttribute(
      "aria-valuetext",
      "Retention run running · 42 %",
    );
    await advance(2_000);
    expect(within(dialog()).getByRole("progressbar")).toHaveAttribute(
      "aria-valuetext",
      "Retention run running · 63 %",
    );
    await advance(2_000);
    expect(dialog()).toHaveTextContent("Retention run succeeded · about 1.2 GB freed");
    expect(
      within(dialog()).getByRole("checkbox", { name: "Apply now (start a retention run)" }),
    ).not.toHaveAttribute("aria-busy");
    observer.disconnect();
    expect(said).toEqual(["Retention run queued", "Retention run succeeded · about 1.2 GB freed"]);
    expect(region.textContent).toBe("Retention run succeeded · about 1.2 GB freed");
  });

  it("7. a failed sweep is said once, assertively, with what to check (BG-05)", async () => {
    routes.put = () => json(200, { items: POLICIES_DEFAULTS.items, job_id: JOB });
    routes.job = () => json(200, { id: JOB, status: "failed", error: "io_error" });
    await openEditor();
    type(field("Trades"), "90");
    press(within(dialog()).getByRole("checkbox", { name: "Apply now (start a retention run)" }));
    const confirm = await openConfirm();
    press(within(confirm).getByRole("button", { name: "Apply" }));
    await flush();
    await flush();
    expect(dialog()).toHaveTextContent("Retention run failed (io_error)");
    expect(dialog()).toHaveTextContent(
      "Some data may already be deleted: check the storage report.",
    );
    // A-5353-08: the alert carries the safety sentence too, once.
    const alert = within(dialog()).getAllByRole("alert").at(-1) as HTMLElement;
    expect(alert.textContent).toBe(
      "Retention run failed (io_error) Some data may already be deleted: check the storage report.",
    );
  });
});

describe(
  "the sweep's other ends (#5309's poll: a lost job, a refused poll; C-5353-13)",
  CASE,
  () => {
    /** Ticks Apply now on a lengthening and applies it; returns the footer's polite region's utterances. */
    async function sweep(): Promise<() => string[]> {
      routes.put = () => json(200, { items: POLICIES_DEFAULTS.items, job_id: JOB });
      await openEditor();
      type(field("Trades"), "90");
      press(within(dialog()).getByRole("checkbox", { name: "Apply now (start a retention run)" }));
      const region = within(dialog())
        .getAllByRole("status")
        .filter((r) => r.getAttribute("aria-atomic") === "true")
        .at(-1) as HTMLElement;
      const said: string[] = [];
      const observer = new MutationObserver(() => {
        const text = region.textContent ?? "";
        if (text !== "" && said.at(-1) !== text) said.push(text);
      });
      observer.observe(region, { childList: true, subtree: true, characterData: true });
      const confirm = await openConfirm();
      press(within(confirm).getByRole("button", { name: "Apply" }));
      await flush();
      await flush();
      return () => {
        observer.disconnect();
        return said;
      };
    }

    it("a sweep the server lost (404) ends on its line, said once, and the poll stops", async () => {
      routes.job = (n) =>
        n === 1
          ? json(200, { id: JOB, kind: "retention_sweep", status: "running", progress_pct: 10 })
          : json(404, problem(404, "not_found"));
      const stop = await sweep();
      await advance(2_000);
      const lost = "Retention run status is no longer available on the server. (not_found)";
      expect(dialog()).toHaveTextContent(lost);
      await advance(10_000);
      expect(count.job).toBe(2);
      expect(stop()).toEqual(["Retention run queued", lost]);
    });

    it("a refused poll shows its T4 under the line, said once; the next answer clears it", async () => {
      routes.job = (n) =>
        n <= 2
          ? json(503, problem(503, "audit_unavailable"))
          : json(200, { id: JOB, kind: "retention_sweep", status: "running", progress_pct: 50 });
      const stop = await sweep();
      const refused = "Status not updated: the server refused it. (audit_unavailable)";
      // The visible line (the polite region keeps its last words, as every live region here does).
      const line = () => within(dialog()).queryByText(refused, { selector: "p" });
      expect(line()).toBeVisible();
      await advance(2_000);
      expect(line()).toBeVisible();
      await advance(2_000);
      expect(line()).toBeNull();
      expect(within(dialog()).getByRole("progressbar")).toHaveAttribute(
        "aria-valuetext",
        "Retention run running · 50 %",
      );
      expect(stop()).toEqual(["Retention run queued", refused]);
    });

    it("a finished sweep's line belongs to its opening: the next opening is at rest again", async () => {
      routes.job = () =>
        json(200, {
          id: JOB,
          kind: "retention_sweep",
          status: "succeeded",
          result: { deleted: 0, freed_bytes: 0, skipped: 0, failed: 0, skipped_locked: true },
        });
      const stop = await sweep();
      stop();
      expect(dialog()).toHaveTextContent("Retention run succeeded");
      expect(dialog()).toHaveTextContent(
        "Nothing was swept: another retention run or a purge held the volume.",
      );
      expect(dialog()).not.toHaveTextContent("freed");
      press(within(dialog()).getByRole("button", { name: "Close" }));
      press(screen.getByRole("button", { name: "Retention policy" }));
      await flush();
      expect(dialog()).toHaveTextContent("Next retention run: daily at 03:00 UTC");
      expect(dialog()).not.toHaveTextContent("Retention run succeeded");
    });
  },
);

describe("one confirm, one request (S-5353-01, S-5353-02, C-5353-03, S-5353-04)", CASE, () => {
  const SAVED = { items: POLICIES_DEFAULTS.items, job_id: null };
  const confirmNamed = (name: string) => screen.queryByRole("dialog", { name });

  it("in flight the confirm holds (H22): Esc, Cancel and its close do nothing; its challenge opens SCR-006 there", async () => {
    const first = held();
    routes.put = first.put;
    await openEditor();
    reduceTrades();
    await previewNow();
    const { confirm, destroy } = await typedConfirm();
    press(destroy);
    await flush();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    press(within(confirm).getByRole("button", { name: "Cancel" }));
    press(within(confirm).getByRole("button", { name: `Close ${K1_TITLE}` }));
    await flush();
    expect(confirmNamed(K1_TITLE)).toBe(confirm);
    expect(confirm).toHaveAttribute("aria-busy", "true");
    first.answer(challenge(1));
    await flush();
    expect(confirm).toContainElement(
      screen.getByRole("alertdialog", { name: "Confirm with two-factor" }),
    );
    expect(puts()).toHaveLength(1);
  });

  it("a challenge for a confirm that closed meanwhile is dropped: no SCR-006, 'Not sent' where the action was", async () => {
    const first = held();
    routes.put = (n) => (n === 1 ? first.put() : json(200, SAVED));
    const view = await openEditor();
    // An add row naming a symbol no source lists yet: not part of the set the confirm shows.
    press(within(dialog()).getByRole("button", { name: "Add override" }));
    const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
    fireEvent.change(within(grid).getByRole("combobox", { name: "Symbol" }), {
      target: { value: "SOLUSDT" },
    });
    reduceTrades();
    await previewNow();
    const { destroy } = await typedConfirm();
    press(destroy);
    await flush();
    // SCR-140's frame lists SOLUSDT now: the add row joins the set, and the form drifts off the confirm in flight.
    view.rerender(<Host frame={frameOf()} />);
    await flush();
    expect(confirmNamed(K1_TITLE)).toBeNull();
    first.answer(challenge(1));
    await flush();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(within(dialog()).getByRole("heading", { name: "Not sent" })).toHaveFocus();
    expect(puts()).toHaveLength(1);
    // The next confirm shows no SCR-006 before its own press, and sends the set it shows.
    await previewNow();
    const { destroy: again } = await typedConfirm();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    press(again);
    await flush();
    const [earlier, mine] = puts();
    expect(mine?.key).not.toBe(earlier?.key);
    expect(mine?.body?.items).toHaveLength(10);
    expect(mine?.body?.items).toContainEqual(expect.objectContaining({ symbol: "SOLUSDT" }));
  });

  it("closed while its re-send is in flight: the re-send's challenge never surfaces under the next confirm", async () => {
    const resend = held();
    routes.put = (n) => (n === 1 ? challenge(1) : n === 2 ? resend.put() : json(200, SAVED));
    await openEditor();
    reduceTrades();
    await previewNow();
    const { confirm, destroy } = await typedConfirm();
    press(destroy);
    await flush();
    await grant();
    // The re-send is in flight; SCR-006's scrim paints under the confirm's footer (A-5347-01), so its Cancel is pressed.
    const footerCancel = within(confirm)
      .getAllByRole("button", { name: "Cancel" })
      .find((b) => b.closest('[role="alertdialog"]') === null) as HTMLElement;
    press(footerCancel);
    await flush();
    expect(confirmNamed(K1_TITLE)).toBeNull();
    resend.answer(challenge(2));
    await flush();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    // Another change and its own plain confirm: no SCR-006 until its own press, which sends its own set.
    press(within(row("Trades")).getByRole("button", { name: "Reset to default" }));
    type(field("Tickers"), "45");
    const next = await openConfirm();
    expect(next).toHaveAccessibleName("Keep tickers for 45 days?");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    press(within(next).getByRole("button", { name: "Apply" }));
    await flush();
    const [first, resent, mine] = puts();
    expect(puts()).toHaveLength(3);
    expect(resent?.key).toBe(first?.key);
    expect(mine?.key).not.toBe(first?.key);
    expect(mine?.body?.items[0]).toEqual({
      stream: "trades",
      retain_days: 30,
      action: "archive_parquet",
      symbol: null,
      applies_to_pinned: false,
    });
  });

  it("an idle confirm the form drifts off closes onto 'Preview the change first.'; nothing is sent", async () => {
    const view = await openEditor();
    press(within(dialog()).getByRole("button", { name: "Add override" }));
    const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
    fireEvent.change(within(grid).getByRole("combobox", { name: "Symbol" }), {
      target: { value: "SOLUSDT" },
    });
    reduceTrades();
    await previewNow();
    await typedConfirm();
    view.rerender(<Host frame={frameOf()} />);
    await flush();
    expect(confirmNamed(K1_TITLE)).toBeNull();
    expect(
      within(dialog()).getByRole("heading", { name: "Preview the change first." }),
    ).toHaveFocus();
    expect(apply()).toHaveAccessibleDescription("Preview the change first.");
    expect(puts()).toEqual([]);
  });

  it("a frame that changes what the open confirm says closes it too (its scope widened)", async () => {
    const view = await openEditor();
    reduceTrades();
    await previewNow();
    await typedConfirm();
    view.rerender(<Host frame={frameOf()} />);
    await flush();
    expect(confirmNamed(K1_TITLE)).toBeNull();
    expect(
      within(dialog()).getByRole("heading", { name: "Preview the change first." }),
    ).toHaveFocus();
    expect(puts()).toEqual([]);
  });

  it("the confirm shows and sends the set Apply froze: a report re-read under it changes none of its words", async () => {
    const view = await openEditor();
    type(field("Trades"), "90");
    const confirm = await openConfirm();
    const words =
      "Nothing is deleted. The fast store settles at most about 189.8 GB, plus pinned data.";
    expect(confirm).toHaveAccessibleDescription(words);
    const faster = {
      ...STORAGE_USAGE,
      symbols: STORAGE_USAGE.symbols.map((s) => ({
        ...s,
        daily_growth_bytes: 2 * s.daily_growth_bytes,
      })),
    };
    view.rerender(<Host storage={faster} />);
    await flush();
    expect(confirmNamed("Keep trades for 90 days?")).toBe(confirm);
    expect(confirm).toHaveAccessibleDescription(words);
    press(within(confirm).getByRole("button", { name: "Apply" }));
    await flush();
    expect(puts()[0]?.body?.items[0]).toMatchObject({ stream: "trades", retain_days: 90 });
  });

  it("a re-send with no answer closes the confirm and says the outcome is pending: never 'Not sent', never re-sent", async () => {
    routes.put = (n) => (n === 1 ? challenge(1) : Promise.reject(new TypeError("offline")));
    let lists = 0;
    routes.list = () => {
      lists += 1;
      return json(200, POLICIES_DEFAULTS);
    };
    await openEditor();
    reduceTrades();
    await previewNow();
    const { destroy } = await typedConfirm();
    press(destroy);
    await flush();
    await grant();
    expect(confirmNamed(K1_TITLE)).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(
      within(dialog()).getByRole("heading", { name: "Outcome pending, see Retention policy" }),
    ).toHaveFocus();
    expect(document.body).not.toHaveTextContent("Not sent");
    await advance(10_000);
    const [first, resent] = puts();
    expect(puts()).toHaveLength(2);
    expect(resent?.key).toBe(first?.key);
    expect(lists).toBe(2);
  });

  it("a challenge on the re-send opens one more SCR-006; one on that re-send is the refusal (the host's rule)", async () => {
    routes.put = (n) => challenge(n);
    let stepUps = 0;
    routes.stepUp = () => {
      stepUps += 1;
      return json(200, { action_class: "recorder" });
    };
    await openEditor();
    reduceTrades();
    await previewNow();
    const { destroy } = await typedConfirm();
    press(destroy);
    await flush();
    await grant();
    expect(screen.getByRole("alertdialog", { name: "Confirm with two-factor" })).toBeVisible();
    await grant();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(confirmNamed(K1_TITLE)).toBeNull();
    expect(
      within(dialog()).getByRole("heading", {
        name: "Not saved: the server refused it. (step_up_required)",
      }),
    ).toHaveFocus();
    expect(puts()).toHaveLength(3);
    expect(new Set(puts().map((p) => p.key)).size).toBe(1);
    expect(stepUps).toBe(2);
  });
});

describe("keys, focus and the session (D03 §10; KB-09, FM-12; analytics)", CASE, () => {
  it("Esc on a dirty form discards it as the caption said; the next opening reads the set again", async () => {
    await openEditor();
    type(field("Trades"), "90");
    fireEvent.keyDown(field("Trades"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Retention policy" })).toHaveFocus();
    press(screen.getByRole("button", { name: "Retention policy" }));
    await flush();
    expect(field("Trades")).toHaveValue("30");
    expect(
      reported.filter((e) => (e as { name: string }).name === "retention.editor_opened"),
    ).toHaveLength(2);
  });

  it("Esc in a saved override's field leaves the edit, never the dialog (A-5353-02)", async () => {
    await openEditor();
    type(field("Trades"), "90");
    const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
    const days = within(grid).getByRole("spinbutton");
    const cell = days.closest("td") as HTMLElement;
    act(() => cell.focus());
    fireEvent.keyDown(cell, { key: "Enter" });
    fireEvent.change(days, { target: { value: "9" } });
    const event = userEscape(days);
    await flush();
    expect(event.defaultPrevented).toBe(true);
    expect(screen.getByRole("dialog", { name: "Retention policy" })).toBeVisible();
    expect(cell).toHaveFocus();
    expect(within(grid).getByRole("spinbutton")).toHaveValue("3");
    // The unsaved edit elsewhere is kept: only the cell's edit ended.
    expect(field("Trades")).toHaveValue("90");
  });

  it("Enter in a field sends nothing (no implicit submit)", async () => {
    await openEditor();
    type(field("Trades"), "90");
    fireEvent.keyDown(field("Trades"), { key: "Enter" });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(puts()).toEqual([]);
  });

  it("Reset to default puts the seed back and keeps focus on the row's field", async () => {
    await openEditor();
    type(field("Trades"), "90");
    press(within(row("Trades")).getByRole("button", { name: "Reset to default" }));
    expect(field("Trades")).toHaveValue("30");
    expect(field("Trades")).toHaveFocus();
  });

  it("closing after a preview with nothing applied is counted once (retention.change_cancelled_after_preview)", async () => {
    await openEditor();
    reduceTrades();
    await previewNow();
    press(within(dialog()).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(reported).toEqual([
      { name: "retention.editor_opened" },
      { name: "retention.preview_requested", kind: "K1" },
      { name: "retention.change_cancelled_after_preview" },
    ]);
  });

  it("a scrim press keeps a dirty form (the caption names Cancel and Esc only); a clean one closes (A-5353-13)", async () => {
    await openEditor();
    type(field("Trades"), "90");
    const scrim = document.querySelector(".cv-dialog__scrim") as HTMLElement;
    fireEvent.pointerDown(scrim);
    fireEvent.click(scrim);
    expect(dialog()).toBeVisible();
    press(within(row("Trades")).getByRole("button", { name: "Reset to default" }));
    fireEvent.pointerDown(scrim);
    fireEvent.click(scrim);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a Retry whose read fails again hands focus to the new Retry (A-5353-11)", async () => {
    routes.list = () => json(503, problem(503, "service_unavailable"));
    await openEditor();
    press(within(dialog()).getByRole("button", { name: "Retry" }));
    await flush();
    expect(within(dialog()).getByRole("button", { name: "Retry" })).toHaveFocus();
  });

  it("Preview brings the whole panel into view after its heading takes focus (A-5353-12)", async () => {
    await openEditor();
    reduceTrades();
    vi.mocked(Element.prototype.scrollIntoView).mockClear();
    await previewNow();
    const panel = within(dialog()).getByRole("region", {
      name: "What becomes eligible for deletion",
    });
    const calls = vi.mocked(Element.prototype.scrollIntoView).mock;
    expect(calls.contexts).toContain(panel);
    expect(calls.calls.at(calls.contexts.indexOf(panel))).toEqual([
      { block: "nearest", inline: "nearest" },
    ]);
  });

  it("an add row that was not complete when the confirm opened stays after the save, as typed (C-5353-11)", async () => {
    await openEditor();
    press(within(dialog()).getByRole("button", { name: "Add override" }));
    const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
    fireEvent.change(within(grid).getByRole("combobox", { name: "Symbol" }), {
      target: { value: "FOOUSDT" },
    });
    type(field("Trades"), "90");
    const confirm = await openConfirm();
    press(within(confirm).getByRole("button", { name: "Apply" }));
    await flush();
    expect(
      within(dialog()).getByText("Retention policy saved. Audited as retention.change."),
    ).toHaveFocus();
    expect(within(dialog()).getByRole("combobox", { name: "Symbol" })).toHaveValue("FOOUSDT");
    expect(dialog()).toHaveTextContent("Unsaved changes — Cancel or Esc discards them.");
    expect(puts()[0]?.body?.items).not.toContainEqual(
      expect.objectContaining({ symbol: "FOOUSDT" }),
    );
  });

  it("a save in flight keeps the dialog: Esc does not lose its answer", async () => {
    let answer: (r: Response) => void = () => undefined;
    routes.put = () => new Promise<Response>((resolve) => (answer = resolve));
    await openEditor();
    type(field("Trades"), "90");
    const confirm = await openConfirm();
    press(within(confirm).getByRole("button", { name: "Apply" }));
    await flush();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    // The confirm holds while its PUT is in flight (H22), and the editor under it.
    expect(screen.getByRole("dialog", { name: "Keep trades for 90 days?" })).toBe(confirm);
    expect(screen.getAllByRole("dialog", { hidden: true })).toHaveLength(2);
    answer(json(200, { items: POLICIES_DEFAULTS.items, job_id: null }));
    await flush();
    expect(
      within(dialog()).getByText("Retention policy saved. Audited as retention.change."),
    ).toBeVisible();
  });
});

describe(
  "without the storage report (503 before the first sample; #5315's fail-closed scope)",
  CASE,
  () => {
    it("a reduction is still one: the preview names the unknown scope without sizes, the confirm types the stream", async () => {
      routes.storage = () => json(503, problem(503, "service_unavailable"));
      await openEditor({ storage: null });
      reduceTrades();
      expect(apply()).toHaveAccessibleDescription("Preview the change first.");
      await previewNow();
      const panel = within(dialog()).getByRole("region", {
        name: "What becomes eligible for deletion",
      });
      expect(panel).toHaveTextContent(
        "Trades for every unpinned symbol without its own rule older than 7 days become eligible for deletion",
      );
      // C-5353-05: how much goes is unknown, and the sentence says so (D06 §20.3 (viii)).
      const noReport = "No storage report yet, so the size is not estimated.";
      expect(panel).toHaveTextContent(noReport);
      expect(within(panel).queryByRole("table")).toBeNull();
      const confirm = await openConfirm();
      expect(confirm).toHaveAccessibleName("Delete trades after 7 days?");
      expect(confirm).toHaveAccessibleDescription(expect.stringContaining(noReport));
      expect(
        within(confirm).getByRole("textbox", { name: "Type trades to confirm" }),
      ).toBeVisible();
      expect(confirm).not.toHaveTextContent("Nothing is deleted.");
    });

    it("a lengthening needs no report and no preview", async () => {
      routes.storage = () => json(503, problem(503, "service_unavailable"));
      await openEditor({ storage: null });
      type(field("Trades"), "90");
      expect(dialog()).toHaveTextContent(
        "Nothing becomes eligible: this change keeps data longer.",
      );
      expect(apply()).not.toHaveAccessibleDescription();
    });
  },
);

describe(
  "symbols the storage report does not list (it lists at most 64; #5315's open item)",
  CASE,
  () => {
    const K1_LEAD =
      "older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included.";

    it("SCR-140's recorded symbols widen the scope; the estimate names them unsized; a live pin is exempt", async () => {
      // The report lists BTCUSDT (pinned) and ETHUSDT; the status adds SOLUSDT, the frame ADAUSDT and a pinned XRPUSDT.
      await openEditor({ status: statusHealthy, frame: frameOf({ XRPUSDT: { pinned: true } }) });
      reduceTrades();
      const unsized = "Not in the storage report, so not estimated: ADAUSDT and SOLUSDT.";
      // C-5353-01: three symbols, one sized with nothing before the cut-off: never "deletes nothing".
      const sentence = `Trades for 3 symbols ${K1_LEAD} Nothing recorded before 2026-09-07 exists yet for ETHUSDT (about 0 GB now). ${unsized}`;
      expect(dialog()).toHaveTextContent(sentence);
      expect(dialog()).not.toHaveTextContent("deletes nothing");
      expect(dialog()).toHaveTextContent(
        "BTCUSDT is pinned and is not affected.XRPUSDT is pinned and is not affected.",
      );
      expect(
        within(within(dialog()).getByRole("region", { name: "Pinned symbols (exempt)" }))
          .getAllByRole("listitem")
          .map((item) => item.textContent),
      ).toEqual([
        "BTCUSDT· 812.3 GB· Exempt (pinned)· grows about 780 MB/day",
        "XRPUSDT· Exempt (pinned)",
      ]);
      await previewNow();
      const panel = within(dialog()).getByRole("region", {
        name: "What becomes eligible for deletion",
      });
      expect(
        within(within(panel).getByRole("table"))
          .getAllByRole("row")
          .slice(1)
          .map((r) => r.textContent),
      ).toEqual([
        "ETHUSDTTrades——about 0 GB now (recorded since about 2026-09-12)",
        "BTCUSDTTrades——Exempt (pinned)",
        "XRPUSDTTrades——Exempt (pinned)",
      ]);
      expect(panel).toHaveTextContent(`${unsized}BTCUSDT is pinned`);
      expect(within(panel).getByRole("heading")).toHaveAccessibleDescription(
        "About 0 GB now across 1 symbol",
      );
      const confirm = await openConfirm();
      // The unsized symbols are named inside the described paragraph, not in a line after it.
      expect(confirm).toHaveAccessibleDescription(
        `${sentence} It cannot be undone. Replay, footprint history and the journal lose the deleted days. Bars built from these trades can no longer be rebuilt.`,
      );
      expect(confirm).toHaveTextContent("BTCUSDT is pinned and is not affected.");
      expect(confirm).not.toHaveTextContent("About 0 GB now across 1 symbol");
    });

    it("a change that reaches only unsized symbols gives no total; the line names them", async () => {
      await openEditor({ status: statusHealthy });
      press(within(dialog()).getByRole("button", { name: "Add override" }));
      const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
      fireEvent.change(within(grid).getByRole("combobox", { name: "Symbol" }), {
        target: { value: "SOLUSDT" },
      });
      type(within(grid).getByRole("spinbutton", { name: "Retention (days)" }), "14");
      choose(within(grid).getByRole("combobox", { name: "Action" }), "Delete after");
      await previewNow();
      const unsized = "Not in the storage report, so not estimated: SOLUSDT.";
      const panel = within(dialog()).getByRole("region", {
        name: "What becomes eligible for deletion",
      });
      expect(panel).toHaveTextContent(unsized);
      expect(within(panel).queryByRole("table")).toBeNull();
      expect(panel).not.toHaveTextContent("About 0 GB now");
      const confirm = await openConfirm();
      expect(confirm).toHaveAccessibleName("Delete SOLUSDT trades after 14 days?");
      expect(confirm).toHaveTextContent(unsized);
      expect(confirm).not.toHaveTextContent("About 0 GB now");
    });

    it("a pin holds only while every source says so: the frame's unpin puts BTCUSDT in the scope", async () => {
      await openEditor({ frame: frameOf({ BTCUSDT: { pinned: false } }) });
      reduceTrades();
      expect(dialog()).toHaveTextContent(
        `Trades for 5 symbols ${K1_LEAD} About 806.9 GB across 2 symbols goes at the first run. Not in the storage report, so not estimated: 3 symbols.`,
      );
      expect(dialog()).not.toHaveTextContent("is pinned and is not affected");
      expect(
        within(dialog()).getByRole("region", { name: "Pinned symbols (exempt)" }),
      ).toHaveTextContent("No pinned symbols.");
    });

    it("a stored rule for a symbol no source lists keeps it in scope: its shrink is a reduction, unsized (C-5353-04)", async () => {
      routes.list = () =>
        json(200, {
          items: [
            ...POLICIES_DEFAULTS.items,
            {
              id: "f1000000-0000-4000-8000-000000000009",
              stream: "trades",
              retain_days: 30,
              action: "archive_parquet",
              symbol: "ZZZUSDT",
              applies_to_pinned: false,
            },
          ],
        });
      await openEditor();
      const grid = within(dialog()).getByRole("grid", { name: "Per-symbol overrides" });
      type(within(grid).getByRole("spinbutton", { name: "ZZZUSDT trades Retention (days)" }), "7");
      choose(within(grid).getByRole("combobox", { name: "ZZZUSDT trades Action" }), "Delete after");
      expect(apply()).toHaveAccessibleDescription("Preview the change first.");
      expect(dialog()).toHaveTextContent(
        `Trades for ZZZUSDT ${K1_LEAD} Not in the storage report, so not estimated: ZZZUSDT.`,
      );
      expect(dialog()).not.toHaveTextContent("Nothing becomes eligible");
    });
  },
);

describe("the footer's state from the job poll (D03 §8; BQ-11, BQ-18)", () => {
  const view = (patch: Partial<JobView>): JobView => ({
    phase: "running",
    pct: 0,
    job: null,
    route: null,
    pollRefusal: null,
    ...patch,
  });
  it("queued until the server says running; the result's freed bytes; the error code; a lost sweep's code", () => {
    expect(jobStateOf(null)).toEqual({ kind: "rest" });
    expect(jobStateOf(view({}))).toEqual({ kind: "queued" });
    expect(
      jobStateOf(view({ pct: 42, job: { id: JOB, status: "running", progress_pct: 42 } })),
    ).toEqual({
      kind: "running",
      pct: 42,
    });
    const result = { deleted: 1, freed_bytes: 5e9, skipped: 0, failed: 0, skipped_locked: false };
    const succeeded = (patch: Partial<typeof result>) =>
      jobStateOf(
        view({
          phase: "succeeded",
          job: { id: JOB, status: "succeeded", result: { ...result, ...patch } },
        }),
      );
    expect(succeeded({})).toEqual({ kind: "succeeded", freedBytes: 5e9, locked: false, failed: 0 });
    // C-5353-13: a locked volume swept nothing; failed partitions stay pending.
    expect(succeeded({ freed_bytes: 0, deleted: 0, skipped_locked: true })).toEqual({
      kind: "succeeded",
      freedBytes: 0,
      locked: true,
      failed: 0,
    });
    expect(succeeded({ failed: 2 })).toMatchObject({ kind: "succeeded", failed: 2 });
    expect(jobStateOf(view({ phase: "succeeded", job: { id: JOB, status: "succeeded" } }))).toEqual(
      {
        kind: "succeeded",
        freedBytes: null,
      },
    );
    expect(
      jobStateOf(view({ phase: "failed", job: { id: JOB, status: "failed", error: null } })),
    ).toEqual({
      kind: "failed",
      code: "failed",
    });
    expect(jobStateOf(view({ phase: "cancelled" }))).toEqual({ kind: "cancelled" });
    const route: RefusalRoute = { kind: "t4", code: "not_found", field: null, status: 404 };
    expect(jobStateOf(view({ phase: "unknown", route }))).toEqual({
      kind: "lost",
      code: "not_found",
    });
    expect(jobStateOf(view({ phase: "unknown" }))).toEqual({ kind: "lost", code: null });
  });
});
