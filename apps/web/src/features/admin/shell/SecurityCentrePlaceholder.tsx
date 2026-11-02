import type { JSX } from "react";
import { Card, Link, PageHeader } from "@candleviewer/ui";
import { ScreenRoot } from "../../app-shell/ScreenRoot";
import { routerLink } from "../routerLink";

/**
 * R-354 `/admin/security` until E43-S02 mounts SCR-137 here (E42-S01, Out of scope): the ticket's
 * placeholder card, its title through CMP-088 PageHeader, its R4 line and a link to the audit log (R-360's name, `12` §2).
 */
export function SecurityCentrePlaceholder(): JSX.Element {
  return (
    <ScreenRoot>
      <PageHeader title="Security centre" />
      <Card>
        <p>Security posture checks ship in R4 (E43)</p>
        <Link to="/admin/audit" as={routerLink}>
          Audit log
        </Link>
      </Card>
    </ScreenRoot>
  );
}
