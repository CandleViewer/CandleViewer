// Types for the Node-side imports of color-math.mjs (E47-Q03: the keyboard suite's focus-visibility check
// imports the one contrast function instead of copying it). Declares only what a TypeScript caller uses.
export function relativeLuminance(hex: string): number;
export function contrastRatio(hexA: string, hexB: string): number;
