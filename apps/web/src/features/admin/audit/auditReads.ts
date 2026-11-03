/**
 * The audit log's calls (E42-S04; E42-D04 §4 and §7; the build plan's §3): the list read and the
 * tamper check SCR-135 makes, each through `apiFetch` (the step-up module's `sendHeld`) and typed
 * from the generated contract (`docs/plan/22-api-openapi.yaml`, C-4.16); the incident read comes
 * with the integrity model, the export's calls with its job. Every answer settles as one of four
 * kinds:
 * - `ok`: a `2xx` whose body is vetted first. An unknown enum value or a missing or ill-shaped
 *   member is an unreadable answer, never a guessed value; members the contract does not name are
 *   dropped.
 * - `refused`: any other status, with the problem's `code`, `Retry-After` (the header, else the
 *   problem's `retry_after_seconds`), its `instance` as the Ref and its field errors (`field` and
 *   `rule` only: the server never echoes a value).
 * - `unknown`: a write that got no answer, so it may have run (D04 X11); a read never is.
 * - `failed`: a read that got no answer in its bound (`timeout`), none at all (`network`, an abort
 *   included), or an answer it could not read (`unreadable`).
 * List reads stop at 6 s (BQ-11, PROPOSED), above the query's 4 s server stop (`22`
 * `queryAuditLog` Limits), so the server's own `503` is what a slow query shows; the tamper check
 * waits past its 60 s run deadline (BQ-6).
 * `csrf_token_invalid` is `apiFetch`'s own retry. The module keeps no state: the stores own the
 * timing, at the cadences `AUDIT_CADENCE` sets together.
 */
import type { generated } from "@candleviewer/protocol";
import { holdRequest, sendHeld, type HeldRequest } from "../../stepUp/challenge";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;

export type AuditEntry = Schemas["AuditEntry"];
/** An entry's `outcome` (D3's words), not a call's answer. */
export type EntryOutcome = Schemas["AuditOutcome"];
export type Severity = Schemas["Severity"];
export type Environment = Schemas["Environment"];
export type PageMeta = Schemas["PageMeta"];
export type Problem = Schemas["Problem"];
/** `queryAuditLog`'s parameters: the filter set, `limit` and `cursor`. */
export type AuditQuery = NonNullable<Ops["queryAuditLog"]["parameters"]["query"]>;
type QueryOk = Ops["queryAuditLog"]["responses"][200]["content"]["application/json"];
/** A list page as the browser keeps it: the served page, its items the generated entries. */
export type AuditPageBody = Pick<QueryOk, "chain_verified" | "meta"> & {
  readonly items: readonly AuditEntry[];
};
export type VerifyBody = NonNullable<
  Ops["verifyAuditChain"]["requestBody"]
>["content"]["application/json"];
export type VerifyResult = Ops["verifyAuditChain"]["responses"][200]["content"]["application/json"];
/** A problem's field error as the client keeps it: the field and the rule, never a message. */
export type FieldError = Required<Pick<NonNullable<Problem["errors"]>[number], "field" | "rule">>;

/** Whose entries a page reads: the Owner's raw log, or a Manager's own projection (SR-067). */
export type AuditView = "raw" | "own";

export interface AuditRefusal {
  readonly kind: "refused";
  readonly status: number;
  /** The problem's `code` (`x-error-codes`), or null when the answer carried none it could read. */
  readonly code: string | null;
  /** Seconds before a retry can pass: `Retry-After`, else the problem's `retry_after_seconds`. */
  readonly retryAfterS?: number | undefined;
  /** `Problem.instance` (`urn:cv:req:{id}`), the Ref; only in that shape. */
  readonly refId?: string | undefined;
  /** `400` / `422` field errors, at most ten (the server sends up to ten). */
  readonly errors?: readonly FieldError[] | undefined;
  /** The problem's `detail`, short text only. */
  readonly detail?: string | undefined;
}

export type AuditFailReason = "timeout" | "network" | "unreadable";

export type AuditAnswer<T> =
  | { readonly kind: "ok"; readonly body: T }
  | AuditRefusal
  | { readonly kind: "unknown" }
  | { readonly kind: "failed"; readonly reason: AuditFailReason };

export interface AuditTimers {
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (handle: unknown) => void;
}

export interface CallOptions {
  /** The caller stops waiting (the page unmounted, a newer read replaced this one). */
  readonly signal?: AbortSignal | undefined;
  readonly timers?: AuditTimers | undefined;
  /** The client's clock, for a `Retry-After` sent as a date. */
  readonly now?: (() => number) | undefined;
}

