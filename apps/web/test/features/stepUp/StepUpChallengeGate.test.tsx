import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  RESEND_TIMEOUT_MS,
  StepUpChallengeGate,
} from "../../../src/features/stepUp/StepUpChallengeGate";
import { holdRequest, type StepUpChallenge } from "../../../src/features/stepUp/challenge";
import { resetMeClaims } from "../../../src/lib/auth/meCache";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function seriousViolations(): Promise<unknown[]> {
  // jsdom has no canvas; contrast is covered by the Storybook and Playwright axe runs.
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

const FIVE_MINUTES = 5 * 60_000;
const CHALLENGE: StepUpChallenge = {
  challengeId: "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b",
  expiresAt: new Date(Date.now() + 10 * FIVE_MINUTES).toISOString(),
  actionClass: "keys",
  actionSummary: "Release kill switch, scope global",
  target: null,
  clockOffsetMs: 0,
};
const HELD = holdRequest(
  "POST",
  "/api/v1/keys/k1/rotate",
  { "Content-Type": "application/json", "Idempotency-Key": "idem-0001" },
  '{"reason":"scheduled"}',
);
const GRANTED = {
  elevated_until: "2026-09-14T10:36:10Z",
  action_class: "keys",
  single_use: false,
  step_up_expires_at: "2026-09-14T10:36:10Z",
};

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const problem = (status: number, code: string, extra: object = {}): Response =>
  json(status, {
    type: `https://candleviewer.local/errors/${code}`,
    title: code,
    status,
    code,
    ...extra,
  });

type Route = (url: string, init: RequestInit) => Response | Promise<Response>;
let fetchMock: ReturnType<typeof vi.fn>;

function stubFetch(stepUp: Route, held: Route = () => json(200, { ok: true })): void {
  fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    return url.endsWith("/auth/step-up") ? stepUp(url, init) : held(url, init);
  });
  vi.stubGlobal("fetch", fetchMock);
}

const calls = (suffix: string): RequestInit[] =>
  fetchMock.mock.calls
    .filter(([input]) => String(input).endsWith(suffix))
    .map(([, init]) => init as RequestInit);

function mount(
  challenge: StepUpChallenge = CHALLENGE,
  props: { readBack?: () => unknown; onResent?: (r: Response) => void } = {},
) {
  const onResent = props.onResent ?? vi.fn();
  const readBack = props.readBack ?? vi.fn();
  render(
    <>
      <button type="button">Rotate key</button>
      <StepUpChallengeGate
        challenge={challenge}
        held={HELD}
        onResent={onResent}
        readBack={readBack}
        outcomeWhere="Orders"
      />
    </>,
  );
  return { onResent, readBack };
}

function answer(code = "123456", typed?: string): void {
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct horse" } });
  fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: code } });
  if (typed !== undefined) {
    fireEvent.change(screen.getByLabelText(/to confirm \(case-sensitive\)/), {
      target: { value: typed },
    });
  }
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
}

/** Only the expiry tests fake time: the challenge then expires five minutes from "now". */
function fakeClock(): StepUpChallenge {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  return { ...CHALLENGE, expiresAt: new Date(Date.now() + FIVE_MINUTES).toISOString() };
}

