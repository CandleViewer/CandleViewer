/**
 * E28-S01 (#971): SCR-130 (E28-D02 §5.1; E28-D03 §3.2 S130-1 … S130-9). The rows read served values
 * as text; loading, empty and error keep the header; the row menu edits, duplicates and deletes; a
 * delete is confirmed by name, challenged by the server's step-up and re-sent once, and a refusal
 * shows the served blockers. axe finds nothing serious, and the list is viewed once per visit.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JSX } from "react";
import type { ProfilesEvent } from "../../../../src/features/admin/profiles/analytics";
import {
  profilesApi,
  type AccountProfile,
  type ProfilesApi,
  type WriteOutcome,
} from "../../../../src/features/admin/profiles/api";
import { PROFILES_COPY as C } from "../../../../src/features/admin/profiles/copy";
import {
  deleteRefusalText,
  ProfilesPage,
} from "../../../../src/features/admin/profiles/ProfilesPage";
import { clearAnnouncements, ShellAnnouncer } from "../../../../src/features/app-shell/announcer";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import { ACCOUNT_IDS, account, json, stepUpBody, stored } from "./fixtures";

// axe-core is a transitive dependency of @axe-core/playwright (as in AdminArea.test.tsx).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function seriousViolations(): Promise<unknown[]> {
  // jsdom has no layout: contrast is the Playwright axe run's
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

/** A render under host load can take seconds: each wait gets 5 s, each test 30 s. */
const WAIT = { timeout: 5_000 } as const;
vi.setConfig({ testTimeout: 30_000 });
const main = account(ACCOUNT_IDS.main, "Main");
const sub1 = account(ACCOUNT_IDS.sub1, "sub_001");
const sub2 = account(ACCOUNT_IDS.sub2, "sub_002");
const mainDefault = stored(ACCOUNT_IDS.main, "Main default", { is_default: true });
const mainAlt = stored(ACCOUNT_IDS.main, "Main 0.5R");
const sub1Default = stored(ACCOUNT_IDS.sub1, "sub_001 default", { is_default: true });
const sub1Alt = stored(ACCOUNT_IDS.sub1, "sub_001 0.5R");
const sub2Default = stored(
  ACCOUNT_IDS.sub2,
  "sub_002 default",
  { is_default: true, all_symbols: true, allowed_symbols: [] },
  { warnings: [{ code: "all_symbols", estimated: false, message: "served" }] },
);

interface Fake {
  readonly api: ProfilesApi;
  readonly deletes: AccountProfile[];
  profiles: Record<string, AccountProfile[]>;
  accounts: "ok" | "failed";
  next: WriteOutcome[];
}

function fake(): Fake {
  const state: Fake = {
    deletes: [],
    accounts: "ok",
    next: [],
    profiles: {
      [main.id]: [mainAlt, mainDefault],
      [sub1.id]: [sub1Default, sub1Alt],
      [sub2.id]: [sub2Default],
    },
    api: {
      ...profilesApi,
      listAccounts: async () =>
        state.accounts === "ok"
          ? { kind: "ok", value: [main, sub1, sub2] }
          : { kind: "failed" as const },
      listProfiles: async (id) => {
        const own = state.profiles[id];
        return own === undefined ? { kind: "not_found" } : { kind: "ok", value: own };
      },
      deleteProfile: async (p) => {
        state.deletes.push(p);
        return state.next.shift() ?? { kind: "ok", profile: null, etag: null };
      },
    },
  };
  return state;
}

