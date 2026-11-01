# @candleviewer/ui

Design system: tokens, primitives, trading components. Storybook 10 with the
a11y addon; Style Dictionary token build. Depends only on
`@candleviewer/protocol` and `@candleviewer/chart-engine` — never on `apps/*`
(C-3.5).

- `tokens/` — DTCG source JSON (contract from E02-D01, content from E05-D01),
  verified by `tokens/tests/verify_tokens.py`.
- `src/tokens/`, `src/primitives/`, `src/components/` — TS/React surface.
- `scripts/build-tokens.mjs` — the token build entry point (E05-T01).
- `scripts/token-css.mjs` — how a token becomes CSS (a shadow as a `box-shadow` list, a typography
  token as one custom property per field) and the esbuild check of each written CSS file (#3422).
- `build/` — generated artefacts, **gitignored, never committed**. CI
  regenerates them on every run: the `js` lane's `build` job builds this
  package (which runs `pnpm --filter @candleviewer/ui build:tokens`) and then
  `contrast:gate`, and the unit lane's `test/tokens-build/*` tests run the real
  build and pin its artefacts (see "Build output policy" below).

Architectural record: [`docs/plan/27-adrs/ADR-0024-design-token-architecture-and-theming.md`](../../docs/plan/27-adrs/ADR-0024-design-token-architecture-and-theming.md)
records the tier model, theming/density decisions and the WebGL/Electron delivery
formats below, plus the alternatives rejected (CSS-in-JS runtime theming,
Tailwind-config-as-source, two parallel density scales, naive dark→light inversion).

## Token build (E05-T01)

One `pnpm --filter @candleviewer/ui build:tokens` run produces these artefacts
from `docs/plan/16-design-system-brief.md#11`:

| Artefact                                   | Format                                                            | Consumer                 |
| ------------------------------------------ | ----------------------------------------------------------------- | ------------------------ |
| `build/css/tokens.dark.css`                | `[data-theme="dark"]` custom properties                           | React app                |
| `build/css/tokens.light.css`               | `[data-theme="light"]` custom properties                          | React app                |
| `build/css/tokens.high-contrast.css`       | `[data-theme="high-contrast"]` custom properties                  | React app                |
| `build/ts/tokens.ts`                       | typed nested `const tokens = {...} as const`                      | React, Storybook         |
| `build/engine/theme-uniforms.<theme>.json` | flat `{ hex, rgba }` per chart-category token, one file per theme | WebGL chart engine (E11) |
| `build/engine/theme-uniforms.json`         | the dark export under its original name                           | WebGL chart engine (E11) |
| `build/electron/tokens.main.json`          | flat key→value JSON, no CSS/TS syntax                             | Electron main process    |

Custom Style Dictionary formats (`json/flat-rgba`, `json/flat`,
`typescript/nested-object`) live in `tools/style-dictionary/formats/` with
their own Vitest unit tests in `packages/ui/test/tokens-build/` (run as part
of `pnpm --filter @candleviewer/ui test`).

**Engine colour contract**: every `theme-uniforms.json` entry is `{ hex,
rgba }`, where `rgba` is **sRGB 0..1** floats (not linear — conversion to
linear happens in the shader, per the brief §11.1 so E11 never guesses).

**Determinism**: no timestamps in output headers; every object/array is
name-sorted before serialisation; `style-dictionary` is pinned in the
lockfile. Two consecutive builds are byte-identical (asserted by
`packages/ui/test/tokens-build/build-integration.test.ts`).

**Error codes** (thrown by `scripts/build-tokens.mjs`, caught by CI):

- `TOKENS-E001 missing-theme-parity` — a token defined in one theme but
  absent from another; the error names the token.
- `TOKENS-E002 unresolved alias reference` — a `{token.path}` that never
  resolves to a primitive (dangling or circular).
- `TOKENS-E003 unknown category for the engine filter` — a
  `color.chart.*`/`color.candle.*`/etc. token whose resolved value isn't a
  hex colour string.
- `TOKENS-E004 invalid CSS output` — a token that `scripts/token-css.mjs` cannot write (an
  unknown or missing shadow or typography field, a length or `inset` with no CSS form, an object of
  any other type) or will not let the browser misread (a name with a character other than a letter,
  a digit, `_`, `-` or `.`; a value with `;`, a brace, a comment delimiter, a control character, a
  trailing backslash, a `!` or brackets that do not pair up), or a theme's CSS that esbuild, the
  production minifier, warns about or minifies to an empty custom property, checked before
  `build/css/tokens.<theme>.css` is written; the error names the token or the custom property.

**Build output policy**: `build/` is gitignored. The build must be
deterministic and fast enough (`<=10s` locally) to run on every `pnpm dev`
start, so nothing is checked in and there is no stale committed artefact to
diff against, by design. The guards over a token change are the ones
`docs/plan/16-design-system-brief.md` §11 lists: the `js` lane's `build` job
(package build, then `contrast:gate`), the a11y lane's second `contrast:gate`
run before Storybook, and the unit lane's `test/tokens-build/*` tests, which
run the real build and pin a resolved value. The generated-code freshness gate
(`tools/ci/check_gen_freshness.py`) covers the protocol, CVWB and policy
generators, not these tokens.

**Raw-value lint**: `packages/ui/src/**` may not hardcode a hex colour or a
raw `px` length — use a token from `build/ts/tokens.ts` instead
(`eslint.config.mjs`'s `candleviewer/no-raw-design-values` rule; the token
source files themselves are exempt).

## Changing a token (contributing)

Every token change, in either direction, follows the runbook in
[`docs/plan/16-design-system-brief.md` §11](../../docs/plan/16-design-system-brief.md#11-handoff-spec-tokens-json--code-via-style-dictionary)
(E05-D06): §11.2 design → code (Penpot token sets → `tokens/*.tokens.json` → PR → gates →
`tokens/CHANGELOG.md` version bump), §11.3 code → design (a token an engineer discovers during
implementation, and how it is re-imported into Penpot), §11.4 the per-component handoff
checklist, §11.5 change control and arbitration, §11.6 secrets. The short form for an engineer:

1. Edit `tokens/primitives.tokens.json` (a value) or `tokens/semantic-dark.tokens.json` (a new
   alias, `category.subcategory.variant.state`, leaf `.default` when the path has children). A new
   name needs no light/high-contrast line unless those themes want a different value
   (`TOKENS-E001` names a missing one).
2. A new `color.*` token needs a pair in `tools/contrast/pairs.mjs` or an exemption with `reason`
   and `owner` in `tools/contrast/exemptions.json` (`A11Y-C002` otherwise); a new directional or
   status encoding needs its surfaces in `tools/contrast/encodings.json` (`A11Y-C008`).
3. Run `pnpm --filter @candleviewer/ui build:tokens`, then
   `pnpm --filter @candleviewer/ui contrast:gate`. On `A11Y-C007` run
   `pnpm --filter @candleviewer/ui contrast:data-ink` and commit `contrast/data-ink-matrix.{json,md}`.
   Then `python3 tokens/tests/verify_tokens.py` and `pnpm --filter @candleviewer/ui test`: a value
   pinned in `test/tokens-build/build-integration.test.ts` moves with the token, never the reverse.
4. Add a `## [x.y.z] - <date>` entry to `tokens/CHANGELOG.md` (pre-1.0, C-15.5: PATCH = retune or
   new name, MINOR = rename or removal, with `!` and a `BREAKING CHANGE:` footer; MAJOR only from
   1.0.0), commit `feat(design-system): …` and open the PR with the contrast report and the Penpot
   page link (§11.2 steps 7–9). CI adds `security-review` by itself (the token file names match
   C-10.2's `*token*`): leave it on; the second review is the `security-reviewer` (§11.2 step 11).
5. Never commit `build/`, never add to `tools/contrast/data-ink-baseline.json`, never lower a
   threshold, and never put a credential in a token file (§11.6).

## Theme runtime (E05-T02)

`src/theme/` owns the `data-theme`, `data-density`, `data-motion` and `data-text-scale` root attributes
that the token CSS and `src/theme/theme.css` key off. They are written on `document.documentElement` only
(never a React-owned wrapper), so a switch is a CSS custom-property swap with no remount. Contract and
event payload: [`16-design-system-brief.md` §4](../../docs/plan/16-design-system-brief.md).

- `createThemeStore()` — framework-free store: persistence (`localStorage["cv.theme.v1"]`), OS media
  listeners, the `candleviewer:themechange` event, an injectable analytics sink (`onAnalytics`).
- `ThemeProvider`, `useTheme`, `useDensity`, `useReducedMotion`, `useTextScale` — React bindings over
  `useSyncExternalStore`: only components that read a value re-render when it changes.
- `THEME_PREPAINT_SCRIPT` + `THEME_PREPAINT_SCRIPT_SHA256` — the synchronous no-flash snippet. The shell
  embeds it byte-for-byte as its only inline script and allows it by hash (a `'sha256-…'` source in
  `script-src`), never `'unsafe-inline'`.
- `HIGH_CONTRAST_SHORTCUT` (`Ctrl+Shift+H`) and `toggleHighContrastAnnounced` — the shortcut contract the
  E10 hotkey registry calls (it must ignore key auto-repeat: `ignoreRepeat`, the `repeat` option); each
  toggle is announced through one polite live region that the provider pre-renders (bootstraps without
  the provider, like the E10 registry, call `mountLiveRegion()` at startup).
- `theme.css` — density pointers (any element with `data-density` re-points its subtree), the text-scale
  rules (root font size and `--cv-text-scale`), the `--cv-motion-scale` hook (the motion recipes are
  `TODO(#3174, blocked by #162)`) and the `[data-motion="reduce"]` / `prefers-reduced-motion` blocks.
  Apps import the token CSS and then `theme.css` through the package exports:
  `import "@candleviewer/ui/tokens.dark.css"` (likewise `tokens.light.css` and `tokens.high-contrast.css`),
  then `import "@candleviewer/ui/theme.css"`. They are built files in `dist/`, so a build comes first:
  `pnpm --filter @candleviewer/ui build`, or `node scripts/build-tokens.mjs && node scripts/copy-css.mjs`
  in `packages/ui` (the copy fails when a token CSS file is missing; the `apps/web` resolve test runs both
  itself when `dist/` lacks them). A bundler alias for `@candleviewer/ui` must match the entry exactly
  (`/^@candleviewer\/ui$/`); a prefix alias turns these subpaths into `src/index.ts/theme.css`.
- Storybook: run `build:tokens` first; the Theme / Density / Motion toolbars drive the runtime.
- Apps feed server-side preferences in through `store.apply(...)`; `applyAppearance` and the
  `a11y-preferences` feature should call it rather than write the attributes themselves.
- Store details: `sharedThemeStore()` returns one store per root element, so every provider, story and
  bootstrap on a page agrees; without a DOM the store is inert (state and subscriptions only);
  `apply(patch, { persist: false, track: false })` is the hydration form, and an invalid value keeps the
  current preference of that field.
- Tests: a `ThemeProvider` without a `store` prop (or a `root` option) uses the shared store of
  `document.documentElement`, which outlives a single test. Call `resetSharedThemeStores()` in `afterEach`,
  or pass a fresh `root`, so tests do not leak preferences into each other.

## Storybook (E05-T03)

- Run: `build:tokens`, then `storybook` (dev server on 127.0.0.1:6006) or `storybook:build`. The
  preview imports the generated token bundles the app imports. Storybook 10 needs Node 20.19+ or
  22.12+.
- Test: `storybook:test` runs the `storybook` Vitest project (`@storybook/addon-vitest`) in headless
  Chromium (once: `pnpm --filter @candleviewer/ui exec playwright install chromium`): each story's
  play function, then axe. A serious or critical violation fails the story, naming the rule and the
  element; moderate and minor are reported only. Stories tagged `perf` are skipped unless
  `CV_STORYBOOK_PERF=1` (a quiet machine).
- Self-test: `CV_STORYBOOK_A11Y_FIXTURES=1 pnpm --filter @candleviewer/ui storybook:test` runs the
  gate on `.storybook/__fixtures__/` alone (never built or published otherwise): it must fail the
  2:1-contrast button naming `color-contrast` and `#a11y-gate-fixture`. CI's `storybook` job
  (`_job-a11y.yml`, the required `a11y` check) checks that, runs `storybook:test`, logs the story
  count and the axe violations by impact, and uploads the a11y report; codes `CI-A11Y-002..004`.
- Organisation: titles sit under a catalogue band (`Atoms/` .. `ChartEngine/`, see catalogue
  §0.3 rule 8) or `Foundations/`; the `candleviewer/story-title-bands` lint rule fails any other.
  The Theme, Density and Motion toolbars drive the E05-T02 runtime; decorators paint the canvas with
  `surface.app` (on a docs page, a wrapper around each inline story) and count story mounts
  (`<output aria-label="Mount count" hidden>`).
- Hosting: internal only, never an internet-reachable host (Pages, a public bucket, a preview
  service). Publishing the static build to the Tailscale-only internal host is not yet scheduled:
  it is the E05 threat model's accepted A4 residual (E05-X01, #215; its §5 and §6).

## Icons (E05-T06)

`src/icons/` is the icon set of [`16-design-system-brief.md` §5](../../docs/plan/16-design-system-brief.md).
Code draws a glyph by name with CMP-019 `<Icon name size decorative label>`, never by raw SVG. The
registry holds 61 glyphs, each listed in §5: the base set's 48, vendored from Lucide (ISC), and the
13 trading glyphs CandleViewer draws from E05-D02 §7.12.

- `registry.ts`: each icon's canonical name (the `IconName` union), group, glyph source and
  one-sentence meaning, sorted by name: the code twin of the Penpot icon page, compared by diff.
  `minimumPx: 16` marks the six glyphs E05-D02 §7.12 calls "16 px minimum", whose detail closes
  up at 12 px, so they never draw at `sm`; the types hold that, not the runtime. `Icon` is
  generic in its name, and `IconProps<N>`'s `size` drops `sm` for a marked name: neither
  `<Icon name="twap" size="sm" />` nor a CMP-002 `IconButton` with `icon="twap"` and `size="sm"`
  type-checks. A name the call site leaves open, the whole `IconName` union as in a map over the
  registry, keeps all three sizes.
- `source/<origin>/<name>.svg`: the vetted glyphs, committed data (nothing is fetched at
  runtime). `lucide/` holds glyphs vendored byte for byte from `lucide-static`, each renamed to
  its registry name, beside their licence, `source/lucide/LICENSE` (ISC, plus the MIT notice of
  the Feather-derived glyphs); the version, its checksum and the owner are in the vendored-code
  register, [`35-dependency-freeze-policy.md` §7](../../docs/plan/35-dependency-freeze-policy.md).
- `source/custom/`: the 13 trading glyphs of E05-D02 §7.12, CandleViewer's own, so a custom
  source carries no `@license` line (the generator fails on one). Each draws its §7.12 motif as
  an outline on a root with the grid's stroke (1.5, round caps and joins), with no dash, fill or
  transform, its paths in absolute `M`, `L`, `H`, `V`, `C`, `A` and `Z` only (each arc circular
  and unrotated), so `test/icons/glyphs.test.ts` reads every point. Every point, Bezier control
  points and arc bulges included, stays in [1.75, 22.25]: the 1-unit clear margin plus half the
  stroke.
- `<name>.sm.svg` beside a source is its reduced form (E05-D02 §6 J24): a second drawing of the
  name, never a name of its own, that `Icon` draws at `size="sm"` in place of the 24-unit master.
  The generator gives it a module and an entry in `ICON_FORMS`, internal like the rest of
  `generated/`. One glyph has one, `estimated`, whose 12 px form §7.12 left #271 to choose once:
  a solid ring or the "≈" alone. It is the "≈" alone, drawn larger. At 12 px the master's dashed
  ring resolves to dots; a solid ring would drop the dash that marks the value as inferred and
  read as a plain circle; and a ring with the "≈" inside closes up. The reduced forms and the
  `minimumPx` guard are both keyed to the `sm` token, 12 px as shipped: if slice 1 A10
  (16 / 20 / 24 px) is approved, re-key them to the 12 px size.
- `generated/`: one component per icon, and `components.ts`, the map by name that `Icon` draws
  from. Both are internal: the package exports `Icon`, the registry and the sizes, never a glyph
  component. `scripts/build-icons.mjs` (`build:icons`) writes them from the sources, in name
  order and with no timestamp; `build` runs it with `--check`, which fails naming each stale,
  missing or extra module. Never edit one: `test/icons/generator.test.ts`, the drift check,
  compares each byte for byte with the generator's rendering. The generator reads a source as
  data, never markup: it accepts only a 24x24 outline root and plain geometry (path, circle,
  ellipse, line, polyline, polygon, rect), and fails on anything else, naming the file. A Lucide
  glyph's module repeats its source's `@license lucide-static v<version> - ISC` line as a legal
  comment (`/*! ... */`) above the component, which tsup keeps in `dist` and Vite in the app's
  bundle; a Lucide source without that line fails.
- `IconSvg.tsx`: the grid every module draws its geometry in, which no prop changes: the
  24-unit `viewBox`, `currentColor`, no fill, and a non-scaling 1.5px stroke at every size.
- Lint (`eslint.config.mjs`): `candleviewer/no-raw-svg` fails a raw `<svg>` in any file of the
  package outside `src/icons/`, the registry. On `src/**`, stories included,
  `candleviewer/icon-label-required`, `candleviewer/icon-only-control-label` and
  `candleviewer/icon-beside-text-hidden` (CMP-019's ids) enforce decorative vs meaningful. Tests
  are exempt from those three: they write unnamed cases on purpose to pin the types.
- Cost: `Icon` imports every glyph by name, so an app pays for the whole registry, never per
  screen. `test/icons/registry-cost.test.ts` bundles `src/icons/index.ts` with tsup as a production
  build would (minified ESM, React external) and holds it to E05-T06's bound, 15 KB gzipped.

To add an icon, put its SVG at `src/icons/source/<origin>/<name>.svg` (a Lucide glyph is copied
verbatim from the registered `lucide-static` tarball, once its sha512 matches the register row),
add its `registry.ts` entry in name order, then run `build:icons` and `test` in `packages/ui`.

## Visual regression (E05-T04)

[ADR-0019](../../docs/plan/27-adrs/ADR-0019-visual-regression-tooling.md): Playwright's
`toHaveScreenshot` against PNG baselines committed in `vr/baselines/` (plain git, no LFS).

- Matrix: every story of the built Storybook's `index.json` x 3 themes x 2 densities, one test and
  one PNG per cell, both named `{story}--{theme}--{density}`, so a missing cell fails by name. At
  E05-T04, 726 stories made 4,356 cells. A story is left out only by a tag in `EXCLUDED_TAGS`
  (`vr/matrix.ts`; today `perf`), and the job summary names each one. A story that pins a global
  itself (`globals: { theme: "light" }`), or whose play function switches one, shows what it sets
  in every cell of its row; the summary counts those cells.
- Capture: the story's iframe (no Storybook chrome) with the theme and density set as the E05-T03
  toolbar globals in the URL, plus `motion:system`, so E05-T02's runtime follows the OS preference.
  The story renders and plays with none, as in the storybook job where its play function is proven;
  then the test emulates `prefers-reduced-motion: reduce`, the runtime writes `data-motion="reduce"`
  and its CSS stops animation for the shot (`REDUCED_MOTION`, `vr/settings.ts`). Under reduce every
  style change is a 0.01 ms transition, so a play that reads a style right after a step would read
  the old value. The test waits for Storybook to finish the story (play function included), checks
  that Storybook took the cell's globals from the URL and that the reduced-motion attribute is on,
  and clips the shot to what the story paints (`vr/clip.ts`). An overlay's scrim (a flat fill over
  the whole viewport, out of the flow, with no text, edge or shadow of its own) is no part of that:
  a dialog is captured as the dialog, its shadow and a 4 px edge, where a scrim change still shows.
- A cell is never a screenshot of a partial state. Storybook 10.6 reaches `finished` even after a
  play function threw, so the test reads the play's exception from Storybook's channel and fails
  the cell by name (`play function failed: ...`, `vr/page.ts`). A play starts only after its
  story's mount effects (`.storybook/mountAfterEffects.tsx`): a production build has no `act`, so
  without that wait a play could run before the theme runtime applied the cell's globals. Once the
  story finished, the page probe (`vr/probe.ts`) lets the timers due within 1 s fire (a tooltip's
  hover delay), waits for 2 animation frames with no DOM mutation, then freezes every timer, interval
  and frame; a page still changing after 3 s fails by name (`SETTLE`, `vr/settings.ts`). The clip
  is measured twice, two frames apart, and must agree; its edges go out to whole pixels unless they
  lie within 0.01 px of one, so float noise never changes an image's size.
- Tolerance: a cell fails when more pixels change (pixelmatch's `threshold: 0.2`) than 2% of its
  capture (`maxDiffPixelRatio: 0.02`) or 25 (`maxDiffPixels: 25`), whichever is smaller, with
  `animations: "disabled"` (`vr/settings.ts`). The cap holds a capture that is still page-sized (a
  layout drawn edge to edge) to 25 pixels instead of the 41,000 that 2% of 2 Mpx would allow; two
  compare runs on an unchanged head found no cell past it (ADR-0019, Validation). Never raise either
  to accept a change.
- Determinism: a 1920x1080 viewport at `deviceScaleFactor: 1`, `en-US` and UTC, `Date` held at a
  fixed instant by the probe except while a play runs, when it moves with real time (a countdown the
  play waits on counts; timers and frames always stay the browser's, as in the storybook job),
  storage cleared per cell, Playwright's own retries off. A story whose state needs room (a menu
  that scrolls) is sized for this viewport, which is taller than the storybook job's.
- Fonts: the token families, `font.family.ui` (Inter) and `font.family.mono` (JetBrains Mono),
  name no `@font-face` and no generic fallback, so they draw only where they are installed. The
  `vr` job runs on the pinned `ubuntu-24.04` image and installs both from its own archive at fixed
  versions (noble's release pocket): `fonts-inter 4.0+ds-1` (OFL-1.1; its Debian copyright
  records OFL-1.1 and Apache-2.0) and `fonts-jetbrains-mono 2.304+ds-4` (OFL-1.1 upstream, the design
  brief's locked record; its Debian copyright records Apache-2). The install is
  not best-effort: a missing package or family fails the job (CI-A11Y-008). Each shard then draws
  a sample of each family and asks Chromium, through the DevTools protocol
  (`CSS.getPlatformFontsForNode`), which faces it used; anything but exactly Inter and JetBrains
  Mono fails by name (`vr/fonts.ts`), and the job summary names the faces drawn and the packages
  installed. No font is fetched over the network: every request outside the local Storybook goes
  to a closed port and fails the cell, naming the URL. Storybook's iframe loads only its own
  Nunito Sans, for its chrome. Baselines come from the CI image only, never from a laptop.
- CI: the `vr` job of `_job-a11y.yml`, in 14 shards beside `storybook`, fails the required `a11y`
  check (CI-A11Y-006, budget CI-A11Y-007; `docs/ci-runbook.md`). Each shard runs one browser per two
  CPUs (`workers: "50%"`): on a saturated runner a story's commit outruns React's time slice and a
  play races its page far more often. A shard (`VR_SHARD=k/14`) takes every 14th cell of the matrix
  from its k-th (`shardCells`, `vr/matrix.ts`), so each samples every story family and a story's six
  cells run in six shards; Playwright's own `--shard` cut contiguous ranges, and one held the whole
  skeleton family, whose finite sweep Storybook waits out, over its budget.
- Local runs, for debugging only: `build:tokens`, `storybook:build`, then `vr` (Chromium once, as
  for `storybook:test`; the static server is `python3 -m http.server` on 127.0.0.1:6007).

Reviewing a diff:

1. **Inspect.** The job summary lists each failed cell. The `vr-diffs-<shard>` artifact holds, per
   cell, the baseline (`-expected.png`), the capture (`-actual.png`) and the changed pixels
   (`-diff.png`). An unintended diff is a bug: fix the component or token. A cell under "Cells not
   captured" has no image: its reason names the failed play step or what kept moving; fix the story
   or the component, never the tolerance.
2. **Accept an intentional change.** A designer approves the change first (C-10.3). Then
   `vr:update` runs on the CI image only: the gate refuses it in CI unless the a11y workflow's
   dispatch sets `VR_UPDATE=1`, however the update flag is spelled (`vr/gate.ts`). Run
   `gh workflow run _job-a11y.yml --ref <branch> -f vr_update=true`; its unsharded `vr 0` job writes
   every cell that changed beyond the tolerance and every cell with no baseline yet (a new story),
   deletes the PNGs no cell owns, and uploads the `vr-baselines` artifact. Replace `vr/baselines/`
   with the artifact, commit it in the same PR, push, and the PR's `vr` shards must pass. GitHub's
   image diff shows each changed PNG. After a rebase that brings in story or token changes, run the
   dispatch again: a new story has no baseline and a changed one diffs.
3. **Approve.** A CODEOWNER of `vr/baselines/` reviews the PNGs (CODEOWNERS lists
   `@CandleViewer/design-system`, `@CandleViewer/design` and `@basiltt`; any one of them satisfies
   it), and the designer's sign-off is C-10.3's `design-approved` from `@CandleViewer/design`, which
   CODEOWNERS does not enforce. Snapshot review never replaces the manual screen-reader pass (E05-Q02).

Repository growth: a PR adds only the PNGs it changes; ADR-0019's Validation records the measured
size of the full set.

## Scripts

- `pnpm --filter @candleviewer/ui build` — runs `build:tokens` (Style
  Dictionary-driven, see above), `build:icons --check`, then the tsup build.
- `pnpm --filter @candleviewer/ui build:tokens` — token build only.
- `pnpm --filter @candleviewer/ui build:icons` — writes `src/icons/generated/` (see "Icons").
- `pnpm --filter @candleviewer/ui storybook` — dev server with the a11y addon.
- `pnpm --filter @candleviewer/ui storybook:build` / `storybook:test` — static build / its Vitest project.
- `pnpm --filter @candleviewer/ui test` / `test:cov` — the Vitest unit project, ≥80% gate.
- `pnpm --filter @candleviewer/ui vr` / `vr:update` — compare with / rewrite the visual-regression
  baselines (see "Visual regression"; `vr:update` refuses to run in CI outside its dispatch).
