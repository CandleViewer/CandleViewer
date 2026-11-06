// VolumeSeries (E12-S08 PR 1, E12-D06 §12; BQ-2, BQ-11): the volume column plugin. One host node
// draws the dedicated `volume` program from a `CandleRing` whose derived write is a `VolumeRing`;
// the ring is synced from the PRICE series' store (borrowed, never owned), so the columns sit on
// the same logical indices and slots as the price series' bars (index spacing on time and non-time
// bars alike). One draw, 20 B per bar, labelled `series.volume.body`. The palette is the candle
// palette (tokens from the theme object, never a colour in code); a theme without them hides the
// column. A theme switch is a uniform write; a pan writes no bytes. The pane is the caller's
// (`HostDeps.pane`): nothing here knows the pane stack. `dispose()` detaches the host and drops
// the ring. No DOM, no GL.
import type { AttributeLayout, BatchUniforms, VertexSource } from "../../scene/gpu-types.js";
import type { BarStore } from "../../model/BarStore.js";
import type { MutationRange } from "../../model/counters.js";
import type { SceneGraph } from "../../scene/graph.js";
import { PROGRAM } from "../../scene/instance-layout.js";
import { type HostContext, type HostDeps, type HostedPlugin, SeriesHost } from "../host.js";
import { candleGeometry, GEOM, GEOM_FLOATS } from "../candle/geometry.js";
import { candlePalette, PALETTE_FLOATS, PaletteError } from "../candle/palette.js";
import { CANDLE_STRIDE, CandleRing, type RangePatchSink } from "../candle/ring.js";
import { VolumeExtentSource } from "./extent.js";
import { VolumeRing } from "./volume-ring.js";

export const VOLUME_LABEL = "series.volume";
/** `u_batch.x` and the host part of the one column batch. */
export const VOLUME_PART = 0;
/** The ring as the `volume` shader's attributes (`a_vol`, `a_meta`; the candle ring's stride). */
export const VOLUME_ATTRIBUTES: AttributeLayout = {
  stride: CANDLE_STRIDE,
  ints: [
    [0, 0, 4],
    [1, 4, 1],
  ],
};

export class VolumeSeries implements HostedPlugin {
  readonly palette = new Float32Array(PALETTE_FLOATS);
  readonly geom = new Float32Array(GEOM_FLOATS);
  readonly ring: CandleRing;
  readonly transform: VolumeRing;
  /** The pane's autoscale source (`PriceExtentSource`), bumped on every sync. */
  readonly extent: VolumeExtentSource;
  /** The one batch's uniforms: `u_batch` = (body part, head, mask, length). */
  readonly block: BatchUniforms;
  host: SeriesHost | null = null;
  /** False while the theme lacks a candle token: the host is hidden. */
  drawable = false;

  /** `quantum`: the instrument's qty_step, REQUIRED (`VolumeQuantumError` when absent / invalid). */
  constructor(quantum: number, sink: RangePatchSink | null = null) {
    this.ring = new CandleRing(sink);
    this.transform = new VolumeRing(quantum);
    this.ring.setMode(null, false, this.transform);
    this.extent = new VolumeExtentSource(this.ring);
    this.block = {
      ints: Int32Array.of(VOLUME_PART, 0, 0, 0),
      geom: this.geom,
      palette: this.palette,
      vertices: 4,
      label: `${VOLUME_LABEL}.body`,
      instances: -1,
    };
  }

  get source(): VertexSource {
    return this.ring;
  }

  collect(ctx: HostContext): void {
    ctx.instances(this.ring, "candle", VOLUME_PART); // the name is the plugin API's; see PROGRAM
  }

  /** Mirrors the price series' `store` after its mutation `r` (the store is borrowed). */
  sync(store: BarStore, r: MutationRange): void {
    this.ring.sync(store, r);
    this.extent.bump();
  }

  /** New quantum (an instrument change): rewrites every column in place from `store`. */
  setQuantum(store: BarStore, quantum: number): void {
    this.transform.setQuantum(quantum);
    this.rewrite(store);
  }

  /** A decimated tier draws every column neutral (D06 §12 L1 / L2); L0 draws by direction. */
  setNeutral(store: BarStore, on: boolean): void {
    if (this.transform.neutral === on) return;
    this.transform.neutral = on;
    this.rewrite(store);
  }

  private rewrite(store: BarStore): void {
    this.ring.setMode(null, false, null); // no store: sets the mode only, nothing written
    this.ring.setMode(store, false, this.transform); // one O(n) rewrite, same array
    this.extent.bump();
  }

  mount(graph: SceneGraph, paneId: string, id: string, deps: HostDeps): SeriesHost {
    const host = new SeriesHost(id, this, deps, {
      part: VOLUME_PART,
      program: PROGRAM.volume,
    });
    graph.addNode(paneId, "series", host);
    host.visible = this.drawable;
    this.host = host;
    this.ring.nodes.length = 0;
    this.ring.nodes.push(id);
    return host;
  }

  /** Resolves the palette (theme load only); the refusal, else null. Hides or shows the host. */
  setTheme(theme: Readonly<Record<string, string>>, inverted = false): PaletteError | null {
    let err: PaletteError | null = null;
    try {
      candlePalette(theme, inverted, this.palette);
    } catch (e) {
      if (!(e instanceof PaletteError)) throw e;
      err = e;
    }
    this.drawable = err === null;
    if (this.host !== null) this.host.visible = this.drawable;
    return err;
  }

  /** Per frame, before submission: the geometry and the ring's state, in place (no allocation). */
  frame(spacingCss: number, dpr: number): void {
    candleGeometry(spacingCss, dpr, this.geom);
    this.geom[GEOM.plotTop] = 0;
    this.geom[GEOM.plotBottom] = 0;
    const r = this.ring;
    const ints = this.block.ints;
    ints[1] = r.head;
    ints[2] = r.capacity - 1;
    ints[3] = r.length;
  }

  dispose(): void {
    if (this.host !== null) this.host.visible = false;
    this.host = null;
    this.ring.nodes.length = 0;
    this.ring.sink = null;
    this.drawable = false;
  }
}
