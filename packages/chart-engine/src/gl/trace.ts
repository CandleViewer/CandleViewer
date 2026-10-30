// The draw trace (E11-S02, README BQ-51): per-frame counters `frame` stats report, and, opt-in,
// the node of every draw in order, which the CI draw-call gate reads off the fake GL.
export class DrawTrace {
  /** Records `nodes` when true; off by default, so a production frame records nothing. */
  enabled = false;
  draws = 0;
  triangles = 0;
  programSwitches = 0;
  textureSwitches = 0;
  /** The node id of each draw this frame, in submission order (only while `enabled`). */
  readonly nodes: string[] = [];

  begin(): void {
    this.draws = this.triangles = this.programSwitches = this.textureSwitches = 0;
    this.nodes.length = 0;
  }
}
