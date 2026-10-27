import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Heading, MonoText, Text, type NumSize } from "./Typography.js";

const col = { display: "grid", gap: "var(--space-inset-sm)", maxWidth: "36rem" } as const;
const SIZES: readonly NumSize[] = ["xs", "sm", "base", "md", "lg", "xl"];

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof Text> = {
  title: "Atoms/Typography",
  component: Text,
};
export default meta;
type Story = StoryObj<typeof Text>;

function Scale(): JSX.Element {
  return (
    <div style={col}>
      <Heading level={2} variant="display">
        Display
      </Heading>
      <Heading level={3} variant="heading-lg">
        Heading large
      </Heading>
      <Heading level={4} variant="heading-md">
        Heading medium
      </Heading>
      <Heading level={5} variant="heading-sm">
        Heading small
      </Heading>
      <Text variant="body-strong">Body strong</Text>
      <Text>Body</Text>
      <Text variant="label">Label</Text>
      <Text variant="caption" tone="secondary">
        Caption, secondary tone
      </Text>
      {SIZES.map((size) => (
        <MonoText key={size} size={size}>
          {`num.${size} 0123456789 ord-7f3a`}
        </MonoText>
      ))}
    </div>
  );
}

export const TypeScale: Story = {
  render: () => <Scale />,
  play: async ({ canvasElement }) => {
    for (const el of canvasElement.querySelectorAll<HTMLElement>(".cv-mono")) {
      await expect(getComputedStyle(el).fontVariantNumeric).toBe("tabular-nums");
    }
  },
};

/** The semantic level never follows the look: an h1 drawn small, an h4 drawn as display. */
export const HeadingLevelVsStyle: Story = {
  render: () => (
    <div style={col}>
      <Heading level={1} variant="heading-sm">
        Level 1, heading-sm
      </Heading>
      <Heading level={4} variant="display">
        Level 4, display
      </Heading>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 1 })).toHaveAttribute(
      "data-variant",
      "heading-sm",
    );
    await expect(canvas.getByRole("heading", { level: 4 })).toHaveAttribute(
      "data-variant",
      "display",
    );
  },
};

const themed = (theme: string): Story => ({
  globals: { theme },
  render: () => (
    <div style={col}>
      <Scale />
    </div>
  ),
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");

export const LongText: Story = {
  render: () => (
    <div style={{ width: "12rem" }}>
      <Text as="p">
        Body text wraps within its container and never truncates: a long explanation keeps every
        word available to the reader.
      </Text>
      <MonoText>ord-7f3a9c2e-5b1d-4e8a-9f60-1c2d3e4f5a6b</MonoText>
    </div>
  ),
};
