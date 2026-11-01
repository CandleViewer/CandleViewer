import type { JSX } from "react";
import { MemoryRouter } from "react-router";
import { SettingsNav } from "./SettingsNav";

// CMP-086 SettingsNav (E47-S08). It lives in apps/web because it is coupled to the router (`Link`,
// `useLocation`); the story is picked up by the packages/ui Storybook glob. Plain CSF, no storybook types,
// so apps/web takes no storybook dependency.
export default { title: "Organisms/SettingsNav", component: SettingsNav };

function At({ entry }: { readonly entry: string }): JSX.Element {
  return (
    <MemoryRouter initialEntries={[entry]}>
      <SettingsNav />
    </MemoryRouter>
  );
}

/** Appearance open: aria-current on its link; sections not built yet disabled with their reason. */
export const Default = { render: () => <At entry="/settings/appearance" /> };

/** Two sections on one route: the hash picks Security. */
export const SecurityHash = { render: () => <At entry="/settings/profile#security" /> };

/** A route that is no section (R-205): no item is current. */
export const NoCurrentSection = { render: () => <At entry="/settings/windows" /> };
