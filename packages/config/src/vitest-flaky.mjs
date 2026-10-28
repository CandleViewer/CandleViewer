// The C-9.3 quarantine modifier for Vitest (E02-T10): `it.flaky`, `test.flaky` and `describe.flaky`.
// Vitest has no such modifier; tools/ci/flaky_quarantine_report.py reads the call as the quarantine
// marker, as it reads pytest's `@pytest.mark.flaky`. A quarantined test, and every test of a
// quarantined suite, is skipped: a run reports it as skipped and never runs it. It also carries the
// `flaky` tag, so `vitest --tags-filter=flaky` lists the quarantined tests and the JSON reporter
// shows the tag on each. The call names its ticket and start date on its own line or the line above,
// `// ticket: GH-<n> quarantined: <YYYY-MM-DD>`: the report fails on a marker with no ticket, and
// tests/toolchain/pack.py on one older than 10 working days. To run one while fixing it, drop `.flaky`.
//
// The shared preset (../vitest.preset.mjs) loads this module before every test file. Vitest's
// TestAPI and SuiteAPI are type aliases that no declaration can extend, so a TypeScript test imports
// `it`, `test` or `describe` from `@candleviewer/config/vitest-flaky` for the typed modifier
// (vitest-flaky.d.mts). At runtime they are Vitest's own objects.
import { describe, it, test } from "vitest";

/** The tag of a quarantined test. The preset declares it: Vitest refuses an undeclared tag. */
export const FLAKY_TAG = "flaky";

/** Marks this module's modifier across module instances, so a second install can recognise it. */
const OURS = Symbol.for("@candleviewer/config/vitest-flaky");

/** The options of one call, quarantined: skipped, and tagged on top of any tags it had. */
const quarantine = (options) => ({
  ...options,
  skip: true,
  tags: [...[options.tags ?? []].flat(), FLAKY_TAG],
});

/**
 * Installs `api.flaky` with the plain call forms of `api` (`it`/`test` or `describe`):
 * `(name, fn?, timeout?)` and `(name, options, fn?)`. A second install of this modifier changes
 * nothing; any other `flaky` (a Vitest that ships its own, say) throws, so the clash is seen.
 */
export function installFlaky(api) {
  const current = Object.getOwnPropertyDescriptor(api, "flaky");
  if (current?.value?.[OURS] === true) return;
  if (current !== undefined) {
    throw new Error(
      "vitest-flaky: this Vitest API already has a `flaky`; review the C-9.3 modifier",
    );
  }
  const flaky = (name, optionsOrFn, fnOrTimeout) => {
    if (typeof optionsOrFn === "function" || optionsOrFn === undefined) {
      const options = typeof fnOrTimeout === "number" ? { timeout: fnOrTimeout } : {};
      return api(name, quarantine(options), optionsOrFn);
    }
    return api(name, quarantine(optionsOrFn), fnOrTimeout);
  };
  Object.defineProperty(api, "flaky", { value: Object.assign(flaky, { [OURS]: true }) });
}

installFlaky(test); // `it` is the same object
installFlaky(describe); // and so is `suite`

export { describe, it, test };
