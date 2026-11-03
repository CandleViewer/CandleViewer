/**
 * The audit log's integrity, as this session knows it (E42-S04; E42-D04 §7, D10, D11, AL-10 to
 * AL-13, AD-5; the build plan's §3). Module-level session state: a page leaving keeps it.
 * - Shown as served, compared by id only: the client hashes nothing and never re-links rows.
 * - Run tamper check posts no bounds (D11), so its range ends at the head. Each passing range is
 *   kept for SCR-136's line. `verified: false` starts FAILED, which only a later pass from genesis
 *   to the head (`anchor_hash` 64 zeros) ends; a partial pass, an acknowledged incident or a
 *   cleared alert never does.
 * - The incident episode: an `open` or `acknowledged` `audit_chain_break` incident (component
 *   `db`, the served title "audit chain break at id <n>", `api/audit_verify.py`; CG-13), read on
 *   entry and every 60 s (`AUDIT_CADENCE`, PROPOSED), and once more right after a run finds a break
 *   (the orchestrator's Q2 (a)). A failed read keeps the last state and says so. My activity never
 *   reads it: a Manager holds no `admin:read` (BQ-4).
 * - The halt line keys on the served `open` incident, which acknowledging lifts, never on the
 *   kill-switch frame's free-text reason (the orchestrator's BQ-5 override). A run's break with no
 *   served incident (its event write failed, or the read did) never says order entry runs on: the
 *   halt is the verify route's own, so the line says it may stand (PROPOSED, C-1135P2-08).
 * - Each episode speaks once: its voice is `break:<first bad id>`, else the incident's or the
 *   run's own key. A run's break waits for an incident read to answer before the banner shows,
 *   so its one alert carries the line the incident decides (A-1135P2-09).
 * - Under view-as a `403 forbidden` is the target's refusal, never the area withdrawn (BQ-9): the
 *   holding page passes its view-as source (C-1135P2-07).
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import {
  AUDIT_CADENCE,
  forbiddenMeaning,
  listIncidents,
  verifyAuditChain,
  type AuditAnswer,
  type AuditEntry,
  type AuditPageBody,
  type AuditRefusal,
  type AuditTimers,
  type AuditView,
  type Incident,
  type IncidentPageBody,
  type VerifyResult,
} from "./auditReads";
import { AUDIT_COPY as COPY, num, range, utc } from "./copy";

/** D04 §7 (PROPOSED): the incident read's cadence, set with the others in `AUDIT_CADENCE`. */
export const INCIDENT_POLL_MS = AUDIT_CADENCE.incidentReadMs;
/** The anchor of a range that starts at the chain's first entry (`22` verifyAuditChain). */
export const GENESIS_HASH = "0".repeat(64);
/** The served incident's component and title (`api/audit_verify.py`, `raise_break_event`). */
export const CHAIN_BREAK_COMPONENT = "db";
const CHAIN_BREAK_TITLE = /^audit chain break\b/;
const CHAIN_BREAK_DETAIL = /^audit chain break at id (\d{1,16})$/;
/** PROPOSED: a `429` that names no `Retry-After`. */
const LIMIT_FALLBACK_S = 60;
/** The passing ranges kept: far more than a session's runs (30 an hour, `22`). */
const MAX_PASSES = 64;

export interface PassedRange {
  readonly fromId: number;
  readonly toId: number;
  readonly checkedAt: string;
}

/** A run's `verified: false`, its served fields as served. */
export interface FailedRun {
  readonly firstBadId: number | null;
  readonly checkedAt: string;
  readonly fromId: number | null;
  readonly toId: number | null;
  readonly lastHash: string | null;
  readonly anchorHash: string;
  readonly entriesChecked: number;
}

