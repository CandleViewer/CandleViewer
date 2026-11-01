import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type JSX,
  type RefObject,
} from "react";
import { accessToken } from "../../lib/auth/accessToken";
import { useFocusOnView } from "../app-shell/useFocusOnView";
import { changePassword, type ChangePasswordOutcome, type PasswordRefusal } from "./authApi";
import { PasswordField } from "./password/PasswordField";
import {
  PasswordStrengthMeter,
  RequirementChecklist,
  STATE_WORDS,
} from "./password/RequirementChecklist";
import {
  MIN_LENGTH,
  codePoints,
  containsIdentity,
  evaluate,
  meterWord,
  strengthScore,
  type Identity,
  type ServerVerdicts,
} from "./password/policy";

/** The E09-D05 §11.1 copy deck: every string this screen shows (W-n), none from a server `detail`. */
export const PW_COPY = {
  heading: "Choose a new password", // W-21
  explanation: "An owner requires you to choose a new password before you continue.", // W-23
  current: "Current password",
  next: "New password",
  confirm: "Confirm new password",
  submit: "Change password", // W-29
  busy: "Changing password…", // W-19
  slow: "Still working — the server is slow to answer.", // W-20
  identity: "Doesn't contain your username or email", // W-5
  tooShort: `Use at least ${MIN_LENGTH} characters.`, // W-9 (`14` SCR-004, C-85)
  breached: "This password appears in a known breach list.", // W-10
  mismatch: "Passwords don't match.", // W-11
  reused: "You can't reuse any of your last 5 passwords.", // W-12
  cleared: "We cleared both new password fields so the rejected password isn't sent again.", // W-13
  tooLong: "Use at most 512 characters.", // W-14
  refused: "That password was not accepted.", // W-15
  currentInvalid: "Your current password is incorrect.", // W-16
  unreachable: "Can't reach the server. Check your connection and try again.", // W-18
  retry: "Retry",
  readOnly: "Not sent — read-only after three wrong codes.", // W-32
  doneHeading: "Password changed", // W-24
  doneBody: "You've been signed out on your other devices. This device stays signed in.", // W-25
  doneAction: "Continue", // W-26
} as const;

/** W-17, the countdown from the `429`'s `Retry-After` only (E09-D05 §6.1). */
export const rateLine = (seconds: number): string => {
  const s = Math.max(0, Math.ceil(seconds));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  return `Too many attempts. Try again in ${mm}:${String(s % 60).padStart(2, "0")}.`;
};

const REFUSAL_COPY: Readonly<Record<PasswordRefusal, string>> = {
  breached: PW_COPY.breached,
  reused: PW_COPY.reused,
  too_short: PW_COPY.tooShort,
  too_long: PW_COPY.tooLong,
  identity: PW_COPY.identity,
  other: PW_COPY.refused,
};
const REFUSAL_ITEM: Partial<Record<PasswordRefusal, keyof ServerVerdicts>> = {
  breached: "breach",
  reused: "reuse",
  identity: "identity",
};
/** The status node speaks after the user stops typing (`15`:2569). */
export const ANNOUNCE_DEBOUNCE_MS = 500;
/** D08:344: the slow-path line, once, this long after the press. */
export const SLOW_MS = 5_000;

type Field = "current" | "next" | "confirm";
type FieldErrors = { [K in Field]?: string | undefined };
type Phase = "idle" | "busy" | "rate_limited" | "unreachable" | "done";
type FocusTarget = Field | "alert" | "submit";
/**
 * E09-D05 §13.1: the card is `color.surface.raised` with `color.text.primary`. The checklist and the
 * meter bind the text tokens of that pair (§13.2 P-1, P-2), so they must sit on it and not on the
 * bare canvas, where the dark tokens measured 1.96:1 and 1.2:1 under axe.
 */
const CARD: CSSProperties = {
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
};

const NO_REVEAL: Readonly<Record<Field, boolean>> = { current: false, next: false, confirm: false };

/**
 * SCR-004 Forced password change (R-007; E09-D05, the hi-fi delta of hand-off §D): the five-item
 * checklist and the meter (§4), each field's own error with focus to it (§9.1), both new fields
 * cleared after a refusal with W-13 (§6.1), the server's answers by problem code (§6.1), D08's busy
 * rule (§5.3) and the success card (§7.1): the session was rotated, so this device stays signed in.
 * The identity item is client-evaluated only when the host passes the user's `identity`.
 */
