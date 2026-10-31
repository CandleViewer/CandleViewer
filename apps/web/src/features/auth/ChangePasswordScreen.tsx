import { useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import { changePassword } from "./authApi";

const MIN = 12;

function strength(pw: string): "Weak" | "Fair" | "Strong" {
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  if (pw.length < MIN) return "Weak";
  return pw.length >= 16 && classes >= 3 ? "Strong" : "Fair";
}

/** The field an error belongs to; `null` when the client cannot tell (A11Y-F-0006). */
type Field = "current" | "next" | "confirm";
interface FormError {
  readonly message: string;
  readonly field: Field | null;
  readonly seq: number;
}

/** SCR-004 Forced password change (R-007): no dismiss path. */
export function ChangePasswordScreen(): JSX.Element {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setFormError] = useState<FormError | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const curRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const confRef = useRef<HTMLInputElement>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const longEnough = next.length >= MIN;
  const matches = next !== "" && next === confirm;

  function setError(message: string | null, field: Field | null = null): void {
    setFormError((e) => (message === null ? null : { message, field, seq: (e?.seq ?? 0) + 1 }));
  }

  // focus the field in error, else the summary that holds a message no field owns
  const seq = error?.seq;
  const errorField = error?.field;
  useEffect(() => {
    if (seq === undefined) return;
    const field = { current: curRef, next: nextRef, confirm: confRef };
    (errorField ? field[errorField].current : summary.current)?.focus();
  }, [seq, errorField]);

  /** Editing the field an error belongs to clears that error, its mark and its message. */
  function edit(field: Field, set: (value: string) => void, value: string): void {
    set(value);
    if (error?.field === field) setFormError(null);
  }

  function described(
    field: Field,
    base?: string,
  ): {
    "aria-invalid"?: true;
    "aria-describedby"?: string;
  } {
    const own = error?.field === field;
    const ids = [base, own ? "cp-error" : undefined].filter(Boolean).join(" ");
    return {
      ...(own ? { "aria-invalid": true } : {}),
      ...(ids ? { "aria-describedby": ids } : {}),
    };
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!longEnough) return setError("Use at least 12 characters.", "next");
    if (!matches) return setError("Passwords don't match.", "confirm");
    setError(null);
    setBusy(true);
    const out = await changePassword(current, next);
    setBusy(false);
    if (out === "ok") setDone(true);
    else if (out === "reused") setError("You cannot reuse any of your last 5 passwords.", "next");
    else if (out === "breached") setError("This password appears in a known breach list.", "next");
    else if (out === "unreachable") setError("Cannot reach the server. Try again.");
    else setError("That password was not accepted.");
  }

  if (done) {
    return (
      <main>
        <h1>Password changed</h1>
        <a href="/login">Continue to sign in</a>
      </main>
    );
  }
  const type = reveal ? "text" : "password";
  return (
    <main>
      <h1>Choose a new password</h1>
      <p>You must change your password before continuing.</p>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <div ref={summary} tabIndex={-1} role="alert" id="cp-error">
          {error?.message}
        </div>
        <label htmlFor="cp-cur">Current password</label>
        <input
          id="cp-cur"
          ref={curRef}
          type={type}
          autoComplete="current-password"
          {...described("current")}
          value={current}
          onChange={(e) => edit("current", setCurrent, e.target.value)}
        />
        <label htmlFor="cp-new">New password</label>
        <input
          id="cp-new"
          ref={nextRef}
          type={type}
          autoComplete="new-password"
          value={next}
          {...described("next", "cp-req cp-strength")}
          onChange={(e) => edit("next", setNext, e.target.value)}
        />
        <p id="cp-strength">Strength: {strength(next)}</p>
        <label htmlFor="cp-conf">Confirm new password</label>
        <input
          id="cp-conf"
          ref={confRef}
          type={type}
          autoComplete="new-password"
          {...described("confirm")}
          value={confirm}
          onChange={(e) => edit("confirm", setConfirm, e.target.value)}
        />
        <ul id="cp-req" aria-live="polite" aria-label="Password requirements">
          <li>
            {longEnough ? "Met" : "Not met"}: at least {MIN} characters
          </li>
          <li>{matches ? "Met" : "Not met"}: passwords match</li>
        </ul>
        {/* one stable name; aria-pressed alone carries the state (CMP-201, A11Y-F-0003) */}
        <button type="button" aria-pressed={reveal} onClick={() => setReveal((r) => !r)}>
          Show passwords
        </button>
        <button type="submit" disabled={busy}>
          Change password
        </button>
      </form>
    </main>
  );
}
