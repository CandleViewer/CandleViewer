import { useCallback, useEffect, useState, type FormEvent, type JSX } from "react";
import { StepUpChallengeGate } from "../stepUp/StepUpChallengeGate";
import {
  inviteApi,
  readResult,
  type ApiResult,
  type CreatedInvite,
  type PendingInvite,
  type StepUpHold,
} from "./inviteApi";

/** A refused call waiting on its step-up, and what to do with the answer to its re-send. */
interface PendingStepUp {
  readonly hold: StepUpHold;
  readonly onAnswer: (res: ApiResult<CreatedInvite>) => void;
}

/** SCR-123 Admin: invite user (R-303). Link is shown once; only revoke/re-issue afterwards. */
export function AdminInviteScreen(): JSX.Element {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState<string | null>(null);
  const [stepUp, setStepUp] = useState<PendingStepUp | null>(null);
  const [created, setCreated] = useState<CreatedInvite | null>(null);
  const [copied, setCopied] = useState(false);
  const [pending, setPending] = useState<readonly PendingInvite[]>([]);

  const refresh = useCallback(async () => {
    const res = await inviteApi.list();
    if (res.ok && res.data) setPending(res.data.items);
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  function show(invite: CreatedInvite): void {
    setCreated(invite);
    setCopied(false);
    void refresh();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setStepUp(null);
    if (!/^[a-z0-9._-]{3,32}$/.test(username)) {
      setError("Username must be 3-32 characters of a-z, 0-9, dot, underscore or dash.");
      return;
    }
    onCreateAnswer(await inviteApi.create({ username, email, roles: [role] }));
  }

  function onCreateAnswer(res: ApiResult<CreatedInvite>): void {
    if (res.ok && res.data) show(res.data);
    else if (res.stepUp) setStepUp({ hold: res.stepUp, onAnswer: onCreateAnswer });
    else if (res.status === 409) setError("That email or username is already in use.");
    else setError("The invitation could not be created.");
  }

  function reissued(res: ApiResult<CreatedInvite>): void {
    if (res.ok && res.data) show(res.data);
    else if (res.stepUp) setStepUp({ hold: res.stepUp, onAnswer: reissued });
    else setError("The invitation could not be re-issued.");
  }

  async function onResent(pending: PendingStepUp, response: Response): Promise<void> {
    setStepUp(null);
    pending.onAnswer(await readResult<CreatedInvite>(response, pending.hold.held));
  }

  async function copy(): Promise<void> {
    if (!created) return;
    await navigator.clipboard.writeText(`${window.location.origin}${created.invite_url}`);
    setCopied(true);
  }

  async function reissue(userId: string): Promise<void> {
    setError(null);
    setStepUp(null);
    reissued(await inviteApi.reissue(userId));
  }

  async function revoke(userId: string): Promise<void> {
    await inviteApi.revoke(userId);
    await refresh();
  }

  const link = created ? `${window.location.origin}${created.invite_url}` : "";

  return (
    <main>
      <h1>Invite user</h1>
      <p>
        The invitee also needs a Tailscale ACL grant before the link will open. Link delivery is
        manual: copy it and send it yourself.
      </p>
      {stepUp ? (
        <StepUpChallengeGate
          key={stepUp.hold.challenge.challengeId}
          challenge={stepUp.hold.challenge}
          held={stepUp.hold.held}
          onResent={(response) => void onResent(stepUp, response)}
          readBack={refresh}
          outcomeWhere="Pending invitations"
        />
      ) : null}
      <form onSubmit={(event) => void onSubmit(event)}>
        <label htmlFor="inv-username">Username</label>
        <input id="inv-username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <label htmlFor="inv-email">Email</label>
        <input
          id="inv-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="inv-role">Role</label>
        <select id="inv-role" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="viewer">Viewer</option>
        </select>
        <p>Invitations grant the viewer role; promote the user after activation.</p>
        <p>Expires 72 hours after creation. Account access is granted after activation.</p>
        {error ? <p role="alert">{error}</p> : null}
        <button type="submit">Create invitation</button>
      </form>
      {created ? (
        <section aria-labelledby="inv-link-title">
          <h2 id="inv-link-title">Invitation link</h2>
          <p>
            This link grants access - treat it as a secret. It is shown only once and cannot be
            retrieved later, only revoked or re-issued.
          </p>
          <label htmlFor="inv-link">Invite link</label>
          <input id="inv-link" readOnly value={link} />
          <button type="button" onClick={() => void copy()}>
            Copy link
          </button>
          <span aria-live="polite">{copied ? "Copied" : ""}</span>
          <p>Expires at {new Date(created.invite_expires_at).toUTCString()}</p>
        </section>
      ) : null}
      <section aria-labelledby="inv-pending-title">
        <h2 id="inv-pending-title">Pending invitations</h2>
        <ul>
          {pending.map((p) => (
            <li key={p.user_id}>
              {p.username} ({p.role}) -{" "}
              {p.expired
                ? "Expired - re-issue to send a new link"
                : `expires ${new Date(p.expires_at).toUTCString()}`}{" "}
              <button type="button" onClick={() => void reissue(p.user_id)}>
                Re-issue
              </button>
              <button type="button" onClick={() => void revoke(p.user_id)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
