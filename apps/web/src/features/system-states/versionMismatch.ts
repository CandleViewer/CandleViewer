/**
 * SCR-157 (#306 slice 10a; E10-D03 §9.1): the check, per `welcome`, and its analytics. `14`'s
 * 15-minute re-check is not built, by ruling (BQ-10.2: no poll), though `getBuildInfo` exists.
 */
import { CLIENT_PROTOCOL } from "../../lib/ws/protocol/frames";
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";

/** `update_available` is this slice's banner; `incompatible` is 10b's blocking dialog. */
export type VersionCheck = "compatible" | "update_available" | "incompatible";

/**
 * Another protocol, or a refused one (`null`), is `incompatible`: 10b's dialog fails closed.
 * Another build on the protocol is `update_available`, older or newer. Before the first
 * `welcome` (`undefined`), or with a refused build label, it is `compatible`: nothing to show.
 */
export function checkVersion(
  clientVersion: string,
  serverProtocol: string | null | undefined,
  serverVersion: string | undefined,
): VersionCheck {
  if (serverProtocol === undefined) return "compatible"; // never welcomed
  if (serverProtocol !== CLIENT_PROTOCOL) return "incompatible";
  return serverVersion === undefined || serverVersion === clientVersion
    ? "compatible"
    : "update_available";
}

/** The pairs said this session (a page load). */
const reported = new Set<string>();

/**
 * `app.version_mismatch {clientVersion, serverVersion, blocking}` (`14` SCR-157) on the app's
 * analytics seam, `cv:analytics` on `window`, once per distinct pair a session: versions only.
 */
export function reportVersionMismatch(
  clientVersion: string,
  serverVersion: string,
  blocking: boolean,
): void {
  const pair = JSON.stringify([clientVersion, serverVersion, blocking]);
  if (reported.has(pair)) return;
  reported.add(pair);
  const detail = { name: "app.version_mismatch", clientVersion, serverVersion, blocking };
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
}

/** Test-only: a new session, which says each pair again. */
export function resetVersionReports(): void {
  reported.clear();
}
