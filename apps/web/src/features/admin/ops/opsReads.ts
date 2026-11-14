/**
 * The ops screens' reads (E42-S06; E42-D05 §5–§7; the build plan's §1.1, §2), one problem-aware
 * reader shaped as #1135's audit reads; this part carries SCR-143's three. Types are the generated
 * contract's (C-4.16); every body is vetted first: an unknown enum or an ill-shaped member makes the
 * answer unreadable, never a guess, and members the contract does not name are dropped. An answer is
 * `ok` (the body and the client's clock), `refused` (any other status but `501`: the registered
 * `code` and the Ref; a `403` is `denied`, the area withdrawn, BQ-10), `not_built` (`501` only: a
 * `404` is never "not built" here, so S01's reader is not reused) or `failed` (`timeout`,
 * `network` or `unreadable`). The problem's `detail` is never kept (BQ-14).
 */
import { ERROR_CODES, type ErrorCode, type generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import { READ_TIMEOUT_MS, vetHealth, type ReadTimers } from "../overview/adminReads";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;
type Json = Record<string, unknown>;

export type HealthReport = Schemas["HealthReport"];
export type ComponentState = Schemas["ComponentState"];
export type Incident = Schemas["Incident"];
export type PageMeta = Schemas["PageMeta"];
export type IncidentStatus = Incident["status"];
type IncidentsOk = Ops["listIncidents"]["responses"][200]["content"]["application/json"];
/** A `listIncidents` page as the client keeps it: its meta and its vetted incidents. */
export type IncidentPageBody = Pick<IncidentsOk, "meta"> & { readonly items: readonly Incident[] };
type StatechartsOk = Ops["listStatecharts"]["responses"][200]["content"]["application/json"];
/** What D9's gate reads of `listStatecharts`: each kind's latch count and the snapshots' status. */
export interface ProtectionBody {
  readonly kinds: readonly Pick<
    StatechartsOk["kinds"][number],
    "machine_kind" | "degraded_machines"
  >[];
  readonly snapshots: Pick<StatechartsOk["snapshots"], "status">;
}

export type OpsFailReason = "timeout" | "network" | "unreadable";

export interface OpsRefusal {
  readonly kind: "refused";
  readonly status: number;
  /** The problem's `code` when `ERROR_CODES` registers it, else null. */
  readonly code: ErrorCode | null;
  /** `Problem.instance`, the Ref, only in its `urn:cv:req:…` shape. */
  readonly refId?: string | undefined;
  /** A `403`: the session lost the area (BQ-10); the store that met it calls the area's `deny`. */
  readonly denied: boolean;
}

export type OpsAnswer<T> =
  | { readonly kind: "ok"; readonly body: T; readonly at: number }
  | OpsRefusal
  | { readonly kind: "not_built" }
  | { readonly kind: "failed"; readonly reason: OpsFailReason };

/** `getHealth`'s bound: S01's 3 s. */
export const HEALTH_TIMEOUT_MS = READ_TIMEOUT_MS;
/** PROPOSED (#1135's `AUDIT_READ_TIMEOUT_MS`): a list's bound, above the server's 4 s query stop. */
export const LIST_TIMEOUT_MS = 6_000;
/** Page 1 of a status, newest first: D9's legs and the detail view read no further. */
export const INCIDENT_LIMIT = 100;
/** Bounds on what a body may hold: a report's components, and a text F34's 500 does not cover. */
const MAX_COMPONENTS = 64;
const MAX_TEXT = 500;

/** The contract's paths (`22`, servers `/api/v1`): nothing in them comes from data. */
export const OPS_PATHS = {
  health: "/api/v1/admin/health", // getHealth
  incidents: (status: IncidentStatus): string =>
    `/api/v1/admin/incidents?status=${status}&limit=${INCIDENT_LIMIT}`, // listIncidents
  protection: "/api/v1/admin/statecharts?kind=position_protection", // listStatecharts
} as const;

const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);
const isText = (raw: unknown): raw is string => typeof raw === "string";
const isShort = (raw: unknown): raw is string => isText(raw) && raw.length <= MAX_TEXT;
const isInt = (raw: unknown): raw is number => typeof raw === "number" && Number.isSafeInteger(raw);
const isCount = (raw: unknown): raw is number => isInt(raw) && raw >= 0;
const isDate = (raw: unknown): raw is string => isText(raw) && Number.isFinite(Date.parse(raw));
const isDateOrNull = (raw: unknown): raw is string | null => raw === null || isDate(raw);
const isIntOrNull = (raw: unknown): raw is number | null => raw === null || isInt(raw);

