/**
 * The machine view (E42-S08 §5.2; E42-D05 §11 SI-3 to SI-7): one machine, opened from the list as
 * the route's query state (`?machine=&env=`, wired with R-357 under BQ-1). Its `h2`, [Back to
 * machines], its facts as served, the acknowledge as T2 while the machine is latched (SI-7 "today",
 * BQ-5: the press sends nothing), the chart's drawing beside its text list with the configuration's
 * leaves marked "(current)" (SI-4; the drawing a feature-local SVG under BQ-6), and the event
 * timeline (SI-5). It shows served values only, never a derived state, transition or latch (C-2.19
 * to C-2.22).
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  type CSSProperties,
  type JSX,
} from "react";
import {
  ADMIN_COPY,
  Button,
  ErrorState,
  GatedAnnounceProvider,
  Icon,
  MonoText,
  Skeleton,
} from "@candleviewer/ui";
import { announce, forget } from "../../app-shell/announcer";
import { ChartDiagram } from "./ChartDiagram";
import { layoutOf } from "./chartLayout";
import { currentIds } from "./chartModel";
import { ChartTextList } from "./ChartTextList";
import { INSPECTOR_COPY as COPY } from "./copy";
import { utcTime } from "./format";
import {
  SEAL_FAILED,
  type MachineDetail,
  type MachineRef,
  type StatechartMachine,
} from "./inspectorReads";
import {
  inspector,
  useInspectorSelector,
  useOpenMachine,
  type ChartRead,
  type InspectorStore,
  type MachineState,
} from "./inspectorStore";
import { kindLabel } from "./kinds";
import { Timeline } from "./Timeline";

/** The shell announcer's key for the acknowledge's refused press: said again on every press. */
const ACK_PRESS = "admin:statecharts:ack-press";
const NO_STATES: ReadonlySet<string> = new Set();

const SECTION: CSSProperties = { display: "grid", gap: "var(--space-stack-md)" };
const H2: CSSProperties = {
  margin: 0,
  overflowWrap: "anywhere",
  font: "var(--type-ui-heading-md-font-weight) var(--type-ui-heading-md-font-size) / var(--type-ui-heading-md-line-height) var(--type-ui-heading-md-font-family)",
};
/** Two columns of term and value; at 200 % text each pair wraps under the other. */
const FACTS: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 16rem), 1fr))",
  gap: "var(--space-stack-sm) var(--space-stack-md)",
  margin: 0,
};
const TERM: CSSProperties = { color: "var(--color-text-secondary)" };
const VALUE: CSSProperties = { margin: 0, overflowWrap: "anywhere" };
const LINE: CSSProperties = { margin: 0 };
/** The octagon in `color.status.danger.strong` (D05 §16); the words carry the latch. */
const OCTAGON: CSSProperties = {
  display: "inline-flex",
  verticalAlign: "middle",
  marginInlineEnd: "var(--space-1)",
  color: "var(--color-status-danger-strong)",
};
/** G-T2.2: the reason in `color.text.secondary`, inline under the control (rendering 2a). */
const REASON: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
const ACK: CSSProperties = { display: "grid", gap: "var(--space-1)", justifyItems: "start" };

function Fact({
  term,
  children,
}: {
  readonly term: string;
  readonly children: JSX.Element | string;
}) {
  return (
    <div>
      <dt style={TERM}>{term}</dt>
      <dd style={VALUE}>{children}</dd>
    </div>
  );
}

/** "—", named "not recorded" for assistive technology. */
function NotRecorded(): JSX.Element {
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="cv-visually-hidden">{COPY.notRecorded}</span>
    </>
  );
}

