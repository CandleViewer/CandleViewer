// The fixed scene tree (26 §3.1: Chart -> TimeAxis + Pane[] -> PriceAxis + LAYER_ORDER -> content),
// its dirty propagation, and a flat pre-order walk rebuilt only on LAYOUT (E11-S01). DOM-free.
import { Dirty, LAYER_ORDER, type LayerName, SHED_ALL } from "./dirty.js";
import type { FrameContext } from "./frame-context.js";
import { ContentNode, type SceneNode, StructuralNode } from "./node.js";
import type { BatchSink } from "./pool.js";

export class PaneNode extends StructuralNode {
  readonly priceAxis: StructuralNode;
  readonly layers: readonly StructuralNode[]; // LAYER_ORDER, in order

  constructor(id: string) {
    super(id, "pane");
    this.priceAxis = new StructuralNode(`${id}/price-axis`, "price-axis");
    this.layers = LAYER_ORDER.map((name) => new StructuralNode(`${id}/${name}`, "layer"));
  }
}

export class SceneGraph {
  readonly root = new StructuralNode("chart", "chart");
  rebuilds = 0; // walk rebuilds so far: LAYOUT changes only
  private readonly byId = new Map<string, SceneNode>();
  private readonly order: SceneNode[] = [];
  private layoutPending = true;

  constructor() {
    this.byId.set(this.root.id, this.root); // reserves the root's id: no node may reuse "chart"
    this.attach(this.root, new StructuralNode("chart/time-axis", "time-axis"));
  }

  addPane(id: string): PaneNode {
    const pane = new PaneNode(id);
    this.attach(this.root, pane);
    this.attach(pane, pane.priceAxis);
    for (const layer of pane.layers) this.attach(pane, layer);
    return pane;
  }

  addNode(paneId: string, layer: LayerName, node: ContentNode): void {
    const target = this.pane(paneId).layers[LAYER_ORDER.indexOf(layer)];
    if (target === undefined) throw new RangeError(`unknown layer ${layer}`);
    this.attach(target, node);
  }

  get(id: string): SceneNode | undefined {
    return this.byId.get(id);
  }

  setVisible(id: string, visible: boolean): void {
    const node = this.byId.get(id);
    if (node === undefined) throw new RangeError(`unknown node ${id}`);
    if (node.visible !== visible) node.dirty |= Dirty.STYLE;
    node.visible = visible;
  }

  /** A data update marks only that series DATA; `false` for an unknown id. */
  markData(id: string): boolean {
    const node = this.byId.get(id);
    if (node instanceof ContentNode) node.dirty |= Dirty.DATA;
    return node instanceof ContentNode;
  }

  /** Every drawable node (content and axes) TRANSFORM, never DATA: buffers are reused. */
  markViewport(): void {
    this.markDrawable(Dirty.TRANSFORM);
  }

  markTheme(): void {
    this.markDrawable(Dirty.STYLE);
  }

  /** The pane's subtree (every pane when omitted) and the time axis LAYOUT. */
  markResize(paneId?: string): void {
    if (paneId === undefined) this.markLayout(this.root);
    else {
      this.markLayout(this.pane(paneId));
      (this.byId.get("chart/time-axis") as SceneNode).dirty |= Dirty.LAYOUT; // made in constructor
    }
    this.layoutPending = true;
  }

  walk(): readonly SceneNode[] {
    if (this.layoutPending) {
      this.order.length = 0;
      this.linearise(this.root);
      this.layoutPending = false;
      this.rebuilds += 1;
    }
    return this.order;
  }

  /**
   * One traversal: each dirty, visible node is updated and collected, and its flags clear when the
   * collect succeeds (BQ-23). A node whose deferClass bit is set in `shed` is deferred and keeps its
   * flags; critical nodes are NONE, whose bit is ignored, so never deferred. A hidden subtree keeps
   * its flags. `shed` skips rungs for this frame only; the scheduler owns the cadences (BQ-35).
   */
  frame(ctx: FrameContext, sink: BatchSink, shed = 0): void {
    const order = this.walk();
    for (let i = 0; i < order.length; i += 1) {
      const node = order[i] as SceneNode; // i < order.length
      if (!node.visible) i = node.end - 1;
      if (!node.visible || node.dirty === Dirty.NONE) continue;
      if (((shed & SHED_ALL) >> node.deferClass) & 1) {
        ctx.stats.deferred += 1;
        continue;
      }
      node.update(ctx);
      ctx.stats.updated += 1;
      if (node.collect(sink)) {
        node.dirty = Dirty.NONE;
        ctx.stats.collected += 1;
      }
    }
  }

  private pane(id: string): PaneNode {
    const pane = this.byId.get(id);
    if (!(pane instanceof PaneNode)) throw new RangeError(`unknown pane ${id}`);
    return pane;
  }

  /** Stable: lands after every sibling with zIndex <= its own (ties: insertion order, BQ-20). */
  private attach(parent: SceneNode, node: SceneNode): void {
    if (this.byId.has(node.id)) throw new RangeError(`duplicate node id ${node.id}`);
    this.byId.set(node.id, node);
    let at = parent.children.length;
    while (at > 0 && (parent.children[at - 1] as SceneNode).zIndex > node.zIndex) at -= 1;
    parent.children.splice(at, 0, node);
    node.parent = parent;
    this.layoutPending = true;
  }

  private linearise(node: SceneNode): void {
    node.start = this.order.length;
    this.order.push(node);
    for (const child of node.children) this.linearise(child);
    node.end = this.order.length;
  }

  private markDrawable(flag: number): void {
    const order = this.walk();
    for (let i = 0; i < order.length; i += 1) {
      const node = order[i] as SceneNode; // i < order.length
      if (node.kind === "content" || node.kind.endsWith("-axis")) node.dirty |= flag;
    }
  }

  private markLayout(node: SceneNode): void {
    node.dirty |= Dirty.LAYOUT;
    for (const child of node.children) this.markLayout(child);
  }
}
