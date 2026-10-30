/**
 * SCR-048's engine half (E11-S02 PR4; E11-D04 §12, E11-D06 D19): a `<Chart>` with its error
 * states. The restoring strip overlays the held last frame; a card replaces the pane stack (kept
 * laid out, `visibility: hidden` + `inert`) and never covers the toolbar or status row outside it.
 * Retry remounts the chart (a key bump): its unmount disposes the old engine, then the new one
 * probes again; no engine surface is added. Announcements go through one polite region, once each;
 * the card's alert is CMP-027's own region; focus is never moved to a card (`05` §3.4 item 3)
 * unless it was inside the panes the card hides: then it goes to the card's first stop, never
 * `<body>`. On close it returns to where it was, else to the named chart region (E11-S13's plot
 * stop refines that later). A `RECREATE_KEYS` recreate (a symbol change, §12.4) clears the error.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
  type Ref,
} from "react";
import type { ChartEvents } from "@candleviewer/chart-engine";
import { Button, Callout, CopyButton, ErrorState } from "@candleviewer/ui";
import { Chart, RECREATE_KEYS, type ChartProps } from "../../chart";
import { THEME_ANALYTICS_EVENT } from "../../shell/bootstrap/themeStore";
import { CHART_ERROR_COPY as COPY } from "./copy";
import { chartErrorReducer, INITIAL, isCard, type ChartErrorState } from "./state";

const OVERLAY: CSSProperties = { position: "absolute", top: 0, left: 0, right: 0 };
const CARD: CSSProperties = {
  position: "absolute",
  inset: 0,
  overflow: "auto",
  padding: "var(--space-inset-md)",
  background: "var(--color-surface-raised)",
  // E11-D04 §12.1's 4 px rule: no border-width token is that wide (`border.thick` is 2).
  borderLeft: "4px solid var(--color-status-danger-strong)",
};
const ROW: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-inset-sm)",
};
/** The selectable reference chip: wraps, never truncated (E11-D04 §12.3). */
const CHIP: CSSProperties = {
  fontFamily: "var(--font-family-mono)",
  color: "var(--color-text-primary)",
  background: "var(--color-surface-sunken)",
  padding: "var(--space-inset-xs)",
  overflowWrap: "anywhere",
  userSelect: "text",
};

/** An engine-local reference until SCR-046's `errors[].ref` exists (E11-D04 §12.3, §23 G-1). */
export const mintRef = (): string => `urn:cv:ui:${crypto.randomUUID()}`;

type Said = { readonly text: string; readonly n: number };

/** The sentence a transition says once, politely; null when it says nothing. */
function sayOnEntry(prev: ChartErrorState, next: ChartErrorState): string | null {
  if (next.kind === "restoring" && prev.kind !== "restoring") return COPY.strip.announce;
  if (next.kind === "restored" && prev.kind !== "restored") return COPY.restored;
  if (isCard(next) && isCard(prev) && next.retry === "failed" && prev.retry !== "failed")
    return next.kind === "no-webgl2" ? COPY.noWebgl2.retryFailed : COPY.stopped.retryFailed;
  return null;
}

type FrameProfile = ChartEvents["frameStats"]["renderProfile"];

/** `chart.error_shown` once per card (E11-D04 D14) on the app's seam, `cv:analytics` on `window`. */
function reportShown(
  state: Extract<ChartErrorState, { ref: string }>,
  profile: FrameProfile | null,
) {
  const detail = {
    name: "chart.error_shown",
    code: state.code,
    correlationId: state.ref,
    kind: "engine",
    recoverable: state.recoverable,
    attempt: 0,
    nextRetryMs: null,
    renderProfile: state.kind === "no-webgl2" ? "degraded-2d" : profile,
  };
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
}

export type ChartErrorSurfaceProps = ChartProps & {
  /** For the host (SCR-030) to size the surface. */
  readonly className?: string;
  readonly style?: CSSProperties;
};