/** A list holding every member of the generated union `T`: a member the contract adds fails tsc. */
const every =
  <T extends string>() =>
  <const L extends readonly T[]>(list: L & ([T] extends [L[number]] ? unknown : never)): L =>
    list;
const member = <T extends string>(list: readonly T[], raw: unknown): raw is T =>
  typeof raw === "string" && (list as readonly string[]).includes(raw);

const STATES = every<ComponentState>()(["healthy", "degraded", "warning", "down", "not_deployed"]);
const SEVERITIES = every<Incident["severity"]>()(["debug", "info", "warning", "error", "critical"]);
const INCIDENT_STATUSES = every<IncidentStatus>()(["open", "acknowledged", "resolved"]);
type SliceStatus = NonNullable<StatechartsOk["snapshots"]["status"]>;
const SLICE_STATUSES = every<SliceStatus>()(["ok", "error", "unavailable"]);

/** The members SCR-143 reads; `alerts_active` is never shown (E42-D05 §5.1). */
const REPORT_MEMBERS =
  "overall version git_sha environment uptime_seconds server_time clock_offset_ms".split(" ");
const COMPONENT_MEMBERS = "name state latency_ms latency_unit detail last_good_at".split(" ");

const pick = (raw: Json, names: readonly string[]): Json =>
  Object.fromEntries(names.filter((name) => name in raw).map((name) => [name, raw[name]]));

/**
 * `getHealth`'s `200` through S01's `vetHealth` (own scalars of at most 500 characters, F34), then
 * its enums: a state the contract does not name, or more than 64 components, makes the report
 * unreadable. `vetHealth` drops a component without a string state; here a named one stays, its
 * `state` left out, so its record reads `not_received` and its tile stays (A-1084P1-d01): never a
 * component that vanishes. A nameless one has no tile and goes. Members the screen does not read
 * are dropped.
 */
export function vetHealthReport(raw: unknown): HealthReport | null {
  const list = isRecord(raw) ? raw["components"] : undefined;
  if (Array.isArray(list) && list.length > MAX_COMPONENTS) return null;
  const report: Json | null = vetHealth(raw);
  if (report === null || !("overall" in report ? member(STATES, report["overall"]) : true)) {
    return null;
  }
  const components: Json[] = [];
  for (const item of Array.isArray(list) ? list.filter(isRecord) : []) {
    // `vetHealth`'s own scalars and name check, with the state judged here: it drops a component
    // without a string state, and a dropped component would vanish from the page.
    const [vetted] = vetHealth({ components: [{ ...item, state: "" }] })?.components ?? [];
    if (vetted === undefined) continue; // no name: no tile to keep
    const state = item["state"];
    if (typeof state === "string" && !member(STATES, state)) return null;
    const kept = pick(
      vetted,
      COMPONENT_MEMBERS.filter((name) => name !== "state"),
    );
    components.push(member(STATES, state) ? { ...kept, state } : kept);
  }
  // The vetted members, each checked above or a scalar `vetHealth` kept: the generated shape.
  return { ...pick(report, REPORT_MEMBERS), components } as HealthReport;
}

/** Copies an optional member `ok` accepts; false for one present and refused. */
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
  if ((next !== null && !isShort(next)) || (raw["has_more"] && next === null)) return null;
  const meta: Json = { next_cursor: next, has_more: raw["has_more"], count: raw["count"] };
  if (!optional(raw, meta, "total", isIntOrNull)) return null;
  return meta as PageMeta; // every member checked above
}

/** One `Incident`, its required members checked and its texts within the contract's lengths. */
function incidentOf(raw: unknown): Incident | null {
  if (!isRecord(raw)) return null;
  const { id, component, first_seen_at, last_seen_at } = raw;
  if (!isShort(id) || !isShort(component) || !isDate(first_seen_at) || !isDate(last_seen_at)) {
    return null;
  }
  if (!member(SEVERITIES, raw["severity"]) || !member(INCIDENT_STATUSES, raw["status"])) {
    return null;
  }
  const out: Json = {
    id,
    component,
    severity: raw["severity"],
    status: raw["status"],
    first_seen_at,
    last_seen_at,
  };
  const within = (max: number) => (value: unknown) => isText(value) && value.length <= max;
  const orNull = (ok: (value: unknown) => boolean) => (value: unknown) =>
    value === null || ok(value);
  const checks: readonly (readonly [string, (value: unknown) => boolean])[] = [
    ["title", within(200)],
    ["detail", orNull(within(2_000))],
    ["occurrences", (value) => isInt(value) && value >= 1],
    ["acknowledged_by", orNull(isShort)],
    ["acknowledged_at", isDateOrNull],
    ["resolved_at", isDateOrNull],
    ["runbook_ref", orNull(isShort)],
    ["signature", isShort],
  ];
  for (const [name, ok] of checks) if (!optional(raw, out, name, ok)) return null;
  return out as Incident; // every member checked above
}