/**
 * BQ-11 (PROPOSED, as ruled): the list reads' bound (`queryAuditLog`), above
 * `audit_query_timeout_ms` (4,000, `22`), so the server's own `503` is what a slow query shows.
 */
export const AUDIT_READ_TIMEOUT_MS = 6_000;
/**
 * BQ-6 (PROPOSED, as ruled): Run tamper check is synchronous and may run until
 * `audit_verify_deadline_s` (60 s by default, `22` `verifyAuditChain` Limits), then writes its
 * result; the client waits past that, so a long run is never shown as lost while it still runs.
 */
export const VERIFY_TIMEOUT_MS = 75_000;
/**
 * The audit pages' cadences, set together (the orchestrator's ruling on #1135, "Polling cost"),
 * each PROPOSED. Every timed read writes audit rows, so this block is the pages' standing audit
 * volume. While SCR-135 is open and visible:
 * - `headRereadMs` (D04 D5): page 1 of the same filter set, for the "N new entries" pill. A known
 *   filter set is counted, not re-recorded, and its counts flush into one `admin.audit_read` at
 *   least every 300 s (`audit_read_flush_seconds`): about 12 rows an hour. It yields to any list
 *   read in flight.
 * - `incidentReadMs` (D04 §7, BQ-4): `listIncidents` for the integrity banner. It is on the
 *   admin-area guard, so each read writes an `admin.area_entered` row: 60 an hour. My activity
 *   never reads it (a Manager holds no `admin:read`).
 * - `jobPoll` (D13 as overridden by BQ-7): `getJob` while an export runs, 2 s, then 1 s longer
 *   each time up to 5 s. Each poll writes an `admin.area_entered` row: 13 in an export's first
 *   minute, then 12 a minute. After 10 failed polls in a row it backs off to one every 30 s until
 *   a poll answers, so an unreadable job is not polled at 5 s for as long as the page is open.
 * So an open SCR-135 writes about 72 rows an hour per session, and about 12 more a minute while
 * an export runs. Text filters apply on Enter or blur (BQ-3), and Environment sends no read (D7).
 */
export const AUDIT_CADENCE = {
  headRereadMs: 30_000,
  incidentReadMs: 60_000,
  jobPoll: { firstMs: 2_000, stepMs: 1_000, maxMs: 5_000, backoffAfter: 10, backoffMs: 30_000 },
} as const;

/**
 * The wait before job poll `n` (0 first): 2 s, then 1 s longer each time, never past 5 s; after
 * `backoffAfter` failed polls in a row, `backoffMs` until a poll answers again.
 */
export function jobPollDelay(n: number, failures = 0): number {
  const { firstMs, stepMs, maxMs, backoffAfter, backoffMs } = AUDIT_CADENCE.jobPoll;
  if (failures >= backoffAfter) return backoffMs;
  return Math.min(firstMs + Math.max(0, Math.floor(n)) * stepMs, maxMs);
}
/** The longest `Retry-After` taken as given; a longer one is read as a day. */
const MAX_RETRY_AFTER_S = 86_400;

/** The contract's paths (`22`, servers `/api/v1`). */
export const AUDIT_PATHS = {
  query: "/api/v1/admin/audit", // queryAuditLog
  verify: "/api/v1/admin/audit/verify", // verifyAuditChain
} as const;

const BROWSER_TIMERS: AuditTimers = {
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

type Json = Record<string, unknown>;

const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);
const isText = (raw: unknown): raw is string => typeof raw === "string";
const isTextOrNull = (raw: unknown): raw is string | null =>
  raw === null || typeof raw === "string";
const isInt = (raw: unknown): raw is number => typeof raw === "number" && Number.isSafeInteger(raw);
const isCount = (raw: unknown): raw is number => isInt(raw) && raw >= 0;
const isDate = (raw: unknown): raw is string =>
  typeof raw === "string" && Number.isFinite(Date.parse(raw));
const isIntOrNull = (raw: unknown): raw is number | null => raw === null || isInt(raw);

const HEX64 = /^[0-9a-f]{64}$/;
const CODE = /^[a-z][a-z0-9_]{0,63}$/;
const REF = /^[\w:.-]{1,128}$/;
/** The longest problem `detail` kept: the server's are one short sentence. */
const MAX_DETAIL = 300;
const MAX_ERRORS = 10;

/** A list holding every member of the generated union `T`: a member the contract adds fails tsc. */
const every =
  <T extends string>() =>
  <const L extends readonly T[]>(list: L & ([T] extends [L[number]] ? unknown : never)): L =>
    list;