/** The served `audit_chain_break` incident while it stands. */
export interface BreakIncident {
  readonly id: string;
  readonly status: "open" | "acknowledged";
  readonly firstSeenAt: string;
  readonly lastSeenAt: string;
  /** The entry the incident's text names ("audit chain break at id <n>"), if it names one. */
  readonly entryId: number | null;
  readonly detail: string | null;
}

/** Run tamper check's last state (AL-11, AL-12). */
export type CheckState =
  | { readonly kind: "idle" }
  | { readonly kind: "running" }
  | { readonly kind: "passed"; readonly range: PassedRange }
  | { readonly kind: "empty" }
  | { readonly kind: "broken"; readonly run: FailedRun }
  | { readonly kind: "busy" }
  | { readonly kind: "limited"; readonly until: number }
  | { readonly kind: "stopped"; readonly retryAt: number }
  | { readonly kind: "stopped_entry" }
  | { readonly kind: "read_only" }
  | { readonly kind: "view_as"; readonly code: string | null }
  | { readonly kind: "refused"; readonly status: number; readonly code: string | null }
  | { readonly kind: "unknown" };

export interface IntegrityState {
  /** Passing ranges this session, newest first. */
  readonly passes: readonly PassedRange[];
  /** The session's FAILED episode. */
  readonly failed: FailedRun | null;
  readonly incident: BreakIncident | null;
  /** The last incident read: `unavailable` keeps the last `incident` (AL-10). */
  readonly incidentRead: "idle" | "ok" | "unavailable";
  /** An incident read has answered since the last run that found a break (the banner waits). */
  readonly incidentSettled: boolean;
  readonly check: CheckState;
  /** The episodes' voices already spoken (D11: the banner's `role="alert"` mounts once each). */
  readonly spoken: readonly string[];
  /** An Owner's `403 forbidden` withdrew the area: nothing more is asked. */
  readonly denied: { readonly refId: string | undefined } | null;
}

export interface IntegrityDeps extends AuditTimers {
  readonly now: () => number;
  /** The document whose visibility pauses the incident read; `null` reads it as visible. */
  readonly document: Document | null;
  readonly readIncidents: (signal: AbortSignal) => Promise<AuditAnswer<IncidentPageBody>>;
  readonly verify: () => Promise<AuditAnswer<VerifyResult>>;
  /** The session views as another user (#1134); false until the shell has a source. */
  readonly viewAs?: (() => boolean) | undefined;
}

export interface IntegrityStore {
  readonly getState: () => IntegrityState;
  readonly subscribe: (listener: () => void) => () => void;
  /**
   * SCR-135 holds the incident read while mounted; "My activity" (`own`) reads nothing (BQ-4).
   * `viewAs` is the holding page's view-as source, read while it holds.
   */
  readonly hold: (view?: AuditView, viewAs?: () => boolean) => () => void;
  /** Run tamper check: false while one runs, after a `429` until `Retry-After`, or withdrawn. */
  readonly runCheck: () => boolean;
  /** The episode's banner has spoken. */
  readonly markSpoken: (voice: string) => void;
  /** Tests only: back to the first state, every read and timer stopped. */
  readonly reset: () => void;
}

const INITIAL: IntegrityState = Object.freeze<IntegrityState>({
  passes: [],
  failed: null,
  incident: null,
  incidentRead: "idle",
  incidentSettled: true,
  check: { kind: "idle" },
  spoken: [],
  denied: null,
});

/** The standing `audit_chain_break` incident in a read, the latest seen if more than one. */
function breakIncidentOf(items: readonly Incident[]): BreakIncident | null {
  let found: Incident | null = null;
  for (const item of items) {
    if (item.component !== CHAIN_BREAK_COMPONENT) continue;
    if (!CHAIN_BREAK_TITLE.test(item.title ?? "")) continue;
    if (item.status !== "open" && item.status !== "acknowledged") continue;
    if (found === null || Date.parse(item.last_seen_at) > Date.parse(found.last_seen_at)) {
      found = item;
    }
  }
  if (found === null || found.status === "resolved") return null;
  const named = CHAIN_BREAK_DETAIL.exec(found.detail ?? "")?.[1];
  const entryId = named === undefined ? null : Number(named);
  return {
    id: found.id,
    status: found.status,
    firstSeenAt: found.first_seen_at,
    lastSeenAt: found.last_seen_at,
    entryId: entryId !== null && Number.isSafeInteger(entryId) ? entryId : null,
    detail: found.detail ?? null,
  };
}

