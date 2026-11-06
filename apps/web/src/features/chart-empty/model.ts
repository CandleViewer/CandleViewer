/**
 * SCR-047's state selection (E11-D04 §11.2 reasons 1a / 1b / 2 / 3; E16-D05 §1.5, §4) and its words (§14), pure. A typed
 * leaf the SCR-030 pane composes (BQ-01): it builds no engine and requests no bars. The state is driven by data — the
 * pane's `/market/bars` outcome (the 422 `no_data_recorded`, `meta`), the engine's edge-triggered `dataState` (`26`:446),
 * the coverage read through `symbol-info`'s `fetchCoverage`, the instrument's status, the served `role_restricted` flag —
 * never by an empty array alone. Role legs are by permission, never by role name (D06 C-r): view-as, then
 * `recording:write`; `/admin/**` links need `admin:read`.
 */
import type { ChartEvents } from "@candleviewer/chart-engine";
import type { generated } from "@candleviewer/protocol";
import type { IconName } from "@candleviewer/ui";
import { ROUTE_MANIFEST } from "../../routes/manifest";
import type { CoverageOutcome } from "../symbol-info/coverage";
import { CAUSE, HEADING, LABEL, STATUS_FALLBACK, STATUS_WORDS, fill } from "./copy";
import {
  earliestRecorded,
  gapCause,
  gapIntervals,
  utcDate,
  utcStamp,
  utcTime,
  type GapInterval,
  type TimeWindow,
} from "./gaps";

type Schemas = generated.rest.components["schemas"];

/** The pane's bars bootstrap. `failed` is a timeout or transport failure: SCR-048 (BQ-06). */
export type BarsAnswer =
  | { readonly kind: "loading" }
  | { readonly kind: "ok"; readonly count: number; readonly meta?: Schemas["BarsMeta"] }
  | { readonly kind: "no_data_recorded"; readonly recordingStartedAtMs: number | null }
  | { readonly kind: "failed" };

/** The recorder's auto-record facts (D05 §4 `autorecord-*`), fed by E16-S02 #566; those frames are carried until then. */
export interface AutoRecordInputs {
  readonly enabled: Schemas["RecorderPolicySettings"]["autorecord_enabled"];
  readonly delayS: Schemas["RecorderPolicySettings"]["autostart_delay_s"];
  readonly refusal: Schemas["RecordRefusal"] | undefined;
}

export interface ChartStateInput {
  readonly symbol: string;
  readonly interval: string;
  readonly window: TimeWindow;
  readonly bars: BarsAnswer;
  /** `fetchCoverage`'s outcome, `null` while in flight; its deadline and failed branch are the reader's (BQ-06). */
  readonly coverage: CoverageOutcome | null;
  /** The engine's `dataState` for the visible range (`26`:446); `"empty"` with bars loaded is the range-empty case. */
  readonly dataState?: ChartEvents["dataState"]["state"] | null;
  /** `Instrument.status`; `null` until known. */
  readonly instrumentStatus: string | null;
  /** `Instrument.status_reason`: the not-trading cause when the server sends it (D05 :184). */
  readonly statusReason?: string | null;
  /** The served `role_restricted` flag (`22`:21193; BQ-07): rendered, never inferred. */
  readonly roleRestricted?: Schemas["RecordingStatus"]["role_restricted"];
  /** `RecordedSymbol.retention_days`; `null` = the policy's 30 days. */
  readonly retentionDays?: number | null;
  /** The role and view-as legs (C-r); see `accessOf`. */
  readonly access: Access;
  readonly autoRecord?: AutoRecordInputs | null;
}

export type FrameId =
  | "never-recorded"
  | "before-start"
  | "gap"
  | "gap-retention-purge"
  | "no-trades-in-window"
  | "not-trading"
  | "role-restricted";

/** E11-D04 §11.2's reasons. */
export type Reason = "1a" | "1b" | "2" | "3";

