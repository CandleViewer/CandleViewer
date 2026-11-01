/**
 * CMP-197 ChartTooltip (E11-S07; E11-D02 §7.3, D10): the DOM readout that follows the crosshair.
 * `aria-hidden`: the same values reach assistive technology through the polite announcements and
 * the DOM mirror (AC4), so this never announces. Placed by `transform` only (`placeTooltip`), faded
 * in 100 ms and instant under reduced motion (chart-tooltip.css). Values are never coloured:
 * direction is a glyph and a sign.
 */
import { useLayoutEffect, useRef, useState, type CSSProperties, type JSX } from "react";
import type { ChartEvents } from "@candleviewer/chart-engine";
import { placeTooltip, type Size } from "./placeTooltip";
import "./chart-tooltip.css";

type Readout = ChartEvents["readout"];
type Field = Readout["fields"][number];

export interface ChartTooltipProps {
  /** From `useReadout()`; null or `visible: false` fades the box out. */
  readonly readout: Readout | null;
  /** The bar interval the app knows ("1m"); the title reads `<timeText> · <interval>`. */
  readonly interval: string;
  /** The plot's size in CSS px (the box stays inside it, never over the gutters). */
  readonly plot: Size;
}

const num = (text: string | undefined): number =>
  text === undefined ? NaN : Number(text.replace(/[,\s]/g, "").replace("−", "-"));

/** Direction glyph after the close (▲ up, ▼ down); none when flat or unparseable. */
export function directionGlyph(fields: readonly Field[]): "▲" | "▼" | "" {
  const open = num(fields.find((f) => f.key === "open")?.value);
  const close = num(fields.find((f) => f.key === "close")?.value);
  if (!(open < close) && !(open > close)) return "";
  return close > open ? "▲" : "▼";
}

/** The delta carries its sign as text: a bare positive number gets a "+". */
function valueText(f: Field, glyph: string): string {
  let v = f.value;
  if (f.key === "delta" && num(v) > 0 && !v.startsWith("+")) v = `+${v}`;
  if (f.key === "close" && glyph !== "") v = `${v} ${glyph}`;
  return f.unit === "" ? v : `${v} ${f.unit}`;
}

export function ChartTooltip({ readout, interval, plot }: ChartTooltipProps): JSX.Element | null {
  const boxRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<Size>({ width: 0, height: 0 });
  // The last visible readout keeps its text while the box fades out.
  const shown = useRef<Readout | null>(null);
  if (readout?.visible === true) shown.current = readout;
  const content = shown.current;

  // Measured when the content changes (the box's size follows its rows); `setBox` bails out when equal.
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (el === null) return;
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    setBox((b) => (b.width === width && b.height === height ? b : { width, height }));
  }, [content]);

  if (content === null) return null;
  const at = placeTooltip({ x: content.x, y: content.y }, box, plot);
  const style: CSSProperties = { transform: `translate3d(${at.x}px, ${at.y}px, 0)` };
  const glyph = directionGlyph(content.fields);
  return (
    <div
      ref={boxRef}
      aria-hidden="true"
      className="cv-chart-tooltip"
      data-visible={readout?.visible === true ? "" : undefined}
      data-docked={at.docked ? "" : undefined}
      style={style}
    >
      <div className="cv-chart-tooltip__title">{`${content.timeText} · ${interval}`}</div>
      <dl className="cv-chart-tooltip__rows">
        {content.fields.map((f) => (
          <div key={f.key} className="cv-chart-tooltip__row">
            <dt>{f.label}</dt>
            <dd>{valueText(f, glyph)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
