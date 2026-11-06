/**
 * The statechart inspector's reads (E42-S08 §3.1): E42-T07's `listStatecharts`, `getStatechart` and
 * `exportStatechart`, all `admin:read` and no step-up (`22`). The idiom is the overview's
 * (`overview/adminReads.ts`): `apiFetch` only, a 3 s client bound, the caller's `AbortSignal`, a
 * discriminated outcome, and every body vetted to the generated types before anything shows it, so
 * an unknown enum value, a missing field or a value off its pattern is a failed read, never a
 * guessed value. `readAdmin` itself is not reused: `getStatechart` answers an unknown or hidden
 * machine `404`, which is no "not built", and a list `400` names its problem `code`
 * (`invalid_cursor`). Paths are built from vetted values only, every segment and parameter encoded.
 */
import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../../../lib/http/csrfFetch";
import { READ_TIMEOUT_MS, type FailReason, type ReadTimers } from "../overview/adminReads";
import { vetStately, type ChartModel } from "./chartModel";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;
type Ok<K extends keyof Ops> = Ops[K] extends {
  responses: { 200: { content: { "application/json": infer B } } };
}
  ? B
  : never;

export type Environment = Schemas["Environment"];
export type AdminSliceStatus = Schemas["AdminSliceStatus"];
export type StatechartMachine = Schemas["StatechartMachine"];
export type StatechartKindSummary = Schemas["StatechartKindSummary"];
export type StatechartExport = Schemas["StatechartExport"];
type ListBody = Ok<"listStatecharts">;

/** A list page as the inspector reads it: the generated page, its rows and counters vetted. */
export type MachineList = Pick<ListBody, "snapshots" | "metrics" | "meta"> & {
  readonly items: readonly StatechartMachine[];
  readonly kinds: readonly StatechartKindSummary[];
};
/** `getStatechart`'s answer without `config` and `context_summary`: neither is shown (BQ-4), so
 * neither is kept. */
export type MachineDetail = Omit<Ok<"getStatechart">, "config" | "context_summary">;
export type RecentEvent = NonNullable<MachineDetail["recent_events"]>[number];
/** `exportStatechart`'s kind and hash, its `stately` chart read into the model (§4.1). */
export type ChartExport = Pick<StatechartExport, "machine_kind" | "machine_hash"> & {
  readonly model: ChartModel;
};

/** A machine as the inspector asks for it: a key and an environment, both vetted (`machineRef`). */
export interface MachineRef {
  readonly key: string;
  readonly env: Environment;
}

/** One page's rows: CMP-049's v0 bound, drawn whole (plan §10). */
export const LIST_LIMIT = 200;

/** `snapshots.detail`'s fixed reason when a snapshot's seal does not verify (`22`, CV-C53); read by
 * the machine view and the list page (`MachineView`, `InspectorPage`, later parts of #1137). */
export const SEAL_FAILED = "snapshot seal did not verify";

/**
 * The contract's `MachineKey` (`22`): a singleton's kind, or `{kind}:{uuid|symbol}`. Patterns hold
 * only where a value builds a path (a key, a kind); a name that is only shown (a state, a
 * `by_state` key, a configuration id) is any non-empty string up to 200 characters: React escapes
 * it, and `22` and the chart schema constrain it no further.
 */
const MACHINE_KEY =
  /^[a-z_]{1,32}(:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Z0-9]{2,20}USDT))?$/;
const MAX_MACHINE_KEY = 80;
/** A catalogue `machine_kind` (`listStatecharts`' `kind` parameter). */
const KIND = /^[a-z_]{1,32}$/;
const HASH = /^[0-9a-f]{64}$/;
const ENVIRONMENTS: readonly Environment[] = ["live", "demo", "testnet"];
const PHASES: readonly RecentEvent["phase"][] = ["ahead", "commit", "fault"];
/** The cursor's bound (the server's `max_length`). */
const MAX_CURSOR = 512;
/** A shown name's or text's bound: a state, a state id, a slice detail, an event type. */
const MAX_TEXT = 200;
/** The most state ids a configuration or an event lists, and the most rows a detail shows. */
const MAX_IDS = 200;
const MAX_EVENTS = 50;
/** The most bytes a body may declare or stream before it is parsed: the largest chart the model
 * admits (`MAX_STATES`, `MAX_ARMS`) scales B01's 30 KB to about 260 KB and a 200-row page is under
 * 200 KB, so 1 MiB holds any real answer and refuses a runaway one inside the 3 s window. */
export const MAX_BODY_BYTES = 1_048_576;
/** `22`'s `date-time` as the server writes it (RFC 3339, `Z` or an offset), checked before parsing. */
const ISO_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/;

