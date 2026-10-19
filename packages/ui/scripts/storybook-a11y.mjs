// E05-T03: the Storybook a11y gate's CI reports, read from the storybook Vitest project's JSON report
// (`--reporter=json`), whose story tests carry axe's results in `meta.reports`.
//   summary <results.json>              story counts and axe violations by impact
//   selftest <fixtures.json> <status>   exit 0 only if the run on `.storybook/__fixtures__/`
//                                       (CV_STORYBOOK_A11Y_FIXTURES=1) failed closed

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

if (command === "summary") {
  const found = tests.flatMap((test) => test.violations);
  const impacts = ["critical", "serious", "moderate", "minor"].map(
    (impact) => `${impact} ${found.filter((v) => v.impact === impact).length}`,
  );
  console.log(
    `- Storybook stories: ${tests.length} (${count("passed")} passed, ${count("failed")} failed, ` +
      `${count("skipped", "pending", "todo")} skipped)\n` +
      `- axe violations by impact: ${impacts.join(", ")} (a failed story's are in its failure)`,
  );
} else if (command === "selftest") {
  // The gate failed closed if the 2:1-contrast button failed it naming the rule and the element.
  const button = tests.find((test) => test.id.endsWith("--low-contrast-button"));
  const problems = status === "0" ? ["the fixture run passed: the gate is blind"] : [];
  if (button?.status !== "failed") problems.push("the 2:1-contrast button did not fail");
  for (const name of ["(color-contrast)", "#a11y-gate-fixture"]) {
    if (!button?.message.includes(name)) problems.push(`its failure does not name ${name}`);
  }
  for (const problem of problems) console.error(`a11y gate self-test: ${problem}`);
  process.exitCode = problems.length === 0 ? 0 : 1;
} else {
  throw new Error("usage: storybook-a11y.mjs summary <results.json> | selftest <json> <status>");
}
