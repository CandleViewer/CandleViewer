/**
 * The chart's text list (E42-S08 §4.2; E42-D05 §11, D35, D45): every state, nested as the chart
 * nests them and marked in words, then every transition as "from → to on EVENT". It is the
 * normative non-visual equivalent of the drawing and AC4's check against `exportStatechart`: never
 * truncated, never scrolled (D05 §4.2), always in the DOM and never live. The drawing (BQ-6) points
 * at it with `aria-details`, through `id`.
 */
import { memo, type CSSProperties, type JSX } from "react";
import type { ChartEdge, ChartModel, ChartState } from "./chartModel";
import { INSPECTOR_COPY } from "./copy";

const COPY = INSPECTOR_COPY.chart;

/** Long names wrap, never cut or scroll (D05 §4.2: only the drawing scrolls). */
const ROOT: CSSProperties = { overflowWrap: "anywhere", display: "grid", gap: "var(--space-2)" };
const HEADING: CSSProperties = {
  margin: 0,
  font: "var(--type-ui-heading-sm-font-weight) var(--type-ui-heading-sm-font-size) / var(--type-ui-heading-sm-line-height) var(--type-ui-heading-sm-font-family)",
};
const LIST: CSSProperties = { margin: 0, paddingInlineStart: "var(--space-6)" };
const GROUPS: CSSProperties = { display: "grid", gap: "var(--space-2)" };
const NOTE: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
/** The current state reads bold as well as "(current)": weight is never the only signal. */
const CURRENT: CSSProperties = { fontWeight: "var(--font-weight-semibold)" };

export interface ChartTextListProps {
  readonly model: ChartModel;
  /**
   * The states marked "(current)": `currentIds(model, configuration)`, or none while the export's
   * hash differs from the machine's (no highlight, §4.4).
   */
  readonly current: ReadonlySet<string>;
  /** The node the drawing's `aria-details` names. */
  readonly id?: string | undefined;
  /** The level of its two headings: 3 under the machine view's `h2`. */
  readonly headingLevel?: 3 | 4;
}

/** " (initial) (current)": a state's markers, each a word. */
function markers(state: ChartState, current: boolean): string {
  const words = [
    state.initial ? COPY.initial : null,
    state.kind === "final" ? COPY.final : null,
    state.kind === "parallel" ? COPY.parallel : null,
    current ? INSPECTOR_COPY.current : null,
  ];
  return words
    .filter((word) => word !== null)
    .map((word) => ` (${word})`)
    .join("");
}

/** One level of the state tree, and below each state its own children. */
function StateList({
  parent,
  tree,
  current,
}: {
  readonly parent: string;
  readonly tree: ReadonlyMap<string, readonly ChartState[]>;
  readonly current: ReadonlySet<string>;
}): JSX.Element | null {
  const states = tree.get(parent);
  if (states === undefined) return null;
  return (
    <ul style={LIST}>
      {states.map((state) => {
        const now = current.has(state.id);
        return (
          <li key={state.id}>
            <span style={now ? CURRENT : undefined}>{state.name}</span>
            {markers(state, now)}
            <StateList parent={state.id} tree={tree} current={current} />
          </li>
        );
      })}
    </ul>
  );
}

/** How the transition is taken, in words: "on KILL", "(always)", "when cancel_all is done". */
function how(edge: ChartEdge): string {
  switch (edge.via) {
    case "on":
      return COPY.on(edge.event);
    case "always":
      return COPY.always;
    case "after":
      return COPY.after(edge.event);
    case "done":
      return COPY.done(edge.event);
    case "error":
      return COPY.error(edge.event);
  }
}

/**
 * "clear → engaging on ENGAGE", read as "clear to engaging on ENGAGE" (the arrow is hidden from
 * assistive technology); "engaged on RELEASE: no state change" for an arm with no target.
 */
function EdgeLine({
  edge,
  label,
}: {
  readonly edge: ChartEdge;
  readonly label: (id: string) => string;
}): JSX.Element {
  if (edge.to === null) {
    return <>{`${label(edge.from)} ${how(edge)}: ${COPY.noChange}`}</>;
  }
  return (
    <>
      {`${label(edge.from)} `}
      <span aria-hidden="true">→</span>
      <span className="cv-visually-hidden">{COPY.to}</span>
      {` ${label(edge.to)} ${how(edge)}`}
    </>
  );
}

const edgeKey = (edge: ChartEdge): string =>
  `${edge.from}|${edge.to ?? ""}|${edge.via}|${edge.event}`;

export const ChartTextList = memo(function ChartTextList({
  model,
  current,
  id,
  headingLevel = 3,
}: ChartTextListProps): JSX.Element {
  const Heading = headingLevel === 3 ? "h3" : "h4";
  const tree = new Map<string, ChartState[]>();
  const labels = new Map<string, string>([[model.root, COPY.anyState]]);
  for (const state of model.states) {
    tree.set(state.parent, [...(tree.get(state.parent) ?? []), state]);
    labels.set(state.id, state.label);
  }
  // The model lists edges by source in document order, the root's first: one list per source.
  const groups: ChartEdge[][] = [];
  for (const edge of model.edges) {
    const last = groups.at(-1);
    if (last !== undefined && last[0]?.from === edge.from) last.push(edge);
    else groups.push([edge]);
  }
  const label = (state: string): string => labels.get(state) ?? state;
  return (
    <div id={id} style={ROOT}>
      <Heading style={HEADING}>{COPY.states}</Heading>
      {model.rootKind === "parallel" ? <p style={NOTE}>{COPY.parallelRoot}</p> : null}
      <StateList parent={model.root} tree={tree} current={current} />
      <Heading style={HEADING}>{COPY.transitions}</Heading>
      <div style={GROUPS}>
        {groups.map((group) => (
          <ul key={group[0]?.from} style={LIST}>
            {group.map((edge) => (
              <li key={edgeKey(edge)}>
                <EdgeLine edge={edge} label={label} />
              </li>
            ))}
          </ul>
        ))}
      </div>
    </div>
  );
});
