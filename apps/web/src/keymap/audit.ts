import { apiFetch } from "../lib/http/csrfFetch";
import { getCommand } from "./keymap";

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
 * change goes through `applyRebind`, which emits for destructive (trading) commands, so no
 * caller can change one without the audit event. The sink is injected by the shell; the default
 * dispatches a DOM event the shell's audit transport listens to.
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
  if (getCommand(commandId)?.destructive && before !== binding) {
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
 * attributes it to the session principal and appends the hash-chained row. Records stay in the
 * outbox until the POST succeeds so a failed attempt can be flushed later.
 */
const AUDIT_PATH = "/api/v1/settings/hotkey-audit";
const STORE_KEY = "cv.hotkey-audit-outbox.v1";

function load(): AuditRecord[] {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    const v: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? (v as AuditRecord[]) : [];
  } catch {
    return [];
  }
}
function persist(list: readonly AuditRecord[]): void {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable: the in-memory copy still retries this session */
  }
}
// Durable outbox: survives reload; a record leaves it only after a 2xx from the server.
const outbox: AuditRecord[] = load();

export async function sendAudit(r: AuditRecord): Promise<boolean> {
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
    return res.ok;
  } catch {
    return false;
  }
}

let flushing: Promise<void> | null = null;
let rerun = false;
async function drain(): Promise<void> {
  // Oldest first; stop at the first failure and retry on `online` / next load.
  while (outbox.length > 0) {
    const r = outbox[0] as AuditRecord;
    if (!(await sendAudit(r))) return;
    outbox.shift();
    persist(outbox);
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
      await drain();
    } while (rerun && outbox.length > 0);
    flushing = null;
  })();
  flushing = run;
  return run;
}

export function recordAudit(r: AuditRecord): void {
  outbox.push(r);
  persist(outbox);
  void flushAuditOutbox();
}
export function auditOutbox(): readonly AuditRecord[] {
  return outbox;
}
