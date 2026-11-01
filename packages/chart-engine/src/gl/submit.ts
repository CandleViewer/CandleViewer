// Draw submission (E11-S02, 26 §3.2 step 5): walks the batch builder's `drawList[0, count)` in its
// state-sorted order (BQ-42), switching program and texture only when they change. No allocation
// per frame (§3.2 rule 4): plain loops over retained batches, counters on the trace.
import type { RetainedBatch } from "../scene/batch-builder.js";
import type { BatchUniforms } from "../scene/gpu-types.js";
import type { PaneUniforms } from "../viewport/transform.js";
import type { GlBuffers } from "./buffers.js";
import { GL, type GL2Like } from "./gl-types.js";
import type { ProgramCache } from "./program-cache.js";
import type { GlTextures } from "./textures.js";
import type { DrawTrace } from "./trace.js";

/** Each batch is `count` instances of one 4-vertex strip quad: 2 triangles each. */
export const QUAD_VERTICES = 4;
/**
 * Strip vertices per instance, indexed by `PROGRAM` (E12-S06, BQ-15): every program draws one
 * quad; a batch block's `vertices` overrides it (the OHLC ticks' 10-vertex strip).
 */
export const PROGRAM_VERTICES: readonly number[] = [4, 4, 4, 4, 4];

/** A batch's pane uniform block (E11-S03), written by `writePaneUniforms` once per frame. */
export type PaneUniformSource = (batch: RetainedBatch) => PaneUniforms | null;

export type { BatchUniforms };
export type BatchUniformSource = (batch: RetainedBatch) => BatchUniforms | null;

export function submitDrawList(
  gl: GL2Like,
  list: readonly RetainedBatch[],
  count: number,
  parts: {
    programs: ProgramCache;
    textures: GlTextures;
    buffers: GlBuffers;
    trace: DrawTrace;
    paneUniforms?: PaneUniformSource | null;
    batchUniforms?: BatchUniformSource | null;
  },
): void {
  const { programs, textures, buffers, trace } = parts;
  const panes = parts.paneUniforms ?? null;
  const own = parts.batchUniforms ?? null;
  trace.begin();
  let program = -1;
  let texture = -1;
  let block: PaneUniforms | null = null; // set on the current program: once per (pane, program)
  try {
    for (let i = 0; i < count; i += 1) {
      const b = list[i] as RetainedBatch; // i < count <= list.length
      const vao = buffers.vao(b.nodeId);
      if (vao === null) continue; // no attached ring (the layers attach, E12/E18): no draw
      const blk = own === null ? null : own(b);
      const n = blk !== null && (blk.instances ?? -1) >= 0 ? (blk.instances as number) : b.count;
      if (n === 0) continue; // E12-S06: the gap seam with no gap in view (BQ-8): no draw
      if (b.program !== program) {
        programs.bind(b.program);
        program = b.program;
        trace.programSwitches += 1;
        block = null;
      }
      const pane = panes === null ? null : panes(b);
      if (pane !== null && pane !== block) {
        programs.setUniforms(program, pane); // a pan is this uniform write, never a buffer upload
        block = pane;
      }
      if (b.texture !== texture) {
        textures.bind(b.texture);
        texture = b.texture;
        trace.textureSwitches += 1;
      }
      if (blk !== null) programs.setBatchUniforms(program, blk);
      const vertices =
        blk !== null && blk.vertices > 0 ? blk.vertices : (PROGRAM_VERTICES[b.program] ?? 4);
      gl.bindVertexArray(vao);
      gl.drawArraysInstanced(GL.TRIANGLE_STRIP, 0, vertices, n);
      trace.draws += 1;
      trace.triangles += (vertices - 2) * n;
      if (trace.enabled) {
        trace.nodes.push(b.nodeId);
        trace.labels.push(blk?.label ?? b.nodeId);
      }
    }
  } finally {
    gl.bindVertexArray(null);
  }
}
