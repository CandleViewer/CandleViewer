/**
 * The profile screens' REST calls (E28-S01, #971), typed from the generated contract
 * (`packages/protocol`, C-4.16): `listExchangeAccounts`, then the profile operations under
 * `/exchange-accounts/{accountId}/profiles` (`22`). Writes are Owner-only behind the `risk_caps`
 * step-up, which the server enforces (SR-025): a `403 step_up_required` comes back as a hold the
 * screen answers with `StepUpChallengeGate`, re-sending the same request (same `Idempotency-Key`).
 * Nothing here decides a cap, a size or an access: the client sends the policy, the server judges.
 */
import type { generated } from "@candleviewer/protocol";
import {
  holdRequest,
  readChallenge,
  sendHeld,
  type HeldRequest,
  type StepUpChallenge,
} from "../../stepUp/challenge";
import { apiFetch } from "../../../lib/http/csrfFetch";

type Schemas = generated.rest.components["schemas"];
export type AccountProfile = Schemas["AccountProfile"];
export type AccountProfileInput = Schemas["AccountProfileInput"];
export type ProfileWarning = Schemas["ProfileWarning"];
export type ExchangeAccount = Schemas["ExchangeAccount"];
type FieldError = NonNullable<Schemas["Problem"]["errors"]>[number];

const BASE = "/api/v1";
/** `22` `Limit.maximum`, and a page bound so a bad cursor never loops. */
const PAGE = 500;
const MAX_PAGES = 10;
/** The longest served text shown (the contract bounds `detail` and `message` well below it). */
const MAX_TEXT = 500;

/** A read's outcome: `not_found` is the contract's `404` (missing, foreign-environment, ungranted). */
export type ReadOutcome<T> =
  | { readonly kind: "ok"; readonly value: T }
  | { readonly kind: "not_found" }
  | { readonly kind: "denied" }
  | { readonly kind: "failed" };

/** A refusal as the screen shows it: the served code, `detail` and field errors, vetted. */
export interface Refusal {
  readonly status: number;
  readonly code: string;
  readonly detail: string | null;
  readonly errors: readonly FieldError[];
}

/** A `403 step_up_required`: the challenge and the refused request, held unchanged. */
export interface StepUpHold {
  readonly challenge: StepUpChallenge;
  readonly held: HeldRequest;
}

export type WriteOutcome =
  | {
      readonly kind: "ok";
      readonly profile: AccountProfile | null;
      readonly etag: string | null;
    }
  | { readonly kind: "step_up"; readonly hold: StepUpHold }
  | { readonly kind: "refused"; readonly refusal: Refusal }
  /** No answer: the write may or may not have happened, so the caller reads back. */
  | { readonly kind: "unknown" };

const isRecord = (raw: unknown): raw is Record<string, unknown> =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);

const text = (raw: unknown): string | null =>
  typeof raw === "string" && raw.length <= MAX_TEXT ? raw : null;

/** The `Problem` fields a screen reads: strings only, bounded; anything else is dropped. */
export function vetRefusal(status: number, raw: unknown): Refusal {
  const body = isRecord(raw) ? raw : {};
  const errors: FieldError[] = [];
  for (const entry of Array.isArray(body["errors"]) ? body["errors"] : []) {
    if (!isRecord(entry)) continue;
    const error: Record<string, string> = {};
    for (const name of ["field", "rule", "message", "symbol", "limit"]) {
      const value = text(entry[name]);
      if (value !== null) error[name] = value;
    }
    errors.push(error as FieldError);
  }
  return { status, code: text(body["code"]) ?? "unknown", detail: text(body["detail"]), errors };
}

/** `W/"<id>:<version>"`, the profile's tag as `22` `ProfileETag` publishes it, for `If-Match`. */
export function profileETag(profile: Pick<AccountProfile, "id" | "version">): string {
  return `W/"${profile.id}:${profile.version}"`;
}

/** `22`'s id shape for accounts and profiles (`format: uuid`): 8-4-4-4-12 hex digits. */
const ID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The id as a path segment, only when it has the contract's id shape; otherwise `null`. */
export function pathId(id: string): string | null {
  return ID_SHAPE.test(id) ? id.toLowerCase() : null;
}

const accountPath = (accountId: string): string | null => {
  const id = pathId(accountId);
  return id === null ? null : `${BASE}/exchange-accounts/${id}/profiles`;
};

const profilePath = (accountId: string, profileId: string): string | null => {
  const base = accountPath(accountId);
  const id = pathId(profileId);
  return base === null || id === null ? null : `${base}/${id}`;
};

/** A request that names no valid id is not sent; a write answers as the contract's `404` would. */
const NO_SUCH_ID: WriteOutcome = {
  kind: "refused",
  refusal: { status: 404, code: "not_found", detail: null, errors: [] },
};

async function read<T>(
  url: string | null,
  vet: (raw: unknown) => T | null,
  signal?: AbortSignal,
  onResponse?: (res: Response) => void,
): Promise<ReadOutcome<T>> {
  if (url === null) return { kind: "not_found" };
  try {
    const res = await apiFetch(url, signal === undefined ? {} : { signal });
    onResponse?.(res);
    if (res.status === 404) return { kind: "not_found" };
    if (res.status === 403) return { kind: "denied" };
    if (!res.ok) return { kind: "failed" };
    const value = vet(await res.json());
    return value === null ? { kind: "failed" } : { kind: "ok", value };
  } catch {
    return { kind: "failed" };
  }
}

