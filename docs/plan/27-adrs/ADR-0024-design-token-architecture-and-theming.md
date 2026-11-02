# ADR-0024 — Design-token architecture and theming strategy

- Status: **Accepted — Approved (owner waiver, Sprint 01 per C-10.1 v1.1.0)**
- Date: 2026-09-30
- Amended: 2026-11-01, E11-T04 PR-1 (#390): the engine export is per theme,
  `build/engine/theme-uniforms.{dark,light,high-contrast}.json`, and `theme-uniforms.json` stays as
  the dark export, byte-identical to `theme-uniforms.dark.json` (`16` §11.1); the build now emits
  nine artefacts. §5's decision is unchanged.
- Deciders: Owner (`@basiltt`) — per the "Agent-delivery adaptations" on ticket E05-T07 (issue #214), the
  owner's `approved` comment on the issue, or owner merge of the PR, substitutes for Architect/CDO
  countersignature; this ADR is Accepted on drafting and does not block on a separate signature.
- Consulted: `docs/plan/16-design-system-brief.md` §2, §4, §11, `docs/plan/26-chart-engine-design.md`,
  `docs/plan/05-accessibility-standard.md` §5.4/§5.6, `docs/plan/02-definition-of-ready-done.md` §5.2,
  the merged E05-T01 implementation (PR #1588, `packages/ui/tokens/`, `packages/ui/scripts/build-tokens.mjs`)
- Related: E05-T01 (token source of truth and Style Dictionary build — implements this decision),
  E10 (Electron shell — consumes `build/electron/tokens.main.json`), E11 (chart engine core — consumes
  `build/engine/theme-uniforms.json`), E05-T02 (CSP inline-script hash for the theme-swap mechanism)

---

## Context and problem statement

`docs/plan/16-design-system-brief.md` (§2, §4, §11) specifies a token architecture and multi-target
build for CandleViewer's design system, but as a brief it does not carry the weight of a binding
architectural record, and it left several structural questions open until E05-T01 built the real thing:
how many token tiers, how theming and density are expressed without combinatorial explosion, and how a
non-CSS, non-DOM consumer (the WebGL chart engine) and a non-browser consumer (the Electron main
process) receive theme data without parsing CSS or TypeScript. `docs/plan/27-adrs/README.md` requires
decisions with long-lived downstream consequences to be recorded as ADRs so a later engineer does not
re-litigate them (risk `R10` key-person risk in `docs/plan/32-risk-register.md`). E05-T01 (PR #1588,
merged) has now shipped the real implementation; this ADR records what was actually built, not a
proposal, per the ticket's acceptance criteria.

## Decision

1. **Three-tier global -> alias -> component token model.** Tier 1 (`packages/ui/tokens/primitives.tokens.json`)
   holds raw values with no semantic meaning (`palette.blue.500`, `size.4`) and is never referenced
   directly by components. Tier 2 (`packages/ui/tokens/semantic-{dark,light,high-contrast}.tokens.json`)
   holds the meaning-carrying alias names components actually consume (`color.buy`, `font.mono`,
   `space.field.gap`); this is the layer `15-component-catalogue.md` entries reference. Tier 3
   (component tokens, e.g. `button.primary.background`) is used sparingly, only where the semantic layer
   doesn't express a needed override, to keep token count bounded.
2. **Style Dictionary, one build script, four platforms, two custom formats.**
   `packages/ui/scripts/build-tokens.mjs` drives theme composition and alias resolution through Style
   Dictionary, emitting six documented artefacts from three custom formats (`json/flat-rgba`,
   `json/flat`, `typescript/nested-object` in `tools/style-dictionary/formats/`): three theme CSS files
   (`build/css/tokens.{dark,light,high-contrast}.css`), a typed nested TS object
   (`build/ts/tokens.ts`), a flat RGBA JSON for the WebGL engine (`build/engine/theme-uniforms.json`),
   and a flat, CSS/TS-free JSON for Electron main (`build/electron/tokens.main.json`).
3. **Themes are alias re-pointing, not new token names.** Dark is the canonical, source-of-truth theme;
   light and high-contrast are produced by re-mapping the same Tier-2 alias names to different Tier-1
   primitives (`semantic-light.tokens.json`, `semantic-high-contrast.tokens.json`), never by inventing
   parallel token names. A theme-parity build guard (`TOKENS-E001`) fails the build and names the
   offending token if any alias exists in one theme file but not another, making theme-name drift a
   build-time error rather than a runtime visual bug.
4. **Density is alias-step selection, never a second scale, never structural branching.** A single
   4px-based spacing/size primitive scale (`space.{0,1,2,3,4,6,8,12,16,24,32,48,64}`,
   `size.row.*`/`size.control.*`) is shared by both density modes; density changes which scale step a
   component's spacing/row-height alias resolves to, never the component's structure or the information
   it shows. This keeps the token count bounded (one scale, not two) and keeps density a pure styling
   concern that visual-regression tests can assert parity over.
5. **WebGL theming via a flat `theme-uniforms.json`, not CSS custom properties.** The chart engine
   (`packages/chart-engine`, C-2.16: no DOM, no CSS) cannot read `getComputedStyle` or CSS custom
   properties without violating its independence rule, so every chart-category token is emitted as a
   `{ hex, rgba }` object where `rgba` is sRGB 0..1 floats (linear conversion happens in the shader, per
   the brief §11.1, so the engine never guesses a colour space). This is the binding contract E11 (chart
   engine core) consumes for colour uniforms on theme switch.
6. **Electron main gets a flat JSON so it never parses CSS or TS.** The main process (no bundler, no
   PostCSS/TS pipeline at runtime) receives `build/electron/tokens.main.json`, a flat key->value map with
   no CSS syntax and no TypeScript syntax, so window-chrome theming (title bar colour, native menu
   accents) never requires embedding a CSS or TS parser in the main process.
7. **Tokens are versioned independently of the component library.** `packages/ui/tokens/CHANGELOG.md`
   tracks the token contract's own semver (initialised at `0.1.0` by E05-T01), separate from
   `packages/ui`'s package version, so a token-only change (e.g. a rebalanced palette) does not force a
   component-library major bump, and vice versa.
8. **Determinism and build-time guards are part of the contract, not an afterthought.** Two consecutive
   builds are byte-identical (no timestamps in headers, every object/array name-sorted before
   serialisation, `style-dictionary` pinned in the lockfile). Three error codes are thrown and CI-caught:
   `TOKENS-E001` (missing theme parity - names the token), `TOKENS-E002` (dangling or circular alias
   reference), `TOKENS-E003` (a chart-category token supplied as non-hex, which would silently break the
   RGBA-uniform contract for E11). The `candleviewer/no-raw-design-values` ESLint rule rejects raw
   hex/px literals in `packages/ui/src/**`, so token bypass is caught at lint time, not design review.

## Rejected alternatives

- **CSS-in-JS runtime theming** (e.g. styled-components/Emotion theme objects computed at render time):
  rejected on frame-budget grounds. The brief's binding requirement (§4) is an instant, one-frame theme
  swap with no reload, including the chart engine's WebGL colour uniforms re-uploading on the same
  event; a runtime CSS-in-JS layer that recomputes styles per-component on theme change has no path to
  feed a Web Worker/OffscreenCanvas renderer without a serialization bridge, and reintroduces a
  style-recalculation cost the static CSS-custom-property approach avoids entirely. Structurally, it also
  has no answer for the Electron-main and WebGL consumers, which read data, not a JS runtime.
- **Tailwind config as the token source of truth**: rejected because it is a single-consumer format
  (the PostCSS/Tailwind pipeline for the React app) with no mechanical path to a typed TS object, a
  flat Electron JSON, or an RGBA engine-uniform file - every non-CSS consumer would need a second,
  hand-maintained mapping that could drift from the Tailwind config, reintroducing exactly the
  multi-source-of-truth problem tokens exist to remove.
- **Two parallel density scales** (a "comfortable" scale and a "compact" scale defined independently):
  rejected for token sprawl - doubling every spacing/size token's definitions roughly doubles the
  contrast-linting and visual-regression surface for no semantic benefit, since density is a pure
  resolution choice over one already-designed scale, not a different design language.
- **Inverting dark to produce light** (naive lightness-inversion of the dark palette): rejected on a
  structural/measured basis - a mechanical inversion washes out the heatmap ramps and candle-body
  colours the brief's automated per-stop contrast-check script (§2, owner decision #10) validates
  independently against each theme's background, and produces theme-specific colours that no longer
  pass the same contrast matrix dark was authored against. Light is authored and validated as its own
  palette re-mapping, not derived mechanically.

## Consequences

- **E10 (Electron shell)**: consumes `build/electron/tokens.main.json` directly as a flat map; must never
  add a CSS or TS parser to the main process to read tokens, and must respect the CSP inline-script hash
  requirement from E05-T02 when the renderer applies the corresponding CSS custom properties at the
  document root.
- **E11 (chart engine core)**: consumes `build/engine/theme-uniforms.json`; must treat every `rgba` value
  as sRGB 0..1 and perform its own linear conversion in-shader (never assume the JSON is already linear),
  and must subscribe to the same theme-change event the React app uses so canvas colour uniforms
  re-upload within the same frame budget as the CSS custom-property swap.
- Any future ticket that adds a fourth theme preset or a new chart-category token must go through the
  `TOKENS-E001`/`TOKENS-E003` build guards and the automated contrast/CVD validation pipeline (§2 of the
  brief) - this is a build-time gate, not a manual design-review step, and cannot be skipped under sprint
  pressure.
- `packages/ui/tokens/CHANGELOG.md` semver governs downstream consumers' upgrade discipline; a breaking
  token rename bumps it independently of `packages/ui`'s own package version.

## Validation

- E05-T01's merged test suite (`packages/ui/test/tokens-build/build-integration.test.ts` and the
  per-format unit tests) exercises every claim in this ADR: all nine artefacts non-empty (six before the E11-T04 amendment), byte-identical
  across two consecutive builds, `TOKENS-E001`/`TOKENS-E002` failures naming the offending token, RGBA
  engine uniforms as numeric 0..1 floats with no CSS/hex leakage, and a flat CSS/TS-free Electron JSON.
- `docs/plan/16-design-system-brief.md` was checked against the merged implementation while drafting
  this ADR; no divergence was found between the brief's §2/§4/§11 description and what E05-T01 shipped,
  so no brief edit is required.

## Deviation note

The ticket body names `docs/plan/27-adrs/ADR-0020-design-token-architecture-and-theming.md`, written
before ADR-0016 was reassigned to the statechart-runtime record and ADR-0017...0023 were taken by later
tickets. Per the "Agent-delivery adaptations" clause on this ticket, this ADR uses the next free number
in `docs/plan/27-adrs/` at drafting time, **ADR-0024**, and this filename/number is the one added to the
index (`27-adrs/README.md`) and `20-architecture.md` §16.
