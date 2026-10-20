import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The label-on-fill contrast matrix (#3896): the CI gate over tools/contrast/label-on-fill.json,
// whose `$comment` states the rules and what is not checked (hover and pressed fills are not held
// to the 3:1 boundary; plain `disabled`, with no reason, dims the whole control and is exempt
// under WCAG 2.2 SC 1.4.3). packages/ui/tokens/tests/verify_tokens.py checks the same registry over
// the theme tokens; this test also checks the labels in every chart colour mode. Plain .mjs
// tooling loads untyped through a string specifier, as in data-ink.test.ts, and is typed here.

type Theme = Record<string, { $value: unknown } | undefined>;
type Pair = [string, string];
type Mode = { palette: string; convention: string };
interface Role {
  label: string;
  states: Record<string, string>;
  boundary: boolean;
  hue: boolean;
  outline?: string;
  distinctFrom?: string[];
}
interface Registry {
  thresholds: Record<
    "label" | "glyph" | "boundary" | "stateLightness" | "stateHue" | "ringDeltaE",
    number
  >;
  surfaces: string[];
  stateSuffixes: string[];
  roles: Record<string, Role>;
  disabledWithReason: {
    gated: { opacity: string; label: string; glyph: string };
    text: Pair[];
    glyph: Pair[];
  };
  focusRing: { ring: string; surfaces: string[]; distinctThemes: string[]; distinctFrom: string[] };
}

const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as {
  contrastRatio(a: string, b: string): number;
  cieLab(hex: string): [number, number, number];
  deltaE76(a: string, b: string): number;
};
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const modes = (await import(
  /* @vite-ignore */ "../../scripts/chart-color-modes.mjs" as string
)) as {
  MODES: Mode[];
  modeOverrides(theme: Theme, mode: Mode): Record<string, unknown>;
};
const registry = JSON.parse(
  readFileSync(new URL("../../../../tools/contrast/label-on-fill.json", import.meta.url), "utf-8"),
) as Registry;
const T = registry.thresholds;
const themes = await build.loadResolvedThemes();

// Truncated to three places, so a failing 2.9993:1 never prints as the 3:1 it misses.
const r3 = (n: number) => (Math.floor(n * 1000) / 1000).toFixed(3);

/** A token's resolved colour; an absent or non-opaque value fails loudly, never skips a pair. */
function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(v)) {
    throw new Error(`label-on-fill: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

/** An opacity token's value; anything but a number in (0, 1] fails loudly. */
function opacityOf(theme: Theme, name: string): number {
  const v = Number(theme[name]?.$value);
  if (!(v > 0 && v <= 1)) {
    throw new Error(`label-on-fill: "${name}" does not resolve to an opacity in (0, 1]`);
  }
  return v;
}

/** `fg` at `alpha` over opaque `bg`, mixed per sRGB channel and rounded, as a browser paints it. */
function over(fg: string, bg: string, alpha: number): string {
  const ch = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  const mix = [0, 1, 2].map((i) => Math.round(alpha * ch(fg, i) + (1 - alpha) * ch(bg, i)));
  return `#${mix.map((c) => c.toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}

const lightness = (hex: string) => math.cieLab(hex)[0];
function hue(hex: string): number {
  const [, a, b] = math.cieLab(hex);
  return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
}
const hueGap = (x: number, y: number) => Math.abs(((x - y + 540) % 360) - 180);
const roles = () => Object.entries(registry.roles);
const rest = (r: Role) => r.states["default"] ?? "";

function labelFindings(
  name: string,
  theme: Theme,
  only: (r: Role) => boolean = () => true,
): string[] {
  return roles()
    .filter(([, r]) => only(r))
    .flatMap(([role, r]) =>
      Object.entries(r.states).flatMap(([state, fill]) => {
        const ratio = math.contrastRatio(hexOf(theme, r.label), hexOf(theme, fill));
        return ratio < T.label
          ? [`${name} ${role}.${state}: ${r.label} on ${fill} ${r3(ratio)}:1 < ${T.label}:1`]
          : [];
      }),
    );
}

function orderFindings(name: string, theme: Theme): string[] {
  return roles().flatMap(([role, r]) => {
    const fills = Object.values(r.states);
    return fills.flatMap((a, i) =>
      fills.slice(i + 1).flatMap((b) => {
        const d = Math.abs(lightness(hexOf(theme, a)) - lightness(hexOf(theme, b)));
        return d < T.stateLightness
          ? [`${name} ${role}: ${a} vs ${b} dL* ${r3(d)} < ${T.stateLightness}`]
          : [];
      }),
    );
  });
}

/** A role with `distinctFrom` (the selected fill) keeps its rest fill 5 L* from each listed fill. */
function distinctFindings(name: string, theme: Theme): string[] {
  return roles().flatMap(([role, r]) =>
    (r.distinctFrom ?? []).flatMap((other) => {
      const d = Math.abs(lightness(hexOf(theme, rest(r))) - lightness(hexOf(theme, other)));
      return d < T.stateLightness
        ? [`${name} ${role}: ${rest(r)} vs ${other} dL* ${r3(d)} < ${T.stateLightness}`]
        : [];
    }),
  );
}

function hueFindings(name: string, theme: Theme): string[] {
  return roles()
    .filter(([, r]) => r.hue)
    .flatMap(([role, r]) => {
      const restHue = hue(hexOf(theme, rest(r)));
      return Object.values(r.states).flatMap((fill) => {
        const gap = hueGap(hue(hexOf(theme, fill)), restHue);
        return gap > T.stateHue
          ? [`${name} ${role}: ${fill} hue ${r3(gap)} deg from the rest fill > ${T.stateHue}`]
          : [];
      });
    });
}

function boundaryFindings(name: string, theme: Theme): string[] {
  return roles()
    .filter(([, r]) => r.boundary)
    .flatMap(([role, r]) =>
      registry.surfaces.flatMap((surface) => {
        const ratio = math.contrastRatio(hexOf(theme, rest(r)), hexOf(theme, surface));
        return ratio < T.boundary
          ? [`${name} ${role}: ${rest(r)} on ${surface} ${r3(ratio)}:1 < ${T.boundary}:1`]
          : [];
      }),
    );
}

/** A role with `outline` carries its boundary on a 2 px inner outline: 3:1 on surfaces and fills. */
function outlineFindings(name: string, theme: Theme): string[] {
  return roles().flatMap(([role, r]) => {
    const outline = r.outline;
    if (outline === undefined) return [];
    return [...registry.surfaces, ...Object.values(r.states)].flatMap((bg) => {
      const ratio = math.contrastRatio(hexOf(theme, outline), hexOf(theme, bg));
      return ratio < T.boundary
        ? [`${name} ${role} outline: ${outline} on ${bg} ${r3(ratio)}:1 < ${T.boundary}:1`]
        : [];
    });
  });
}

/** Disabled with reason: full-opacity label and glyph on the rest fill dimmed over each surface. */
function gatedFindings(name: string, theme: Theme): string[] {
  const g = registry.disabledWithReason.gated;
  const alpha = opacityOf(theme, g.opacity);
  const checks: [string, number, string][] = [
    [g.label, T.label, "label"],
    [g.glyph, T.glyph, "locked glyph"],
  ];
  return roles().flatMap(([role, r]) =>
    registry.surfaces.flatMap((surface) => {
      const dimmed = over(hexOf(theme, rest(r)), hexOf(theme, surface), alpha);
      return checks.flatMap(([fg, min, what]) => {
        const ratio = math.contrastRatio(hexOf(theme, fg), dimmed);
        return ratio < min
          ? [
              `${name} gated ${role} ${what}: ${fg} on ${rest(r)} at ${alpha} over ${surface} ` +
                `${r3(ratio)}:1 < ${min}:1`,
            ]
          : [];
      });
    }),
  );
}

function disabledFindings(name: string, theme: Theme): string[] {
  const check = (pairs: Pair[], min: number, what: string) =>
    pairs.flatMap(([fg, bg]) => {
      const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
      return ratio < min ? [`${name} ${what}: ${fg} on ${bg} ${r3(ratio)}:1 < ${min}:1`] : [];
    });
  return [
    ...check(registry.disabledWithReason.text, T.label, "reason text"),
    ...check(registry.disabledWithReason.glyph, T.glyph, "ghost locked glyph"),
  ];
}

/** The focus ring clears 3:1 on each surface; in `distinctThemes` it also stands off the fills. */
function ringFindings(name: string, theme: Theme): string[] {
  const f = registry.focusRing;
  const ring = hexOf(theme, f.ring);
  const onSurfaces = f.surfaces.flatMap((surface) => {
    const ratio = math.contrastRatio(ring, hexOf(theme, surface));
    return ratio < T.boundary
      ? [`${name} ${f.ring} on ${surface} ${r3(ratio)}:1 < ${T.boundary}:1`]
      : [];
  });
  const offFills = f.distinctThemes.includes(name)
    ? f.distinctFrom.flatMap((fill) => {
        const d = math.deltaE76(ring, hexOf(theme, fill));
        return d < T.ringDeltaE
          ? [`${name} ${f.ring} vs ${fill} dE76 ${r3(d)} < ${T.ringDeltaE}`]
          : [];
      })
    : [];
  return [...onSurfaces, ...offFills];
}

/** A `<role>.<hover|active|pressed>` token the matrix does not list fails, so a new state is gated. */
function undeclaredFindings(name: string, theme: Theme): string[] {
  return roles().flatMap(([role, r]) => {
    const base = rest(r);
    const prefix = base.endsWith(".default") ? base.slice(0, -"default".length) : `${base}.`;
    return registry.stateSuffixes
      .map((suffix) => prefix + suffix)
      .filter((token) => token in theme && !Object.values(r.states).includes(token))
      .map((token) => `${name} ${role}: ${token} is not in tools/contrast/label-on-fill.json`);
  });
}

/** The theme as a chart colour mode (E47-S06) renders it: the buy and sell fills re-pointed. */
function inMode(theme: Theme, mode: Mode): Theme {
  const out: Theme = { ...theme };
  for (const [k, v] of Object.entries(modes.modeOverrides(theme, mode))) out[k] = { $value: v };
  return out;
}

const everyTheme = (check: (name: string, theme: Theme) => string[]) =>
  Object.entries(themes).flatMap(([name, theme]) => check(name, theme));

describe("label-on-fill contrast matrix (#3896)", () => {
  it("covers the three themes the token build resolves", () => {
    expect(Object.keys(themes).sort()).toEqual(["dark", "high-contrast", "light"]);
  });

  it("keeps the registry at or past its floors, so a data-only edit cannot loosen the gate", () => {
    // WCAG 2.2 SC 1.4.3 (label) and SC 1.4.11 (glyph, boundary), the ticket's 5 L* state step
    // and hue identity, and the high-contrast ring's 20 dE76 (verify_tokens.py holds the same
    // thresholds).
    expect(T.label).toBeGreaterThanOrEqual(4.5);
    expect(T.glyph).toBeGreaterThanOrEqual(3);
    expect(T.boundary).toBeGreaterThanOrEqual(3);
    expect(T.stateLightness).toBeGreaterThanOrEqual(5);
    expect(T.stateHue).toBeLessThanOrEqual(10);
    expect(T.ringDeltaE).toBeGreaterThanOrEqual(20);
    expect(Object.keys(registry.roles)).toEqual(
      expect.arrayContaining(["primary", "secondary", "danger", "buy", "sell", "selected"]),
    );
    expect(registry.surfaces).toEqual(
      expect.arrayContaining([
        "color.surface.app",
        "color.surface.raised",
        "color.surface.overlay",
      ]),
    );
    expect(registry.focusRing.distinctThemes).toContain("high-contrast");
  });

  it("every label clears 4.5:1 on each of its state fills", () => {
    expect(everyTheme(labelFindings)).toEqual([]);
  });

  it("every label clears 4.5:1 in every chart colour mode (re-pointed buy and sell fills)", () => {
    const found = everyTheme((name, theme) =>
      modes.MODES.flatMap((m) => {
        const moved = Object.keys(modes.modeOverrides(theme, m));
        const repointed = (r: Role) => Object.values(r.states).some((f) => moved.includes(f));
        return labelFindings(`${name} ${m.palette}+${m.convention}`, inMode(theme, m), repointed);
      }),
    );
    expect(found).toEqual([]);
  });

  it("a role's states are pairwise at least 5 CIE L* apart", () => {
    expect(everyTheme(orderFindings)).toEqual([]);
  });

  it("the selected fill is at least 5 CIE L* from every primary state fill", () => {
    expect(everyTheme(distinctFindings)).toEqual([]);
  });

  it("a chromatic role's states keep the rest fill's hue (LCh, within 10 degrees)", () => {
    expect(everyTheme(hueFindings)).toEqual([]);
  });

  it("each rest fill clears 3:1 against the app, raised and overlay surfaces", () => {
    expect(everyTheme(boundaryFindings)).toEqual([]);
  });

  it("the selected outline clears 3:1 against every surface and the selected fill", () => {
    expect(everyTheme(outlineFindings)).toEqual([]);
  });

  it("disabled with reason: label 4.5:1 and glyph 3:1 on each rest fill dimmed over each surface", () => {
    expect(everyTheme(gatedFindings)).toEqual([]);
  });

  it("disabled with reason: reason text clears 4.5:1, a ghost's locked glyph 3:1", () => {
    expect(everyTheme(disabledFindings)).toEqual([]);
  });

  it("the focus ring clears 3:1 on every surface and, in high contrast, stands off the fills", () => {
    expect(everyTheme(ringFindings)).toEqual([]);
  });

  it("lists every interaction-state token of each role", () => {
    expect(everyTheme(undeclaredFindings)).toEqual([]);
  });

  it("fails closed: each check reports a broken synthetic theme pair by pair", () => {
    const dark = themes["dark"] ?? {};
    const broken: Theme = {
      ...dark,
      "color.action.primary.hover": { $value: "#AFB8F8" }, // brand-hue tint under a white label
      "color.buy.hover": dark["color.buy.default"], // no visible hover step
      "color.sell.hover": { $value: "#3CB371" }, // sell hover turned green
      "color.status.danger.default": dark["color.surface.overlay"], // no boundary
      "color.buy.active": { $value: "#2EBD59" }, // a new state outside the matrix
      "color.action.selected": dark["color.action.primary.active"], // a pressed toggle = pressed primary
      "color.action.selected.hover": { $value: "#173F8F" }, // a new selected state outside the matrix
      "color.border.selected": dark["color.surface.overlay"], // an outline lost on the overlay
      "color.focus.ring": dark["color.surface.raised"], // a ring lost on the raised surface
      "opacity.disabled": { $value: "1" }, // gated fills not dimmed at all
    };
    expect(labelFindings("x", broken)).toEqual([
      "x primary.hover: color.text.on-action on color.action.primary.hover 1.903:1 < 4.5:1",
    ]);
    expect(orderFindings("x", broken)).toContainEqual(
      "x buy: color.buy.default vs color.buy.hover dL* 0.000 < 5",
    );
    expect(distinctFindings("x", broken)).toEqual([
      "x selected: color.action.selected vs color.action.primary.active dL* 0.000 < 5",
    ]);
    expect(hueFindings("x", broken)).toEqual([
      expect.stringMatching(
        /^x sell: color\.sell\.hover hue \d+\.\d{3} deg from the rest fill > 10$/,
      ),
    ]);
    expect(boundaryFindings("x", broken)).toContainEqual(
      "x danger: color.status.danger.default on color.surface.overlay 1.000:1 < 3:1",
    );
    expect(outlineFindings("x", broken)).toContainEqual(
      "x selected outline: color.border.selected on color.surface.overlay 1.000:1 < 3:1",
    );
    expect(gatedFindings("x", broken)).toContainEqual(
      "x gated primary label: color.text.primary on color.action.primary.default at 1 over " +
        "color.surface.app 3.948:1 < 4.5:1",
    );
    expect(ringFindings("x", broken)).toContainEqual(
      "x color.focus.ring on color.surface.raised 1.000:1 < 3:1",
    );
    expect(undeclaredFindings("x", broken)).toEqual([
      "x buy: color.buy.active is not in tools/contrast/label-on-fill.json",
      "x selected: color.action.selected.hover is not in tools/contrast/label-on-fill.json",
    ]);
    // main's high-contrast ring was the primary rest fill, and its hover fill is close by too.
    const hc = themes["high-contrast"] ?? {};
    const sameRing: Theme = { ...hc, "color.focus.ring": hc["color.action.primary.default"] };
    expect(ringFindings("high-contrast", sameRing)).toEqual([
      "high-contrast color.focus.ring vs color.action.primary.default dE76 0.000 < 20",
      "high-contrast color.focus.ring vs color.action.primary.hover dE76 16.130 < 20",
    ]);
    // Standing off the fills is asked of high contrast only; elsewhere the 3:1 surface rule holds.
    expect(
      ringFindings("dark", { ...dark, "color.focus.ring": dark["color.action.primary.default"] }),
    ).toEqual([]);
    const missing: Theme = Object.fromEntries(
      Object.entries(dark).filter(([name]) => name !== "color.action.primary.active"),
    );
    expect(() => labelFindings("x", missing)).toThrow(/does not resolve/);
    const noOpacity: Theme = { ...dark, "opacity.disabled": { $value: "none" } };
    expect(() => gatedFindings("x", noOpacity)).toThrow(/opacity in \(0, 1\]/);
  });
});
