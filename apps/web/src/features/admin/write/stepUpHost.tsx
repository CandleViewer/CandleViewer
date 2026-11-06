/**
 * The admin area's step-up host (E42-S02; the lane's shared write kit, reused by E42-S04's export and E42-S05): the
 * E09 invite screen's pattern and the recorder's, made generic. An action runs a write and routes its answer; a
 * write refused with `403 step_up_required` opens SCR-006 through the shipped `StepUpChallengeGate`, which re-sends
 * the held request once, unchanged (method, path with its query, `Idempotency-Key`, body), after a step-up for the
 * challenged class. A re-send refused by a fresh challenge opens one more cycle; a further one is the write's
 * refusal, never a third cycle. Esc, Cancel, the expiry or the third failed code drop it ("Not sent"); a renewal
 * runs the action again as a new request (a new attempt). A re-send that got no answer is read back, never sent
 * again (the gate's `readBack`). A write belongs to the host's opening its action started in: once `clear()`, or
 * another action's `start()`, ends that opening, a challenge answering it is dropped and said "Not sent" once, never
 * parked or re-sent. No elevation is kept here: the server holds it (C-12.4).
 *
 * Its signals (`WriteSignals`) tell the action's own in-flight state when to arm and when to settle, once each per
 * send, so no consumer hand-codes them: `onSending` as its write goes on the wire (the first send and a renewal's),
 * then `onSettled` with how that turn ended. The held request's one re-send runs inside SCR-006, which stays open and
 * busy until it answers, so the page under it is never reachable while the request is on the wire.
 */
import { useCallback, useRef, useState, type JSX } from "react";
import { StepUpChallengeGate } from "../../stepUp/StepUpChallengeGate";
import { STEP_UP_NOT_SENT } from "../../stepUp/StepUpDialog";
import type { StepUpRequestBody } from "../../stepUp/challenge";
import type { StepUpHold, WriteResult } from "./writeCall";

/** A step-up class the contract names (`authStepUp`'s `action_class`). */
export type StepUpClass = NonNullable<StepUpRequestBody["action_class"]>;

/**
 * Routes a write's answer: a challenge opens the gate (the re-send's answer comes back to `onAnswer`); any other
 * answer goes to `onAnswer` now. Bound to the opening its action started in.
 */
export type WriteRoute = <T>(res: WriteResult<T>, onAnswer: (res: WriteResult<T>) => void) => void;

/** The user's action: its write, whose answer it routes through the `route` it is handed. */
export type WriteAction = (route: WriteRoute) => Promise<void>;

/**
 * How a send's turn on the wire ended, for the action's in-flight state:
 * - `answered`: its answer reached `onAnswer` (the first send's, or the held request's re-send's). It is signalled
 *   even when `onAnswer` throws, so the action's in-flight state never outlives its answer; the error stays the
 *   caller's (`start()` rejects with it on a first send);
 * - `held`: a challenge holds the request; SCR-006 asks the owner and nothing of it is on the wire. The re-send's
 *   `answered` or `pending` may follow; a challenge the gate drops (Esc, Cancel, its expiry, the third code) ends
 *   there, its notice saying so;
 * - `dropped`: its opening ended first, so its challenge was dropped, never opened ("Not sent", said once);
 * - `pending`: the re-send got no answer, so the gate reads the state back ("Outcome pending");
 * - `failed`: the action threw before it routed an answer. `sendWrite` never throws for a request that went out (no
 *   answer is status 0), so this is a request it could not build: nothing was sent. A development build warns with
 *   the error's name, never its message.
 */
export type WriteEnd = "answered" | "held" | "dropped" | "pending" | "failed";

/** What an action's own state hears from the host, once each per send (all optional). */
export interface WriteSignals {
  /** Its write goes on the wire: the first send, and each renewal's (a new attempt). */
  readonly onSending?: () => void;
  /** Its turn on the wire ended (`WriteEnd`); after `held`, the re-send's `answered` or `pending` may follow. */
  readonly onSettled?: (end: WriteEnd) => void;
  /** Reads the affected state back when the re-send got no answer; the host's `readBack` by default. */
  readonly readBack?: () => unknown;
}

export interface StepUpHostOptions {
  /** The class this host's writes are challenged for (`users`); a challenge naming another is warned in development. */
  readonly stepUpClass: StepUpClass;
  /** Reads the affected state back when a re-send got no answer: it may have executed. */
  readonly readBack: () => unknown;
  /** Where that read-back shows the outcome: "Outcome pending, see {outcomeWhere}". */
  readonly outcomeWhere: string;
  /** The page's polite voice: "Not sent" for a challenge whose opening has ended. */
  readonly say: (text: string) => void;
}

export interface StepUpHost {
  readonly stepUpClass: StepUpClass;
  /**
   * Ends the last action's opening (as `clear()` does) and runs this one in a new one, remembered with its signals
   * so a renewal can run it again.
   */
  readonly start: (action: WriteAction, signals?: WriteSignals) => Promise<void>;
  /** SCR-006 while a challenge is open, then its notice ("Not sent"); null otherwise. */
  readonly gate: JSX.Element | null;
  /**
   * Ends the opening (a dialog closed or opened again; `start()` ends it too): its open challenge and notice go. Never
   * on the close that follows a Confirm, since the write's challenge arrives after it.
   */
  readonly clear: () => void;
}

type Answer = (res: WriteResult<unknown>) => void;

