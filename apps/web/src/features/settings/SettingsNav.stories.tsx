import type { JSX } from "react";
import { SettingsNavView } from "./SettingsNavView";

// CMP-086 SettingsNav (E47-S08). The router-coupled wrapper (`SettingsNav`) lives in apps/web; these stories render
// the router-free view with plain anchors, so packages/ui needs no router. Plain CSF, no storybook types.
export default { title: "Organisms/SettingsNav", component: SettingsNavView };

function At({ current }: { readonly current: string | null }): JSX.Element {
  return <SettingsNavView current={current} />;
}

/** Appearance open: aria-current on its link; sections not built yet disabled with their reason. */
export const Default = { render: () => <At current="appearance" /> };

/** Two sections on one route: Security open. */
export const SecurityOpen = { render: () => <At current="security" /> };

/** A route that is no section (R-205): no item is current. */
export const NoCurrentSection = { render: () => <At current={null} /> };
