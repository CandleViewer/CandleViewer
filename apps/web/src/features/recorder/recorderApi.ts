/**
 * The recorder screen's REST client (E16-S01, SCR-140; `22` tag `recording`, the job poll and the
 * coverage read): `inviteApi.ts`'s `call` / `ApiResult` shape, copied rather than shared (BQ-4),
 * over the generated `packages/protocol` types only (C-4.16). Each write carries one
 * `Idempotency-Key`, held with the request, so the re-send after a `403 step_up_required` is the
 * same submission (C-2.10); the refused request comes back held for the step-up seam, and no
 * elevation is kept here. A refusal is routed as E16-D06 §16.4 says (`route`); a problem's
 * `message` and `detail` never leave this module, and its `code` only when it is one of `22`'s
 * tokens. A read gives up after `READ_TIMEOUT_MS`; a 2xx the client cannot read is a failure.
 */
import { ERROR_CODES, type ErrorCode, type generated } from "@candleviewer/protocol";
import {
  holdRequest,
  readChallenge,
  sendHeld,
  type HeldRequest,
  type StepUpChallenge,
} from "../stepUp/challenge";

type Ops = generated.rest.operations;
type Json<T> = T extends { content: { "application/json": infer B } } ? B : never;
type Query<Op extends keyof Ops> = NonNullable<Ops[Op]["parameters"]["query"]>;

export type RecordedSymbol = generated.rest.components["schemas"]["RecordedSymbol"];
export type RecordedSymbolPage = Json<Ops["listRecordedSymbols"]["responses"][200]>;
export type RecordingStatus = Json<Ops["getRecordingStatus"]["responses"][200]>;
export type StorageUsage = Json<Ops["getStorageUsage"]["responses"][200]>;
export type RecordingSessionPage = Json<Ops["listRecordingSessions"]["responses"][200]>;
export type DataCoverage = Json<Ops["getDataCoverage"]["responses"][200]>;
export type Job = Json<Ops["getJob"]["responses"][200]>;
/** `201` with the disk estimate, or `200` with the row already listed (it gains `manual`). */
export type AddedRecordedSymbol =
  | Json<Ops["addRecordedSymbol"]["responses"][201]>
  | Json<Ops["addRecordedSymbol"]["responses"][200]>;
export type JobAccepted = Json<Ops["purgeRecordedData"]["responses"][202]>;
export type AddRecordedSymbolBody = Json<Ops["addRecordedSymbol"]["requestBody"]>;
export type UpdateRecordedSymbolBody = Json<Ops["updateRecordedSymbol"]["requestBody"]>;
export type PinBody = Json<Ops["pinRecordedSymbol"]["requestBody"]>;
export type CompactBody = Json<NonNullable<Ops["compactRecorder"]["requestBody"]>>;
export type PurgeBody = Json<Ops["purgeRecordedData"]["requestBody"]>;
export type ListQuery = Query<"listRecordedSymbols">;
export type SessionsQuery = Query<"listRecordingSessions">;
export type CoverageQuery = Query<"getDataCoverage">;
/** A stop's query: `force` alone. `purge_data` is never sent: the purge route is the one delete. */
export type RemoveQuery = Pick<Query<"removeRecordedSymbol">, "force">;

/** The job a poll follows: its `unknown` line names it. */
export type JobAction = "compact" | "purge";

/** A read with no answer by then is given up, as one with no answer at all (a hung read holds nothing). */
export const READ_TIMEOUT_MS = 10_000;
/** `listAll`'s page: `22`'s largest `limit`. */
export const LIST_PAGE_SIZE = 500;
/** `listAll` reads at most this many pages; a list longer than that is a failure, never a cut one. */
export const MAX_LIST_PAGES = 10;

/** The deck sentences a refusal routes to (E16-D06 §16.4), keys of `E16-D06-copy.json`. */
export const REFUSAL_DECK_KEYS = [
  "storage.purge.refused.before",
  "storage.purge.refused.pinned",
  "storage.purge.refused.audit",
  "storage.job.refused.running",
  "storage.compact.unknown",
  "storage.purge.unknown",
] as const;
export type RefusalDeckKey = (typeof REFUSAL_DECK_KEYS)[number];

/** A `403 step_up_required` refusal: the challenge, and the refused request held unchanged. */
export interface StepUpHold {
  readonly challenge: StepUpChallenge;
  readonly held: HeldRequest;
}

/**
 * How the screen shows a refused call (E16-D06 §16.4): the step-up flow; a deck sentence with the
 * code token in parentheses; or the generic T4, the CMP-027 sentence with the code token (null when
 * the answer named none), inline under `field` when the server named one. Stable tokens only.
 */
