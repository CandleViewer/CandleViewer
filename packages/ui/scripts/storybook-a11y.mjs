// E05-T03: the Storybook a11y gate's CI reports, from the storybook Vitest project's JSON report
// (`--reporter=json`), where a passed story test carries axe's results in `meta.reports`.
//   summary <results.json>              story counts, axe violations by impact, failing rules;
//                                       exit 1 if no story passed (the gate checked nothing)
//   selftest <fixtures.json> <status>   exit 0 only if the run on `.storybook/__fixtures__/`
//                                       (CV_STORYBOOK_A11Y_FIXTURES=1) failed closed: every
//                                       fixture story failed, each naming its rule and element

import { readFileSync } from "node:fs";
import { stripVTControlCharacters } from "node:util";

const [command, file = "", status] = process.argv.slice(2);
/** Each story test: id, status, failure text and axe's violations (none where axe did not run). */
const tests = JSON.parse(readFileSync(file, "utf-8")).testResults.flatMap((result) =>
  result.assertionResults.map((test) => ({
    id: test.meta?.storyId ?? test.fullName,
    status: test.status,
    message: stripVTControlCharacters((test.failureMessages ?? []).join("\n")),
    violations: (test.meta?.reports ?? []).flatMap((report) =>
      report.type === "a11y" ? (report.result?.violations ?? []) : [],
    ),
  })),
);
const count = (...states) => tests.filter((test) => states.includes(test.status)).length;
/** A failed story has no axe report; its failure names each rule as `"<help> (<rule id>)"`. */
const RULE = /Received:\s+"[^"\n]*\(([\w-]+)\)"/g;
/**
 * The fixture stories and what each failure must name: the 2:1-contrast button (E05-T03), in every
 * fixture run, and the icon-only button without an aria-label (E05-T06), whenever the run has it.
 * Its fixture file is linted by test/eslint-rules/icon-a11y.test.ts, so it cannot vanish unseen.
 */
const FIXTURES = [
  {
    story: "--low-contrast-button",
    what: "the 2:1-contrast button",
    names: ["(color-contrast)", "#a11y-gate-fixture"],
    always: true,
  },
  {
    story: "--icon-only-button-without-label",
    what: "the unlabelled icon-only button",
    names: ["(button-name)", "#icon-only-gate-fixture"],
    always: false,
  },
];

if (command === "summary") {
  const found = tests.flatMap((test) => test.violations);
  const impacts = ["critical", "serious", "moderate", "minor"].map(
    (impact) => `${impact} ${found.filter((v) => v.impact === impact).length}`,
  );
  // Each failed story's rules, once per story: the violations that failed the gate.
  const blocking = tests.flatMap((test) => [
    ...new Set(Array.from(test.message.matchAll(RULE), ([, rule]) => rule)),
  ]);
  console.log(
    `- Storybook stories: ${tests.length} (${count("passed")} passed, ${count("failed")} failed, ` +
      `${count("skipped", "pending", "todo")} skipped)\n` +
      `- axe violations by impact in passed stories: ${impacts.join(", ")}\n` +
      `- blocking axe violations in failed stories: ${blocking.length}` +
      (blocking.length > 0 ? ` (${[...new Set(blocking)].join(", ")})` : ""),
  );
  // Fail closed on a run that checked nothing: Vitest exits 0 when every story is skipped.
  if (count("passed") === 0) {
    console.log("- no story passed: the gate checked nothing");
    process.exitCode = 1;
  }
} else if (command === "selftest") {
  // The gate failed closed if every fixture story failed it, each naming its rule and element.
  const problems = status === "0" ? ["the fixture run passed: the gate is blind"] : [];
  for (const test of tests) {
    if (test.status !== "failed") problems.push(`fixture story ${test.id} did not fail`);
  }
  for (const { story, what, names, always } of FIXTURES) {
    const fixture = tests.find((test) => test.id.endsWith(story));
    if (!fixture && !always) continue;
    if (fixture?.status !== "failed") problems.push(`${what} did not fail`);
    for (const name of names) {
      if (!fixture?.message.includes(name)) {
        problems.push(`${what}'s failure does not name ${name}`);
      }
    }
  }
  for (const problem of problems) console.error(`a11y gate self-test: ${problem}`);
  process.exitCode = problems.length === 0 ? 0 : 1;
} else {
  throw new Error("usage: storybook-a11y.mjs summary <results.json> | selftest <json> <status>");
}
