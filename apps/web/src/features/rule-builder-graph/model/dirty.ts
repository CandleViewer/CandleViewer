/**
 * Unsaved changes (E37-S01; US-RULE-006 "Unsaved changes"; the navigation guard reads it): the
 * editor is dirty while its graph differs from the graph last saved or loaded. Only the graph
 * counts, its envelope, nodes and edges. A layout change (a move) is cosmetic and never makes the
 * rule dirty (E37-D02 §20 P7: no layout change makes a version or a dirty flag), and neither does
 * a selection: the mark holds neither. The undo stack (PR 4 of 9) replays the very node and edge
 * objects an edit removed, so an undo back to the saved graph is clean again; a node made anew
 * with the same content is a change. Pure, and linear in the graph's size.
 */
import type { GraphModel } from "@candleviewer/rule-graph";

/** The graph as last saved or loaded. */
export interface SavedMark {
  readonly graph: GraphModel;
}

export const markSaved = (graph: GraphModel): SavedMark => ({ graph });

const sameItems = <T>(a: readonly T[], b: readonly T[]): boolean =>
  a.length === b.length && a.every((item, i) => item === b[i]);

/** Whether `graph`, the editor's graph now, differs from the one `mark` holds. */
export function isDirty(graph: GraphModel, mark: SavedMark): boolean {
  const saved = mark.graph;
  if (graph === saved) return false;
  return (
    graph.envelope !== saved.envelope ||
    !sameItems(graph.nodes, saved.nodes) ||
    !sameItems(graph.edges, saved.edges)
  );
}
