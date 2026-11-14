// E24-S07 (#782) slice 2: the recorded layer's switch (D03 S54-57 `zones-b-alone`): CMP-004, off by default, no
// acknowledgement (exact data, BQ 1 / BQ 8). Access (BQ 10, ruled 6624627875; D03 D-7): `persisted` saves
// `deriv.liq_by_price`; `session` is a Viewer's T1, held for the session; `view-as` is T2 `rbac.view_as` in CMP-079's
// notice form (G-T2.1a–c, G-T2.5): full label, native role, `aria-disabled`, focusable, described by the panel's one
// notice; `Enter` / `Space` change nothing and re-announce it (G-T2.3). The server still enforces (C-12.4).
// Not mounted yet: the row goes beside S06's liquidation controls once #5768 merges (BQ 11).
import type { JSX } from "react";
import { RbacGate, Toggle } from "@candleviewer/ui";
import type { ByPriceAnalytics } from "./analytics";
import * as copy from "./copy";
import type { ToggleAccess } from "./model";

export interface RecordedByPriceToggleProps {
  readonly symbol: string;
  readonly checked: boolean;
  readonly access: ToggleAccess;
  /** The host saves (`persisted`) or keeps it for the session (`session`); never called under view-as. */
  readonly onChange: (checked: boolean, scope: "persisted" | "session") => void;
  readonly analytics?: ByPriceAnalytics | undefined;
}

export function RecordedByPriceToggle(p: RecordedByPriceToggleProps): JSX.Element {
  const { access } = p;
  const toggle = (
    <Toggle
      label={copy.TOGGLE_LABEL}
      checked={p.checked}
      density="compact"
      onChange={(next) => {
        if (access.kind === "view-as") return;
        p.analytics?.toggled(p.symbol, next, access.kind);
        p.onChange(next, access.kind);
      }}
    />
  );
  // one gate in both states, so a context that starts or ends never remounts the switch
  return access.kind === "view-as" ? (
    <RbacGate
      form="notice"
      noticeId={access.noticeId}
      allowed={false}
      reason="rbac.view_as"
      fills={{ user: access.user }}
    >
      {toggle}
    </RbacGate>
  ) : (
    <RbacGate form="notice" noticeId="" allowed>
      {toggle}
    </RbacGate>
  );
}
