import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  ChangePasswordScreen,
  PW_COPY,
  rateLine,
} from "../../src/features/auth/ChangePasswordScreen";
import { changePassword } from "../../src/features/auth/authApi";
import { accessToken } from "../../src/lib/auth/accessToken";
import { apiFetch } from "../../src/lib/http/csrfFetch";
import {
  containsIdentity,
  evaluate,
  meterWord,
  strengthScore,
} from "../../src/features/auth/password/policy";

// E09-D05 (the hi-fi delta of hand-off §D) on SCR-004, and the #2110 client: outcomes by problem
// code, the `200`'s rotated token held, the checklist, meter, W-13 clearing and the success card.

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function serious(): Promise<unknown[]> {
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

const reply = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
const problem = (status: number, code: string, extra: Record<string, unknown> = {}): Response =>
  reply(status, {
    type: "about:blank",
    title: "t",
    status,
    detail: "a server sentence",
    code,
    ...extra,
  });
const TOKEN = "rotated-token-after-password-change";
const changed = (): Response =>
  reply(200, {
    status: "password_changed",
    tokens: { access_token: TOKEN, token_type: "Bearer", expires_in: 720, refresh_token: null },
  });

const GOOD = "correct horse battery staple";
const HELD = {
  access_token: "held-before-the-change",
  token_type: "Bearer" as const,
  expires_in: 600,
};
let fetchMock: ReturnType<typeof vi.fn>;
let assign: ReturnType<typeof vi.fn>;

const ORIGIN = window.location.origin; // the jsdom page's, so `apiFetch` sees the API as same-origin

beforeEach(() => {
  assign = vi.fn();
  vi.stubGlobal("location", {
    origin: ORIGIN,
    pathname: "/login/change-password",
    search: "",
    hash: "",
    href: `${ORIGIN}/login/change-password`,
    assign,
  });
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  accessToken.clear();
});

const field = (name: string): HTMLInputElement => screen.getByLabelText(name) as HTMLInputElement;
function fill(current: string, next: string, confirm = next): void {
  fireEvent.change(field(PW_COPY.current), { target: { value: current } });
  fireEvent.change(field(PW_COPY.next), { target: { value: next } });
  fireEvent.change(field(PW_COPY.confirm), { target: { value: confirm } });
}
const press = (): void => {
  fireEvent.click(screen.getByRole("button", { name: /Change password|Changing password/ }));
};
const item = (label: RegExp): HTMLElement =>
  within(screen.getByRole("list", { name: "Password requirements" }))
    .getByText(label)
    .closest("li") as HTMLElement;

describe("the policy the client evaluates (E09-D05 §4)", () => {
  it("counts length in code points and caps the meter at Weak below 14", () => {
    const astral = "😀".repeat(13) + "a";
    expect(evaluate(astral, astral, undefined, {})[0]?.state).toBe("met");
    expect(evaluate("😀".repeat(13), "", undefined, {})[0]?.state).toBe("not-met");
    expect(meterWord(4, false)).toBe("Weak");
    expect([0, 1, 2, 3, 4].map((s) => meterWord(s as 0, true))).toEqual([
      "Weak",
      "Weak",
      "Fair",
      "Strong",
      "Strong",
    ]);
  });

  it("scores few distinct characters 0 and longer mixed passwords higher", () => {
    expect(strengthScore("aaaaaaaaaaaaaaaaaaaa")).toBe(0);
    expect(strengthScore("abcdefgh")).toBe(1);
    expect(strengthScore("abcdefghijklmn")).toBe(2);
    expect(strengthScore("Abcdefghijklmnopqr1!")).toBe(4);
  });

  it("reads the identity rule as the server does (3 characters or more, case-insensitive)", () => {
    const id = { username: "Ann", email: "jo@example.test" };
    expect(containsIdentity("xxannxx", id)).toBe(true);
    expect(containsIdentity("xxJOxx", id)).toBe(false); // the local part is under 3
    expect(containsIdentity("xxexamplexx", id)).toBe(false); // only the local part counts
    expect(containsIdentity("xxBOBxx", { username: "bob", email: "" })).toBe(true);
  });

  it("never shows a server item met before the server answers", () => {
    const states = evaluate(GOOD, GOOD, undefined, {}).map((i) => [i.id, i.state]);
    expect(states).toEqual([
      ["length", "met"],
      ["breach", "server"],
      ["reuse", "server"],
      ["match", "met"],
      ["identity", "server"],
    ]);
    const refused = evaluate("", "", undefined, { breach: true, reuse: true, identity: true });
    expect(refused.filter((i) => i.state === "not-met").map((i) => i.id)).toEqual([
      "length",
      "breach",
      "reuse",
      "match",
      "identity",
    ]);
  });
});

describe("changePassword maps by problem code, never by detail (E09-D05 §6.1)", () => {
  it.each([
    [problem(403, "current_password_invalid"), { kind: "current_invalid" }],
    [problem(409, "conflict"), { kind: "current_invalid" }],
    [problem(422, "password_breached"), { kind: "refused", reason: "breached" }],
    [problem(422, "password_reused"), { kind: "refused", reason: "reused" }],
    [
      problem(422, "password_policy", { errors: [{ field: "new_password", rule: "min_length" }] }),
      { kind: "refused", reason: "too_short" },
    ],
    [
      problem(422, "password_policy", {
        errors: [{ field: "new_password", rule: "contains_identity" }],
      }),
      { kind: "refused", reason: "identity" },
    ],
    [problem(422, "password_policy"), { kind: "refused", reason: "other" }],
    [
      problem(422, "validation_failed", {
        errors: [{ field: "new_password", rule: "max_length" }],
      }),
      { kind: "refused", reason: "too_long" },
    ],
    [problem(422, "validation_failed"), { kind: "refused", reason: "other" }],
    [problem(403, "session_read_only"), { kind: "read_only" }],
    [problem(403, "mfa_enrollment_required"), { kind: "enrolment_required" }],
    [problem(403, "view_as_read_only"), { kind: "not_allowed" }],
    [
      problem(422, "validation_failed", {
        errors: [{ field: "current_password", rule: "max_length" }],
      }),
      { kind: "current_invalid" },
    ],
    [problem(401, "session_revoked"), { kind: "signed_out" }],
    [problem(401, "session_idle_locked"), { kind: "locked" }],
    [problem(503, "audit_unavailable"), { kind: "unreachable" }],
    [problem(503, "store_unavailable"), { kind: "sign_in_again" }],
    [reply(422, "not json"), { kind: "refused", reason: "other" }],
  ])("%#", async (res, outcome) => {
    fetchMock.mockResolvedValueOnce(res);
    expect(await changePassword("old", GOOD)).toEqual(outcome);
  });

  it("a detail that names a rule decides nothing", async () => {
    fetchMock.mockResolvedValueOnce(
      reply(422, { code: "validation_failed", detail: "reuse breach previous" }),
    );
    expect(await changePassword("old", GOOD)).toEqual({ kind: "refused", reason: "other" });
  });

  it("a 429 counts down from Retry-After; a network failure is unreachable", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("{}", { status: 429, headers: { "Retry-After": "47" } }),
    );
    expect(await changePassword("old", GOOD)).toEqual({ kind: "rate_limited", retryAfterS: 47 });
    fetchMock.mockRejectedValueOnce(new Error("down"));
    expect(await changePassword("old", GOOD)).toEqual({ kind: "unreachable" });
  });

  it("the 200 holds the rotated session's access token and sends the contract body", async () => {
    fetchMock.mockResolvedValueOnce(changed());
    expect(await changePassword("pw-old", GOOD)).toEqual({ kind: "changed" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/password");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({
      current_password: "pw-old",
      new_password: GOOD,
    });
    await expect(accessToken.getToken()).resolves.toMatchObject({ kind: "ok", accessToken: TOKEN });
  });

  it("the next call after the 200 carries the rotated token, not the one held before", async () => {
    accessToken.set(HELD);
    fetchMock.mockResolvedValueOnce(changed()).mockResolvedValueOnce(reply(200, {}));
    await changePassword("pw-old", GOOD);
    await apiFetch("/api/v1/auth/session", { method: "GET" });
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(`Bearer ${TOKEN}`);
  });

  it("a 401 session_idle_locked is reported to SCR-005's listeners and ends nothing", async () => {
    accessToken.set(HELD);
    const heard = vi.fn();
    const stop = accessToken.onLocked(heard);
    const end = vi.spyOn(accessToken, "endSession");
    fetchMock.mockResolvedValueOnce(problem(401, "session_idle_locked"));
    expect(await changePassword("pw-old", GOOD)).toEqual({ kind: "locked" });
    stop();
    expect(heard).toHaveBeenCalledTimes(1);
    expect(end).not.toHaveBeenCalled();
  });
});