/** An action as started: what a renewal runs again. */
interface Started {
  readonly action: WriteAction;
  readonly signals: WriteSignals | undefined;
}

interface Pending {
  readonly hold: StepUpHold<unknown>;
  readonly onAnswer: Answer;
  /** This challenge refused a re-send: no further one is opened. */
  readonly retried: boolean;
  /** The opening its write started in. */
  readonly opening: number;
  readonly signals: WriteSignals | undefined;
}

const warnClass = (expected: StepUpClass, challenged: string): void => {
  if (import.meta.env?.DEV && challenged !== expected) {
    console.warn(
      `useStepUpHost: a ${challenged} challenge answered a ${expected} write; SCR-006 shows the server's summary.`,
    );
  }
};

/**
 * An action threw before it routed an answer (`failed`: nothing was sent). A development build names the error so
 * a broken `send` or `vet` leaves a trace; its message, which may carry a target, is never logged.
 */
const warnFailed = (error: unknown): void => {
  if (import.meta.env?.DEV) {
    const name = error instanceof Error ? error.name : typeof error;
    console.warn(
      `useStepUpHost: an action threw ${name} before it routed an answer; nothing was sent.`,
    );
  }
};

/** Hands an answer to its handler; the send's turn is settled even when the handler throws (its caller's error). */
function deliver(
  onAnswer: Answer,
  res: WriteResult<unknown>,
  signals: WriteSignals | undefined,
): void {
  try {
    onAnswer(res);
  } finally {
    signals?.onSettled?.("answered");
  }
}

/** A further challenge after the one re-send: the write's refusal, never a third cycle. */
const refusedAgain = (res: WriteResult<unknown>): WriteResult<unknown> => ({
  ...res,
  stepUp: null,
});

export function useStepUpHost({
  stepUpClass,
  readBack,
  outcomeWhere,
  say,
}: StepUpHostOptions): StepUpHost {
  const [pending, setPending] = useState<Pending | null>(null);
  const [priorFailures, setPriorFailures] = useState(0);
  const last = useRef<Started | null>(null);
  /** The host's opening, ended by `clear()` and by the next action's `start()`. */
  const opening = useRef(0);
  const latest = useRef({ say, stepUpClass });
  latest.current = { say, stepUpClass };

  /** Its opening ended while it was on the wire: the challenge is dropped and said once. */
  const orphaned = useCallback((at: number): boolean => {
    if (at === opening.current) return false;
    latest.current.say(STEP_UP_NOT_SENT);
    return true;
  }, []);

  const run = useCallback(
    async ({ action, signals }: Started): Promise<void> => {
      const at = opening.current;
      let routed = false;
      signals?.onSending?.();
      const route: WriteRoute = (res, onAnswer) => {
        routed = true;
        const answer = onAnswer as Answer;
        const hold = res.stepUp as StepUpHold<unknown> | null;
        if (hold === null) {
          deliver(answer, res as WriteResult<unknown>, signals);
        } else if (orphaned(at)) {
          signals?.onSettled?.("dropped");
        } else {
          warnClass(latest.current.stepUpClass, hold.challenge.actionClass);
          setPending({ hold, onAnswer: answer, retried: false, opening: at, signals });
          signals?.onSettled?.("held");
        }
      };
      try {
        await action(route);
      } catch (error) {
        if (routed) throw error; // the action's own answer threw: not its write's failure
        warnFailed(error);
        signals?.onSettled?.("failed"); // a request it could not build: nothing was sent
      }
    },
    [orphaned],
  );

  const start = useCallback(
    async (action: WriteAction, signals?: WriteSignals): Promise<void> => {
      opening.current += 1; // another action ends the last one's opening, whoever forgot to clear it
      const started: Started = { action, signals };
      last.current = started;
      setPending(null);
      setPriorFailures(0);
      await run(started);
    },
    [run],
  );

  async function resent(at: Pending, response: Response): Promise<void> {
    setPending(null);
    const res = await at.hold.read(response);
    if (res.stepUp !== null && orphaned(at.opening)) {
      at.signals?.onSettled?.("dropped");
      return;
    }
    if (res.stepUp !== null && !at.retried) {
      warnClass(latest.current.stepUpClass, res.stepUp.challenge.actionClass);
      setPending({ ...at, hold: res.stepUp, retried: true });
      at.signals?.onSettled?.("held");
    } else {
      deliver(at.onAnswer, res.stepUp === null ? res : refusedAgain(res), at.signals);
    }
  }

  /** The re-send got no answer: its action hears `pending`, and its own read-back (else the host's) runs. */
  function lost(at: Pending): unknown {
    at.signals?.onSettled?.("pending");
    return (at.signals?.readBack ?? readBack)();
  }

  function renew(failures: number): void {
    setPending(null);
    setPriorFailures(failures);
    const started = last.current;
    if (started !== null) void run(started);
  }

  const clear = useCallback((): void => {
    opening.current += 1;
    setPending(null);
  }, []);

  const gate =
    pending === null ? null : (
      <StepUpChallengeGate
        key={pending.hold.challenge.challengeId}
        challenge={pending.hold.challenge}
        held={pending.hold.held}
        onResent={(response) => void resent(pending, response)}
        readBack={() => lost(pending)}
        outcomeWhere={outcomeWhere}
        onRenew={renew}
        priorFailures={priorFailures}
      />
    );
  return { stepUpClass, start, gate, clear };
}
