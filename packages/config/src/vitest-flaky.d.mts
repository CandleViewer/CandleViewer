// Types for vitest-flaky.mjs: Vitest's `it`, `test` and `describe`, each with the C-9.3 quarantine
// modifier. @vitest/runner declares TestAPI and SuiteAPI as type aliases over interfaces it does not
// export, so no module augmentation can add `flaky` to them: a TypeScript test imports these three
// from `@candleviewer/config/vitest-flaky` instead of from `vitest`.
import type {
  SuiteAPI,
  SuiteCollector,
  SuiteFactory,
  SuiteOptions,
  TestAPI,
  TestFunction,
  TestOptions,
} from "vitest";

/** The options a quarantine takes. It is always skipped, so `only`, `skip` and `todo` are refused. */
type Quarantined<Options> = Omit<Options, "only" | "skip" | "todo">;

/** `it.flaky` and `test.flaky`: the call forms of `it`; the test is skipped and tagged `flaky`. */
export interface FlakyTest {
  (name: string, fn?: TestFunction, timeout?: number): void;
  (name: string, options: Quarantined<TestOptions>, fn?: TestFunction): void;
}

/** `describe.flaky`: the call forms of `describe`; the suite and each test in it are skipped and tagged. */
export interface FlakySuite {
  (name: string, factory?: SuiteFactory, timeout?: number): SuiteCollector;
  (name: string, options: Quarantined<SuiteOptions>, factory?: SuiteFactory): SuiteCollector;
}

/** The tag of a quarantined test, which the shared preset declares. */
export declare const FLAKY_TAG: "flaky";

/** Installs `flaky` on a Vitest test or suite API once; throws on an API that has another `flaky`. */
export declare function installFlaky(api: TestAPI | SuiteAPI): void;

export declare const it: TestAPI & { readonly flaky: FlakyTest };
export declare const test: TestAPI & { readonly flaky: FlakyTest };
export declare const describe: SuiteAPI & { readonly flaky: FlakySuite };
