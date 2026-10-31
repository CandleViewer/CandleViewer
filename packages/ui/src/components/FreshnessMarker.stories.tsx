import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import {
  DATA_CONFIDENCE_PRECEDENCE,
  FreshnessMarker,
  freshnessClassName,
} from "./FreshnessMarker.js";

/**
 * CMP-239's compact presentation (E08-D07 §5): the age chip a dense grid draws once per row, and the class swap a
 * degraded cell takes. The chip form with every state's word is CMP-239's base, built with its first consumer.
 */
const meta: Meta<typeof FreshnessMarker> = {
  title: "Atoms/FreshnessMarker",
  component: FreshnessMarker,
  args: { presentation: "compact", state: "stale", lastUpdatedAgeMs: 7000 },
};
export default meta;
type Story = StoryObj<typeof FreshnessMarker>;

/** Stale, T1 (E08-D07 D1): the subtle chip, "Stale 7s", read "Stale, 7 seconds". */
export const Stale: Story = {
  play: async ({ canvasElement }) => {
    const chip = canvasElement.querySelector('[data-cmp="CMP-239"]') as HTMLElement;
    await expect(chip).toHaveAttribute("data-level", "subtle");
    await expect(within(chip).getByText("Stale, 7 seconds")).toBeInTheDocument();
  },
};

/** Stale past T2 (15 s): the strong chip. */
export const StaleEscalated: Story = {
  args: { lastUpdatedAgeMs: 15_000, escalated: true },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector('[data-cmp="CMP-239"]')).toHaveAttribute(
      "data-level",
      "strong",
    );
  },
};

/** Flagged by the server (`meta.stale`, E17-D01 L149): "Stale (server)", T1's style until T2. */
export const StaleServer: Story = {
  args: { label: "Stale (server)" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement).toHaveTextContent("Stale (server)");
  },
};

/** The age in its largest whole unit (E08-D07 D34): seconds, then minutes, then hours. */
export const AgeFormats: Story = {
  render: () => (
    <div style={{ display: "flex", gap: "1rem" }}>
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={7000} />
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={125_000} escalated />
      <FreshnessMarker
        presentation="compact"
        state="stale"
        lastUpdatedAgeMs={3_700_000}
        escalated
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const shown = [...canvasElement.querySelectorAll('[data-cmp="CMP-239"] [aria-hidden="true"]')];
    await expect(shown.map((node) => node.textContent)).toEqual([
      "Stale 7s",
      "Stale 2m",
      "Stale 1h",
    ]);
  },
};

/**
 * The cell marker: each degraded state is one className on the cell that holds the value, never a node of its own
 * (`freshnessClassName`); `live` adds nothing. The state names beside the cells are this page's, not the marker's.
 */
export const CellClasses: Story = {
  render: () => (
    <table>
      <tbody>
        {DATA_CONFIDENCE_PRECEDENCE.map((state) => (
          <tr key={state}>
            <th scope="row" style={{ textAlign: "start", paddingInlineEnd: "1rem" }}>
              {state}
            </th>
            <td className={freshnessClassName(state)} style={{ paddingInline: "0.5rem" }}>
              64,012.50
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    const cells = [...canvasElement.querySelectorAll("td")];
    await expect(cells.map((cell) => cell.childNodes.length)).toEqual(cells.map(() => 1));
    await expect(cells.at(-1)?.className ?? "").toBe("");
  },
};
