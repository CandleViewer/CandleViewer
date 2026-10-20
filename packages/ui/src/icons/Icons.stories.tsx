import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { ICON_COMPONENTS } from "./generated/components.js";
import {
  CloseIcon,
  DownloadIcon,
  ICON_SIZES,
  ICONS,
  SearchIcon,
  WarningIcon,
  type IconName,
} from "./index.js";

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

/** The optical sizes: each takes its `size.icon.*` token and keeps a 1.5px stroke. */
export const SizeScale: Story = {
  render: () => (
    <ul aria-label="Optical sizes" style={LIST}>
      {ICON_SIZES.map((size) => (
        <li key={size} style={ROW}>
          <SearchIcon size={size} />
          <code>size.icon.{size}</code>
        </li>
      ))}
    </ul>
  ),
  play: async ({ canvasElement }) => {
    for (const size of ICON_SIZES) {
      const label = within(canvasElement).getByText(`size.icon.${size}`);
      const svg = label.parentElement?.querySelector("svg");
      if (!svg) throw new Error(`no icon beside size.icon.${size}`);
      const token = computed(document.documentElement, `--size-icon-${size}`);
      await expect(token, "token CSS missing: run `build:tokens` first").not.toBe("");
      await expect(`${svg.getBoundingClientRect().width}px`).toBe(token);
      for (const shape of svg.children) {
        await expect(computed(shape, "vector-effect")).toBe("non-scaling-stroke");
        await expect(Number.parseFloat(computed(shape, "stroke-width"))).toBe(1.5);
      }
    }
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
