// E11-X02 (CE-T20): no runtime dependency enters the engine. Whatever it bundles runs in the
// worker inside the trading origin, so the package ships its own code only; build and test tools
// stay devDependencies. A new runtime edge needs an ADR and a C-12.3 dependency review first.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const manifest = JSON.parse(readFileSync(join(PKG, "package.json"), "utf8")) as Record<
  string,
  unknown
>;

describe("Scenario: The engine package has no runtime dependencies", () => {
  it.each([
    "dependencies",
    "peerDependencies",
    "optionalDependencies",
    "bundleDependencies",
    "bundledDependencies",
  ])("package.json declares no %s", (field) => {
    expect(manifest[field]).toBeUndefined();
  });
});
