// E49-Q01 GA regression pack (#1335 BQ-6): every `@ga-regression` web spec takes `test` and
// `expect` from here, so it runs behind the one egress guard (`@candleviewer/fixtures/e2e`'s
// `guardContextEgress`, applied as the shell suite's auto-fixture). This re-exports that fixture
// instead of declaring a second one. `test/e2e-egress.test.ts` fails a pack spec that takes `test`
// from anywhere else.
export { expect, test } from "../shell/fixtures";
