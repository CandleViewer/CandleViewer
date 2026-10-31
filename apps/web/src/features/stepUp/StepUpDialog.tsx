import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type JSX,
} from "react";

/** What the user enters in the step-up dialog: the `{password, code}` of the step-up request. */
export interface StepUpCredentials {
  readonly password: string;
  readonly code: string;
}

/**
 * A failed step-up attempt; the text is announced assertively. A refused credential
 * (`credentials`, the default) marks the code field invalid and, on each new `seq`, clears the
 * password and the code and returns focus to the password. Any other failure (no answer, a `5xx`)
 * keeps what was typed.
 */
export interface StepUpFailure {
  readonly message: string;
  readonly seq: number;
  readonly credentials?: boolean;
}

export interface StepUpDialogProps {
  /**
   * The challenge's server-composed `action_summary`, shown verbatim after "Action:" and used,
   * verbatim, as the dialog's accessible description (E09-D06 §6). Never composed by the client.
   */
  readonly actionSummary: string | null;
  /**
   * The challenge's `target`: when not null the user must type it exactly (case-sensitive) before
   * Confirm is enabled (E09-D06 §3, "code+typed confirmation").
   */
  readonly target: string | null;
  /** True while the step-up (and the held request's re-send) is on the wire. */
  readonly submitting?: boolean;
  readonly failure?: StepUpFailure | null;
  /**
   * The expiry warning (A11Y-F-0010), announced once, assertively, inside the dialog: a discrete,
   * high-importance event (05 §6.2), not ambient data.
   */
  readonly warning?: string | null;
  /** Abandons this challenge for a fresh server-issued one; absent, no renewal is offered. */
  readonly onRenew?: (() => void) | undefined;
  readonly onSubmit: (credentials: StepUpCredentials) => void;
  /** Esc or Cancel: a safe no-op for the caller (E09-D06 §5). */
  readonly onCancel: () => void;
}

/** SCR-006 copy (E09-D06 frames `code-only` and `code+confirmation`). */
export const STEP_UP_TITLE = "Confirm with two-factor";
/** The toast of E09-D06 §2 item 7: the held request was dropped without being sent. */
export const STEP_UP_NOT_SENT = "Not sent";
/*
 * PROPOSED copy (#5196, E09-D06 design confirmation pending), like LoginScreen `REASONS`.
 */
/** A11Y-F-0010: the challenge passed `challenge_expires_at`; the held request was dropped. */
export const STEP_UP_EXPIRED =
  "Not sent: the confirmation timed out. Your entries on this page are kept.";
/** A11Y-F-0012: the third invalid code, or `403 session_read_only` (the contract's 5 minutes). */
export const STEP_UP_LOCKED =
  "Incorrect code. Too many attempts: this was not sent, and your session is read-only for 5 minutes.";
/**
 * A11Y-F-0012: `403 session_read_only` answers before either factor is checked (an earlier lock, in
 * this or another tab), so it never says the code was wrong.
 */
export const STEP_UP_READ_ONLY =
  "Not sent: too many incorrect codes, so your session is read-only for 5 minutes.";
/** A11Y-F-0010: abandons the challenge for a fresh one; the old one is never extended. */
export const STEP_UP_RENEW = "Request a new confirmation";
/** A11Y-F-0011: the code field's format instruction. */
export const STEP_UP_CODE_HINT = "6-digit code from your authenticator app";

/**
 * A11Y-F-0010: the warning shown `STEP_UP_WARN_MS` (30 s) before the challenge expires. Fixed text
 * that stays true while it is on screen, never a number that goes stale.
 */
export const STEP_UP_EXPIRY_WARNING =
  "This confirmation expires in less than 30 seconds. Nothing is sent if it expires.";

type Missing = "password" | "code" | "typed";

const CODE = /^[0-9]{6}$/;
const FOCUSABLE = "input:not([disabled]), button:not([disabled])";

