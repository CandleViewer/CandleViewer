import { usePreferences } from "./PreferencesContext";
import type { A11yPreferences, TriState } from "./model";

interface ToggleProps {
  readonly id: string;
  readonly label: string;
  readonly help: string;
  readonly checked: boolean;
  readonly onChange: (v: boolean) => void;
}

function Toggle({ id, label, help, checked, onChange }: ToggleProps): JSX.Element {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="checkbox"
        role="switch"
        checked={checked}
        aria-describedby={`${id}-d`}
        onChange={(e) => onChange(e.target.checked)}
      />
      <p id={`${id}-d`}>{help}</p>
    </div>
  );
}

interface RadiosProps<T extends string> {
  readonly name: string;
  readonly legend: string;
  readonly help: string;
  readonly value: T;
  readonly options: readonly { value: T; label: string }[];
  readonly onChange: (v: T) => void;
}

function Radios<T extends string>(p: RadiosProps<T>): JSX.Element {
  return (
    <fieldset aria-describedby={`${p.name}-d`}>
      <legend>{p.legend}</legend>
      <p id={`${p.name}-d`}>{p.help}</p>
      {p.options.map((o) => (
        <label key={o.value}>
          <input
            type="radio"
            name={p.name}
            value={o.value}
            checked={p.value === o.value}
            onChange={() => p.onChange(o.value)}
          />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

function triOptions(system: boolean): { value: TriState; label: string }[] {
  return [
    { value: "system", label: `${system ? "On" : "Off"} (from system)` },
    { value: "on", label: "On" },
    { value: "off", label: "Off" },
  ];
}

export function AccessibilitySettingsScreen(): JSX.Element {
  const { prefs, media, update, saveError, retry } = usePreferences();
  const set = (patch: Partial<A11yPreferences>): void => void update(patch);
  return (
    <section
      id="accessibility"
      aria-labelledby="a11y-h"
      style={{ maxWidth: "60rem", overflowWrap: "anywhere" }}
    >
      <h2 id="a11y-h">Accessibility</h2>
      <p>Changes apply immediately, including chart canvases. They are saved to your account.</p>
      <div role="status" aria-live="polite">
        {saveError ? (
          <span role="alert">
            {saveError} <button onClick={() => void retry()}>Retry</button>
          </span>
        ) : null}
      </div>
      <Radios
        name="reduced-motion"
        legend="Reduced motion"
        help="Stops transitions, heatmap fade, chart inertia and flash-on-tick."
        value={prefs.reduced_motion}
        options={triOptions(media.reducedMotion)}
        onChange={(v) => set({ reduced_motion: v })}
      />
      <Radios
        name="contrast"
        legend="Increased contrast"
        help="Uses higher-contrast colours throughout."
        value={prefs.increased_contrast}
        options={triOptions(media.highContrast)}
        onChange={(v) => set({ increased_contrast: v })}
      />
      <Toggle
        id="canvas-anim"
        label="Disable canvas animation"
        help="Chart canvases stop animating and the heatmap updates instantly."
        checked={prefs.disable_canvas_animation}
        onChange={(v) => set({ disable_canvas_animation: v })}
      />
      <Toggle
        id="tables"
        label="Always show data-table alternatives"
        help="Panels open in their table view by default; no data is re-fetched."
        checked={prefs.always_show_tables}
        onChange={(v) => set({ always_show_tables: v })}
      />
      <Toggle
        id="focus"
        label="Increase focus-ring thickness"
        help="Draws a thicker outline around the focused control."
        checked={prefs.thick_focus_ring}
        onChange={(v) => set({ thick_focus_ring: v })}
      />
      <Radios
        name="announce"
        legend="Announce price updates"
        help="How often screen readers hear price changes."
        value={prefs.announce_prices}
        options={[
          { value: "off", label: "Off" },
          { value: "significant", label: "On significant change" },
          { value: "always", label: "Always" },
        ]}
        onChange={(v) => set({ announce_prices: v })}
      />
      <Radios
        name="verbosity"
        legend="Screen-reader verbosity for the tape"
        help="Low announces only significant events."
        value={prefs.verbosity}
        options={[
          { value: "low", label: "Low" },
          { value: "normal", label: "Normal" },
          { value: "high", label: "High" },
        ]}
        onChange={(v) => set({ verbosity: v })}
      />
      <Toggle
        id="kbd"
        label="Keyboard-only mode"
        help="Hides drag-only interactions and shows nudge controls and numeric fields instead."
        checked={prefs.keyboard_only}
        onChange={(v) => set({ keyboard_only: v })}
      />
      <p>
        <a href="/accessibility">Accessibility statement</a> |{" "}
        <a href="/settings/hotkeys">Keyboard shortcuts (SCR-013)</a>
      </p>
    </section>
  );
}
