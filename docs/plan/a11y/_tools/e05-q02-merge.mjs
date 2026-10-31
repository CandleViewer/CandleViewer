// E05-Q02 (#262): merge the per-story axe results (<out>/stories/*.json, <out>/manifest.json) of one or more
// A11Y_OUT dirs into results.json and summary.md in the first dir. Fails if a manifest story has no file.
// Usage: node e05-q02-merge.mjs [--strict] [outDir ...]   (default A11Y_OUT or <os temp>/e05-q02-ds)
// One A11Y_OUT per shard (never shared: the control wipes its stories/ dir). Fails (exit 1) on: no manifest,
// empty story list, manifests that disagree on sha/stories/themes/densities, a duplicate or missing story
// file, a story whose cell count differs from themes x densities x (1 if it pins motion, else 2), off-site
// requests, errored cells. --strict also exits 1 on any serious/critical violation.
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = process.argv.slice(2);
const strict = args.includes("--strict");
const paths = args.filter((a) => a !== "--strict");
const dirs = paths.length > 0 ? paths : [process.env.A11Y_OUT ?? join(tmpdir(), "e05-q02-ds")];
const IMPACTS = ["critical", "serious", "moderate", "minor"];
const PAGE_LEVEL = ["landmark-one-main", "page-has-heading-one", "region"];
const manifests = dirs.map((d) => join(d, "manifest.json")).filter(existsSync);
if (manifests.length === 0) {
  console.error("A11Y-INFRA: no manifest.json (the negative control did not run)");
  process.exit(1);
}
const all = manifests.map((m) => JSON.parse(readFileSync(m, "utf8")));
const manifest = all[0];
const problems = [];
if (manifests.length !== dirs.length) problems.push("a dir has no manifest.json");
for (const m of all) {
  for (const k of ["sha", "stories", "themes", "densities"]) {
    if (JSON.stringify(m[k]) !== JSON.stringify(manifest[k]))
      problems.push(`manifests disagree on ${k}`);
  }
}
if (manifest.stories.length === 0) problems.push("the manifest story list is empty");
const byId = new Map();
for (const d of dirs) {
  const sd = join(d, "stories");
  if (!existsSync(sd)) continue;
  for (const f of readdirSync(sd).filter((x) => x.endsWith(".json"))) {
    const s = JSON.parse(readFileSync(join(sd, f), "utf8"));
    if (byId.has(s.id)) problems.push(`duplicate story file ${s.id}`);
    byId.set(s.id, s);
  }
}
// Under --shard each shard runs a subset, so the union over all given dirs must cover the manifest.
const missing = manifest.stories.filter((id) => !byId.has(id));
const listed = new Set(manifest.stories);
for (const id of byId.keys())
  if (!listed.has(id)) problems.push(`story file ${id} is not in the manifest`);
const perStory = (manifest.themes?.length ?? 0) * (manifest.densities?.length ?? 0);
for (const id of manifest.stories) {
  const s = byId.get(id);
  if (s === undefined) continue;
  const want = perStory * (s.pinned ? 1 : (manifest.motions?.length ?? 2));
  if (want === 0) {
    problems.push(
      `${id}: the expected cell count is 0 (themes / densities / motions empty: check A11Y_THEMES and A11Y_DENSITIES)`,
    );
  } else if (s.cells.length !== want) {
    problems.push(`${id}: ${s.cells.length} cells, expected ${want}`);
  }
}
const cells = manifest.stories.flatMap((id) => byId.get(id)?.cells ?? []);
const offsite = [...byId.values()].flatMap((s) => s.offsite);
const total = Object.fromEntries(IMPACTS.map((i) => [i, 0]));
for (const c of cells) for (const i of IMPACTS) total[i] += c.counts[i];
const failed = cells.filter((c) => c.error !== undefined);
const control = manifest.negativeControl;
const out = dirs[0];
writeFileSync(
  join(out, "results.json"),
  JSON.stringify(
    {
      sha: manifest.sha,
      stories: manifest.stories.length,
      excluded: manifest.excluded,
      negativeControl: control,
      total,
      offsite,
      missing,
      cells,
    },
    null,
    2,
  ),
);
const rows = cells
  .filter((c) => c.error !== undefined || IMPACTS.some((i) => c.counts[i] > 0))
  .map(
    (c) =>
      `| ${c.story} | ${c.theme} | ${c.density} | ${c.motion} | ${IMPACTS.map((i) => c.counts[i]).join(" / ")} | ${c.error ?? [...new Set(c.violations.map((v) => v.id))].join(", ")} |`,
  );
writeFileSync(
  join(out, "summary.md"),
  [
    `Stories ${manifest.stories.length} (excluded perf: ${manifest.excluded.length}), cells ${cells.length}, errored ${failed.length}, off-site requests ${offsite.length}, missing story files ${missing.length}`,
    `Violations: ${IMPACTS.map((i) => `${i} ${total[i]}`).join(", ")}`,
    `Negative control: ${control.tripped ? "tripped" : "NOT tripped"} (${control.rules.join(", ")})`,
    `Disabled page-level rules: ${PAGE_LEVEL.join(", ")} (a lone component in the isolated iframe has no main landmark, h1 or region; the screens sweep, E47, covers them)`,
    "",
    "| story | theme | density | motion | crit / ser / mod / min | rules or error |",
    "|---|---|---|---|---|---|",
    ...rows,
    "",
  ].join("\n"),
);
if (missing.length > 0) {
  console.error(
    `A11Y-INFRA: ${missing.length} story file(s) missing: ${missing.slice(0, 5).join(", ")}`,
  );
  process.exit(1);
}
if (problems.length > 0) {
  const unique = [...new Set(problems)];
  const more = unique.length > 5 ? ` (+${unique.length - 5} more)` : "";
  console.error(`A11Y-INFRA: ${unique.slice(0, 5).join("; ")}${more}`);
  process.exit(1);
}
if (offsite.length > 0 || failed.length > 0) process.exit(1);
if (strict && (total.critical > 0 || total.serious > 0)) {
  console.error(`strict: ${total.critical} critical, ${total.serious} serious violation(s)`);
  process.exit(1);
}
console.log(`merged ${cells.length} cells from ${byId.size} stories into ${out}`);