const OUTCOMES = every<EntryOutcome>()(["success", "failure", "denied"]);
const SEVERITIES = every<Severity>()(["debug", "info", "warning", "error", "critical"]);
const ENVIRONMENTS = every<Environment>()(["live", "demo", "testnet"]);
const ELIDED = every<"before" | "after">()(["before", "after"]);

const member = <T extends string>(list: readonly T[], raw: unknown): raw is T =>
  typeof raw === "string" && (list as readonly string[]).includes(raw);

/**
 * `out[name]` = `raw[name]` when the contract's optional member is present and `ok` accepts it;
 * false when present and refused; absent stays absent.
 */
function optional(raw: Json, out: Json, name: string, ok: (value: unknown) => boolean): boolean {
  if (!(name in raw) || raw[name] === undefined) return true;
  if (!ok(raw[name])) return false;
  out[name] = raw[name];
  return true;
}

/** `PageMeta`: `has_more` and `count`, a cursor whenever there is more. */
function metaOf(raw: unknown): PageMeta | null {
  if (!isRecord(raw) || typeof raw["has_more"] !== "boolean" || !isCount(raw["count"])) {
    return null;
  }
  const next = raw["next_cursor"] ?? null;
  if (!isTextOrNull(next) || (raw["has_more"] && next === null)) return null;
  const meta: Json = { next_cursor: next, has_more: raw["has_more"], count: raw["count"] };
  if (!optional(raw, meta, "total", isIntOrNull)) return null;
  return meta as PageMeta;
}

/** `AuditEntry.detail`: an object; `before` and `after` objects or null; `elided` their names. */
function detailOf(raw: unknown): AuditEntry["detail"] | null {
  if (!isRecord(raw)) return null;
  for (const state of ["before", "after"]) {
    const value = raw[state];
    if (value !== undefined && value !== null && !isRecord(value)) return null;
  }
  const elided = raw["elided"];
  if (elided !== undefined) {
    if (!Array.isArray(elided) || elided.length > 2) return null;
    if (!elided.every((name) => member(ELIDED, name))) return null;
    if (new Set(elided).size !== elided.length) return null;
  }
  return raw as AuditEntry["detail"];
}

const ENTRY_TEXT = ["actor_username", "subject_label", "reason", "session_id", "ip"] as const;
const ENTRY_MORE_TEXT = ["user_agent", "request_id"] as const;

/** One served entry, its members checked, the contract's members only. */
function entryOf(raw: unknown): AuditEntry | null {
  if (!isRecord(raw)) return null;
  const { id, ts, actor_user_id, action, subject_type, subject_id } = raw;
  if (!isInt(id) || id < 1 || !isDate(ts) || !isText(action)) return null;
  if (!isTextOrNull(actor_user_id) || !isTextOrNull(subject_type) || !isTextOrNull(subject_id)) {
    return null;
  }
  if (!member(OUTCOMES, raw["outcome"]) || !member(SEVERITIES, raw["severity"])) return null;
  if (!isTextOrNull(raw["entry_hash"]) || !isTextOrNull(raw["prev_hash"])) return null;
  const detail = detailOf(raw["detail"]);
  if (detail === null) return null;
  const out: Json = {
    id,
    ts,
    actor_user_id,
    action,
    subject_type,
    subject_id,
    outcome: raw["outcome"],
    severity: raw["severity"],
    detail,
    entry_hash: raw["entry_hash"],
    prev_hash: raw["prev_hash"],
  };
  for (const name of [...ENTRY_TEXT, ...ENTRY_MORE_TEXT]) {
    if (!optional(raw, out, name, isTextOrNull)) return null;
  }
  const env = (value: unknown): boolean => value === null || member(ENVIRONMENTS, value);
  if (!optional(raw, out, "environment", env)) return null;
  return out as AuditEntry;
}

/** `queryAuditLog`'s `200`: every entry readable, else the whole page is unreadable. */
export function vetAuditPage(raw: unknown): AuditPageBody | null {
  if (!isRecord(raw) || !Array.isArray(raw["items"])) return null;
  if (typeof raw["chain_verified"] !== "boolean") return null;
  const meta = metaOf(raw["meta"]);
  if (meta === null) return null;
  const items: AuditEntry[] = [];
  for (const item of raw["items"]) {
    const entry = entryOf(item);
    if (entry === null) return null;
    items.push(entry);
  }
  return { items, chain_verified: raw["chain_verified"], meta };
}

