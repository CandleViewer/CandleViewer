/**
 * The SCR-010 shell mode (E10-S01 S8, #304): one of E10-D03 §4's six states (D02 :77–84; `14`
 * SCR-010 States), derived from plain inputs. Pure: the result depends on the arguments only.
 *
 * Precedence, first match wins:
 *
 * 1. `disconnected`: E17-D01 §4 ranks Disconnected first ("Feed precedence: Disconnected > Stale").
 *    It also outranks frozen and lockout: while the transport is down the kill-switch state is
 *    unknown ("Kill switch: status unknown · last clear 00:12 ago", D03 §4 cell 2; E17-D01 D11).
 * 2. `frozen` and 3. `lockout`: both are E17-D01 §4 Read-only reasons, which "rank above Stale in
 *    effect because [they block] action regardless of data age". Frozen before lockout is PROPOSED:
 *    the kill switch can span every account, while a B20 lockout is per account (D03 §4 cells 4, 5).
 * 4. `degraded`: E17-D01's Stale with the upstream reason, shown as SCR-153 rows (D02 :81).
 * 5. `read-only`: the standing role or view-as overlay. A Viewer's normal shell **is** read-only
 *    (D03 §4 cell 13; D02 :55); under any other mode the role legs stand (cells 14–17), so the
 *    overlay is also returned as the `readOnly` flag, never dropped. E17-D01 §4: "Read-only is
 *    orthogonal"; D03 §1.3 orders the legs view-as first.
 * 6. `normal`.
 *
 * `frozen`, `lockout` and `viewAs` have no client source yet (#304 gap 13; the store holds no
 * kill-switch, B20 or view-as fact): callers pass `false` until E39 (kill switch, lockout) and the
 * view-as context (23 §9.6) land. They are never inferred from other inputs.
 */
import type { ConnectionState, Me } from "../../shell/bootstrap/store.js";

export type ShellMode = "normal" | "disconnected" | "degraded" | "frozen" | "lockout" | "read-only";

/** Why the shell is read-only; `view-as` first, the server's leg order (D03 §1.3). */
export type ReadOnlyReason = "view-as" | "role";

export interface ShellModeInputs {
  readonly connection: ConnectionState["kind"];
  /** The transport was live at least once; a first `connecting` is the session start, not a loss. */
  readonly everLive: boolean;
  /** At least one SCR-153 (CMP-092) row holds. */
  readonly degraded: boolean;
  /** The kill switch is engaged. `false` until E39 supplies the fact (#304 gap 13). */
  readonly frozen: boolean;
  /** A B20 risk lockout holds. `false` until E39 supplies the fact (#304 gap 13). */
  readonly lockout: boolean;
  readonly role: Me["role"] | null;
  /** A view-as session. `false` until the client holds the view-as context (23 §9.6). */
  readonly viewAs: boolean;
}

export interface ShellModeResult {
  readonly mode: ShellMode;
  /** The read-only overlay, set under every mode while it holds (E17-D01 §4 "orthogonal"). */
  readonly readOnly: ReadOnlyReason | null;
}

/** The transport is down: a retry is scheduled or stopped, or a reconnect has not yet gone live. */
export function isDisconnected(
  connection: ShellModeInputs["connection"],
  everLive: boolean,
): boolean {
  if (connection === "reconnecting" || connection === "offline") return true;
  return connection === "connecting" && everLive;
}

export function readOnlyReason(i: Pick<ShellModeInputs, "role" | "viewAs">): ReadOnlyReason | null {
  if (i.viewAs) return "view-as";
  return i.role === "viewer" ? "role" : null;
}

export function deriveShellMode(i: ShellModeInputs): ShellModeResult {
  const readOnly = readOnlyReason(i);
  let mode: ShellMode;
  if (isDisconnected(i.connection, i.everLive)) mode = "disconnected";
  // Frozen before lockout is PROPOSED, pending E39's ruling (kill switch spans accounts; B20 is one).
  else if (i.frozen) mode = "frozen";
  else if (i.lockout) mode = "lockout";
  else if (i.degraded) mode = "degraded";
  else mode = readOnly === null ? "normal" : "read-only";
  return { mode, readOnly };
}

/** Two results are the same mode and overlay (the hook's `isEqual`). */
export const sameShellMode = (a: ShellModeResult, b: ShellModeResult): boolean =>
  a.mode === b.mode && a.readOnly === b.readOnly;
