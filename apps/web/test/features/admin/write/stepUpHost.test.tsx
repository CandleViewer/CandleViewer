/**
 * E42-S02 (#1023): the admin area's step-up host, shared by the users screens, E42-S04's export and E42-S05 (the
 * lane's shared write kit). A write refused with `403 step_up_required` opens SCR-006 through the shipped gate; after
 * the step-up the held request is re-sent once, unchanged (method, path with its query, `Idempotency-Key`, body);
 * a re-send challenged again opens one more cycle and no third; Esc or Cancel drops it ("Not sent"); a renewal is
 * a new request with a new attempt that keeps the failure count; a challenge for a write whose opening ended (by
 * `clear()` or by another action's `start()`) is dropped and said once, a re-send's included; `clear()` closes an
 * open gate; a challenge naming another class than the host's is answered and warned in development. It keeps no
 * elevation. Its signals arm and settle the action's own in-flight state once per send, an answer handler that
 * throws included; an action that throws before it routes is warned in development by the error's name alone.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type JSX } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { STEP_UP_INVALID } from "../../../../src/features/stepUp/StepUpChallengeGate";
import {
  STEP_UP_LOCKED,
  STEP_UP_NOT_SENT,
  STEP_UP_RENEW,
  stepUpOutcomePending,
} from "../../../../src/features/stepUp/StepUpDialog";
import { newAttempt } from "../../../../src/features/admin/write/idempotency";
import {
  useStepUpHost,
  type StepUpHost,
  type WriteSignals,
} from "../../../../src/features/admin/write/stepUpHost";
import {
  holdWrite,
  sendWrite,
  type WriteResult,
} from "../../../../src/features/admin/write/writeCall";

const USER = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
const PATH = `/api/v1/users/${USER}?acknowledge_unknown_positions=true`;
const reply = (status: number, body: unknown): Response =>
  ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
const challenge = (id: string, cls = "users", expiresInMs = 300_000) => ({
  code: "step_up_required",
  action_class: cls,
  challenge_id: id,
  challenge_expires_at: new Date(Date.now() + expiresInMs).toISOString(),
  action_summary: "Disable user 'alex'",
  target: null,
});
const vetAny = (raw: unknown): unknown => raw;

interface Calls {
  readonly writes: () => [string, RequestInit][];
  readonly fetch: ReturnType<typeof vi.fn>;
}

/** A server whose writes answer `answers` in turn, and whose step-up always grants `granted`. */
function server(answers: Response[], granted = "users"): Calls {
  const queue = [...answers];
  const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) => {
    if (url.endsWith("/auth/step-up")) {
      return reply(200, { action_class: granted, single_use: false, elevated_until: "x" });
    }
    return queue.shift() ?? reply(500, {});
  });
  vi.stubGlobal("fetch", fetch);
  return {
    fetch,
    writes: () =>
      fetch.mock.calls
        .filter(([url]) => !url.endsWith("/auth/step-up"))
        .map(([url, init]): [string, RequestInit] => [url, init ?? {}]),
  };
}

interface HarnessProps {
  readonly onAnswer: (res: WriteResult<unknown>) => void;
  readonly say?: (text: string) => void;
  readonly readBack?: () => unknown;
  readonly expose?: (host: StepUpHost) => void;
  /** The action's signals: each call is recorded as it comes. */
  readonly signals?: WriteSignals;
}

/** A page with one write: Disable, through the host; Clear ends the host's opening. */
function Harness({
  onAnswer,
  say = vi.fn(),
  readBack = vi.fn(),
  expose,
  signals,
}: HarnessProps): JSX.Element {
  const host = useStepUpHost({ stepUpClass: "users", readBack, outcomeWhere: "Users", say });
  expose?.(host);
  const [, setRuns] = useState(0);
  const disable = (): void => {
    setRuns((n) => n + 1);
    void host.start(async (route) => {
      const res = await sendWrite(
        holdWrite("PATCH", PATH, newAttempt(), { status: "disabled" }),
        vetAny,
      );
      route(res, onAnswer);
    }, signals);
  };
  return (
    <>
      <button type="button" onClick={disable}>
        Disable alex
      </button>
      <button type="button" onClick={() => host.clear()}>
        Clear
      </button>
      {host.gate}
    </>
  );
}

/**
 * Fake clock (`setTimeout`, `Date`) for a challenge that expires: the 403 is let through, then the clock is moved
 * past the 20 ms expiry by hand, so no real timer races a `waitFor`. Returns the renewal button.
 */
