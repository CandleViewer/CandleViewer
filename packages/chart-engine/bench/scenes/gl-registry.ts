// `gl-registry` scene (E11-S02 PR1): 1 000 GPU resources in a `GlRegistry`, each step a context
// loss (invalidate) and a restore (recreate) on an injected GL, the CPU side of the 2 s restore
// budget (30 §5.3 exit criterion 8). The unit test counts; the .perf.test.ts times.
import type { GL2Like } from "../../src/gl/gl-types.js";
import { GlRegistry, RESOURCE_KINDS } from "../../src/gl/registry.js";

export class GlRegistryBench {
  readonly registry: GlRegistry;

  /** `gl` is the fake context (test/gl/fake-gl.ts): its `lose`/`restore` model the events. */
  constructor(
    private readonly gl: GL2Like & { loseContext(): void; restoreContext(): void },
    readonly resources = 1_000,
  ) {
    this.registry = new GlRegistry(gl);
    for (let i = 0; i < resources; i += 1) {
      this.registry.create(RESOURCE_KINDS[i % RESOURCE_KINDS.length] ?? "buffer");
    }
  }

  /** One loss and restore; returns the slots left without an object (0 on success). */
  step(): number {
    this.gl.loseContext();
    this.registry.invalidateAll();
    this.gl.restoreContext();
    return this.registry.recreateAll();
  }
}
