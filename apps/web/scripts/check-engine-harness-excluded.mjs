// E11-Q02 (#444, Security notes): the engine E2E harness exposes engine internals on `window`, so it
// must not ship. Fails when a built bundle holds a harness marker; source maps are skipped (they carry
// main.tsx, which names the route by design).
// Usage: node scripts/check-engine-harness-excluded.mjs [distDir]   (default: dist)
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

export const HARNESS_MARKER = /__engine/u; // __engineEvents, __engine-feed: the page contract's names
const SERVED = /\.(?:js|mjs|html|css)$/u;

/** @param {readonly { name: string; text: string }[]} files @returns {string[]} one line per leak */
export function findHarnessLeaks(files) {
  return files
    .filter(({ name, text }) => SERVED.test(name) && HARNESS_MARKER.test(text))
    .map(({ name }) => `${name}: contains an __engine* marker`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dist = resolve(process.argv[2] ?? "dist");
  const files = readdirSync(dist, { recursive: true, encoding: "utf8" })
    .filter((f) => SERVED.test(f))
    .map((f) => ({ name: f, text: readFileSync(join(dist, f), "utf8") }));
  if (files.length === 0) {
    process.stderr.write(`check-engine-harness-excluded: no built files under ${dist}\n`);
    process.exit(2);
  }
  const leaks = findHarnessLeaks(files);
  if (leaks.length > 0) {
    process.stderr.write(
      `engine harness leaked into a production build (E11-Q02):\n${leaks.join("\n")}\n`,
    );
    process.exit(1);
  }
  process.stdout.write(`engine harness absent from ${files.length} built files\n`);
}
