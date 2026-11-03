/**
 * SCR-124's Exit (E42-S03; E42-D03 §10 V-9, V-14; `22` `endViewAs`): one
 * `DELETE /auth/session/view-as` through `apiFetch` (its CSRF header and the tab's bearer; no
 * step-up, and neither the read-only rule nor the hold refuses it), then the sibling tabs hear
 * `changed`, this page's view-as sync stops and the page loads SCR-121 in the owner's own scope:
 * only a full load drops every datum of the target's. A `503` changed nothing. No answer, or none
 * within `EXIT_TIMEOUT_MS`, leaves the outcome unknown, so the banner stays (V-14) and Exit can be
 * pressed again (`endViewAs` is idempotent). A session found idle-locked is SCR-005's to unlock
 * first. The next page says `va.back` once, from a session-storage note that holds the time of the
 * Exit and the target's user id, never a name or the reason, and keeps that id once for SCR-121's
 * row (V-9, `takeExitRowFocus`).
 */
import {
  VIEW_AS_PATH,
  announceChange,
  getViewAs,
  isTargetUserId,
  stopViewAsSync,
} from "../../lib/auth/viewAsContext";
import { apiFetch } from "../../lib/http/csrfFetch";

/** V-9: where Exit lands (R-301, SCR-121; the test pins it to the route manifest). */
export const EXIT_TO = "/admin/users";
/**
 * The note the next page load reads once: `<time>` or `<time>:<target user id>`. Never a name or
 * the reason, and the id never rides in a URL or a history entry.
 */
export const BACK_NOTE = "cv.view-as.back";
/** A note older than this belongs to a load that never mounted the shell: it is not said. */
export const BACK_NOTE_MAX_AGE_MS = 60_000;
/** V-14's "no answer": Exit stops waiting after this long, as the boot's own reads do. */
export const EXIT_TIMEOUT_MS = 10_000;
/** The note's value; any other is no note of Exit's, and an id must pass `isTargetUserId` too. */
const NOTE = /^(\d{1,15})(?::(.+))?$/;

/** What a press of Exit came to: the page is leaving, nothing changed (V-14), or SCR-005 has it. */
export type ExitOutcome = "leaving" | "failed" | "locked";

type NoteStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export interface ExitPorts {
  /** `apiFetch` by default. */
  readonly send?: ((input: string, init: RequestInit) => Promise<Response>) | undefined;
  /** A full load of `url`: `window.location.assign` by default. */
  readonly navigate?: ((url: string) => void) | undefined;
  /** The broadcast to sibling tabs: `announceChange` by default. */
  readonly broadcast?: (() => void) | undefined;
  /** Stops this page's view-as sync before the load: `stopViewAsSync` by default. */
  readonly stopSync?: (() => void) | undefined;
  /** `sessionStorage` by default. */
  readonly notes?: NoteStore | undefined;
}

function sessionNotes(): NoteStore | null {
  try {
    return window.sessionStorage;
  } catch {
    return null; // storage blocked: the next page says nothing
  }
}

/** `401 session_idle_locked`: the session lives on, locked, and the `DELETE` changed nothing. */
async function idleLocked(res: Response): Promise<boolean> {
  if (res.status !== 401) return false;
  try {
    // a problem body or anything else: `code` is read as `unknown` and compared, never trusted
    return ((await res.json()) as { code?: unknown } | null)?.code === "session_idle_locked";
  } catch {
    return false;
  }
}

/** The `DELETE`, or `null` once `EXIT_TIMEOUT_MS` passed unanswered (the call is then aborted). */
async function sendBounded(send: NonNullable<ExitPorts["send"]>): Promise<Response | null> {
  const stall = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stalled = new Promise<null>((resolve) => {
    timer = setTimeout(() => {
      stall.abort();
      resolve(null);
    }, EXIT_TIMEOUT_MS);
  });
  const sending = send(VIEW_AS_PATH, { method: "DELETE", signal: stall.signal });
  sending.catch(() => undefined); // an answer after the stall is V-14's already
  try {
    return await Promise.race([sending, stalled]);
  } finally {
    clearTimeout(timer);
  }
}

/** Leaves view-as: `leaving` once the server ended or cleared it; else what kept the page here. */
export async function exitViewAs(ports: ExitPorts = {}): Promise<ExitOutcome> {
  // the target's id as held at the press: a re-read landing during the `DELETE` may clear it
  const held = getViewAs();
  const target = held.kind === "held" && isTargetUserId(held.targetId) ? held.targetId : null;
  let res: Response | null;
  try {
    res = await sendBounded(ports.send ?? apiFetch);
  } catch {
    return "failed";
  }
  if (res === null) return "failed";
  if (!res.ok) return (await idleLocked(res)) ? "locked" : "failed";
  try {
    const at = String(Date.now()); // a malformed or missing id never blocks Exit: the time alone
    (ports.notes ?? sessionNotes())?.setItem(BACK_NOTE, target === null ? at : `${at}:${target}`);
  } catch {
    // storage full or blocked: the next page says nothing
  }
  (ports.broadcast ?? announceChange)();
  (ports.stopSync ?? stopViewAsSync)();
  (ports.navigate ?? ((url: string) => window.location.assign(url)))(EXIT_TO);
  return "leaving";
}

/**
 * The target's id from this load's note, until SCR-121 takes it. Focus on the target's row: written
 * here, consumed by SCR-121 in part 5 (E42-S03); until then the landing is the top of the page.
 */
let exitRow: string | null = null;

/**
 * Whether this page load follows an Exit within `BACK_NOTE_MAX_AGE_MS`: `true` once. A note it
 * finds also sets the landing's row: the note's id if fresh and well-formed, else none.
 */
export function takeBackNote(notes: NoteStore | null = sessionNotes()): boolean {
  try {
    const note = notes?.getItem(BACK_NOTE) ?? null;
    if (note === null) return false;
    notes?.removeItem(BACK_NOTE);
    const [, at, id] = NOTE.exec(note) ?? [];
    const ours = at !== undefined && (id === undefined || isTargetUserId(id));
    const fresh = ours && Math.abs(Date.now() - Number(at)) <= BACK_NOTE_MAX_AGE_MS;
    exitRow = fresh ? (id ?? null) : null;
    return fresh;
  } catch {
    return false;
  }
}

/**
 * V-9's landing: the target's id from Exit's note, once, for SCR-121 to focus that user's row;
 * `null` after the first take, and for a stale or malformed note or none. It is a hint from this
 * tab's own storage, not the server's: SCR-121 matches it against the rows it rendered and only
 * moves focus; it never fetches, navigates or builds a URL with it.
 */
export function takeExitRowFocus(): string | null {
  const id = exitRow;
  exitRow = null;
  return id;
}
