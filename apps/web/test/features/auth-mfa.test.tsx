import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "../../src/features/auth/LoginScreen";
import { MFA_MIRRORED_ATTEMPTS, MFA_WARN_MS } from "../../src/features/auth/TwoFactorStep";

// #2711: SCR-002, the TOTP challenge step in place on R-001 (E09-D12 §5.2; BQ-02..BQ-13 of record).

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function serious(): Promise<unknown[]> {
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

const LOGIN = "/api/v1/auth/login";
const VERIFY = "/api/v1/auth/mfa/verify";
const RECOVERY = "/api/v1/auth/mfa/recovery";
/** Short, low-entropy stand-ins: a challenge handle and a marker for the bundle's access value. */
const HANDLE = "h-1";
const MARKER = "marker-a1";

function reply(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: { get: (k: string) => headers[k] ?? null },
  } as unknown as Response;
}

type Answer = Response | Error | Promise<Response>;
interface Call {
  readonly path: string;
  readonly body: unknown;
}

/** A fetch that answers each path from its own queue, in order, and records every call. */
function server(queues: Record<string, Answer[]>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      calls.push({ path, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
      const next = queues[path]?.shift();
      if (next === undefined) throw new Error(`unexpected call ${path}`);
      if (next instanceof Error) throw next;
      return next;
    }),
  );
  return calls;
}

const challenge = (handle = HANDLE, expiresIn = 300): Response =>
  reply(200, {
    status: "mfa_required",
    mfa_token: handle,
    methods: ["totp"],
    expires_in: expiresIn,
  });
const authenticated = (user: Record<string, unknown> = {}): Response =>
  reply(200, {
    status: "authenticated",
    tokens: { access_token: MARKER, token_type: "Bearer", expires_in: 600 },
    user: {
      id: "u-1",
      username: "ann",
      email: "a@x.test",
      roles: ["owner"],
      status: "active",
      ...user,
    },
  });
/** The one `401`, with whatever body: the client never reads it. */
const refused = (title = "Unauthorized", detail = "x", code = "mfa_invalid"): Response =>
  reply(401, { type: "about:blank", title, status: 401, detail, code });

let assign: ReturnType<typeof vi.fn>;
function stubLocation(search = "", hash = ""): void {
  assign = vi.fn();
  vi.stubGlobal("location", {
    origin: "http://localhost",
    pathname: "/login",
    search,
    hash,
    href: `http://localhost/login${search}${hash}`,
    assign,
  });
}

beforeEach(() => stubLocation());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

