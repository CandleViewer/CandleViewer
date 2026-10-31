import type { JSX } from "react";
import { announcePolite } from "../theme/a11y.js";
import { useDensity } from "../theme/ThemeProvider.js";
import { DENSITIES, type DensityName } from "../theme/store.js";
import {
  SegmentedControl,
  type SegmentedControlBaseProps,
  type SegmentedOption,
  type SegmentedOptions,
} from "./SegmentedControl.js";

/**
 * Default English copy (BQ-21: copy as props, defaults exported beside the component). The panel
 * sentence follows E11-D05's form ("Chart panel density: compact"). The global sentence is the host's
 * key and none is written yet (J16), so `globalAnnouncement` is an English placeholder default that a
 * host overrides through `copy`.
 */
export const DENSITY_TOGGLE_COPY: DensityToggleCopy = {
  groupLabel: "Density",
  options: { compact: "Compact", comfortable: "Comfortable" },
  panelGroupLabel: (panel: string): string => `${panel} density`,
  globalAnnouncement: (label: string): string => `Density: ${label}`,
  panelAnnouncement: (panel: string, label: string): string =>
    `${panel} density: ${label.toLowerCase()}`,
};

export interface DensityToggleCopy {
  readonly groupLabel: string;
  readonly options: Readonly<Record<DensityName, string>>;
  readonly panelGroupLabel: (panel: string) => string;
  readonly globalAnnouncement: (label: string) => string;
  readonly panelAnnouncement: (panel: string, label: string) => string;
}

interface DensityToggleCommon {
  readonly copy?: Partial<DensityToggleCopy>;
  /** Passed through to CMP-003 (its size). */
  readonly size?: "sm" | "md";
  /** Passed through to CMP-003 (its full-width layout). */
  readonly fullWidth?: boolean;
  /** Passed through to CMP-003's disabled state, which CMP-003 owns and draws. */
  readonly disabled?: boolean;
  /** Renders the control itself at this density (`data-density`); absent = inherit. */
  readonly density?: DensityName;
}

export interface DensityToggleGlobalProps extends DensityToggleCommon {
  readonly scope?: "global";
  readonly value: DensityName;
  readonly onChange: (value: DensityName) => void;
}

export interface DensityTogglePanelProps extends DensityToggleCommon {
  readonly scope: "panel";
  /** The panel's name: it names the group and leads the sentence ("Chart panel density: compact"). */
  readonly panelName: string;
  readonly value: DensityName;
  readonly onChange: (value: DensityName) => void;
}

export type DensityToggleProps = DensityToggleGlobalProps | DensityTogglePanelProps;

const option = (copy: DensityToggleCopy, value: DensityName): SegmentedOption => ({
  value,
  label: copy.options[value],
});

/**
 * CMP-063: the density switch, CMP-003's segmented form. The `menuitemradio` menu form (`form`
 * prop, the MenuForm story) is slice H's.
 * Props only: it emits no analytics (the store is the one emitter, BQ-16). A committed user change
 * speaks one polite sentence (J16); a new `value` from the host (initial load, a server-fed apply)
 * speaks nothing, because only the change handler announces. Global offers exactly the runtime's
 * DENSITIES in both scopes (BQ-19). J14's chart-panel Dense is not offered: no runtime density
 * carries it, and its naming reconcile is slice H's row.
 */
export function DensityToggle(props: DensityToggleProps): JSX.Element {
  const copy: DensityToggleCopy = { ...DENSITY_TOGGLE_COPY, ...props.copy };
  const [compact, comfortable] = DENSITIES;
  const panel = props.scope === "panel" ? props : undefined;
  const values: readonly DensityName[] = [compact, comfortable];
  const options: SegmentedOptions = [option(copy, compact), option(copy, comfortable)];
  const onChange = (raw: string): void => {
    const next = values.find((v) => v === raw);
    if (next === undefined) return;
    const label = copy.options[next];
    if (panel !== undefined) {
      panel.onChange(next);
      announcePolite(copy.panelAnnouncement(panel.panelName, label));
    } else if (props.scope !== "panel") {
      props.onChange(next);
      announcePolite(copy.globalAnnouncement(label));
    }
  };
  const pass: Pick<SegmentedControlBaseProps, "size" | "fullWidth" | "disabled" | "density"> = {
    ...(props.size === undefined ? {} : { size: props.size }),
    ...(props.fullWidth === undefined ? {} : { fullWidth: props.fullWidth }),
    ...(props.disabled === undefined ? {} : { disabled: props.disabled }),
    ...(props.density === undefined ? {} : { density: props.density }),
  };
  return (
    <div
      className="cv-density-toggle"
      data-cmp="CMP-063"
      data-scope={panel === undefined ? "global" : "panel"}
      data-full-width={props.fullWidth === true ? "" : undefined}
    >
      <SegmentedControl
        {...pass}
        aria-label={panel === undefined ? copy.groupLabel : copy.panelGroupLabel(panel.panelName)}
        options={options}
        value={props.value}
        onChange={onChange}
      />
    </div>
  );
}

export type DensityToggleConnectedProps = Omit<
  DensityToggleGlobalProps,
  "scope" | "value" | "onChange"
>;

/**
 * CMP-063 bound to the theme runtime (BQ-15): the global scope, reading and writing the provider's
 * store. `setDensity` is the store's, so the store alone emits `appearance.density_changed`.
 */
export function DensityToggleConnected(props: DensityToggleConnectedProps): JSX.Element {
  const [value, setDensity] = useDensity();
  return <DensityToggle {...props} scope="global" value={value} onChange={setDensity} />;
}
