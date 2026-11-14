/**
 * The users client over the served routes (E42-S02; `22` tag users, BQ-1, BQ-3, BQ-6). Reads go through the admin
 * read layer (`readAdmin`: one 3 s bound; a `403` is the area denied), and `GET /users` answering `405` reads as not
 * built too, since `POST /users` holds the path until `listUsers` mounts (BQ-1); a `404` on a per-user read is a
 * failed read, `22` declaring `404 NotFound` there. Writes go through the admin write
 * kit: held as first sent, one `Idempotency-Key` per call (a step-up re-send is the held request; a Retry or a
 * renewal calls again, so it is a new attempt; the tier write, whose route ignores the key, sends none), the CSRF
 * header from `apiFetch`, and the first send bounded as the gate bounds the re-send (no answer in time is an
 * unknown outcome, read back). An invite asks for a viewer with two-factor and never for account access; a disable
 * and a delete carry `acknowledge_unknown_positions` (D21: no position source is wired, so the count is always
 * unknown), and a two-factor reset carries it only when the owner ticked it. Every path is a fixed template filled
 * with a served user id checked as a UUID; any other target throws before anything is sent. The one-time link in a
 * create's or a re-issue's answer goes to the caller alone.
 */
import { RESEND_TIMEOUT_MS } from "../../stepUp/StepUpChallengeGate";
import { readAdmin, type ReadOutcome, type ReadTimers } from "../overview/adminReads";
import { newAttempt } from "../write/idempotency";
import { holdWrite, sendWrite, type WriteMethod, type WriteResult } from "../write/writeCall";
import { listPath, type UsersQuery } from "./query";
import {
  userIdOf,
  vetCreatedInvite,
  vetGrants,
  vetMfaPreview,
  vetMfaReset,
  vetPendingInvites,
  vetSessionCount,
  vetUser,
  vetUserPage,
  type CreatedInvite,
  type Grant,
  type MfaResetDone,
  type MfaResetPreview,
  type PendingInvite,
  type UserId,
  type UserPage,
  type VettedUser,
} from "./vet";

const BASE = "/api/v1";

/** Each operation the client calls: `22`'s path template and method (the contract test pins both). */
export const USERS_ROUTES = {
  listUsers: { path: "/users", method: "GET" },
  createUser: { path: "/users", method: "POST" },
  updateUser: { path: "/users/{userId}", method: "PATCH" },
  deleteUser: { path: "/users/{userId}", method: "DELETE" },
  listUserAccountAccess: { path: "/users/{userId}/account-access", method: "GET" },
  listUserSessions: { path: "/users/{userId}/sessions", method: "GET" },
  previewMfaReset: { path: "/users/{userId}/mfa/reset-preview", method: "GET" },
  resetUserMfa: { path: "/users/{userId}/mfa/reset", method: "POST" },
  listPendingInvites: { path: "/users/invites", method: "GET" },
  reissueInvite: { path: "/users/{userId}/invite", method: "POST" },
  revokeInvite: { path: "/users/{userId}/invite", method: "DELETE" },
  setSubaccountTier: { path: "/admin/capacity/subaccount-tier", method: "PUT" },
} as const satisfies Readonly<Record<string, { readonly path: string; readonly method: string }>>;

type Route = keyof typeof USERS_ROUTES;

/** A route's URL: its template under `/api/v1`, `{userId}` filled with a served id, never anything else. */
function urlOf(route: Route, id?: UserId, query = ""): string {
  const { path } = USERS_ROUTES[route];
  if (!path.includes("{userId}")) return `${BASE}${path}${query}`;
  if (userIdOf(id) === null) throw new TypeError(`${route}: the target is not a served user id`);
  return `${BASE}${path.replace("{userId}", id as string)}${query}`;
}

/** The acknowledgement every disable and delete sends while the position count is unknown (D21). */
const ACKNOWLEDGED = "acknowledge_unknown_positions=true";

/** A write's first send waits as long as the gate lets its re-send wait; past it the outcome is unknown. */
export const WRITE_TIMEOUT_MS = RESEND_TIMEOUT_MS;

/** `readAdmin`'s outcome, with a `405` read as not built too: `listUsers` is not mounted yet (BQ-1). */
const notBuiltOn405 = <T>(outcome: ReadOutcome<T>): ReadOutcome<T> =>
  outcome.kind === "failed" && outcome.status === 405 ? { kind: "not_built" } : outcome;

/**
 * A per-user read's outcome with a `404` read as failed: `22` declares `404 NotFound` for a user that is gone, so it
 * is no "not built" (`readAdmin` folds `404` and `501` into `not_built`; here both read as a failed `404`).
 */
const goneOn404 = <T>(outcome: ReadOutcome<T>): ReadOutcome<T> =>
  outcome.kind === "not_built" ? { kind: "failed", reason: "status", status: 404 } : outcome;

