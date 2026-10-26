import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type JSX,
} from "react";

/** What the user enters in the step-up dialog (`POST /auth/step-up` `{password, code}`). */
export interface StepUpCredentials {
  readonly password: string;
  readonly code: string;
}

/** A refused step-up: the text is announced assertively; a new `seq` clears the code field. */
export interface StepUpFailure {
  readonly message: string;
  readonly seq: number;
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
  readonly onSubmit: (credentials: StepUpCredentials) => void;
  /** Esc or Cancel: a safe no-op for the caller (E09-D06 §5). */
  readonly onCancel: () => void;
}

/** SCR-006 copy (E09-D06 frames `code-only` and `code+confirmation`). */
export const STEP_UP_TITLE = "Confirm with two-factor";
export const STEP_UP_WHY = "Why: this action needs a fresh authenticator code.";
/** The toast of E09-D06 §2 item 7: the held request was dropped without being sent. */
export const STEP_UP_NOT_SENT = "Not sent";

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
  onSubmit,
  onCancel,
}: StepUpDialogProps): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const passwordField = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [typed, setTyped] = useState("");
  const seq = failure?.seq;

  useEffect(() => {
    const opener = document.activeElement;
    passwordField.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  useEffect(() => {
    if (seq !== undefined) setCode("");
  }, [seq]);

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

  const ready =
    !submitting && password.length > 0 && CODE.test(code) && (target === null || typed === target);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (ready) onSubmit({ password, code });
  }

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
        <p style={{ margin: 0, color: "var(--color-text-secondary)" }}>{STEP_UP_WHY}</p>
        <form
          onSubmit={submit}
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
            style={field}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <label htmlFor={`${id}-code`}>Authenticator code</label>
          <input
            id={`${id}-code`}
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            required
            aria-invalid={failure === null ? undefined : true}
            aria-describedby={failure === null ? undefined : `${id}-failure`}
            style={failure === null ? field : failed}
            value={code}
            onChange={(event) => setCode(event.target.value)}
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
          {target === null ? null : (
            <>
              <label htmlFor={`${id}-typed`}>Type {target} to confirm (case-sensitive)</label>
              <input
                id={`${id}-typed`}
                name="confirmation"
                autoComplete="off"
                spellCheck={false}
                required
                style={field}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
              />
            </>
          )}
          <div style={actions}>
            <button type="button" style={button} onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" style={primary} disabled={!ready}>
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
}

/** The polite status line a step-up leaves behind once its dialog has closed. */
export function StepUpNotice({ message }: StepUpNoticeProps): JSX.Element {
  return (
    <p role="status" style={{ margin: 0, color: "var(--color-text-primary)" }}>
      {message}
    </p>
  );
}

/**
 * E09-D06 §2 item 4: a re-send that got no answer may have executed, so it is never reported as
 * not sent; the user is pointed at the place whose read-back shows the outcome ("see Orders").
 */
export function stepUpOutcomePending(where: string): string {
  return `Outcome pending, see ${where}`;
}
