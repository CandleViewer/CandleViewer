/**
 * The `CV_DEV_SERVER_URL` development hook (#3411; C-12.9, C-12.10). When honoured, the main
 * window loads that URL instead of the shell's own `app://candleviewer` bundle, and the navigation
 * guard (SR-113) accepts its origin, so the page it serves gets the preload bridge (`window.cv`).
 * The shell therefore honours it only in an unpackaged build and only for a loopback http origin
 * with an explicit port, decided on the parsed URL, never by string prefix.
 */

/**
 * The hosts a dev server may use. `[::1]` is left out: the repo's dev servers bind `127.0.0.1` or
 * `localhost` (which also reaches a server on the IPv6 loopback), and a smaller closed set is
 * easier to audit.
 */
const LOOPBACK_HOSTS: ReadonlySet<string> = new Set(["127.0.0.1", "localhost"]);

/**
 * Printable ASCII without spaces. The URL parser silently drops tabs and newlines and trims
 * spaces and controls, so a value carrying any of them is refused rather than repaired.
 */
const PRINTABLE_ASCII = /^[\x21-\x7e]+$/;

/** Why a set `CV_DEV_SERVER_URL` was ignored: the only detail about it the shell logs. */
export type DevServerIgnoredReason = "unpackaged-only" | "not-loopback-http" | "malformed";

declare const accepted: unique symbol;

/** A dev-server URL that passed {@link resolveDevServerUrl}, normalised by the URL parser. */
export type DevServerUrl = string & { readonly [accepted]: true };

export type DevServerResolution =
  | { readonly kind: "unset" }
  | { readonly kind: "accepted"; readonly url: DevServerUrl }
  | { readonly kind: "ignored"; readonly reason: DevServerIgnoredReason };

/**
 * Decides whether the shell honours `raw`, the `CV_DEV_SERVER_URL` value (undefined when not
 * set). Accepted: `http://127.0.0.1:<port>` or `http://localhost:<port>` with a port from 1 to
 * 65535 and no credentials, in an unpackaged build. The result never carries a rejected value.
 * An accepted value comes back as the parser's canonical href, the URL the window loads, so
 * another spelling of the two hosts (`127.1`, `0x7f.0.0.1`) loads as one of those two origins.
 */
export function resolveDevServerUrl(
  raw: string | undefined,
  isPackaged: boolean,
): DevServerResolution {
  if (raw === undefined) {
    return { kind: "unset" };
  }
  if (isPackaged) {
    return { kind: "ignored", reason: "unpackaged-only" };
  }
  if (!PRINTABLE_ASCII.test(raw)) {
    return { kind: "ignored", reason: "malformed" };
  }
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return { kind: "ignored", reason: "malformed" };
  }
  if (parsed.protocol !== "http:" || !LOOPBACK_HOSTS.has(parsed.hostname)) {
    return { kind: "ignored", reason: "not-loopback-http" };
  }
  // The parser rejects ports above 65535 and drops the scheme's default (80), leaving "".
  const port = Number(parsed.port);
  if (parsed.username !== "" || parsed.password !== "" || port < 1) {
    return { kind: "ignored", reason: "malformed" };
  }
  return { kind: "accepted", url: parsed.href as DevServerUrl };
}
