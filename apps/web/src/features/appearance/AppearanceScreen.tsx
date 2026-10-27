import { useState, type CSSProperties, type JSX } from "react";
import { ColorConventionLegend } from "@candleviewer/ui";
import {
  readStoredChartColorMode,
  type ChartConvention,
  type ChartPalette,
} from "../../shell/bootstrap/preferencesApply.js";
import { applyChartColorModeToSurfaces } from "./chartColorMode.js";
import { registeredEngines } from "./engineRegistry.js";

/** Order-flow views that must state their colour convention (US-SET-005 scenario 1). */
export const LEGEND_VIEWS = [
  "Chart",
  "Footprint",
  "DOM ladder",
  "Heatmap",
  "Bubbles",
  "Profile",
] as const;

const TARGET: CSSProperties = {
  minWidth: "var(--size-target-min, 24px)",
  minHeight: "var(--size-target-min, 24px)",
};

/** SCR-116 chart palette / convention section: selects, persists locally, applies everywhere. */
export function AppearanceScreen(): JSX.Element {
  const stored = readStoredChartColorMode();
  const [palette, setPalette] = useState<ChartPalette>(stored.palette ?? "default");
  const [convention, setConvention] = useState<ChartConvention>(stored.convention ?? "standard");
  const [saved, setSaved] = useState(false);

  function change(p: ChartPalette, c: ChartConvention): void {
    setPalette(p);
    setConvention(c);
    applyChartColorModeToSurfaces({ palette: p, convention: c }, registeredEngines());
    try {
      localStorage.setItem("cv.chartColorMode", JSON.stringify({ palette: p, convention: c }));
    } catch {
      // storage unavailable: the choice still applies for this session
    }
    setSaved(true);
  }

  return (
    <div>
      <h1>Appearance</h1>
      <fieldset>
        <legend>Chart palette</legend>
        {(["default", "cvd-safe"] as const).map((p) => (
          <label key={p} style={{ ...TARGET, display: "inline-flex", alignItems: "center" }}>
            <input
              type="radio"
              name="chart-palette"
              value={p}
              checked={palette === p}
              style={TARGET}
              onChange={() => change(p, convention)}
            />
            {p === "default" ? "Default (green / red)" : "Colour-blind safe (blue / orange)"}
          </label>
        ))}
      </fieldset>
      <label style={{ ...TARGET, display: "inline-flex", alignItems: "center" }}>
        <input
          type="checkbox"
          checked={convention === "inverted"}
          style={TARGET}
          onChange={(e) => change(palette, e.target.checked ? "inverted" : "standard")}
        />
        Invert buy/sell colours
      </label>
      <p role="status">{saved ? "Saved." : ""}</p>
      <section aria-label="Preview">
        {LEGEND_VIEWS.map((view) => (
          <ColorConventionLegend key={view} view={view} palette={palette} convention={convention} />
        ))}
      </section>
    </div>
  );
}