export function ChartErrorSurface({
  onError,
  onFrameStats,
  className,
  style,
  ...chart
}: ChartErrorSurfaceProps): JSX.Element {
  const [state, dispatch] = useReducer(chartErrorReducer, INITIAL);
  const [generation, setGeneration] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [said, setSaid] = useState<Said>({ text: "", n: 0 });
  const prev = useRef(state);
  const region = useRef<HTMLDivElement>(null);
  const stack = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const profile = useRef<FrameProfile | null>(null);
  const card = isCard(state);

  const recreateKey = JSON.stringify(RECREATE_KEYS.map((k) => chart.options[k] ?? null));
  const lastKey = useRef(recreateKey);
  useEffect(() => {
    if (lastKey.current === recreateKey) return;
    lastKey.current = recreateKey;
    dispatch({ type: "reset" });
  }, [recreateKey]);

  const handleError = useCallback(
    (error: ChartEvents["error"]) => {
      const t = Date.now();
      setNow(t);
      dispatch({ type: "error", error, now: t, ref: mintRef() });
      onError?.(error);
    },
    [onError],
  );
  const handleStats = useCallback(
    (stats: ChartEvents["frameStats"]) => {
      profile.current = stats.renderProfile;
      dispatch({ type: "frame", profile: stats.renderProfile });
      onFrameStats?.(stats);
    },
    [onFrameStats],
  );

  // A layout effect: focus is read before the browser can drop it from the hidden panes.
  useLayoutEffect(() => {
    const was = prev.current;
    prev.current = state;
    const text = sayOnEntry(was, state);
    const active = document.activeElement;
    if (isCard(state) && !isCard(was)) {
      opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
      if (active !== null && stack.current?.contains(active) === true)
        cardRef.current?.querySelector("button")?.focus();
      reportShown(state, profile.current);
    }
    stack.current?.toggleAttribute("inert", card);
    // A card that closed under the user's focus hands it back, never to `<body>`.
    if (!card && isCard(was)) {
      if (active === null || active === document.body)
        (opener.current?.isConnected === true ? opener.current : region.current)?.focus();
      opener.current = null;
    }
    if (text !== null) setSaid((s) => ({ text, n: s.n + 1 }));
  }, [state, card]);

  // The 1 Hz countdown: a text swap with no live region, stopped on restore, failure or unmount.
  const counting = state.kind === "restoring" && state.nextAt !== null;
  useEffect(() => {
    if (!counting) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [counting, state]);

  return (
    <div
      ref={region}
      role="region"
      aria-label={chart.label}
      tabIndex={-1}
      className={className}
      style={{ position: "relative", ...style }}
      data-chart-error={state.kind}
    >
      <div ref={stack} style={card ? { visibility: "hidden" } : undefined}>
        <Chart key={generation} {...chart} onError={handleError} onFrameStats={handleStats} />
      </div>
      {state.kind === "restoring" ? (
        <div style={OVERLAY}>
          <Callout tone="warning" placement="band" live="off" title={COPY.strip.title}>
            {state.nextAt === null
              ? undefined
              : COPY.strip.body(
                  state.attempt,
                  state.maxAttempts,
                  // Never "in 0 s", never more than the event's wait.
                  Math.max(1, Math.ceil(Math.min(state.nextAt - now, state.nextTryMs ?? 0) / 1000)),
                )}
          </Callout>
        </div>
      ) : null}
      {card ? (
        <ErrorCard
          cardRef={cardRef}
          state={state}
          onRetry={() => {
            dispatch({ type: "retry" });
            setGeneration((g) => g + 1);
          }}
          onContinue={() => dispatch({ type: "continue" })}
        />
      ) : null}
      <div role="status" aria-live="polite" aria-atomic="true" className="cv-visually-hidden">
        {said.text === "" ? null : <span key={said.n}>{said.text}</span>}
      </div>
    </div>
  );
}

type CardProps = {
  readonly cardRef: Ref<HTMLDivElement>;
  readonly state: Extract<ChartErrorState, { ref: string }>;
  readonly onRetry: () => void;
  readonly onContinue: () => void;
};

/**
 * CMP-027's panel (role="alert" once, filled after mount), then the actions (so `Retry` is the
 * first Tab stop, E11-D04 §12.4), the retry line, and the reference line with CMP-033.
 * SCR-045 / SCR-046 / SCR-118 have no route yet: their actions are omitted, not disabled, until
 * each lands.
 */
function ErrorCard({ cardRef, state, onRetry, onContinue }: CardProps): JSX.Element {
  const webgl = state.kind === "no-webgl2";
  const copy = webgl ? COPY.noWebgl2 : COPY.stopped;
  const body = state.kind === "failed" || webgl ? copy.body : COPY.fatalBody;
  const retryLine =
    state.retry === "failed"
      ? copy.retryFailed
      : state.kind === "failed"
        ? COPY.stopped.retryLine
        : null;
  return (
    <div ref={cardRef} style={CARD} data-cmp="SCR-048">
      <ErrorState
        severity="error"
        form="panel"
        live="assertive"
        title={copy.heading}
        message={body}
      />
      <div style={ROW}>
        {webgl ? (
          <>
            <Button variant="primary" onClick={onContinue}>
              {COPY.noWebgl2.continue}
            </Button>
            <Button variant="secondary" onClick={onRetry}>
              {COPY.noWebgl2.retry}
            </Button>
          </>
        ) : (
          <Button variant="primary" onClick={onRetry}>
            {COPY.stopped.retry}
          </Button>
        )}
      </div>
      {retryLine === null ? null : <p>{retryLine}</p>}
      <div style={ROW}>
        <code style={CHIP}>{COPY.referenceLine(state.code, state.ref)}</code>
        <CopyButton value={state.ref} label={COPY.copyReference} />
      </div>
    </div>
  );
}
