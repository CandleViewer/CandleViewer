import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { DockPanel } from "./DockPanel.js";
import { SplitPane } from "./SplitPane.js";

function Demo({
  direction,
  initial,
  mins,
}: {
  direction: "row" | "column";
  initial: number[];
  mins?: number[];
}): JSX.Element {
  const [sizes, setSizes] = useState(initial);
  const names = ["Chart", "DOM", "Tape", "CVD"].slice(0, initial.length);
  return (
    <div style={{ height: "16rem", display: "flex" }}>
      <SplitPane
        direction={direction}
        sizes={sizes}
        {...(mins === undefined ? {} : { minSizes: mins })}
        labels={names.slice(1).map((n, i) => `${names[i]} and ${n} splitter`)}
        cells={names.map((n) => ({ key: n, content: <DockPanel title={n} /> }))}
        onResize={(i, d) =>
          setSizes((s) => s.map((v, k) => (k === i ? v + d : k === i + 1 ? v - d : v)))
        }
      />
    </div>
  );
}

/** CMP-083: the dock's separators and the in-panel split. */
const meta: Meta<typeof SplitPane> = { title: "Organisms/Dock/SplitPane", component: SplitPane };
export default meta;
type Story = StoryObj<typeof SplitPane>;

export const Horizontal: Story = { render: () => <Demo direction="row" initial={[0.5, 0.5]} /> };
export const Vertical: Story = { render: () => <Demo direction="column" initial={[0.5, 0.5]} /> };
export const NAry: Story = {
  render: () => <Demo direction="row" initial={[0.4, 0.3, 0.2, 0.1]} />,
};
export const AtMinimum: Story = {
  render: () => <Demo direction="row" initial={[0.8, 0.2]} mins={[0.2, 0.2]} />,
};

/**
 * The keyboard resize demo: arrows 2 %, Shift+arrows 10 %, End moves this separator to the
 * maximum, Home sets equal sizes. Home's reach differs by host: with `onEqualise` (the dock wires
 * it, E15-D04 §6) it equalises the whole split; without it, as here, only the separator's pair.
 * Arrow keys are physical (Left/Up shrink the cell before): the app is LTR only, so no RTL mirror.
 */
export const KeyboardResize: Story = {
  render: () => <Demo direction="row" initial={[0.5, 0.5]} mins={[0.2, 0.2]} />,
  play: async ({ canvasElement }) => {
    const separator = within(canvasElement).getByRole("separator", {
      name: "Chart and DOM splitter",
    });
    separator.focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(separator).toHaveAttribute("aria-valuenow", "52");
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    await expect(separator).toHaveAttribute("aria-valuenow", "42");
    await userEvent.keyboard("{End}");
    await expect(separator).toHaveAttribute("aria-valuenow", "80");
    await userEvent.keyboard("{Home}");
    await expect(separator).toHaveAttribute("aria-valuenow", "50");
  },
};