/** `verifyAuditChain`'s `200`, every required member in its served shape. */
export function vetVerifyResult(raw: unknown): VerifyResult | null {
  if (!isRecord(raw) || typeof raw["verified"] !== "boolean") return null;
  const { entries_checked, first_bad_id, checked_at, from_id, to_id, anchor_hash, last_hash } = raw;
  if (!isCount(entries_checked) || !isIntOrNull(first_bad_id) || !isDate(checked_at)) return null;
  if (!isIntOrNull(from_id) || !isIntOrNull(to_id)) return null;
  if (!isText(anchor_hash) || !HEX64.test(anchor_hash)) return null;
  if (last_hash !== null && !(isText(last_hash) && HEX64.test(last_hash))) return null;
  return {
    verified: raw["verified"],
    entries_checked,
    first_bad_id,
    checked_at,
    from_id,
    to_id,
    anchor_hash,
    last_hash,
  };
}

/**
 * Seconds before a retry can pass: the `Retry-After` header (delta-seconds or an HTTP date), else
 * the problem's `retry_after_seconds`; undefined when neither is readable.
 */
export function retryAfterSeconds(
  header: string | null,
  problem: unknown,
  now: number,
): number | undefined {
  const value = header?.trim() ?? "";
  let seconds: number | undefined;
  if (/^\d+$/.test(value)) seconds = Number(value);
  else if (value !== "" && Number.isFinite(Date.parse(value))) {
    seconds = Math.max(0, Math.ceil((Date.parse(value) - now) / 1_000));
  } else if (isRecord(problem) && isCount(problem["retry_after_seconds"])) {
    seconds = problem["retry_after_seconds"];
  }
  return seconds === undefined ? undefined : Math.min(seconds, MAX_RETRY_AFTER_S);
}

/** What a `403` means on the audit routes (the plan's §3), by its code; null for another status. */
export type ForbiddenMeaning =
  /**
   * `forbidden`: the area is gone (SCR-154 N-2). A Manager's `q` or `ip` would meet it too (`22`
   * queryAuditLog Access), but this client never sends either for a Manager (BQ-3).
   */
  | "withdrawn"
  /** The export or its download: the shipped gate. */
  | "step_up"
  /** D09's `inflight.read_only`. */
  | "read_only"
  /** T4 `inflight.not_sent` with the view-as sentence. */
  | "view_as"
  | "other";

/** Whom a refused call was made for. */
export interface RefusalContext {
  /**
   * The session views as another user (#1134; false until the shell has a source). Its reads
   * answer as the target, so a `403 forbidden` is the target's refusal, never the area
   * withdrawn: the download answers so under view-as (BQ-9, `22` View-as, Scope).
   */
  readonly viewAs?: boolean | undefined;
}

export function forbiddenMeaning(
  answer: AuditRefusal,
  context: RefusalContext,
): ForbiddenMeaning | null {
  if (answer.status !== 403) return null;
  switch (answer.code) {
    case "forbidden":
      return context.viewAs === true ? "view_as" : "withdrawn";
    case "step_up_required":
      return "step_up";
    case "session_read_only":
      return "read_only";
    case "view_as_read_only":
    case "view_as_expired":
      return "view_as";
    default:
      return "other";
  }
}

/** `queryAuditLog`'s query: the contract's names in its order, `action` repeated, nothing empty. */
export function queryString(query: AuditQuery): string {
  const params = new URLSearchParams();
  const add = (name: string, value: string | number | undefined): void => {
    if (value !== undefined && value !== "") params.append(name, String(value));
  };
  add("cursor", query.cursor);
  add("limit", query.limit);
  add("actor_user_id", query.actor_user_id);
  for (const code of query.action ?? []) add("action", code);
  add("subject_type", query.subject_type);
  add("subject_id", query.subject_id);
  add("outcome", query.outcome);
  add("severity", query.severity);
  add("ip", query.ip);
  add("from", query.from);
  add("to", query.to);
  add("q", query.q);
  return params.toString();
}

/** A problem body, read once; null when the answer carried none. */
async function problemOf(res: Response): Promise<unknown> {
  try {
    return (await res.json()) as unknown;
  } catch {
    return null;
  }
}

function errorsOf(raw: unknown): readonly FieldError[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const short = (value: unknown): value is string => isText(value) && value.length <= 64;
  const errors = raw
    .filter(isRecord)
    .filter(
      (error) => short(error["rule"]) && (error["field"] === undefined || short(error["field"])),
    )
    .slice(0, MAX_ERRORS)
    .map((error) => ({ field: String(error["field"] ?? ""), rule: String(error["rule"]) }));
  return errors.length === 0 ? undefined : errors;
}

