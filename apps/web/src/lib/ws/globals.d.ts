/**
 * Build-time switch for the dev-only fault-injection channel (E17-T04 S5e): `true` only in a build made with
 * `CV_ALLOW_FAULT_INJECTION=1` (see `vite.config.ts`), `false` in every other. A production build has it `false`,
 * so the worker's `import.meta.env.DEV || __CV_ALLOW_FAULT_INJECTION__` is `false` and the channel is not bundled.
 */
declare const __CV_ALLOW_FAULT_INJECTION__: boolean;

/**
 * The web app's version, `apps/web/package.json`'s `version`, substituted at build time by `define` in
 * `vite.config.ts` (and `vitest.config.mjs`). `hello` reports it and the status bar shows it (E10-S01 S4).
 */
declare const __CV_APP_VERSION__: string;