export function ChangePasswordScreen(props: { readonly identity?: Identity }): JSX.Element {
  const { identity } = props;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [revealed, setRevealed] = useState(NO_REVEAL);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [cleared, setCleared] = useState(false);
  const [verdicts, setVerdicts] = useState<ServerVerdicts>({});
  const [phase, setPhase] = useState<Phase>("idle");
  const [alertText, setAlertText] = useState<string | null>(null);
  const [submitReason, setSubmitReason] = useState<string | null>(null);
  // the 429's countdown: derived from a deadline, so no state updater has a side effect
  const [deadline, setDeadline] = useState(0);
  const [now, setNow] = useState(0);
  const [rateSpoken, setRateSpoken] = useState("");
  const [slow, setSlow] = useState(false);
  const [status, setStatus] = useState("");
  // entry on the forced page: focus the current-password field in the frame of the cut (§9.1)
  const [focus, setFocus] = useState<{ readonly target: FocusTarget; readonly n: number } | null>({
    target: "current",
    n: 0,
  });
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const alertRef = useRef<HTMLDivElement>(null);
  const submitRef = useRef<HTMLButtonElement>(null);

  const items = useMemo(
    () => evaluate(next, confirm, identity, verdicts),
    [next, confirm, identity, verdicts],
  );
  const lengthMet = codePoints(next) >= MIN_LENGTH;
  const word = meterWord(strengthScore(next), lengthMet);
  const busy = phase === "busy";
  const rateLimited = phase === "rate_limited";
  // the form -> done change moves focus to the new view's heading (E47-S05, A11Y-P-02, CMP-200)
  const heading = useFocusOnView(phase === "done" ? "done" : "form");
  const remaining = rateLimited ? Math.max(0, Math.ceil((deadline - now) / 1000)) : 0;

  const focusTo = (target: FocusTarget): void => setFocus((f) => ({ target, n: (f?.n ?? 0) + 1 }));
  useEffect(() => {
    if (focus === null) return;
    const targets: Readonly<Record<FocusTarget, RefObject<HTMLElement | null>>> = {
      current: currentRef,
      next: nextRef,
      confirm: confirmRef,
      alert: alertRef,
      submit: submitRef,
    };
    targets[focus.target].current?.focus();
  }, [focus]);

  // one polite status node speaks only what changed, 500 ms after the last keystroke (§4.2, AC6)
  const spoken = useRef({ items, word });
  useEffect(() => {
    const timer = setTimeout(() => {
      const before = spoken.current;
      const changed = items.filter((item, i) => before.items[i]?.state !== item.state);
      const parts = changed.map((item) => `${item.label}: ${STATE_WORDS[item.state]}`);
      if (before.word !== word) parts.push(`Strength: ${word}`);
      spoken.current = { items, word };
      if (parts.length > 0) setStatus(parts.join(". "));
    }, ANNOUNCE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [items, word]);

  useEffect(() => {
    if (!busy) return;
    const timer = setTimeout(() => setSlow(true), SLOW_MS);
    return () => clearTimeout(timer);
  }, [busy]);

  useEffect(() => {
    if (!rateLimited) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [rateLimited]);
  useEffect(() => {
    if (rateLimited && remaining <= 0) setPhase("idle");
  }, [rateLimited, remaining]);

  function editNext(value: string): void {
    setNext(value);
    setVerdicts({});
    setCleared(false);
    setErrors((e) => ({
      ...e,
      next: undefined,
      confirm: e.confirm !== undefined && value === confirm ? undefined : e.confirm,
    }));
  }

  /** The press with an unmet client item: each failing field's error, focus to the first (§9.1). */
  function clientErrors(): FieldErrors {
    const found: FieldErrors = {};
    if (current === "") found.current = PW_COPY.currentInvalid;
    if (!lengthMet) found.next = PW_COPY.tooShort;
    else if (identity !== undefined && containsIdentity(next, identity)) {
      found.next = PW_COPY.identity;
    }
    if (next !== confirm) found.confirm = PW_COPY.mismatch;
    return found;
  }

  function settle(out: ChangePasswordOutcome): void {
    setSlow(false);
    setPhase("idle");
    switch (out.kind) {
      case "changed":
        setCurrent("");
        setNext("");
        setConfirm("");
        setPhase("done"); // useFocusOnView focuses the done heading
        return;
      case "current_invalid":
        setCurrent("");
        setErrors({ current: PW_COPY.currentInvalid });
        return focusTo("current");
      case "refused": {
        setNext("");
        setConfirm("");
        setCleared(true);
        const item = REFUSAL_ITEM[out.reason];
        setVerdicts(item === undefined ? {} : { [item]: true });
        setErrors({ next: REFUSAL_COPY[out.reason] });
        return focusTo("next");
      }
      case "rate_limited": {
        const at = Date.now();
        setNow(at);
        setDeadline(at + out.retryAfterS * 1000);
        setRateSpoken(rateLine(out.retryAfterS));
        setPhase("rate_limited");
        return focusTo("alert");
      }
      case "read_only":
        setSubmitReason(PW_COPY.readOnly);
        return focusTo("submit");
      case "enrolment_required":
        window.location.assign("/login/2fa/enroll");
        return;
      case "signed_out":
        accessToken.endSession();
        return;
      case "locked":
        // SCR-005 takes over (`accessToken.onLocked`); the session lives on, no password stays typed
        setCurrent("");
        setNext("");
        setConfirm("");
        return;
      case "sign_in_again":
        // the new password may already stand: never re-sent (a retry could count lockout strikes)
        setCurrent("");
        setNext("");
        setConfirm("");
        accessToken.endSession();
        return;
      case "not_allowed":
        setAlertText(PW_COPY.refused);
        return focusTo("alert");
      case "unreachable":
        setAlertText(PW_COPY.unreachable);
        setPhase("unreachable");
        return focusTo("alert");
    }
  }

  async function send(): Promise<void> {
    if (busy) return;
    if (rateLimited) {
      // G-T2.3: a press on the held submit changes nothing and says why, once, politely
      setStatus(rateLine(remaining));
      return;
    }
    setRevealed(NO_REVEAL);
    const found = clientErrors();
    const first = (["current", "next", "confirm"] as const).find((f) => found[f] !== undefined);
    setAlertText(null);
    setSubmitReason(null);
    if (first !== undefined) {
      setErrors(found);
      return focusTo(first);
    }
    setErrors({});
    setPhase("busy");
    settle(await changePassword(current, next));
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void send();
  }

  if (phase === "done") {
    return (
      <main style={CARD}>
        <h1 ref={heading}>{PW_COPY.doneHeading}</h1>
        <p>{PW_COPY.doneBody}</p>
        <button type="button" onClick={() => window.location.assign("/terminal")}>
          {PW_COPY.doneAction}
        </button>
      </main>
    );
  }

  const reveal = (field: Field) => ({
    revealed: revealed[field],
    onRevealedChange: (on: boolean) => setRevealed((r) => ({ ...r, [field]: on })),
  });
  const submitDisabled = busy || rateLimited;
  return (
    <main aria-describedby="cp-explain" style={CARD}>
      <h1 ref={heading}>{PW_COPY.heading}</h1>
      <p id="cp-explain">{PW_COPY.explanation}</p>
      <form onSubmit={onSubmit} noValidate aria-busy={busy}>
        {/* form-level failures only (a 429 or an unreachable server), focused on arrival (CMP-200) */}
        <div ref={alertRef} tabIndex={-1} role="alert" id="cp-alert">
          {rateLimited ? (
            <>
              <span className="cv-visually-hidden">{rateSpoken}</span>
              <span aria-hidden="true">{rateLine(remaining)}</span>
            </>
          ) : (
            alertText
          )}
        </div>
        {phase === "unreachable" ? (
          <button type="button" onClick={() => void send()}>
            {PW_COPY.retry}
          </button>
        ) : null}
        <PasswordField
          id="cp-cur"
          label={PW_COPY.current}
          autoComplete="current-password"
          value={current}
          onChange={(v) => {
            setCurrent(v);
            setErrors((e) => ({ ...e, current: undefined }));
          }}
          error={errors.current}
          readOnly={busy}
          inputRef={currentRef}
          {...reveal("current")}
        />
        <PasswordField
          id="cp-new"
          label={PW_COPY.next}
          autoComplete="new-password"
          value={next}
          onChange={editNext}
          error={errors.next}
          note={cleared ? PW_COPY.cleared : null}
          describedBy="cp-req cp-strength"
          readOnly={busy}
          inputRef={nextRef}
          {...reveal("next")}
        />
        <RequirementChecklist id="cp-req" items={items} />
        <PasswordStrengthMeter id="cp-strength" word={word} />
        <PasswordField
          id="cp-conf"
          label={PW_COPY.confirm}
          autoComplete="new-password"
          value={confirm}
          onChange={(v) => {
            setConfirm(v);
            setErrors((e) => ({ ...e, confirm: undefined }));
          }}
          onBlur={() => {
            if (confirm !== "" && confirm !== next) {
              setErrors((e) => ({ ...e, confirm: PW_COPY.mismatch }));
            }
          }}
          error={errors.confirm}
          readOnly={busy}
          inputRef={confirmRef}
          {...reveal("confirm")}
        />
        <button
          ref={submitRef}
          type="submit"
          aria-disabled={submitDisabled}
          aria-describedby={
            rateLimited ? "cp-alert" : submitReason ? "cp-submit-reason" : undefined
          }
        >
          {busy ? PW_COPY.busy : PW_COPY.submit}
        </button>
        {submitReason ? <p id="cp-submit-reason">{submitReason}</p> : null}
        <p role="status" aria-live="polite" id="cp-slow">
          {busy && slow ? PW_COPY.slow : ""}
        </p>
      </form>
      <div role="status" aria-live="polite" aria-atomic="true" className="cv-visually-hidden">
        {status}
      </div>
    </main>
  );
}