/** `GET /users`: a page of 50 for `query`, from its first page or from `cursor`. */
export async function readUserPage(
  query: UsersQuery,
  cursor: string | undefined,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<ReadOutcome<UserPage>> {
  return notBuiltOn405(await readAdmin(listPath(query, cursor), vetUserPage, signal, timers));
}

/** `GET /users/invites`: the pending invites (never a link). */
export function readPendingInvites(
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<ReadOutcome<readonly PendingInvite[]>> {
  return readAdmin(urlOf("listPendingInvites"), vetPendingInvites, signal, timers);
}

/** `GET /users/{id}/account-access`: a row's grants (the Accounts cell; Disable's counts). */
export async function readGrants(
  id: UserId,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<ReadOutcome<readonly Grant[]>> {
  return goneOn404(await readAdmin(urlOf("listUserAccountAccess", id), vetGrants, signal, timers));
}

/** `GET /users/{id}/sessions`: how many sessions a disable signs out, and nothing else about them. */
export async function readSessionCount(
  id: UserId,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<ReadOutcome<number>> {
  return goneOn404(await readAdmin(urlOf("listUserSessions", id), vetSessionCount, signal, timers));
}

/** `GET /users/{id}/mfa/reset-preview`: whether the reset needs the unknown-positions tick. */
export async function readMfaPreview(
  id: UserId,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<ReadOutcome<MfaResetPreview>> {
  return goneOn404(await readAdmin(urlOf("previewMfaReset", id), vetMfaPreview, signal, timers));
}

/** SCR-123's inputs: the server's rules decide (`auth/models.py`: username 3–32 of `[A-Za-z0-9._-]`). */
export interface InviteInput {
  readonly username: string;
  readonly email: string;
  /** Optional; trimmed, and left out when empty. */
  readonly displayName?: string | undefined;
}

/** `CreateUserRequest` as SCR-123 sends it: a viewer with two-factor, never account access (#2109, BQ-6). */
export interface InviteBody {
  readonly username: string;
  readonly email: string;
  readonly display_name?: string;
  readonly roles: ["viewer"];
  readonly mfa_required: true;
}

/**
 * One write: a new attempt every call (`attempt` null where the route ignores the key), its first send bounded by
 * `WRITE_TIMEOUT_MS` (no answer by then is status 0: the caller reads the outcome back, never sends it again).
 */
async function write<T>(
  method: WriteMethod,
  url: string,
  vet: (raw: unknown) => T | null,
  body?: unknown,
  attempt: string | null = newAttempt(),
): Promise<WriteResult<T>> {
  const bound = new AbortController();
  const timer = setTimeout(() => bound.abort(), WRITE_TIMEOUT_MS);
  try {
    return await sendWrite(holdWrite(method, url, attempt, body), vet, bound.signal);
  } finally {
    clearTimeout(timer);
  }
}

const nothing = (): null => null;

export const usersApi = {
  /** `POST /users` (`users` step-up, CG-24): its `201` carries the one-time link, for the caller alone. */
  async invite(input: InviteInput): Promise<WriteResult<CreatedInvite>> {
    const display = input.displayName?.trim() ?? "";
    const body: InviteBody = {
      username: input.username,
      email: input.email,
      ...(display === "" ? {} : { display_name: display }),
      roles: ["viewer"],
      mfa_required: true,
    };
    return write("POST", urlOf("createUser"), vetCreatedInvite, body);
  },
  /** `PATCH /users/{id}` `{status: "disabled"}` with the acknowledgement (E42-D03 §7 U-8). */
  async disable(id: UserId): Promise<WriteResult<VettedUser>> {
    return write("PATCH", urlOf("updateUser", id, `?${ACKNOWLEDGED}`), vetUser, {
      status: "disabled",
    });
  },
  /** `PATCH /users/{id}` `{status: "active"}` (U-9; an anonymised user answers `409 conflict`). */
  async enable(id: UserId): Promise<WriteResult<VettedUser>> {
    return write("PATCH", urlOf("updateUser", id), vetUser, { status: "active" });
  },
  /** `DELETE /users/{id}?purge=true` with the acknowledgement (U-10, U-12): the history stays. */
  async remove(id: UserId): Promise<WriteResult<null>> {
    return write("DELETE", urlOf("deleteUser", id, `?purge=true&${ACKNOWLEDGED}`), nothing);
  },
  /**
   * `POST /users/{id}/mfa/reset` (U-11): the unknown-positions acknowledgement goes only when the owner gave it
   * (the preview asked for the tick and it was ticked, D03 §12); otherwise the body carries no flag (`22`'s default,
   * false).
   */
  async resetMfa(id: UserId, acknowledge: boolean): Promise<WriteResult<MfaResetDone>> {
    return write(
      "POST",
      urlOf("resetUserMfa", id),
      vetMfaReset,
      acknowledge ? { acknowledge_unknown_positions: true } : {},
    );
  },
  /** `POST /users/{id}/invite`: a new one-time link; any open one stops working. */
  async reissueInvite(id: UserId): Promise<WriteResult<CreatedInvite>> {
    return write("POST", urlOf("reissueInvite", id), vetCreatedInvite);
  },
  /** `DELETE /users/{id}/invite`: the link stops working now. */
  async revokeInvite(id: UserId): Promise<WriteResult<null>> {
    return write("DELETE", urlOf("revokeInvite", id), nothing);
  },
  /**
   * `PUT /admin/capacity/subaccount-tier` (no step-up of its own, `22`; `x-idempotency: ignored`, so no key); the
   * caller re-reads capacity.
   */
  async setTier(tier: "regular" | "business_kyc"): Promise<WriteResult<null>> {
    return write("PUT", urlOf("setSubaccountTier"), nothing, { tier }, null);
  },
} as const;
