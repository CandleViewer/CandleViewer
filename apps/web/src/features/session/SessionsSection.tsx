/**
 * #1640 S3: SCR-112's sessions section on R-201 (`14` SCR-112; ruling 3 of 2026-10-27).
 * PROPOSED (no hi-fi): the layout is built from the text (E09-D09 grammar, the `14` entry, E09-D06
 * vocabulary); every string not quoted from a merged spec is PROPOSED (copy-pending, #2701).
 * Temporary dialog chrome (#2725) as in SCR-005. Fetched on open, never polled (`14` Performance).
 */
import { useCallback, useEffect, useId, useRef, useState, type JSX } from "react";
import { actions, card, hidden, primary, scrim, secondary, title, useModalKeys } from "./chrome";
import {
  sessionsApi,
  type SessionsApi,
  type SessionsFailure,
  type UserSession,
} from "./sessionsApi";

/** PROPOSED copy; `unavailable` is #1640's `lock.unreachable`. Never the server's `detail`. */
const FAILURE: Readonly<Record<SessionsFailure, string>> = {
  forbidden: "This was refused. Reload the page, then try again.",
  not_found: "That session has already ended.",
  refused: "Signing out everywhere needs a fresh sign-in. Sign in again, then try.",
  unavailable: "Couldn't reach the server. Try again.",
};

type ListState =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly failure: SessionsFailure }
  | { readonly kind: "ok"; readonly items: readonly UserSession[] };
type Pending = { readonly kind: "all" } | { readonly kind: "one"; readonly session: UserSession };

