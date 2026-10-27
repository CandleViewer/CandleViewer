import { useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import { formatRemaining, login } from "./authApi";

type State = "idle" | "submitting" | "invalid" | "disabled" | "locked" | "unreachable";

const MESSAGES: Record<"invalid" | "disabled" | "unreachable", string> = {
  invalid: "Username or password is incorrect",
  disabled: "Account disabled - contact the owner",
  unreachable: "Cannot reach the server. Check your connection and try again.",
};

/**
 * Why the session ended, by a fixed `reason` key the client itself put on the URL (`endSession`):
 * the line is ours, never text from the URL. PROPOSED copy (#1640 ruling 5, owner approval pending).
 */
const REASONS: Readonly<Record<string, string>> = {
  unlock_attempts: "Signed out after too many unlock attempts.",
};

/** SCR-001 Login (R-001): idle / submitting / invalid / disabled / locked / server-unreachable. */
export function LoginScreen(): JSX.Element {
  const [state, setState] = useState<State>("idle");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const [reason] = useState(() => {
    const key = new URLSearchParams(window.location.search).get("reason");
    return key !== null && Object.hasOwn(REASONS, key) ? REASONS[key] : undefined;
  });

  useEffect(() => {
    if (state !== "locked") return;
    const timer = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          clearInterval(timer);
          setState("idle");
          return 0;
        }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [state]);

  useEffect(() => {
    if (state === "invalid" || state === "disabled" || state === "unreachable" || fieldError) {
      summary.current?.focus();
    }
  }, [state, fieldError]);
  // the reason a session ended is read on arrival: focus moves to the summary that holds it
  useEffect(() => {
    if (reason !== undefined) summary.current?.focus();
  }, [reason]);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (state === "submitting" || state === "locked") return;
    if (identifier.trim() === "") return setFieldError("Enter your username.");
    if (password === "") return setFieldError("Enter your password.");
    setFieldError(null);
    setState("submitting");
    const out = await login(identifier.trim(), password);
    setPassword("");
    if (out.kind === "mfa_required") {
      setMfaToken(out.mfaToken);
      setState("idle");
    } else if (out.kind === "authenticated") {
      window.location.assign("/terminal");
    } else if (out.kind === "locked") {
      setRemaining(out.retryAfterS);
      setState("locked");
    } else setState(out.kind);
  }

  const busy = state === "submitting";
  const locked = state === "locked";
  const message =
    fieldError ??
    (state === "invalid" || state === "disabled" || state === "unreachable"
      ? MESSAGES[state]
      : null);

  if (mfaToken !== null) {
    return (
      <main>
        <h1>Two-factor code</h1>
        <p>Continue in the authenticator step.</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Sign in to CandleViewer</h1>
      <form onSubmit={(e) => void onSubmit(e)} noValidate aria-busy={busy}>
        <div ref={summary} tabIndex={-1} role="alert" id="login-error">
          {message ?? reason}
        </div>
        {locked ? (
          <p role="status" aria-live="polite">
            Too many attempts. Try again in {formatRemaining(remaining)}.
          </p>
        ) : null}
        <label htmlFor="login-id">Username or email</label>
        <input
          id="login-id"
          autoComplete="username"
          value={identifier}
          disabled={busy}
          aria-describedby={message ? "login-error" : undefined}
          onChange={(e) => setIdentifier(e.target.value)}
        />
        <label htmlFor="login-pw">Password</label>
        <input
          id="login-pw"
          type={reveal ? "text" : "password"}
          autoComplete="current-password"
          value={password}
          disabled={busy}
          aria-describedby={message ? "login-error" : undefined}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="button" aria-pressed={reveal} onClick={() => setReveal((r) => !r)}>
          {reveal ? "Hide password" : "Show password"}
        </button>
        <button type="submit" disabled={busy || locked}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
