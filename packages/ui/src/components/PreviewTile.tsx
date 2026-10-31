import { useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, JSX, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { ColorSwatch } from "./ColorSwatch.js";
import { SkeletonChart } from "./SkeletonChart.js";
import { contrastRatio } from "./internal/contrast.js";
import { THEME_CHANGE_EVENT } from "../theme/store.js";

/** The catalogue's kinds plus J21's `scales`, `chart` (E12-D05) and `ladder` (E32-D04). */
export type PreviewTileKind =
  "candles" | "chart" | "footprint" | "heatmap" | "ladder" | "scales" | "theme";
export type PreviewTileSource = "live" | "sample";
/** `ready` draws the image; `empty` and `error` are availability and failure (J21). Never loading. */
export type PreviewTileStatus = "ready" | "empty" | "error";

/** Default English copy (plan gap 9, BQ-21); every string is a prop. */
export const PREVIEW_TILE_COPY = {
  unavailable: "Preview unavailable",
  empty: "Preview unavailable — no bars loaded",
  error: "Preview unavailable — chart error; settings still apply",
  sample: "Sample bars: not this chart",
  contrastWarning: (ratio: string): string =>
    `Low contrast: text on this preview measures ${ratio}:1, below 4.5:1`,
  // Theme sample = a chart cell, a ladder row and a positions row (14-screens-catalogue ~L2435).
  // The numbers are illustrative, not market data.
  themeSample: {
    chart: "Chart sample",
    bid: "Bid 64,210.5",
    ask: "Ask 64,211.0",
    position: "BTCUSDT long 0.500 BTC",
  },
} as const;

/**
 * The pairs the BQ-18 warning measures, each at `min`: the body text (the theme sample, the ladder
 * value) and the secondary text (the empty and error reason) on the tile's own surface. A side the host
 * does not override is read from the frame's computed custom property (the active theme). Only opaque
 * `#RGB` / `#RRGGBB` values are measured: an `rgb()`, `hsl()`, `var()` or alpha value is not checked.
 */
export const PREVIEW_TILE_CONTRAST_PAIRS = {
  pairs: [
    { text: "color.text.primary", surface: "color.surface.sunken" },
    { text: "color.text.secondary", surface: "color.surface.sunken" },
  ],
  min: 4.5,
} as const;

export interface PreviewTileProps {
  readonly kind?: PreviewTileKind;
  /** The configuration in words: the tile's accessible name while it draws ("Preview: BTCUSDT 1 minute, …"). */
  readonly label: string;
  /** `sample` adds the visible "not this chart" line (E12-D05 W-19). */
  readonly source?: PreviewTileSource;
  readonly status?: PreviewTileStatus;
  /** The host's renderer output (a second engine view); its colours are its own. */
  readonly children?: ReactNode;
  /** `ladder` only: one figure, or the five figures of the collapsed form, joined by " · ". */
  readonly value?: string | readonly string[];
  /** The visible "Changes:" line under the tile; read in DOM order, not referenced by the tile. */
  readonly caption?: string;
  /**
   * Token name -> value, applied as scoped custom properties on the tile only (BQ-18):
   * `{ "color.surface.sunken": "#0B0E13" }` sets `--color-surface-sunken`. Invalid names are ignored.
   * Overriding a side of a `PREVIEW_TILE_CONTRAST_PAIRS` pair arms the warning; only opaque hex is measured.
   */
  readonly tokenOverrides?: Readonly<Record<string, string>>;
  readonly emptyText?: string;
  readonly errorText?: string;
  readonly unavailableName?: string;
  readonly sampleText?: string;
  readonly contrastWarning?: (ratio: string) => string;
  readonly themeSample?: {
    readonly chart: string;
    readonly bid: string;
    readonly ask: string;
    readonly position: string;
  };
}

/** `color.text.primary` -> `--color-text-primary`. */
const cssName = (token: string): string => `--${token.replace(/\./g, "-")}`;

const TOKEN_NAME = /^[a-z][a-z0-9-]*(\.[a-z0-9-]+)+$/;

/** The overrides as `--a-b-c` custom properties; a name outside the token grammar is dropped. */
function scopedProperties(overrides: Readonly<Record<string, string>>): CSSProperties {
  const style: Record<string, string> = {};
  for (const [name, value] of Object.entries(overrides)) {
    if (TOKEN_NAME.test(name)) style[cssName(name)] = value;
  }
  return style as CSSProperties;
}

/**
 * The lowest ratio over the pairs with at least one overridden side; the other side is the frame's
 * computed value. `null` when no pair is overridden or no side is an opaque hex.
 */
function overrideRatio(
  frame: HTMLElement,
  overrides: Readonly<Record<string, string>>,
): number | null {
  let computed: CSSStyleDeclaration | null = null;
  const read = (token: string): string => {
    const own = overrides[token];
    if (own !== undefined) return own;
    computed ??= getComputedStyle(frame);
    return computed.getPropertyValue(cssName(token));
  };
  let lowest: number | null = null;
  for (const { text, surface } of PREVIEW_TILE_CONTRAST_PAIRS.pairs) {
    if (overrides[text] === undefined && overrides[surface] === undefined) continue;
    const ratio = contrastRatio(read(text), read(surface));
    if (ratio !== null && (lowest === null || ratio < lowest)) lowest = ratio;
  }
  return lowest;
}

/**
 * CMP-228 PreviewTile: the miniature preview beside a settings form. One `role="img"` named in words,
 * never focusable, never a live region, never the only disclosure. No spinner: a recomputing host keeps
 * its last frame. Empty and error tiles are named "Preview unavailable" and say why in visible text.
 *
 * Named deviation from the catalogue props (`settings: object`, `sampleData?: unknown`, 15-component-catalogue
 * CMP-228): the tile owns no settings behaviour. `settings` is carried as `label`, the configuration in words
 * (the accessible name), and `sampleData` as `children`, the host renderer's image. Nothing else is added.
 */
export function PreviewTile({
  kind = "candles",
  label,
  source = "live",
  status = "ready",
  children,
  value,
  caption,
  tokenOverrides = {},
  emptyText = PREVIEW_TILE_COPY.empty,
  errorText = PREVIEW_TILE_COPY.error,
  unavailableName = PREVIEW_TILE_COPY.unavailable,
  sampleText = PREVIEW_TILE_COPY.sample,
  contrastWarning = PREVIEW_TILE_COPY.contrastWarning,
  themeSample = PREVIEW_TILE_COPY.themeSample,
}: PreviewTileProps): JSX.Element {
  const ready = status === "ready";
  const collapsed = ready && kind === "ladder" && Array.isArray(value);
  const state = ready ? (collapsed ? "collapsed" : source) : status;
  const descriptionId = useId();
  const frameRef = useRef<HTMLDivElement>(null);
  const [ratio, setRatio] = useState<number | null>(null);
  const overrideKey = JSON.stringify(tokenOverrides);
  // Measured after layout so an unoverridden side resolves to the active theme's value.
  // It re-measures when the runtime reports a theme change, so a one-sided override follows the switcher
  // with or without a ThemeProvider (the event is dispatched on `document`).
  useLayoutEffect(() => {
    const measure = (): void => {
      const frame = frameRef.current;
      const overrides = JSON.parse(overrideKey) as Record<string, string>;
      setRatio(frame === null ? null : overrideRatio(frame, overrides));
    };
    measure();
    document.addEventListener(THEME_CHANGE_EVENT, measure);
    return () => document.removeEventListener(THEME_CHANGE_EVENT, measure);
  }, [overrideKey]);
  const warning =
    ready && ratio !== null && ratio < PREVIEW_TILE_CONTRAST_PAIRS.min
      ? contrastWarning(ratio.toFixed(2))
      : null;

  // The host image keeps its own colours under forced colours; the edge and the text do not (CSS).
  let image: ReactNode =
    children === undefined ? undefined : <span className="cv-preview-tile__image">{children}</span>;
  // Content inside a role="img" is not exposed, so the reason and the theme sample are referenced as
  // the image's description: the name stays "Preview unavailable" (J21) and the words still reach AT.
  let description: string | undefined = descriptionId;
  if (status === "empty")
    image = (
      <span className="cv-preview-tile__empty">
        <span className="cv-preview-tile__silhouette">
          <SkeletonChart />
        </span>
        <span id={descriptionId} className="cv-preview-tile__status">
          {emptyText}
        </span>
      </span>
    );
  else if (status === "error")
    image = (
      <span id={descriptionId} className="cv-preview-tile__status">
        <span className="cv-preview-tile__glyph">
          <Icon name="error" />
        </span>
        {errorText}
      </span>
    );
  else if (kind === "ladder" && value !== undefined) {
    // The ladder value is repeated by the normative totals row (E32-D04 D04-A2), not described here.
    description = undefined;
    image = (
      <span className="cv-preview-tile__value">
        {typeof value === "string" ? value : value.join(" · ")}
      </span>
    );
  } else if (kind === "theme" && children === undefined) {
    // One id per row, so the description reads the rows as separate words ("… 64,210.5 Ask …").
    description = ["chart", "bid", "ask", "position"]
      .map((row) => `${descriptionId}-${row}`)
      .join(" ");
    image = (
      <span className="cv-preview-tile__sample">
        <span id={`${descriptionId}-chart`} className="cv-preview-tile__row">
          <span className="cv-preview-tile__candles" aria-hidden="true">
            <span className="cv-preview-tile__candle cv-preview-tile__candle--buy" />
            <span className="cv-preview-tile__candle cv-preview-tile__candle--sell" />
            <span className="cv-preview-tile__candle cv-preview-tile__candle--buy" />
          </span>
          {themeSample.chart}
        </span>
        <span id={`${descriptionId}-bid`} className="cv-preview-tile__row">
          <ColorSwatch decorative color="var(--color-buy-default)" label="" />
          {themeSample.bid}
        </span>
        <span id={`${descriptionId}-ask`} className="cv-preview-tile__row">
          <ColorSwatch decorative color="var(--color-sell-default)" label="" />
          {themeSample.ask}
        </span>
        <span id={`${descriptionId}-position`} className="cv-preview-tile__row">
          {themeSample.position}
        </span>
      </span>
    );
  } else description = undefined;

  return (
    <div className="cv-preview-tile" data-cmp="CMP-228" data-kind={kind} data-state={state}>
      <div
        role="img"
        aria-label={ready ? label : unavailableName}
        aria-describedby={description}
        ref={frameRef}
        aria-live="off"
        className="cv-preview-tile__frame"
        style={scopedProperties(tokenOverrides)}
      >
        {image}
      </div>
      {ready && source === "sample" ? <p className="cv-preview-tile__note">{sampleText}</p> : null}
      {warning !== null ? (
        <p className="cv-preview-tile__note cv-preview-tile__warning">
          <span className="cv-preview-tile__glyph">
            <Icon name="warning" />
          </span>
          {warning}
        </p>
      ) : null}
      {caption !== undefined ? <p className="cv-preview-tile__caption">{caption}</p> : null}
    </div>
  );
}
