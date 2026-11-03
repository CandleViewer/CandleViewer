/**
 * The E42-S08 statechart inspector at R-357 `/admin/statecharts` (E42-D05 §11 SI-1, SI-2; BQ-1 as
 * ruled): an owner-only admin page inside CMP-087, reached by its URL (nothing links to it yet).
 * Top to bottom (D05:746-752, board 09): CMP-088's `h1`, its "as of" line and [Re-read]; the kind
 * counters (CMP-049), a line per latched kind that has no rows; the danger banner while any
 * machine is latched; and the machine grid (CMP-049).
 *
 * It shows served values only (C-2.19 to C-2.22): every state, count and latch is the server's;
 * nothing is derived but words, and no interpreter is asked anything. Reads run on entry, on
 * [Re-read] and on a Retry, never on a timer (BQ-7). The page owns no live
 * region: its lines are said once, politely, through the shell's announcer, behind any other
 * writer's last line; "as of", rows and re-reads are never said, a recovery once. It measures one render (`cv_admin_statecharts_render_ms`, E42-Q03) and reports
 * `empty_state_shown`, nothing else.
 */
import {
  memo,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
} from "react";
import {
  ADMIN_COPY,
  Button,
  Callout,
  EmptyState,
  ErrorState,
  Icon,
  PageHeader,
} from "@candleviewer/ui";
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";
import { announce, forget, lastWrittenAt, REGION_BUDGET_MS } from "../../app-shell/announcer";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { hms, timeOf } from "../overview/tileModels";
import { AdminDenied } from "../shell/AdminDenied";
import { INSPECTOR_COPY } from "./copy";
import {
  SEAL_FAILED,
  type MachineList,
  type StatechartKindSummary,
  type StatechartMachine,
} from "./inspectorReads";
import {
  inspector,
  useInspectorHold,
  useInspectorSelector,
  type InspectorState,
  type InspectorStore,
  type ListState,
} from "./inspectorStore";
import { isRowless, kindLabel } from "./kinds";
import { KindCounters } from "./KindCounters";
import { MachineGrid, type GridEmpty } from "./MachineGrid";

const COPY = INSPECTOR_COPY;

/**
 * The page's screen id: PROPOSED, the `14` owner's to assign (BQ-1). The admin band's two free
 * slots, SCR-138 and SCR-139, are held for security screens (`14` §0.2), so neither is taken here.
 * The ruling replaces this one value and `14`'s heading.
 */
export const INSPECTOR_SCREEN = "SCR-PROPOSED";

/** The render budget's measure, read by E42-Q03 without a transport (plan §10). */
export const RENDER_MEASURE = "cv_admin_statecharts_render_ms";
/** `empty_state_shown`'s surface (`14` §11's reusable empty state). */
export const EMPTY_SURFACE = "admin.statecharts";
/** Every announcer key this page writes starts with this. */
const KEY = "admin:statecharts:";
const DAY_MS = 86_400_000;

/**
 * The page is its own stacking context, so the tables' sticky headers (`z-index: 1`) stay under the
 * shell's canvas overlays, SCR-159's offline page among them (A-1137-01). The kit-wide
 * `.cv-table { isolation: isolate }` comes with E42-S02's PR A; once it lands this is redundant.
 * Its one track never grows past the canvas: a long served name wraps in its cell, and the tables
 * stack at 400 % (A-1137-d07).
 */
const PAGE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr)",
  gap: "var(--space-stack-lg)",
  isolation: "isolate",
};
const SECTION: CSSProperties = { display: "grid", gap: "var(--space-stack-sm)" };
const H2: CSSProperties = {
  margin: 0,
  font: "var(--type-ui-heading-sm-font-weight) var(--type-ui-heading-sm-font-size) / var(--type-ui-heading-sm-line-height) var(--type-ui-heading-sm-font-family)",
};
const LINE: CSSProperties = { margin: 0 };
const NOTE: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
/** The octagon in `color.status.danger.strong` (D05 §16); the words carry the latch. */
const OCTAGON: CSSProperties = {
  display: "inline-flex",
  verticalAlign: "middle",
  marginInlineEnd: "var(--space-1)",
  color: "var(--color-status-danger-strong)",
};

