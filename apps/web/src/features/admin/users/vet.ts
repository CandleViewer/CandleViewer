/**
 * The users screens' vetting (E42-S02), in the admin read layer's way (`overview/adminReads.ts`): every served shape
 * is checked before anything shows it, a field a row does not read is dropped, and a value of another shape is never
 * guessed. A status the client does not know reads as unknown, never Active; an id that is not a UUID drops its row,
 * so every target a write names was served (BQ-5); an invite's link is accepted only as a relative `/invite/…`
 * path, so composing it with the page's origin can never name another host.
 */
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];
export type RoleName = Schemas["RoleName"];
export type UserStatus = Schemas["UserStatus"];
export type Environment = Schemas["Environment"];

/** A user id the server served, checked as a UUID: the only id a users path is built from. */
export type UserId = string & { readonly __servedUserId: true };

/** A `User` as a row reads it. */
export interface VettedUser {
  readonly id: UserId;
  readonly username: string;
  readonly email: string;
  readonly display_name: string | null;
  /** The listed roles only; a role the client does not know is dropped. */
  readonly roles: readonly RoleName[];
  /** A status the client does not know is `unknown`: an unknown chip, never Active. */
  readonly status: UserStatus | "unknown";
  /** Absent from the answer: not known, never false. */
  readonly mfa_enabled: boolean | null;
  /** RFC 3339, or null: never signed in, or a time the client cannot read. */
  readonly last_login_at: string | null;
}

/** A page of the list: its users and its cursor. */
export interface UserPage {
  readonly items: readonly VettedUser[];
  readonly hasMore: boolean;
  readonly nextCursor: string | null;
}

/** A pending invite (`api/invites.py`; untyped in `22`, E42-D03 CG-14): never a link. */
export interface PendingInvite {
  readonly user_id: UserId;
  readonly username: string;
  readonly email: string;
  readonly display_name: string | null;
  readonly role: string;
  readonly expires_at: string;
  readonly expired: boolean;
}

/** A user's grant on one account (`AccountAccessGrant`), as the Accounts cell reads it. */
export interface Grant {
  readonly exchange_account_id: string;
  readonly level: "read" | "trade";
  readonly account_label?: string | undefined;
  readonly environment?: Environment | undefined;
}

/** A two-factor reset's preview: whether the open positions are known (D21). */
export interface MfaResetPreview {
  readonly positions: "known" | "unavailable";
  /** Null when the position state is unknown: never a fabricated 0. */
  readonly openPositionCount: number | null;
  readonly requiresAcknowledge: boolean;
}

/** A two-factor reset's answer: what it revoked. */
export interface MfaResetDone {
  readonly methodsRevoked: number;
  readonly sessionsRevoked: number;
}

/** A create's `201` (`UserWithInvite`) and a re-issue's, one shape: the one-time link and its expiry. */
export interface CreatedInvite {
  readonly id: UserId;
  readonly username: string;
  /** Relative: `/invite/{token}`. The caller composes it with the page's origin and keeps it in its own state. */
  readonly invite_url: string;
  readonly invite_expires_at: string;
}

type Json = Readonly<Record<string, unknown>>;

const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ROLES: ReadonlySet<string> = new Set<RoleName>(["owner", "manager", "viewer"]);
const STATUSES: ReadonlySet<string> = new Set<UserStatus>([
  "invited",
  "active",
  "disabled",
  "locked",
]);
const ENVIRONMENTS: ReadonlySet<string> = new Set<Environment>(["live", "demo", "testnet"]);
/** The longest name or address a row shows (the server's own caps are shorter). */
const MAX_TEXT = 320;
/** A relative one-time link: `/invite/` and a URL-safe token, nothing that could leave the page's origin. */
const INVITE_PATH = /^\/invite\/[A-Za-z0-9_-]{1,512}$/;

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value.length <= MAX_TEXT ? value : undefined;
const time = (value: unknown): string | undefined =>
  typeof value === "string" && Number.isFinite(Date.parse(value)) ? value : undefined;
const count = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;
const listOf = (raw: unknown, name: string): readonly unknown[] | null =>
  isRecord(raw) && Array.isArray(raw[name]) ? (raw[name] as readonly unknown[]) : null;
const kept = <T>(items: readonly unknown[], vet: (raw: unknown) => T | null): T[] =>
  items.map(vet).filter((item): item is T => item !== null);

const isUuid = (raw: unknown): raw is string => typeof raw === "string" && UUID.test(raw);

/** A served user id, or null: a UUID only. */
export function userIdOf(raw: unknown): UserId | null {
  return isUuid(raw) ? (raw as UserId) : null;
}

