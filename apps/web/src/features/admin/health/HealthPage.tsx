/**
 * SCR-143 System health at R-350 (E42-S06; E42-D05 §5): CMP-088's "System health" with its "as of"
 * and [Re-read], the overall and incidents lines, the outage banner, a CMP-178 tile per served
 * component, the clock and the fixed tiles, and the build line. Each tile selects its own model, so
 * a frame that changes one component renders one tile (D5); the reads run on mount and Re-read only
 * (D6). `?component=` opens a component's detail view [BQ-11]. Voice is the shell announcer's, and
 * telemetry is the analytics seam and one `performance.measure`, no transport of its own.
 */
import { memo, useCallback, useEffect, useRef, type CSSProperties, type JSX } from "react";
import { useSearchParams } from "react-router";
import {
  Button,
  Callout,
  FreshnessMarker,
  PageHeader,
  SYSTEM_HEALTH_TILE_COPY,
  SystemHealthTile,
} from "@candleviewer/ui";
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { OVERVIEW_COPY } from "../overview/copy";
import { hms } from "../overview/tileModels";
import { routerLink } from "../routerLink";
import { AdminDenied } from "../shell/AdminDenied";
import { ComponentDetail } from "./ComponentDetail";
import { HEALTH_COPY as COPY } from "./copy";
import { healthStore, useHealthHold, useHealthSelector, type HealthState } from "./healthStore";
import * as tiles from "./tiles";
import { useHealthVoice } from "./voice";

/** The render budget's measure (E42J:215), read by E42-Q03 without a transport. */
export const RENDER_MEASURE = "cv_admin_health_render_ms";

/** D1: three columns at 1280, five at 2560, one at 200 % text (§4.2). */
const GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "repeat(auto-fit, minmax(min(100%, max(18rem, calc((100% - 4 * var(--space-stack-md)) / 5))), 1fr))",
  gap: "var(--space-stack-md)",
};
const STACK: CSSProperties = { display: "grid", gap: "var(--space-stack-md)" };
const LINE: CSSProperties = { margin: 0 };
const PROBE = { valueLabel: COPY.probe, unit: COPY.unit, unitSpoken: COPY.unitSpoken };

const selectDenied = (s: HealthState): HealthState["denied"] => s.denied;
const selectFramesSeenAt = (s: HealthState): number | undefined => s.framesSeenAt;

/**
 * A frame's words' "as of" [BQ-8], the store's one `framesSeenAt`, on a leaf of its own: a frame
 * re-renders this line in each frame-sourced tile, never CMP-178 (C-1084P1-d01). It sits in the
 * tile's children slot, in CMP-178's own "as of" style.
 */
function FramesAsOf(): JSX.Element | null {
  const at = useHealthSelector(selectFramesSeenAt);
  if (at === undefined) return null;
  return <p className="cv-health-tile__meta">{`${SYSTEM_HEALTH_TILE_COPY.asOf} ${hms(at)}`}</p>;
}

/** CMP-178 over a model: the probe line only where the tile has one, CMP-239 when it is stale. */
const Tile = memo(function Tile({ model }: { readonly model: tiles.TileModel }) {
  const { key, anchor, probe, value, staleSince, retry, framesAsOf, ...shown } = model;
  return (
    <div id={anchor}>
      <SystemHealthTile
        {...shown}
        {...(probe ? { ...PROBE, value } : {})}
        linkAs={routerLink}
        headingLevel={2}
        onRetry={retry ? () => healthStore.retry(key) : undefined}
      >
        {staleSince === undefined ? null : (
          <p>
            <FreshnessMarker
              presentation="compact"
              state="stale"
              label={COPY.staleSince(hms(staleSince))}
            />
          </p>
        )}
        {framesAsOf === true ? <FramesAsOf /> : null}
      </SystemHealthTile>
    </div>
  );
});

/** A component's tile selects its own model, so it renders only when that model changes. */
const ComponentTile = memo(function ComponentTile({ name }: { readonly name: string }) {
  const model = useHealthSelector(useCallback((s: HealthState) => tiles.tileOf(name, s), [name]));
  return model === undefined ? null : <Tile model={model} />;
});

const ClockTile = memo(function ClockTile() {
  return <Tile model={useHealthSelector(tiles.clockTile)} />;
});

/** D10's line on its own selector: the frames' time re-renders it alone. */
function OverallLine(): JSX.Element | null {
  const line = useHealthSelector(tiles.overallLine);
  return line === undefined ? null : <p style={LINE}>{line}</p>;
}

