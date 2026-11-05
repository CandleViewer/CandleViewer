/**
 * The chart's drawing (E42-S08 §4.4; E42-D05 §11 SI-4, D35; BQ-6 as ruled: a plain SVG drawing in
 * place of CMP-146, which is unbuilt, for now). A labelled region holding one image: the states as
 * boxes, compound states as nested groups, parallel regions side by side and dashed, transitions as
 * arrows, each initial child's dot. It is a convenience: its details are the text list
 * (`aria-details`, a relationship that is never read out), the normative equivalent, which follows
 * it, and its keyboard path is that list (no pan or zoom key of its own, D02 D18); the region takes
 * a Tab stop only while it scrolls (WCAG 2.1.1). The current states are the caller's, from the
 * served configuration while the export's hash is the machine's: a 3 px `color.border.selected`
 * border, a bold label and the word "current" (`machine.current`), never colour alone. Text goes
 * through React as SVG `<text>`, never as markup. Nothing moves, so reduced motion needs nothing.
 */
import {
  memo,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
  type RefObject,
} from "react";
import { layoutOf, type LaidBox } from "./chartLayout";
import type { ChartModel } from "./chartModel";
import { INSPECTOR_COPY } from "./copy";
import { kindLabel } from "./kinds";
import "./inspector.css";

const COPY = INSPECTOR_COPY.chart;
/** A group's header line and a leaf's two lines (label, then "current"), in px from the box's top. */
const HEADER_BASELINE = 14;
const LEAF_MIDDLE = 22;
const LEAF_LABEL = 17;
const LEAF_CURRENT = 32;
/** Inside a final state's border, a second one (the notation's "final"; the list says it in words). */
const FINAL_INSET = 3;
/** Past this many characters a label is fitted to its box's width rather than cut. */
const FIT_FROM = 30;

/**
 * Whether the region scrolls, so it takes a Tab stop: measured as the region or the drawing
 * resizes (a text scale or a zoom), once without ResizeObserver.
 */
function useScrolls(region: RefObject<HTMLDivElement | null>): boolean {
  const [scrolls, setScrolls] = useState(false);
  useEffect(() => {
    const node = region.current;
    if (node === null) return undefined;
    const measure = (): void => {
      setScrolls(node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth);
    };
    if (typeof ResizeObserver === "undefined") {
      measure();
      return undefined;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    for (const child of node.children) observer.observe(child);
    return () => observer.disconnect();
  }, [region]);
  return scrolls;
}

/** A label that fits its box: a long one is fitted to the width, never cut. */
const fit = (label: string, width: number): { textLength?: number; lengthAdjust?: string } =>
  label.length > FIT_FROM ? { textLength: width - 16, lengthAdjust: "spacingAndGlyphs" } : {};

function Group({ box, current }: { readonly box: LaidBox; readonly current: boolean }) {
  return (
    <g>
      <rect
        className="cv-inspector-diagram__group"
        data-region={box.region ? "" : undefined}
        data-current={current ? "" : undefined}
        x={box.x}
        y={box.y}
        width={box.w}
        height={box.h}
        rx={6}
      />
      <text
        className="cv-inspector-diagram__group-label"
        data-current={current ? "" : undefined}
        x={box.x + 12}
        y={box.y + HEADER_BASELINE}
      >
        {box.label}
        {current ? (
          <tspan className="cv-inspector-diagram__group-current">{` ${INSPECTOR_COPY.current}`}</tspan>
        ) : null}
      </text>
    </g>
  );
}

function Leaf({ box, current }: { readonly box: LaidBox; readonly current: boolean }) {
  const middle = box.x + box.w / 2;
  return (
    <g>
      <rect
        className="cv-inspector-diagram__box"
        data-current={current ? "" : undefined}
        x={box.x}
        y={box.y}
        width={box.w}
        height={box.h}
        rx={4}
      />
      {box.kind === "final" ? (
        <rect
          className="cv-inspector-diagram__final"
          x={box.x + FINAL_INSET}
          y={box.y + FINAL_INSET}
          width={box.w - 2 * FINAL_INSET}
          height={box.h - 2 * FINAL_INSET}
          rx={2}
        />
      ) : null}
      <text
        className="cv-inspector-diagram__label"
        data-current={current ? "" : undefined}
        x={middle}
        y={box.y + (current ? LEAF_LABEL : LEAF_MIDDLE)}
        {...fit(box.label, box.w)}
      >
        {box.label}
      </text>
      {current ? (
        <text className="cv-inspector-diagram__current" x={middle} y={box.y + LEAF_CURRENT}>
          {INSPECTOR_COPY.current}
        </text>
      ) : null}
    </g>
  );
}

export interface ChartDiagramProps {
  readonly model: ChartModel;
  /** The current states: none while the export's hash differs from the machine's (§4.4). */
  readonly current: ReadonlySet<string>;
  /** The text list's id: the drawing's details. */
  readonly listId: string;
}

/** The drawing, or nothing for a chart over the drawing's bounds (the caller says so, §4.3). */
export const ChartDiagram = memo(function ChartDiagram({
  model,
  current,
  listId,
}: ChartDiagramProps): JSX.Element | null {
  const region = useRef<HTMLDivElement>(null);
  const scrolls = useScrolls(region);
  const arrow = `cv-inspector-arrow-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const layout = layoutOf(model);
  if (layout === null) return null;
  const kind = kindLabel(model.kind);
  const head = `url(#${arrow})`;
  // The drawing keeps its proportions under the in-app text scale: its text never outgrows a box.
  const size: CSSProperties = {
    inlineSize: `calc(${layout.width}px * var(--cv-text-scale, 1))`,
    blockSize: `calc(${layout.height}px * var(--cv-text-scale, 1))`,
  };
  return (
    <div
      ref={region}
      role="region"
      aria-label={COPY.diagramName(kind)}
      className="cv-inspector-diagram cv-focus-ring"
      {...(scrolls ? { tabIndex: 0 } : {})}
    >
      <svg
        role="img"
        aria-label={COPY.diagramTitle(kind, model.states.length)}
        aria-details={listId}
        className="cv-inspector-diagram__svg"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        width={layout.width}
        height={layout.height}
        style={size}
      >
        <defs>
          <marker
            id={arrow}
            viewBox="0 0 8 8"
            markerWidth={8}
            markerHeight={8}
            markerUnits="userSpaceOnUse"
            refX={8}
            refY={4}
            orient="auto"
          >
            <path className="cv-inspector-diagram__head" d="M0 0 L8 4 L0 8 Z" />
          </marker>
        </defs>
        {layout.boxes
          .filter((box) => box.group)
          .map((box) => (
            <Group key={box.id} box={box} current={current.has(box.id)} />
          ))}
        {layout.edges.map((edge) => (
          <path
            key={`${edge.from}|${edge.to}`}
            className="cv-inspector-diagram__edge"
            d={edge.path}
            markerEnd={head}
          />
        ))}
        {layout.boxes
          .filter((box) => !box.group)
          .map((box) => (
            <Leaf key={box.id} box={box} current={current.has(box.id)} />
          ))}
        {layout.initials.map((mark) => (
          <g key={mark.to}>
            <circle className="cv-inspector-diagram__dot" cx={mark.cx} cy={mark.cy} r={3} />
            <path className="cv-inspector-diagram__edge" d={mark.path} markerEnd={head} />
          </g>
        ))}
      </svg>
    </div>
  );
});