const selectData = (s: InspectorState): MachineList | undefined => s.list.data;
const selectPhase = (s: InspectorState): ListState["phase"] => s.list.phase;
const selectInFlight = (s: InspectorState): boolean => s.list.inFlight;
const selectAnsweredAt = (s: InspectorState): number | undefined => s.list.answeredAt;
const selectDenied = (s: InspectorState): InspectorState["denied"] => s.denied;

/** What the list shows, from the store's served answer (§5.1's state table). */
type View =
  | { readonly kind: "loading" }
  | { readonly kind: "not_built" }
  /** The first read failed: CMP-049's error with Retry. */
  | { readonly kind: "failed" }
  /** `snapshots` unavailable, or an error other than a failed seal (today's deployed state). */
  | { readonly kind: "unreadable" }
  /** `snapshots` ok and nothing at all running. */
  | { readonly kind: "empty" }
  | {
      readonly kind: "list";
      readonly data: MachineList;
      /** A snapshot's seal failed: its machine is left out (`machine.seal_failed`). */
      readonly sealFailed: boolean;
      /** A re-read failed: the rows shown are the last good answer's. */
      readonly stale: boolean;
    };

function viewOf(phase: ListState["phase"], data: MachineList | undefined): View {
  if (phase === "not_built") return { kind: "not_built" };
  if (data === undefined) return phase === "failed" ? { kind: "failed" } : { kind: "loading" };
  const { snapshots } = data;
  const sealFailed = snapshots.status === "error" && snapshots.detail === SEAL_FAILED;
  if (snapshots.status !== "ok" && !sealFailed) return { kind: "unreadable" };
  if (snapshots.status === "ok" && data.kinds.length === 0 && data.items.length === 0) {
    return { kind: "empty" };
  }
  return { kind: "list", data, sealFailed, stale: phase === "failed" };
}

/** What the page's lines need besides the view. */
interface LineState {
  /** A read is in flight: a failure's line is forgotten until it answers. */
  readonly inFlight: boolean;
  /** A good read came after a failed one: the recovery is said (D05 §13 "recovery"). */
  readonly recovered: boolean;
}

/**
 * The lines the page says once, politely: each by its key while its condition holds, so a key is
 * forgotten only when its condition ends, never while rows are read.
 */
function linesOf(view: View, { inFlight, recovered }: LineState): (readonly [string, string])[] {
  const lines: (readonly [string, string])[] = [];
  // A failed read is said once per failure: a Retry or Re-read in flight forgets it (CMP-049's rule).
  const failed = view.kind === "failed" || (view.kind === "list" && view.stale);
  if (failed && !inFlight) lines.push(["failed", COPY.list.failed]);
  if (view.kind === "not_built") lines.push(["not_built", COPY.list.notBuilt]);
  if (view.kind === "unreadable") lines.push(["unreadable", COPY.unreadable]);
  if (view.kind === "empty") lines.push(["empty", COPY.list.empty]);
  if (view.kind !== "list") return lines;
  // A recovery first: it answers the user's own Retry.
  if (recovered) lines.push(["loaded", COPY.list.loaded]);
  if (view.sealFailed) lines.push(["seal_failed", COPY.sealFailed]);
  if (view.data.metrics.status !== "ok") {
    lines.push(["metrics", COPY.list.metricsUnavailable(metricsDetail(view.data))]);
  }
  return lines;
}

const metricsDetail = (data: MachineList): string => data.metrics.detail ?? COPY.list.notReceived;

/** What one visit said and has still to say. */
interface Visit {
  readonly said: Set<string>;
  waiting: (readonly [string, string])[];
  timer: ReturnType<typeof setTimeout> | null;
  /** The polite region's last write when the timer was armed: nobody wrote since, the wait is spent. */
  armedFor: number | null;
}

/**
 * Says each line once, politely, through the shell's announcer (the page owns no live region): a
 * line waits until the polite region has been quiet a whole budget, whoever wrote last (E17-D02
 * §11), as the strip's lines do. A line whose condition ends is forgotten, so its return is said
 * again; leaving the page drops what waits and forgets every key it said. The budget wait is the
 * strip's own (`features/admin/shell/useStripAnnouncements.ts`, its `sayNext` and `armedFor`):
 * change the two together, and give it one home when a third writer needs it.
 */
