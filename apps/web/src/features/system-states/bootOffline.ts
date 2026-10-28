/**
 * E10-S04 (#306) slice 9: R-902 `/offline` at boot (SCR-159 backend-unreachable, E10-D03 §9.2,
 * §9.3). `main.tsx` asks before the router exists: a boot that found no server opens the takeover
 * in place of the page asked for, and start-up resumes there once the server answers.
 */
import { reportOffline } from "../../shell/bootstrap/liveness";
import { getShellState, type BootstrapPhase } from "../../shell/bootstrap/store";

/** R-902 (`12` §2). */
export const OFFLINE_PATH = "/offline";
/** One leading slash, not followed by a second or by a backslash (a browser reads it as one). */
const ONE_SLASH = /^\/(?![/\\])/;
/** R-902 itself, in any case, with or without a trailing slash. */
const OFFLINE = /^\/offline\/*$/i;

/** Set by a diverted boot: where start-up resumes. `null`: `/offline` was opened as it is. */
let resume: string | null = null;
/** R-902 handed a ready session back: the shell says the recovery once, when its socket is live. */
let handedBack = false;

/** No answer, a timeout or a 5xx: the server was not reached. A 4xx is its answer (401: sign in). */
export function isUnreachableBoot(phase: BootstrapPhase): boolean {
  if (phase.kind !== "failed") return false;
  return phase.reason !== "http_error" || (phase.status ?? 0) >= 500;
}

/**
 * Where start-up resumes for the page asked for: that page only when it is one of the app's own
 * (the same origin, a path with one leading slash and no scheme, also once percent-decoded as a
 * router reads it) and not R-902 itself; only its path, query and hash. Anything else: `/`.
 */
function resumeTarget(asked: string): string {
  const { origin } = window.location;
  try {
    const url = new URL(asked, origin);
    const path = decodeURIComponent(url.pathname);
    const own = url.origin === origin && ONE_SLASH.test(asked) && ONE_SLASH.test(path);
    return own && !OFFLINE.test(path) ? `${url.pathname}${url.search}${url.hash}` : "/";
  } catch {
    return "/"; // an opaque origin is no base; a malformed escape is no page
  }
}

/** Opens R-902 for a boot that found no server, keeping the page asked for; `true` when it did. */
export function divertUnreachableBoot(
  location: Pick<Location, "pathname" | "search" | "hash"> = window.location,
  history: Pick<History, "replaceState"> = window.history,
): boolean {
  if (!isUnreachableBoot(getShellState().bootstrap)) return false;
  resume = resumeTarget(`${location.pathname}${location.search}${location.hash}`);
  history.replaceState(null, "", OFFLINE_PATH);
  reportOffline("backend_unreachable");
  return true;
}

/** Whether this page load diverted its boot here: the takeover then retries by itself. */
export function bootDiverted(): boolean {
  return resume !== null;
}

/**
 * The boot owns an outage from its start until it settles, and R-902 owns it after a diversion until
 * it hands start-up back: meanwhile the liveness probe publishes no verdict and no analytics, so a
 * boot that finds no server is reported once, as `backend_unreachable`.
 */
export function bootOwnsOutage(): boolean {
  const { kind } = getShellState().bootstrap;
  return kind === "loading" || kind === "slow" || bootDiverted();
}

/** Where start-up resumes, once; the episode ends. */
export function takeResumePath(): string {
  const path = resume ?? "/";
  resume = null;
  return path;
}

/**
 * R-902's success: the episode ends, and start-up resumes at the path this returns. Only a ready
 * session is handed back to be said: a sign-in (401) mounts no shell to say it.
 */
export function resumeBoot(ready: boolean): string {
  handedBack = ready;
  return takeResumePath();
}

/** The shell's side of `resumeBoot`: `true` once. */
export function takeHandedBack(): boolean {
  const was = handedBack;
  handedBack = false;
  return was;
}
