import { memo, useState, type JSX } from "react";
import { flushSync } from "react-dom";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { withMountCount } from "../../.storybook/decorators.js";
import { useThemeStore } from "../theme/index.js";
import { DensityToggleConnected } from "./DensityToggle.js";
import { PreviewTile } from "./PreviewTile.js";
import { ThemeSwitcherConnected } from "./ThemeSwitcher.js";

/**
 * E05-S04 perf: the theme and density controls beside a 500-row plain table (CMP-049 is capped at 200 rows in v0,
 * so a plain table, as the theme runtime's own benchmark uses). `NoRemount` is deterministic and runs in the
 * storybook gate; `FrameBudget` is a wall-clock benchmark, tagged `perf` (excluded from the gate and from the
 * visual-regression matrix by the repo's `EXCLUDED_TAGS`).
 */
const meta: Meta = {
  title: "Molecules/Theming and density perf",
  parameters: { layout: "padded" },
  decorators: [withMountCount],
};
export default meta;
type Story = StoryObj;

const BUDGET_MS = 16.6;
const WARMUP = 3;
const SAMPLES = 30;
const ROWS = Array.from({ length: 500 }, (_, i) => i);
const TILE_LABEL = "Preview: dark theme sample, 1 decimal, UTC";

let tableRenders = 0;
const Rows = memo(function Rows(): JSX.Element {
  tableRenders += 1;
  return (
    <table aria-label="Five hundred rows">
      <tbody>
        {ROWS.map((i) => (
          <tr key={i} style={{ height: "var(--size-row-height)" }}>
            <th scope="row">{`Row ${i}`}</th>
            <td>{i * 7}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
});

function Page({
  overrides,
}: {
  readonly overrides?: Readonly<Record<string, string>>;
}): JSX.Element {
  return (
    <div>
      <ThemeSwitcherConnected />
      <DensityToggleConnected />
      <DensityToggleConnected form="menu" />
      <div style={{ maxWidth: "24rem" }}>
        <PreviewTile
          kind="theme"
          label={TILE_LABEL}
          {...(overrides ? { tokenOverrides: overrides } : {})}
        />
      </div>
      <Rows />
    </div>
  );
}

const rafs = (): Promise<void> => new Promise((done) => requestAnimationFrame(() => done()));

/** A theme and a density switch mount nothing again: not the story, not a row, and the table is not re-rendered. */
export const NoRemount: Story = {
  render: () => <Page />,
  play: async ({ canvasElement }) => {
    const ui = within(canvasElement);
    const root = document.documentElement;
    const mounts = ui.getByLabelText("Mount count").textContent;
    const row = canvasElement.querySelectorAll("tbody tr")[250];
    const tile = ui.getByRole("img", { name: TILE_LABEL });
    const renders = tableRenders;
    await expect(row).toBeDefined();

    await userEvent.click(ui.getByRole("radio", { name: "High contrast" }));
    await rafs();
    await expect(root).toHaveAttribute("data-theme", "high-contrast");
    await userEvent.click(ui.getAllByRole("radio", { name: "Comfortable" })[0] as HTMLElement);
    await waitFor(() => expect(root).toHaveAttribute("data-density", "comfortable"));

    await expect(ui.getByLabelText("Mount count").textContent).toBe(mounts);
    await expect(canvasElement.querySelectorAll("tbody tr")[250]).toBe(row);
    await expect(row?.isConnected).toBe(true);
    await expect(ui.getByRole("img", { name: TILE_LABEL })).toBe(tile);
    await expect(tableRenders).toBe(renders);
    await expect(ui.getByRole("table", { name: "Five hundred rows" })).toBeVisible();
  },
};

const median = (xs: number[]): number =>
  [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)] ?? 0;

function Bench(): JSX.Element {
  const store = useThemeStore();
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [result, setResult] = useState("");
  const time = (change: () => void): number => {
    const start = performance.now();
    change();
    void document.body.offsetHeight; // force the style recalculation the switch causes
    return performance.now() - start;
  };
  const run = (): void => {
    const css = getComputedStyle(document.documentElement);
    const base = css.getPropertyValue("--color-border-default").trim();
    const alt = css.getPropertyValue("--color-border-strong").trim();
    const themes = ["light", "high-contrast", "dark"] as const;
    const densities = ["comfortable", "compact"] as const;
    const out = { theme: [] as number[], density: [] as number[], tile: [] as number[] };
    for (let i = 0; i < WARMUP + SAMPLES; i += 1) {
      const t = time(() => store.setTheme(themes[i % 3] as (typeof themes)[number]));
      const d = time(() => store.setDensity(densities[i % 2] as (typeof densities)[number]));
      const p = time(() =>
        flushSync(() => setOverrides({ "color.surface.sunken": i % 2 ? alt : base })),
      );
      if (i >= WARMUP) {
        out.theme.push(t);
        out.density.push(d);
        out.tile.push(p);
      }
    }
    setResult(
      JSON.stringify({
        theme: median(out.theme),
        density: median(out.density),
        tile: median(out.tile),
      }),
    );
  };
  return (
    <div>
      <button type="button" onClick={run}>
        Run benchmark
      </button>
      <output aria-label="Benchmark result">{result}</output>
      <Page overrides={overrides} />
    </div>
  );
}

/** Median of 30 warmed switches over 500 rows, and the PreviewTile palette change, each within one frame. */
export const FrameBudget: Story = {
  tags: ["perf"],
  render: () => <Bench />,
  play: async ({ canvasElement }) => {
    const ui = within(canvasElement);
    await userEvent.click(ui.getByRole("button", { name: "Run benchmark" }));
    const ms = JSON.parse(ui.getByLabelText("Benchmark result").textContent ?? "{}") as Record<
      string,
      number
    >;
    await expect(ms["theme"]).toBeLessThan(BUDGET_MS);
    await expect(ms["density"]).toBeLessThan(BUDGET_MS);
    await expect(ms["tile"]).toBeLessThan(BUDGET_MS);
  },
};
