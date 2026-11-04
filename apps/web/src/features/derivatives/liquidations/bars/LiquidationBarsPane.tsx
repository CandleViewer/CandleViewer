// E24-S06 (#781): the liquidation bars' sub-pane part of SCR-054 (CMP-186): the legend (side words, the threshold
// line, the boundary label), the controls (`bars | heatmap`, the minimum notional), the crosshair readout, the states
// and the table alternative. The state model is the product here: a bar with no recorded data reads "not recorded",
// never 0 (the story's trap), and the boundary label comes from `first_available_ts`.
// TODO(#534): the plot (the split histogram, shorts above the zero tick and longs below, magnitudes on both halves of
// the USDT axis, the 1 px boundary rule over it) needs the engine's `histogram` series with per-bar style words
// (sign x weight, up/down tips, hatch): one G-row on #534 (E12-S08) covers #781 and #777. This ticket adds no canvas
// host and edits no packages/chart-engine; until then the pane has the table and the labels, and the boundary is
// its label. The host keeps the pane dark behind the composition guard's `derivatives` row.
// TODO(#781 slice 3): analytics for threshold / mode changes and the boundary-render counter.
// TODO(#780, #534): not here, owned elsewhere: the boundary's 1 px rule and its label over the plot (#534's engine
// series, with this pane's `data-cv-boundary` label as its text twin); the partial chip, the `Recording settings
// for {symbol}…` route (and its T2 sentence form) and "Live liquidations are streaming now." are #780's feed states
// (SCR-054's mount, slice 3 of #780), not repeated per sub-pane.
import { useId, useState, type JSX, type KeyboardEvent } from "react";
import {
  Button,
  EmptyState,
  FreshnessMarker,
  SegmentedControl,
  Skeleton,
  TextInput,
} from "@candleviewer/ui";
import type { LiqCoverage } from "../history";
import { coverageTime, notional2 } from "../ui/format";
import "../ui/liquidationPane.css";
import { BarsTable, TABLE_ROWS } from "./BarsTable";
import * as copy from "./copy";
import { barTime, intervalLabel } from "./format";
import { SIDE_GLYPHS, SIDE_WORDS, type LiquidatedSide } from "../side";
import { BARS_FILTER_SERVER_SIDE } from "./barsRead";
import { barAt, boundaryOf, DEFAULT_WINDOW_BARS, type Boundary } from "./model";
import { parseThreshold, type LiqBarSettings, type LiqMode } from "./settings";
import type { LiqBarsView } from "./useLiquidationBars";

export type BarsCoverage =
  | { readonly kind: "loading" }
  | { readonly kind: "failed"; readonly onRetry: () => void }
  | { readonly kind: "ok"; readonly coverage: LiqCoverage };

export interface LiquidationBarsPaneProps {
  readonly symbol: string;
  readonly view: LiqBarsView;
  /** #780's single coverage read (BQ-2); this pane makes none. */
  readonly coverage: BarsCoverage;
  readonly settings: LiqBarSettings;
  /**
   * The feed's own applied `min_notional_usd` (#780's `snapshot.minNotionalUsd`), or `null` for none. The legend's
   * "feed ≥ X" is this value, never the setting's: it claims only what is applied (BQ-1).
   */
  readonly feedMinNotionalUsd: string | null;
  readonly onSettingsChange: (patch: Partial<LiqBarSettings>) => void;
  /** The chart crosshair's time, epoch ms, or `null`. */
  readonly crosshairMs?: number | null | undefined;
  /** Wall-clock epoch ms for "today" in a time label. */
  readonly nowMs: number;
}

const MODES: readonly LiqMode[] = ["bars", "heatmap"];

