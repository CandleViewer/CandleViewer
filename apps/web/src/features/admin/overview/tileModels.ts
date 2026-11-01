/**
 * SCR-120's nine tiles as data (E42-S01; E42-D03 §6, D8, and E42-D02 D4's "old" and "down"): pure
 * functions of the read store, so every state is testable without a DOM. A model holds only what its
 * tile shows: a re-read that changed nothing yields the same model and its tile does not re-render.
 */
import type { SystemHealthTileEnv } from "@candleviewer/ui";
import type { AdminOverview, AuditEntry, FailReason } from "./adminReads";
import { OVERVIEW_COPY as COPY, STOPS } from "./copy";
import { routePath, type AdminLink } from "./links";
import type { AdminReadState, ReadEntry, ReadId } from "./readStore";

export type TileKey = keyof typeof COPY.tiles;
export type TileState = "loading" | "ready" | "error" | "unavailable";
export type TileTone = "ok" | "warning" | "danger" | "stale" | "neutral";

export interface TileRow {
  readonly label: string;
  /** `null` is a value not received: "—", never a number. */
  readonly value: string | number | null;
  /** The value links to this manifest path. */
  readonly href?: string | undefined;
  /**
   * Epoch ms of the answer to this line's own read. Set only on a line fed by a read asked once per
   * entry, under a tile whose "as of" is the cycled overview's: the line prints its own time, never
   * the tile's (C-5330-11).
   */
  readonly asOf?: number | undefined;
}

export interface TileModel {
  readonly key: TileKey;
  readonly label: string;
  readonly href: string;
  readonly state: TileState;
  readonly tone?: TileTone | undefined;
  readonly stateWord?: string | undefined;
  readonly detail?: string | undefined;
  readonly asOf?: number | undefined;
  readonly lastGoodAt?: number | undefined;
  readonly staleSince?: number | undefined;
  readonly stopsWorking?: string | undefined;
  readonly env?: SystemHealthTileEnv | undefined;
  readonly rows: readonly TileRow[];
  /** One sentence after the rows: the capacity line. */
  readonly note?: string | undefined;
  /** When the capacity read answered, printed after the note (a row's `asOf`, C-5330-11). */
  readonly noteAsOf?: number | undefined;
  /** The Audit tile's CMP-173 compact rows and its audited-read marker. */
  readonly audit?: readonly AuditEntry[] | undefined;
  readonly marker?: string | undefined;
  /** The reads its Retry repeats; empty, the tile has no Retry. */
  readonly retry: readonly ReadId[];
}

export type Env = SystemHealthTileEnv | "unknown";
type Fields = Readonly<Record<string, unknown>>;
type SliceName = "users" | "accounts" | "recorder" | "storage" | "trading" | "incidents";

/** The tile's heading link: the manifest's path, else the overview itself (never data). */
const HOME = "/admin";
const hrefOf = (link: AdminLink): string => routePath(link) ?? HOME;

/** Epoch ms of an RFC 3339 time, or `undefined`: never a guessed time. */
export function timeOf(value: unknown): number | undefined {
  if (typeof value !== "string") return undefined;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : undefined;
}

const num = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

/** A table's own entry for a server string, never an inherited one: "constructor" names nothing. */
const own = <T>(table: Readonly<Record<string, T>>, key: string): T | undefined =>
  Object.hasOwn(table, key) ? table[key] : undefined;

const two = (n: number): string => String(n).padStart(2, "0");
/** "hh:mm" in UTC (admin times are UTC, E42-D03 §1). */
const hhmm = (ms: number): string => {
  const at = new Date(ms);
  return `${two(at.getUTCHours())}:${two(at.getUTCMinutes())}`;
};
/** "hh:mm:ss" in UTC (E42-D03 §1). */
export const hms = (ms: number): string => `${hhmm(ms)}:${two(new Date(ms).getUTCSeconds())}`;
/** "yyyy-mm-dd" in UTC. */
const ymd = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/** The client's words for a read that failed. */
export function failureWords(reason: FailReason | undefined, status: number | undefined): string {
  if (reason === "timeout") return COPY.failure.timeout;
  if (reason === "status") return COPY.failure.status(status);
  if (reason === "unreadable") return COPY.failure.unreadable;
  return COPY.failure.network;
}