export function createIntegrityStore(deps: IntegrityDeps): IntegrityStore {
  /** The holding page's view-as source, else the deps' (BQ-9). */
  let holderViewAs: (() => boolean) | null = null;
  const viewAs = (): boolean => (holderViewAs ?? deps.viewAs)?.() === true;
  let state: IntegrityState = INITIAL;
  const listeners = new Set<() => void>();
  let holds = 0;
  let watching = false;
  let controller: AbortController | null = null;
  let timer: unknown = null;
  let checkTimer: unknown = null;
  let answeredAt: number | null = null;

  const visible = (): boolean => deps.document?.visibilityState !== "hidden";
  const due = (): boolean => answeredAt === null || deps.now() - answeredAt >= INCIDENT_POLL_MS;
  /** A read is owed at once: its 60 s are up, or a break waits for its incident (A-1135P2-09). */
  const owed = (): boolean => due() || !state.incidentSettled;

  function patch(next: Partial<IntegrityState>): void {
    state = { ...state, ...next };
    for (const listener of [...listeners]) listener();
  }
  function stopReads(): void {
    if (timer !== null) deps.clearTimeout(timer);
    timer = null;
    if (watching) deps.document?.removeEventListener("visibilitychange", onVisibility);
    watching = false;
    controller?.abort();
    controller = null;
  }
  function withdraw(answer: AuditRefusal): void {
    stopReads();
    patch({ denied: { refId: answer.refId } });
  }
  const withdrawn = (answer: AuditAnswer<unknown>): answer is AuditRefusal =>
    answer.kind === "refused" && forbiddenMeaning(answer, { viewAs: viewAs() }) === "withdrawn";

  function schedule(): void {
    if (timer !== null) deps.clearTimeout(timer);
    timer = null;
    if (holds === 0 || state.denied !== null || !visible()) return;
    const wait = answeredAt === null ? 0 : INCIDENT_POLL_MS - (deps.now() - answeredAt);
    timer = deps.setTimeout(
      () => {
        timer = null;
        if (controller === null) read();
        else schedule();
      },
      Math.max(0, wait),
    );
  }

  function settleIncidents(answer: AuditAnswer<IncidentPageBody>): void {
    answeredAt = deps.now();
    if (answer.kind === "ok") {
      const incident = breakIncidentOf(answer.body.items);
      patch({ incident, incidentRead: "ok", incidentSettled: true });
    } else if (withdrawn(answer)) {
      withdraw(answer);
      return;
    } else {
      // the banner keeps its last state (AL-10); a waiting break shows now, its line unknown
      patch({ incidentRead: "unavailable", incidentSettled: true });
    }
    schedule();
  }

  function read(): void {
    if (controller !== null || state.denied !== null) return;
    const c = new AbortController();
    controller = c;
    const land = (answer: AuditAnswer<IncidentPageBody>): void => {
      if (controller !== c) return;
      controller = null;
      settleIncidents(answer);
    };
    void deps.readIncidents(c.signal).then(land, () => land({ kind: "failed", reason: "network" }));
  }

  function onVisibility(): void {
    if (!visible()) {
      if (timer !== null) deps.clearTimeout(timer);
      timer = null;
    } else if (owed()) {
      read();
    } else {
      schedule();
    }
  }

  /**
   * The orchestrator's Q2 (a): a run that finds a break raises its incident
   * (`api/audit_verify.py`), so a held SCR-135 reads the incidents again at once, not on the next
   * 60 s tick, and the halt line never lags the banner. A read already in flight may have been
   * sent before the break was recorded, so it is dropped for the new one. One extra
   * `admin.area_entered` row: the cadence starts again from its answer. A page that let go, and
   * My activity, which never holds the read, read nothing (BQ-4).
   */
  function rereadAfterBreak(): void {
    if (holds === 0 || state.denied !== null) return;
    if (timer !== null) deps.clearTimeout(timer);
    timer = null;
    controller?.abort();
    controller = null;
    read();
  }

  function settleCheck(answer: AuditAnswer<VerifyResult>): void {
    const now = deps.now();
    if (answer.kind === "ok") {
      const r = answer.body;
      if (!r.verified) {
        const run: FailedRun = {
          firstBadId: r.first_bad_id,
          checkedAt: r.checked_at,
          fromId: r.from_id,
          toId: r.to_id,
          lastHash: r.last_hash,
          anchorHash: r.anchor_hash,
          entriesChecked: r.entries_checked,
        };
        patch({ failed: run, check: { kind: "broken", run }, incidentSettled: false });
        rereadAfterBreak();
        return;
      }
      if (r.entries_checked === 0 || r.from_id === null || r.to_id === null) {
        patch({ check: { kind: "empty" } }); // an empty range proves nothing (`22`)
        return;
      }
      const pass: PassedRange = { fromId: r.from_id, toId: r.to_id, checkedAt: r.checked_at };
      // D11: only a later pass from genesis to the head ends the session's FAILED
      const { failed } = state;
      const ends =
        failed !== null &&
        r.anchor_hash === GENESIS_HASH &&
        Date.parse(r.checked_at) > Date.parse(failed.checkedAt);
      patch({
        passes: [pass, ...state.passes].slice(0, MAX_PASSES),
        check: { kind: "passed", range: pass },
        ...(ends ? { failed: null } : {}),
      });
      return;
    }
    if (answer.kind !== "refused") {
      patch({ check: { kind: "unknown" } }); // no answer, or none it could read: it may have run
      return;
    }
    const { status, code } = answer;
    if (status === 409) return patch({ check: { kind: "busy" } });
    if (status === 429) {
      const until = now + (answer.retryAfterS ?? LIMIT_FALLBACK_S) * 1_000;
      patch({ check: { kind: "limited", until } });
      if (checkTimer !== null) deps.clearTimeout(checkTimer);
      checkTimer = deps.setTimeout(() => {
        checkTimer = null;
        if (state.check.kind === "limited") patch({ check: { kind: "idle" } });
      }, until - now);
      return;
    }
    if (status === 503) {
      const retry = answer.retryAfterS;
      return patch({
        check:
          retry === undefined
            ? { kind: "stopped_entry" } // over the entry cap: the only stop without Retry-After
            : { kind: "stopped", retryAt: now + retry * 1_000 },
      });
    }
    const meaning = forbiddenMeaning(answer, { viewAs: viewAs() });
    if (meaning === "withdrawn") withdraw(answer);
    if (meaning === "read_only") return patch({ check: { kind: "read_only" } });
    if (meaning === "view_as") return patch({ check: { kind: "view_as", code } });
    patch({ check: { kind: "refused", status, code } });
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    hold: (view = "raw", source) => {
      if (view === "own") return () => undefined; // `listIncidents` needs `admin:read` (BQ-4)
      holds += 1;
      if (source !== undefined) holderViewAs = source;
      if (!watching && deps.document !== null) {
        deps.document.addEventListener("visibilitychange", onVisibility);
        watching = true;
      }
      if (visible() && owed()) read();
      else schedule();
      let released = false;
      return () => {
        if (released) return;
        released = true;
        holds -= 1;
        queueMicrotask(() => {
          if (holds > 0) return;
          stopReads();
          holderViewAs = null;
        });
      };
    },
    runCheck: () => {
      const { check } = state;
      if (state.denied !== null || check.kind === "running") return false;
      if (check.kind === "limited" && deps.now() < check.until) return false;
      patch({ check: { kind: "running" } });
      // a write the page leaving does not stop: its outcome is the session's (FAILED included)
      void deps.verify().then(settleCheck, () => settleCheck({ kind: "unknown" }));
      return true;
    },
    markSpoken: (voice) => {
      if (!state.spoken.includes(voice)) patch({ spoken: [...state.spoken, voice] });
    },
    reset: () => {
      stopReads();
      if (checkTimer !== null) deps.clearTimeout(checkTimer);
      checkTimer = null;
      holds = 0;
      holderViewAs = null;
      answeredAt = null;
      state = INITIAL;
      for (const listener of [...listeners]) listener();
    },
  };
}

