/**
 * SCR-047's block (E11-D04 §11; E16-D05 §4) and its SCR-151 panel instance (§5), a leaf the pane composes (BQ-01):
 * CMP-026 in DOM only, no canvas, no engine (AC 7). Loading is CMP-029 under `aria-busy`; a failed coverage read is CMP-026 `error` with Retry (BQ-06 (a));
 * the Owner's CTA navigates to SCR-140 (BQ-03 (a)), others read the sentence form (T2-13 / T2-14). Once per entry the
 * status region says "{heading} {cause}" (D05-D15) and analytics fire (D05-D13).
 */
import { useEffect, useLayoutEffect, useRef, useState, type JSX, type RefObject } from "react";
import {
  EmptyState,
  Icon,
  SkeletonChart,
  formatRbacReason,
  type EmptyStateActions,
} from "@candleviewer/ui";
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import { COVERAGE_ERROR, LABEL, LIVE, RECORD_VERB } from "./copy";
import { missingSentence, type GapInterval } from "./gaps";
import {
  chartAnalytics,
  entryKey,
  emptyView,
  recordHref,
  type ActionId,
  type ChartState,
  type ViewWords,
} from "./model";

/** The live topics' state (E17-D01 F13) as the pane's connection reads it. */
export type LiveState = "live" | "delayed" | "stale" | "disconnected";

export interface ChartEmptyStateProps {
  readonly state: ChartState;
  readonly live: LiveState;
  /** The pressed control; `href` is the registry's SCR-140 path for the Owner's CTA — the host navigates. */
  readonly onAction: (id: ActionId, href: string | null) => void;
  readonly onRetry: () => void;
  /** A SCR-151 panel's `surface` (E08-D10); omitted on the chart pane. Its `empty_state_shown` is carried. */
  readonly surface?: string;
  /**
   * FM-16: where focus goes when the first bar ends 1a / 1b while the block held it (the chart's toolbar). Ordering
   * it after the first-bar announcement is the host's: it unmounts the block once it has spoken.
   */
  readonly returnFocusTo?: RefObject<HTMLElement | null>;
  readonly report?: Report;
}

export type Report = (detail: Readonly<Record<string, unknown>>) => void;
/** The app's analytics seam, `cv:analytics` on `window` (D05-D13): enums and public symbols only, no audit. */
const dispatchAnalytics: Report = (detail) => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

const LIVE_WORDS: Readonly<Record<LiveState, string | null>> = { ...LIVE, stale: null };
const LIVE_INK = { color: "var(--color-data-confidence-live-indicator)", display: "inline-flex" };

export function ChartEmptyState(props: ChartEmptyStateProps): JSX.Element | null {
  const { state } = props;
  if (state.kind === "loading")
    return (
      <div className="cv-chart-empty" aria-busy="true" data-state="loading">
        <SkeletonChart />
      </div>
    );
  if (state.kind === "coverage-error")
    return (
      <div className="cv-chart-empty" data-state="coverage-error">
        <EmptyState
          variant="error"
          title={COVERAGE_ERROR}
          actions={[{ label: LABEL.retry, onClick: props.onRetry, variant: "secondary" }]}
        />
      </div>
    );
  if (state.kind !== "empty") return null;
  return <EmptyBlock {...props} state={state} />;
}