/** The parts of a tile its reads decide: its state, words, times and Retry. */
interface Look {
  readonly state: TileState;
  readonly tone?: TileTone | undefined;
  readonly stateWord?: string | undefined;
  readonly detail?: string | undefined;
  readonly asOf?: number | undefined;
  readonly lastGoodAt?: number | undefined;
  readonly staleSince?: number | undefined;
  readonly retry: readonly ReadId[];
}

const LOADING: Look = { state: "loading", retry: [] };
const NOT_BUILT: Look = { state: "unavailable", detail: COPY.notBuilt, retry: [] };

/** Loading until the first answer, and while this tile's own Retry runs. */
const loading = (entry: ReadEntry<unknown>, tile: TileKey): boolean =>
  entry.phase === "idle" || (entry.inFlight && entry.retriedBy === tile);

/**
 * A loading look: the first load has no Retry; a tile's own Retry stays while its read runs, busy,
 * so the pressed button keeps focus and hands it to the heading link only after a good answer
 * (A-5330-01).
 */
const loadingLook = (entry: ReadEntry<unknown>, retry: readonly ReadId[]): Look =>
  entry.phase === "idle" ? LOADING : { state: "loading", retry };

/**
 * A whole read's look, for a tile fed by one body: fresh, old (the last good body kept, "stale
 * since" the first failure, D02 D4), down (failed with nothing kept) or not built.
 */
function readLook(entry: ReadEntry<unknown>, id: ReadId, tile: TileKey): Look {
  if (loading(entry, tile)) return loadingLook(entry, [id]);
  if (entry.phase === "not_built") return NOT_BUILT;
  if (entry.phase === "ok") return { state: "ready", tone: "ok", asOf: entry.okAt, retry: [] };
  if (entry.phase === "failed" && entry.data !== undefined) {
    return { state: "ready", tone: "stale", staleSince: entry.failedAt, retry: [id] };
  }
  return { state: "error", detail: failureWords(entry.reason, entry.status), retry: [id] };
}

interface SliceLook extends Look {
  /** The fields to show: the slice as last read, or none. */
  readonly fields?: Fields | undefined;
}

/** One `AdminOverview` slice's look (§6 data table): its `status` is the server's word for it. */
function sliceLook(s: AdminReadState, name: SliceName, tile: TileKey): SliceLook {
  const entry = s.overview;
  if (loading(entry, tile)) return loadingLook(entry, ["overview"]);
  const kept = entry.data?.[name] as Fields | undefined;
  if (entry.phase === "failed") {
    if (kept?.["status"] === "ok") {
      return {
        state: "ready",
        tone: "stale",
        staleSince: entry.failedAt,
        fields: kept,
        retry: ["overview"],
      };
    }
    return {
      state: "error",
      detail: failureWords(entry.reason, entry.status),
      retry: ["overview"],
    };
  }
  if (entry.phase !== "ok") return NOT_BUILT;
  if (kept === undefined) return { state: "unavailable", detail: COPY.notReceived, retry: [] };
  const detail = typeof kept["detail"] === "string" ? kept["detail"] : COPY.notReceived;
  if (kept["status"] === "ok") {
    const asOf = timeOf(kept["generated_at"]) ?? entry.okAt;
    return { state: "ready", tone: "ok", asOf, fields: kept, retry: [] };
  }
  if (kept["status"] === "error") {
    const lastGoodAt = entry.sliceGoodAt?.[name];
    return { state: "error", detail, lastGoodAt, fields: kept, retry: ["overview"] };
  }
  return { state: "unavailable", detail, fields: kept, retry: [] };
}

/** A look's parts a model spreads, its Retry set aside (a model names its own reads). */
const lookParts = (look: Look): Omit<Look, "retry"> => ({
  state: look.state,
  tone: look.tone,
  stateWord: look.stateWord,
  detail: look.detail,
  asOf: look.asOf,
  lastGoodAt: look.lastGoodAt,
  staleSince: look.staleSince,
});

/** A row per field that was received; a field not read is left out (D8). */
function rows(fields: Fields | undefined, spec: ReadonlyArray<[string, string]>): TileRow[] {
  const out: TileRow[] = [];
  for (const [name, label] of spec) {
    const value = num(fields?.[name]);
    if (value !== undefined) out.push({ label, value });
  }
  return out;
}

