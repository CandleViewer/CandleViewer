/**
 * The admin area's reads (E42-S01; E42-D03 §6's data table, D8: one read per tile line). Each is one
 * `GET` the contract serves (`docs/plan/22-api-openapi.yaml`), bounded by its own 3 s client timeout
 * (BQ-5: the server already bounds every overview slice at 300 ms and answers a slow one as `error`),
 * and settles as one of four outcomes. Types are the generated contract's; every body is vetted
 * before a tile reads it, so an answer of another shape is a failure, never a guessed value.
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;
type Ok<K extends keyof Ops> = Ops[K] extends {
  responses: { 200: { content: { "application/json": infer B } } };
}
  ? B
  : never;

export type AdminOverview = Schemas["AdminOverview"];
export type AdminSliceStatus = Schemas["AdminSliceStatus"];
export type CapacityReport = Schemas["CapacityReport"];
export type HealthReport = Schemas["HealthReport"];
export type FeatureFlag = Schemas["FeatureFlag"];
export type AuditEntry = Schemas["AuditEntry"];
export type Backup = Schemas["Backup"];
export type FlagList = Ok<"listFeatureFlags">;
/** A list page as a tile reads it: the generated items, without the `meta` it does not read. */
export type AuditPage = Pick<Ok<"queryAuditLog">, "chain_verified"> & {
  readonly items: readonly AuditEntry[];
};
export interface BackupPage {
  readonly items: readonly Backup[];
}
/** `GET /users/invites`: its items are untyped (E42-D03 CG-14), so a tile reads their count only. */
export interface InviteCount {
  readonly count: number;
}

/** The client's bound on one read (BQ-5); the server's own slice budget is 300 ms. */
export const READ_TIMEOUT_MS = 3_000;

export type FailReason = "timeout" | "network" | "status" | "unreadable";

export type ReadOutcome<T> =
  | { readonly kind: "ok"; readonly body: T }
  /** `404` or `501`: the source is not built or not mounted yet; the line reads `tile.not_built`. */
  | { readonly kind: "not_built" }
  /** `403`: the session lost the area mid-visit (BQ-8); `refId` is the problem's `instance`. */
  | { readonly kind: "denied"; readonly refId: string | undefined }
  | { readonly kind: "failed"; readonly reason: FailReason; readonly status?: number | undefined };

type Json = Record<string, unknown>;

const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);

/** The longest string a tile shows; the contract caps a slice's `detail` at 200. */
const MAX_TEXT = 500;

/**
 * A record's own scalar fields only: finite numbers, booleans, `null` and short strings. Nested
 * objects and arrays are dropped, so nothing a tile does not read reaches it.
 */
function scalars(raw: Json): Json {
  const out: Json = {};
  for (const [name, value] of Object.entries(raw)) {
    if (
      value === null ||
      typeof value === "boolean" ||
      (typeof value === "number" && Number.isFinite(value)) ||
      (typeof value === "string" && value.length <= MAX_TEXT)
    ) {
      out[name] = value;
    }
  }
  return out;
}

/** A slice's status as a reader takes it: open-ended, so a value it does not know is not `ok`. */
function sliceOf(raw: unknown): Json | undefined {
  if (!isRecord(raw)) return undefined;
  const slice = scalars(raw);
  const status = slice["status"];
  slice["status"] = status === "ok" || status === "error" ? status : "unavailable";
  return slice;
}

const OVERVIEW_SLICES = ["users", "accounts", "recorder", "storage", "trading", "incidents"];

export function vetOverview(raw: unknown): AdminOverview | null {
  if (!isRecord(raw)) return null;
  const out: Json = {};
  if (typeof raw["generated_at"] === "string") out["generated_at"] = raw["generated_at"];
  for (const name of OVERVIEW_SLICES) {
    const slice = sliceOf(raw[name]);
    if (slice !== undefined) out[name] = slice;
  }
  return out as AdminOverview;
}

export function vetCapacity(raw: unknown): CapacityReport | null {
  if (!isRecord(raw)) return null;
  const subaccounts = sliceOf(raw["subaccounts"]);
  return (subaccounts === undefined ? {} : { subaccounts }) as CapacityReport;
}

const listOf = (raw: unknown): Json[] => (Array.isArray(raw) ? raw.filter(isRecord) : []);