/** The entry of the standing break: the session's run's, else the one the incident names. */
export function breakEntry(state: IntegrityState): number | null {
  return state.failed?.firstBadId ?? state.incident?.entryId ?? null;
}

/** The voice of the standing episode, null when none stands (D11: one voice per episode). */
export function episodeVoice(state: IntegrityState): string | null {
  const n = breakEntry(state);
  if (n !== null) return `break:${n}`;
  if (state.failed !== null) return `run:${state.failed.checkedAt}`;
  return state.incident === null ? null : `incident:${state.incident.id}`;
}

export const isSpoken = (state: IntegrityState, voice: string): boolean =>
  state.spoken.includes(voice);

/** BQ-5 as overridden: the halt's source, the served incident while it is `open`. */
export function haltIncident(state: IntegrityState): BreakIncident | null {
  return state.incident?.status === "open" ? state.incident : null;
}

/** §7's banner: what it says while an episode stands. */
export interface BannerModel {
  readonly voice: string;
  readonly entryId: number | null;
  readonly title: string;
  readonly facts: string | null;
  readonly meaning: string;
  /**
   * The PROPOSED halt sentence while the served incident is open, `tamper.failed.safe` once it is
   * acknowledged, and the PROPOSED "may be halted" while no incident is served.
   */
  readonly safe: string;
  readonly halted: boolean;
  readonly recheck: string;
  readonly steps: string;
  /** [Copy details]: the served fields as served, one `name: value` a line. */
  readonly details: string;
}