const union = (...lists: ReadonlyArray<readonly ReadId[]>): ReadId[] => [...new Set(lists.flat())];
const envOf = (env: Env): SystemHealthTileEnv | undefined => (env === "unknown" ? undefined : env);

/** Users: the `users` slice and the pending invites (`GET /users/invites`). */
export function usersTile(s: AdminReadState): TileModel {
  const look = sliceLook(s, "users", "users");
  const out: TileRow[] = rows(look.fields, [
    ["total", COPY.users.total],
    ["active", COPY.users.active],
    ["without_mfa", COPY.users.withoutMfa],
  ]);
  const invites = s.invites;
  if (look.state !== "loading" && invites.phase !== "idle") {
    const value =
      invites.phase === "ok"
        ? (invites.data?.count ?? null)
        : invites.phase === "not_built"
          ? `Unavailable — ${COPY.notBuilt}` // `tile.not_built`: a 404 or 501 (C-5330-04)
          : null;
    // The count is the invites read's, asked once per entry: it prints its own time (C-5330-11).
    const asOf = typeof value === "number" ? invites.okAt : undefined;
    out.push({ label: COPY.users.invites, value, asOf });
  }
  return {
    key: "users",
    label: COPY.tiles.users,
    href: hrefOf("users"),
    ...lookParts(look),
    rows: look.state === "loading" ? [] : out,
    retry: union(look.retry, invites.phase === "failed" ? ["invites"] : []),
  };
}

/** The capacity line and when its read answered: its own time, printed after it (C-5330-11). */
interface CapacityLine {
  note?: string;
  asOf?: number | undefined;
  retry: ReadId[];
}

/** The capacity line (`cap.*`) from `SubaccountCapacity`; its [Change] and [Record tier] are S02's. */
function capacityLine(s: AdminReadState): CapacityLine {
  const entry = s.capacity;
  if (entry.phase === "idle") return { retry: [] };
  if (entry.phase === "not_built") return { note: COPY.cap.notBuilt, retry: [] }; // C-5330-04
  if (entry.phase !== "ok") {
    return { note: COPY.cap.down, retry: entry.phase === "failed" ? ["capacity"] : [] };
  }
  const sub = entry.data?.subaccounts as Fields | undefined;
  const used = num(sub?.["used"]);
  const cap = num(sub?.["cap"]);
  const rawTier = sub?.["tier"];
  const tier = typeof rawTier === "string" ? (own(COPY.cap.tiers, rawTier) ?? rawTier) : undefined;
  // What the read served below is asked once per entry: each line prints that read's own time.
  const asOf = entry.okAt;
  if (sub?.["tier_source"] === "unrecorded" && used !== undefined) {
    return { note: COPY.cap.unrecorded(used), asOf, retry: [] };
  }
  if (tier !== undefined && cap !== undefined) {
    if (used === undefined) return { note: COPY.cap.usedUnavailable(tier, cap), asOf, retry: [] };
    if (used > cap) return { note: COPY.cap.over(used, cap, tier), asOf, retry: [] };
    const recorded = timeOf(sub?.["recorded_at"]);
    const date = recorded === undefined ? null : ymd(recorded);
    return { note: COPY.cap.recorded(used, cap, tier, date), asOf, retry: [] };
  }
  if (used !== undefined) return { note: COPY.cap.tierUnavailable(used), asOf, retry: [] };
  return { note: COPY.cap.down, retry: [] };
}

/** Accounts and keys: the `accounts` slice, the capacity line, the withdrawal line (not mounted). */
export function accountsTile(s: AdminReadState, env: Env): TileModel {
  const look = sliceLook(s, "accounts", "accounts");
  const capacity: CapacityLine = look.state === "loading" ? { retry: [] } : capacityLine(s);
  const out = rows(look.fields, [
    ["total", COPY.accounts.total],
    ["enabled", COPY.accounts.enabled],
    ["keys_expiring_30d", COPY.accounts.expiring],
    ["keys_invalid", COPY.accounts.invalid],
  ]);
  // `getSecuritySummary` is not mounted (CG-7, E42-T02): the line takes `tile.not_built` (D8).
  out.push({ label: COPY.accounts.withdrawal, value: `Unavailable — ${COPY.notBuilt}` });
  return {
    key: "accounts",
    label: COPY.tiles.accounts,
    href: hrefOf("accounts"),
    env: envOf(env),
    ...lookParts(look),
    rows: look.state === "loading" ? [] : out,
    note: capacity.note,
    noteAsOf: capacity.asOf,
    retry: union(look.retry, capacity.retry),
  };
}