export interface EmptyFacts {
  readonly frame: FrameId;
  readonly reason: Reason;
  readonly symbol: string;
  readonly interval: string;
  /** 1b: the recording start; retention: the trim date. */
  readonly atMs: number | null;
  /** Reason 2 inside a gap: the gap. */
  readonly gap: GapInterval | null;
  readonly instrumentStatus: string | null;
  readonly statusReason: string | null;
  readonly retentionDays: number | null;
  readonly access: Access;
}

export type ChartState =
  | { readonly kind: "loading" }
  /** SCR-048 (`features/chart-errors`): the bars bootstrap failed or timed out. */
  | { readonly kind: "bootstrap-failed" }
  /** CMP-026 `variant="error"` with Retry: the coverage read that decides an empty state failed. */
  | { readonly kind: "coverage-error" }
  | {
      readonly kind: "populated";
      readonly gaps: readonly GapInterval[];
      /** `false` when coverage failed: the carriers say it could not load, never "no gaps" (D05-CG1). */
      readonly coverageKnown: boolean;
    }
  | ({ readonly kind: "empty" } & EmptyFacts);

const covers = (gap: GapInterval, window: TimeWindow): boolean =>
  gap.fromMs <= window.fromMs && gap.toMs >= window.toMs;

/** The decision table. Order: restricted → not trading → 422 → coverage (never / before / gap / none). */
export function selectChartState(input: ChartStateInput): ChartState {
  const { bars, coverage, window } = input;
  if (bars.kind === "loading") return { kind: "loading" };
  if (bars.kind === "failed") return { kind: "bootstrap-failed" };
  const read = coverage?.kind === "ok" ? coverage.coverage : null;
  if (bars.kind === "ok" && bars.count > 0 && input.dataState !== "empty") {
    return read !== null
      ? { kind: "populated", gaps: gapIntervals(read, window), coverageKnown: true }
      : { kind: "populated", gaps: [], coverageKnown: coverage === null };
  }
  const facts = (frame: FrameId, reason: Reason, extra: Partial<EmptyFacts> = {}): ChartState => ({
    kind: "empty",
    frame,
    reason,
    symbol: input.symbol,
    interval: input.interval,
    atMs: null,
    gap: null,
    instrumentStatus: input.instrumentStatus,
    statusReason: input.statusReason ?? null,
    retentionDays: input.retentionDays ?? null,
    access: input.access,
    ...extra,
  });
  if (input.roleRestricted === true) return facts("role-restricted", "2");
  if (input.instrumentStatus !== null && input.instrumentStatus !== "Trading")
    return facts("not-trading", "3");
  const gaps = read !== null ? gapIntervals(read, window, false) : [];
  // A retention gap over the window is the retention frame, never 1b: its trim date lies after the start (D05 :206).
  const purge = gaps.find((g) => g.reason === "retention_purge" && covers(g, window));
  if (purge !== undefined)
    return facts("gap-retention-purge", "2", { gap: purge, atMs: purge.toMs });
  const neverFrame = (): ChartState => facts("never-recorded", "1a");
  if (bars.kind === "no_data_recorded") {
    return bars.recordingStartedAtMs === null
      ? neverFrame()
      : facts("before-start", "1b", { atMs: bars.recordingStartedAtMs });
  }
  // Zero bars in view: coverage decides the reason.
  if (coverage === null) return { kind: "loading" };
  if (read === null) return { kind: "coverage-error" };
  const earliest = earliestRecorded(read);
  if (earliest === null) return neverFrame();
  if (window.toMs <= earliest) return facts("before-start", "1b", { atMs: earliest });
  const inside = gaps.find((g) => covers(g, window));
  // `never_recorded` is a gap reason that routes to the history-start family, never a gap sentence (D05 §2).
  if (inside?.reason === "never_recorded") return neverFrame();
  if (inside !== undefined) return facts("gap", "2", { gap: inside });
  return facts("no-trades-in-window", "2");
}

const isProblem = (body: unknown): body is Schemas["Problem"] =>
  typeof body === "object" && body !== null && typeof Reflect.get(body, "code") === "string";

