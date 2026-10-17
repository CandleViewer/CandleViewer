import { memo, useLayoutEffect, useRef, useState, type JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import {
  DENSITIES,
  MOTION_OVERRIDES,
  TEXT_SCALES,
  THEMES,
  toggleHighContrastAnnounced,
  useThemeSnapshot,
  useThemeStore,
} from "./index.js";

/** Style-recalculation budget for a theme or density switch over 500 dense rows (ticket AC "One-frame budget"). */
const BUDGET_MS = 16.6;
/** The first switches after load are cold (computed-style caches fill up): they are discarded, the median of the rest is reported. */
const WARMUP = 3;
const SAMPLES = 30;
const ROWS = Array.from({ length: 500 }, (_, i) => i);
const PAGE = {
  background: "var(--color-surface-app)",
  color: "var(--color-text-primary)",
  fontFamily: "var(--font-family-ui), system-ui, sans-serif",
  minHeight: "100vh",
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
  /** Appended to each label, so a bare number reads as a quantity ("150 %"). */
  readonly unit?: string;
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
          {`${option}${props.unit ?? ""}`}
        </label>
      ))}
    </fieldset>
  );
}

function Playground(): JSX.Element {
  const store = useThemeStore();
  const s = useThemeSnapshot();
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
    const sweep = (change: () => void): number => {
      const ms = Array.from({ length: WARMUP + SAMPLES }, () => time(change)).slice(WARMUP);
      return ms.sort((a, b) => a - b)[SAMPLES / 2] ?? Infinity;
    };
    setResult(
      JSON.stringify({
        theme: sweep(() => store.setTheme(store.getSnapshot().theme === "dark" ? "light" : "dark")),
        density: sweep(() =>
          store.setDensity(store.getSnapshot().density === "compact" ? "comfortable" : "compact"),
        ),
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

/** Unbreakable text in a box of fixed width: it has to reflow, not clip or scroll sideways, as text grows (WCAG 1.4.4, 1.4.10). */
const UNBREAKABLE = "CANCEL_ALL_WORKING_ORDERS";
/** The reflow reference width in CSS px; unlike rem or em it does not grow with the text scale. A fixture, not a design value. */
const BOX_WIDTH = 320;

function Reflow(): JSX.Element {
  const store = useThemeStore();
  const { textScale } = useThemeSnapshot();
  return (
    <main style={PAGE}>
      <h1>Text scale reflow</h1>
      <Choice
        legend="Text scale"
        options={TEXT_SCALES}
        unit=" %"
        value={textScale}
        onChange={store.setTextScale}
      />
      <p style={{ width: `${BOX_WIDTH}px`, overflowWrap: "anywhere" }}>{UNBREAKABLE}</p>
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

/** Reflow: every text scale and a 200 % text zoom leave the fixed-width text inside its box (ticket: 125 % and 200 %). */
export const TextScaleReflow: Story = {
  render: () => <Reflow />,
  play: async ({ canvasElement }) => {
    const ui = within(canvasElement);
    const text = ui.getByText(UNBREAKABLE);
    const fits = async (): Promise<void> => {
      await expect(text.scrollWidth).toBeLessThanOrEqual(text.clientWidth);
    };
    const pick = (scale: number): Promise<void> =>
      userEvent.click(ui.getByRole("radio", { name: `${scale} %` }));
    for (const scale of TEXT_SCALES) {
      await pick(scale); // 100 first: the preview store outlives a story, so this is a known start
      const factor = getComputedStyle(document.documentElement).getPropertyValue("--cv-text-scale");
      await expect(factor.trim()).toBe(String(scale / 100));
      await fits();
    }
    await pick(100);
    text.style.fontSize = "200%"; // text-only zoom on top of the page text size
    await fits();
  },
};

/** One-frame budget: the median of 30 warmed theme and density switches over 500 rows stays within 16.6 ms. */
export const StyleRecalcBenchmark: Story = {
  render: () => <Benchmark />,
  play: async ({ canvasElement }) => {
    const ui = within(canvasElement);
    const token = getComputedStyle(document.documentElement).getPropertyValue("--size-row-compact");
    await expect(token, "token CSS missing: run `build:tokens` first").not.toBe("");
    await userEvent.click(ui.getByRole("button", { name: "Run benchmark" }));
    const ms = JSON.parse(ui.getByLabelText("Benchmark result").textContent ?? "{}") as Record<
      string,
      number
    >;
    await expect(ms["theme"]).toBeLessThan(BUDGET_MS);
    await expect(ms["density"]).toBeLessThan(BUDGET_MS);
  },
};