/** Profiles and limits: no slice serves it (CG-6), so `tile.not_built`. */
export function profilesTile(): TileModel {
  return {
    key: "profiles",
    label: COPY.tiles.profiles,
    href: hrefOf("profiles"),
    ...NOT_BUILT,
    rows: [],
  };
}

const RANK: Readonly<Record<string, number>> = { error: 3, unavailable: 2, ready: 1 };

const gb = (bytes: number): string => `${(bytes / 1e9).toFixed(1)} GB`;

/** Recorder and storage: two slices, one look: the worse of the two speaks (each `detail` names it). */
export function recorderTile(s: AdminReadState): TileModel {
  const recorder = sliceLook(s, "recorder", "recorder");
  const storage = sliceLook(s, "storage", "recorder");
  const worse =
    (RANK[storage.state] ?? 0) > (RANK[recorder.state] ?? 0) ||
    (storage.state === recorder.state && storage.tone === "stale")
      ? storage
      : recorder;
  const times = [recorder, storage].map((l) => l.asOf).filter((t): t is number => t !== undefined);
  const out = rows(recorder.fields, [
    ["symbols_recording", COPY.recorder.recording],
    ["symbols_degraded", COPY.recorder.degraded],
  ]);
  const lag = num(recorder.fields?.["lag_seconds_p99"]);
  if (lag !== undefined) out.push({ label: COPY.recorder.lag, value: `${lag.toFixed(1)} s` });
  for (const [name, label] of [
    ["used_bytes", COPY.recorder.used],
    ["free_bytes", COPY.recorder.free],
  ] as const) {
    const bytes = num(storage.fields?.[name]);
    if (bytes !== undefined) out.push({ label, value: gb(bytes) });
  }
  if (storage.fields !== undefined && "days_until_full" in storage.fields) {
    const days = num(storage.fields["days_until_full"]);
    out.push({
      label: COPY.recorder.daysUntilFull,
      value: days === undefined ? COPY.recorder.notMeasured : Math.floor(days),
    });
  }
  return {
    key: "recorder",
    label: COPY.tiles.recorder,
    href: hrefOf("recorder"),
    ...lookParts(worse),
    asOf: times.length === 0 ? undefined : Math.min(...times),
    rows: worse.state === "loading" ? [] : out,
    retry: union(recorder.retry, storage.retry),
  };
}

/**
 * The `maintenance.mode` line: the flags read's, and "—" unless that read stands (D02 §6.2). That
 * read is asked once per entry, so a value it served prints its own time (C-5330-11).
 */
function maintenanceRow(s: AdminReadState): TileRow {
  const label = COPY.trading.maintenance;
  const entry = s.flags;
  if (entry.phase !== "ok" || entry.data?.resolution !== "stored") return { label, value: null };
  const flag = entry.data.items?.find((f) => f.key === "maintenance.mode");
  const asOf = entry.okAt;
  if (flag?.value === false) return { label, value: COPY.trading.maintenanceOff, asOf };
  if (flag?.value !== true) return { label, value: null };
  const since = timeOf(flag.updated_at);
  return {
    label,
    value: COPY.trading.maintenanceOn(since === undefined ? null : hhmm(since)),
    href: routePath("maintenance"),
    asOf,
  };
}

/**
 * Trading safety: the current answer's `trading` slice, which the server never caches, and never an
 * old one here. Each field the slice served shows whatever its status: the server reads the kill
 * switch first and returns every part it read (E42-D03 preface (7) and §6's data table supersede
 * D01 AD-2's "unknown whenever the slice is not `ok`"). A field it left out reads "—" or
 * "unknown", and so does every field after a failed re-read: no "on" or "off" outlives the answer
 * that carried it (C-5330-01).
 */