describe("ChangePasswordScreen (SCR-004, E09-D05)", () => {
  it("lays out all five items at mount with their states, and is axe clean", async () => {
    render(<ChangePasswordScreen />);
    expect(screen.getByRole("heading", { level: 1, name: PW_COPY.heading })).toBeTruthy();
    expect(screen.getByText(PW_COPY.explanation)).toBeTruthy();
    const list = screen.getByRole("list", { name: "Password requirements" });
    expect(list).not.toHaveAttribute("aria-live"); // one status node instead (C-8)
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((li) => li.textContent?.trim()),
    ).toEqual([
      "≥14 chars, not met",
      "not in breach list (checked when you submit)",
      "not equal to previous 5 (checked when you submit)",
      "must match confirmation, not met",
      "Doesn't contain your username or email (checked when you submit)",
    ]);
    expect(screen.getByText(/^Strength: Weak/)).toBeTruthy();
    expect(field(PW_COPY.next)).toHaveAccessibleDescription(/≥14 chars.*Strength: Weak/);
    expect(await serious()).toEqual([]);
  });

  it("paints the card the checklist and meter text tokens are measured on (§13.1, P-1, P-2)", () => {
    render(<ChangePasswordScreen />);
    const main = screen.getByRole("main");
    expect(main.style.background).toBe("var(--color-surface-raised)");
    expect(main.style.color).toBe("var(--color-text-primary)");
    expect(main.contains(screen.getByRole("list", { name: "Password requirements" }))).toBe(true);
    expect(main.contains(screen.getByText(/^Strength: Weak/))).toBe(true);
  });

  it("evaluates the identity item when the host knows the user", () => {
    render(<ChangePasswordScreen identity={{ username: "annie", email: "ann@x.test" }} />);
    fill("old", "my annie password 1");
    expect(item(/Doesn't contain/).textContent).toMatch(/, not met$/);
    fill("old", GOOD);
    expect(item(/Doesn't contain/).textContent).toMatch(/, met$/);
    press();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refuses a client-side identity match without a request", () => {
    render(<ChangePasswordScreen identity={{ username: "annie", email: "ann@x.test" }} />);
    fill("old", "my annie password 1");
    press();
    expect(field(PW_COPY.next)).toHaveAccessibleDescription(/Doesn't contain your username/);
    expect(field(PW_COPY.next)).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("the status node speaks only the changed items and the meter, 500 ms after typing", () => {
    vi.useFakeTimers();
    render(<ChangePasswordScreen />);
    const status = screen
      .getAllByRole("status")
      .find((n) => n.getAttribute("aria-atomic") === "true") as HTMLElement;
    fireEvent.change(field(PW_COPY.next), { target: { value: "abcdefghijklm" } });
    fireEvent.change(field(PW_COPY.next), { target: { value: "abcdefghijklmn" } });
    act(() => vi.advanceTimersByTime(499));
    expect(status).toBeEmptyDOMElement();
    act(() => vi.advanceTimersByTime(1));
    expect(status).toHaveTextContent("≥14 chars: met. Strength: Fair");
    fireEvent.change(field(PW_COPY.confirm), { target: { value: "abcdefghijklmn" } });
    act(() => vi.advanceTimersByTime(500));
    expect(status).toHaveTextContent(/^must match confirmation: met$/);
  });

  it("each field has its own reveal, one constant name, reset after a submit", () => {
    render(<ChangePasswordScreen />);
    const reveals = screen.getAllByRole("button", { name: "Show password" });
    expect(reveals).toHaveLength(3);
    fireEvent.click(reveals[1] as HTMLElement);
    expect(reveals[1]).toHaveAttribute("aria-pressed", "true");
    expect(field(PW_COPY.next).type).toBe("text");
    expect(field(PW_COPY.current).type).toBe("password");
    expect(screen.getAllByRole("button", { name: "Show password" })).toHaveLength(3);
    press();
    expect(reveals[1]).toHaveAttribute("aria-pressed", "false");
    expect(field(PW_COPY.next).type).toBe("password");
  });

  it("says Caps Lock is on for the focused field only", () => {
    render(<ChangePasswordScreen />);
    const input = field(PW_COPY.current);
    fireEvent.keyDown(input, { key: "A", modifierCapsLock: true });
    expect(input).toHaveAccessibleDescription(/Caps Lock is on\./);
    fireEvent.blur(input);
    expect(input).not.toHaveAccessibleDescription(/Caps Lock/);
  });

  it("a press with unmet items marks each failing field and focuses the first", async () => {
    render(<ChangePasswordScreen />);
    fill("", "short", "other");
    press();
    expect(field(PW_COPY.current)).toHaveFocus();
    expect(field(PW_COPY.current)).toHaveAccessibleDescription(
      /Your current password is incorrect/,
    );
    expect(field(PW_COPY.next)).toHaveAttribute("aria-invalid", "true");
    expect(field(PW_COPY.next)).toHaveAccessibleDescription(/Use at least 14 characters\./);
    expect(field(PW_COPY.confirm)).toHaveAccessibleDescription(/Passwords don't match\./);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await serious()).toEqual([]);
  });

  it("the mismatch shows on the confirm field's blur, never while it is typed into", () => {
    render(<ChangePasswordScreen />);
    fill("old", GOOD, "correct horse");
    expect(field(PW_COPY.confirm)).not.toHaveAttribute("aria-invalid");
    fireEvent.blur(field(PW_COPY.confirm));
    expect(field(PW_COPY.confirm)).toHaveAccessibleDescription(/Passwords don't match\./);
    fireEvent.change(field(PW_COPY.confirm), { target: { value: GOOD } });
    expect(field(PW_COPY.confirm)).not.toHaveAttribute("aria-invalid");
  });

  it.each([
    ["password_breached", {}, PW_COPY.breached, /not in breach list/],
    ["password_reused", {}, PW_COPY.reused, /not equal to previous 5/],
    [
      "password_policy",
      { errors: [{ field: "new_password", rule: "contains_identity" }] },
      PW_COPY.identity,
      /Doesn't contain/,
    ],
    [
      "password_policy",
      { errors: [{ field: "new_password", rule: "min_length" }] },
      PW_COPY.tooShort,
      /≥14 chars/,
    ],
    [
      "validation_failed",
      { errors: [{ field: "new_password", rule: "max_length" }] },
      PW_COPY.tooLong,
      null,
    ],
    ["password_policy", {}, PW_COPY.refused, null],
  ])(
    "a 422 %s clears both new fields, says W-13 and marks the item",
    async (code, extra, copy, label) => {
      fetchMock.mockResolvedValueOnce(problem(422, code, extra));
      accessToken.set(HELD); // BQ-225: a refusal leaves the session signed in
      render(<ChangePasswordScreen />);
      fill("pw-old", GOOD);
      press();
      const next = field(PW_COPY.next);
      await waitFor(() => expect(next).toHaveFocus());
      expect(next.value).toBe("");
      expect(field(PW_COPY.confirm).value).toBe("");
      expect(field(PW_COPY.current).value).toBe("pw-old");
      expect(next).toHaveAttribute("aria-invalid", "true");
      expect(next).toHaveAccessibleDescription(new RegExp(`^${copy}.*${PW_COPY.cleared}`, "u"));
      expect(screen.queryByText("a server sentence")).toBeNull(); // never the raw detail
      await expect(accessToken.getToken()).resolves.toMatchObject({
        accessToken: HELD.access_token,
      });
      if (label !== null) expect(item(label).textContent).toMatch(/, not met$/);
      expect(await serious()).toEqual([]);
      fireEvent.change(next, { target: { value: "x" } });
      expect(next).not.toHaveAttribute("aria-invalid");
      expect(screen.queryByText(PW_COPY.cleared)).toBeNull();
      if (label !== null && label.source !== "≥14 chars") {
        expect(item(label).textContent).not.toMatch(/, not met$/);
      }
    },
  );

  it("puts initial focus on the current-password field at mount (§9.1)", () => {
    render(<ChangePasswordScreen />);
    expect(field(PW_COPY.current)).toHaveFocus();
  });

  it.each([
    [422, PW_COPY.refused],
    [403, PW_COPY.refused],
    [503, PW_COPY.unreachable],
  ])(
    "an undeclared %s code takes the generic outcome and never shows detail",
    async (status, copy) => {
      fetchMock.mockImplementation(() =>
        Promise.resolve(problem(status, "a_code_nobody_declared")),
      );
      render(<ChangePasswordScreen />);
      fill("pw-old", GOOD);
      press();
      await waitFor(() => expect(screen.getAllByText(copy).length).toBeGreaterThan(0));
      expect(screen.queryByText("a server sentence")).toBeNull();
      expect(document.body.textContent).not.toContain("a server sentence");
    },
  );

  it("a 403 csrf_token_invalid that survives apiFetch's retry is the W-18 outcome", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(problem(403, "csrf_token_invalid")));
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(PW_COPY.unreachable));
    expect(screen.queryByText("a server sentence")).toBeNull();
    expect(field(PW_COPY.next).value).toBe(GOOD); // kept, so Retry can send it again
  });

  it("never leaks a password to the console, web storage or the URL across a full cycle", async () => {
    const CUR = "leak-probe-current-Aq93!x";
    const NEW = "leak-probe-new-Zk71#long-enough";
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const replies = [
      problem(422, "password_breached"),
      problem(403, "current_password_invalid"),
      problem(422, "password_policy"),
      changed(),
    ];
    fetchMock.mockImplementation(() => Promise.resolve(replies.shift() ?? changed()));
    render(<ChangePasswordScreen />);
    for (let i = 0; i < 4; i += 1) {
      fill(CUR, NEW);
      press();
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(i + 1));
      await waitFor(() => expect(screen.queryByText(/Changing password/)).toBeNull());
    }
    const seen = [
      ...spies.flatMap((s) => s.mock.calls.map((c) => JSON.stringify(c))),
      JSON.stringify({ ...window.localStorage }),
      JSON.stringify({ ...window.sessionStorage }),
      window.location.href,
      JSON.stringify(assign.mock.calls), // every navigation the screen asked for (location is stubbed)
      JSON.stringify(window.history.state),
      document.cookie,
    ].join("\n");
    for (const secret of [CUR, NEW]) expect(seen).not.toContain(secret);
  });

  it("a wrong current password clears only that field and focuses it (W-16)", async () => {
    fetchMock.mockResolvedValueOnce(problem(403, "current_password_invalid"));
    accessToken.set(HELD); // BQ-225: a refusal leaves the session signed in
    render(<ChangePasswordScreen />);
    fill("pw-wrong", GOOD);
    press();
    const current = field(PW_COPY.current);
    await waitFor(() => expect(current).toHaveFocus());
    expect(current.value).toBe("");
    expect(current).toHaveAccessibleDescription(/^Your current password is incorrect\./);
    expect(field(PW_COPY.next).value).toBe(GOOD);
    await expect(accessToken.getToken()).resolves.toMatchObject({ accessToken: HELD.access_token });
    expect(await serious()).toEqual([]);
  });

  it("busy keeps the submit focusable with W-19, the fields read-only, and adds W-20 at 5 s", async () => {
    vi.useFakeTimers();
    let answer: (res: Response) => void = () => undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((r) => (answer = r)));
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    const submit = screen.getByRole("button", { name: PW_COPY.busy });
    expect(submit).toHaveAttribute("aria-disabled", "true");
    expect(submit).not.toBeDisabled();
    expect(field(PW_COPY.next)).toHaveAttribute("readonly");
    expect(screen.getByRole("main").querySelector("form")).toHaveAttribute("aria-busy", "true");
    press(); // a second press sends nothing
    expect(fetchMock).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByText(PW_COPY.slow)).toBeTruthy();
    await act(async () => answer(problem(422, "password_reused")));
    expect(screen.queryByText(PW_COPY.slow)).toBeNull();
  });

  it("a 429 shows W-17 once in the alert, counts down from Retry-After and holds the submit", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValueOnce(
      new Response("{}", { status: 429, headers: { "Retry-After": "47" } }),
    );
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    const alert = screen.getByRole("alert");
    await waitFor(() => expect(alert).toHaveFocus());
    expect(alert).toHaveTextContent(rateLine(47));
    expect(rateLine(47)).toBe("Too many attempts. Try again in 00:47.");
    expect(field(PW_COPY.current).value).toBe("pw-old"); // kept
    const submit = screen.getByRole("button", { name: PW_COPY.submit });
    expect(submit).toHaveAttribute("aria-disabled", "true");
    expect(submit).toHaveAccessibleDescription(rateLine(47)); // G-T2.3: the reason, linked
    act(() => vi.advanceTimersByTime(1_000));
    press(); // changes nothing and says why once, politely
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const polite = screen
      .getAllByRole("status")
      .find((n) => n.getAttribute("aria-atomic") === "true") as HTMLElement;
    expect(polite).toHaveTextContent(rateLine(46));
    act(() => vi.advanceTimersByTime(1_000));
    expect(alert.querySelector("[aria-hidden]")).toHaveTextContent("00:45");
    expect(alert.querySelector(".cv-visually-hidden")).toHaveTextContent("00:47"); // spoken once
    act(() => vi.advanceTimersByTime(45_000));
    expect(alert).toBeEmptyDOMElement();
    expect(submit).toHaveAttribute("aria-disabled", "false");
    expect(submit).not.toHaveAccessibleDescription(rateLine(0));
  });

  it("unreachable shows W-18 with Retry, which sends the kept values again", async () => {
    fetchMock.mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce(changed());
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveFocus());
    expect(screen.getByRole("alert")).toHaveTextContent(PW_COPY.unreachable);
    for (const name of [PW_COPY.current, PW_COPY.next, PW_COPY.confirm]) {
      expect(field(name)).not.toHaveAttribute("aria-invalid");
    }
    fireEvent.click(screen.getByRole("button", { name: PW_COPY.retry }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: PW_COPY.doneHeading })).toHaveFocus(),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("an audit_unavailable 503 changed nothing: W-18 with Retry", async () => {
    fetchMock.mockResolvedValueOnce(problem(503, "audit_unavailable"));
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(PW_COPY.unreachable));
    expect(screen.getByRole("button", { name: PW_COPY.retry })).toBeTruthy();
  });

  it("a store_unavailable 503 may follow the commit: no Retry, the client signs in again", async () => {
    const end = vi.spyOn(accessToken, "endSession").mockImplementation(() => undefined);
    fetchMock.mockResolvedValueOnce(problem(503, "store_unavailable"));
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    await waitFor(() => expect(end).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: PW_COPY.retry })).toBeNull();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    expect(field(PW_COPY.current).value).toBe("");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("an idle lock hands over to SCR-005: nothing ends, no password stays typed", async () => {
    const end = vi.spyOn(accessToken, "endSession").mockImplementation(() => undefined);
    fetchMock.mockResolvedValueOnce(problem(401, "session_idle_locked"));
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    await waitFor(() => expect(field(PW_COPY.current).value).toBe(""));
    expect(field(PW_COPY.next).value).toBe("");
    expect(field(PW_COPY.confirm).value).toBe("");
    expect(end).not.toHaveBeenCalled();
  });

  it("success is the card: the session stays signed in and Continue goes to the shell", async () => {
    fetchMock.mockResolvedValueOnce(changed());
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    fireEvent.submit(field(PW_COPY.confirm).closest("form") as HTMLFormElement); // Enter in a field
    const heading = await screen.findByRole("heading", { name: PW_COPY.doneHeading });
    expect(heading).toHaveFocus();
    expect(screen.getByText(PW_COPY.doneBody)).toBeTruthy();
    expect(screen.queryByLabelText(PW_COPY.next)).toBeNull();
    await expect(accessToken.getToken()).resolves.toMatchObject({ accessToken: TOKEN });
    expect(await serious()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: PW_COPY.doneAction }));
    expect(assign).toHaveBeenCalledWith("/terminal");
  });

  it("session_read_only says W-32 at the submit; enrolment goes to SCR-003; a 401 signs out", async () => {
    fetchMock.mockResolvedValueOnce(problem(403, "session_read_only"));
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    const submit = await screen.findByRole("button", { name: PW_COPY.submit });
    await waitFor(() => expect(submit).toHaveFocus());
    expect(submit).toHaveAccessibleDescription(PW_COPY.readOnly);

    fetchMock.mockResolvedValueOnce(problem(403, "mfa_enrollment_required"));
    press();
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login/2fa/enroll"));

    const end = vi.spyOn(accessToken, "endSession").mockImplementation(() => undefined);
    fetchMock.mockResolvedValueOnce(problem(401, "session_revoked"));
    press();
    await waitFor(() => expect(end).toHaveBeenCalledTimes(1));
  });

  it("another 403 says W-15 in the alert, without touching the fields", async () => {
    fetchMock.mockResolvedValueOnce(problem(403, "view_as_read_only"));
    render(<ChangePasswordScreen />);
    fill("pw-old", GOOD);
    press();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveFocus());
    expect(screen.getByRole("alert")).toHaveTextContent(PW_COPY.refused);
    expect(field(PW_COPY.next).value).toBe(GOOD);
  });
});
