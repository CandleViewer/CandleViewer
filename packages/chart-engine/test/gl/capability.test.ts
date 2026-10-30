// E11-S02 S3 and the context acquisition: the BQ-50 decision matrix over synthetic caps, the probe
// over a fake GL, and the attributes a browser grants rather than those asked for (BQ-62).
import { describe, expect, it } from "vitest";
import {
  FAILED_CONTEXT_REASON,
  NO_WEBGL2_REASON,
  probeCanvas,
  probeCapabilities,
  selectProfile,
  type GlCaps,
} from "../../src/gl/capability.js";
import { acquireContext, CONTEXT_ATTRIBUTES } from "../../src/gl/context.js";
import { GL } from "../../src/gl/gl-types.js";
import { FakeGl, ROOMY } from "./fake-gl.js";

const FLOORS = { maxTextureSize: 4096, maxVertexAttribs: 16, maxTextureImageUnits: 8 };
const caps = (over: Partial<GlCaps> = {}): GlCaps => ({
  ...FLOORS,
  extensions: [],
  renderer: null,
  ...over,
});
const why = (what: string, v: number, floor: number): string =>
  Number.isFinite(v)
    ? `Reduced detail: the GPU's ${what} is ${v}, under ${floor}.`
    : `Reduced detail: the GPU did not report its ${what}.`;

describe("Scenario: Capability probing selects a profile instead of crashing", () => {
  it.each([
    ["every floor met exactly", caps(), "full", []],
    ["float extensions missing", caps({ extensions: [] }), "full", []],
    [
      "MAX_TEXTURE_SIZE below the atlas requirement",
      caps({ maxTextureSize: 2048 }),
      "reduced",
      [why("largest texture", 2048, 4096)],
    ],
    [
      "MAX_TEXTURE_SIZE one under",
      caps({ maxTextureSize: 4095 }),
      "reduced",
      [why("largest texture", 4095, 4096)],
    ],
    [
      "MAX_VERTEX_ATTRIBS one under",
      caps({ maxVertexAttribs: 15 }),
      "reduced",
      [why("vertex attribute count", 15, 16)],
    ],
    [
      "MAX_TEXTURE_IMAGE_UNITS one under and a NaN limit",
      caps({ maxTextureImageUnits: 7, maxTextureSize: Number.NaN }),
      "reduced",
      [why("largest texture", Number.NaN, 4096), why("texture unit count", 7, 8)],
    ],
    ["no WebGL2", null, "degraded-2d", [NO_WEBGL2_REASON]],
  ])("%s", (_name, input, profile, reasons) => {
    expect(selectProfile(input)).toEqual({ profile, reasons, caps: input });
    for (const r of reasons) expect(r).toMatch(/^[A-Z][^\n]*\.$/); // one plain sentence each
  });

  it("probes limits, the recorded extensions and the unmasked renderer off a context", () => {
    const gl = new FakeGl({
      params: { ...ROOMY, [GL.MAX_TEXTURE_SIZE]: 2048, [GL.UNMASKED_RENDERER_WEBGL]: "GPU X" },
      extensions: { EXT_color_buffer_float: {}, WEBGL_debug_renderer_info: {} },
    });
    expect(probeCapabilities(gl)).toEqual({
      profile: "reduced",
      reasons: [why("largest texture", 2048, 4096)],
      caps: caps({
        maxTextureSize: 2048,
        maxTextureImageUnits: 16,
        extensions: ["EXT_color_buffer_float"],
        renderer: "GPU X",
      }),
    });
  });

  it("never crashes: missing limits, a lost context and a throwing driver all report", () => {
    expect(probeCapabilities(new FakeGl()).profile).toBe("reduced"); // unreported limits: NaN
    const lost = new FakeGl({ params: ROOMY });
    lost.loseContext();
    expect(probeCapabilities(lost).reasons).toEqual([FAILED_CONTEXT_REASON]);
    const faulty = new FakeGl({ params: ROOMY });
    faulty.failAt = 2;
    const failed = { profile: "degraded-2d", reasons: [FAILED_CONTEXT_REASON], caps: null };
    expect(probeCapabilities(faulty)).toEqual(failed);
    expect(probeCapabilities(null).profile).toBe("degraded-2d");
  });

  it("probes a throwaway canvas and releases its context at once", () => {
    const gl = new FakeGl({ params: ROOMY });
    expect(probeCanvas({ getContext: () => gl }).profile).toBe("full");
    expect(gl.lost).toBe(true);
    expect(probeCanvas({ getContext: () => null }).profile).toBe("degraded-2d");
  });
});

describe("WebGL2 context acquisition (BQ-62)", () => {
  it("asks for the E10 attributes and records what the browser granted", () => {
    const asked: unknown[] = [];
    const granted = { antialias: false, desynchronized: false }; // a hint ignored
    const gl = new FakeGl({ attributes: granted });
    const got = acquireContext({ getContext: (_id, attrs) => (asked.push(attrs), gl) });
    expect(asked).toEqual([CONTEXT_ATTRIBUTES]);
    expect(got).toEqual({ gl, attributes: granted });
  });

  it("returns null without WebGL2, on a non-GL answer or a throw; a lost one records {}", () => {
    expect(acquireContext({ getContext: () => null })).toBeNull();
    expect(acquireContext({ getContext: () => ({}) })).toBeNull();
    const unsupported = (): never => {
      throw new TypeError("unsupported attribute");
    };
    expect(acquireContext({ getContext: unsupported })).toBeNull();
    const lost = new FakeGl();
    lost.loseContext();
    expect(acquireContext({ getContext: () => lost })?.attributes).toEqual({});
  });
});