/** The served row's facts, each as served: nothing is derived from another. */
function Facts({
  machine,
  today,
}: {
  readonly machine: StatechartMachine;
  readonly today: number;
}) {
  return (
    <dl style={FACTS}>
      <Fact term={COPY.facts.kind}>{kindLabel(machine.machine_kind)}</Fact>
      <Fact term={COPY.facts.environment}>{ADMIN_COPY.env[machine.environment]}</Fact>
      <Fact term={COPY.facts.state}>{machine.state}</Fact>
      <Fact term={COPY.facts.hash}>
        <>
          <MonoText size="sm">{machine.machine_hash}</MonoText>
          {` · ${machine.lock_matches ? COPY.matches : COPY.differs}`}
        </>
      </Fact>
      <Fact term={COPY.facts.chainTrips}>{String(machine.chain_trips)}</Fact>
      <Fact term={COPY.facts.latched}>
        {machine.degraded ? (
          <>
            <span style={OCTAGON}>
              <Icon name="danger" />
            </span>
            {COPY.latched(machine.chain_trips)}
          </>
        ) : (
          COPY.notLatched
        )}
      </Fact>
      <Fact term={COPY.facts.deferred}>
        {machine.deferred_depth === null ? <NotRecorded /> : String(machine.deferred_depth)}
      </Fact>
      <Fact term={COPY.facts.updated}>{utcTime(Date.parse(machine.updated_at), today)}</Fact>
    </dl>
  );
}

/**
 * [Acknowledge latch…] as T2 (D05 §4.1; G-T2.1 to G-T2.3): CMP-001's own gated button, focusable,
 * `aria-disabled`, the `lock` leading its full label, and described by its reason, shown inline
 * under it from mount (rendering 2a). Its name names the machine. A press, Enter or Space changes
 * nothing and sends nothing; the reason is said once per press, politely, through the shell's
 * announcer (the surface owns the gated announcement, #5135).
 */
function Acknowledge({ machine }: { readonly machine: string }): JSX.Element {
  const reasonId = useId();
  const say = useCallback((reason: string): void => {
    forget(ACK_PRESS);
    announce("polite", reason, ACK_PRESS);
  }, []);
  return (
    <div style={ACK}>
      <GatedAnnounceProvider announce={say}>
        <Button variant="danger" disabledReason={COPY.ackNotBuilt} disabledReasonId={reasonId}>
          {COPY.view.acknowledge}
          {/* The name reads "… on {machine}…" in one text run: no engine parts it from its "…". */}
          <span className="cv-visually-hidden">
            {COPY.view.acknowledgeOn(machine)}
            {COPY.view.ellipsis}
          </span>
          <span aria-hidden="true">{COPY.view.ellipsis}</span>
        </Button>
      </GatedAnnounceProvider>
      <p id={reasonId} style={REASON}>
        {COPY.ackNotBuilt}
      </p>
    </div>
  );
}

const NO_IDS: readonly string[] = [];

/**
 * The chart's drawing beside its text list, or why it is not shown. The configuration's leaves read
 * "(current)" only while the export's hash is the machine's; otherwise a redeploy raced the read,
 * so neither marks a current state and [Re-read] is offered (§4.4, MUST-12). A chart over the
 * drawing's bounds is the text list alone, with its line (§4.3).
 */
function Chart({
  read,
  machine,
  configuration,
  store,
}: {
  readonly read: ChartRead;
  readonly machine: StatechartMachine;
  readonly configuration: readonly string[];
  readonly store: InspectorStore;
}): JSX.Element {
  const listId = useId();
  const chart = read.phase === "ok" ? read.chart : undefined;
  const same = chart?.machine_hash === machine.machine_hash;
  const current = useMemo(
    () => (chart !== undefined && same ? currentIds(chart.model, configuration) : NO_STATES),
    [chart, same, configuration],
  );
  if (chart === undefined) {
    return read.phase === "unusable" ? (
      <ErrorState
        form="inline"
        live="off"
        message={COPY.view.chartUnavailable}
        retry={{ label: COPY.view.retry, onClick: () => store.retry("chart") }}
      />
    ) : (
      <div aria-busy="true">
        <Skeleton shape="text" count={3} />
      </div>
    );
  }
  return (
    <div style={SECTION}>
      {same ? null : (
        <p style={LINE}>
          {COPY.view.chartChanged}{" "}
          <Button size="sm" onClick={() => store.reread()}>
            {COPY.view.reread}
          </Button>
        </p>
      )}
      {layoutOf(chart.model) === null ? (
        <>
          <p style={LINE}>{COPY.chart.tooLarge}</p>
          <ChartTextList model={chart.model} current={current} id={listId} />
        </>
      ) : (
        <div className="cv-inspector-chart">
          <ChartDiagram model={chart.model} current={current} listId={listId} />
          <ChartTextList model={chart.model} current={current} id={listId} />
        </div>
      )}
    </div>
  );
}