const failedTitle = (n: number | null): string =>
  n === null ? COPY.tamper.failed.titleUnknown : COPY.tamper.failed.title(num(n));

export function bannerModel(state: IntegrityState): BannerModel | null {
  const voice = episodeVoice(state);
  if (voice === null) return null;
  // a run's break waits for its incident read: the footer's FAILED line stands in meanwhile
  if (state.incident === null && !state.incidentSettled) return null;
  const n = breakEntry(state);
  const halted = haltIncident(state) !== null;
  const { failed, incident } = state;
  let facts: string | null = null;
  let details = "";
  if (failed !== null) {
    const at = Date.parse(failed.checkedAt);
    if (failed.fromId !== null && failed.toId !== null && Number.isFinite(at)) {
      facts = COPY.tamper.failed.facts(
        utc.hms(at),
        utc.date(at),
        range(failed.fromId, failed.toId),
      );
    }
    details = [
      `first_bad_id: ${failed.firstBadId ?? "null"}`,
      `checked_at: ${failed.checkedAt}`,
      `from_id: ${failed.fromId ?? "null"}`,
      `to_id: ${failed.toId ?? "null"}`,
      `last_hash: ${failed.lastHash ?? "null"}`,
      `anchor_hash: ${failed.anchorHash}`,
    ].join("\n");
  } else if (incident !== null) {
    const at = Date.parse(incident.firstSeenAt);
    if (Number.isFinite(at)) facts = COPY.tamper.failed.factsIncident(utc.hms(at), utc.date(at));
    details = [
      `incident: ${incident.id}`,
      `status: ${incident.status}`,
      `first_seen_at: ${incident.firstSeenAt}`,
      ...(incident.detail === null ? [] : [`detail: ${incident.detail}`]),
    ].join("\n");
  }
  return {
    voice,
    entryId: n,
    title: failedTitle(n),
    facts,
    meaning: COPY.tamper.failed.meaning,
    safe: halted
      ? COPY.tamper.failed.halted
      : incident === null
        ? COPY.tamper.failed.mayBeHalted
        : COPY.tamper.failed.safe,
    halted,
    recheck: COPY.tamper.failed.recheck,
    steps: COPY.tamper.failed.steps,
    details,
  };
}

