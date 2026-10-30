/**
 * SCR-157 (#306 slice 10a; E10-D03 §9.1): the check, per `welcome`, and its analytics. `14`'s
 * 15-minute re-check is not built, by ruling (BQ-10.2: no poll), though `getBuildInfo` exists.
 */
import { CLIENT_PROTOCOL, CLIENT_VERSION } from "../../lib/ws/protocol/frames";
import type { ShellState } from "../../shell/bootstrap/store";
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import { VERSION_DIALOG_COPY } from "./copy";

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

/**
 * The incompatible build the store holds, as one key (its protocol and version), else `undefined`.
 * SCR-157's dialog shows once per key; while there is one, the gated set's T2 leg holds
 * (`protocolLeg`), the dialog answered or not.
 */
export function incompatibleBuild(
  s: Pick<ShellState, "serverProtocol" | "serverVersion">,
): string | undefined {
  return checkVersion(CLIENT_VERSION, s.serverProtocol, s.serverVersion) === "incompatible"
    ? JSON.stringify([s.serverProtocol, s.serverVersion ?? null])
    : undefined;
}

const PROTOCOL_LEG = Object.freeze({
  key: "health.protocol_incompatible",
  reason: VERSION_DIALOG_COPY.unavailable,
  killSwitchLine: VERSION_DIALOG_COPY.killSwitchLine,
} as const);

/**
 * The `health.protocol_incompatible` leg (`PANIC_LEGS`) an incompatible build puts on E10-D03
 * §1.3's gated set, held through Continue read-only (E10-D04 T-16) and gone when the builds match
 * (T-18), else `null`: `reason` is each gated control's own reason node (FLATTEN ALL…, CANCEL
 * ALL…, FREEZE…, the StatusBar's Kill switch…), `killSwitchLine` the Safety cluster's line (§9.1).
 * Those controls render it; they are E39-S05's, and nothing stands in for them (`slots.tsx`).
 */
export function protocolLeg(
  s: Pick<ShellState, "serverProtocol" | "serverVersion">,
): typeof PROTOCOL_LEG | null {
  return incompatibleBuild(s) === undefined ? null : PROTOCOL_LEG;
}

/** The pairs said this session (a page load). */
const reported = new Set<string>();

/**
 * `app.version_mismatch {clientVersion, serverVersion, blocking}` (`14` SCR-157) on the app's
 * analytics seam, `cv:analytics` on `window`, once per distinct pair a session: versions only,
 * `null` for a server build the client did not keep.
 */
export function reportVersionMismatch(
  clientVersion: string,
  serverVersion: string | null,
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