export function vetHealth(raw: unknown): HealthReport | null {
  if (!isRecord(raw)) return null;
  const out = scalars(raw);
  out["components"] = listOf(raw["components"])
    .map(scalars)
    .filter((c) => typeof c["name"] === "string" && typeof c["state"] === "string");
  return out as HealthReport;
}

export function vetFlags(raw: unknown): FlagList | null {
  if (!isRecord(raw) || typeof raw["resolution"] !== "string") return null;
  const items = listOf(raw["items"])
    .map(scalars)
    .filter((f) => typeof f["key"] === "string");
  return { resolution: raw["resolution"], items } as FlagList;
}

/** The fields a compact row reads (CMP-173, D9): never a hash, an IP, a session or a user agent. */
const AUDIT_FIELDS = [
  "id",
  "ts",
  "action",
  "outcome",
  "severity",
  "reason",
  "actor_username",
  "subject_id",
  "subject_label",
  "subject_type",
];

/** An entry a compact row can show: the fields CMP-173 reads, the rest dropped. */
function auditEntryOf(raw: Json): AuditEntry | null {
  const fields = scalars(raw);
  const entry: Json = {};
  for (const name of AUDIT_FIELDS) if (name in fields) entry[name] = fields[name];
  const text = (name: string): boolean => typeof entry[name] === "string";
  if (!text("ts") || !text("action") || !text("outcome") || !text("severity")) return null;
  if (typeof entry["id"] !== "number") return null;
  const detail = isRecord(raw["detail"]) ? raw["detail"] : {};
  const after = isRecord(detail["after"]) ? { phase: detail["after"]["phase"] } : null;
  return {
    actor_user_id: null,
    entry_hash: null,
    prev_hash: null,
    subject_id: null,
    subject_type: null,
    ...entry,
    detail: { after },
  } as AuditEntry;
}

export function vetAudit(raw: unknown): AuditPage | null {
  if (!isRecord(raw)) return null;
  const items = listOf(raw["items"])
    .map(auditEntryOf)
    .filter((entry): entry is AuditEntry => entry !== null);
  return { chain_verified: raw["chain_verified"] === true, items } as AuditPage;
}

export function vetBackups(raw: unknown): BackupPage | null {
  if (!isRecord(raw)) return null;
  return { items: listOf(raw["items"]).map(scalars) } as BackupPage;
}

export function vetInvites(raw: unknown): InviteCount | null {
  return isRecord(raw) && Array.isArray(raw["items"]) ? { count: raw["items"].length } : null;
}

/** `Problem.instance`, the Ref CMP-089 shows (`urn:cv:req:{uuid}`), only in that shape. */
async function problemInstance(res: Response): Promise<string | undefined> {
  try {
    const body: unknown = await res.json();
    const instance = isRecord(body) ? body["instance"] : undefined;
    return typeof instance === "string" && /^[\w:.-]{1,128}$/.test(instance) ? instance : undefined;
  } catch {
    return undefined;
  }
}

export interface ReadTimers {
  readonly setTimeout: (run: () => void, ms: number) => unknown;
  readonly clearTimeout: (handle: unknown) => void;
}

/**
 * One read. `signal` lets the caller stop waiting (the area unmounted); the 3 s bound is the read's
 * own. Any `403` is the area denied: a `GET` never meets a step-up or a CSRF refusal.
 */
export async function readAdmin<T>(
  path: string,
  vet: (raw: unknown) => T | null,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<ReadOutcome<T>> {
  const controller = new AbortController();
  let timedOut = false;
  const stop = (): void => controller.abort();
  signal.addEventListener("abort", stop, { once: true });
  const timer = timers.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, READ_TIMEOUT_MS);
  try {
    const res = await apiFetch(path, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (res.status === 403) return { kind: "denied", refId: await problemInstance(res) };
    if (res.status === 404 || res.status === 501) return { kind: "not_built" };
    if (!res.ok) return { kind: "failed", reason: "status", status: res.status };
    let raw: unknown;
    try {
      raw = await res.json();
    } catch (error) {
      if (controller.signal.aborted) throw error; // stopped mid-body: the outer catch says why
      return { kind: "failed", reason: "unreadable" };
    }
    const body = vet(raw);
    return body === null ? { kind: "failed", reason: "unreadable" } : { kind: "ok", body };
  } catch {
    return { kind: "failed", reason: timedOut ? "timeout" : "network" };
  } finally {
    timers.clearTimeout(timer);
    signal.removeEventListener("abort", stop);
  }
}
