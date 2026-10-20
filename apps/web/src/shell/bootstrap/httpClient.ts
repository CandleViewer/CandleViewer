/**
 * Minimal fetch wrapper for the bootstrap calls. No React import needed
 * here (`no fetch/network singletons in the chart engine` doesn't apply to
 * the app shell, only to `packages/chart-engine`), but we still keep this
 * tiny and dependency-free per `AGENTS.md` §5.1 (no new deps without
 * justification).
 */
import { accessToken } from "../../lib/auth/accessToken.js";

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export class HttpTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HttpTimeoutError";
  }
}

export interface FetchJsonOptions {
  readonly timeoutMs: number;
  readonly signal?: AbortSignal | undefined;
  /** Test seam; defaults to the global `fetch`. */
  readonly fetchImpl?: typeof fetch | undefined;
}

/**
 * Fetches `path` and parses the JSON body, applying `timeoutMs` as an
 * `AbortController` timeout composed with any caller-supplied signal.
 * Throws `HttpError` on a non-2xx response and `HttpTimeoutError` if the
 * request is aborted by the timeout specifically (distinguished so callers
 * can show a "slow boot" state rather than a generic failure).
 */
export async function fetchJson<T>(path: string, options: FetchJsonOptions): Promise<T> {
  const { timeoutMs, signal, fetchImpl = fetch } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const onExternalAbort = (): void => controller.abort();
  signal?.addEventListener("abort", onExternalAbort);

  try {
    // #2712: the tab's bearer, and one refresh then one more try on a 401
    const response = await accessToken.send(
      path,
      {
        method: "GET",
        credentials: "include",
        signal: controller.signal,
        headers: { accept: "application/json" },
      },
      (init) => fetchImpl(path, init),
    );
    if (!response.ok) {
      throw new HttpError(response.status, `${path} responded ${response.status}`);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (controller.signal.aborted && !(signal?.aborted ?? false)) {
      throw new HttpTimeoutError(`${path} timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", onExternalAbort);
  }
}