const isProfile = (raw: unknown): raw is AccountProfile =>
  isRecord(raw) &&
  typeof raw["id"] === "string" &&
  pathId(raw["id"]) !== null &&
  typeof raw["exchange_account_id"] === "string" &&
  pathId(raw["exchange_account_id"]) !== null &&
  typeof raw["version"] === "number" &&
  typeof raw["updated_at"] === "string" &&
  isRecord(raw["profile"]) &&
  Array.isArray(raw["warnings"]);

const isAccount = (raw: unknown): raw is ExchangeAccount =>
  isRecord(raw) &&
  typeof raw["id"] === "string" &&
  pathId(raw["id"]) !== null &&
  typeof raw["label"] === "string";

/** Every page of `listExchangeAccounts`, bounded: the Owner's accounts with labels and environments. */
export async function listAccounts(
  signal?: AbortSignal,
): Promise<ReadOutcome<readonly ExchangeAccount[]>> {
  const items: ExchangeAccount[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const after: string = cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`;
    const outcome: ReadOutcome<Record<string, unknown>> = await read(
      `${BASE}/exchange-accounts?limit=${PAGE}${after}`,
      (raw) => (isRecord(raw) && Array.isArray(raw["items"]) ? raw : null),
      signal,
    );
    if (outcome.kind !== "ok") return outcome;
    items.push(...(outcome.value["items"] as unknown[]).filter(isAccount));
    const meta: Record<string, unknown> = isRecord(outcome.value["meta"])
      ? outcome.value["meta"]
      : {};
    const next: unknown = meta["next_cursor"];
    if (meta["has_more"] !== true || typeof next !== "string") break;
    cursor = next;
  }
  return { kind: "ok", value: items };
}

/** `listAccountProfiles`: the account's live profiles, its default among them. */
export function listProfiles(
  accountId: string,
  signal?: AbortSignal,
): Promise<ReadOutcome<readonly AccountProfile[]>> {
  return read(
    accountPath(accountId),
    (raw) => (isRecord(raw) && Array.isArray(raw["items"]) ? raw["items"].filter(isProfile) : null),
    signal,
  );
}

/** Reads the answer to a held write (its first send, or its re-send after a step-up). */
export async function readWrite(response: Response, held: HeldRequest): Promise<WriteOutcome> {
  const raw: unknown = response.status === 204 ? null : await response.json().catch(() => null);
  if (response.ok) {
    return {
      kind: "ok",
      profile: isProfile(raw) ? raw : null,
      etag: response.headers.get("ETag"),
    };
  }
  if (response.status === 403) {
    const challenge = readChallenge(raw, response.headers.get("Date"));
    if (challenge !== null) return { kind: "step_up", hold: { challenge, held } };
  }
  return { kind: "refused", refusal: vetRefusal(response.status, raw) };
}

async function write(
  method: "POST" | "PUT" | "DELETE",
  url: string | null,
  body: AccountProfileInput | null,
  ifMatch: string | null,
): Promise<WriteOutcome> {
  if (url === null) return NO_SUCH_ID;
  // One key per write, held with the request: a re-send after a step-up is the same submission.
  const headers: Record<string, string> = { "Idempotency-Key": crypto.randomUUID() };
  if (body !== null) headers["Content-Type"] = "application/json";
  if (ifMatch !== null) headers["If-Match"] = ifMatch;
  const held = holdRequest(method, url, headers, body === null ? null : JSON.stringify(body));
  try {
    return await readWrite(await sendHeld(held), held);
  } catch {
    return { kind: "unknown" };
  }
}

/** `getAccountProfile`: the profile and its `ETag`, which a replace or a delete sends as `If-Match`. */
export async function getProfile(
  accountId: string,
  profileId: string,
  signal?: AbortSignal,
): Promise<ReadOutcome<{ readonly profile: AccountProfile; readonly etag: string }>> {
  const seen: { etag: string | null } = { etag: null };
  const outcome = await read(
    profilePath(accountId, profileId),
    (raw) => (isProfile(raw) ? raw : null),
    signal,
    (res) => {
      seen.etag = res.headers.get("ETag");
    },
  );
  if (outcome.kind !== "ok") return outcome;
  // The contract always tags a profile; a missing tag falls back to its published form.
  return {
    kind: "ok",
    value: { profile: outcome.value, etag: seen.etag ?? profileETag(outcome.value) },
  };
}

/** `createAccountProfile`: a new alternate at `version` 1 (`is_default` is never sent true). */
export function createProfile(accountId: string, body: AccountProfileInput): Promise<WriteOutcome> {
  return write("POST", accountPath(accountId), body, null);
}

/** `updateAccountProfile`: the whole profile, `If-Match` the tag it was read with. */
export function updateProfile(
  accountId: string,
  profileId: string,
  body: AccountProfileInput,
  etag: string,
): Promise<WriteOutcome> {
  return write("PUT", profilePath(accountId, profileId), body, etag);
}

/** `deleteAccountProfile` with the profile's tag; `409` names each served blocker in `detail`. */
export function deleteProfile(profile: AccountProfile): Promise<WriteOutcome> {
  return write(
    "DELETE",
    profilePath(profile.exchange_account_id, profile.id),
    null,
    profileETag(profile),
  );
}

export interface ProfilesApi {
  readonly listAccounts: typeof listAccounts;
  readonly listProfiles: typeof listProfiles;
  readonly getProfile: typeof getProfile;
  readonly createProfile: typeof createProfile;
  readonly updateProfile: typeof updateProfile;
  readonly deleteProfile: typeof deleteProfile;
  readonly readWrite: typeof readWrite;
}

/** The seam the screens and their tests share. */
export const profilesApi: ProfilesApi = {
  listAccounts,
  listProfiles,
  getProfile,
  createProfile,
  updateProfile,
  deleteProfile,
  readWrite,
};
