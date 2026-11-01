import { useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import { useParams } from "react-router";
import { inviteApi, type EnrollStart, type InviteView } from "./inviteApi";

type Phase = "loading" | "invalid" | "accept" | "password" | "totp" | "done";

/** The deck's frozen `invite.invalid` (E09-D12 §8.2 (7)): never says which cause (#5254 DF-2). */
export const INVITE_INVALID = "This invitation is no longer valid. Ask the owner for a new one.";
/** The deck's frozen `enrol.codes.ack` (E09-D12 §8.2 (3)), the gate before the wizard moves on. */
export const CODES_ACK = "I've saved these codes somewhere safe";

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
  const [saved, setSaved] = useState(false);
  /** The control a phase change lands on (E09-D10 T-24, T-30; #5254 DF-35). */
  const first = useRef<HTMLElement | null>(null);
  const land = (el: HTMLElement | null): void => {
    first.current = el;
  };
  const previous = useRef<Phase>("loading");

  useEffect(() => {
    // the arrival (out of loading) is the route's; every later phase change moves focus to the
    // new step's first control, or to the invalid state's heading
    const from = previous.current;
    previous.current = phase;
    if (from !== "loading" && from !== phase) first.current?.focus();
  }, [phase]);

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
        <h1 ref={land} tabIndex={-1}>
          Invitation not valid
        </h1>
        <p>{INVITE_INVALID}</p>
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
            ref={land}
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
            ref={land}
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
      {/* frozen (3): the acknowledgement gates the way on; nothing moves on until it is ticked */}
      <input
        ref={land}
        id="inv-codes-ack"
        type="checkbox"
        checked={saved}
        onChange={(e) => setSaved(e.target.checked)}
      />
      <label id="inv-codes-ack-label" htmlFor="inv-codes-ack">
        {CODES_ACK}
      </label>
      <button
        type="button"
        aria-disabled={!saved}
        aria-describedby={saved ? undefined : "inv-codes-ack-label"}
        onClick={() => {
          if (saved) window.location.assign("/login");
          else first.current?.focus();
        }}
      >
        Go to sign in
      </button>
    </main>
  );
}
