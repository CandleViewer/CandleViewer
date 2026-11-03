// E24-S08 (#783) slice 1: the basis source. Owner ruling (#778, §19.110): the `deriv.*` settings get a
// server contract block and there is no local-storage fallback, so `deriv.basis.source` is held in memory
// by the component and starts at the contract default `last` on every mount.
// TODO(#778 contract PR, §19.110): read and write `deriv.basis.source` through the `deriv` settings block.
// BQ 2, ruled (6612480577): the served default `last` wins; D03 S54-6 draws mark − index, default `mark`, which
// becomes a D03 A-row after merge. The default is the contract's `last` (`24` §7: `basis = last − index`, with `source = last | mark`); D02 /
// D03 draw `mark`, so the selector exposes both sources. `deriv.basis.annualised` is not kept: no annualised
// basis code exists (BQ 4).

export type BasisSource = "last" | "mark";

export const DEFAULT_BASIS_SOURCE: BasisSource = "last";
