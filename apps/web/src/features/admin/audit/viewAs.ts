/**
 * The audit pages' view-as seam (E42-S04; the orchestrator's BQ-9; E09-D09 §3.1 `rbac.view_as`).
 * While the session views as another user, Run tamper check, Signed export… and Download are T2
 * `rbac.view_as`, all three described by one panel notice (`32` G-T2.5). The shell's mode carries
 * the view-as overlay (`useShellMode`), which is false until the client holds the view-as context
 * (#1134: `selectShellMode` passes `viewAs: false`). Reads answer as the target meanwhile (`22`
 * View-as), so the session's `me` is the target's and names `{user}`. With no name to show, the
 * session is still in view-as: `{user}` reads "another user" and the gates hold (S-1135P2-d02).
 */
import { useMemo } from "react";
import type { Me } from "../../../shell/bootstrap/store";
import { useShellSelector } from "../../../shell/useShellSelector";
import { useShellMode } from "../../app-shell/useShellMode";

/** `{user}` when the session's `me` names no one: still view-as, never the session's own writes. */
const NO_NAME = "another user";

export interface AuditViewAs {
  /** The view-as target's name, `rbac.view_as`'s `{user}`. */
  readonly user: string;
}

export function useAuditViewAs(): AuditViewAs | null {
  const viewing = useShellMode().readOnly === "view-as";
  const name = useShellSelector((state) => {
    // a /me without `user` (a stub, a malformed answer) names no one
    const user: Partial<Me["user"]> | undefined = state.me?.user;
    return user?.username ?? null;
  });
  return useMemo(
    () => (viewing ? { user: name !== null && name !== "" ? name : NO_NAME } : null),
    [viewing, name],
  );
}