function Where(): JSX.Element {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderPage(state: Fake, events: ProfilesEvent[] = []): void {
  render(
    <MemoryRouter initialEntries={["/admin/profiles"]}>
      <InShellProvider>
        <ShellAnnouncer />
        <main tabIndex={-1}>
          <Routes>
            <Route
              path="/admin/profiles"
              element={<ProfilesPage api={state.api} analytics={{ emit: (e) => events.push(e) }} />}
            />
            <Route path="/admin/profiles/:profileId" element={<Where />} />
          </Routes>
        </main>
      </InShellProvider>
    </MemoryRouter>,
  );
}

const table = (): Promise<HTMLElement> => screen.findByRole("grid", { name: C.title }, WAIT);
const rowOf = (name: RegExp): HTMLElement => screen.getByRole("row", { name });

async function openRowMenu(name: RegExp): Promise<void> {
  await table();
  await waitFor(() => expect(rowOf(name)).toBeInTheDocument(), WAIT);
  fireEvent.click(within(rowOf(name)).getByRole("button", { name: /Actions for/ }));
}

beforeEach(() => {
  clearAnnouncements();
});

afterEach(() => {
  clearAnnouncements();
  vi.unstubAllGlobals();
});

describe("SCR-130 rows", () => {
  it("test_the_list_names_each_profile_with_served_values_and_no_serious_axe_issue", async () => {
    const events: ProfilesEvent[] = [];
    renderPage(fake(), events);
    expect(await screen.findByRole("heading", { level: 1, name: C.title }, WAIT)).toBeVisible();
    await table();
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(6), WAIT);
    const def = rowOf(/Main default \(v2\) · default/);
    expect(within(def).getByText("Main · DEMO")).toBeInTheDocument();
    expect(within(def).getByText("Risk-based 0.5 %")).toBeInTheDocument();
    expect(rowOf(/alternates: Main 0\.5R \(v2\)/)).toBeInTheDocument();
    expect(screen.getByText(C.defaultCeiling)).toBeInTheDocument();
    expect(events).toEqual([{ name: "profile.list_viewed", accounts: 3, profiles: 5 }]);
    expect(await seriousViolations()).toEqual([]);
  });

  it("test_all_symbols_is_flagged_in_text", async () => {
    renderPage(fake());
    await table();
    const row = await screen.findByRole("row", { name: /sub_002 default/ }, WAIT);
    expect(within(row).getByText(C.allSymbols)).toBeInTheDocument();
    expect(within(row).getByText(C.allSymbolsWarning)).toBeInTheDocument();
  });

  it("test_no_accounts_shows_the_empty_state", async () => {
    const state = fake();
    renderPage({
      ...state,
      api: { ...state.api, listAccounts: async () => ({ kind: "ok", value: [] }) },
    });
    expect(await screen.findByText(C.empty, {}, WAIT)).toBeInTheDocument();
  });

  it("test_a_failed_read_offers_retry_and_retry_reads_again", async () => {
    const state = fake();
    state.accounts = "failed";
    renderPage(state);
    expect((await screen.findAllByText(C.loadFailed, {}, WAIT))[0]).toBeInTheDocument();
    state.accounts = "ok";
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(6), WAIT);
    // the Retry button left with the error state, so focus lands on the heading, not `body`
    await waitFor(
      () => expect(screen.getByRole("heading", { level: 1, name: C.title })).toHaveFocus(),
      WAIT,
    );
  });
});

describe("SCR-130 row menu", () => {
  it("test_edit_opens_r331_with_the_account_in_the_query", async () => {
    renderPage(fake());
    await openRowMenu(/sub_001 default/);
    fireEvent.click(await screen.findByRole("menuitem", { name: C.edit }, WAIT));
    expect(await screen.findByTestId("where", {}, WAIT)).toHaveTextContent(
      `/admin/profiles/${sub1Default.id}?account=${sub1.id}`,
    );
  });

  it("test_duplicate_opens_a_new_alternate_from_the_row", async () => {
    renderPage(fake());
    await openRowMenu(/sub_001 default/);
    fireEvent.click(await screen.findByRole("menuitem", { name: C.duplicate }, WAIT));
    expect(await screen.findByTestId("where", {}, WAIT)).toHaveTextContent(
      `/admin/profiles/new?account=${sub1.id}&from=${sub1Default.id}`,
    );
  });
});