function signInFields(): void {
  fireEvent.change(screen.getByLabelText("Username or email"), { target: { value: "ann" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

async function toStep(): Promise<HTMLInputElement> {
  render(<LoginScreen />);
  signInFields();
  await screen.findByRole("heading", { name: "Two-factor code", level: 1 });
  return codeField();
}

const codeField = (): HTMLInputElement =>
  screen.getByRole("textbox", { name: "Two-factor code" }) as HTMLInputElement;
const verifyButton = (): HTMLElement => screen.getByRole("button", { name: "Verify" });
const verifies = (calls: readonly Call[]): Call[] =>
  calls.filter((c) => c.path === VERIFY || c.path === RECOVERY);
const type = (value: string): void => {
  fireEvent.change(codeField(), { target: { value } });
};
const settle = (): Promise<void> => act(async () => {});

/** Pending answers the test resolves by hand. */
function deferred(): { promise: Promise<Response>; resolve: (r: Response) => void } {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("SCR-002 TOTP step (#2711)", () => {
  it("replaces SCR-001 in place, moves focus to its heading and is axe clean (A11Y-F-0004)", async () => {
    server({ [LOGIN]: [challenge()] });
    const field = await toStep();
    const heading = screen.getByRole("heading", { name: "Two-factor code", level: 1 });
    expect(heading).toHaveFocus();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByLabelText("Password")).toBeNull();
    // CMP-204: one input named by the visible heading, described by the visible helper
    expect(field).toHaveAccessibleDescription("Code from your authenticator app");
    expect(field).toHaveAttribute("autocomplete", "one-time-code");
    expect(field).toHaveAttribute("inputmode", "numeric");
    expect(screen.queryByRole("group")).toBeNull();
    expect(await serious()).toEqual([]);
  });

  it("with the build switch off, no recovery control is in the accessibility tree (BQ-08 a)", async () => {
    server({ [LOGIN]: [challenge()] });
    await toStep();
    expect(screen.queryByRole("button", { name: /recovery code/iu })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Recovery code" })).toBeNull();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
  });

  it("keyboard: the code field then Verify are the tab stops, and Enter submits", async () => {
    const calls = server({ [LOGIN]: [challenge()], [VERIFY]: [refused()] });
    const field = await toStep();
    const stops = [...document.querySelectorAll<HTMLElement>("input, button, [tabindex]")].filter(
      (el) => el.tabIndex >= 0,
    );
    expect(stops).toEqual([field, verifyButton()]);
    field.focus();
    fireEvent.change(field, { target: { value: "12345" } });
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    expect(verifies(calls)).toHaveLength(0); // incomplete: Enter names the field instead
    expect(field).toHaveFocus();
  });

  it("a paste of the whole code sends one request; Enter and Verify while verifying send none", async () => {
    const pending = deferred();
    const calls = server({ [LOGIN]: [challenge()], [VERIFY]: [pending.promise] });
    const field = await toStep();
    field.focus();
    type("123 456");
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    fireEvent.click(verifyButton());
    type("654321");
    expect(verifies(calls)).toEqual([
      { path: VERIFY, body: { mfa_token: HANDLE, method: "totp", code: "123456" } },
    ]);
    // verifying: read-only and aria-disabled, focus kept; the submit stays focusable
    expect(field).toHaveAttribute("readonly");
    expect(field).toHaveAttribute("aria-disabled", "true");
    expect(field).toHaveFocus();
    expect(field.value).toBe("123456");
    expect(verifyButton()).toHaveAttribute("aria-disabled", "true");
    expect(verifyButton()).not.toBeDisabled();
    expect(await serious()).toEqual([]);
    pending.resolve(refused());
    await settle();
    expect(verifies(calls)).toHaveLength(1);
  });

  it("an invalid code clears the field, marks and describes it, and focuses it", async () => {
    server({ [LOGIN]: [challenge()], [VERIFY]: [refused()] });
    const field = await toStep();
    type("123456");
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    expect(field.value).toBe("");
    expect(field).toHaveFocus();
    expect(field).toHaveAccessibleDescription(
      "Code from your authenticator app That code isn't valid.",
    );
    expect(await serious()).toEqual([]);
    type("1");
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText("That code isn't valid.")).toBeNull();
  });

  it("no oracle: wrong, replayed and exhausted refusals render the same, and never as expired", async () => {
    const bodies = [
      refused("Unauthorized", "wrong-marker", "mfa_invalid"),
      refused("Replayed-marker", "replay-marker", "mfa_replayed"),
      refused("Exhausted-marker", "exhausted-marker", "recovery_exhausted"),
    ];
    server({ [LOGIN]: [challenge()], [VERIFY]: bodies });
    const field = await toStep();
    const seen: string[] = [];
    for (let i = 0; i < bodies.length; i += 1) {
      type("123456");
      await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
      expect(field).toHaveFocus();
      seen.push(document.querySelector("main")?.innerHTML ?? "");
    }
    expect(new Set(seen).size).toBe(1);
    expect(document.body.innerHTML).not.toMatch(/marker|replay|exhaust|expired/iu);
    expect(screen.queryByRole("button", { name: "Back to login" })).toBeNull();
  });

  it(`after the mirrored cap of ${MFA_MIRRORED_ATTEMPTS} refusals nothing more is sent and the step is expired`, async () => {
    const calls = server({
      [LOGIN]: [challenge()],
      [VERIFY]: Array.from({ length: MFA_MIRRORED_ATTEMPTS }, () => refused()),
    });
    const field = await toStep();
    for (let i = 1; i < MFA_MIRRORED_ATTEMPTS; i += 1) {
      type("123456");
      await waitFor(() => expect(verifies(calls)).toHaveLength(i));
      await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
      // the mirror is never rendered, announced or put in an attribute
      expect(document.body.innerHTML).not.toMatch(/attempt|remaining|data-/iu);
    }
    type("123456");
    const back = await screen.findByRole("button", { name: "Back to login" });
    expect(back).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This code has expired. Please log in again.",
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(verifies(calls)).toHaveLength(MFA_MIRRORED_ATTEMPTS);
    expect(await serious()).toEqual([]);
  });

  it("only a 401 counts: a 5xx, a network failure and another 4xx do not move the mirror", async () => {
    const calls = server({
      [LOGIN]: [challenge()],
      [VERIFY]: [
        refused(),
        refused(),
        reply(503, {}),
        new Error("offline"),
        reply(400, {}),
        refused(),
        refused(),
        refused(),
      ],
    });
    const field = await toStep();
    for (let i = 1; i <= 7; i += 1) {
      type("123456");
      await waitFor(() => expect(verifies(calls)).toHaveLength(i));
      await settle();
      expect(screen.queryByRole("button", { name: "Back to login" }), `answer ${i}`).toBeNull();
      if (field.getAttribute("aria-invalid") !== "true") type(""); // unreachable keeps the code
    }
    type("123456");
    await screen.findByRole("button", { name: "Back to login" });
    expect(verifies(calls)).toHaveLength(8);
  });

  it("no 422 leaves the browser: an incomplete or non-digit code is never sent", async () => {
    const calls = server({ [LOGIN]: [challenge()] });
    const field = await toStep();
    type("abcdef");
    expect(field.value).toBe("");
    type("12a3");
    expect(field.value).toBe("123");
    fireEvent.click(verifyButton());
    expect(verifies(calls)).toHaveLength(0);
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveFocus();
    expect(field).toHaveAccessibleDescription(
      "Code from your authenticator app Enter the 6-digit code from your authenticator app.",
    );
  });

  it("a 429 shows the Retry-After countdown in the focused alert and blocks submit", async () => {
    const calls = server({
      [LOGIN]: [challenge()],
      [VERIFY]: [reply(429, {}, { "Retry-After": "60" })],
    });
    const field = await toStep();
    type("123456");
    const alert = await screen.findByText("Too many attempts. Try again in 1:00.", {
      selector: ".cv-visually-hidden",
    });
    expect(screen.getByRole("alert")).toContainElement(alert);
    expect(screen.getByRole("alert")).toHaveFocus();
    expect(verifyButton()).toHaveAttribute("aria-disabled", "true");
    type("");
    type("654321");
    fireEvent.click(verifyButton());
    expect(verifies(calls)).toHaveLength(1);
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(await serious()).toEqual([]);
  });

  it("an unreachable server shows SCR-001's line in the focused alert, and Verify retries", async () => {
    const calls = server({ [LOGIN]: [challenge()], [VERIFY]: [reply(503, {}), refused()] });
    await toStep();
    type("123456");
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Cannot reach the server. Check your connection and try again.",
      ),
    );
    expect(screen.getByRole("alert")).toHaveFocus();
    expect(await serious()).toEqual([]);
    fireEvent.click(verifyButton());
    await waitFor(() => expect(verifies(calls)).toHaveLength(2));
  });

  it("a 200 navigates to the shell once, keeps no token, and nothing after it changes the screen", async () => {
    const calls = server({ [LOGIN]: [challenge()], [VERIFY]: [authenticated()] });
    const field = await toStep();
    type("123456");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/terminal"));
    const before = document.body.innerHTML;
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    fireEvent.click(verifyButton());
    await settle();
    expect(document.body.innerHTML).toBe(before);
    expect(assign).toHaveBeenCalledTimes(1);
    expect(verifies(calls)).toHaveLength(1);
    expect(document.body.innerHTML).not.toContain(MARKER);
    expect(JSON.stringify({ ...localStorage })).not.toContain(MARKER);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(MARKER);
  });

  it("an enrolment-only user goes to enrolment (R-006), not the shell", async () => {
    server({
      [LOGIN]: [challenge()],
      [VERIFY]: [authenticated({ mfa_required: true, mfa_enabled: false })],
    });
    await toStep();
    type("123456");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login/2fa/enroll"));
  });

  it("the handle and the code never reach the URL, history state, storage or the DOM", async () => {
    server({ [LOGIN]: [challenge("h-77")], [VERIFY]: [refused()] });
    const field = await toStep();
    type("246810");
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    const places = [
      window.location.href,
      window.location.search,
      window.location.hash,
      JSON.stringify(window.history.state),
      JSON.stringify({ ...localStorage }),
      JSON.stringify({ ...sessionStorage }),
      document.body.innerHTML,
      document.title,
    ];
    for (const place of places) {
      expect(place).not.toContain("h-77");
      expect(place).not.toContain("246810");
    }
  });

  it("a handle planted in the query, hash, history state or storage is never sent", async () => {
    stubLocation("?mfa_token=planted-q", "#mfa_token=planted-h");
    window.history.replaceState({ mfa_token: "planted-s" }, "");
    localStorage.setItem("mfa_token", "planted-l");
    sessionStorage.setItem("mfa_token", "planted-ss");
    const calls = server({ [LOGIN]: [challenge()], [VERIFY]: [refused()] });
    await toStep();
    type("123456");
    await waitFor(() => expect(verifies(calls)).toHaveLength(1));
    expect(JSON.stringify(calls)).not.toMatch(/planted/u);
    expect(verifies(calls)[0]?.body).toEqual({ mfa_token: HANDLE, method: "totp", code: "123456" });
  });
});

describe("SCR-002 challenge life (#2711 BQ-06; fake clock)", () => {
  async function toStepFake(expiresIn: number, verify: Answer[] = []): Promise<Call[]> {
    vi.useFakeTimers({
      toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
    });
    const calls = server({ [LOGIN]: [challenge(HANDLE, expiresIn)], [VERIFY]: verify });
    render(<LoginScreen />);
    signInFields();
    await settle();
    expect(screen.getByRole("heading", { name: "Two-factor code" })).toBeInTheDocument();
    return calls;
  }
  const advance = (ms: number): Promise<void> =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });

  it("warns once, politely, 30 s before the end, then expires with focus on Back to login", async () => {
    await toStepFake(120);
    const status = screen.getByRole("status");
    await advance(120_000 - MFA_WARN_MS - 1);
    expect(status).toBeEmptyDOMElement();
    await advance(1);
    expect(screen.getByRole("status")).toHaveTextContent(
      "This sign-in step expires in less than 30 seconds.",
    );
    expect(codeField()).toBeInTheDocument(); // never extended, never ended early
    await advance(MFA_WARN_MS);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This code has expired. Please log in again.",
    );
    expect(screen.getByRole("button", { name: "Back to login" })).toHaveFocus();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("an answer still on the wire at expiry is dropped", async () => {
    const pending = deferred();
    await toStepFake(60, [pending.promise]);
    type("123456");
    await advance(60_000);
    expect(screen.getByRole("button", { name: "Back to login" })).toBeInTheDocument();
    pending.resolve(authenticated());
    await settle();
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Back to login" })).toHaveFocus();
  });

  it("Back to login returns to SCR-001; a new challenge's handle is sent, never the old one", async () => {
    const calls = await toStepFake(60);
    await advance(60_000);
    fireEvent.click(screen.getByRole("button", { name: "Back to login" }));
    expect(screen.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeInTheDocument();
    expect(screen.getByLabelText("Username or email")).toHaveFocus();
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    const queues = { [LOGIN]: [challenge("h-2")], [VERIFY]: [refused()] };
    const more = server(queues);
    signInFields();
    await settle();
    type("123456");
    await settle();
    expect(
      verifies([...calls, ...more]).map((c) => (c.body as { mfa_token: string }).mfa_token),
    ).toEqual(["h-2"]);
  });

  it("a 429 counts down each second without re-announcing, then Verify works again", async () => {
    const calls = await toStepFake(300, [reply(429, {}, { "Retry-After": "3" }), refused()]);
    type("123456");
    await settle();
    const spoken = screen.getByText("Too many attempts. Try again in 0:03.", {
      selector: ".cv-visually-hidden",
    });
    await advance(1000);
    expect(spoken).toHaveTextContent("Too many attempts. Try again in 0:03."); // frozen for AT
    expect(screen.getByText("Too many attempts. Try again in 0:02.")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    await advance(2000);
    expect(verifyButton()).not.toHaveAttribute("aria-disabled");
    fireEvent.click(verifyButton());
    await settle();
    expect(verifies(calls)).toHaveLength(2);
  });

  it("a new code pasted over a complete one sends it once the countdown ends", async () => {
    const calls = await toStepFake(300, [reply(429, {}, { "Retry-After": "1" }), refused()]);
    type("123456");
    await settle();
    await advance(1000);
    expect(codeField().value).toBe("123456"); // a 429 keeps the code: the paste lands on a complete one
    type("654321");
    await settle();
    expect(verifies(calls).map((c) => (c.body as { code: string }).code)).toEqual([
      "123456",
      "654321",
    ]);
  });
});

describe("SCR-002 recovery-code entry (#2711 BQ-08 a; build switch on)", () => {
  beforeEach(() => vi.stubGlobal("__CV_MFA_RECOVERY_UI__", true));

  async function toRecovery(calls: Record<string, Answer[]>): Promise<Call[]> {
    const seen = server({ [LOGIN]: [challenge()], ...calls });
    await toStep();
    fireEvent.click(screen.getByRole("button", { name: "Use a recovery code instead" }));
    return seen;
  }
  const recoveryField = (): HTMLInputElement =>
    screen.getByRole("textbox", { name: "Recovery code" }) as HTMLInputElement;

  it("switches to one labelled field, focused, and back; axe clean", async () => {
    await toRecovery({});
    expect(recoveryField()).toHaveFocus();
    expect(await serious()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Back to authenticator code" }));
    expect(codeField()).toHaveFocus();
  });

  it("a malformed recovery code is never sent; a valid one goes to the recovery route", async () => {
    const calls = await toRecovery({ [RECOVERY]: [refused()] });
    fireEvent.change(recoveryField(), { target: { value: "short" } });
    fireEvent.click(verifyButton());
    expect(verifies(calls)).toHaveLength(0);
    expect(recoveryField()).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(recoveryField(), { target: { value: "abcd2345efgh" } });
    fireEvent.click(verifyButton());
    await waitFor(() => expect(recoveryField()).toHaveAttribute("aria-invalid", "true"));
    expect(verifies(calls)).toEqual([
      { path: RECOVERY, body: { mfa_token: HANDLE, recovery_code: "abcd2345efgh" } },
    ]);
    expect(recoveryField()).toHaveAccessibleDescription("That recovery code isn't valid.");
    expect(recoveryField()).toHaveFocus();
    expect(recoveryField().value).toBe("");
  });

  it("a recovery 200 always lands on enrolment (an enrolment-only session)", async () => {
    await toRecovery({ [RECOVERY]: [authenticated()] });
    fireEvent.change(recoveryField(), { target: { value: "abcd2345efgh" } });
    fireEvent.click(verifyButton());
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login/2fa/enroll"));
  });

  it("the code and recovery forms share one mirrored count", async () => {
    const calls = server({
      [LOGIN]: [challenge()],
      [VERIFY]: [refused(), refused(), refused()],
      [RECOVERY]: [refused(), refused()],
    });
    await toStep();
    for (let i = 1; i <= 3; i += 1) {
      type("123456");
      await waitFor(() => expect(verifies(calls)).toHaveLength(i));
      await settle();
    }
    fireEvent.click(screen.getByRole("button", { name: "Use a recovery code instead" }));
    fireEvent.change(recoveryField(), { target: { value: "abcd2345efgh" } });
    fireEvent.click(verifyButton());
    await waitFor(() => expect(verifies(calls)).toHaveLength(4));
    await settle();
    fireEvent.change(recoveryField(), { target: { value: "abcd2345efgh" } });
    fireEvent.click(verifyButton());
    expect(await screen.findByRole("button", { name: "Back to login" })).toHaveFocus();
    expect(verifies(calls)).toHaveLength(5);
  });
});