/** The page's state lines, over the tiles and over a detail view alike (A-1084P1-d02). */
function StateLines({ lines }: { readonly lines: tiles.PageLines }): JSX.Element {
  const { banner, report } = lines;
  return (
    <>
      <OverallLine />
      {lines.incidents === undefined ? null : <p style={LINE}>{lines.incidents}</p>}
      {report === undefined ? null : (
        <p style={LINE}>
          {report.text}{" "}
          <Button size="sm" loading={report.busy} onClick={() => healthStore.retry("report")}>
            {COPY.retry}
          </Button>
        </p>
      )}
      {lines.probesNotDeployed ? <p style={LINE}>{COPY.probesNotDeployed}</p> : null}
      {banner === undefined ? null : (
        <Callout tone="danger" live="off" title={banner.title}>
          {banner.safe ? SYSTEM_HEALTH_TILE_COPY.stillSafe : undefined}
        </Callout>
      )}
    </>
  );
}

function Grid({ lines }: { readonly lines: tiles.PageLines }): JSX.Element {
  return (
    <div style={STACK}>
      <StateLines lines={lines} />
      <div style={GRID}>
        {lines.names.map((name) => (
          <ComponentTile key={name} name={name} />
        ))}
        <ClockTile />
        {tiles.FIXED_TILES.map((model) => (
          <Tile key={model.key} model={model} />
        ))}
      </div>
      {lines.build === undefined ? null : <p style={LINE}>{lines.build}</p>}
    </div>
  );
}

/** `admin.health_viewed` once per visit; the measure from mount to the report's first answer. */
function useRenderBudget(settled: boolean): void {
  const start = useRef<number | null>(null);
  const done = useRef(false);
  useEffect(() => {
    if (start.current !== null) return; // StrictMode runs this twice: one visit, one event
    start.current = performance.now();
    const detail = { name: "admin.health_viewed" };
    window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
  }, []);
  useEffect(() => {
    if (!settled || done.current || start.current === null) return;
    done.current = true;
    try {
      performance.measure(RENDER_MEASURE, { start: start.current, end: performance.now() });
    } catch {
      // A runtime without User Timing Level 3 keeps the viewed event alone.
    }
  }, [settled]);
}

/**
 * Focus (§4): closing a detail view hands it to that tile's heading link, or to Re-read when no
 * tile has that name (A-1084P1-d03); a report Retry that a good read takes away hands it to Re-read,
 * never to `<body>`.
 */
function useFocusReturns(component: string | null, retry: boolean): void {
  const last = useRef(component);
  const retried = useRef(retry);
  useEffect(() => {
    const was = last.current;
    last.current = component;
    if (was === null || component !== null) return;
    const link = document.getElementById(`health-${was}`)?.querySelector<HTMLElement>("h2 a");
    (link ?? document.querySelector<HTMLElement>("[data-health-reread]"))?.focus();
  }, [component]);
  useEffect(() => {
    const was = retried.current;
    retried.current = retry;
    // Only a Retry the good read took away: the first render's focus is the shell's.
    if (!was || retry || document.activeElement !== document.body) return;
    document.querySelector<HTMLElement>("[data-health-reread]")?.focus();
  }, [retry]);
}

export function HealthPage(): JSX.Element {
  useHealthHold();
  const component = useSearchParams()[0].get("component");
  const denied = useHealthSelector(selectDenied);
  const lines = useHealthSelector(tiles.pageLines);
  useHealthVoice(useHealthSelector(tiles.voiceStates), lines.report);
  useRenderBudget(lines.settled);
  useFocusReturns(component, lines.report !== undefined);
  if (denied !== null) return <AdminDenied refId={denied.refId} />;
  const asOf = lines.asOf === undefined ? COPY.allUtc : OVERVIEW_COPY.meta(hms(lines.asOf));
  const reread = (
    <Button
      size="sm"
      data-health-reread=""
      loading={lines.rereading}
      onClick={() => healthStore.reread()}
    >
      {COPY.reread}
    </Button>
  );
  return (
    <ScreenRoot>
      <PageHeader
        title={COPY.title}
        meta={
          <>
            {asOf} {reread}
          </>
        }
      />
      {component === null ? (
        <Grid lines={lines} />
      ) : (
        <div style={STACK}>
          <StateLines lines={lines} />
          <ComponentDetail name={component} />
        </div>
      )}
    </ScreenRoot>
  );
}