/** Any status but `2xx`, as a refusal. */
async function refusalOf(res: Response, now: number): Promise<AuditRefusal> {
  const problem = await problemOf(res);
  const fields = isRecord(problem) ? problem : {};
  const code = isText(fields["code"]) && CODE.test(fields["code"]) ? fields["code"] : null;
  const instance = fields["instance"];
  const detail = fields["detail"];
  const out: {
    -readonly [K in keyof AuditRefusal]: AuditRefusal[K];
  } = { kind: "refused", status: res.status, code };
  const retryAfterS = retryAfterSeconds(res.headers.get("Retry-After"), problem, now);
  if (retryAfterS !== undefined) out.retryAfterS = retryAfterS;
  if (isText(instance) && REF.test(instance)) out.refId = instance;
  const errors = errorsOf(fields["errors"]);
  if (errors !== undefined) out.errors = errors;
  if (isText(detail) && detail.length <= MAX_DETAIL) out.detail = detail;
  return out;
}

const UNREADABLE = { kind: "failed", reason: "unreadable" } as const;

/** A JSON answer: the vetted body, or the refusal. */
async function jsonAnswer<T>(
  res: Response,
  vet: (raw: unknown) => T | null,
  now: number,
  aborted: () => boolean,
): Promise<AuditAnswer<T>> {
  if (!res.ok) return refusalOf(res, now);
  let raw: unknown;
  try {
    raw = await res.json();
  } catch (error) {
    if (aborted()) throw error; // stopped mid-body: the caller says why
    return UNREADABLE;
  }
  const body = vet(raw);
  return body === null ? UNREADABLE : { kind: "ok", body };
}

interface Exchange<T> {
  readonly held: HeldRequest;
  readonly timeoutMs: number;
  /** A write's lost answer is `unknown`; a read's is `failed`. */
  readonly write: boolean;
  readonly read: (res: Response, now: number, aborted: () => boolean) => Promise<AuditAnswer<T>>;
}

/** Sends `held` once under its bound and the caller's signal, and reads the answer. */
async function exchange<T>(spec: Exchange<T>, options: CallOptions = {}): Promise<AuditAnswer<T>> {
  const timers = options.timers ?? BROWSER_TIMERS;
  const now = options.now ?? Date.now;
  const caller = options.signal;
  const controller = new AbortController();
  let timedOut = false;
  const stop = (): void => controller.abort();
  if (caller?.aborted) controller.abort();
  else caller?.addEventListener("abort", stop, { once: true });
  let timer: unknown = timers.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, spec.timeoutMs);
  const clear = (): void => {
    if (timer !== null) timers.clearTimeout(timer);
    timer = null;
  };
  try {
    const res = await sendHeld(spec.held, controller.signal);
    return await spec.read(res, now(), () => controller.signal.aborted);
  } catch {
    if (spec.write) return { kind: "unknown" };
    return { kind: "failed", reason: timedOut ? "timeout" : "network" };
  } finally {
    clear();
    caller?.removeEventListener("abort", stop);
  }
}

const ACCEPT_JSON: Readonly<Record<string, string>> = { Accept: "application/json" };

/** A plain `GET` of `url` (a read): JSON, under the read bound. */
function readJson<T>(
  url: string,
  vet: (raw: unknown) => T | null,
  options?: CallOptions,
  timeoutMs: number = AUDIT_READ_TIMEOUT_MS,
): Promise<AuditAnswer<T>> {
  const held = holdRequest("GET", url, ACCEPT_JSON, null);
  return exchange(
    {
      held,
      timeoutMs,
      write: false,
      read: (res, now, aborted) => jsonAnswer(res, vet, now, aborted),
    },
    options,
  );
}

/** `GET /admin/audit`: one keyset page of the filter set (D4), `admin.audit_read` on a new set. */
export function queryAuditLog(
  query: AuditQuery,
  options?: CallOptions,
): Promise<AuditAnswer<AuditPageBody>> {
  const search = queryString(query);
  const url = search === "" ? AUDIT_PATHS.query : `${AUDIT_PATHS.query}?${search}`;
  return readJson(url, vetAuditPage, options);
}

/**
 * `POST /admin/audit/verify` with no bounds (D11): the newest span, ending at the head, so a pass
 * whose `anchor_hash` is 64 zeros ran from genesis. A write: no answer is `unknown`.
 */
export function verifyAuditChain(options?: CallOptions): Promise<AuditAnswer<VerifyResult>> {
  const body: VerifyBody = {};
  const headers = { ...ACCEPT_JSON, "Content-Type": "application/json" };
  const held = holdRequest("POST", AUDIT_PATHS.verify, headers, JSON.stringify(body));
  return exchange(
    {
      held,
      timeoutMs: VERIFY_TIMEOUT_MS,
      write: true,
      read: (res, now, aborted) => jsonAnswer(res, vetVerifyResult, now, aborted),
    },
    options,
  );
}
