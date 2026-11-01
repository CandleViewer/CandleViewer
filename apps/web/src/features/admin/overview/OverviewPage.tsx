/**
 * SCR-120 Admin home / overview at `/admin` (E42-S01; E42-D03 §6): CMP-088's "Overview" and its
 * "as of" line, then nine CMP-178 tiles in three bands. Each tile resolves on its own read (D8), so
 * none waits for another; while the page is visible the overview's slices are re-read every 30 s,
 * the other reads once per entry and on Retry (BQ-5 as ruled for #5330). Client telemetry is the
 * app's analytics seam and one `performance.measure`, no transport of its own (BQ-8, CG-25).
 */
import { useEffect, useRef, type CSSProperties, type JSX } from "react";
import { PageHeader } from "@candleviewer/ui";
import { THEME_ANALYTICS_EVENT } from "../../../shell/bootstrap/themeStore";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { OVERVIEW_COPY as COPY } from "./copy";
import { OverviewTile } from "./OverviewTile";
import { useAdminHold, useAdminSelector, type AdminReadState } from "./readStore";
import { allAnswered, BANDS, hms, PAGE_READS, timeOf } from "./tileModels";

/** The render budget's measure (`14` SCR-120: ≤ 800 ms), read by E42-Q03 without a transport. */
export const RENDER_MEASURE = "cv_admin_overview_render_ms";

/**
 * Three tiles a row at both sizes (D1: about 307 px at 1280, 675 px at 2560), `space.3` gaps bound as
 * `space.stack.md` (board 10 row H); at 200 % text or zoom the track's minimum takes the whole row,
 * so the grid reflows to one tile per row (§13). A band's tiles share one height (the grid's stretch).
 */
const GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 18rem), 1fr))",
  gap: "var(--space-stack-md)",
};
const BANDS_STYLE: CSSProperties = { display: "grid", gap: "var(--space-stack-md)" };
const BAND: CSSProperties = { display: "grid", gap: "var(--space-stack-sm)" };
/** Board 10 row H: the band's `h2` in `type.ui.heading-sm`, `color.text.secondary`, drawn in capitals. */
const H2: CSSProperties = {
  margin: 0,
  color: "var(--color-text-secondary)",
  font: "var(--type-ui-heading-sm-font-weight) var(--type-ui-heading-sm-font-size) / var(--type-ui-heading-sm-line-height) var(--type-ui-heading-sm-font-family)",
  textTransform: "uppercase",
};

const report = (detail: Readonly<Record<string, unknown>>): void => {
  window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
};

/** The page's "as of": the overview's own `generated_at`, else the time its answer came. */
const pageAsOf = (s: AdminReadState): number | undefined =>
  timeOf(s.overview.data?.generated_at) ?? s.overview.okAt;

/**
 * `admin.overview_viewed` once per visit, and once every read has answered (a tile in any state),
 * `admin.overview_rendered {ms}` with the matching `performance.measure`. A visit that found every
 * read answered (a return within the area) waited for nothing, so it measures nothing (C-5330-02).
 */
function useRenderBudget(answered: boolean): void {
  const start = useRef<number | null>(null);
  const done = useRef(false);
  const answeredAtMount = useRef(answered);
  useEffect(() => {
    if (start.current !== null) return; // StrictMode runs this twice: one visit, one event
    start.current = performance.now();
    report({ name: "admin.overview_viewed" });
    if (answeredAtMount.current) done.current = true;
  }, []);
  useEffect(() => {
    if (!answered || done.current || start.current === null) return;
    done.current = true;
    const end = performance.now();
    const ms = Math.round(end - start.current);
    try {
      performance.measure(RENDER_MEASURE, { start: start.current, end });
    } catch {
      // A runtime without User Timing Level 3 keeps the analytics event alone.
    }
    report({ name: "admin.overview_rendered", ms });
  }, [answered]);
}

export function OverviewPage(): JSX.Element {
  useAdminHold(PAGE_READS);
  const answered = useAdminSelector(allAnswered);
  const asOf = useAdminSelector(pageAsOf);
  useRenderBudget(answered);
  return (
    <ScreenRoot>
      <PageHeader title={COPY.title} meta={asOf === undefined ? undefined : COPY.meta(hms(asOf))} />
      <div style={BANDS_STYLE}>
        {BANDS.map((band, i) => (
          <div key={COPY.bands[i]} style={BAND}>
            <h2 style={H2}>{COPY.bands[i]}</h2>
            <div style={GRID}>
              {band.map((tile) => (
                <OverviewTile key={tile} tile={tile} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </ScreenRoot>
  );
}