function Controls({
  settings,
  onSettingsChange,
}: Pick<LiquidationBarsPaneProps, "settings" | "onSettingsChange">): JSX.Element {
  const id = useId();
  const [draft, setDraft] = useState(settings.minNotionalUsd);
  const [invalid, setInvalid] = useState(false);
  const [seen, setSeen] = useState(settings.minNotionalUsd);
  if (seen !== settings.minNotionalUsd) {
    // the setting changed from outside (a reset, the server's value): the field shows it
    setSeen(settings.minNotionalUsd);
    setDraft(settings.minNotionalUsd);
    setInvalid(false);
  }
  const commit = (): void => {
    const value = parseThreshold(draft);
    setInvalid(value === null);
    if (value !== null && value !== settings.minNotionalUsd)
      onSettingsChange({ minNotionalUsd: value });
  };
  return (
    <span className="cv-liq-pane__controls">
      <SegmentedControl
        aria-label={copy.MODE_NAME}
        size="sm"
        density="compact"
        options={[
          { value: "bars", label: copy.MODE_BARS },
          { value: "heatmap", label: copy.MODE_HEATMAP },
        ]}
        value={settings.mode}
        onChange={(v) => {
          const mode = MODES.find((m) => m === v);
          if (mode !== undefined) onSettingsChange({ mode });
        }}
      />
      <label htmlFor={id} className="cv-liq-pane__caption">
        {copy.THRESHOLD_LABEL}
      </label>
      <TextInput
        id={id}
        inputMode="decimal"
        density="compact"
        value={draft}
        invalid={invalid}
        errorMessage={copy.THRESHOLD_INVALID}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
          if (e.key === "Enter") commit();
        }}
      />
    </span>
  );
}

/** The side word with its glyph: the glyph is drawn beside the word, never read (D03 §6.1). */
function Side({ side }: { side: LiquidatedSide }): JSX.Element {
  return (
    <>
      {SIDE_WORDS[side]}{" "}
      <span className="cv-liq-side__glyph" aria-hidden="true">
        {SIDE_GLYPHS[side]}
      </span>
    </>
  );
}

function boundaryNode(b: Boundary, symbol: string, nowMs: number): JSX.Element | null {
  const when = (ms: number): string => coverageTime(ms, nowMs);
  if (b.kind === "in-view") {
    return (
      <p className="cv-liq-pane__caption" data-cv-boundary>
        {copy.recordedFrom(when(b.atMs))}
      </p>
    );
  }
  if (b.kind === "before") {
    return (
      <EmptyState
        variant="recording-not-started"
        title={copy.notRecordedBefore(when(b.atMs))}
        headingLevel={4}
      />
    );
  }
  return b.kind === "never" ? (
    <EmptyState
      variant="recording-not-started"
      title={copy.neverRecorded(symbol)}
      headingLevel={4}
    />
  ) : null;
}