describe("SCR-130 delete", () => {
  async function askToDelete(): Promise<HTMLElement> {
    await openRowMenu(/sub_001 0\.5R/);
    fireEvent.click(await screen.findByRole("menuitem", { name: new RegExp(C.delete) }, WAIT));
    const dialog = await screen.findByRole("alertdialog", {}, WAIT);
    // CMP-044 ignores a press in its first 400 ms (its misfire guard): the clock moves past it.
    const opened = performance.now();
    vi.spyOn(performance, "now").mockImplementation(() => opened + 1_000);
    return dialog;
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("test_the_confirm_names_the_account_and_the_profile_and_cancel_sends_nothing", async () => {
    const state = fake();
    renderPage(state);
    const dialog = await askToDelete();
    expect(dialog).toHaveAccessibleName(C.confirmDelete("sub_001", "sub_001 0.5R"));
    fireEvent.click(within(dialog).getByRole("button", { name: C.cancel }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), WAIT);
    expect(state.deletes).toEqual([]);
  });

  it("test_a_delete_announces_and_reads_the_list_again", async () => {
    const state = fake();
    renderPage(state);
    const dialog = await askToDelete();
    state.profiles[sub1.id] = [sub1Default];
    fireEvent.click(within(dialog).getByRole("button", { name: C.delete }));
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(5), WAIT);
    expect(state.deletes.map((p) => p.id)).toEqual([sub1Alt.id]);
    expect(
      await screen.findByText(C.deleted("sub_001 0.5R", "sub_001"), {}, WAIT),
    ).toBeInTheDocument();
  });

  it("test_a_409_shows_the_served_blockers_in_the_dialog", async () => {
    const state = fake();
    state.next.push({
      kind: "refused",
      refusal: {
        status: 409,
        code: "conflict",
        detail: "an armed rule covers this account: Breakout (r-7)",
        errors: [],
      },
    });
    const events: ProfilesEvent[] = [];
    renderPage(state, events);
    const dialog = await askToDelete();
    fireEvent.click(within(dialog).getByRole("button", { name: C.delete }));
    expect(
      await within(dialog).findByText(
        "Can't delete: an armed rule covers this account: Breakout (r-7)",
        {},
        WAIT,
      ),
    ).toBeInTheDocument();
    expect(events).toContainEqual({
      name: "profile.write_refused",
      operation: "delete",
      code: "conflict",
    });
  });

  it("test_a_step_up_challenge_is_answered_and_the_held_delete_is_re_sent_once", async () => {
    const state = fake();
    const hold = await profilesApi.readWrite(json(403, stepUpBody()), {
      method: "DELETE",
      url: "/api/v1/x",
      headers: [["If-Match", 'W/"x:2"']],
      body: null,
    });
    if (hold.kind !== "step_up") throw new Error("expected a hold");
    state.next.push(hold);
    const sent: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: RequestInfo | URL) => {
        sent.push(String(url));
        return String(url).endsWith("/auth/step-up")
          ? json(200, { elevated_until: "2026-11-03T10:40:00Z", action_class: "risk_caps" })
          : json(204, null);
      }),
    );
    renderPage(state);
    const dialog = await askToDelete();
    fireEvent.click(within(dialog).getByRole("button", { name: C.delete }));
    const password = await screen.findByLabelText("Password", {}, WAIT);
    const stepUp = password.closest("[role=alertdialog]") as HTMLElement;
    expect(stepUp).toHaveTextContent("Delete sub_001's profile 'sub_001 0.5R'");
    fireEvent.change(password, { target: { value: "pw" } });
    fireEvent.change(within(stepUp).getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    await act(async () => {
      fireEvent.submit(password.closest("form") as HTMLFormElement);
    });
    await waitFor(() => expect(sent).toEqual(["/api/v1/auth/step-up", "/api/v1/x"]), WAIT);
    expect(
      await screen.findByText(C.deleted("sub_001 0.5R", "sub_001"), {}, WAIT),
    ).toBeInTheDocument();
  });
});