export function vetUser(raw: unknown): VettedUser | null {
  if (!isRecord(raw)) return null;
  const id = userIdOf(raw["id"]);
  const username = text(raw["username"]);
  const email = text(raw["email"]);
  if (id === null || username === undefined || email === undefined) return null;
  const status = raw["status"];
  const roles = Array.isArray(raw["roles"]) ? (raw["roles"] as readonly unknown[]) : [];
  const mfa = raw["mfa_enabled"];
  return {
    id,
    username,
    email,
    display_name: text(raw["display_name"]) ?? null,
    roles: roles.filter((role): role is RoleName => typeof role === "string" && ROLES.has(role)),
    status: typeof status === "string" && STATUSES.has(status) ? (status as UserStatus) : "unknown",
    mfa_enabled: typeof mfa === "boolean" ? mfa : null,
    last_login_at: time(raw["last_login_at"]) ?? null,
  };
}

/** `GET /users`: `Page` + `User[]`; a page without its `meta` is unreadable. */
export function vetUserPage(raw: unknown): UserPage | null {
  const items = listOf(raw, "items");
  const meta = isRecord(raw) ? raw["meta"] : undefined;
  if (items === null || !isRecord(meta) || typeof meta["has_more"] !== "boolean") return null;
  const cursor = typeof meta["next_cursor"] === "string" ? meta["next_cursor"] : null;
  // A page that says it has more but gives no cursor cannot be followed: no further page is read.
  const hasMore = meta["has_more"] && cursor !== null && cursor !== "";
  return { items: kept(items, vetUser), hasMore, nextCursor: hasMore ? cursor : null };
}

function vetInvite(raw: unknown): PendingInvite | null {
  if (!isRecord(raw)) return null;
  const user_id = userIdOf(raw["user_id"]);
  const username = text(raw["username"]);
  const email = text(raw["email"]);
  const role = text(raw["role"]);
  const expires_at = time(raw["expires_at"]);
  const expired = raw["expired"];
  if (
    user_id === null ||
    username === undefined ||
    email === undefined ||
    role === undefined ||
    expires_at === undefined ||
    typeof expired !== "boolean"
  ) {
    return null;
  }
  const display_name = text(raw["display_name"]) ?? null;
  return { user_id, username, email, display_name, role, expires_at, expired };
}

/** `GET /users/invites`. */
export function vetPendingInvites(raw: unknown): readonly PendingInvite[] | null {
  const items = listOf(raw, "items");
  return items === null ? null : kept(items, vetInvite);
}

function vetGrant(raw: unknown): Grant | null {
  if (!isRecord(raw)) return null;
  const account = raw["exchange_account_id"];
  const level = raw["level"];
  if (!isUuid(account) || (level !== "read" && level !== "trade")) return null;
  const label = text(raw["account_label"]);
  const env = raw["environment"];
  return {
    exchange_account_id: account,
    level,
    ...(label === undefined ? {} : { account_label: label }),
    ...(typeof env === "string" && ENVIRONMENTS.has(env)
      ? { environment: env as Environment }
      : {}),
  };
}

/** `GET /users/{id}/account-access`. */
export function vetGrants(raw: unknown): readonly Grant[] | null {
  const items = listOf(raw, "items");
  return items === null ? null : kept(items, vetGrant);
}

/** `GET /users/{id}/sessions`: the count alone, never a session's device, address or agent. */
export function vetSessionCount(raw: unknown): number | null {
  const items = listOf(raw, "items");
  return items === null ? null : items.length;
}

/** `GET /users/{id}/mfa/reset-preview`. */
export function vetMfaPreview(raw: unknown): MfaResetPreview | null {
  if (!isRecord(raw)) return null;
  const positions = raw["positions"];
  const requires = raw["requires_acknowledge_unknown_positions"];
  if ((positions !== "known" && positions !== "unavailable") || typeof requires !== "boolean") {
    return null;
  }
  return {
    positions,
    openPositionCount: count(raw["open_position_count"]) ?? null,
    requiresAcknowledge: requires,
  };
}

/** `POST /users/{id}/mfa/reset`'s `200`. */
export function vetMfaReset(raw: unknown): MfaResetDone | null {
  if (!isRecord(raw)) return null;
  const methods = count(raw["methods_revoked"]);
  const sessions = count(raw["sessions_revoked"]);
  return methods === undefined || sessions === undefined
    ? null
    : { methodsRevoked: methods, sessionsRevoked: sessions };
}

/** `POST /users`'s `201` and `POST /users/{id}/invite`'s: a relative link and its expiry, or nothing. */
export function vetCreatedInvite(raw: unknown): CreatedInvite | null {
  if (!isRecord(raw)) return null;
  const id = userIdOf(raw["id"]);
  const username = text(raw["username"]);
  const url = raw["invite_url"];
  const expires = time(raw["invite_expires_at"]);
  if (id === null || username === undefined || expires === undefined) return null;
  if (typeof url !== "string" || !INVITE_PATH.test(url)) return null;
  return { id, username, invite_url: url, invite_expires_at: expires };
}
