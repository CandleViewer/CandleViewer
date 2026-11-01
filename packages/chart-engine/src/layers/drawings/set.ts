// One chart's drawing set (E14-T03 slice 1): `setDrawings` folded under the caps, checked before
// the first write so a refusal changes nothing (E14-X01 DR29). The worker keeps records here, the
// host the inputs it replays as one `replace` after a restart.
import { MAX_ANCHORS, MAX_DRAWINGS, type DrawingInput, type SetDrawings } from "./model.js";

export class DrawingSet<R> {
  /** In draw order: insertion order, a patched id keeps its place. */
  readonly order: R[] = [];
  readonly ids: string[] = [];
  anchors = 0;
  /** Bumps on every applied command. */
  rev = 0;
  private readonly at = new Map<string, number>();
  private readonly counts: number[] = [];

  constructor(private readonly make: (d: DrawingInput) => R) {} // given validated inputs only

  get size(): number {
    return this.order.length;
  }

  /** Applies a structurally valid command: null, or why it is refused with nothing changed. */
  apply(cmd: SetDrawings): string | null {
    const patch = cmd.op === "patch";
    let size = patch ? this.order.length : 0;
    let anchors = patch ? this.anchors : 0;
    const gone = new Set<string>();
    for (const id of patch ? (cmd.remove ?? []) : []) {
      const i = this.at.get(id);
      if (i === undefined || gone.has(id)) continue;
      gone.add(id);
      size -= 1;
      anchors -= this.counts[i] as number;
    }
    for (const d of cmd.drawings) {
      const i = patch && !gone.has(d.id) ? this.at.get(d.id) : undefined;
      if (i === undefined) size += 1;
      else anchors -= this.counts[i] as number;
      anchors += d.points.length / 2;
    }
    if (size > MAX_DRAWINGS) return `more than ${MAX_DRAWINGS} drawings`;
    if (anchors > MAX_ANCHORS) return `more than ${MAX_ANCHORS} anchors`;
    if (!patch) this.keep(() => false);
    else if (gone.size > 0) this.keep((id) => !gone.has(id));
    for (const d of cmd.drawings) {
      const i = this.at.get(d.id) ?? this.order.length;
      if (i === this.order.length) this.at.set(d.id, i);
      this.order[i] = this.make(d);
      this.ids[i] = d.id;
      this.counts[i] = d.points.length / 2;
    }
    this.anchors = anchors;
    this.rev += 1;
    return null;
  }

  /** Compacts to the ids `keep` accepts, in order. */
  private keep(keep: (id: string) => boolean): void {
    let w = 0;
    this.at.clear();
    for (let r = 0; r < this.order.length; r += 1) {
      const id = this.ids[r] as string;
      if (!keep(id)) continue;
      this.order[w] = this.order[r] as R;
      this.ids[w] = id;
      this.counts[w] = this.counts[r] as number;
      this.at.set(id, w);
      w += 1;
    }
    this.order.length = this.ids.length = this.counts.length = w;
  }
}
