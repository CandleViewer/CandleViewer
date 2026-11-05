// The drawing selection (E14-T04, #359; BQ-02 (a)): the worker owns one set per chart, so the
// handles, the drag and the app's tree read one truth. Keyboard and pointer reach it through the
// same operations (`focusObject` behaves as a press, BQ-05), and every change sets `dirty`, which
// the runtime turns into one edge-triggered `selection` message. Ids are drawing ids only (E11
// TM CE-I05): the E14-T02 store's stable local `Handle`, never the server id, so a selection
// survives an undone delete (ruling 6653052281, BQ-01). DOM-free.

export type SelectionOp = "replace" | "add" | "toggle" | "clear";
export type InteractionMode = "cursor" | "select-area";

export class Selection {
  private readonly set = new Set<string>();
  /** The drawing (and handle, -1 for its body) keyboard focus or the last press is on. */
  focused: string | null = null;
  handle = -1;
  mode: InteractionMode = "cursor";
  /** Viewer and view-as (D02 §5.1, T2): every edit is refused as if every drawing were locked. */
  readOnly = false;
  /** A change not yet posted. */
  dirty = false;

  get size(): number {
    return this.set.size;
  }

  has(id: string): boolean {
    return this.set.has(id);
  }

  /** The ids in selection order (a copy: it is posted). */
  ids(): string[] {
    return [...this.set];
  }

  /** `known` filters ids the engine does not hold; unknown ids are ignored, never stored. */
  apply(ids: readonly string[], op: SelectionOp, known: (id: string) => boolean): void {
    if (op === "clear" || op === "replace") {
      const next = op === "clear" ? [] : ids.filter(known);
      const same = next.length === this.set.size && next.every((id) => this.set.has(id));
      if (same) return;
      this.set.clear();
      for (const id of next) this.set.add(id);
      this.dirty = true;
      return;
    }
    for (const id of ids) {
      if (!known(id)) continue;
      if (this.set.has(id)) {
        if (op === "toggle") this.set.delete(id);
        else continue;
      } else this.set.add(id);
      this.dirty = true;
    }
  }

  /**
   * A press, or keyboard focus, on `id` (`handle` -1 for the body): an unselected drawing becomes
   * the selection, a selected one keeps the group (so a group drag can start from any member).
   * `null` drops the focus and keeps the selection.
   */
  focus(id: string | null, handle: number): void {
    if (id !== null && !this.set.has(id)) {
      this.set.clear();
      this.set.add(id);
      this.dirty = true;
    }
    const h = id === null ? -1 : handle;
    if (this.focused === id && this.handle === h) return;
    this.focused = id;
    this.handle = h;
    this.dirty = true;
  }

  /** A drawing left the engine: out of the set and the focus. */
  forget(id: string): void {
    if (this.set.delete(id)) this.dirty = true;
    if (this.focused === id) this.focus(null, -1);
  }

  setMode(mode: InteractionMode, readOnly: boolean): void {
    if (this.mode !== mode) this.dirty = true; // the event carries the mode (the rail reverts)
    this.mode = mode;
    this.readOnly = readOnly;
  }
}
