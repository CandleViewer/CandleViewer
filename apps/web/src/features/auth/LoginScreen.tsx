import { useCallback, useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import { formatRemaining, login } from "./authApi";
import { TwoFactorStep } from "./TwoFactorStep";

type State = "idle" | "submitting" | "invalid" | "rate_limited" | "unreachable";

/**
 * Every failed sign-in renders the one `invalid` string, whatever the cause (SR-014, #4961): the
 * deck's frozen `auth.login.failed` (E09-D12 §8.2 (1)), byte for byte (#5254 DF-1).
 */
const MESSAGES: Record<"invalid" | "unreachable", string> = {
  invalid: "Couldn't sign you in. Check your details and try again.",
  unreachable: "Cannot reach the server. Check your connection and try again.",
};

/**
 * Why the session ended, by a fixed `reason` key the client itself put on the URL (`endSession`):
 * the line is ours, never text from the URL. PROPOSED copy (#1640 ruling 5, owner approval pending).
 */
const REASONS: Readonly<Record<string, string>> = {
  unlock_attempts: "Signed out after too many unlock attempts.",
};

/** SCR-001 Login (R-001): idle / submitting / invalid / rate-limited / server-unreachable. */
export function LoginScreen(): JSX.Element {
  const [state, setState] = useState<State>("idle");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  /**
   * The SCR-002 challenge (#2711 BQ-02): its handle lives in this ref only, taken from the in-memory
   * `login()` outcome, never from the URL, history state, storage or the DOM, and never logged. A new
   * `mfa_required` replaces it; `id` remounts the step, so a stale handle is never sent.
   */
  const handle = useRef<string | null>(null);
  const [challenge, setChallenge] = useState<{ id: number; deadline: number } | null>(null);
  const [returned, setReturned] = useState(0);
  const identifierField = useRef<HTMLInputElement>(null);
  const summary = useRef<HTMLDivElement>(null);
  const rateLimitLine = useRef<HTMLParagraphElement>(null);
  const [reason] = useState(() => {
    const key = new URLSearchParams(window.location.search).get("reason");
    return key !== null && Object.hasOwn(REASONS, key) ? REASONS[key] : undefined;
  });

  useEffect(() => {
    if (state !== "rate_limited") return;
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
    if (state === "invalid" || state === "unreachable" || fieldError) {
      summary.current?.focus();
    }
  }, [state, fieldError]);
  // the reason a session ended is read on arrival: focus moves to the summary that holds it
  // ...otherwise R-001's arrival focuses the identifier field (E09-D10 T-1; #5254 DF-4)
  useEffect(() => {
    if (reason !== undefined) summary.current?.focus();
    else identifierField.current?.focus();
  }, [reason]);
  // a 429 moves focus to the rate-limit line once per episode (E09-D10 T-4; #5254 DF-5)
  useEffect(() => {
    if (state === "rate_limited") rateLimitLine.current?.focus();
  }, [state]);
  // "Back to login" from SCR-002: focus returns to the form's first field
  useEffect(() => {
    if (returned > 0) identifierField.current?.focus();
  }, [returned]);

  const takeHandle = useCallback((): string | null => handle.current, []);
  const dropHandle = useCallback((): void => {
    handle.current = null;
  }, []);
  const backToLogin = useCallback((): void => {
    handle.current = null;
    setChallenge(null);
    setState("idle");
    setReturned((n) => n + 1);
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (state === "submitting" || state === "rate_limited") return;
    if (identifier.trim() === "") return setFieldError("Enter your username.");
    if (password === "") return setFieldError("Enter your password.");
    setFieldError(null);
    setState("submitting");
    const out = await login(identifier.trim(), password);
    setPassword("");
    if (out.kind === "mfa_required") {
      handle.current = out.mfaToken;
      // the challenge's life is fixed once, here, from `expires_in` (BQ-06)
      const deadline = Date.now() + out.expiresInS * 1000;
      setChallenge((c) => ({ id: (c?.id ?? 0) + 1, deadline }));
      setState("idle");
    } else if (out.kind === "authenticated") {
      window.location.assign("/terminal");
    } else if (out.kind === "rate_limited") {
      setRemaining(out.retryAfterS);
      setState("rate_limited");
    } else setState(out.kind);
  }

  const busy = state === "submitting";
  const rateLimited = state === "rate_limited";
  const message =
    fieldError ?? (state === "invalid" || state === "unreachable" ? MESSAGES[state] : null);

  if (challenge !== null) {
    return (
      <TwoFactorStep
        key={challenge.id}
        deadline={challenge.deadline}
        takeHandle={takeHandle}
        dropHandle={dropHandle}
        onBack={backToLogin}
      />
    );
  }

  return (
    <main>
      <h1>Sign in to CandleViewer</h1>
      <form onSubmit={(e) => void onSubmit(e)} noValidate aria-busy={busy}>
        <div ref={summary} tabIndex={-1} role="alert" id="login-error">
          {message ?? reason}
        </div>
        {rateLimited ? (
          <p ref={rateLimitLine} tabIndex={-1} role="status" aria-live="polite">
            Too many attempts. Try again in {formatRemaining(remaining)}.
          </p>
        ) : null}
        <label htmlFor="login-id">Username or email</label>
        <input
          ref={identifierField}
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
        {/* one stable name; aria-pressed alone carries the state (CMP-201, A11Y-F-0003) */}
        <button type="button" aria-pressed={reveal} onClick={() => setReveal((r) => !r)}>
          Show password
        </button>
        <button type="submit" disabled={busy || rateLimited}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