const deviceOf = (s: UserSession): string => s.device_name ?? s.user_agent ?? "Unknown device";
/** A server timestamp as `YYYY-MM-DD hh:mm UTC` (E09-D09 `{hh:mm} UTC`), never a client zone. */
function when(iso: string | undefined): string {
  const ms = iso === undefined ? Number.NaN : Date.parse(iso);
  if (!Number.isFinite(ms)) return "Unknown";
  return `${new Date(ms).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

const cell = {
  padding: "var(--space-2) var(--space-3)",
  textAlign: "start",
  borderBlockEnd: "1px solid var(--color-border-default)",
} as const;
/** On the page (no themed surface under it yet), a button carries its own surface for contrast. */
const onPage = { ...secondary, background: "var(--color-surface-raised)" } as const;
const badge = {
  marginInlineStart: "var(--space-2)",
  padding: "0 var(--space-2)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-badge)",
  fontSize: "var(--font-size-xs)",
} as const;

export function SessionsSection({
  api = sessionsApi,
}: {
  readonly api?: SessionsApi;
}): JSX.Element {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  /** Focused once the dialog is gone: its focus guard pulls focus back while it is mounted. */
  const focusNext = useRef<HTMLElement | null>(null);
  const alive = useRef(true);
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<SessionsFailure | null>(null);
  const [status, setStatus] = useState("");

  const load = useCallback(async () => {
    setList({ kind: "loading" });
    const out = await api.list();
    if (!alive.current) return;
    setList(out.kind === "ok" ? out : { kind: "error", failure: out.kind });
  }, [api]);
  useEffect(() => {
    alive.current = true;
    void load();
    return () => void (alive.current = false);
  }, [load]);

  const open = (next: Pending): void => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setFailed(null);
    setStatus("");
    setPending(next);
  };
  useEffect(() => {
    if (pending !== null) return;
    focusNext.current?.focus();
    focusNext.current = null;
  }, [pending]);
  const cancel = (): void => {
    focusNext.current = opener.current;
    setPending(null);
  };
  const confirm = async (): Promise<void> => {
    if (pending === null) return;
    setBusy(true);
    setFailed(null);
    const one = pending.kind === "one" ? pending.session : null;
    const target = one === null ? null : (one.id ?? "");
    // a row without an id never reaches here (its button is disabled); never widened to "everywhere"
    const out = target === null ? await api.signOutEverywhere() : await api.revoke(target);
    if (!alive.current) return;
    // 22 `revokeMySession`: revoking the current session is a logout; so is signing out everywhere
    if (out.kind === "done" && (one === null || one.current === true)) return api.endSession();
    setBusy(false);
    if (out.kind !== "done") {
      setFailed(out.kind);
      if (out.kind === "not_found") void load();
      return;
    }
    focusNext.current = heading.current; // the row and its button are gone: the heading takes focus
    setPending(null);
    setStatus("Session revoked.");
    await load();
  };

  return (
    <section aria-labelledby={`${id}-h`} aria-busy={list.kind === "loading"}>
      <h2 id={`${id}-h`} ref={heading} tabIndex={-1}>
        Sessions
      </h2>
      <p role="status">{status}</p>
      {list.kind === "loading" ? <p>Loading sessions…</p> : null}
      {list.kind === "error" ? (
        <>
          <p role="alert">{FAILURE[list.failure]}</p>
          <button type="button" style={onPage} onClick={() => void load()}>
            Try again
          </button>
        </>
      ) : null}
      {list.kind === "ok" && list.items.length === 0 ? <p>No active sessions.</p> : null}
      {list.kind === "ok" && list.items.length > 0 ? (
        <table style={{ borderCollapse: "collapse" }}>
          <caption style={{ textAlign: "start" }}>Signed-in sessions</caption>
          <thead>
            <tr>
              {["Device", "IP address", "Signed in", "Last seen", "Action"].map((h) => (
                <th key={h} scope="col" style={cell}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list.items.map((s) => (
              <tr key={s.id}>
                <th scope="row" style={cell}>
                  {deviceOf(s)}
                  {s.current === true ? <span style={badge}>This session</span> : null}
                </th>
                <td style={cell}>{s.ip ?? "Not recorded"}</td>
                <td style={cell}>{when(s.created_at)}</td>
                <td style={cell}>{when(s.last_seen_at)}</td>
                <td style={cell}>
                  <button
                    type="button"
                    style={onPage}
                    disabled={s.id === undefined}
                    onClick={() => open({ kind: "one", session: s })}
                  >
                    Revoke
                    {/* `14` SCR-112 A11y: a destructive control names its target */}
                    <span style={hidden}>
                      {` ${deviceOf(s)}${s.current === true ? " (this session)" : `, last seen ${when(s.last_seen_at)}`}`}
                    </span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <button
        type="button"
        style={onPage}
        disabled={list.kind !== "ok" || list.items.length === 0}
        onClick={() => open({ kind: "all" })}
      >
        Sign out everywhere
      </button>
      {pending === null ? null : (
        <SessionsConfirm
          pending={pending}
          busy={busy}
          failed={failed}
          onConfirm={() => void confirm()}
          onCancel={cancel}
        />
      )}
    </section>
  );
}

interface ConfirmProps {
  readonly pending: Pending;
  readonly busy: boolean;
  readonly failed: SessionsFailure | null;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
}

/**
 * The confirm sub-dialog (as SCR-005 `sign-out-instead`): focus starts on Cancel, Esc cancels unless
 * the call is on the wire, Tab is trapped. The current-session line is `14` SCR-112's, verbatim.
 */
function SessionsConfirm({
  pending,
  busy,
  failed,
  onConfirm,
  onCancel,
}: ConfirmProps): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  useModalKeys(dialog, busy ? undefined : onCancel, true);
  useEffect(() => (busy ? dialog : back).current?.focus(), [busy]);
  const all = pending.kind === "all";
  const current = pending.kind === "one" && pending.session.current === true;
  const body = all
    ? "Every session, this one included, will be signed out. Unsent ticket inputs will be discarded. Open orders stay live on the exchange with their native stop-loss."
    : current
      ? "This will sign you out on this device."
      : `${deviceOf(pending.session)} will be signed out.`;
  const verb = all ? "Sign out everywhere" : current ? "Revoke and sign out" : "Revoke";
  return (
    <div style={scrim}>
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-t`}
        aria-describedby={`${id}-d`}
        aria-busy={busy}
        tabIndex={-1}
        style={card}
      >
        <h2 id={`${id}-t`} style={title}>
          {all ? "Sign out everywhere?" : "Revoke session?"}
        </h2>
        <p id={`${id}-d`} style={{ margin: 0, color: "var(--color-text-secondary)" }}>
          {body}
        </p>
        {failed === null ? null : (
          <p role="alert" style={{ margin: 0, color: "var(--color-status-warning-default)" }}>
            {FAILURE[failed]}
          </p>
        )}
        <div style={actions}>
          <button ref={back} type="button" style={secondary} disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button type="button" style={primary} disabled={busy} onClick={onConfirm}>
            {verb}
          </button>
        </div>
      </div>
    </div>
  );
}