/**
 * `listIncidents`'s `200`: every incident readable and no more than asked, else unreadable. A copy of #1135's
 * `vetIncidentPage` (`audit/auditReads.ts`, not on `main` yet) with its pins as the parity test;
 * the import replaces it once that PR merges [BQ-12].
 */
export function vetIncidentPage(raw: unknown): IncidentPageBody | null {
  if (!isRecord(raw) || !Array.isArray(raw["items"])) return null;
  if (raw["items"].length > INCIDENT_LIMIT) return null;
  const meta = metaOf(raw["meta"]);
  if (meta === null) return null;
  const items: Incident[] = [];
  for (const item of raw["items"]) {
    const incident = incidentOf(item);
    if (incident === null) return null;
    items.push(incident);
  }
  return { items, meta };
}

/**
 * `listStatecharts`' `200` as D9 reads it: each kind's `machine_kind` and `degraded_machines`, and
 * the `snapshots` slice's status (more than 64 kinds, or a kind over 500 characters, is unreadable).
 * That status is open-ended for readers (C-6.3), so a value the client does not know reads
 * `unavailable`, never `ok`. The rows and every other member are dropped.
 */
export function vetProtection(raw: unknown): ProtectionBody | null {
  if (!isRecord(raw)) return null;
  const { kinds: list, snapshots } = raw;
  if (!Array.isArray(list) || list.length > MAX_COMPONENTS || !isRecord(snapshots)) return null;
  const kinds: ProtectionBody["kinds"][number][] = [];
  for (const kind of list) {
    if (!isRecord(kind)) return null;
    const { machine_kind, degraded_machines } = kind;
    if (!isShort(machine_kind) || !isCount(degraded_machines)) return null;
    kinds.push({ machine_kind, degraded_machines });
  }
  const { status } = snapshots;
  return { kinds, snapshots: { status: member(SLICE_STATUSES, status) ? status : "unavailable" } };
}

const REF = /^urn:cv:req:[\w.-]{1,116}$/;
const UNREADABLE = { kind: "failed", reason: "unreadable" } as const;
const NOT_BUILT = { kind: "not_built" } as const;

/** Any status but `2xx` and `501`: the problem's registered code and its Ref, never its words. */
async function refusalOf(res: Response): Promise<OpsRefusal> {
  let problem: unknown = null;
  try {
    problem = await res.json();
  } catch {
    problem = null;
  }
  const fields = isRecord(problem) ? problem : {};
  const { code, instance } = fields;
  return {
    kind: "refused",
    status: res.status,
    code: member(ERROR_CODES, code) ? code : null,
    ...(isText(instance) && REF.test(instance) ? { refId: instance } : {}),
    denied: res.status === 403,
  };
}

export interface ReadOptions {
  /** The caller stops waiting (the page unmounted): the answer is `failed`, `network`. */
  readonly signal: AbortSignal;
  readonly timers: ReadTimers;
  /** The client's clock, stamped on a good answer. */
  readonly now: () => number;
}

/** One `GET` of `path` under `timeoutMs` and the caller's signal. */
export async function readOps<T>(
  path: string,
  vet: (raw: unknown) => T | null,
  timeoutMs: number,
  { signal, timers, now }: ReadOptions,
): Promise<OpsAnswer<T>> {
  const controller = new AbortController();
  let timedOut = false;
  const stop = (): void => controller.abort();
  if (signal.aborted) controller.abort();
  else signal.addEventListener("abort", stop, { once: true });
  const timer = timers.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const res = await apiFetch(path, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (res.status === 501) return NOT_BUILT;
    if (!res.ok) return await refusalOf(res);
    let raw: unknown;
    try {
      raw = await res.json();
    } catch (error) {
      if (controller.signal.aborted) throw error; // stopped mid-body: the outer catch says why
      return UNREADABLE;
    }
    const body = vet(raw);
    return body === null ? UNREADABLE : { kind: "ok", body, at: now() };
  } catch {
    return { kind: "failed", reason: timedOut ? "timeout" : "network" };
  } finally {
    timers.clearTimeout(timer);
    signal.removeEventListener("abort", stop);
  }
}
