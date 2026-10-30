// TEST-ONLY content node (E11-S01): records updates and collects, can fail a collect on demand.
import { ContentNode } from "./node.js";
import type { BatchSink } from "./pool.js";

export class NullSeries extends ContentNode {
  updates = 0;
  collects = 0;
  cleanCollects = 0; // collects of a clean node: must stay 0
  lastFlags = 0;
  failCollect = false;
  program = 0; // what its batch entry carries, for the batch builder's tests
  texture = 0;
  count = 1;

  override update(): void {
    this.updates += 1;
  }

  collect(sink: BatchSink): boolean {
    this.collects += 1;
    this.lastFlags = this.dirty;
    if (this.dirty === 0) this.cleanCollects += 1;
    if (this.failCollect) return false;
    const entry = sink.append();
    entry.nodeId = this.id;
    entry.program = this.program;
    entry.texture = this.texture;
    entry.count = this.count;
    return true;
  }
}
