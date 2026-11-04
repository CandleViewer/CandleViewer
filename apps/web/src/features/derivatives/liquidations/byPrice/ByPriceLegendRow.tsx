// E24-S07 (#782) slice 2: the recorded layer's legend row (CMP-199 row, D03 S54-56; BQ 11), the one place the layer's
// state is said: the label with its window, "Not available to rules", the K01 sentence as its tooltip (CMP-016,
// `describes`), then one state line:
// - loading; failed with Retry (CMP-199 "history unavailable · Retry"); refused (BQ 7: nothing drawn); stale;
// - partial: #780's partial-coverage chip ("since 09:14 UTC", a neutral CMP-011 Tag until CMP-239 `partial` exists)
//   and its sentence, with no day phrase in the label: never a full-day claim (BQ 5);
// - not recorded: D02 §6's sentence, never "no liquidations"; recorded but empty: the PROPOSED sentence.
// The estimated word is drawn iff the answer's flag is true (BQ 7); for (b) it never is (BQ 8).
// TODO(#5747): the word becomes CMP-227 EstimatedBadge once it merges; the (a) follow-up owns its drawer link.
// The swatch (`color.profile.bar`) comes with the plot attach (slice 3, #534): no DOM token carries it yet.
import type { JSX } from "react";
import { Button, Tag, Tooltip } from "@candleviewer/ui";
import * as copy from "./copy";
import type { ByPriceLayer } from "./model";
import type { ByPriceView } from "./useLiquidationsByPrice";

export interface ByPriceLegendRowProps {
  readonly view: ByPriceView;
  /** The reference time for "09:14 UTC" / "21 Oct 09:14 UTC". */
  readonly nowMs: number;
}

function coverageLine(layer: ByPriceLayer, nowMs: number): string | null {
  const c = layer.coverage;
  if (c.kind === "not-recorded")
    return c.firstAvailableMs === null
      ? copy.neverRecorded(layer.symbol)
      : copy.notRecordedBefore(copy.coverageTime(c.firstAvailableMs, nowMs));
  if (c.kind === "partial") return copy.partialSentence(copy.coverageTime(c.fromMs, nowMs));
  if (layer.buckets.length === 0) return copy.noneRecordedSince(copy.coverageTime(c.fromMs, nowMs));
  return null;
}

const time = (ms: number): string => new Date(ms).toISOString().slice(11, 19) + " UTC";

export function ByPriceLegendRow({ view, nowMs }: ByPriceLegendRowProps): JSX.Element | null {
  if (view.phase === "off") return null;
  const { layer } = view;
  const c = layer?.coverage;
  const name = c?.kind === "full" ? `${copy.LAYER_NAME} ${copy.WINDOW_TODAY}` : copy.LAYER_NAME;
  const line =
    view.phase === "loading"
      ? copy.LOADING
      : view.phase === "refused"
        ? copy.REFUSED
        : view.phase === "failed"
          ? copy.RETRY_TITLE
          : layer === null
            ? null
            : coverageLine(layer, nowMs);
  return (
    <li className="cv-liq-by-price__legend" data-cmp="CMP-199">
      <Tooltip content={copy.K01_SENTENCE}>
        {/* CMP-199's rows are its roving stops: the row's name takes focus so the tooltip opens from the keyboard */}
        <button type="button" className="cv-liq-by-price__name">
          {name}
          {layer?.estimated === true ? ` ${copy.ESTIMATED_WORD}` : null}
          {` · ${copy.NOT_FOR_RULES}`}
        </button>
      </Tooltip>
      {c?.kind === "partial" ? (
        <Tag label={copy.sinceChip(copy.coverageTime(c.fromMs, nowMs))} density="compact" />
      ) : null}
      <span role="status" className="cv-liq-by-price__status">
        {view.stale && view.loadedAtMs !== null ? copy.stale(time(view.loadedAtMs)) : null}
      </span>
      {line === null ? null : <p className="cv-liq-by-price__caption">{line}</p>}
      {view.phase === "failed" ? (
        <Button variant="secondary" density="compact" onClick={view.retry}>
          {copy.RETRY}
        </Button>
      ) : null}
    </li>
  );
}
