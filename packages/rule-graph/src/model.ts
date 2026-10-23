// The rule editor's graph model (E37-T01), library-neutral: the canvas joins the positions in.
/** A CMP-146 node type; a comparison, temporal or arithmetic node is a `condition` of that kind. */
export type GraphNodeType = "trigger" | "condition" | "action" | "logicGate" | "comment";

/** Its id is the IR `node_id` (the trigger's is `trigger`), and `data` holds its own IR fields. */
export interface GraphNode {
  readonly id: string;
  readonly type: GraphNodeType;
  readonly data: Readonly<Record<string, unknown>>;
}

/** `source` feeds input `targetPort` of `target`: `left`, `right`, `right2`, `child`, `when` (the
 * root feeding an action) or `in`, which fills the `null` items of a list in edge order. */
export interface GraphEdge {
  readonly id: string;
  readonly source: string;
  readonly sourcePort: string;
  readonly target: string;
  readonly targetPort: string;
}

/** A rule: `envelope` holds its other fields, and the actions keep their IR order in `nodes`. */
export interface GraphModel {
  readonly envelope: Readonly<Record<string, unknown>>;
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
}

export type CommentNode = { readonly id: string; readonly text: string };

/** The presentation, stored as `graph_layout`, never hashed; `extra` keeps its other keys. */
export interface GraphLayout {
  readonly positions: Readonly<Record<string, { readonly x: number; readonly y: number }>>;
  readonly collapsed: readonly string[];
  readonly comments: readonly CommentNode[];
  readonly extra: Readonly<Record<string, unknown>>;
}

/** The IR of a graph, before the server's compile validates it. */
export type RuleIrDraft = Readonly<Record<string, unknown>>;