const scrim: CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "grid",
  placeItems: "center",
  background: "var(--color-surface-overlay)",
};
const card: CSSProperties = {
  inlineSize: "calc(var(--space-64) + var(--space-48))",
  maxInlineSize: "100%",
  padding: "var(--space-6)",
  display: "flex",
  flexDirection: "column",
  gap: "var(--space-3)",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-lg)",
  fontFamily: "var(--font-family-ui)",
};
const field: CSSProperties = {
  minBlockSize: "var(--size-target-min)",
  padding: "var(--space-2) var(--space-3)",
  background: "var(--color-surface-sunken)",
  color: "var(--color-text-primary)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-md)",
};
const failed: CSSProperties = { ...field, borderColor: "var(--color-status-warning-default)" };
const actions: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: "var(--space-3)",
};
const button: CSSProperties = {
  minBlockSize: "var(--size-target-min)",
  padding: "var(--space-2) var(--space-4)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border-default)",
  background: "var(--color-action-secondary-default)",
  color: "var(--color-text-primary)",
};
const primary: CSSProperties = {
  ...button,
  background: "var(--color-action-primary-default)",
  color: "var(--color-text-on-action)",
};

/**
 * Temporary feature component (#2725): re-base on CMP-043 / CMP-044 (#266) when they land.
 *
 * SCR-006 step-up dialog (E09-D06): `role="alertdialog"`, password + authenticator code, plus a
 * typed confirmation when the challenge names a `target`. Focus starts on the password, Tab is
 * trapped inside, Esc and Cancel call `onCancel`, a scrim click never dismisses, and on close focus
 * returns to the element that had it. Presentational: the caller sends the step-up.
 */