export type InspectorOutcome<T> =
  | { readonly kind: "ok"; readonly body: T }
  /** `404` on a machine or a chart: unknown, not visible to the caller, or not registered. */
  | { readonly kind: "not_found" }
  /** `501`, or a `404` on the list: the source is not served here. */
  | { readonly kind: "not_built" }
  /** `403`: the session lost the area (BQ-8); `refId` is the problem's `instance`. */
  | { readonly kind: "denied"; readonly refId: string | undefined }
  /**
   * `400 invalid_cursor`: the cursor expired or was issued for another listing. BQ-9 groundwork:
   * only a cursor sends one, and only tests send a cursor until #1135's pager does.
   */
  | { readonly kind: "invalid_cursor" }
  | { readonly kind: "failed"; readonly reason: FailReason; readonly status?: number | undefined };

type Json = Record<string, unknown>;

const isRecord = (raw: unknown): raw is Json =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);
const isCount = (raw: unknown): raw is number =>
  typeof raw === "number" && Number.isSafeInteger(raw) && raw >= 0;
const isEnvironment = (raw: unknown): raw is Environment => ENVIRONMENTS.some((env) => env === raw);
const isTime = (raw: unknown): raw is string =>
  typeof raw === "string" && ISO_TIME.test(raw) && Number.isFinite(Date.parse(raw));
const isText = (raw: unknown, max: number): raw is string =>
  typeof raw === "string" && raw.length > 0 && raw.length <= max;

/** `machineKey` and `environment` as a machine's address, or `null` off their pattern or enum. */
export function machineRef(key: unknown, env: unknown): MachineRef | null {
  if (typeof key !== "string" || key.length > MAX_MACHINE_KEY || !MACHINE_KEY.test(key)) {
    return null;
  }
  return isEnvironment(env) ? { key, env } : null;
}

export interface ListRequest {
  /** "Latched only": `degraded=true`. */
  readonly latchedOnly: boolean;
  /**
   * A page after the first: the previous page's `meta.next_cursor`. BQ-9 groundwork, kept for the
   * cursor pager (#1135's CMP-053 cursor mode): the page sends none yet, `has_more` shows
   * `machine.more` instead, and only tests send one.
   */
  readonly cursor?: string | undefined;
}

/** `listStatecharts`: `?limit=200[&degraded=true][&cursor=…]`, in that order. */
export function listPath({ latchedOnly, cursor }: ListRequest): string {
  const degraded = latchedOnly ? "&degraded=true" : "";
  const after = cursor === undefined ? "" : `&cursor=${encodeURIComponent(cursor)}`;
  return `/api/v1/admin/statecharts?limit=${LIST_LIMIT}${degraded}${after}`;
}

/** `getStatechart` for a vetted machine; `null` for an address off its pattern. */
export function detailPath(ref: MachineRef): string | null {
  if (machineRef(ref.key, ref.env) === null) return null;
  const key = encodeURIComponent(ref.key);
  return `/api/v1/admin/statecharts/${key}?environment=${encodeURIComponent(ref.env)}`;
}

/**
 * `exportStatechart` by the bare kind, never by a machine key: an `algo:{id}` key is `404` (`22`),
 * so the four algo charts are asked for by `oco`, `iceberg`, `twap` or `chase`.
 */
export function exportPath(kind: string): string | null {
  return KIND.test(kind) ? `/api/v1/admin/statecharts/${encodeURIComponent(kind)}/export` : null;
}

/** A list of `vet`'s items, at most `max`; `null` when any one is refused. */
function listOf<T>(raw: unknown, vet: (item: unknown) => T | null, max: number): T[] | null {
  if (!Array.isArray(raw) || raw.length > max) return null;
  const out: T[] = [];
  for (const item of raw) {
    const vetted = vet(item);
    if (vetted === null) return null;
    out.push(vetted);
  }
  return out;
}

const idsOf = (raw: unknown): string[] | null =>
  listOf(raw, (id) => (isText(id, MAX_TEXT) ? id : null), MAX_IDS);

/**
 * A slice's outcome, open-ended for readers (C-6.3): a status it does not know reads as
 * `unavailable`, never `ok`. A detail over the contract's 200 characters, or a `generated_at` off
 * its pattern, is dropped, not refused: both are optional here, and neither decides what is shown.
 */
function sliceOf(raw: unknown): AdminSliceStatus | null {
  if (!isRecord(raw)) return null;
  const status = raw["status"];
  const slice: AdminSliceStatus = {
    status: status === "ok" || status === "error" ? status : "unavailable",
  };
  if (isText(raw["detail"], MAX_TEXT)) slice.detail = raw["detail"];
  if (isTime(raw["generated_at"])) slice.generated_at = raw["generated_at"];
  return slice;
}