export type RefusalRoute =
  | { readonly kind: "step_up"; readonly hold: StepUpHold }
  | {
      readonly kind: "deck";
      readonly key: RefusalDeckKey;
      readonly code: string;
      /** `storage.purge.refused.before` only: the server's clock, an RFC 3339 instant. */
      readonly serverTime: string | null;
    }
  | {
      readonly kind: "t4";
      readonly code: string | null;
      readonly field: string | null;
      readonly status: number;
    };

export interface ApiResult<T> {
  readonly ok: boolean;
  readonly status: number;
  readonly code: string | null;
  readonly data: T | null;
  /** Set when the call was refused with a step-up challenge (#2725). */
  readonly stepUp: StepUpHold | null;
  /** How the screen shows the refusal; null when the call succeeded. */
  readonly route: RefusalRoute | null;
}

/** §16.4 rows 9, 10 and 12: the codes a write answers with a deck sentence; any other is the T4. */
const DECK: Partial<Record<keyof Ops, Partial<Record<ErrorCode, RefusalDeckKey>>>> = {
  purgeRecordedData: {
    retention_pinned_refused: "storage.purge.refused.pinned",
    job_running: "storage.job.refused.running",
    audit_unavailable: "storage.purge.refused.audit",
  },
  compactRecorder: { job_running: "storage.job.refused.running" },
};
/** An instant with an offset: how `before_in_future`'s `message` gives the server's clock. */
const INSTANT = /\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)/;

const isRecord = (value: unknown): value is Readonly<Record<string, unknown>> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string | null => (typeof value === "string" ? value : null);
const STABLE: ReadonlySet<string> = new Set(ERROR_CODES);
/** A problem's `code` when it is one of `22`'s stable tokens; anything else (free text) is no code. */
const codeOf = (value: unknown): ErrorCode | null =>
  typeof value === "string" && STABLE.has(value) ? (value as ErrorCode) : null;

/** The server's clock out of the message, re-written: the message itself goes no further. */
function instantIn(message: unknown): string | null {
  const found = INSTANT.exec(text(message) ?? "");
  const ms = found === null ? Number.NaN : Date.parse(found[0]);
  return Number.isNaN(ms) ? null : new Date(ms).toISOString();
}

function routeOf(
  op: keyof Ops,
  status: number,
  body: unknown,
  stepUp: StepUpHold | null,
  job: JobAction | undefined,
): RefusalRoute {
  if (stepUp !== null) return { kind: "step_up", hold: stepUp };
  const problem = isRecord(body) ? body : {};
  const errors = problem["errors"];
  const first = Array.isArray(errors) && isRecord(errors[0]) ? errors[0] : {};
  const code = codeOf(problem["code"]);
  const deck = (key: RefusalDeckKey, serverTime: string | null = null): RefusalRoute | null =>
    code === null ? null : { kind: "deck", key, code, serverTime };
  let route: RefusalRoute | null = null;
  if (op === "purgeRecordedData" && first["rule"] === "before_in_future") {
    const serverTime = instantIn(first["message"]); // rows 2, 3: it names the server's time
    if (serverTime !== null) route = deck("storage.purge.refused.before", serverTime);
  } else if (op === "getJob" && status === 404 && job !== undefined) {
    route = deck(`storage.${job}.unknown`); // rows 17, 18: a lost job (rule `job_unknown`)
  } else if (code !== null) {
    const table: Partial<Record<ErrorCode, RefusalDeckKey>> = DECK[op] ?? {};
    const key = Object.hasOwn(table, code) ? table[code] : undefined;
    if (key !== undefined) route = deck(key);
  }
  return route ?? { kind: "t4", code, field: text(first["field"]), status };
}

/** No answer the client can use: the generic T4 with no code (`status` 0 when nothing answered). */
const unanswered = <T>(status: number): ApiResult<T> => ({
  ok: false,
  status,
  code: null,
  data: null,
  stepUp: null,
  route: { kind: "t4", code: null, field: null, status },
});

/** Reads the answer to `held` (its first send, or its re-send after a step-up) for `op`. */
export async function readResult<T>(
  op: keyof Ops,
  response: Response,
  held: HeldRequest,
  job?: JobAction,
): Promise<ApiResult<T>> {
  let json: unknown = null;
  let readable = true;
  try {
    json = await response.json();
  } catch {
    json = null; // no body, or a body that is not JSON
    readable = false;
  }
  // A 2xx the client cannot read is no success (a proxy's page, a cut body); `204` and `205` have none.
  if (response.ok && !readable && response.status !== 204 && response.status !== 205) {
    return unanswered(response.status);
  }
  // The `Date` header gives the server clock the challenge's expiry is on (test doubles have none).
  const date = response.headers?.get("Date") ?? null;
  const challenge = response.status === 403 ? readChallenge(json, date) : null;
  const stepUp = challenge === null ? null : { challenge, held };
  return {
    ok: response.ok,
    status: response.status,
    code: response.ok || !isRecord(json) ? null : codeOf(json["code"]),
    data: response.ok ? (json as T) : null,
    stepUp,
    route: response.ok ? null : routeOf(op, response.status, json, stepUp, job),
  };
}