export interface Line {
  readonly key: string;
  readonly text: string;
}
export interface FooterLine extends Line {
  /** `tamper.failed.title`: the octagon, silent (the banner speaks). */
  readonly failed: boolean;
}
export interface FooterModel {
  readonly line: FooterLine | null;
  /** `tamper.incidents_unavailable` under it, after a failed incident read (AL-10). */
  readonly incidents: Line | null;
}

/**
 * The footer's tamper line, by D04 §4's table: none before a page or on an empty one; FAILED while
 * an episode stands; else the re-read's `newest_partial`, the page's `page_partial` or
 * `page_passed`. "My activity" stays neutral (BQ-4): `page_partial_own` or `page_passed` only.
 */
export function footerModel(
  state: IntegrityState,
  page: Pick<AuditPageBody, "items" | "chain_verified"> | null,
  options: { readonly view: AuditView; readonly newestPartial?: boolean | undefined },
): FooterModel {
  const own = options.view === "own";
  const incidents =
    !own && state.incidentRead === "unavailable"
      ? { key: "tamper.incidents_unavailable", text: COPY.tamper.incidentsUnavailable }
      : null;
  const line = (key: string, text: string, failed = false): FooterModel => ({
    line: { key, text, failed },
    incidents,
  });
  if (page === null || page.items.length === 0) return { line: null, incidents };
  const partial = !page.chain_verified || options.newestPartial === true;
  if (own) {
    return partial
      ? line("tamper.page_partial_own", COPY.tamper.pagePartialOwn)
      : line("tamper.page_passed", COPY.tamper.pagePassed);
  }
  if (episodeVoice(state) !== null) {
    return line("tamper.failed.title", failedTitle(breakEntry(state)), true);
  }
  if (options.newestPartial === true) {
    return line("tamper.newest_partial", COPY.tamper.newestPartial);
  }
  if (!page.chain_verified) return line("tamper.page_partial", COPY.tamper.pagePartial);
  return line("tamper.page_passed", COPY.tamper.pagePassed);
}

export interface RecordLine extends Line {
  readonly tone: "danger" | "neutral";
}

/**
 * SCR-136's integrity line (AD-1, AD-5), by id alone: after the break, a passed range, or none. My
 * activity's stays `rec.not_checked` (BQ-4, AD-7): the session's integrity state is the Owner's
 * (S-1135P2-02).
 */
export function recordLine(
  state: IntegrityState,
  entry: Pick<AuditEntry, "id">,
  view: AuditView = "raw",
): RecordLine {
  if (view === "own") return { key: "rec.not_checked", text: COPY.rec.notChecked, tone: "neutral" };
  const n = breakEntry(state);
  if (n !== null && entry.id >= n) {
    return { key: "rec.after_break", text: COPY.rec.afterBreak(num(n)), tone: "danger" };
  }
  const pass = state.passes.find((p) => p.fromId <= entry.id && entry.id <= p.toId);
  if (pass !== undefined) {
    const at = Date.parse(pass.checkedAt);
    const text = COPY.rec.verifiedTo(range(pass.fromId, pass.toId), utc.hm(at));
    return { key: "rec.verified_to", text, tone: "neutral" };
  }
  return { key: "rec.not_checked", text: COPY.rec.notChecked, tone: "neutral" };
}