describe("SCR-130 delete outcomes", () => {
  async function confirmWith(outcome: WriteOutcome): Promise<{ state: Fake; dialog: HTMLElement }> {
    const state = fake();
    state.next.push(outcome);
    renderPage(state);
    await openRowMenu(/sub_001 0\.5R/);
    fireEvent.click(await screen.findByRole("menuitem", { name: new RegExp(C.delete) }, WAIT));
    const dialog = await screen.findByRole("alertdialog", {}, WAIT);
    const opened = performance.now();
    vi.spyOn(performance, "now").mockImplementation(() => opened + 1_000);
    fireEvent.click(within(dialog).getByRole("button", { name: C.delete }));
    return { state, dialog };
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("test_no_answer_closes_the_confirm_and_reads_the_list_back", async () => {
    await confirmWith({ kind: "unknown" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), WAIT);
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(6), WAIT);
  });

  it("test_a_412_reads_the_version_conflict_words", async () => {
    const { dialog } = await confirmWith({
      kind: "refused",
      refusal: { status: 412, code: "version_conflict", detail: null, errors: [] },
    });
    expect(await within(dialog).findByText(C.versionConflict, {}, WAIT)).toBeInTheDocument();
  });

  it("test_a_412_reads_the_list_again_and_a_second_delete_sends_the_new_version", async () => {
    const state = fake();
    state.next.push({
      kind: "refused",
      refusal: { status: 412, code: "version_conflict", detail: null, errors: [] },
    });
    renderPage(state);
    await openRowMenu(/sub_001 0\.5R/);
    fireEvent.click(await screen.findByRole("menuitem", { name: new RegExp(C.delete) }, WAIT));
    const dialog = await screen.findByRole("alertdialog", {}, WAIT);
    const opened = performance.now();
    vi.spyOn(performance, "now").mockImplementation(() => opened + 1_000);
    // another session saved v3 meanwhile
    state.profiles[sub1.id] = [sub1Default, { ...sub1Alt, version: 3 }];
    fireEvent.click(within(dialog).getByRole("button", { name: C.delete }));
    expect(await within(dialog).findByText(C.versionConflict, {}, WAIT)).toBeInTheDocument();
    await waitFor(() => {
      fireEvent.click(within(dialog).getByRole("button", { name: C.delete }));
      expect(state.deletes).toHaveLength(2);
    }, WAIT);
    expect(state.deletes.map((p) => p.version)).toEqual([2, 3]);
  });

  it("test_a_409_with_no_readable_detail_names_the_code_not_a_guessed_blocker", async () => {
    const { dialog } = await confirmWith({
      kind: "refused",
      refusal: { status: 409, code: "conflict", detail: null, errors: [] },
    });
    expect(
      await within(dialog).findByText("Nothing was deleted (conflict).", {}, WAIT),
    ).toBeInTheDocument();
  });

  it("test_no_answer_says_the_outcome_is_pending_on_the_list", async () => {
    await confirmWith({ kind: "unknown" });
    expect(
      await screen.findByText(`Outcome pending, see ${C.title}`, {}, WAIT),
    ).toBeInTheDocument();
  });

  it("test_the_confirm_shows_the_accounts_served_environment", async () => {
    const { dialog } = await confirmWith({
      kind: "refused",
      refusal: { status: 404, code: "not_found", detail: null, errors: [] },
    });
    expect(within(dialog).getByText("sub_001 · DEMO")).toBeInTheDocument();
  });
});

describe("SCR-130 empty and partial reads", () => {
  it("test_accounts_with_no_readable_profile_do_not_read_as_no_accounts", async () => {
    const state = fake();
    state.profiles = {};
    renderPage(state);
    expect((await screen.findAllByText(C.loadFailed, {}, WAIT))[0]).toBeInTheDocument();
    expect(screen.queryByText(C.empty)).toBeNull();
  });
});

describe("SCR-130 step-up renewal", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("test_an_expired_challenge_renews_with_a_fresh_delete_and_a_new_challenge", async () => {
    const state = fake();
    const held = { method: "DELETE", url: "/api/v1/x", headers: [], body: null } as const;
    const expired = await profilesApi.readWrite(
      json(403, {
        ...stepUpBody("11111111-1111-4111-8111-111111111111"),
        challenge_expires_at: "2026-01-01T00:00:00Z",
      }),
      held,
    );
    const fresh = await profilesApi.readWrite(
      json(403, stepUpBody("22222222-2222-4222-8222-222222222222")),
      held,
    );
    if (expired.kind !== "step_up" || fresh.kind !== "step_up") throw new Error("expected holds");
    state.next.push(expired, fresh);
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
        if (String(url).endsWith("/auth/step-up")) bodies.push(String(init?.body));
        return json(401, { code: "mfa_invalid" });
      }),
    );
    renderPage(state);
    await openRowMenu(/sub_001 0\.5R/);
    fireEvent.click(await screen.findByRole("menuitem", { name: new RegExp(C.delete) }, WAIT));
    const dialog = await screen.findByRole("alertdialog", {}, WAIT);
    const opened = performance.now();
    vi.spyOn(performance, "now").mockImplementation(() => opened + 1_000);
    fireEvent.click(within(dialog).getByRole("button", { name: C.delete }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Request a new confirmation" }, WAIT),
    );
    const password = await screen.findByLabelText("Password", {}, WAIT);
    expect(state.deletes).toHaveLength(2);
    fireEvent.change(password, { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    await act(async () => {
      fireEvent.submit(password.closest("form") as HTMLFormElement);
    });
    await waitFor(() => expect(bodies).toHaveLength(1), WAIT);
    expect(bodies[0]).toContain("22222222-2222-4222-8222-222222222222");
  });
});

