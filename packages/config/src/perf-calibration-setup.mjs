import console from "node:console";
import { afterEach } from "vitest";
import { attemptLine, retryWarning, summary, takeLastAssertion } from "./perf-calibration.mjs";

// vitest setupFiles for the perf projects: calibrate once per test file BEFORE any timed region, and
// print the one calibration line the CI log is read from.
console.info(summary());

// The perf projects retry a failed wall-clock test twice (C-9.3). A retry is never silent: every
// attempt prints its measured / calibration / bound, and a pass on a retry emits a warning
// annotation. The bound itself never moves by retry.
afterEach(({ task }) => {
  const attempt = (task.result?.retryCount ?? 0) + 1;
  const state = task.result?.state ?? "unknown";
  const seen = takeLastAssertion();
  console.info(attemptLine(task.name, attempt, state, seen));
  if (attempt > 1 && state !== "fail") {
    console.info(retryWarning(task.name, attempt, seen?.measured, seen?.calibration, seen?.bound));
  }
});