export function tradingTile(s: AdminReadState, env: Env): TileModel {
  const sliced = sliceLook(s, "trading", "trading");
  const look: SliceLook =
    sliced.tone === "stale"
      ? {
          state: "error",
          detail: failureWords(s.overview.reason, s.overview.status),
          retry: ["overview"],
        }
      : sliced;
  const served = s.overview.phase === "ok" ? look.fields : undefined;
  const flag = (name: string): string | null => {
    const value = served?.[name];
    return typeof value === "boolean" ? (value ? COPY.trading.on : COPY.trading.off) : null;
  };
  const kill = flag("kill_switch_engaged");
  return {
    key: "trading",
    label: COPY.tiles.trading,
    href: hrefOf("risk"),
    env: envOf(env),
    ...lookParts(look),
    rows:
      look.state === "loading"
        ? []
        : [
            { label: COPY.trading.live, value: flag("live_enabled") },
            { label: COPY.trading.killSwitch, value: kill ?? COPY.trading.unknown },
            { label: COPY.trading.positions, value: num(served?.["open_positions"]) ?? null },
            maintenanceRow(s),
          ],
    retry: union(look.retry, s.flags.phase === "failed" ? ["flags"] : []),
  };
}

const COMPONENT_RANK: Readonly<Record<string, number>> = { down: 3, warning: 2, degraded: 1 };
const capital = (word: string): string => word.charAt(0).toUpperCase() + word.slice(1);

/** "bybit_private_ws reconnected 3× in the last hour": the name, then the server's detail. */
function componentWords(name: string, detail: unknown): string {
  if (typeof detail !== "string" || detail === "") return name;
  return detail.startsWith(name) ? detail : `${name} ${detail}`;
}

/** A component state's rank: 0 for a state that is no fault, or a name the table only inherits. */
const rankOf = (state: string | undefined): number => own(COMPONENT_RANK, state ?? "") ?? 0;

/** Health (`GET /admin/health`): the worst component speaks; `not_deployed` is never "healthy". */
export function healthTile(s: AdminReadState): TileModel {
  const entry = s.health;
  const base = readLook(entry, "health", "health");
  const report = entry.data;
  const components = report?.components ?? [];
  const out: TileRow[] = components
    .filter((c) => rankOf(c.state) > 0)
    .map((c) => ({ label: c.name ?? "", value: c.state ?? null }));
  // Open incidents from the current overview only: a failed read's count is old, "— not received".
  if (s.overview.phase !== "idle") {
    const incidents = s.overview.phase === "ok" ? s.overview.data?.incidents : undefined;
    const open = num((incidents as Fields | undefined)?.["open"]);
    out.push({ label: COPY.health.incidents, value: open ?? null });
  }
  const model = {
    key: "health" as const,
    label: COPY.tiles.health,
    href: hrefOf("health"),
    rows: base.state === "loading" || report === undefined ? [] : out,
  };
  if (base.state !== "ready" || base.tone !== "ok" || report === undefined) {
    return { ...model, ...base };
  }
  const asOf = timeOf(report.server_time) ?? entry.okAt;
  const worst = [...components].sort((a, b) => rankOf(b.state) - rankOf(a.state))[0];
  if (worst !== undefined && rankOf(worst.state) > 0) {
    const state = worst.state ?? "";
    return {
      ...model,
      state: "ready",
      tone: state === "down" ? "danger" : "warning",
      stateWord: capital(state),
      detail: componentWords(worst.name ?? "", worst.detail),
      lastGoodAt: timeOf(worst.last_good_at),
      stopsWorking: own(STOPS, `${worst.name ?? ""}:${state}`),
      asOf,
      retry: [],
    };
  }
  const overall = report.overall ?? "";
  if (rankOf(overall) > 0) {
    const tone = overall === "down" ? "danger" : "warning";
    return { ...model, state: "ready", tone, stateWord: capital(overall), asOf, retry: [] };
  }
  const notDeployed = components.filter((c) => c.state === "not_deployed").length;
  if (notDeployed > 0) {
    const stateWord = COPY.health.notDeployed(notDeployed);
    return { ...model, state: "ready", tone: "neutral", stateWord, asOf, retry: [] };
  }
  return { ...model, state: "ready", tone: "ok", asOf, retry: [] };
}

