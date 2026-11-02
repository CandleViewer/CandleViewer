/**
 * The recorder's step-up host (E16-D02 §6.4; E09-D06 §2 item 7; #2725), the invite screen's pattern
 * made reusable: a write refused with `403 step_up_required` opens SCR-006 through the shared gate,
 * the refused request is held and re-sent once, unchanged, with the same `Idempotency-Key`; a re-send
 * refused by a fresh challenge opens one more cycle, and a further one is the call's ordinary refusal.
 * Esc, the expiry or the third failure drop it ("Not sent"); a renewal re-runs the user's action as a
 * new request, unless the host offers none (a fresh press is then its renewal). No elevation is kept here: the
 * server holds it (C-12.4).
 *
 * The guard every dialog that hosts it gets (#485/#486 BQ-7; S-5353-01): while its write is on the wire,
 * `cancel` keeps the dialog's view (H22), so the answer is the open dialog's, for as long as the gate waits for a
 * re-send (`SEND_BOUND_MS`); past that, `cancel` closes it, saying "Outcome pending" and reading back, as an
 * unanswered re-send does (C-5347-d03). Whatever closes the dialog, and each opening, calls `clear()`, which ends
 * the host's opening. A write belongs to the opening its action started in, through the `route` its action is
 * handed (S-5347-d01): a challenge that answers a write of an ended opening is dropped, never parked for a later
 * dialog nor re-sent, and "Not sent" is said once at the point of action (the page's polite voice).
 */
import { useCallback, useRef, useState, type JSX } from "react";
import type { generated } from "@candleviewer/protocol";
import { RESEND_TIMEOUT_MS, StepUpChallengeGate } from "../stepUp/StepUpChallengeGate";
import { STEP_UP_NOT_SENT, stepUpOutcomePending } from "../stepUp/StepUpDialog";
import { sayPolitely } from "./pageAnnouncer";
import { readResult, type ApiResult, type StepUpHold } from "./recorderApi";

type Op = keyof generated.rest.operations;
type Answer = (res: ApiResult<unknown>) => void;

/**
 * Routes a write's answer: a challenge opens the gate (and its re-send's answer comes back to `onAnswer`); any other
 * answer goes to `onAnswer` now. Bound to the opening its action started in.
 */
export type StepUpRoute = <T>(
  op: Op,
  res: ApiResult<T>,
  onAnswer: (res: ApiResult<T>) => void,
) => void;
/** The user's action: its write, whose answer it routes through the `route` it is handed. */
export type StepUpAction = (route: StepUpRoute) => Promise<void>;

/** How long a dialog keeps its view for a write on the wire: the gate's bound on its re-send (C-5347-d03). */
export const SEND_BOUND_MS = RESEND_TIMEOUT_MS;

interface Pending {
  readonly op: Op;
  readonly hold: StepUpHold;
  readonly onAnswer: Answer;
  /** This challenge refused a re-send: no further one is opened. */
  readonly retried: boolean;
  /** The opening its write started in. */
  readonly opening: number;
}

/** A write on the wire: the opening its action started in, and when it was sent (epoch ms). */
interface Flight {
  readonly opening: number;
  readonly sentAt: number;
}

export interface StepUpHostOptions {
  /** Where "Not sent" and a closed dialog's "Outcome pending" are said: the page's polite voice by default. */
  readonly say?: (text: string) => void;
  /**
   * Whether the gate offers "Request a new confirmation", which re-runs the action as it was pressed (the default). A
   * host whose inputs are editable again once the challenge has expired passes false: its fresh press is the renewal,
   * so what is sent is what the dialog shows (S-5347-d02).
   */
  readonly renewal?: boolean;
}

export interface StepUpHost {
  /**
   * Runs the user's action with a `route` bound to this opening, remembered so a renewal can send it again as a new
   * request (in the opening it is renewed in).
   */
  readonly start: (action: StepUpAction) => Promise<void>;
  /** SCR-006 while a challenge is open, then its notice ("Not sent"); null otherwise. */
  readonly gate: JSX.Element | null;
  /**
   * Drops the challenge and its notice, and ends the host's opening: a new action, the host's dialog closing (by
   * any path) or opening again. A challenge answering a write of an ended opening is dropped and said "Not sent".
   */
  readonly clear: () => void;
  /**
   * The dialog's Cancel, ✕, scrim or Esc: nothing while this opening's write is on the wire, until it has been out
   * `SEND_BOUND_MS` ("Outcome pending, see …" is said then, and the state read back); then `clear()` and `close`.
   */
  readonly cancel: (close: () => void) => void;
}

