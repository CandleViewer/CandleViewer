// @vitest-environment node
// CV_FUZZ_SECONDS is a finite number of seconds or the fuzz file refuses to load (#415, E17-X02): an
// infinite box would be an endless loop, a negative one no box at all. Node, not jsdom:
// the fuzz file builds its corpus path from `import.meta.url`.
import { afterEach, expect, it, vi } from "vitest";

afterEach(() => void vi.unstubAllEnvs());

it.each(["Infinity", "-1", "abc"])("a time box of %s fails the fuzz file at load", async (box) => {
  vi.stubEnv("CV_FUZZ_SECONDS", box);
  vi.resetModules();
  await expect(import("./codec.fuzz.test")).rejects.toThrow(/CV_FUZZ_SECONDS must be a finite/);
});
