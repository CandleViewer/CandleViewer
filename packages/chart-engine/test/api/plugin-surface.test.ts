// E12-S06 (BQ-2, additive): the series-plugin extension type-checks against §8 (enforced by tsc
// over test/ in `pnpm typecheck`). The host node is a whole `RenderContext`, any `SeriesPlugin`
// fits the host, and the root surface gained no symbol (test/api/surface.test.ts).
import { describe, expect, expectTypeOf, it } from "vitest";
import type { RenderContext, SeriesPlugin } from "../../src/index.js";
import type { HostedPlugin, SeriesHost } from "../../src/layers/index.js";
import type { DataRange, InstanceRing, SeriesProjection } from "../../src/layers/plugin-api.js";

describe("series-plugin extension (BQ-2)", () => {
  it("SeriesHost is a RenderContext; a SeriesPlugin is a HostedPlugin", () => {
    expectTypeOf<SeriesHost>().toExtend<RenderContext>();
    expectTypeOf<SeriesPlugin<unknown, unknown>>().toExtend<HostedPlugin>();
    expectTypeOf<RenderContext["instances"]>().parameters.toEqualTypeOf<
      [InstanceRing, "candle", number]
    >();
    expectTypeOf<RenderContext["projection"]>().toEqualTypeOf<SeriesProjection>();
    expectTypeOf<NonNullable<SeriesPlugin<unknown, unknown>["onMutation"]>>()
      .parameter(1)
      .toEqualTypeOf<DataRange>();
    expect(true).toBe(true);
  });
});
