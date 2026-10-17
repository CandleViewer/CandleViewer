import { memo, useLayoutEffect, useRef, useState, type JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import {
  DENSITIES,
  MOTION_OVERRIDES,
  TEXT_SCALES,
  THEMES,
  toggleHighContrastAnnounced,
  useReducedMotion,
  useThemeSnapshot,
  useThemeStore,
} from "./index.js";

/** Style-recalculation budget for a theme or density switch over 500 dense rows (ticket AC "One-frame budget"). */
const BUDGET_MS = 16.6;
const ROWS = Array.from({ length: 500 }, (_, i) => i);
const PAGE = {
  background: "var(--color-surface-app)",
  color: "var(--color-text-primary)",
  padding: "var(--space-inset-md)",
};

let mounts = 0;
/** Counts mounts, not renders (a layout effect, so the value exists before the play function reads it). */
function MountProbe(): JSX.Element {
  const out = useRef<HTMLOutputElement>(null);
  useLayoutEffect(() => {
    mounts += 1;
    if (out.current) out.current.value = String(mounts);
  }, []);
  return <output ref={out} aria-label="Mount count" />;
}

interface ChoiceProps<T extends string | number> {
  readonly legend: string;
  readonly options: readonly T[];
  readonly value: T;
  readonly onChange: (value: T) => void;
}

function Choice<T extends string | number>(props: ChoiceProps<T>): JSX.Element {
  return (
    <fieldset>
      <legend>{props.legend}</legend>
      {props.options.map((option) => (
        <label key={option}>
          <input
            type="radio"
            name={props.legend}
            checked={props.value === option}
            onChange={() => props.onChange(option)}
          />
          {option}
        </label>
      ))}
    </fieldset>
  );
}

function Playground(): JSX.Element {
  const store = useThemeStore();
  const s = useThemeSnapshot();
  const [reduced] = useReducedMotion();
  return (
    <main style={PAGE}>
      <h1>Theme runtime</h1>
      <Choice legend="Theme" options={THEMES} value={s.theme} onChange={store.setTheme} />
      <Choice legend="Density" options={DENSITIES} value={s.density} onChange={store.setDensity} />
      <Choice
        legend="Reduced motion"
        options={MOTION_OVERRIDES}
        value={s.motionOverride}
        onChange={store.setMotionOverride}
      />
      <Choice
        legend="Text scale"
        options={TEXT_SCALES}
        value={s.textScale}
        onChange={store.setTextScale}
      />
      <label>
        <input
          type="checkbox"
          checked={s.matchSystem}
          onChange={(e) => store.apply({ matchSystem: e.target.checked })}
        />
        Match system theme
      </label>
      <button type="button" onClick={() => toggleHighContrastAnnounced(store)}>
        Toggle high contrast (Ctrl+Shift+H)
      </button>
      <p>{reduced ? "Motion is reduced" : "Motion is allowed"}</p>
      <MountProbe />
    </main>
  );
}

const Rows = memo(function Rows(): JSX.Element {
  return (
    <table>
      <caption>500 dense rows</caption>
      <tbody>
        {ROWS.map((i) => (
          <tr
            key={i}
            style={{ height: "var(--size-row-height)", background: "var(--color-surface-raised)" }}
          >
            <th scope="row">{`Row ${i}`}</th>
            <td>{i * 7}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
});

function Benchmark(): JSX.Element {
  const store = useThemeStore();
  const [result, setResult] = useState("");
  const run = (): void => {
    const time = (change: () => void): number => {
      const start = performance.now();
      change();
      void getComputedStyle(document.documentElement).color; // forces the style recalculation (not layout) now
      return performance.measure("theme-switch", { start, end: performance.now() }).duration;
    };
    const { theme, density } = store.getSnapshot();
    setResult(
      JSON.stringify({
        theme: time(() => store.setTheme(theme === "dark" ? "light" : "dark")),
        density: time(() => store.setDensity(density === "compact" ? "comfortable" : "compact")),
      }),
    );
  };
  return (
    <main style={PAGE}>
      <h1>Style recalculation benchmark</h1>
      <button type="button" onClick={run}>
        Run benchmark
      </button>
      <output aria-label="Benchmark result">{result}</output>
      <Rows />
    </main>
  );
}

const meta: Meta = { title: "Theme/Runtime", parameters: { layout: "fullscreen" } };
export default meta;
type Story = StoryObj;

/** Instant swap without remount: switching theme and density leaves the mount count unchanged. */
export const Default: Story = {
  render: () => <Playground />,
  play: async ({ canvasElement }) => {
    const ui = within(canvasElement);
    const before = ui.getByLabelText("Mount count").textContent;
    await userEvent.click(ui.getByRole("radio", { name: "high-contrast" }));
    await userEvent.click(ui.getByRole("radio", { name: "comfortable" }));
    await userEvent.click(ui.getByRole("radio", { name: "on" }));
    const root = document.documentElement.dataset;
    await expect([root["theme"], root["density"], root["motion"]]).toEqual([
      "high-contrast",
      "comfortable",
      "reduce",
    ]);
    await expect(ui.getByLabelText("Mount count").textContent).toBe(before);
  },
};

/** One-frame budget: theme and density switches over 500 rows stay within 16.6 ms. */
export const StyleRecalcBenchmark: Story = {
  render: () => <Benchmark />,
  play: async ({ canvasElement }) => {
    const ui = within(canvasElement);
    await userEvent.click(ui.getByRole("button", { name: "Run benchmark" }));
    const ms = JSON.parse(ui.getByLabelText("Benchmark result").textContent ?? "{}") as Record<
      string,
      number
    >;
    await expect(ms["theme"]).toBeLessThan(BUDGET_MS);
    await expect(ms["density"]).toBeLessThan(BUDGET_MS);
  },
};