/**
 * The footer's check line (AL-11, AL-12): none at rest or after a break (the banner speaks).
 * `viewAsReason` is the view-as sentence (`rbac.view_as` with its user) for `inflight.not_sent`.
 */
export function checkLine(
  state: IntegrityState,
  options: { readonly viewAsReason?: string | undefined } = {},
): Line | null {
  const { check } = state;
  switch (check.kind) {
    case "idle":
    case "broken":
      return null;
    case "running":
      return { key: "tamper.checking", text: COPY.tamper.checking };
    case "passed": {
      const { fromId, toId, checkedAt } = check.range;
      const text = COPY.tamper.rangePassed(range(fromId, toId), utc.hm(Date.parse(checkedAt)));
      return { key: "tamper.range_passed", text };
    }
    case "empty":
      return { key: "tamper.range_empty", text: COPY.tamper.rangeEmpty };
    case "busy":
      return { key: "tamper.busy", text: COPY.tamper.busy };
    case "limited":
      return { key: "tamper.limited", text: COPY.tamper.limited(utc.hm(check.until)) };
    case "stopped":
      return { key: "tamper.stopped", text: COPY.tamper.stopped(utc.hms(check.retryAt)) };
    case "stopped_entry":
      return { key: "tamper.stopped_entry", text: COPY.tamper.stoppedEntry };
    case "read_only":
      return { key: "inflight.read_only", text: COPY.inflight.readOnly };
    case "view_as":
      return { key: "inflight.not_sent", text: COPY.inflight.notSent(options.viewAsReason ?? "") };
    case "refused":
      return { key: "tamper.not_run", text: COPY.tamper.notRun };
    case "unknown":
      return { key: "tamper.no_answer", text: COPY.tamper.noAnswer };
  }
}

/** Same JSON, so a selection that changed nothing keeps its value and its readers stay still. */
const sameJson = (a: unknown, b: unknown): boolean =>
  a === b || JSON.stringify(a) === JSON.stringify(b);

const browserDeps: IntegrityDeps = {
  now: () => Date.now(),
  setTimeout: (run, ms) => globalThis.setTimeout(run, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
  document: typeof document === "undefined" ? null : document,
  readIncidents: (signal) => listIncidents({ signal }),
  verify: () => verifyAuditChain(),
};

/** The session's one integrity store. */
export const auditIntegrity: IntegrityStore = createIntegrityStore(browserDeps);

/**
 * Holds the incident read while the calling view is mounted (SCR-135 only: BQ-4), with the page's
 * view-as state, so a `403 forbidden` under view-as is the target's refusal (BQ-9).
 */
export function useIntegrityHold(
  view: AuditView,
  options: { readonly active?: boolean; readonly viewAs?: boolean } = {},
  store: IntegrityStore = auditIntegrity,
): void {
  const { active = true, viewAs = false } = options;
  const viewing = useRef(viewAs);
  useEffect(() => {
    viewing.current = viewAs;
  }, [viewAs]);
  useEffect(() => {
    if (!active) return undefined;
    return store.hold(view, () => viewing.current);
  }, [view, active, store]);
}

/** A selection from the integrity store, kept while its JSON is unchanged. */
export function useIntegrity<T>(
  selector: (state: IntegrityState) => T,
  store: IntegrityStore = auditIntegrity,
): T {
  const memo = useRef<{ state: IntegrityState; selector: typeof selector; value: T } | null>(null);
  const getSnapshot = (): T => {
    const current = store.getState();
    const last = memo.current;
    if (last !== null && last.state === current && last.selector === selector) return last.value;
    const next = selector(current);
    const value = last !== null && sameJson(last.value, next) ? last.value : next;
    memo.current = { state: current, selector, value };
    return value;
  };
  return useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}