function usePoliteLines(lines: readonly (readonly [string, string])[]): void {
  const visit = useRef<Visit>({ said: new Set(), waiting: [], timer: null, armedFor: null });
  const sayNext = useCallback((v: Visit): void => {
    v.timer = null;
    const next = v.waiting[0];
    if (next === undefined) return;
    const last = lastWrittenAt("polite");
    const wait =
      last === v.armedFor ? 0 : Math.min(last + REGION_BUDGET_MS - Date.now(), REGION_BUDGET_MS);
    if (wait > 0) {
      v.armedFor = last;
      v.timer = setTimeout(() => sayNext(v), wait);
      return;
    }
    v.waiting.shift();
    announce("polite", next[1], `${KEY}${next[0]}`);
    v.said.add(next[0]);
    sayNext(v);
  }, []);
  useEffect(() => {
    const v = visit.current;
    const now = new Map(lines);
    for (const key of [...v.said]) {
      if (now.has(key)) continue;
      forget(`${KEY}${key}`);
      v.said.delete(key);
    }
    // What waits is what the lines hold and was not said yet, in the lines' own order: a line that
    // comes a render later (a recovery's, set in an effect) still goes before the ones after it.
    v.waiting = lines.filter(([key]) => !v.said.has(key));
    if (v.timer === null) sayNext(v);
  }, [lines, sayNext]);
  useEffect(() => {
    const v = visit.current;
    return () => {
      if (v.timer !== null) clearTimeout(v.timer);
      v.timer = null;
      v.waiting = [];
      for (const key of v.said) forget(`${KEY}${key}`);
      v.said.clear();
    };
  }, []);
}

const report = (detail: Readonly<Record<string, unknown>>): void => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

/** `empty_state_shown` once per entry into an empty state (`14` §11): none running, or unreadable. */
function useEmptyReport(view: View): void {
  const reason =
    view.kind === "empty" ? "no_snapshots" : view.kind === "unreadable" ? "unreadable" : null;
  const reported = useRef<string | null>(null);
  useEffect(() => {
    // StrictMode's rehearsal keeps the ref: one entry, one event.
    if (reason !== null && reported.current !== reason) {
      report({ name: "empty_state_shown", surface: EMPTY_SURFACE, reason });
    }
    reported.current = reason;
  }, [reason]);
}

/**
 * One `performance.measure` from the mount to the first list answer drawn, in any outcome. A visit
 * that found the list answered waited for nothing, so it measures nothing (as SCR-120's does).
 */
function useRenderBudget(answered: boolean): void {
  const start = useRef<number | null>(null);
  const done = useRef(false);
  const answeredAtMount = useRef(answered);
  useEffect(() => {
    if (start.current !== null) return; // StrictMode runs this twice: one visit, one measure
    start.current = performance.now();
    if (answeredAtMount.current) done.current = true;
  }, []);
  useEffect(() => {
    if (!answered || done.current || start.current === null) return;
    done.current = true;
    try {
      performance.measure(RENDER_MEASURE, { start: start.current, end: performance.now() });
    } catch {
      // A runtime without User Timing Level 3 measures nothing.
    }
  }, [answered]);
}

/** Whether the list's last answer read after a failed one: true until the next failure. */
function useRecovered(phase: ListState["phase"]): boolean {
  const [recovered, setRecovered] = useState(false);
  const last = useRef(phase);
  useEffect(() => {
    if (phase === "failed") setRecovered(false);
    else if (phase === "ok" && last.current === "failed") setRecovered(true);
    last.current = phase;
  }, [phase]);
  return recovered;
}

/** A latched kind with no rows (B8, B9, B13, B15): its line, never a row (`machine.rowless`). */
const RowlessLines = memo(function RowlessLines({
  kinds,
}: {
  readonly kinds: readonly StatechartKindSummary[];
}): JSX.Element | null {
  const latched = kinds.filter((k) => isRowless(k.machine_kind) && k.degraded_machines > 0);
  if (latched.length === 0) return null;
  return (
    <div>
      {latched.map((k) => (
        <p key={`${k.machine_kind}@${k.environment}`} style={LINE}>
          <span style={OCTAGON}>
            <Icon name="danger" />
          </span>
          {COPY.list.rowless(
            `${kindLabel(k.machine_kind)} · ${ADMIN_COPY.env[k.environment]}`,
            k.degraded_machines,
          )}
        </p>
      ))}
    </div>
  );
});

const NO_MACHINES: readonly StatechartMachine[] = [];
const NO_KINDS: readonly StatechartKindSummary[] = [];

export interface InspectorPageProps {
  readonly store?: InspectorStore;
}