function machineOf(raw: unknown): StatechartMachine | null {
  if (!isRecord(raw)) return null;
  const key = raw["machine_key"];
  const kind = raw["machine_kind"];
  const environment = raw["environment"];
  const state = raw["state"];
  const hash = raw["machine_hash"];
  const lockMatches = raw["lock_matches"];
  const degraded = raw["degraded"];
  const trips = raw["chain_trips"];
  const deferred = raw["deferred_depth"];
  const updated = raw["updated_at"];
  if (typeof key !== "string" || machineRef(key, environment) === null) return null;
  if (typeof kind !== "string" || !KIND.test(kind) || !isEnvironment(environment)) return null;
  if (!isText(state, MAX_TEXT)) return null;
  if (typeof hash !== "string" || !HASH.test(hash)) return null;
  if (typeof lockMatches !== "boolean" || typeof degraded !== "boolean") return null;
  if (!isCount(trips) || (deferred !== null && !isCount(deferred)) || !isTime(updated)) return null;
  return {
    machine_key: key,
    machine_kind: kind,
    environment,
    state,
    machine_hash: hash,
    lock_matches: lockMatches,
    chain_trips: trips,
    degraded,
    deferred_depth: deferred,
    updated_at: updated,
  };
}

/** `by_state`: a count per published (and only shown) state name, at most one per chart state. */
function byStateOf(raw: unknown): Record<string, number> | null {
  if (!isRecord(raw)) return null;
  const entries = Object.entries(raw);
  if (entries.length > MAX_IDS) return null;
  const counts: [string, number][] = [];
  for (const [state, n] of entries) {
    if (!isText(state, MAX_TEXT) || !isCount(n)) return null;
    counts.push([state, n]);
  }
  return Object.fromEntries(counts);
}

function summaryOf(raw: unknown): StatechartKindSummary | null {
  if (!isRecord(raw)) return null;
  const kind = raw["machine_kind"];
  const environment = raw["environment"];
  const machines = raw["machines"];
  const byState = byStateOf(raw["by_state"]);
  const trips = raw["chain_trips"];
  const latched = raw["degraded_machines"];
  const dropped = raw["dropped_receipts"];
  if (typeof kind !== "string" || !KIND.test(kind) || !isEnvironment(environment)) return null;
  if (!isCount(machines) || machines < 1 || byState === null) return null;
  if (!isCount(trips) || !isCount(latched) || (dropped !== null && !isCount(dropped))) return null;
  return {
    machine_kind: kind,
    environment,
    machines,
    by_state: byState,
    chain_trips: trips,
    degraded_machines: latched,
    dropped_receipts: dropped,
  };
}

function metaOf(raw: unknown): MachineList["meta"] | null {
  if (!isRecord(raw)) return null;
  const hasMore = raw["has_more"];
  const count = raw["count"];
  const next = raw["next_cursor"];
  if (typeof hasMore !== "boolean" || !isCount(count)) return null;
  if (next !== undefined && next !== null && !isText(next, MAX_CURSOR)) return null;
  return { has_more: hasMore, count, next_cursor: typeof next === "string" ? next : null };
}

/** `listStatecharts`' page: every row and counter vetted, or the read is unreadable. */
export function vetList(raw: unknown): MachineList | null {
  if (!isRecord(raw)) return null;
  const items = listOf(raw["items"], machineOf, LIST_LIMIT);
  const kinds = listOf(raw["kinds"], summaryOf, LIST_LIMIT);
  const snapshots = sliceOf(raw["snapshots"]);
  const metrics = sliceOf(raw["metrics"]);
  const meta = metaOf(raw["meta"]);
  if (items === null || kinds === null || snapshots === null || metrics === null) return null;
  return meta === null ? null : { items, kinds, snapshots, metrics, meta };
}

function eventOf(raw: unknown): RecentEvent | null {
  if (!isRecord(raw)) return null;
  const type = raw["event_type"];
  const phase = PHASES.find((known) => known === raw["phase"]);
  const at = raw["occurred_at"];
  if (!isText(type, MAX_TEXT) || phase === undefined || !isTime(at)) return null;
  const event: RecentEvent = { event_type: type, phase, occurred_at: at };
  for (const side of ["from_states", "to_states"] as const) {
    if (raw[side] === undefined) continue;
    const ids = idsOf(raw[side]);
    if (ids === null) return null;
    event[side] = ids;
  }
  const faulted = raw["faulted"];
  if (faulted !== undefined && typeof faulted !== "boolean") return null;
  if (faulted !== undefined) event.faulted = faulted;
  return event;
}

/**
 * `getStatechart`'s answer: the slices, the machine as a list row, the configuration and at most
 * 50 events, each vetted; `config` and `context_summary` are dropped, never kept.
 */
