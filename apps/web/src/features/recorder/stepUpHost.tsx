/**
 * The recorder's step-up host (E16-D02 §6.4; E09-D06 §2 item 7; #2725), the invite screen's pattern
 * made reusable: a write refused with `403 step_up_required` opens SCR-006 through the shared gate,
 * the refused request is held and re-sent once, unchanged, with the same `Idempotency-Key`; a re-send
 * refused by a fresh challenge opens one more cycle, and a further one is the call's ordinary refusal.
 * Esc, the expiry or the third failure drop it ("Not sent"); a renewal re-runs the user's action as a
 * new request. No elevation is kept here: the server holds it (C-12.4).
 */
import { useCallback, useRef, useState, type JSX } from "react";
import type { generated } from "@candleviewer/protocol";
import { StepUpChallengeGate } from "../stepUp/StepUpChallengeGate";
import { readResult, type ApiResult, type StepUpHold } from "./recorderApi";

type Op = keyof generated.rest.operations;
type Answer = (res: ApiResult<unknown>) => void;

interface Pending {
  readonly op: Op;
  readonly hold: StepUpHold;
  readonly onAnswer: Answer;
  /** This challenge refused a re-send: no further one is opened. */
  readonly retried: boolean;
}

export interface StepUpHost {
  /**
   * Routes a write's answer: a challenge opens the gate (and its re-send's answer comes back to
   * `onAnswer`); any other answer goes to `onAnswer` now.
   */
  readonly route: <T>(op: Op, res: ApiResult<T>, onAnswer: (res: ApiResult<T>) => void) => void;
  /** Runs the user's action, remembered so a renewal can send it again as a new request. */
  readonly start: (action: () => Promise<void>) => Promise<void>;
  /** SCR-006 while a challenge is open, then its notice ("Not sent"); null otherwise. */
  readonly gate: JSX.Element | null;
  /** Drops the notice (a new action, or the host closing). */
  readonly clear: () => void;
}

/** A further challenge after the one re-send: the refusal the screen shows, never a third cycle. */
const refusedAgain = (res: ApiResult<unknown>): ApiResult<unknown> => ({
  ...res,
  stepUp: null,
  route: { kind: "t4", code: res.code, field: null, status: res.status },
});

export function useStepUpHost(readBack: () => unknown, outcomeWhere: string): StepUpHost {
  const [pending, setPending] = useState<Pending | null>(null);
  const [priorFailures, setPriorFailures] = useState(0);
  const last = useRef<(() => Promise<void>) | null>(null);

  const open = useCallback(
    (op: Op, res: ApiResult<unknown>, onAnswer: Answer, retried: boolean) => {
      if (res.stepUp === null) onAnswer(res);
      else if (retried) onAnswer(refusedAgain(res));
      else setPending({ op, hold: res.stepUp, onAnswer, retried: false });
    },
    [],
  );

  const route = useCallback(
    <T,>(op: Op, res: ApiResult<T>, onAnswer: (res: ApiResult<T>) => void): void =>
      open(op, res, onAnswer as Answer, false),
    [open],
  );

  const start = useCallback(async (action: () => Promise<void>): Promise<void> => {
    last.current = action;
    setPending(null);
    setPriorFailures(0);
    await action();
  }, []);

  async function resent(at: Pending, response: Response): Promise<void> {
    setPending(null);
    const res = await readResult<unknown>(at.op, response, at.hold.held);
    if (res.stepUp !== null && !at.retried) setPending({ ...at, hold: res.stepUp, retried: true });
    else at.onAnswer(res.stepUp === null ? res : refusedAgain(res));
  }

  function renew(failures: number): void {
    setPending(null);
    setPriorFailures(failures);
    void last.current?.();
  }

  const clear = useCallback((): void => setPending(null), []);
  const gate =
    pending === null ? null : (
      <StepUpChallengeGate
        key={pending.hold.challenge.challengeId}
        challenge={pending.hold.challenge}
        held={pending.hold.held}
        onResent={(response) => void resent(pending, response)}
        readBack={readBack}
        outcomeWhere={outcomeWhere}
        onRenew={renew}
        priorFailures={priorFailures}
      />
    );
  return { route, start, gate, clear };
}