export function InspectorPage({ store = inspector }: InspectorPageProps = {}): JSX.Element {
  useInspectorHold(store);
  const data = useInspectorSelector(selectData, store);
  const phase = useInspectorSelector(selectPhase, store);
  const inFlight = useInspectorSelector(selectInFlight, store);
  const answeredAt = useInspectorSelector(selectAnsweredAt, store);
  const denied = useInspectorSelector(selectDenied, store);
  const recovered = useRecovered(phase);
  const view = useMemo(() => viewOf(phase, data), [phase, data]);
  const lines = useMemo(() => linesOf(view, { inFlight, recovered }), [view, inFlight, recovered]);
  usePoliteLines(lines);
  useEmptyReport(view);
  useRenderBudget(phase !== "idle");

  const machinesHeading = useRef<HTMLHeadingElement>(null);
  const kindsId = useId();
  const machinesId = useId();

  // A Retry goes as its read succeeds: focus waits on the section's heading, never on the document,
  // and the recovery is said once (`loaded`; A-1137-02).
  const retryList = useCallback(() => {
    machinesHeading.current?.focus();
    store.retry("list");
  }, [store]);
  const listError = useMemo(() => ({ message: COPY.list.failed, onRetry: retryList }), [retryList]);

  if (denied !== null) return <AdminDenied refId={denied.refId} />;

  const asOf = data === undefined ? undefined : (timeOf(data.snapshots.generated_at) ?? answeredAt);
  const today = Math.floor((answeredAt ?? 0) / DAY_MS) * DAY_MS;
  const kinds = data?.kinds ?? NO_KINDS;
  const metricsOk = data?.metrics.status === "ok";
  const empty: GridEmpty = kinds.length > 0 ? "no_rows_rowless" : "no_rows";

  let body: JSX.Element;
  // Under the `h1` with no section of their own: an `h2`, never a skipped level (`05` §8.2).
  if (view.kind === "not_built") body = <EmptyState title={COPY.list.notBuilt} headingLevel={2} />;
  else if (view.kind === "unreadable")
    body = <ErrorState form="panel" live="off" message={COPY.unreadable} />;
  else if (view.kind === "empty") body = <EmptyState title={COPY.list.empty} headingLevel={2} />;
  else {
    const list = view.kind === "list" ? view : null;
    body = (
      <>
        {view.kind === "failed" ? null : (
          <section aria-labelledby={kindsId} style={SECTION}>
            <h2 id={kindsId} style={H2}>
              {COPY.list.kindsHeading}
            </h2>
            {list !== null && !metricsOk ? (
              <p style={NOTE}>{COPY.list.metricsUnavailable(metricsDetail(list.data))}</p>
            ) : null}
            <KindCounters kinds={kinds} metricsOk={metricsOk} loading={list === null} />
            <RowlessLines kinds={kinds} />
          </section>
        )}
        {kinds.some((k) => k.degraded_machines > 0) ? (
          <Callout tone="danger" live="off" title={COPY.list.latchedEffect} />
        ) : null}
        <section aria-labelledby={machinesId} style={SECTION}>
          <h2 id={machinesId} ref={machinesHeading} tabIndex={-1} style={H2}>
            {COPY.list.machinesHeading}
          </h2>
          {list?.stale === true ? (
            <ErrorState
              form="inline"
              live="off"
              message={COPY.list.failed}
              retry={{ label: COPY.view.retry, onClick: retryList }}
            />
          ) : null}
          {list?.sealFailed === true ? (
            <ErrorState form="inline" live="off" message={COPY.sealFailed} />
          ) : null}
          {list?.data.meta.has_more === true ? <p style={NOTE}>{COPY.list.more}</p> : null}
          <MachineGrid
            machines={list !== null ? list.data.items : NO_MACHINES}
            loading={view.kind === "loading"}
            error={view.kind === "failed" ? listError : undefined}
            empty={empty}
            today={today}
          />
        </section>
      </>
    );
  }

  return (
    <ScreenRoot>
      <div style={PAGE} data-scr={INSPECTOR_SCREEN}>
        <PageHeader
          title={COPY.page.title}
          meta={asOf === undefined ? COPY.page.utc : COPY.page.asOf(hms(asOf))}
          actions={
            <Button onClick={() => store.reread()} loading={inFlight}>
              {COPY.view.reread}
            </Button>
          }
        />
        {body}
      </div>
    </ScreenRoot>
  );
}
