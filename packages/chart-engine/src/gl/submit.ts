// Draw submission (E11-S02, 26 §3.2 step 5): walks the batch builder's `drawList[0, count)` in its
// state-sorted order (BQ-42), switching program and texture only when they change. No allocation
// per frame (§3.2 rule 4): plain loops over retained batches, counters on the trace.
import type { RetainedBatch } from "../scene/batch-builder.js";
import type { GlBuffers } from "./buffers.js";
import { GL, type GL2Like } from "./gl-types.js";
import type { ProgramCache } from "./program-cache.js";
import type { GlTextures } from "./textures.js";
import type { DrawTrace } from "./trace.js";

/** Each batch is `count` instances of one 4-vertex strip quad: 2 triangles each. */
export const QUAD_VERTICES = 4;

export function submitDrawList(
  gl: GL2Like,
  list: readonly RetainedBatch[],
  count: number,
  parts: { programs: ProgramCache; textures: GlTextures; buffers: GlBuffers; trace: DrawTrace },
): void {
  const { programs, textures, buffers, trace } = parts;
  trace.begin();
  let program = -1;
  let texture = -1;
  try {
    for (let i = 0; i < count; i += 1) {
      const b = list[i] as RetainedBatch; // i < count <= list.length
      const vao = buffers.vao(b.nodeId);
      if (vao === null) continue; // no attached ring (the layers attach, E12/E18): no draw
      if (b.program !== program) {
        programs.bind(b.program);
        program = b.program;
        trace.programSwitches += 1;
      }
      if (b.texture !== texture) {
        textures.bind(b.texture);
        texture = b.texture;
        trace.textureSwitches += 1;
      }
      gl.bindVertexArray(vao);
      gl.drawArraysInstanced(GL.TRIANGLE_STRIP, 0, QUAD_VERTICES, b.count);
      trace.draws += 1;
      trace.triangles += 2 * b.count;
      if (trace.enabled) trace.nodes.push(b.nodeId);
    }
  } finally {
    gl.bindVertexArray(null);
  }
}