/**
 * The pane's `/market/bars` refusal read for SCR-047: `no_data_recorded` (422) with its `recording_started_at` (null
 * when never recorded), else `null` (the pane routes any other answer). `Problem.detail` is never read (D05-C6).
 */
export function noDataRecorded(status: number, body: unknown): BarsAnswer | null {
  if (status !== 422 || !isProblem(body) || body.code !== "no_data_recorded") return null;
  const at = body.recording_started_at;
  const ms = typeof at === "string" ? Date.parse(at) : NaN;
  return { kind: "no_data_recorded", recordingStartedAtMs: Number.isFinite(ms) ? ms : null };
}

/** Who is looking (C-r): by permission, never by role name; the view-as leg comes first. */
export interface Access {
  /** The view-as target's name while the Owner views as someone, else `null`. */
  readonly viewAsUser: string | null;
  readonly canRecord: boolean;
  readonly canAdmin: boolean;
}

export const accessOf = (permissions: readonly string[], viewAsUser: string | null): Access => ({
  viewAsUser,
  canRecord: permissions.includes("recording:write"),
  canAdmin: permissions.includes("admin:read"),
});

export type LinkId = "retention_policy";
export type ActionId = Exclude<keyof typeof LABEL, LinkId | "retry">;
export interface ViewAction {
  readonly id: ActionId;
  readonly label: string;
}

/** The block's words and controls for one frame and one viewer. */
export interface EmptyView {
  readonly heading: string;
  /** The cause, then the T2 sentence when the sole write is replaced (the sentence form). */
  readonly description: string;
  readonly glyph: IconName;
  readonly variant: "no-data" | "recording-not-started";
  readonly actions: readonly ViewAction[];
  /** An `/admin/**` link, the Owner's only; absent without `admin:read` or while viewing as (T2-15). */
  readonly link: { readonly id: LinkId; readonly label: string; readonly href: string } | null;
  /** Whether the live-data sentence applies: only while `Instrument.status` is Trading (E11-D04 :351). */
  readonly live: boolean;
}

/** SCR-140's route id (R-340): the CTA and the retention link go there; the add happens there (BQ-03). */
export const RECORDER_ROUTE = "R-340";
/** The registry's path for SCR-140, never hard-coded; `undefined` if the registry has none (then nothing links). */
export const recordHref = (): string | undefined =>
  ROUTE_MANIFEST.find((entry) => entry.id === RECORDER_ROUTE)?.path;

const action = (id: ActionId): ViewAction => ({ id, label: LABEL[id] });

/**
 * The recorder write a viewer gets (exported for the other consumers of the gated CTA, e.g. the liquidations feed):
 * the action when the session may write, else the T2 sentence that replaces it (view-as first).
 */
export function recordWrite(
  access: Access,
  words: Pick<ViewWords, "ownerOnly" | "viewAs">,
): { readonly action: ViewAction } | { readonly sentence: string } {
  if (access.viewAsUser !== null) return { sentence: words.viewAs(access.viewAsUser) };
  return access.canRecord ? { action: action("record") } : { sentence: words.ownerOnly };
}

export interface ViewWords {
  readonly ownerOnly: string;
  readonly viewAs: (user: string) => string;
  /** A SCR-151 panel instance rather than the chart pane. */
  readonly panel?: boolean;
}

interface Spec {
  readonly heading: string;
  readonly cause: string;
  readonly glyph: IconName;
  readonly actions: readonly ActionId[];
  /** `Record this symbol` leads the actions, role-resolved. */
  readonly write?: true;
  readonly link?: LinkId;
}

const sp = (
  heading: string,
  cause: string,
  glyph: IconName,
  actions: readonly ActionId[],
  extra: Partial<Spec> = {},
): Spec => ({ heading, cause, glyph, actions, ...extra });

