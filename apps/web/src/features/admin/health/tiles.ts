/**
 * SCR-143's tiles and lines as data (E42-D05 §5, D2–D10; the build plan's §1.2): pure functions of
 * the store, testable without a DOM. A model holds only what its tile shows, so a frame that
 * changes one component changes one model and only its tile renders: a frame's words carry no time
 * in the model, their "as of" is the page's one leaf on `framesSeenAt` (C-1084P1-d01).
 */
import type { SystemHealthTileTone } from "@candleviewer/ui";
import { hms } from "../overview/tileModels";
import { HEALTH_COPY as COPY, HINTS, STOPS } from "./copy";
import {
  clockOf,
  isFault,
  mergeComponents,
  type ComponentRecord,
  type RecordState,
  type Reported,
} from "./frames";
import { stillSafe, type GateLegs } from "./gate";
import { READ_IDS, type Bodies, type Failure, type HealthState, type ReadId } from "./healthStore";
import { headingOf, plainLabel } from "./labels";

export interface TileModel {
  /** The component's name, or a fixed tile's key. */
  readonly key: string;
  readonly label: string;
  /** The detail view, `?component={name}` on R-350 [BQ-11]. */
  readonly href: string;
  /** `health-{name}` (F36), for a name safe as an id. */
  readonly anchor?: string | undefined;
  readonly state: "loading" | "ready";
  readonly tone: SystemHealthTileTone;
  readonly stateWord: string;
  readonly detail?: string | undefined;
  /** Whether the tile has a probe line; a `null` value reads "— not received". */
  readonly probe: boolean;
  readonly value?: number | null | undefined;
  readonly valueAsOf?: number | undefined;
  /** The report's time, for the report's words; a frame's words read the page's leaf instead. */
  readonly asOf?: number | undefined;
  /** The words are a frame's: "as of" is `framesSeenAt`, rendered by its own leaf [BQ-8]. */
  readonly framesAsOf?: boolean | undefined;
  readonly lastGoodAt?: number | undefined;
  /** CMP-239 after an observed failure (D6), never by age. */
  readonly staleSince?: number | undefined;
  readonly stopsWorking?: string | undefined;
  readonly stillSafe?: boolean | undefined;
  readonly hint?: string | undefined;
  readonly runbookHref?: string | undefined;
  readonly retry: boolean;
}

/**
 * D2: a tone per contract word; degraded and warning share the triangle and their word differs. A
 * word the client cannot read is neutral, neither down nor healthy (A-1084P1-d01).
 */
