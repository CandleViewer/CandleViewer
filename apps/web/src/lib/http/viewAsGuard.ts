/**
 * The view-as request guard (E42-S03, SCR-124; `22` "View-as session"): a courtesy in front of
 * the server's own guard, never the control (C-2.12, C-12.4). While the session holds a view-as
 * context, `apiFetch` asks `viewAsRefusal` first, and a request the server would refuse gets the
 * same `403` here, built locally: nothing is sent, so it spends none of the viewer's hourly refusal
 * budget (`view_as_refusal_budget_per_hour`), and nothing is logged.
 *
 * - The viewer's own operations and the eight protective writes always pass, live or held: the
 *   server decides them (C-2.6, C-4.14: a protective write is never refused here). The lists are
 *   `services/api/candleviewer/api/view_as_policy.py`'s, and both lanes pin them: the web suite's
 *   `viewAsGuard.test.ts` reads that file, and the py suite's
 *   `services/api/tests/unit/api/test_view_as_web_guard_parity.py` reads this one, each failing
 *   closed if the other file moves, cannot be parsed in whole or differs. So a change to either
 *   side alone fails its own lane until the other follows.
 * - Live (`active`): every other write method is refused `view_as_read_only`, and so is a refused
 *   read (`REFUSED_READS`, or a `HEAD` of one); every other read passes, answered as the target.
 * - Held (`expired`): every other request is refused `view_as_expired`, reads included.
 *
 * Only a same-origin `/api/v1/` request is judged; with no context held (`none`, or `unknown`
 * before the boot read) every request passes. The server's own `view_as_*` answers seen by
 * `apiFetch` are reported to `onServerRefusal` listeners: the view-as source re-reads on one.
 */
import type { generated } from "@candleviewer/protocol";
import { getShellState, type ViewAsState } from "../../shell/bootstrap/store";
import { sameOriginUrl } from "./sameOrigin";

type Problem = generated.rest.components["schemas"]["Problem"];
/** `(METHOD, contract path template)`, the template relative to `/api/v1` (`view_as_policy.py`). */
export type ViewAsOperation = readonly [method: string, template: string];
export type ViewAsRefusalCode = "view_as_read_only" | "view_as_expired";

/** `OWN_OPERATIONS`: the start, reading and ending the context, and the session's own calls. */
export const OWN_OPERATIONS: readonly ViewAsOperation[] = [
  ["POST", "/admin/view-as"],
  ["GET", "/auth/session/view-as"],
  ["DELETE", "/auth/session/view-as"],
  ["GET", "/auth/session"],
  ["POST", "/auth/refresh"],
  ["POST", "/auth/logout"],
  ["POST", "/auth/session/extend"],
  ["POST", "/auth/lock"],
  ["POST", "/auth/unlock"],
  ["POST", "/telemetry/frontend"],
];

/** `PROTECTIVE_WRITES` (C-2.6), by operationId: the server's handlers decide each one. */
export const PROTECTIVE_WRITES: Readonly<Record<string, ViewAsOperation>> = {
  setKillSwitch: ["POST", "/trading/kill-switch"],
  amendOrder: ["PATCH", "/orders/{orderId}"],
  amendTradeGroup: ["POST", "/trade-groups/{tradeGroupId}/amend"],
  setPositionTpSl: ["PUT", "/positions/{positionId}/tpsl"],
  cancelOrder: ["DELETE", "/orders/{orderId}"],
  cancelAllOrders: ["POST", "/orders/cancel-all"],
  closePosition: ["POST", "/positions/{positionId}/close"],
  closeAllPositions: ["POST", "/positions/close-all"],
};

/** `REFUSED_READS`, by operationId: a read the server refuses in a live context as a write. */
export const REFUSED_READS: Readonly<Record<string, ViewAsOperation>> = {
  exportWorkspace: ["GET", "/workspaces/{workspaceId}/export"],
};

/** The synthetic answer's `instance`: a client refusal, never a server correlation id. */
export const CLIENT_REFUSAL_INSTANCE = "urn:cv:client:view-as";