/**
 * Flags (`GET /admin/feature-flags`): a `fail_closed` list is not the stored state (E42-T03), fresh
 * or kept through a failed re-read: never a count of its fail-closed values (C-5330-07).
 */
export function flagsTile(s: AdminReadState): TileModel {
  const look = readLook(s.flags, "flags", "flags");
  const list = s.flags.data;
  const model = { key: "flags" as const, label: COPY.tiles.flags, href: hrefOf("flags") };
  if (look.state === "ready" && list?.resolution !== "stored") {
    return {
      ...model,
      state: "unavailable",
      detail: COPY.flags.failClosed,
      rows: [],
      retry: ["flags"],
    };
  }
  const items = look.state === "ready" ? (list?.items ?? []) : [];
  return {
    ...model,
    ...lookParts(look),
    rows:
      look.state === "ready"
        ? [
            { label: COPY.flags.total, value: items.length },
            { label: COPY.flags.enabled, value: items.filter((f) => f.value === true).length },
          ]
        : [],
    retry: look.retry,
  };
}

/** Audit: the three latest entries as CMP-173 compact rows and the audited-read marker (D9). */
export function auditTile(s: AdminReadState): TileModel {
  const look = readLook(s.audit, "audit", "audit");
  const entries = look.state === "ready" ? (s.audit.data?.items ?? []).slice(0, 3) : [];
  return {
    key: "audit",
    label: COPY.tiles.audit,
    href: hrefOf("audit"),
    ...lookParts(look),
    rows: [],
    audit: look.state === "ready" ? entries : undefined,
    marker: look.state === "ready" ? COPY.auditMarker : undefined,
    retry: look.retry,
  };
}

/** The newest run's line: "{hh:mm} UTC · {status}" (board 09's Ok specimen). */
function lastBackupRow(s: AdminReadState): TileRow | undefined {
  const label = COPY.backups.last;
  const entry = s.backups;
  if (entry.phase === "idle") return undefined;
  if (entry.phase === "not_built") return { label, value: `Unavailable — ${COPY.notBuilt}` };
  if (entry.phase !== "ok") return { label, value: null };
  const runs = (entry.data?.items ?? [])
    .map((run) => ({ at: timeOf(run.finished_at) ?? timeOf(run.started_at), status: run.status }))
    .filter((run): run is { at: number; status: typeof run.status } => run.at !== undefined)
    .sort((a, b) => b.at - a.at);
  const newest = runs[0];
  if (newest === undefined) return { label, value: COPY.backups.none };
  return { label, value: `${hhmm(newest.at)} UTC · ${newest.status ?? COPY.notReceived}` };
}

/** Security and backups: the summary is not mounted (CG-7); backups answer 501 until catalogued. */
export function securityTile(s: AdminReadState): TileModel {
  const backup = lastBackupRow(s);
  return {
    key: "security",
    label: COPY.tiles.security,
    href: hrefOf("security"),
    ...NOT_BUILT,
    rows: backup === undefined ? [] : [backup],
    retry: s.backups.phase === "failed" ? ["backups"] : [],
  };
}

/** The nine tiles in their three bands, in DOM and Tab order (§6 Anatomy). */
export const BANDS: readonly (readonly TileKey[])[] = [
  ["trading", "health", "recorder"],
  ["users", "accounts", "profiles"],
  ["audit", "security", "flags"],
];

export function tileModel(key: TileKey, s: AdminReadState, env: Env): TileModel {
  switch (key) {
    case "trading":
      return tradingTile(s, env);
    case "health":
      return healthTile(s);
    case "recorder":
      return recorderTile(s);
    case "users":
      return usersTile(s);
    case "accounts":
      return accountsTile(s, env);
    case "profiles":
      return profilesTile();
    case "audit":
      return auditTile(s);
    case "security":
      return securityTile(s);
    case "flags":
      return flagsTile(s);
  }
}

/** Whether every read the page shows has answered at least once: the render budget's end (800 ms). */
export const PAGE_READS: readonly ReadId[] = [
  "overview",
  "capacity",
  "health",
  "flags",
  "audit",
  "backups",
  "invites",
];

export function allAnswered(s: AdminReadState): boolean {
  return PAGE_READS.every((id) => s[id].phase !== "idle");
}

export type { AdminOverview };
