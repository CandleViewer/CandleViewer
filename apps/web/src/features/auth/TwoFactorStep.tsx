import { useCallback, useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import { OtpInput } from "./OtpInput";
import { RECOVERY_COPY, RecoveryCodeField } from "./RecoveryCodeField";
import {
  RECOVERY_CODE,
  TOTP_CODE,
  formatRemaining,
  verifyRecovery,
  verifyTotp,
  type MfaOutcome,
} from "./authApi";

/**
 * SCR-002 strings: the E09-D12 deck (`E09-D12-copy.json` `auth.mfa.*`), key_status PROPOSED, verbatim.
 * `missing` is SCR-006's existing line for the same field; `warning` is new, PROPOSED (#2711 BQ-06),
 * a row for the deck owner; `unreachable` and the rate-limited line are SCR-001's (LoginScreen).
 */
export const MFA_COPY = {
  heading: "Two-factor code",
  helper: "Code from your authenticator app",
  verify: "Verify",
  invalid: "That code isn't valid.",
  expired: "This code has expired. Please log in again.",
  back: "Back to login",
  missing: "Enter the 6-digit code from your authenticator app.",
  warning: "This sign-in step expires in less than 30 seconds.",
  unreachable: "Cannot reach the server. Check your connection and try again.",
} as const;

const rateLine = (seconds: number): string =>
  `Too many attempts. Try again in ${formatRemaining(seconds)}.`;

/**
 * The service's attempt cap per challenge (`mfa_service.CHALLENGE_ATTEMPT_CAP`). The client's count is a
 * display-only mirror (#2711 BQ-05): it is never rendered, announced, logged or put in an attribute, and
 * only stops the client sending once the server would refuse anyway. The server enforces (C-2.21).
 */
export const MFA_MIRRORED_ATTEMPTS = 5;
/** The warning's lead before the challenge ends (the step-up gate's `STEP_UP_WARN_MS`; WCAG 2.2.1). */
export const MFA_WARN_MS = 30_000;
/** A timer past 2^31 ms would fire at once. */
const MAX_DELAY_MS = 2 ** 31 - 1;
const delay = (ms: number): number => Math.min(Math.max(ms, 0), MAX_DELAY_MS);

type Phase =
  "idle" | "verifying" | "invalid" | "missing" | "rate_limited" | "unreachable" | "expired";
type Mode = "totp" | "recovery";
type FocusTarget = "heading" | "field" | "alert" | "back";

export interface TwoFactorStepProps {
  /** When the challenge ends (epoch ms), fixed once from `expires_in` at receipt; never extended. */
  readonly deadline: number;
  /** The challenge handle, held by the caller in memory only; `null` once dropped. */
  readonly takeHandle: () => string | null;
  /** Drops the handle: at expiry, at the mirrored cap and on success. */
  readonly dropHandle: () => void;
  /** "Back to login": SCR-001 again. */
  readonly onBack: () => void;
}

/**
 * SCR-002 TOTP challenge (E09-D12 §5.2), in place on R-001 (#2711 BQ-02): idle, verifying, invalid-code,
 * expired-challenge (also the lockout), rate-limited, unreachable, and the recovery-code entry behind
 * `__CV_MFA_RECOVERY_UI__` (BQ-08 (a)). One request per submission: paste, Enter and Verify while one
 * is on the wire do nothing, and an answer for a superseded or ended submission is dropped (BQ-09).
 * Outcomes key on the status alone (BQ-04); a refused code always reads the same (F-2).
 */
export function TwoFactorStep({
  deadline,
  takeHandle,
  dropHandle,
  onBack,
}: TwoFactorStepProps): JSX.Element {
  const [mode, setMode] = useState<Mode>("totp");
  const [phase, setPhase] = useState<Phase>("idle");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState("");
  const [remaining, setRemaining] = useState(0);
  /** The rate-limited line as it read on arrival: announced once, never per second. */
  const [rateSpoken, setRateSpoken] = useState("");
  const [warning, setWarning] = useState(false);
  const [focus, setFocus] = useState<{ readonly target: FocusTarget; readonly n: number }>({
    target: "heading",
    n: 0,
  });
  const heading = useRef<HTMLHeadingElement>(null);
  const otp = useRef<HTMLInputElement>(null);
  const recoveryField = useRef<HTMLInputElement>(null);
  const alertRegion = useRef<HTMLDivElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  const failures = useRef(0);
  const sequence = useRef(0);
  const inflight = useRef(false);
  const ended = useRef(false);
  const blocked = useRef(false);

  const focusTo = useCallback((target: FocusTarget): void => {
    setFocus((f) => ({ target, n: f.n + 1 }));
  }, []);

  useEffect(() => {
    const el =
      focus.target === "heading"
        ? heading.current
        : focus.target === "field"
          ? (otp.current ?? recoveryField.current)
          : focus.target === "alert"
            ? alertRegion.current
            : back.current;
    el?.focus();
  }, [focus]);

  /** Ends the challenge: nothing is sent after this, and any answer still on the wire is dropped. */
  const finish = useCallback((): void => {
    ended.current = true;
    sequence.current += 1;
    inflight.current = false;
    dropHandle();
  }, [dropHandle]);

  const expire = useCallback((): void => {
    if (ended.current) return;
    finish();
    setCode("");
    setRecovery("");
    setWarning(false);
    setPhase("expired");
    focusTo("back");
  }, [finish, focusTo]);

  useEffect(() => {
    ended.current = false;
    return () => {
      ended.current = true; // unmounted: a late answer changes nothing
      sequence.current += 1;
    };
  }, []);

  useEffect(() => {
    const now = Date.now();
    const warn = setTimeout(
      () => {
        if (!ended.current) setWarning(true);
      },
      delay(deadline - MFA_WARN_MS - now),
    );
    const end = setTimeout(expire, delay(deadline - now));
    return () => {
      clearTimeout(warn);
      clearTimeout(end);
    };
  }, [deadline, expire]);

  useEffect(() => {
    if (phase !== "rate_limited") return;
    // the updater stays pure (StrictMode runs it twice); the end of the countdown is the effect below
    const timer = setInterval(() => setRemaining((r) => Math.max(r - 1, 0)), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  useEffect(() => {
    if (phase !== "rate_limited" || remaining > 0) return;
    blocked.current = false;
    setPhase("idle");
  }, [phase, remaining]);

  const recovering = __CV_MFA_RECOVERY_UI__ && mode === "recovery";

  function settle(out: MfaOutcome): void {
    if (out.kind === "authenticated") {
      finish();
      // ADR-0020: the page load re-derives the access token from the refresh cookie; none is kept here
      window.location.assign(out.enrolmentOnly ? "/login/2fa/enroll" : "/terminal");
      return;
    }
    if (out.kind === "invalid" || out.kind === "refused") {
      if (out.kind === "invalid") failures.current += 1;
      if (failures.current >= MFA_MIRRORED_ATTEMPTS) return expire();
      setCode("");
      setRecovery("");
      setPhase("invalid");
      focusTo("field");
      return;
    }
    if (out.kind === "rate_limited") {
      blocked.current = true;
      setRemaining(out.retryAfterS);
      setRateSpoken(rateLine(out.retryAfterS));
      setPhase("rate_limited");
      focusTo("alert");
      return;
    }
    setPhase("unreachable");
    focusTo("alert");
  }

  async function send(value: string): Promise<void> {
    if (ended.current || inflight.current || blocked.current) return;
    const ok = recovering ? RECOVERY_CODE.test(value) : TOTP_CODE.test(value);
    if (!ok) {
      setPhase(recovering ? "invalid" : "missing");
      focusTo("field");
      return;
    }
    const handle = takeHandle();
    if (handle === null) return expire();
    inflight.current = true;
    sequence.current += 1;
    const mine = sequence.current;
    setPhase("verifying");
    const out = recovering ? await verifyRecovery(handle, value) : await verifyTotp(handle, value);
    if (mine !== sequence.current || ended.current) return; // superseded or ended: dropped
    inflight.current = false;
    settle(out);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void send(recovering ? recovery.trim() : code);
  }

  function edit(set: (value: string) => void, value: string): void {
    set(value);
    if (phase === "invalid" || phase === "missing") setPhase("idle");
  }

  function toggleMode(): void {
    if (inflight.current || ended.current) return;
    setMode((m) => (m === "totp" ? "recovery" : "totp"));
    setCode("");
    setRecovery("");
    if (phase === "invalid" || phase === "missing") setPhase("idle");
    focusTo("field");
  }

  const busy = phase === "verifying";
  const rateLimited = phase === "rate_limited";
  const fieldError =
    phase === "invalid"
      ? recovering
        ? RECOVERY_COPY.invalid
        : MFA_COPY.invalid
      : phase === "missing"
        ? MFA_COPY.missing
        : null;
  const describedBy = (base?: string): string | undefined =>
    [base, fieldError === null ? undefined : "mfa-error"].filter(Boolean).join(" ") || undefined;

  return (
    <main>
      <h1 id="mfa-heading" ref={heading} tabIndex={-1}>
        {MFA_COPY.heading}
      </h1>
      {phase === "expired" ? (
        <>
          <div role="alert">{MFA_COPY.expired}</div>
          <button type="button" ref={back} onClick={onBack}>
            {MFA_COPY.back}
          </button>
        </>
      ) : (
        <form onSubmit={onSubmit} noValidate aria-busy={busy}>
          {/* form-level failures only (a 429 or an unreachable server), focused on arrival (CMP-200) */}
          <div ref={alertRegion} tabIndex={-1} role="alert" id="mfa-alert">
            {rateLimited ? (
              <>
                <span className="cv-visually-hidden">{rateSpoken}</span>
                <span aria-hidden="true">{rateLine(remaining)}</span>
              </>
            ) : phase === "unreachable" ? (
              MFA_COPY.unreachable
            ) : null}
          </div>
          {__CV_MFA_RECOVERY_UI__ && mode === "recovery" ? (
            <RecoveryCodeField
              ref={recoveryField}
              value={recovery}
              onChange={(v) => edit(setRecovery, v)}
              describedBy={describedBy()}
              invalid={fieldError !== null}
              busy={busy}
            />
          ) : (
            <>
              <p id="mfa-helper">{MFA_COPY.helper}</p>
              <OtpInput
                ref={otp}
                id="mfa-code"
                value={code}
                onChange={(v) => edit(setCode, v)}
                onComplete={(v) => void send(v)}
                labelledBy="mfa-heading"
                describedBy={describedBy("mfa-helper")}
                invalid={fieldError !== null}
                busy={busy}
              />
            </>
          )}
          {fieldError === null ? null : <p id="mfa-error">{fieldError}</p>}
          <button type="submit" aria-disabled={busy || rateLimited ? true : undefined}>
            {MFA_COPY.verify}
          </button>
          {__CV_MFA_RECOVERY_UI__ ? (
            <button type="button" aria-disabled={busy ? true : undefined} onClick={toggleMode}>
              {mode === "totp" ? RECOVERY_COPY.use : RECOVERY_COPY.back}
            </button>
          ) : null}
        </form>
      )}
      {/* the one polite region: the expiry warning, once (BQ-06); never a count or a time left */}
      <p role="status">{warning && phase !== "expired" ? MFA_COPY.warning : null}</p>
    </main>
  );
}
