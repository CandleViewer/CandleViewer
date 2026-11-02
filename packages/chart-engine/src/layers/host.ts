// The series host node (E12-S06, BQ-2): a scene `ContentNode` that runs one `SeriesPlugin` and is
// the plugin's `RenderContext`. A plugin declares retained instances (`instances(ring, program,
// part)`) and projects through the transform's own functions (`projection`, G-2); a node draws
// one part, so a candle series is two hosts sharing one `CandleRing` (plan §2, BQ-1). The
// immediate-mode calls of §8 land with their layers (E11-S06/S07, E11-S11), not here. No DOM.
import type { BarView } from "../model/BarStore.js";
import { ContentNode, type NodeOptions } from "../scene/node.js";
import type { BatchSink } from "../scene/pool.js";
import { indexToScreen, priceToScreen, screenToTime } from "../viewport/transform.js";
import type { ViewportState } from "../viewport/types.js";
import type { DataRange, InstanceRing, SeriesProjection } from "./plugin-api.js";

/** §8 `ThemeTokens` and `Viewport`, structurally (`api/types.ts` is the DOM project's). */
export interface HostTheme {
  readonly palette: "default" | "cvd-safe";
  readonly convention: "standard" | "inverted";
  readonly colors: Readonly<Record<string, string>>;
}
export interface HostViewport {
  readonly widthPx: number;
  readonly heightPx: number;
  readonly pixelRatio: number;
  readonly timeStart: number;
  readonly timeEnd: number;
}

/** The context a hosted plugin reads: §8 `RenderContext`'s retained half (test/api checks it). */
export interface HostContext {
  readonly viewport: HostViewport;
  readonly theme: HostTheme;
  instances(ring: InstanceRing, program: "candle", part: number): void;
  readonly projection: SeriesProjection;
}

/** The members of §8 `SeriesPlugin` the host calls; any `SeriesPlugin` fits. */
export interface HostedPlugin {
  collect(ctx: HostContext): void;
  onMutation?(view: BarView, range: DataRange): void;
}

export interface HostDeps {
  /** The chart's shared transform (E11-S03). */
  readonly viewport: ViewportState;
  /** The pane the series draws on. */
  readonly pane: number;
  /** The theme as the plugin reads it (§5 rule 1: tokens only). */
  theme(): HostTheme;
}

export interface HostOptions extends NodeOptions {
  /** The part this node draws (`instances`' third argument). */
  readonly part: number;
  /** The `PROGRAM` its batch carries: the state-sort key (26 §3.1). */
  readonly program: number;
}

const unsupported = (what: string): never => {
  throw new Error(`chart-engine: RenderContext.${what} is not available to series plugins yet`);
};

export class SeriesHost extends ContentNode implements HostContext {
  readonly part: number;
  readonly program: number;
  readonly projection: SeriesProjection;
  /** One object for the node's life, refreshed at each collect (no per-frame allocation). */
  private readonly vp = { widthPx: 0, heightPx: 0, pixelRatio: 1, timeStart: 0, timeEnd: 0 };
  private sink: BatchSink | null = null;

  constructor(
    id: string,
    readonly plugin: HostedPlugin,
    private readonly deps: HostDeps,
    opts: HostOptions,
  ) {
    super(id, opts);
    this.part = opts.part;
    this.program = opts.program;
    const { viewport, pane } = deps;
    this.projection = {
      indexToX: (i) => indexToScreen(viewport, i),
      tickToY: (t) => priceToScreen(viewport, pane, t),
    };
  }

  get viewport(): HostViewport {
    return this.vp;
  }

  get theme(): HostTheme {
    return this.deps.theme();
  }

  /** The plugin declares its instances; only this node's part becomes a batch entry. */
  collect(sink: BatchSink): boolean {
    const v = this.deps.viewport;
    const vp = this.vp;
    vp.widthPx = v.plotWidth;
    vp.heightPx = v.height;
    vp.pixelRatio = v.dpr;
    vp.timeStart = screenToTime(v, 0);
    vp.timeEnd = screenToTime(v, v.plotWidth);
    this.sink = sink;
    try {
      this.plugin.collect(this);
    } finally {
      this.sink = null;
    }
    return true;
  }

  /** A store mutation (the runtime's): the retained path when the plugin has one. */
  onMutation(view: BarView, range: DataRange): void {
    this.plugin.onMutation?.(view, range);
  }

  instances(ring: InstanceRing, program: "candle", part: number): void {
    void program; // the name is the plugin's; the node's `program` number is the sort key
    const sink = this.sink;
    if (sink === null) unsupported("instances outside collect");
    if (part !== this.part) return;
    const e = (sink as BatchSink).append();
    e.nodeId = this.id;
    e.program = this.program;
    e.texture = 0;
    e.first = 0;
    e.count = ring.capacity; // the shader maps each slot to its bar (BQ-14)
  }

  // §8's immediate-mode calls: present, so the host is a whole `RenderContext`, and loud.
  rect(): void {
    unsupported("rect");
  }

  line(): void {
    unsupported("line");
  }

  glyphRun(): void {
    unsupported("glyphRun");
  }

  quadBatch(): void {
    unsupported("quadBatch");
  }

  texture(): void {
    unsupported("texture");
  }
}