export function LiquidationBarsPane({
  symbol,
  view,
  coverage,
  settings,
  feedMinNotionalUsd,
  onSettingsChange,
  crosshairMs = null,
  nowMs,
}: LiquidationBarsPaneProps): JSX.Element {
  const { window, intervalMs } = view;
  const [said, setSaid] = useState("");
  const interval = intervalMs === null ? "" : intervalLabel(intervalMs);
  // a 422 is "not computed yet" only by its detail: #5341's router also refuses an unlisted symbol with a 422
  const notComputed =
    view.error?.status === 422 && (view.error.detail ?? "").startsWith(copy.NOT_COMPUTED_DETAIL);
  const retryBand = (retry: () => void): JSX.Element => (
    <div className="cv-liq-pane__retry">
      <Button
        variant="secondary"
        size="sm"
        density="compact"
        aria-label={copy.RETRY_NAME}
        onClick={retry}
      >
        {copy.RETRY}
      </Button>
      {view.loadedAtMs === null ? null : (
        <p className="cv-liq-pane__caption">{copy.lastLoaded(view.loadedAtMs)}</p>
      )}
    </div>
  );

  // the table's lines never outlive their table: a state status or another mode drops them, so they never replay
  const [saidFor, setSaidFor] = useState(settings.mode);
  if (saidFor !== settings.mode) {
    setSaidFor(settings.mode);
    if (said !== "") setSaid("");
  }
  // ONE status node per pane, always mounted, so its changes are announced once: the loading, stale and retry
  // sentences live here (visible for a failure, visually hidden otherwise), and nothing else carries `role="status"`
  let status = "";
  let statusVisible = false;
  let body: JSX.Element | null;
  if (settings.mode === "heatmap") {
    body = <p className="cv-liq-pane__caption">{copy.HEATMAP_PENDING}</p>;
  } else if (view.phase === "failed") {
    status = notComputed ? copy.NOT_COMPUTED : copy.RETRY_TITLE;
    statusVisible = true;
    body = notComputed ? null : retryBand(view.retry);
  } else if (coverage.kind === "failed") {
    // no coverage, no zero: bars are not classified without it (D03 S54-50)
    status = copy.COVERAGE_FAILED;
    statusVisible = true;
    body = retryBand(coverage.onRetry);
  } else if (
    view.phase === "loading" ||
    coverage.kind === "loading" ||
    window === null ||
    intervalMs === null
  ) {
    status = view.phase === "ready" ? copy.COVERAGE_PENDING : copy.LOADING;
    body = (
      <div className="cv-liq-pane__loading" aria-busy="true">
        <Skeleton shape="row" count={3} />
      </div>
    );
  } else {
    if (view.stale && view.loadedAtMs !== null) status = copy.stale(view.loadedAtMs);
    const boundary = boundaryOf(coverage.coverage, window.fromMs, window.toMs);
    const stateless = boundary.kind === "before" || boundary.kind === "never";
    const at = crosshairMs === null ? null : barAt(view.bars, crosshairMs, intervalMs);
    const ref = view.bars.at(-1)?.tMs ?? nowMs;
    const readTime = at === null ? "" : barTime(at.tMs, ref, intervalMs);
    // the line states the filter the FEED has (BQ-1); the bars are unfiltered until #723
    const filter =
      feedMinNotionalUsd === null
        ? null
        : copy.filterLine(feedMinNotionalUsd, BARS_FILTER_SERVER_SIDE);
    body = (
      <>
        <p className="cv-liq-pane__caption">
          <Side side="short" /> above · <Side side="long" /> below
        </p>
        {filter === null ? null : <p className="cv-liq-pane__caption">{filter}</p>}
        {window.bars < DEFAULT_WINDOW_BARS ? (
          <p className="cv-liq-pane__caption">{copy.windowLimited(window.bars)}</p>
        ) : null}
        {view.bars.length > TABLE_ROWS ? (
          <p className="cv-liq-pane__caption">{copy.newestOf(TABLE_ROWS, view.bars.length)}</p>
        ) : null}
        {boundaryNode(boundary, symbol, nowMs)}
        {at === null ? null : (
          <p className="cv-liq-pane__caption" aria-live="off">
            {at.state === "unknown" || at.long === null || at.short === null ? (
              copy.readoutUnknown(readTime)
            ) : (
              <>
                {readTime} · <Side side="long" /> {notional2(at.long)} USDT · <Side side="short" />{" "}
                {notional2(at.short)} USDT
              </>
            )}
          </p>
        )}
        {view.malformed > 0 ? (
          <p className="cv-liq-pane__caption">{copy.MALFORMED(view.malformed)}</p>
        ) : null}
        {stateless ? null : (
          <BarsTable
            symbol={symbol}
            interval={interval}
            intervalMs={intervalMs}
            bars={view.bars}
            emptyState={<EmptyState title={copy.NO_BARS} headingLevel={4} />}
            announce={setSaid}
          />
        )}
      </>
    );
  }

  if (status !== "" && said !== "") setSaid(""); // a state sentence replaces the table's line for good

  return (
    <section className="cv-liq-pane" aria-label={copy.regionName(symbol)}>
      <div className="cv-liq-pane__toolbar">
        <h3 className="cv-liq-pane__title">{copy.BARS_LABEL}</h3>
        {view.stale && view.loadedAtMs !== null && settings.mode === "bars" ? (
          // the status node below says it once; the chip is its visual twin
          <span aria-hidden="true">
            <FreshnessMarker
              presentation="compact"
              state="stale"
              label={copy.stale(view.loadedAtMs)}
            />
          </span>
        ) : null}
        <Controls settings={settings} onSettingsChange={onSettingsChange} />
      </div>
      <p
        role="status"
        className={
          statusVisible ? "cv-liq-pane__retry-title cv-liq-pane__caption" : "cv-visually-hidden"
        }
      >
        {status === "" ? said : status}
      </p>
      {body}
    </section>
  );
}