/** A further challenge after the one re-send: the refusal the screen shows, never a third cycle. */
const refusedAgain = (res: ApiResult<unknown>): ApiResult<unknown> => ({
  ...res,
  stepUp: null,
  route: { kind: "t4", code: res.code, field: null, status: res.status },
});

export function useStepUpHost(
  readBack: () => unknown,
  outcomeWhere: string,
  { say = sayPolitely, renewal = true }: StepUpHostOptions = {},
): StepUpHost {
  const [pending, setPending] = useState<Pending | null>(null);
  const [priorFailures, setPriorFailures] = useState(0);
  const last = useRef<StepUpAction | null>(null);
  /** The host's opening, ended by `clear()`; a write belongs to the opening its action started in. */
  const opening = useRef(0);
  /** Writes on the wire (the grid's host may send several rows' at once). */
  const flights = useRef(new Set<Flight>());
  const latest = useRef({ say, readBack, outcomeWhere });
  latest.current = { say, readBack, outcomeWhere };

  /** Its opening ended while it was on the wire: the challenge is dropped, said once, never parked or re-sent. */
  const orphaned = useCallback((at: number): boolean => {
    if (at === opening.current) return false;
    latest.current.say(STEP_UP_NOT_SENT);
    return true;
  }, []);

  const open = useCallback(
    (op: Op, res: ApiResult<unknown>, onAnswer: Answer, at: number): void => {
      if (res.stepUp === null) onAnswer(res);
      else if (!orphaned(at)) {
        setPending({ op, hold: res.stepUp, onAnswer, retried: false, opening: at });
      }
    },
    [orphaned],
  );

  const run = useCallback(
    async (action: StepUpAction): Promise<void> => {
      const flight: Flight = { opening: opening.current, sentAt: Date.now() };
      const route: StepUpRoute = (op, res, onAnswer) =>
        open(op, res, onAnswer as Answer, flight.opening);
      flights.current.add(flight);
      try {
        await action(route);
      } finally {
        flights.current.delete(flight);
      }
    },
    [open],
  );

  const start = useCallback(
    async (action: StepUpAction): Promise<void> => {
      last.current = action;
      setPending(null);
      setPriorFailures(0);
      await run(action);
    },
    [run],
  );

  async function resent(at: Pending, response: Response): Promise<void> {
    setPending(null);
    const res = await readResult<unknown>(at.op, response, at.hold.held);
    if (res.stepUp !== null && orphaned(at.opening)) return;
    if (res.stepUp !== null && !at.retried) setPending({ ...at, hold: res.stepUp, retried: true });
    else at.onAnswer(res.stepUp === null ? res : refusedAgain(res));
  }

  function renew(failures: number): void {
    setPending(null);
    setPriorFailures(failures);
    const action = last.current;
    if (action !== null) void run(action);
  }

  const clear = useCallback((): void => {
    opening.current += 1;
    setPending(null);
  }, []);

  const cancel = useCallback(
    (close: () => void): void => {
      const mine = [...flights.current].filter((flight) => flight.opening === opening.current);
      if (mine.length > 0) {
        // H22: the answer is the open dialog's while one may still come (C-5347-d03).
        const sentAt = Math.max(...mine.map((flight) => flight.sentAt));
        if (Date.now() - sentAt < SEND_BOUND_MS) return;
        const now = latest.current;
        now.say(stepUpOutcomePending(now.outcomeWhere));
        void (async () => {
          try {
            await now.readBack();
          } catch {
            // The words already point where the outcome shows; a failed read-back changes nothing.
          }
        })();
      }
      clear();
      close();
    },
    [clear],
  );

  const gate =
    pending === null ? null : (
      <StepUpChallengeGate
        key={pending.hold.challenge.challengeId}
        challenge={pending.hold.challenge}
        held={pending.hold.held}
        onResent={(response) => void resent(pending, response)}
        readBack={readBack}
        outcomeWhere={outcomeWhere}
        {...(renewal ? { onRenew: renew } : {})}
        priorFailures={priorFailures}
      />
    );
  return { start, gate, clear, cancel };
}
