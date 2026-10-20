// Decode the golden CVWB vectors with the k6 client's port and fail on any mismatch (23 3.4).
//   node tests/load/ws/lib/cvwb.check.mjs [path/to/vectors.json]
// k6's setup() runs the same `checkVectors`; this is the same check without k6 (the unit tests run it).
/* global URL, process, console */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { checkVectors } from "./cvwb.js";

const here = fileURLToPath(new URL(".", import.meta.url));
const path = process.argv[2] ?? `${here}../../../../packages/fixtures/golden/cvwb/vectors.json`;
const vectors = JSON.parse(readFileSync(path, "utf8"));
const bad = checkVectors(vectors);
if (bad.length > 0) {
  console.error(bad.join("\n"));
  process.exit(1);
}
console.log(`cvwb: ${vectors.length} golden vectors decode as the production decoder reads them`);
