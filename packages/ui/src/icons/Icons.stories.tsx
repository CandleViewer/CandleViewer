import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { ICON_COMPONENTS } from "./generated/components.js";
import { CloseIcon, DownloadIcon, ICON_SIZES, ICONS, WarningIcon, type IconName } from "./index.js";

// Object.keys widens to string[]; ICONS' keys are exactly IconName, the type derived from them.
const NAMES = Object.keys(ICONS) as IconName[];
const ROW = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-inset-sm)",
} as const;
const LIST = { listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--space-2)" };

/** A computed style of `element`, read in the story's own browser. */
const computed = (element: Element, property: string) =>
  getComputedStyle(element).getPropertyValue(property).trim();

/**
 * The grid's live area, in units of the 24-unit box: the base set's glyphs span 2 to 22 on both
 * axes, and every icon, a custom one included, draws inside it (E05-T06 Gherkin "Custom icons match
 * the grid"). getBBox measures geometry, not stroke. The slack is the base set's own: a rounded
 * corner of Lucide's triangle-alert (`warning`) reaches 1.98, and 0.05 units is under 0.05px.
 */
const LIVE_AREA = { min: 2, max: 22 } as const;
const SLACK = 0.05;

/** An icon's geometry, both axes, from the browser's own layout: its lowest and highest edge. */
function geometryEdges(svg: SVGSVGElement): { readonly min: number; readonly max: number } {
  const edges: number[] = [];
  for (const shape of svg.children) {
    if (!(shape instanceof SVGGraphicsElement)) continue;
    const { x, y, width, height } = shape.getBBox();
    edges.push(x, y, x + width, y + height);
  }
  return { min: Math.min(...edges), max: Math.max(...edges) };
}

/**
 * The icon registry (E05-T06, 16-design-system-brief.md §5): every icon with its name and meaning,
 * the three optical sizes, and the decorative-vs-meaningful rule. An icon beside text is
 * `aria-hidden`; an icon-only control carries `aria-label`; a standalone meaningful icon is a
 * named `img`. Every story passes the a11y gate.
 */
const meta: Meta = { title: "Foundations/Icons" };
export default meta;
type Story = StoryObj;

function Registry(): JSX.Element {
  return (
    <ul aria-label="Icon registry" style={LIST}>
      {NAMES.map((name) => {
        const Glyph = ICON_COMPONENTS[name];
        return (
          <li key={name} style={ROW}>
            <Glyph size="lg" />
            <code>{name}</code>
            <span>{ICONS[name].description}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Every registered icon, by name, with its description: the Penpot icon page's code twin. */
export const FullSet: Story = {
  render: () => <Registry />,
  play: async ({ canvasElement }) => {
    const rows = within(canvasElement).getAllByRole("listitem");
    await expect(rows).toHaveLength(NAMES.length);
    // Each icon sits beside its name: decorative, out of the accessibility tree.
    await expect(canvasElement.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(
      NAMES.length,
    );
  },
};

/**
 * The optical sizes: at each `size.icon.*` token every icon takes the token's extent, a 1.5px
 * stroke and the grid's live area, so a new glyph, a custom one included, is checked as it joins.
 */
export const SizeScale: Story = {
  render: () => (
    <ul aria-label="Optical sizes" style={LIST}>
      {ICON_SIZES.map((size) => (
        <li key={size} style={{ ...ROW, flexWrap: "wrap" }}>
          <code>size.icon.{size}</code>
          {NAMES.map((name) => {
            const Glyph = ICON_COMPONENTS[name];
            return <Glyph key={name} size={size} />;
          })}
        </li>
      ))}
    </ul>
  ),
  play: async ({ canvasElement }) => {
    const problems: string[] = [];
    const base: number[] = [];
    for (const size of ICON_SIZES) {
      const token = computed(document.documentElement, `--size-icon-${size}`);
      await expect(token, "token CSS missing: run `build:tokens` first").not.toBe("");
      const row = within(canvasElement).getByText(`size.icon.${size}`).parentElement;
      const icons = [...(row?.querySelectorAll("svg") ?? [])];
      await expect(icons.map((svg) => svg.dataset["icon"])).toEqual(NAMES);
      for (const [index, name] of NAMES.entries()) {
        const svg = icons[index];
        if (!svg) continue; // unreachable: the row holds every name, as just asserted
        const icon = `${name} at ${size}`;
        const extent = `${svg.getBoundingClientRect().width}px`;
        if (extent !== token) problems.push(`${icon}: ${extent} wide, not ${token}`);
        for (const shape of svg.children) {
          const stroke = `${computed(shape, "stroke-width")} ${computed(shape, "vector-effect")}`;
          if (stroke !== "1.5px non-scaling-stroke") problems.push(`${icon}: stroke ${stroke}`);
        }
        const { min, max } = geometryEdges(svg);
        if (min < LIVE_AREA.min - SLACK || max > LIVE_AREA.max + SLACK) {
          problems.push(`${icon}: geometry spans ${min} to ${max}, off the live area`);
        }
        if (ICONS[name].source.startsWith("lucide/")) base.push(min, max);
      }
    }
    await expect(problems).toEqual([]);
    // The live area is the base set's own: its glyphs reach both of its edges, within the slack.
    await expect(Math.abs(Math.min(...base) - LIVE_AREA.min)).toBeLessThanOrEqual(SLACK);
    await expect(Math.abs(Math.max(...base) - LIVE_AREA.max)).toBeLessThanOrEqual(SLACK);
  },
};

/** An icon-only control: the button carries the name, its icon stays hidden. */
export const IconOnlyButton: Story = {
  render: () => (
    <button type="button" aria-label="Close panel">
      <CloseIcon />
    </button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Close panel" })).toBeVisible();
  },
};

/** An icon beside text: the text names the button, so the icon is not read twice. */
export const BesideText: Story = {
  render: () => (
    <button type="button" style={ROW}>
      <DownloadIcon />
      Download
    </button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Download" })).toBeVisible();
  },
};

/** A standalone meaningful icon: named, it is an image to assistive technology. */
export const Labelled: Story = {
  render: () => <WarningIcon size="lg" aria-label="Warning" />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "Warning" })).toBeVisible();
  },
};
