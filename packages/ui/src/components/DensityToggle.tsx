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

/** The runtime's densities, plus `dense`, offered only on a chart panel's override (E05-D02 J14). */
export type DensityToggleValue = DensityName | "dense";

/**
 * Default English copy (plan gap 9 / BQ-21: copy as props, defaults exported beside the component).
 * The panel sentence is E11-D05's ("Chart panel density: dense"); the global one is the host's key,
 * none being written yet (J16), so this default is a stand-in the host replaces.
 */
export const DENSITY_TOGGLE_COPY: DensityToggleCopy = {
  groupLabel: "Density",
  options: { compact: "Compact", comfortable: "Comfortable", dense: "Dense" },
  panelGroupLabel: (panel: string): string => `${panel} density`,
  globalAnnouncement: (label: string): string => `Density: ${label}`,
  panelAnnouncement: (panel: string, label: string): string =>
    `${panel} density: ${label.toLowerCase()}`,
};

export interface DensityToggleCopy {
  readonly groupLabel: string;
  readonly options: Readonly<Record<DensityToggleValue, string>>;
  readonly panelGroupLabel: (panel: string) => string;
  readonly globalAnnouncement: (label: string) => string;
  readonly panelAnnouncement: (panel: string, label: string) => string;
}

interface DensityToggleCommon {
  readonly copy?: Partial<DensityToggleCopy>;
  readonly size?: "sm" | "md";
  readonly fullWidth?: boolean;
  /** No reason form: every role changes the density on this device, so there is no T2 (J15 (a)). */
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
  /** The panel's name: it names the group and leads the sentence ("Chart panel density: dense"). */
  readonly panelName: string;
  /** A chart panel adds Dense (E11-D02 CR-8); no other panel offers it. */
  readonly chartPanel?: boolean;
  readonly value: DensityToggleValue;
  readonly onChange: (value: DensityToggleValue) => void;
}

export type DensityToggleProps = DensityToggleGlobalProps | DensityTogglePanelProps;

const option = (copy: DensityToggleCopy, value: DensityToggleValue): SegmentedOption => ({
  value,
  label: copy.options[value],
});

/**
 * CMP-063: the density switch, CMP-003's segmented form (the `menuitemradio` form is E05-S03's).
 * Props only: it emits no analytics (the store is the one emitter, BQ-16). A committed user change
 * speaks one polite sentence (J16); a new `value` from the host (initial load, a server-fed apply)
 * speaks nothing, because only the change handler announces. Global offers exactly the runtime's
 * DENSITIES (BQ-19); a chart panel's override adds Dense (J14).
 */
export function DensityToggle(props: DensityToggleProps): JSX.Element {
  const copy: DensityToggleCopy = { ...DENSITY_TOGGLE_COPY, ...props.copy };
  const [compact, comfortable] = DENSITIES;
  const panel = props.scope === "panel" ? props : undefined;
  const dense = panel?.chartPanel === true;
  const values: readonly DensityToggleValue[] = dense
    ? [compact, comfortable, "dense"]
    : [compact, comfortable];
  const first = option(copy, compact);
  const second = option(copy, comfortable);
  const options: SegmentedOptions = dense
    ? [first, second, option(copy, "dense")]
    : [first, second];
  const onChange = (raw: string): void => {
    const next = values.find((v) => v === raw);
    if (next === undefined) return;
    const label = copy.options[next];
    if (panel !== undefined) {
      panel.onChange(next);
      announcePolite(copy.panelAnnouncement(panel.panelName, label));
    } else if (props.scope !== "panel" && next !== "dense") {
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