async function expireChallenge(): Promise<HTMLElement> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20);
  });
  return screen.getByRole("button", { name: STEP_UP_RENEW });
}
const settle = (): Promise<void> =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

const answerStepUp = async (): Promise<void> => {
  await screen.findByRole("alertdialog");
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
  fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
};
const attemptOf = (init: RequestInit | undefined): string | null =>
  new Headers(init?.headers).get("Idempotency-Key");

/** Signals that record their calls in order: `sending`, then each end. */
function recorded(): { readonly calls: string[]; readonly signals: WriteSignals } {
  const calls: string[] = [];
  return {
    calls,
    signals: {
      onSending: () => calls.push("sending"),
      onSettled: (end) => calls.push(end),
    },
  };
}

/**
 * A fetch whose writes the test answers one by one, in order (a `TypeError` is no answer), and whose step-up
 * answers `stepUps` in turn, then grants.
 */
function heldServer(stepUps: Response[] = []): {
  readonly answer: (res: Response | TypeError) => Promise<void>;
  readonly writes: () => number;
} {
  const waiting: { resolve: (res: Response) => void; reject: (error: TypeError) => void }[] = [];
  const steps = [...stepUps];
  const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) => {
    if (url.endsWith("/auth/step-up")) {
      return (
        steps.shift() ??
        reply(200, { action_class: "users", single_use: false, elevated_until: "x" })
      );
    }
    return new Promise<Response>((resolve, reject) => waiting.push({ resolve, reject }));
  });
  vi.stubGlobal("fetch", fetch);
  return {
    answer: async (res) => {
      await waitFor(() => expect(waiting.length).toBeGreaterThan(0));
      const next = waiting.shift();
      await act(async () => {
        if (res instanceof TypeError) next?.reject(res);
        else next?.resolve(res);
      });
    },
    writes: () => fetch.mock.calls.filter(([url]) => !url.endsWith("/auth/step-up")).length,
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useStepUpHost (the admin write kit)", () => {
  it("an answer with no challenge goes straight to the write's answer", async () => {
    server([reply(200, { id: USER, status: "disabled" })]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1));
    expect(onAnswer.mock.calls[0]?.[0]).toMatchObject({ ok: true, status: 200 });
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("a challenge opens SCR-006 with the server's summary; the held request is re-sent once, unchanged", async () => {
    const calls = server([reply(403, challenge(USER)), reply(200, { id: USER })]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    expect(await screen.findByRole("alertdialog")).toHaveAccessibleDescription(
      "Disable user 'alex'",
    );
    await answerStepUp();
    await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1));
    expect(onAnswer.mock.calls[0]?.[0]).toMatchObject({ ok: true, status: 200, stepUp: null });
    const [first, second] = calls.writes();
    expect(calls.writes()).toHaveLength(2);
    expect(second?.[0]).toBe(first?.[0]);
    expect(second?.[0]).toBe(PATH);
    expect(second?.[1].method).toBe("PATCH");
    expect(second?.[1].body).toBe(first?.[1].body);
    expect(attemptOf(second?.[1])).toBe(attemptOf(first?.[1]));
    expect(attemptOf(first?.[1])).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("Cancel drops the held request: Not sent, and it is never sent", async () => {
    const calls = server([reply(403, challenge(USER))]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("status")).toHaveTextContent(STEP_UP_NOT_SENT);
    expect(calls.writes()).toHaveLength(1);
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("a re-send challenged again opens one more cycle; a third challenge is the write's refusal", async () => {
    const calls = server([
      reply(403, challenge("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c61")),
      reply(403, challenge("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c62")),
      reply(403, challenge("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c63")),
    ]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await answerStepUp();
    await waitFor(() => expect(calls.writes()).toHaveLength(2));
    await answerStepUp();
    await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1));
    expect(calls.writes()).toHaveLength(3);
    expect(onAnswer.mock.calls[0]?.[0]).toMatchObject({
      ok: false,
      status: 403,
      code: "step_up_required",
      stepUp: null,
    });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    // Every send of the one attempt carried its one value.
    const attempts = new Set(calls.writes().map(([, init]) => attemptOf(init)));
    expect(attempts.size).toBe(1);
  });

  it("a renewal after the challenge expires is a new request with a new attempt", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const calls = server([
      reply(403, challenge(USER, "users", 20)),
      reply(200, { id: USER, status: "disabled" }),
    ]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    fireEvent.click(await expireChallenge());
    await settle();
    expect(onAnswer).toHaveBeenCalledTimes(1);
    const [first, second] = calls.writes();
    expect(calls.writes()).toHaveLength(2);
    expect(attemptOf(second?.[1])).not.toBe(attemptOf(first?.[1]));
  });

  it("a challenge for a write whose opening ended is dropped, said once, and never opened", async () => {
    let release: (res: Response) => void = () => undefined;
    const fetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetch);
    const say = vi.fn();
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} say={say} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await act(async () => {
      release(reply(403, challenge(USER)));
    });
    expect(say).toHaveBeenCalledTimes(1);
    expect(say).toHaveBeenCalledWith(STEP_UP_NOT_SENT);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("names its class; a challenge for another class is still answered and warned in development", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    server([reply(403, challenge(USER, "risk_caps")), reply(200, { id: USER })], "risk_caps");
    const onAnswer = vi.fn();
    let host: StepUpHost | undefined;
    render(<Harness onAnswer={onAnswer} expose={(h) => (host = h)} />);
    expect(host?.stepUpClass).toBe("users");
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await answerStepUp();
    await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1));
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("risk_caps"));
  });

  it("keeps no elevation and no request: nothing is written to storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    server([reply(403, challenge(USER)), reply(200, { id: USER })]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await answerStepUp();
    await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1));
    expect(setItem).not.toHaveBeenCalled();
  });

  it("clear() with a challenge open closes the gate: the held request is never sent", async () => {
    const calls = server([reply(403, challenge(USER))]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(calls.writes()).toHaveLength(1);
    expect(calls.fetch.mock.calls.some(([url]) => String(url).endsWith("/auth/step-up"))).toBe(
      false,
    );
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("a re-send answered by a challenge after clear() is dropped and said once, never opened", async () => {
    const wire = heldServer();
    const say = vi.fn();
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} say={say} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await wire.answer(reply(403, challenge("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c61")));
    await answerStepUp();
    await waitFor(() => expect(wire.writes()).toBe(2)); // the held request's re-send is on the wire
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await wire.answer(reply(403, challenge("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c62")));
    await waitFor(() => expect(say).toHaveBeenCalledWith(STEP_UP_NOT_SENT));
    expect(say).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("another action's start ends the earlier write's opening without clear(): its challenge is dropped", async () => {
    const wire = heldServer();
    const say = vi.fn();
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} say={say} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" })); // write A
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" })); // write B: no clear() between
    await wire.answer(reply(403, challenge(USER))); // A's challenge arrives for an ended opening
    await waitFor(() => expect(say).toHaveBeenCalledWith(STEP_UP_NOT_SENT));
    expect(say).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await wire.answer(reply(200, { id: USER, status: "disabled" })); // B's answer is B's
    await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1));
  });

  it("a renewal keeps the codes already refused: after it, two more wrong codes lock the session", async () => {
    const invalid = (): Response => reply(401, { code: "mfa_invalid" });
    const wire = heldServer([invalid(), invalid(), invalid()]);
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    // inside its last 30 s, so "Request a new confirmation" is offered at once
    await wire.answer(
      reply(403, challenge("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c61", "users", 25_000)),
    );
    await answerStepUp();
    expect(await screen.findByText(STEP_UP_INVALID)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: STEP_UP_RENEW }));
    await wire.answer(reply(403, challenge("0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c62")));
    await answerStepUp();
    expect(await screen.findByText(STEP_UP_INVALID)).toBeInTheDocument();
    await answerStepUp();
    expect(await screen.findByText(STEP_UP_LOCKED)).toBeInTheDocument();
    expect(onAnswer).not.toHaveBeenCalled();
  });
});