const TONE: Readonly<Record<RecordState, SystemHealthTileTone>> = {
  healthy: "ok",
  degraded: "warning",
  warning: "warning",
  down: "danger",
  not_deployed: "neutral",
  not_received: "neutral",
};
/** No probe line for `disk` and `secrets`, whose probe is no round trip (DJ). */
const NO_PROBE: ReadonlySet<string> = new Set(["disk", "secrets"]);
export const ANCHOR = /^[a-z0-9_]{1,64}$/;
/** A runbook links only a same-origin path [BQ-14]. */
const SAME_ORIGIN = /^\/(?![/\\])[\w\-./~%#?=&]*$/;

const own = (table: Readonly<Record<string, string>>, key: string): string | undefined =>
  Object.hasOwn(table, key) ? table[key] : undefined;
function wordFor(state: RecordState): string {
  if (state === "not_received") return COPY.notReceived;
  return state === "not_deployed" ? COPY.notDeployed : state;
}

const reportOf = (s: HealthState): Reported | undefined => {
  const { data, okAt } = s.reads.health;
  return data === undefined || okAt === undefined ? undefined : { body: data, at: okAt };
};

/** The page's component records: the kept report merged with the frames' words. */
export const componentsOf = (s: HealthState): ComponentRecord[] =>
  mergeComponents(reportOf(s), s.words, s.framesSeenAt);

/** D9's legs as the store holds them: a read whose last answer was not `ok` is missing. */
export function legsOf(s: HealthState, records: readonly ComponentRecord[]): GateLegs {
  const oms = records.find((record) => record.name === "oms");
  const ok = <K extends ReadId>(id: K): Bodies[K] | undefined =>
    s.reads[id].phase === "ok" ? s.reads[id].data : undefined;
  // Words are fresh while their source answers: the transport for a frame's, the read for the
  // report's, and no newer frame left `oms` out (C-1084P1-d02). Unreadable words are not received.
  const { phase, okAt } = s.reads.health;
  const fresh =
    oms?.source === "frame"
      ? s.droppedAt === undefined
      : phase === "ok" && (s.framesSeenAt === undefined || s.framesSeenAt < (okAt ?? -Infinity));
  return {
    oms:
      oms === undefined || oms.state === "not_received" ? undefined : { state: oms.state, fresh },
    open: ok("open"),
    acknowledged: ok("acknowledged"),
    protection: ok("protection"),
  };
}

const runbookOf = (name: string, s: HealthState): string | undefined =>
  s.reads.open.data?.items.find(
    (i) =>
      i.component === name && typeof i.runbook_ref === "string" && SAME_ORIGIN.test(i.runbook_ref),
  )?.runbook_ref ?? undefined;

/** Loading until the report's first answer, and while the tile's own Retry runs. */
const loading = (s: HealthState, key: string): boolean => {
  const { phase, inFlight, retriedBy } = s.reads.health;
  return phase === "idle" || (inFlight && retriedBy === key);
};

/** States with no number: down, not built (HL-5, HL-7) and a word not received (A-1084P1-d01). */
const NO_NUMBER: ReadonlySet<RecordState> = new Set(["down", "not_deployed", "not_received"]);

/** One component's CMP-178 model. */
export function componentTile(record: ComponentRecord, s: HealthState, legs: GateLegs): TileModel {
  const { name, state } = record;
  const health = s.reads.health;
  const fault = isFault(state);
  const probe = !NO_PROBE.has(name) && !NO_NUMBER.has(state);
  const framesAsOf = record.source === "frame";
  const failedAt = health.phase === "failed" ? health.failedAt : undefined;
  // HL-14: a frame's words go stale with a lost transport once the report fails; HL-11: a kept
  // number goes stale, and HL-12's never-read one stays "— not received".
  const stale =
    record.source === "frame"
      ? (s.droppedAt ?? (probe && record.latencyMs !== undefined ? failedAt : undefined))
      : failedAt;
  return {
    key: name,
    label: headingOf(name),
    href: `?component=${encodeURIComponent(name)}`,
    anchor: ANCHOR.test(name) ? `health-${name}` : undefined,
    state: loading(s, name) ? "loading" : "ready",
    tone: TONE[state],
    stateWord: wordFor(state),
    detail: record.detail,
    probe,
    value: probe ? (record.latencyMs ?? null) : undefined,
    // D5: a number older than its word carries its own "as of"; a frame's word is never older.
    valueAsOf:
      probe && (framesAsOf || record.latencyAt !== record.wordAt) ? record.latencyAt : undefined,
    asOf: framesAsOf ? undefined : record.wordAt,
    framesAsOf,
    lastGoodAt: fault ? record.lastGoodAt : undefined,
    staleSince: failedAt === undefined ? undefined : stale,
    stopsWorking: fault ? own(STOPS, `${name}:${state}`) : undefined,
    stillSafe: fault && stillSafe(name, legs),
    hint: fault ? (own(HINTS, name) ?? own(HINTS, "default")) : undefined,
    runbookHref: fault ? runbookOf(name, s) : undefined,
    retry: health.phase === "failed",
  };
}

/** The tile of the component `name`, or none once it is gone. */
export function tileOf(name: string, s: HealthState): TileModel | undefined {
  const records = componentsOf(s);
  const record = records.find((r) => r.name === name);
  return record === undefined ? undefined : componentTile(record, s, legsOf(s, records));
}

/** "2 300": D05's thousands, a space apart. */
const grouped = (n: number | undefined): string =>
  n === undefined ? "—" : new Intl.NumberFormat("en-US").format(n).replace(/,/g, " ");

const fixed = (key: string, label: string) =>
  ({
    key,
    label,
    href: `?component=${key}`,
    anchor: `health-${key}`,
    probe: false,
    retry: false,
  }) as const;

/** HL-8: the client-composed clock tile, from the frames and the report. */
export function clockTile(s: HealthState): TileModel {
  const clock = clockOf(s.clock, reportOf(s));
  const base = {
    ...fixed("clock", COPY.clock.label),
    state: loading(s, "clock") ? "loading" : "ready",
  } as const;
  if (clock.kind === "not_measured")
    return { ...base, tone: "neutral", stateWord: COPY.clock.notMeasured };
  const offset = grouped(clock.offsetMs);
  if (clock.kind === "ok")
    return { ...base, tone: "ok", stateWord: COPY.clock.ok(offset), asOf: clock.at };
  const hint = own(HINTS, "clock");
  return { ...base, tone: "danger", stateWord: COPY.clock.drift(offset), asOf: clock.at, hint };
}

/** D4: the algo engine has no component (CG-18); the admin route never hosts a chart engine. */
export const FIXED_TILES: readonly TileModel[] = [
  {
    ...fixed("algo_engine", COPY.algo.label),
    state: "ready",
    tone: "neutral",
    stateWord: COPY.notReported,
  },
  {
    ...fixed("chart_engine", COPY.client.label),
    state: "ready",
    tone: "neutral",
    stateWord: COPY.client.none,
  },
];

/** The client's words for a failed read, never the server's [BQ-14]. */
function failureWords(failure: Failure | undefined): string {
  if (failure === undefined || "reason" in failure) {
    if (failure?.reason === "timeout") return COPY.failure.timeout;
    return failure?.reason === "unreadable" ? COPY.failure.unreadable : COPY.failure.network;
  }
  if (failure.code === "audit_unavailable") return COPY.failure.audit;
  return failure.status === 503 ? COPY.failure.busy : COPY.failure.status(failure.status);
}

/** D10: the newer of the last health frame and the report; HL-15's own line. */
export function overallLine(s: HealthState): string | undefined {
  const { health } = s.reads;
  const failure = health.phase === "failed" ? health.failure : undefined;
  if (failure !== undefined && "code" in failure && failure.code === "audit_unavailable") {
    return COPY.unavailable(COPY.failure.audit);
  }
  const frame = s.overall;
  const word = health.data?.overall;
  const rest =
    word === undefined || health.okAt === undefined ? undefined : { word, at: health.okAt };
  const pick =
    frame === undefined || (rest !== undefined && (frame.at ?? -1) < rest.at) ? rest : frame;
  if (pick === undefined) return undefined;
  const at = pick.at === undefined ? undefined : hms(pick.at);
  return COPY.overall(wordFor(pick.word), at, pick === frame);
}

function uptime(seconds: unknown): string | undefined {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return undefined;
  const m = Math.floor(seconds / 60);
  return COPY.up(Math.floor(m / 1_440), Math.floor(m / 60) % 24, m % 60);
}

/**
 * The page's lines: the tiles' names, whether the report answered (the render measure's end),
 * whether D5's reads run (Re-read busy, never T2), the incidents count, the failed report with
 * the read it is about (HL-11, HL-12, HL-15), HL-10's line, HL-5's banner closed by `health.safe`
 * when D9 holds for every component down [BQ-12], and the build line.
 */
export function pageLines(s: HealthState) {
  const { health, open } = s.reads;
  const records = componentsOf(s);
  const legs = legsOf(s, records);
  const down = records.filter((r) => r.state === "down");
  const r = health.data;
  const build = [r?.version, r?.git_sha, r?.environment, uptime(r?.uptime_seconds)];
  const page = open.phase === "ok" ? open.data : undefined;
  const unread = open.phase === "idle" ? undefined : COPY.incidentsUnread;
  const report = COPY.reportFailed(failureWords(health.failure));
  const busy = health.inFlight && health.retriedBy === "report";
  return {
    names: records.map((record) => record.name),
    settled: health.phase !== "idle",
    rereading: READ_IDS.some((id) => s.reads[id].inFlight && s.reads[id].retriedBy === undefined),
    asOf: health.okAt,
    incidents: page
      ? COPY.incidents(page.meta.total ?? page.meta.count, page.meta.has_more)
      : unread,
    report:
      health.phase === "failed" ? { text: report, answers: health.answers ?? 0, busy } : undefined,
    probesNotDeployed: health.phase === "not_built",
    banner:
      down.length === 0
        ? undefined
        : {
            title: COPY.bannerDown(down.map((d) => plainLabel(d.name)).join(", ")),
            safe: down.every((d) => stillSafe(d.name, legs)),
          },
    build: build.some(Boolean) ? build.filter(Boolean).join(" · ") : undefined,
  };
}
export type PageLines = ReturnType<typeof pageLines>;

/** What the voice compares: each component's state and the clock's, with its label. */
export function voiceStates(s: HealthState): { name: string; label: string; state: string }[] {
  if (s.reads.health.phase === "idle" && s.words.size === 0) return [];
  const clock = clockOf(s.clock, reportOf(s)).kind;
  return [
    ...componentsOf(s).map((r) => ({ name: r.name, label: plainLabel(r.name), state: r.state })),
    { name: "clock", label: COPY.clock.label, state: clock === "drift" ? COPY.clock.word : clock },
  ];
}
