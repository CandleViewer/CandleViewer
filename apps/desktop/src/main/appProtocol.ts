import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * The `app://` scheme the shell serves the built web app from, instead of `file://` (#3410,
 * SR-174). Vite emits root-absolute asset URLs (`/assets/...`), which under `file://` resolve to
 * the filesystem root, so the window stayed blank. A privileged custom scheme gives the app one
 * fixed origin, a handler that can only read files under the web app's dist root, and one place
 * that attaches the shell's CSP header (SR-112) to every response. A `file://` page instead shares
 * the broad file origin, which is why the Electron security checklist recommends a custom protocol.
 */
export const APP_SCHEME = "app";
export const APP_HOST = "candleviewer";

/** The URL the main window loads when no dev server is configured. */
export const APP_ENTRY_URL = `${APP_SCHEME}://${APP_HOST}/`;

/**
 * Privileges for the `app:` scheme, limited to what the web app needs (unit tests and the
 * electron-hardening gate pin this exact set):
 * - `standard`: a hierarchical URL with a host, so root-absolute and relative URLs resolve, the
 *   page has a real origin for CSP `'self'`, React Router's browser router can change the path
 *   with the history API, and web storage works.
 * - `secure`: a secure context, as the `file://` page and the loopback dev server already were,
 *   so secure-context-only APIs (for example the clipboard) behave the same.
 * Not granted: CSP bypass, renderer `fetch()` of `app:` URLs, CORS, service workers, streaming
 * and the code cache. The web app needs none of them.
 */
export const APP_SCHEME_PRIVILEGES = { standard: true, secure: true } as const;

const CONTENT_TYPES: ReadonlyMap<string, string> = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json"],
  [".map", "application/json"],
  [".svg", "image/svg+xml"],
  [".png", "image/png"],
  [".ico", "image/x-icon"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
  [".wasm", "application/wasm"],
  [".txt", "text/plain; charset=utf-8"],
]);

/** Content-Type for a served file, from its extension; unknown types are opaque bytes. */
export function contentTypeFor(filePath: string): string {
  return CONTENT_TYPES.get(path.extname(filePath).toLowerCase()) ?? "application/octet-stream";
}

/** One handler response as plain data, so the mapping is testable without Electron. */
export interface AppResponse {
  readonly status: 200 | 404 | 405;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: Uint8Array | string;
}

/** Reads one file; resolves null when it is missing or is not a regular file. */
export type DistReader = (absolutePath: string) => Promise<Uint8Array | null>;

function parseAppUrl(url: string): URL | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  // Node's URL reports origin "null" for non-special schemes such as app:, so compare the
  // protocol and host fields instead of `.origin`.
  const onAppOrigin =
    parsed.protocol === `${APP_SCHEME}:` &&
    parsed.host === APP_HOST &&
    parsed.username === "" &&
    parsed.password === "";
  return onAppOrigin ? parsed : null;
}

/** True only for the `app:` scheme with its one fixed host (no port, no credentials). */
export function isAppUrl(url: string): boolean {
  return parseAppUrl(url) !== null;
}

function isInside(root: string, target: string): boolean {
  const relative = path.relative(root, target);
  return relative !== "" && relative.split(path.sep)[0] !== ".." && !path.isAbsolute(relative);
}

/**
 * Maps an `app://` request URL to a file path inside `root`, or null when the URL is not on the
 * app origin or its path is not servable (SR-174): the path is decoded once, NUL and backslash
 * are refused, and the resolved path must stay inside `root`. The root itself maps to index.html.
 */
export function resolveDistPath(url: string, root: string): string | null {
  const parsed = parseAppUrl(url);
  if (parsed === null) {
    return null;
  }
  let decoded: string;
  try {
    decoded = decodeURIComponent(parsed.pathname);
  } catch {
    return null;
  }
  if (decoded.includes("\0") || decoded.includes("\\")) {
    return null;
  }
  const base = path.resolve(root);
  const target = path.resolve(base, `.${decoded}`);
  if (target === base) {
    return path.join(base, "index.html");
  }
  return isInside(base, target) ? target : null;
}

/**
 * Builds the response for one `app://` request: a read-only static-file server over `root`
 * (SR-174) that attaches `csp` to every response, errors included (SR-112). Only GET and HEAD
 * are served; any other method gets 405. Error bodies are fixed text and never echo the path.
 */
export async function resolveAppRequest(
  url: string,
  root: string,
  read: DistReader,
  csp: string,
  method = "GET",
): Promise<AppResponse> {
  const baseHeaders = { "content-security-policy": csp, "x-content-type-options": "nosniff" };
  const textHeaders = { ...baseHeaders, "content-type": "text/plain; charset=utf-8" };
  const ok = (file: string, body: Uint8Array): AppResponse => ({
    status: 200,
    headers: { ...baseHeaders, "content-type": contentTypeFor(file) },
    body,
  });
  const notFound: AppResponse = { status: 404, headers: textHeaders, body: "Not found" };

  if (method !== "GET" && method !== "HEAD") {
    return { status: 405, headers: { ...textHeaders, allow: "GET, HEAD" }, body: "Not allowed" };
  }
  const file = resolveDistPath(url, root);
  if (file === null) {
    return notFound;
  }
  const body = await read(file);
  if (body !== null) {
    return ok(file, body);
  }
  // The web app routes with React Router's browser router (history API), so a missing path
  // without an extension is a client route (for example /login) and gets index.html. A missing
  // asset (with an extension) and anything under /api (the backend's prefix) stay a 404.
  const base = path.resolve(root);
  if (path.extname(file) !== "" || path.relative(base, file).split(path.sep)[0] === "api") {
    return notFound;
  }
  const index = path.join(base, "index.html");
  const indexBody = await read(index);
  return indexBody === null ? notFound : ok(index, indexBody);
}

/**
 * The handler's file reader. Symlinks are resolved and must still land inside `root`;
 * directories and anything else that is not a regular file read as missing, so nothing is
 * ever listed.
 */
export function createDistReader(root: string): DistReader {
  // eslint-disable-next-line security/detect-non-literal-fs-filename -- root is the shell's own web dist directory, fixed at startup
  const realRoot = fs.realpath(root).catch(() => null);
  return async (absolutePath) => {
    const base = await realRoot;
    if (base === null) {
      return null;
    }
    try {
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- resolveDistPath confined the path to the dist root; re-checked below after resolving symlinks
      const real = await fs.realpath(absolutePath);
      if (!isInside(base, real)) {
        return null;
      }
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- same confined path
      const stat = await fs.stat(real);
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- same confined path
      return stat.isFile() ? await fs.readFile(real) : null;
    } catch {
      return null;
    }
  };
}