describe("useStepUpHost's signals: the action's in-flight state, armed and settled once per send", () => {
  it("an answer with no challenge: sending, then answered after the action's own answer", async () => {
    server([reply(200, { id: USER })]);
    const { calls, signals } = recorded();
    render(<Harness onAnswer={() => calls.push("onAnswer")} signals={signals} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await waitFor(() => expect(calls).toEqual(["sending", "onAnswer", "answered"]));
  });

  it("a challenge is held while SCR-006 asks; the re-send runs inside SCR-006, busy, until its answer", async () => {
    const wire = heldServer();
    const { calls, signals } = recorded();
    render(<Harness onAnswer={() => calls.push("onAnswer")} signals={signals} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await wire.answer(reply(403, challenge(USER)));
    await waitFor(() => expect(calls).toEqual(["sending", "held"]));
    await answerStepUp();
    await waitFor(() => expect(wire.writes()).toBe(2));
    // On the wire again: SCR-006 stays over the page, busy, so nothing under it can start another write.
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");
    expect(calls).toEqual(["sending", "held"]);
    await wire.answer(reply(200, { id: USER }));
    await waitFor(() => expect(calls).toEqual(["sending", "held", "onAnswer", "answered"]));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("a challenge for an ended opening is dropped", async () => {
    const wire = heldServer();
    const { calls, signals } = recorded();
    render(<Harness onAnswer={vi.fn()} signals={signals} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await wire.answer(reply(403, challenge(USER)));
    await waitFor(() => expect(calls).toEqual(["sending", "dropped"]));
  });

  it("a re-send with no answer is pending, and the action's own read-back runs, not the host's", async () => {
    const wire = heldServer();
    const { calls, signals } = recorded();
    const own = vi.fn();
    const hostReadBack = vi.fn();
    render(
      <Harness
        onAnswer={vi.fn()}
        readBack={hostReadBack}
        signals={{ ...signals, readBack: own }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    await wire.answer(reply(403, challenge(USER)));
    await answerStepUp();
    await wire.answer(new TypeError("Failed to fetch"));
    await waitFor(() => expect(own).toHaveBeenCalledTimes(1));
    expect(hostReadBack).not.toHaveBeenCalled();
    expect(calls).toEqual(["sending", "held", "pending"]);
    expect(await screen.findByRole("status")).toHaveTextContent(stepUpOutcomePending("Users"));
  });

  it("a renewal is a new send: sending again, then its own end", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    server([reply(403, challenge(USER, "users", 20)), reply(200, { id: USER })]);
    const { calls, signals } = recorded();
    const onAnswer = vi.fn();
    render(<Harness onAnswer={onAnswer} signals={signals} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
    fireEvent.click(await expireChallenge());
    await settle();
    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(calls).toEqual(["sending", "held", "sending", "answered"]);
  });

  it("an action that throws before it routes is failed, and start settles with nothing unhandled", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    let host: StepUpHost | undefined;
    render(<Harness onAnswer={vi.fn()} expose={(h) => (host = h)} />);
    const { calls, signals } = recorded();
    await act(async () => {
      await host?.start(async () => {
        throw new TypeError("deleteUser: the target is not a served user id");
      }, signals);
    });
    expect(calls).toEqual(["sending", "failed"]);
    // A development build names the error, never its message, which may carry a target.
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0]?.[0])).toContain("TypeError");
    expect(String(warn.mock.calls[0]?.[0])).not.toContain("served user id");
  });

  it("an answer handler that throws is its caller's error: start rejects, and the send still settles", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    server([reply(200, { id: USER })]);
    let host: StepUpHost | undefined;
    render(<Harness onAnswer={vi.fn()} expose={(h) => (host = h)} />);
    const { calls, signals } = recorded();
    let thrown: unknown = null;
    await act(async () => {
      await host
        ?.start(async (route) => {
          const res = await sendWrite(holdWrite("PATCH", PATH, newAttempt(), {}), vetAny);
          route(res, () => {
            throw new Error("the page's own handler");
          });
        }, signals)
        .catch((error: unknown) => {
          thrown = error;
        });
    });
    expect(thrown).toBeInstanceOf(Error);
    expect(calls).toEqual(["sending", "answered"]);
    expect(warn).not.toHaveBeenCalled(); // the write was sent and answered: never `failed`
  });

  it("a re-send's answer handler that throws still settles answered; the error stays its own", async () => {
    const wire = heldServer();
    const { calls, signals } = recorded();
    // Nothing awaits the gate's re-send, so the handler's error surfaces unhandled: recorded here.
    const unhandled: unknown[] = [];
    const record = (reason: unknown): void => void unhandled.push(reason);
    process.on("unhandledRejection", record);
    try {
      render(
        <Harness
          onAnswer={() => {
            calls.push("onAnswer");
            throw new Error("the page's own handler");
          }}
          signals={signals}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Disable alex" }));
      await wire.answer(reply(403, challenge(USER)));
      await answerStepUp();
      await wire.answer(reply(200, { id: USER }));
      await waitFor(() => expect(calls).toEqual(["sending", "held", "onAnswer", "answered"]));
      await waitFor(() => expect(unhandled).toHaveLength(1));
    } finally {
      process.off("unhandledRejection", record);
    }
    expect((unhandled[0] as Error).message).toBe("the page's own handler");
  });
});