export function StepUpDialog({
  actionSummary,
  target,
  submitting = false,
  failure = null,
  warning = null,
  onRenew,
  onSubmit,
  onCancel,
}: StepUpDialogProps): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const passwordField = useRef<HTMLInputElement>(null);
  const codeField = useRef<HTMLInputElement>(null);
  const typedField = useRef<HTMLInputElement>(null);
  /** A11Y-F-0011: the first unmet requirement of the last incomplete submit, described in text. */
  const [missing, setMissing] = useState<{ field: Missing; seq: number } | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [typed, setTyped] = useState("");
  const seq = failure?.seq;
  const refused = failure !== null && failure.credentials !== false;

  useEffect(() => {
    const opener = document.activeElement;
    passwordField.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  useEffect(() => {
    if (seq === undefined || !refused) return;
    setPassword("");
    setCode("");
    passwordField.current?.focus();
  }, [seq, refused]);

  // Esc cancels and Tab cycles inside the dialog (E09-D06 §5, §6), on the native element so the
  // alertdialog itself takes no React key handler.
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => {
    const node = dialog.current;
    if (node === null) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancel.current();
        return;
      }
      if (event.key !== "Tab") return;
      const stops = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (first === undefined || last === undefined) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    node.addEventListener("keydown", onKeyDown);
    return () => node.removeEventListener("keydown", onKeyDown);
  }, []);

  const unmet: Missing | null =
    password.length === 0
      ? "password"
      : !CODE.test(code)
        ? "code"
        : target !== null && typed !== target
          ? "typed"
          : null;
  const ready = !submitting && unmet === null;

  const missingSeq = missing?.seq;
  const missingField = missing?.field;
  useEffect(() => {
    if (missingSeq === undefined) return;
    const fields = { password: passwordField, code: codeField, typed: typedField };
    if (missingField !== undefined) fields[missingField].current?.focus();
  }, [missingSeq, missingField]);

  // Confirm is aria-disabled, not disabled, so Enter and a click reach here and are explained;
  // nothing is sent until every requirement is met (BQ-10: no factor or confirmation is relaxed).
  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (submitting) return;
    if (unmet !== null) {
      setMissing((m) => ({ field: unmet, seq: (m?.seq ?? 0) + 1 }));
      return;
    }
    setMissing(null);
    onSubmit({ password, code });
  }

  /** An edit to the field a missing-entry message names clears that message and its mark. */
  function edit(f: Missing, set: (value: string) => void, value: string): void {
    set(value);
    if (missing?.field === f) setMissing(null);
  }

  const missingText =
    missing === null
      ? null
      : missing.field === "password"
        ? "Enter your password."
        : missing.field === "code"
          ? "Enter the 6-digit code from your authenticator app."
          : `Type ${target ?? ""} exactly to confirm (case-sensitive).`;
  const marks = (f: Missing): { "aria-invalid"?: true } =>
    missing?.field === f ? { "aria-invalid": true } : {};
  const describe = (...ids: (string | false)[]): string | undefined =>
    ids.filter((i): i is string => i !== false).join(" ") || undefined;

  const describedBy = actionSummary === null ? undefined : `${id}-summary`;
  return (
    <div style={scrim}>
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={describedBy}
        aria-busy={submitting}
        style={card}
      >
        <h2 id={`${id}-title`} style={{ margin: 0, fontSize: "var(--font-size-xl)" }}>
          {STEP_UP_TITLE}
        </h2>
        {actionSummary === null ? null : (
          <p style={{ margin: 0, fontWeight: "var(--font-weight-semibold)" }}>
            Action: <span id={describedBy}>{actionSummary}</span>
          </p>
        )}
        {warning === null ? null : (
          <p role="alert" style={{ margin: 0, color: "var(--color-status-warning-default)" }}>
            {warning}
          </p>
        )}
        <form
          onSubmit={submit}
          noValidate
          style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
        >
          <label htmlFor={`${id}-password`}>Password</label>
          <input
            ref={passwordField}
            id={`${id}-password`}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            {...marks("password")}
            aria-describedby={describe(missing?.field === "password" && `${id}-missing`)}
            style={field}
            value={password}
            onChange={(event) => edit("password", setPassword, event.target.value)}
          />
          <label htmlFor={`${id}-code`}>Authenticator code</label>
          <p id={`${id}-code-hint`} style={{ margin: 0 }}>
            {STEP_UP_CODE_HINT}
          </p>
          <input
            ref={codeField}
            id={`${id}-code`}
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            required
            aria-invalid={refused || missing?.field === "code" ? true : undefined}
            aria-describedby={describe(
              `${id}-code-hint`,
              failure !== null && `${id}-failure`,
              missing?.field === "code" && `${id}-missing`,
            )}
            style={refused ? failed : field}
            value={code}
            onChange={(event) => edit("code", setCode, event.target.value)}
          />
          {failure === null ? null : (
            <p
              id={`${id}-failure`}
              role="alert"
              style={{ margin: 0, color: "var(--color-status-warning-default)" }}
            >
              {failure.message}
            </p>
          )}
          {missingText === null ? null : (
            <p
              id={`${id}-missing`}
              role="alert"
              style={{ margin: 0, color: "var(--color-status-warning-default)" }}
            >
              {missingText}
            </p>
          )}
          {target === null ? null : (
            <>
              <label htmlFor={`${id}-typed`}>Type {target} to confirm (case-sensitive)</label>
              <input
                ref={typedField}
                id={`${id}-typed`}
                name="confirmation"
                autoComplete="off"
                spellCheck={false}
                required
                {...marks("typed")}
                aria-describedby={describe(missing?.field === "typed" && `${id}-missing`)}
                style={field}
                value={typed}
                onChange={(event) => edit("typed", setTyped, event.target.value)}
              />
            </>
          )}
          <div style={actions}>
            {onRenew === undefined || warning === null ? null : (
              <button type="button" style={button} onClick={onRenew} disabled={submitting}>
                {STEP_UP_RENEW}
              </button>
            )}
            <button type="button" style={button} onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" style={primary} aria-disabled={!ready} disabled={submitting}>
              Confirm
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export interface StepUpNoticeProps {
  /** `STEP_UP_NOT_SENT`, or the outcome-pending text of E09-D06 §2 item 4. */
  readonly message: string;
  /** An error and its consequence (A11Y-F-0010, A11Y-F-0012): `role="alert"`, not `status`. */
  readonly assertive?: boolean;
  /** Offers a fresh server-issued challenge after the old one expired (A11Y-F-0010). */
  readonly onRenew?: (() => void) | undefined;
}

/** The status line a step-up leaves behind once its dialog has closed; polite unless `assertive`. */
export function StepUpNotice({
  message,
  assertive = false,
  onRenew,
}: StepUpNoticeProps): JSX.Element {
  const line = (
    <p
      role={assertive ? "alert" : "status"}
      style={{ margin: 0, color: "var(--color-text-primary)" }}
    >
      {message}
    </p>
  );
  if (onRenew === undefined) return line;
  return (
    <div>
      {line}
      <button type="button" onClick={onRenew}>
        {STEP_UP_RENEW}
      </button>
    </div>
  );
}

/**
 * E09-D06 §2 item 4: a re-send that got no answer may have executed, so it is never reported as
 * not sent; the user is pointed at the place whose read-back shows the outcome ("see Orders").
 */
export function stepUpOutcomePending(where: string): string {
  return `Outcome pending, see ${where}`;
}
