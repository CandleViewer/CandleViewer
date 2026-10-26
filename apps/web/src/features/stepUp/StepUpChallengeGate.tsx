import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import {
  STEP_UP_NOT_SENT,
  StepUpDialog,
  StepUpNotice,
  stepUpOutcomePending,
  type StepUpCredentials,
  type StepUpFailure,
} from "@candleviewer/ui";
import { recordStepUp } from "../../lib/auth/meCache";
import { apiFetch } from "../../lib/http/csrfFetch";
import {
  STEP_UP_PATH,
  isStaleChallenge,
  sendHeld,
  type HeldRequest,
  type StepUpChallenge,
  type StepUpGranted,
  type StepUpRequestBody,
} from "./challenge";

/** The third consecutive invalid code downgrades the session to read-only (`session_read_only`). */
export const MAX_STEP_UP_FAILURES = 3;
/** The one generic refusal text: it never reveals which factor failed. */
export const STEP_UP_INVALID = "Invalid password or code.";
/** A timer past 2^31 ms would fire at once. */
const MAX_DELAY_MS = 2 ** 31 - 1;

export interface StepUpChallengeGateProps {
  readonly challenge: StepUpChallenge;
  /** The refused request, held unchanged; sent again at most once, after a matching `200`. */
  readonly held: HeldRequest;
  /** The answer to the re-send, whatever its status. */
  readonly onResent: (response: Response) => void;
  /**
   * Reads the affected state back when the re-send got no answer (a network error or a timeout):
   * the action may have executed, so it is neither reported as not sent nor re-sent (E09-D06 §2.4).
   */
  readonly readBack: () => unknown;
  /** Where the read-back shows the outcome, for "Outcome pending, see …" (E09-D06 §2 item 4). */
  readonly outcomeWhere: string;
}

type Stage = "dialog" | "not-sent" | "pending" | "done";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

/** A refusal after which the challenge cannot be answered: the held request is dropped unsent. */
function endsChallenge(status: number, body: unknown): boolean {
  const code = isRecord(body) ? body["code"] : undefined;
  if (status === 401) return code !== "mfa_invalid"; // idle lock, absolute expiry, revocation
  if (status === 403) return code === "session_read_only";
  return isStaleChallenge(status, body);
}

/**
 * Answers one `403 step_up_required` challenge (#2725): SCR-006 restates `action_summary`, the step-up
 * sends `challenge_id`, and the held request is re-sent once after a `200` for the challenged class.
 * Esc / Cancel, `challenge_expires_at`, a class mismatch, the third failure, idle lock, absolute expiry
 * and a stale-challenge `400` drop it unsent and leave "Not sent" (E09-D06 §2 item 7).
 */
export function StepUpChallengeGate({
  challenge,
  held,
  onResent,
  readBack,
  outcomeWhere,
}: StepUpChallengeGateProps): JSX.Element | null {
  const [stage, setStage] = useState<Stage>("dialog");
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<StepUpFailure | null>(null);
  /** Set once the held request is dropped or re-sent: it is never sent (again) after that. */
  const settled = useRef(false);
  const failures = useRef(0);

  const drop = useCallback((): void => {
    if (settled.current) return;
    settled.current = true;
    setStage("not-sent");
  }, []);

  useEffect(() => {
    settled.current = false;
    return () => {
      settled.current = true; // unmounted: nothing may send it any more
    };
  }, []);

  useEffect(() => {
    const ms = Date.parse(challenge.expiresAt) - Date.now();
    const timer = setTimeout(drop, Number.isNaN(ms) ? 0 : Math.min(Math.max(ms, 0), MAX_DELAY_MS));
    return () => clearTimeout(timer);
  }, [challenge.expiresAt, drop]);

  function refuse(): void {
    setSubmitting(false);
    setFailure((prev) => ({ message: STEP_UP_INVALID, seq: (prev?.seq ?? 0) + 1 }));
  }

  async function resend(): Promise<void> {
    settled.current = true;
    let answer: Response;
    try {
      answer = await sendHeld(held);
    } catch {
      setStage("pending");
      try {
        await readBack();
      } catch {
        // The notice already points at where the outcome shows; a failed read-back changes nothing.
      }
      return;
    }
    setStage("done");
    onResent(answer);
  }

  async function submit({ password, code }: StepUpCredentials): Promise<void> {
    setSubmitting(true);
    const request: StepUpRequestBody = { password, code, challenge_id: challenge.challengeId };
    let response: Response;
    try {
      response = await apiFetch(STEP_UP_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
    } catch {
      if (!settled.current) refuse();
      return;
    }
    const body: unknown = await response.json().catch(() => null);
    if (settled.current) return; // dropped meanwhile (Esc, expiry): never re-sent
    if (response.ok) {
      const granted = body as Partial<StepUpGranted> | null;
      if (granted?.action_class !== challenge.actionClass) return drop();
      if (typeof granted.elevated_until === "string") {
        recordStepUp(granted.elevated_until, granted.step_up_expires_at ?? null);
      }
      return resend();
    }
    if (endsChallenge(response.status, body)) return drop();
    if (response.status === 401) {
      failures.current += 1;
      if (failures.current >= MAX_STEP_UP_FAILURES) return drop();
    }
    refuse();
  }

  if (stage === "not-sent") return <StepUpNotice message={STEP_UP_NOT_SENT} />;
  if (stage === "pending") return <StepUpNotice message={stepUpOutcomePending(outcomeWhere)} />;
  if (stage === "done") return null;
  return (
    <StepUpDialog
      actionSummary={challenge.actionSummary}
      target={challenge.target}
      submitting={submitting}
      failure={failure}
      onSubmit={(credentials) => void submit(credentials)}
      onCancel={drop}
    />
  );
}