/** The timeline, or why it has no rows: the events slice not read, or no event recorded yet. */
function Events({
  detail,
  root,
  today,
}: {
  readonly detail: MachineDetail;
  readonly root: string;
  readonly today: number;
}): JSX.Element {
  if (detail.events?.status !== "ok") return <p style={LINE}>{COPY.view.eventsUnavailable}</p>;
  const events = detail.recent_events ?? [];
  if (events.length === 0) return <p style={LINE}>{COPY.view.eventsNone}</p>;
  return <Timeline events={events} root={root} today={today} />;
}

/** What the store served for the machine, state by state (§5.2's table). */
function Body({
  view,
  store,
}: {
  readonly view: MachineState;
  readonly store: InspectorStore;
}): JSX.Element {
  if (view.phase === "not_found") return <p style={LINE}>{COPY.view.notFound}</p>;
  if (view.phase === "not_built") return <p style={LINE}>{COPY.view.notBuilt}</p>;
  // A failed re-read keeps the last detail shown under its line; a first one has only the line.
  const failed =
    view.phase === "failed" ? (
      <ErrorState
        form="inline"
        live="off"
        message={COPY.view.failed}
        retry={{ label: COPY.view.retry, onClick: () => store.retry("machine") }}
      />
    ) : null;
  const detail = view.detail;
  const machine = detail?.snapshots.status === "ok" ? detail.machine : undefined;
  if (detail === undefined || machine === undefined) {
    const sealed = detail?.snapshots.status === "error" && detail.snapshots.detail === SEAL_FAILED;
    return (
      <>
        {failed}
        {detail === undefined ? null : (
          <p style={LINE}>{sealed ? COPY.sealFailed : COPY.unreadable}</p>
        )}
      </>
    );
  }
  const today = view.answeredAt ?? Date.parse(machine.updated_at);
  return (
    <>
      {failed}
      <Facts machine={machine} today={today} />
      {machine.degraded ? <Acknowledge machine={machine.machine_key} /> : null}
      {view.chart === null ? null : (
        <Chart
          read={view.chart}
          machine={machine}
          configuration={detail.configuration ?? NO_IDS}
          store={store}
        />
      )}
      <Events detail={detail} root={machine.machine_kind} today={today} />
    </>
  );
}

export interface MachineViewProps {
  /** The machine, vetted by `machineRef` from the query state's `machine` and `env`. */
  readonly machine: MachineRef;
  /** [Back to machines]: the page removes the query state and returns focus to the row. */
  readonly onBack: () => void;
  /** Moves focus to the view's `h2` as it opens: a row's Enter opened it (D05 §11 keys). */
  readonly focusOnOpen?: boolean;
  readonly store?: InspectorStore;
}

/**
 * An in-page section named by its `h2`, "{machine} · {ENV}". It opens the machine in the store
 * while mounted (its detail, then its chart) and is busy until the first answer. The Tab order:
 * [Back to machines], [Acknowledge latch…] when latched, the diagram's region while it scrolls,
 * then the timeline; the text list is browse-order text, not a stop.
 */
export function MachineView({
  machine,
  onBack,
  focusOnOpen = false,
  store = inspector,
}: MachineViewProps): JSX.Element | null {
  useOpenMachine(machine, store);
  const view = useInspectorSelector((s) => s.machine, store);
  const denied = useInspectorSelector((s) => s.denied !== null, store);
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const { key, env } = machine;
  useEffect(() => {
    if (focusOnOpen) heading.current?.focus();
  }, [focusOnOpen, key, env]);
  // A withdrawn area: its page (SCR-154 N-2) replaces this one, which shows nothing it read.
  if (denied) return null;
  const shown = view.ref?.key === key && view.ref.env === env && view.phase !== "idle";
  return (
    <section aria-labelledby={headingId} aria-busy={shown ? undefined : true} style={SECTION}>
      <h2 id={headingId} ref={heading} tabIndex={-1} style={H2}>
        {COPY.view.heading(key, ADMIN_COPY.env[env])}
      </h2>
      <div>
        <Button onClick={onBack}>{COPY.view.back}</Button>
      </div>
      {shown ? <Body view={view} store={store} /> : <Skeleton shape="text" count={4} />}
    </section>
  );
}
