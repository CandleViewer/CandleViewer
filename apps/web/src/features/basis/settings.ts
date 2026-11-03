// E24-S08 (#783) slice 1: the basis source. Owner ruling (#778, §19.110): the `deriv.*` settings get a
// server contract block and there is no local-storage fallback, so `deriv.basis.source` is held in memory
// by the component and starts at the contract default `last` on every mount.
// TODO(#778 contract PR, §19.110): read and write `deriv.basis.source` through the `deriv` settings block.
// The default is the contract's `last` (`24` §7: `basis = last − index`, with `source = last | mark`); D02 /
// D03 draw `mark`, so a D03 amendment is routed (BQ 2). `deriv.basis.annualised` is not kept: no annualised
// basis code exists (BQ 4).

export type BasisSource = "last" | "mark";

export const DEFAULT_BASIS_SOURCE: BasisSource = "last";
