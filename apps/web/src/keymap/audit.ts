import { apiFetch } from "../lib/http/csrfFetch";
import { getCommand } from "./keymap";
import { keymapUser, savesToServer } from "./session";

export const TRADING_BINDING_CHANGED = "hotkey.trading_binding_changed";

export interface AuditRecord {
  readonly action: typeof TRADING_BINDING_CHANGED;
  readonly commandId: string;
  readonly before: string;
  readonly after: string;
  readonly acknowledgedUnsafe: boolean;
}
export type AuditSink = (r: AuditRecord) => void;

/**
 * Single choke point for rebinding audit (CMP-093 AuditActionTrigger contract): every binding
 * change goes through `applyRebind` (a rebind, a swap, an unbind, an import, reset-all; #305
 * D10), which emits for every command of the dangerous set (`audited` in keymap.json, held equal
 * to `DANGEROUS_COMMANDS` by a test; SEC-305A-01) and for any binding made on E49-S07's
 * acknowledgement, so no caller can change one without the audit event. The sink is injected by
 * the shell; the default dispatches a DOM event the shell's audit transport listens to.
 */
let sink: AuditSink = (r) => window.dispatchEvent(new CustomEvent("cv:audit", { detail: r }));
export function setAuditSink(s: AuditSink): void {
  sink = s;
}

export function applyRebind(
  current: ReadonlyMap<string, string>,
  commandId: string,
  binding: string,
  acknowledgedUnsafe = false,
): ReadonlyMap<string, string> {
  const before = current.get(commandId) ?? "";
  const next = new Map(current);
  next.set(commandId, binding);
  const audited = getCommand(commandId)?.audited === true || acknowledgedUnsafe;
  if (audited && before !== binding) {
    sink({
      action: TRADING_BINDING_CHANGED,
      commandId,
      before,
      after: binding,
      acknowledgedUnsafe,
    });
  }
  return next;
}

/**
 * Transmit a record to the server audit trail (POST /settings/hotkey-audit, C-2.9). The server
 * attributes it to the session principal and appends the hash-chained row. Records stay in their
 * user's outbox until the POST succeeds, so a failed attempt can be flushed later, and only ever
 * under that user's session (#305, A55); one the server refuses for good is parked (SEC-305B-02).
 */
const AUDIT_PATH = "/api/v1/settings/hotkey-audit";
const STORE_KEY = "cv.hotkey-audit-outbox.v1";
const DEAD_KEY = "cv.hotkey-audit-dead.v1";
const keyed = (base: string, user: string): string => `${base}:${user}`;

function load(key: string): unknown[] {
  try {
    const raw = window.localStorage.getItem(key);
    const v: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? (v as unknown[]) : [];
  } catch {
    return [];
  }
}
function persist(key: string, list: readonly unknown[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(list));
  } catch {
    /* storage unavailable: the in-memory copy still retries this session */
  }
}
// Durable outboxes, one per user on this device: each survives reload, and a record leaves it only
// after a 2xx from the server or parked. A legacy unkeyed outbox has no known maker, so it is never
// sent under anyone's session.
const outboxes = new Map<string, AuditRecord[]>();
function outboxOf(user: string): AuditRecord[] {
  let outbox = outboxes.get(user);
  if (outbox === undefined) {
    outbox = load(keyed(STORE_KEY, user)) as AuditRecord[];
    outboxes.set(user, outbox);
  }
  return outbox;
}

/** What the server's answer means for a record: sent, refused for good, or to retry in order. */
export type AuditOutcome =
  | { readonly kind: "sent" }
  | { readonly kind: "refused"; readonly status: number }
  | { readonly kind: "retry" };
/** The 4xx a later attempt can pass: a session to renew, a timeout, the rate limit. */
const RETRYABLE_4XX: ReadonlySet<number> = new Set([401, 408, 429]);
/** The one 403 no later attempt changes: the role lacks `settings:write`. */
const FORBIDDEN_CODE = "forbidden";

/**
 * Whether a refusal is final: a 4xx but `RETRYABLE_4XX`, and of the 403s only `forbidden`. 22's
 * Forbidden is also the CSRF guard's (`csrf_token_invalid`), a read-only session's
 * (`session_read_only`) and a view-as context's (`view_as_*`), which a later attempt can pass. The
 * problem `code` is read as `csrfFetch` reads it; a body that cannot be read names no `forbidden`,
 * so its record retries in order like a 5xx's (CR-305BF-01).
 */
async function isFinal(res: Response): Promise<boolean> {
  if (res.status < 400 || res.status >= 500 || RETRYABLE_4XX.has(res.status)) return false;
  if (res.status !== 403) return true;
  try {
    const body = (await res.clone().json()) as { code?: unknown };
    return body.code === FORBIDDEN_CODE;
  } catch {
    return false;
  }
}

export async function sendAudit(r: AuditRecord): Promise<AuditOutcome> {
  try {
    const res = await apiFetch(AUDIT_PATH, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        command_id: r.commandId,
        before: r.before,
        after: r.after,
        acknowledged_unsafe: r.acknowledgedUnsafe,
      }),
    });
    if (res.ok) return { kind: "sent" };
    return (await isFinal(res)) ? { kind: "refused", status: res.status } : { kind: "retry" };
  } catch {
    return { kind: "retry" }; // a network error
  }
}

/**
 * SEC-305B-02: a record the server refuses for good (a 403 `forbidden`, a 422) would stall every
 * later one behind it. It is kept on the device under the dead-letter key, said once, and the
 * outbox goes on.
 */
function park(user: string, r: AuditRecord, status: number): void {
  const key = keyed(DEAD_KEY, user);
  persist(key, [...load(key), { status, record: r }]);
  console.warn(`hotkey audit: ${r.commandId} refused with ${status}, parked under ${DEAD_KEY}`);
}

let flushing: Promise<void> | null = null;
let rerun = false;
async function drain(user: string): Promise<void> {
  // Oldest first; stop at a failure to retry and try again on `online` / next load. A sign-in or
  // sign-out on the way stops it: a record is never sent under another user's session.
  const outbox = outboxOf(user);
  while (outbox.length > 0 && keymapUser() === user) {
    const r = outbox[0] as AuditRecord;
    const outcome = await sendAudit(r);
    if (outcome.kind === "retry") return;
    outbox.shift();
    if (outcome.kind === "refused") park(user, r, outcome.status);
    persist(keyed(STORE_KEY, user), outbox);
  }
}
export function flushAuditOutbox(): Promise<void> {
  if (flushing) {
    rerun = true; // a record arrived mid-flush: take another pass when this one ends
    return flushing;
  }
  const run = (async () => {
    await Promise.resolve(); // ensure `flushing` is assigned before any completion
    do {
      rerun = false;
      const user = keymapUser();
      if (user !== null) await drain(user);
    } while (rerun);
    flushing = null;
  })();
  flushing = run;
  return run;
}

/**
 * Queue a record for the signed-in user. Only a session that may change its settings queues one
 * (A55): a Viewer's remap applies on the device and is never POSTed, since the server would refuse
 * it (`settings:write`), and with no one signed in nothing is queued.
 */
export function recordAudit(r: AuditRecord): void {
  const user = keymapUser();
  if (user === null || !savesToServer()) return;
  const outbox = outboxOf(user);
  outbox.push(r);
  persist(keyed(STORE_KEY, user), outbox);
  void flushAuditOutbox();
}
/** The signed-in user's outbox; none while no one is signed in. */
export function auditOutbox(): readonly AuditRecord[] {
  const user = keymapUser();
  return user === null ? [] : outboxOf(user);
}
