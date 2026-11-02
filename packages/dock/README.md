# @candleviewer/dock

The dock layout tree (E15-T02): pure TypeScript, no React, DOM, network or chart engine
(ESLint purity rules in `eslint.config.mjs`, `dock-framework-free` in `.dependency-cruiser.js`).

- **Model** (`model.ts`): `row` / `column` splits with fractional `sizes`, `tabset`s of leaves,
  and `leaf`s carrying `paneId`, `kind` and the compact-view minimums. Floating and minimised
  panes are kept beside the tree. Immutable plain data.
- **Operations** (`ops.ts`): `split`, `move`, `tabify`, `close`, `resize`, `equalise`,
  `activateTab`, `maximise` / `restore`, `float` / `redock`, `applyPreset`. Each returns a new tree
  through `normalise`; a move keeps the leaf object, so the app re-parents a panel and never
  recreates it.
- **Normal form** (`normalise.ts`): no single-child container, no one-tab tab group, sizes summing
  to 1, minimums kept where the dock can hold them, `22`'s caps (depth 6, 64 nodes, 16 panes).
- **Presets** (`presets.ts`): `presetToTree` / `matchPreset` for `lay_preset`.
- **Serialisation** (`serialise.ts`): `toLayoutInput` / `fromLayout` against `22`'s
  `LayoutInput` / `Layout`; `fromLayout` is the import boundary (bounded `validateGridSpec`, the
  caller's kind allow-list). Errors are `DockError` with `22`'s rule codes.
- **Drops** (`drop.ts`): `dropZones` (CMP-214 geometry), `resolveDrop` (pointer) and
  `resolveDirectionalMove` (CMP-216's keyboard chooser) over the same zones, applied by `relocate`.

Ids come from an injected minter (`counterMinter`); one minter per dock keeps node and pane ids
apart. `pnpm --filter @candleviewer/dock test:cov` runs the suite, the 1000-operation property
test included, at the 85 % floor.