/** The `x-error-codes` titles of the two refusals (`22`), verbatim; the test pins them. */
export const REFUSAL_TITLES: Readonly<Record<ViewAsRefusalCode, string>> = {
  view_as_read_only: "Session is viewing as another user, read-only; end view-as to make changes",
  view_as_expired:
    "View-as context ended by the server; clear it with DELETE /auth/session/view-as",
};

const API = "/api/v1";
const SAFE: ReadonlySet<string> = new Set(["GET", "HEAD", "OPTIONS"]);

type Matcher = (method: string, path: string) => boolean;

/** A template as the router matches it: each `{param}` one path segment, the rest literal. */
function matcher([method, template]: ViewAsOperation): Matcher {
  const source = template
    .split(/\{[^/{}]+\}/)
    .map((part) => part.replace(/[.*+?^$()|[\]\\]/g, "\\$&"))
    .join("[^/]+");
  const pattern = new RegExp(`^${source}$`);
  return (m, path) => m === method && pattern.test(path);
}

const OWN = OWN_OPERATIONS.map(matcher);
const PROTECTIVE = Object.values(PROTECTIVE_WRITES).map(matcher);
const REFUSED = Object.values(REFUSED_READS).map(matcher);
const passes = (list: readonly Matcher[], method: string, path: string): boolean =>
  list.some((match) => match(method, path));

/** A refused read, or a `HEAD` of one (the server records it under its `GET`). */
const refusedRead = (method: string, path: string): boolean =>
  passes(REFUSED, method === "HEAD" ? "GET" : method, path);

function refusal(code: ViewAsRefusalCode): Response {
  const body: Problem = {
    type: `https://candleviewer.local/errors/${code}`,
    title: REFUSAL_TITLES[code],
    status: 403,
    code,
    instance: CLIENT_REFUSAL_INSTANCE,
  };
  return new Response(JSON.stringify(body), {
    status: 403,
    headers: { "content-type": "application/problem+json" },
  });
}

/** The request's method as `fetch` sends it: `init` first, then a `Request`'s own, else `GET`. */
export function methodOf(input: RequestInfo | URL, init: RequestInit = {}): string {
  return (init.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
}

/**
 * The local `403` for a request the held context refuses, or `null`: send it. `state` is the
 * shell store's context unless a test passes one.
 */
export function viewAsRefusal(
  input: RequestInfo | URL,
  method: string,
  state: ViewAsState = getShellState().viewAs,
): Response | null {
  if (state.kind !== "held") return null;
  const url = sameOriginUrl(input);
  if (url === null || !url.pathname.startsWith(`${API}/`)) return null;
  const path = url.pathname.slice(API.length);
  const verb = method.toUpperCase();
  if (passes(OWN, verb, path) || passes(PROTECTIVE, verb, path)) return null;
  if (state.state === "expired") return refusal("view_as_expired");
  return SAFE.has(verb) && !refusedRead(verb, path) ? null : refusal("view_as_read_only");
}

const VIEW_AS_CODES: ReadonlySet<unknown> = new Set<ViewAsRefusalCode>([
  "view_as_read_only",
  "view_as_expired",
]);
const serverRefusals = new Set<() => void>();

/** Calls `listener` on each server answer `403 view_as_read_only` or `view_as_expired`. */
export function onServerRefusal(listener: () => void): () => void {
  serverRefusals.add(listener);
  return () => serverRefusals.delete(listener);
}

/**
 * `apiFetch`'s look at a server answer: a `403` whose problem `code` is a view-as refusal tells the
 * listeners. The body is read from a clone taken now, so the caller's copy stays unread; an answer
 * that cannot be cloned (its body already read) is the caller's as it is, never a rejection.
 */
export function noteServerAnswer(res: Response): Response {
  if (res.status !== 403 || serverRefusals.size === 0) return res;
  let copy: Response;
  try {
    copy = res.clone();
  } catch {
    return res; // no body to look at: not a refusal this module can name
  }
  void copy
    .json()
    .then((body: unknown) => {
      // a problem body or anything else: `code` is read as `unknown` and compared, never trusted
      const code = (body as { code?: unknown } | null)?.code;
      if (VIEW_AS_CODES.has(code)) for (const listener of [...serverRefusals]) listener();
    })
    .catch(() => undefined); // no problem body: not a view-as refusal
  return res;
}
