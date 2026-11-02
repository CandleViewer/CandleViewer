import type { JSX } from "react";
import { Link, useLocation } from "react-router";
import { currentSectionId } from "./sections";
import { SettingsNavView, type SettingsNavLinkProps } from "./SettingsNavView";

export { currentSectionId };

function RouterLink(props: SettingsNavLinkProps): JSX.Element {
  return <Link {...props} />;
}

/** CMP-086 nav half at the router: the open section comes from the location, links are the router's. */
export function SettingsNav(): JSX.Element {
  const { pathname, hash } = useLocation();
  return <SettingsNavView current={currentSectionId(pathname, hash)} LinkComponent={RouterLink} />;
}
