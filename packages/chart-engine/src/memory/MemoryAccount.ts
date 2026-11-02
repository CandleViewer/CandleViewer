// MemoryAccount (26 §7, E11-S15 BQ-S15-01): the per-chart sum the memory governor samples. Sources
// register `{ id, bytes() }`: the GL buffers and textures and the default framebuffer now (the
// worker runtime), each store when its owner wires it into the worker. Summing walks a fixed array:
// no allocation per sample.
// TODO(E12-S06 #399): register the BarStore here when it joins the worker's data path; E18 the
// FootprintStore and E21 the HeatmapRing, the same way.

/** One counted holder of memory: `bytes()` is what it holds now, never negative. */
export interface MemorySource {
  readonly id: string;
  bytes(): number;
}

const MIB = 2 ** 20;

export class MemoryAccount {
  private readonly sources: MemorySource[] = [];

  /** Adds `source`, replacing one with the same id; returns the function that removes it. */
  register(source: MemorySource): () => void {
    this.unregister(source.id);
    this.sources.push(source);
    return () => {
      const i = this.sources.indexOf(source);
      if (i >= 0) this.sources.splice(i, 1);
    };
  }

  /** Removes the source registered under `id`; false when there is none. */
  unregister(id: string): boolean {
    const i = this.sources.findIndex((s) => s.id === id);
    if (i < 0) return false;
    this.sources.splice(i, 1);
    return true;
  }

  /** The ids registered, in registration order (tests and diagnostics). It allocates: never read
   * it on a sample path (`MemorySampler` reads `totalBytes` only). */
  get ids(): readonly string[] {
    return this.sources.map((s) => s.id);
  }

  /** The bytes every source holds now. A source reporting a non-finite or negative figure counts 0. */
  get totalBytes(): number {
    let sum = 0;
    for (let i = 0; i < this.sources.length; i += 1) {
      const b = (this.sources[i] as MemorySource).bytes();
      if (Number.isFinite(b) && b > 0) sum += b;
    }
    return sum;
  }

  /** `totalBytes` in MiB, the unit of `memoryBudgetMb` (`frame.memory.usedMb`, §6). */
  get usedMb(): number {
    return this.totalBytes / MIB;
  }
}