const BASE = "/api/v1";
const SAFE_METHODS: ReadonlySet<string> = new Set(["GET", "HEAD", "OPTIONS"]);

async function call<T>(
  op: keyof Ops,
  method: string,
  path: string,
  body?: unknown,
  job?: JobAction,
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // One id per call, held with the request: a re-send after a step-up is one submission (C-2.10).
  if (!SAFE_METHODS.has(method)) headers["Idempotency-Key"] = crypto.randomUUID();
  const payload = body === undefined ? null : JSON.stringify(body);
  const held = holdRequest(method, `${BASE}${path}`, headers, payload);
  // A read is bounded; a write is not given up client-side, since the server may still apply it.
  const bound = SAFE_METHODS.has(method) ? AbortSignal.timeout(READ_TIMEOUT_MS) : undefined;
  let response: Response;
  try {
    response = await sendHeld(held, bound);
  } catch {
    return unanswered(0);
  }
  return readResult<T>(op, response, held, job);
}

type QueryValue = string | number | boolean | readonly string[] | undefined;
/** `?a=1&b=x&b=y` in the order given (an array exploded, `22` `explode: true`); "" when empty. */
function qs(query: Readonly<Record<string, QueryValue>>): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    for (const item of typeof value === "object" ? value : value === undefined ? [] : [value]) {
      params.append(name, String(item));
    }
  }
  const out = params.toString();
  return out === "" ? "" : `?${out}`;
}
const row = (id: string): string => `/recording/symbols/${encodeURIComponent(id)}`;

const list = (query: ListQuery = {}) =>
  call<RecordedSymbolPage>("listRecordedSymbols", "GET", `/recording/symbols${qs(query)}`);

/**
 * The whole list (C-5309-10): `LIST_PAGE_SIZE` a page, following `next_cursor` while `has_more`, at most
 * `MAX_LIST_PAGES`. A refused page is the answer; a page with no list, or more pages than the bound, a failure.
 */
async function listAll(
  query: Omit<ListQuery, "cursor" | "limit"> = {},
): Promise<ApiResult<RecordedSymbolPage>> {
  const items: RecordedSymbol[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_LIST_PAGES; page += 1) {
    const res = await list({
      ...query,
      limit: LIST_PAGE_SIZE,
      ...(cursor === undefined ? {} : { cursor }),
    });
    if (!res.ok) return res;
    if (res.data === null || !Array.isArray(res.data.items)) return unanswered(res.status);
    items.push(...res.data.items);
    if (res.data.meta?.has_more !== true) return { ...res, data: { ...res.data, items } };
    cursor = res.data.meta.next_cursor ?? undefined;
    if (cursor === undefined) return unanswered(res.status);
  }
  return unanswered(200);
}

export const recorderApi = {
  list,
  listAll,
  status: () => call<RecordingStatus>("getRecordingStatus", "GET", "/recording/status"),
  storage: () => call<StorageUsage>("getStorageUsage", "GET", "/recording/storage"),
  sessions: (query: SessionsQuery = {}) =>
    call<RecordingSessionPage>("listRecordingSessions", "GET", `/recording/sessions${qs(query)}`),
  coverage: (query: CoverageQuery) =>
    call<DataCoverage>("getDataCoverage", "GET", `/market/data-coverage${qs(query)}`),
  job: (jobId: string, action: JobAction) =>
    call<Job>("getJob", "GET", `/admin/jobs/${encodeURIComponent(jobId)}`, undefined, action),
  add: (body: AddRecordedSymbolBody) =>
    call<AddedRecordedSymbol>("addRecordedSymbol", "POST", "/recording/symbols", body),
  update: (id: string, body: UpdateRecordedSymbolBody) =>
    call<RecordedSymbol>("updateRecordedSymbol", "PATCH", row(id), body),
  remove: (id: string, { force }: RemoveQuery = {}) =>
    call<null>("removeRecordedSymbol", "DELETE", `${row(id)}${qs({ force })}`),
  pin: (id: string, body: PinBody) =>
    call<RecordedSymbol>("pinRecordedSymbol", "PUT", `${row(id)}/pin`, body),
  compact: (body?: CompactBody) =>
    call<JobAccepted>("compactRecorder", "POST", "/admin/recorder/compact", body),
  purge: (body: PurgeBody) =>
    call<JobAccepted>("purgeRecordedData", "POST", "/admin/recorder/purge", body),
};
