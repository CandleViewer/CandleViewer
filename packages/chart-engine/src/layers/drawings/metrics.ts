// `engine_drawing_*` (E14-T03 PR 2, ticket Observability): the drawings layer's counters, kept on
// its node and posted on the worker's `frame` message (the engine's stats channel, §6) as the
// additive `drawings` block; read by tests. Not on §8's public `FrameStats` (the `engine.pick.*`
// precedent, G-24): the debug overlay that shows them is the app's. DOM- and GL-free.

/** Upper bounds of `engine_drawing_layer_frame_ms`'s buckets (ms); the last one is open. */
export const LAYER_MS_BUCKETS = [0.1, 0.25, 0.5, 1, 2, 4, 8, 12, Infinity] as const;

/** The `frame` message's `drawings` block: the gauges and totals at this frame. */
export interface DrawingMetrics {
  /** `engine_drawing_count`: drawings held. */
  readonly count: number;
  /** `engine_drawing_layer_frame_ms`: this frame's layer update (bounds + any encode), ms. */
  readonly layerFrameMs: number;
  /** `engine_drawing_instance_uploads_total`: instances re-uploaded since the layer was made. */
  readonly instanceUploads: number;
  /** `engine_text_draw_calls`: the label draws of this frame (≤ 1 per pane: 26 §3.7's third). */
  readonly textDrawCalls: number;
  /** `engine_drawing_token_fallbacks_total`: colours resolved by a fallback (a missing token). */
  readonly tokenFallbacks: number;
  /** The last token key the theme lacked (the warn), or null. */
  readonly missingToken: string | null;
}

export class DrawingCounters implements DrawingMetrics {
  /** `engine_drawing_layer_frame_ms`: counts per `LAYER_MS_BUCKETS` bucket (an injected clock). */
  readonly layerFrameHistogram = new Uint32Array(LAYER_MS_BUCKETS.length);
  count = 0;
  layerFrameMs = 0;
  instanceUploads = 0;
  textDrawCalls = 0;
  tokenFallbacks = 0;
  missingToken: string | null = null;

  /** One frame's layer time into the histogram. */
  observe(ms: number): void {
    this.layerFrameMs = ms;
    let i = 0;
    while (ms > (LAYER_MS_BUCKETS[i] as number)) i += 1;
    this.layerFrameHistogram[i] = (this.layerFrameHistogram[i] as number) + 1;
  }

  /** A plain copy for the `frame` message (structured-cloned in worker mode). */
  snapshot(): DrawingMetrics {
    return {
      count: this.count,
      layerFrameMs: this.layerFrameMs,
      instanceUploads: this.instanceUploads,
      textDrawCalls: this.textDrawCalls,
      tokenFallbacks: this.tokenFallbacks,
      missingToken: this.missingToken,
    };
  }
}
