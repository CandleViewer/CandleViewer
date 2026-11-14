/**
 * SCR-121's list query (E42-S02, BQ-7): `role`, `status` and `q` live in the URL, so a filtered list is a deep link
 * (E42-D03 §7); each takes one listed value, `q` (a case-insensitive substring of username or e-mail, `22`'s ≤120)
 * is trimmed, and anything else is dropped, never sent. The list reads 50 users a page by cursor (the ticket; `22`
 * allows 500). Analytics learn whether a search is set, never its words.
 */
import type { RoleName, UserStatus } from "./vet";

/** `RoleName`, in `22`'s order. */
export const ROLE_NAMES = ["owner", "manager", "viewer"] as const satisfies readonly RoleName[];
/** `UserStatus`, in `22`'s order. */
export const USER_STATUSES = [
  "invited",
  "active",
  "disabled",
  "locked",
] as const satisfies readonly UserStatus[];
/** A page of the list (the ticket's 50; `22`'s `Limit` allows 1–500). */
export const PAGE_SIZE = 50;
/** `listUsers`' `q` `maxLength`. */
export const Q_MAX = 120;

export interface UsersQuery {
  readonly role?: RoleName;
  readonly status?: UserStatus;
  readonly q?: string;
}

const ROLE_SET: ReadonlySet<string> = new Set(ROLE_NAMES);
const STATUS_SET: ReadonlySet<string> = new Set(USER_STATUSES);
const NAMES = ["role", "status", "q"] as const;

/** One value of `name`, or undefined: a repeated parameter is no value. */
const single = (params: URLSearchParams, name: string): string | undefined => {
  const values = params.getAll(name);
  return values.length === 1 ? values[0] : undefined;
};

/** The list's query from the page's URL. */
export function usersQueryOf(params: URLSearchParams): UsersQuery {
  const role = single(params, "role");
  const status = single(params, "status");
  const q = single(params, "q")?.trim().slice(0, Q_MAX).trim();
  return {
    ...(role !== undefined && ROLE_SET.has(role) ? { role: role as RoleName } : {}),
    ...(status !== undefined && STATUS_SET.has(status) ? { status: status as UserStatus } : {}),
    ...(q === undefined || q === "" ? {} : { q }),
  };
}

/** The page's URL parameters for `query`, keeping the others `current` holds. */
export function usersSearch(query: UsersQuery, current: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(current);
  for (const name of NAMES) next.delete(name);
  if (query.role !== undefined) next.set("role", query.role);
  if (query.status !== undefined) next.set("status", query.status);
  if (query.q !== undefined && query.q !== "") next.set("q", query.q);
  return next;
}

/** `GET /users` for `query`, from its first page or from `cursor`. */
export function listPath(query: UsersQuery, cursor?: string): string {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (query.role !== undefined) params.set("role", query.role);
  if (query.status !== undefined) params.set("status", query.status);
  if (query.q !== undefined && query.q !== "") params.set("q", query.q);
  if (cursor !== undefined) params.set("cursor", cursor);
  return `/api/v1/users?${params.toString()}`;
}

/** `admin.users_list_viewed`'s filters (BQ-9): the role and the status, and whether a search is set. */
export function analyticsFilters(query: UsersQuery): {
  readonly role: RoleName | null;
  readonly status: UserStatus | null;
  readonly q: boolean;
} {
  return {
    role: query.role ?? null,
    status: query.status ?? null,
    q: query.q !== undefined && query.q !== "",
  };
}