export function vetDetail(raw: unknown): MachineDetail | null {
  if (!isRecord(raw)) return null;
  const snapshots = sliceOf(raw["snapshots"]);
  if (snapshots === null) return null;
  const detail: MachineDetail = { snapshots };
  if (raw["events"] !== undefined) {
    const events = sliceOf(raw["events"]);
    if (events === null) return null;
    detail.events = events;
  }
  if (raw["machine"] !== undefined) {
    const machine = machineOf(raw["machine"]);
    if (machine === null) return null;
    detail.machine = machine;
  }
  if (raw["configuration"] !== undefined) {
    const configuration = idsOf(raw["configuration"]);
    if (configuration === null) return null;
    detail.configuration = configuration;
  }
  if (raw["recent_events"] !== undefined) {
    const events = listOf(raw["recent_events"], eventOf, MAX_EVENTS);
    if (events === null) return null;
    detail.recent_events = events;
  }
  return detail;
}

/** `exportStatechart`'s answer for `kind`: the same kind, a hash, and a chart the model reads. */
export function vetExport(raw: unknown, kind: string): ChartExport | null {
  if (!isRecord(raw)) return null;
  const hash = raw["machine_hash"];
  if (raw["machine_kind"] !== kind || typeof hash !== "string" || !HASH.test(hash)) return null;
  const model = vetStately(raw["stately"], kind, hash);
  return model === null ? null : { machine_kind: kind, machine_hash: hash, model };
}

/** A problem's `code` and `instance` (CMP-089's Ref, `urn:cv:req:{uuid}`), each only in shape. */
async function problemOf(res: Response): Promise<{ code?: string; instance?: string }> {
  try {
    const text = await textOf(res); // the same cap as a 200: no unbounded parse on a refusal
    if (text === null) return {};
    const body: unknown = JSON.parse(text);
    if (!isRecord(body)) return {};
    const code = body["code"];
    const instance = body["instance"];
    return {
      ...(typeof code === "string" && /^[a-z_]{1,64}$/.test(code) ? { code } : {}),
      ...(typeof instance === "string" && /^[\w:.-]{1,128}$/.test(instance) ? { instance } : {}),
    };
  } catch {
    return {};
  }
}

/** The body as text, or `null` once it declares or streams more than `MAX_BODY_BYTES`. */
async function textOf(res: Response): Promise<string | null> {
  const body = res.body;
  if (Number(res.headers.get("Content-Length")) > MAX_BODY_BYTES) {
    await body?.cancel();
    return null;
  }
  if (body === null) return "";
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  let size = 0;
  for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
    size += chunk.value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    text += decoder.decode(chunk.value, { stream: true });
  }
  return text + decoder.decode();
}

/**
 * One read. `signal` lets the caller stop waiting (another filter or machine, or the visit ended);
 * the 3 s bound is the read's own. `404` is `missing`'s outcome: a machine or chart that is not
 * found, or a list that is not served. Any `403` is the area denied: a `GET` meets no step-up.
 */
export async function readInspector<T>(
  path: string,
  vet: (raw: unknown) => T | null,
  signal: AbortSignal,
  timers: ReadTimers,
  missing: "not_found" | "not_built",
): Promise<InspectorOutcome<T>> {
  const controller = new AbortController();
  let timedOut = false;
  const stop = (): void => controller.abort();
  signal.addEventListener("abort", stop, { once: true });
  if (signal.aborted) controller.abort();
  const timer = timers.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, READ_TIMEOUT_MS);
  try {
    const res = await apiFetch(path, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (res.status === 403) return { kind: "denied", refId: (await problemOf(res)).instance };
    if (res.status === 404) return { kind: missing };
    if (res.status === 501) return { kind: "not_built" };
    if (res.status === 400 && (await problemOf(res)).code === "invalid_cursor") {
      return { kind: "invalid_cursor" };
    }
    if (!res.ok) return { kind: "failed", reason: "status", status: res.status };
    let raw: unknown;
    try {
      const text = await textOf(res);
      if (text === null) return { kind: "failed", reason: "unreadable" };
      raw = JSON.parse(text);
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

/** A list page; a `404` there means the list is not served (plan §5.1 "not built"). */
export function readList(
  request: ListRequest,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<InspectorOutcome<MachineList>> {
  return readInspector(listPath(request), vetList, signal, timers, "not_built");
}

/** One machine; an address off its pattern is never asked for and reads as not found. */
export function readDetail(
  ref: MachineRef,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<InspectorOutcome<MachineDetail>> {
  const path = detailPath(ref);
  if (path === null) return Promise.resolve({ kind: "not_found" });
  return readInspector(path, vetDetail, signal, timers, "not_found");
}

/** A kind's chart, by the bare kind; a kind off its pattern is never asked for. */
export function readExport(
  kind: string,
  signal: AbortSignal,
  timers: ReadTimers,
): Promise<InspectorOutcome<ChartExport>> {
  const path = exportPath(kind);
  if (path === null) return Promise.resolve({ kind: "not_found" });
  return readInspector(path, (raw) => vetExport(raw, kind), signal, timers, "not_found");
}