function EmptyBlock({
  state,
  live,
  onAction,
  surface,
  returnFocusTo,
  report = dispatchAnalytics,
}: ChartEmptyStateProps & { readonly state: Extract<ChartState, { kind: "empty" }> }): JSX.Element {
  const words: ViewWords = {
    ownerOnly: formatRbacReason("rbac.owner_only", { verb: RECORD_VERB }),
    viewAs: (user) => formatRbacReason("rbac.view_as", { user }),
    panel: surface !== undefined,
  };
  const view = emptyView(state, words);
  const key = entryKey(state);
  const [said, setSaid] = useState("");
  const block = useRef<HTMLDivElement>(null);
  const focusTo = useRef({ reason: state.reason, returnFocusTo });
  focusTo.current = { reason: state.reason, returnFocusTo };

  const entry = useRef({
    text: "",
    event: null as Readonly<Record<string, unknown>> | null,
    report,
  });
  entry.current = {
    text: `${view.heading} ${view.description}`,
    event:
      surface === undefined ? { name: "chart.empty_state_shown", ...chartAnalytics(state) } : null,
    report,
  };
  // Once per entry, keyed by `key`: the announcement after mount (the region is pre-rendered empty, `05` :150) and
  // the event (D05-D13); a re-render of the same entry says nothing.
  useEffect(() => {
    setSaid(entry.current.text);
    if (entry.current.event !== null) entry.current.report(entry.current.event);
  }, [key]);

  // FM-16, on unmount only (a reason change while mounted moves no focus, `05` :96): the first bar ends 1a / 1b (the
  // host unmounts the block) while focus is inside → the toolbar. Read before the node leaves the document.
  useLayoutEffect(() => {
    const node = block.current;
    return () => {
      const { reason, returnFocusTo: to } = focusTo.current;
      const held = node?.contains(document.activeElement) === true;
      if (held && (reason === "1a" || reason === "1b")) to?.current?.focus();
    };
  }, []);

  const press = (id: ActionId) => (): void =>
    onAction(id, id === "record" ? (recordHref() ?? null) : null);
  // The first action is the CMP-001 primary, except `Learn more` and the restricted frame's "no CTA, no ask" (D05 :225).
  const lead = state.frame !== "role-restricted";
  const list = view.actions.map((a, i) => ({
    label: a.label,
    onClick: press(a.id),
    variant:
      lead && i === 0 && a.id !== "learn_more" ? ("primary" as const) : ("secondary" as const),
  }));
  const [first, second] = list;
  const actions: EmptyStateActions | undefined =
    first === undefined ? undefined : second === undefined ? [first] : [first, second];
  const sentence = view.live ? LIVE_WORDS[live] : null;
  return (
    <div ref={block} className="cv-chart-empty" data-state="empty" data-frame={state.frame}>
      <EmptyState
        variant={view.variant}
        icon={view.glyph}
        title={view.heading}
        description={view.description}
        {...(actions === undefined ? {} : { actions })}
        {...(view.link === null ? {} : { link: { label: view.link.label, href: view.link.href } })}
      />
      {sentence === null ? null : (
        <p className="cv-chart-empty__live">
          {/* E17-D02 §5's live glyph and ink (D05 :94); a neutral glyph for the other states */}
          <span style={live === "live" ? LIVE_INK : undefined}>
            <Icon name={live === "live" ? "check" : "info"} />
          </span>
          {sentence}
        </p>
      )}
      <span className="cv-visually-hidden" role="status">
        {said}
      </span>
    </div>
  );
}

/**
 * The chart region's accessible description (D05 §8; D06 C-x): the band is never a tab stop, so the gaps in view are
 * text here, every range with its short cause (G-09: no cut-off yet), never announced (E12-D02 :288–290). A failed
 * coverage read says it could not load, never "no gaps" (BQ-06 (a), D05-CG1).
 */
export function ChartGapDescription(p: {
  /** The host's `aria-describedby` target on the chart region. */
  readonly id: string;
  readonly gaps: readonly GapInterval[];
  readonly coverageKnown: boolean;
}): JSX.Element {
  // The merged `symbol-info` `COVERAGE_FAILED` words, "Couldn't load recorded coverage." (BQ-06 (a): the nearest).
  const text = p.coverageKnown ? missingSentence(p.gaps) : COVERAGE_ERROR;
  return (
    <p id={p.id} className="cv-visually-hidden" data-carrier="gaps">
      {text ?? ""}
    </p>
  );
}