beforeEach(() => {
  resetMeClaims();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("StepUpChallengeGate (#2725, E09-D06)", () => {
  it("test_step_up_challenge_answered_sends_challenge_id_and_resends_held_request_once", async () => {
    stubFetch(() => json(200, GRANTED));
    const { onResent } = mount();
    answer();
    await waitFor(() => expect(onResent).toHaveBeenCalledTimes(1));
    const [stepUp] = calls("/auth/step-up");
    expect(JSON.parse(String(stepUp?.body))).toEqual({
      password: "correct horse",
      code: "123456",
      challenge_id: CHALLENGE.challengeId,
    });
    const resent = calls("/keys/k1/rotate");
    expect(resent).toHaveLength(1);
    expect(resent[0]?.method).toBe("POST");
    expect(resent[0]?.body).toBe('{"reason":"scheduled"}');
    const headers = new Headers(resent[0]?.headers);
    expect(headers.get("Idempotency-Key")).toBe("idem-0001");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByText("Not sent")).not.toBeInTheDocument();
  });

  it("test_step_up_dialog_description_is_action_summary_verbatim", async () => {
    stubFetch(() => json(200, GRANTED));
    mount();
    const dialog = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    expect(dialog).toHaveAccessibleDescription("Release kill switch, scope global");
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(await seriousViolations()).toEqual([]);
  });

  it.each(["challenge_expired", "challenge_required"])(
    "test_step_up_400_%s_drops_held_request_and_shows_not_sent",
    async (rule) => {
      stubFetch(() =>
        problem(400, "validation_failed", { errors: [{ field: "challenge_id", rule }] }),
      );
      mount();
      answer();
      expect(await screen.findByRole("status")).toHaveTextContent("Not sent");
      expect(calls("/keys/k1/rotate")).toHaveLength(0);
      expect(await seriousViolations()).toEqual([]);
    },
  );

  it("test_step_up_200_for_another_class_drops_held_request_and_shows_not_sent", async () => {
    stubFetch(() => json(200, { ...GRANTED, action_class: "users" }));
    mount();
    answer();
    expect(await screen.findByRole("status")).toHaveTextContent("Not sent");
    expect(calls("/keys/k1/rotate")).toHaveLength(0);
  });

  it("test_resend_network_error_reads_back_never_not_sent_never_resends", async () => {
    stubFetch(
      () => json(200, GRANTED),
      () => Promise.reject(new TypeError("Failed to fetch")),
    );
    const readBack = vi.fn().mockResolvedValue(undefined);
    const { onResent } = mount(CHALLENGE, { readBack });
    answer();
    expect(await screen.findByRole("status")).toHaveTextContent("Outcome pending, see Orders");
    expect(readBack).toHaveBeenCalledTimes(1);
    expect(onResent).not.toHaveBeenCalled();
    expect(calls("/keys/k1/rotate")).toHaveLength(1);
    expect(screen.queryByText("Not sent")).not.toBeInTheDocument();
    expect(await seriousViolations()).toEqual([]);
  });

  it("test_resend_timeout_takes_the_unknown_outcome_path_never_not_sent", async () => {
    const timeout = new AbortController();
    const spy = vi.spyOn(AbortSignal, "timeout").mockReturnValue(timeout.signal);
    stubFetch(
      () => json(200, GRANTED),
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        }),
    );
    const readBack = vi.fn();
    const { onResent } = mount(CHALLENGE, { readBack });
    answer();
    await waitFor(() => expect(calls("/keys/k1/rotate")).toHaveLength(1));
    expect(spy).toHaveBeenCalledWith(RESEND_TIMEOUT_MS);
    act(() => timeout.abort(new DOMException("timed out", "TimeoutError")));
    expect(await screen.findByRole("status")).toHaveTextContent("Outcome pending, see Orders");
    expect(readBack).toHaveBeenCalledTimes(1);
    expect(onResent).not.toHaveBeenCalled();
    expect(calls("/keys/k1/rotate")).toHaveLength(1);
    expect(screen.queryByText("Not sent")).not.toBeInTheDocument();
    spy.mockRestore();
  });

  it("test_resend_without_answer_survives_a_failing_read_back", async () => {
    stubFetch(
      () => json(200, GRANTED),
      () => Promise.reject(new DOMException("timed out", "TimeoutError")),
    );
    mount(CHALLENGE, { readBack: vi.fn().mockRejectedValue(new Error("offline")) });
    answer();
    expect(await screen.findByRole("status")).toHaveTextContent("Outcome pending, see Orders");
  });

  it("test_escape_drops_held_request_and_shows_not_sent", async () => {
    stubFetch(() => json(200, GRANTED));
    mount();
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(await screen.findByRole("status")).toHaveTextContent("Not sent");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("test_cancel_drops_held_request_and_shows_not_sent", async () => {
    stubFetch(() => json(200, GRANTED));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Not sent");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("test_challenge_expiry_drops_held_request_and_shows_not_sent", async () => {
    stubFetch(() => json(200, GRANTED));
    mount(fakeClock());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FIVE_MINUTES);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Not sent");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("test_expiry_during_step_up_never_resends", async () => {
    let release: (r: Response) => void = () => undefined;
    stubFetch(() => new Promise<Response>((resolve) => (release = resolve)));
    mount(fakeClock());
    answer();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FIVE_MINUTES);
    });
    await act(async () => release(json(200, GRANTED)));
    expect(screen.getByRole("status")).toHaveTextContent("Not sent");
    expect(calls("/keys/k1/rotate")).toHaveLength(0);
  });

  it("test_invalid_code_keeps_dialog_with_one_generic_assertive_error", async () => {
    stubFetch(() => problem(401, "mfa_invalid"));
    mount();
    answer();
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect code.");
    // The alert and the cleared fields are separate React updates: wait for the clear.
    await waitFor(() => {
      expect(screen.getByLabelText("Authenticator code")).toHaveValue("");
      expect(screen.getByLabelText("Password")).toHaveValue("");
      expect(screen.getByLabelText("Password")).toHaveFocus();
    });
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(calls("/keys/k1/rotate")).toHaveLength(0);
  });

  it("test_third_failure_drops_held_request_and_shows_not_sent", async () => {
    stubFetch(() => problem(401, "mfa_invalid"));
    mount();
    answer();
    await screen.findByRole("alert");
    answer();
    await waitFor(() => expect(calls("/auth/step-up")).toHaveLength(2));
    answer();
    expect(await screen.findByRole("status")).toHaveTextContent("Not sent");
    expect(calls("/keys/k1/rotate")).toHaveLength(0);
  });

  it.each([
    ["read-only session", 403, "session_read_only"],
    ["idle lock", 401, "session_idle_locked"],
    ["absolute expiry", 401, "session_revoked"],
  ])("test_%s_drops_held_request_and_shows_not_sent", async (_name, status, code) => {
    stubFetch(() => problem(status, code));
    mount();
    answer();
    expect(await screen.findByRole("status")).toHaveTextContent("Not sent");
    expect(calls("/keys/k1/rotate")).toHaveLength(0);
  });

  it.each([
    ["network error", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["503", () => problem(503, "audit_unavailable")],
    ["500", () => problem(500, "internal")],
    ["429", () => problem(429, "rate_limited")],
  ])(
    "test_step_up_%s_is_not_a_credential_failure_and_keeps_the_held_request",
    async (_name, route: () => Response | Promise<Response>) => {
      stubFetch(route);
      mount();
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        answer();
        await waitFor(() => expect(calls("/auth/step-up")).toHaveLength(attempt));
        await waitFor(() => expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled());
      }
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Cannot reach the server. Try again.");
      expect(alert).not.toHaveTextContent("Incorrect code.");
      expect(screen.getByLabelText("Authenticator code")).not.toHaveAttribute("aria-invalid");
      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
      expect(screen.queryByText("Not sent")).not.toBeInTheDocument();
      expect(calls("/keys/k1/rotate")).toHaveLength(0);
    },
  );

  it("test_expiry_uses_the_server_clock_not_a_skewed_client_clock", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    // The client clock runs 10 minutes behind the server: on its own clock the challenge would
    // look live for 15 minutes. On the server's it has 5 minutes left.
    const serverNow = Date.now() + 2 * FIVE_MINUTES;
    stubFetch(() => json(200, GRANTED));
    mount({
      ...CHALLENGE,
      expiresAt: new Date(serverNow + FIVE_MINUTES).toISOString(),
      clockOffsetMs: serverNow - Date.now(),
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FIVE_MINUTES - 1_000);
    });
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Not sent");
  });

  it("test_typed_confirmation_must_equal_target_exactly", async () => {
    stubFetch(() => json(200, GRANTED));
    const { onResent } = mount({
      ...CHALLENGE,
      actionSummary: "Rotate API key for account 'sub_002' (live, UID 1001234)",
      target: "sub_002",
    });
    const field = screen.getByLabelText("Type sub_002 to confirm (case-sensitive)");
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.change(field, { target: { value: "SUB_002" } });
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    fireEvent.change(field, { target: { value: "sub_002" } });
    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    expect(await seriousViolations()).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onResent).toHaveBeenCalledTimes(1));
  });

  it("test_tab_cycles_inside_dialog_and_focus_returns_to_trigger", async () => {
    stubFetch(() => json(200, GRANTED));
    const trigger = (): HTMLElement => screen.getByRole("button", { name: "Rotate key" });
    const onResent = vi.fn();
    const view = render(
      <>
        <button type="button">Rotate key</button>
      </>,
    );
    trigger().focus();
    view.rerender(
      <>
        <button type="button">Rotate key</button>
        <StepUpChallengeGate
          challenge={CHALLENGE}
          held={HELD}
          onResent={onResent}
          readBack={vi.fn()}
          outcomeWhere="Orders"
        />
      </>,
    );
    const dialog = screen.getByRole("alertdialog");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(password).toHaveFocus();
    answer();
    await waitFor(() => expect(onResent).toHaveBeenCalled());
    expect(trigger()).toHaveFocus();
  });
});