/**
 * Enter on a focused native button: the key reaches its handlers, then the browser's activation
 * (a click), which jsdom does not synthesize (`@testing-library/user-event` is not an `apps/web`
 * dependency; the Playwright spec presses the real key).
 */
function pressEnter(button: HTMLElement): void {
  act(() => button.focus());
  expect(button).toHaveFocus();
  if (fireEvent.keyDown(button, { key: "Enter" })) fireEvent.click(button);
}

describe("SCR-130 keyboard and focus", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Keyboard only: the grid's roving focus rests on the row's menu button (CMP-049 owns the arrow
   * keys and the single tab stop), Shift+F10 opens the row menu, End + Enter picks Delete.
   */
  async function deleteByKeyboard(
    name: RegExp,
  ): Promise<{ trigger: HTMLElement; dialog: HTMLElement }> {
    await table();
    await waitFor(() => expect(rowOf(name)).toBeInTheDocument(), WAIT);
    const trigger = within(rowOf(name)).getByRole("button", { name: /Actions for/ });
    act(() => trigger.focus());
    fireEvent.keyDown(trigger, { key: "F10", shiftKey: true });
    const menu = await screen.findByRole("menu", {}, WAIT);
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toHaveAccessibleName(new RegExp(C.delete));
    fireEvent.keyDown(menu, { key: "Enter" });
    const dialog = await screen.findByRole("alertdialog", {}, WAIT);
    const opened = performance.now();
    vi.spyOn(performance, "now").mockImplementation(() => opened + 1_000);
    return { trigger, dialog };
  }

  it("test_esc_on_the_confirm_sends_nothing_and_returns_focus_to_the_rows_menu_button", async () => {
    const state = fake();
    renderPage(state);
    const { trigger } = await deleteByKeyboard(/sub_001 0\.5R/);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull(), WAIT);
    expect(state.deletes).toEqual([]);
    await waitFor(() => expect(trigger).toHaveFocus(), WAIT);
  });

  it("test_a_keyboard_delete_lands_focus_on_the_page_heading", async () => {
    const state = fake();
    renderPage(state);
    const { dialog } = await deleteByKeyboard(/sub_001 0\.5R/);
    state.profiles[sub1.id] = [sub1Default];
    const confirm = within(dialog).getByRole("button", { name: C.delete });
    pressEnter(confirm);
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(5), WAIT);
    await waitFor(() => expect(document.activeElement?.id).toBe("scr-130-title"), WAIT);
  });

  it("test_esc_on_the_step_up_sends_no_held_request_and_keeps_focus_on_the_page", async () => {
    const state = fake();
    const hold = await profilesApi.readWrite(json(403, stepUpBody()), {
      method: "DELETE",
      url: "/api/v1/x",
      headers: [],
      body: null,
    });
    if (hold.kind !== "step_up") throw new Error("expected a hold");
    state.next.push(hold);
    const sent = vi.fn(async () => json(204, null));
    vi.stubGlobal("fetch", sent);
    renderPage(state);
    const { dialog } = await deleteByKeyboard(/sub_001 0\.5R/);
    const confirm = within(dialog).getByRole("button", { name: C.delete });
    pressEnter(confirm);
    await screen.findByLabelText("Password", {}, WAIT);
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByLabelText("Password")).toBeNull(), WAIT);
    expect(sent).not.toHaveBeenCalled();
    expect(await screen.findByText("Not sent", {}, WAIT)).toBeInTheDocument();
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("main")).toContainElement(document.activeElement as HTMLElement);
  });
});

describe("deleteRefusalText", () => {
  it("test_each_served_code_reads_its_deck_row", () => {
    const r = (status: number, code: string, detail: string | null = null) =>
      deleteRefusalText({ status, code, detail, errors: [] });
    expect(r(409, "conflict", "make another profile the default first")).toBe(
      "Can't delete: make another profile the default first",
    );
    // no readable detail: the served code, never a guessed blocker (an armed rule may be one)
    expect(r(409, "conflict")).toBe("Nothing was deleted (conflict).");
    expect(r(412, "version_conflict")).toBe(C.versionConflict);
    expect(r(503, "audit_unavailable")).toBe(C.auditUnavailable);
    expect(r(404, "not_found")).toBe("Nothing was deleted (not_found).");
  });
});
