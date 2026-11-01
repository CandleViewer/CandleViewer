import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Heading, MonoText, NumericText, Text, type NumSize } from "./Typography.js";

const col = { display: "grid", gap: "var(--space-inset-sm)", maxWidth: "36rem" } as const;
const cellStyle = { textAlign: "right", padding: "0 var(--space-inset-sm)" } as const;
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

/** The semantic level never follows the look: an h1 drawn small, an h2 drawn as display. */
export const HeadingLevelVsStyle: Story = {
  render: () => (
    <div style={col}>
      <Heading level={1} variant="heading-sm">
        Level 1, heading-sm
      </Heading>
      <Heading level={2} variant="display">
        Level 2, display
      </Heading>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 1 })).toHaveAttribute(
      "data-variant",
      "heading-sm",
    );
    await expect(canvas.getByRole("heading", { level: 2 })).toHaveAttribute(
      "data-variant",
      "display",
    );
  },
};

const ROWS = [
  { label: "price", node: (v: number) => <NumericText value={v} format="price" /> },
  { label: "qty", node: (v: number) => <NumericText value={v / 1000} format="qty" /> },
  { label: "pct", node: (v: number) => <NumericText value={v / 100} format="pct" /> },
  {
    label: "pnl",
    node: (v: number) => <NumericText value={v} format="pnl" signDisplay="always" />,
  },
  { label: "notional", node: (v: number) => <NumericText value={v * 3000} format="notional" /> },
  {
    label: "price, sign always",
    node: (v: number) => <NumericText value={v} format="price" signDisplay="always" />,
  },
  {
    label: "qty, sign never",
    node: (v: number) => <NumericText value={v / 1000} format="qty" signDisplay="never" />,
  },
] as const;

function Formats(): JSX.Element {
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">Format</th>
          <th scope="col">Positive</th>
          <th scope="col">Negative</th>
          <th scope="col">Zero</th>
        </tr>
      </thead>
      <tbody>
        {ROWS.map((row) => (
          <tr key={row.label}>
            <th scope="row">
              <Text variant="label">{row.label}</Text>
            </th>
            {[420, -420, 0].map((v) => (
              <td key={v} style={cellStyle}>
                {row.node(v)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Every format with a positive, a negative and a zero value; zero is never signed. */
export const NumericFormats: Story = {
  render: () => <Formats />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("row", { name: /^pnl/ })).toHaveTextContent(
      "pnl+420.00-420.000.00",
    );
  },
};

function PnL(): JSX.Element {
  return (
    <div style={col}>
      {[420, -420, 0].map((v) => (
        <NumericText key={v} value={v} format="pnl" signDisplay="always" colorBySign />
      ))}
    </div>
  );
}

/** Colour by sign always carries the + / − glyph; zero is neutral and unsigned. */
export const PnLColoring: Story = {
  render: () => <PnL />,
  play: async ({ canvasElement }) => {
    const [up, down, zero] = canvasElement.querySelectorAll(".cv-num");
    await expect(up).toHaveTextContent("+420.00");
    await expect(down).toHaveTextContent("-420.00");
    await expect(zero).toHaveAttribute("data-sign", "zero");
  },
};

const themed = (theme: string): Story => ({
  globals: { theme },
  render: () => (
    <div style={col}>
      <Scale />
      <PnL />
    </div>
  ),
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");

/** E15: the visible "1.2M" is hidden from assistive technology, which reads "1,200,000". */
export const AbbreviatedWithExpandedReading: Story = {
  render: () => (
    <table>
      <tbody>
        <tr>
          <th scope="row">Notional</th>
          <td style={cellStyle}>
            <NumericText value={1_200_000} format="notional" />
          </td>
        </tr>
      </tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("cell", { name: "1,200,000" })).toBeVisible();
  },
};

const COLUMN = [1111.11, 8888.88, -42.5, 0, 70707.07];

/**
 * The AC: tabular numerics come from the component, so every digit advances identically. JetBrains
 * Mono is monospace already, so the equal widths alone prove little: the `fontVariantNumeric`
 * assertion is the real proof that the component, not the font or the consumer, sets them.
 */
export const TabularColumn: Story = {
  render: () => (
    <div style={{ display: "grid", justifyItems: "end", width: "10rem" }}>
      {COLUMN.map((v) => (
        <NumericText key={v} value={v} format="price" />
      ))}
      <NumericText value={11} format="qty" precision={0} data-testid="ones" />
      <NumericText value={88} format="qty" precision={0} data-testid="eights" />
    </div>
  ),
  play: async ({ canvasElement }) => {
    for (const el of canvasElement.querySelectorAll<HTMLElement>(".cv-num")) {
      await expect(getComputedStyle(el).fontVariantNumeric).toBe("tabular-nums");
    }
    const canvas = within(canvasElement);
    const ones = canvas.getByTestId("ones").getBoundingClientRect().width;
    const eights = canvas.getByTestId("eights").getBoundingClientRect().width;
    await expect(Math.abs(ones - eights)).toBeLessThan(0.5);
  },
};

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
