import { useEffect, useState, type FormEvent, type JSX } from "react";
import { useParams } from "react-router";
import { inviteApi, type EnrollStart, type InviteView } from "./inviteApi";

type Phase = "loading" | "invalid" | "accept" | "password" | "totp" | "done";

/** SCR-017 invited-user onboarding (R-009): accept -> password -> TOTP -> orientation (4 steps). */
export function InviteAcceptScreen(): JSX.Element {
  const { inviteToken = "" } = useParams();
  const [phase, setPhase] = useState<Phase>("loading");
  const [view, setView] = useState<InviteView | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enroll, setEnroll] = useState<EnrollStart | null>(null);
  const [codes, setCodes] = useState<readonly string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void inviteApi.inspect(inviteToken).then((res) => {
      if (!live) return;
      if (res.ok && res.data) {
        setView(res.data);
        setPhase("accept");
      } else setPhase("invalid");
    });
    return () => {
      live = false;
    };
  }, [inviteToken]);

  async function onPassword(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    const res = await inviteApi.redeem(inviteToken, password);
    if (res.ok && res.data) {
      setEnroll(res.data);
      setPhase("totp");
    } else if (res.status === 422) setError("That password does not meet the policy.");
    else setPhase("invalid");
  }

  async function onCode(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!enroll) return;
    setError(null);
    const res = await inviteApi.confirm(inviteToken, enroll.method_id, code);
    if (res.ok && res.data) {
      setCodes(res.data.recovery_codes);
      setPhase("done");
    } else if (res.status === 422) setError("That code did not work. Try again.");
    else setPhase("invalid");
  }

  if (phase === "loading") {
    return (
      <main>
        <p>Checking your invitation...</p>
      </main>
    );
  }
  if (phase === "invalid") {
    return (
      <main>
        <h1>Invitation not valid</h1>
        <p>
          This invitation link is not valid. It may have expired or already been used. Ask the owner
          to re-issue it from Admin.
        </p>
      </main>
    );
  }
  if (phase === "accept") {
    return (
      <main>
        <h1>Welcome, {view?.display_name}</h1>
        <p>Step 1 of 4: accept your invitation. You are being set up as: {view?.role}.</p>
        <button type="button" onClick={() => setPhase("password")}>
          Accept invitation
        </button>
      </main>
    );
  }
  if (phase === "password") {
    return (
      <main>
        <h1>Choose a password</h1>
        <p>Step 2 of 4: choose a password.</p>
        <form onSubmit={(event) => void onPassword(event)}>
          <label htmlFor="inv-pw">New password</label>
          <input
            id="inv-pw"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error ? <p role="alert">{error}</p> : null}
          <button type="submit">Continue</button>
        </form>
      </main>
    );
  }
  if (phase === "totp") {
    return (
      <main>
        <h1>Set up your authenticator</h1>
        <p>Step 3 of 4: add this key to your authenticator app, then enter the code.</p>
        <p>
          Key: <code>{enroll?.secret_base32}</code>
        </p>
        <form onSubmit={(event) => void onCode(event)}>
          <label htmlFor="inv-code">Authenticator code</label>
          <input
            id="inv-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          {error ? <p role="alert">{error}</p> : null}
          <button type="submit">Activate account</button>
        </form>
      </main>
    );
  }
  return (
    <main>
      <h1>You are set up</h1>
      <p>Step 4 of 4: you are signed up as {view?.role}. Save these recovery codes now.</p>
      <section aria-labelledby="inv-orient">
        <h2 id="inv-orient">What happens next</h2>
        <p>
          Your access is limited to your role. The owner grants account access separately, so you
          may see no accounts until then. Recovery codes are shown once.
        </p>
      </section>
      <ul>
        {codes.map((c) => (
          <li key={c}>
            <code>{c}</code>
          </li>
        ))}
      </ul>
      <a href="/login">Go to sign in</a>
    </main>
  );
}