function spec(f: EmptyFacts, words: ViewWords): Spec {
  const s = f.symbol;
  const inWindow = fill(HEADING.no_bars_window, { symbol: s, interval: f.interval });
  const notRec = fill(HEADING.not_recorded, { symbol: s });
  const exits: readonly ActionId[] = ["go_latest", "show_coverage"];
  const g = f.gap;
  const at = f.atMs ?? 0;
  switch (f.frame) {
    case "never-recorded":
      return sp(notRec, CAUSE.recorded_only, "calendar", ["learn_more"], { write: true });
    case "before-start": {
      const heading = fill(HEADING.history_starts, { ts: utcStamp(at) });
      return sp(heading, CAUSE.recorded_only, "calendar", ["go_recorded", "show_coverage"]);
    }
    case "gap": {
      const range = g === null ? null : { from: utcTime(g.fromMs), to: utcTime(g.toMs) };
      const heading =
        range === null
          ? inWindow
          : fill(HEADING.no_bars_between, { symbol: s, interval: f.interval, ...range });
      return sp(heading, gapCause(g?.reason ?? null), "disconnected", exits);
    }
    case "gap-retention-purge": {
      const heading = fill(HEADING.retention_trimmed, { symbol: s, date: utcDate(at) });
      const cause = gapCause("retention_purge", f.retentionDays);
      return sp(heading, cause, "minus", exits, { link: "retention_policy" });
    }
    case "no-trades-in-window":
      return sp(inWindow, CAUSE.no_trades, "info", exits);
    case "not-trading": {
      const status = f.instrumentStatus ?? "";
      const listed = Object.hasOwn(STATUS_WORDS, status) ? STATUS_WORDS[status] : undefined;
      const said = f.statusReason ?? listed ?? fill(STATUS_FALLBACK, { status });
      const cause = `${said} ${CAUSE.no_live}`;
      return sp(fill(HEADING.not_trading, { symbol: s }), cause, "warning", [
        "open_symbol",
        "switch_symbol",
      ]);
    }
    case "role-restricted": {
      const here = fill(HEADING.no_history_here, { symbol: s });
      return sp(words.panel === true ? here : inWindow, CAUSE.restricted, "info", [
        "show_coverage",
      ]);
    }
  }
}

/** The deck for a frame (D05 §4, §5), role-resolved (§1.3: view-as first, then `recording:write`, then `admin:read`). */
export function emptyView(facts: EmptyFacts, words: ViewWords): EmptyView {
  const { access } = facts;
  const v = spec(facts, words);
  const href = recordHref();
  const w = v.write === true ? recordWrite(access, words) : null;
  const owner = access.canAdmin && access.viewAsUser === null;
  return {
    heading: v.heading,
    description: w !== null && "sentence" in w ? `${v.cause} ${w.sentence}` : v.cause,
    glyph: v.glyph,
    // BQ-7: retention (`minus`) stays `recording-not-started`; gap, no-trades and status frames are `no-data`.
    variant: v.glyph === "calendar" || v.glyph === "minus" ? "recording-not-started" : "no-data",
    actions: [...(w !== null && "action" in w ? [w.action] : []), ...v.actions.map(action)],
    link:
      v.link !== undefined && owner && href !== undefined
        ? { id: v.link, label: LABEL[v.link], href }
        : null,
    live: facts.instrumentStatus === "Trading",
  };
}

/** `chart.empty_state_shown {reason, cause?}` (D05-A6; E11-D04 §11.2): 1a / 1b → `not_recorded`, 2, 3. */
export function chartAnalytics(facts: EmptyFacts): {
  readonly reason: "not_recorded" | "no_data_in_range" | "symbol_delisted";
  readonly cause?: string;
} {
  const reason = {
    "1a": "not_recorded",
    "1b": "not_recorded",
    "2": "no_data_in_range",
    "3": "symbol_delisted",
  } as const;
  // D05-G2: `cause` is the gap reason, never invented.
  const cause = facts.gap?.reason ?? null;
  return cause === null
    ? { reason: reason[facts.reason] }
    : { reason: reason[facts.reason], cause };
}

/** The entry key: a new reason (or cause) is a new entry; a re-render is not. */
export const entryKey = (facts: EmptyFacts): string =>
  `${facts.frame}:${facts.gap?.reason ?? ""}:${facts.symbol}`;
