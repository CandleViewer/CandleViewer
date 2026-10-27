import type { CSSProperties, JSX, ReactNode } from "react";
import { Button } from "@candleviewer/ui";
import type { generated } from "@candleviewer/protocol";
import { EnvBadge, type BadgeEnvironment } from "./EnvBadge";

type RoleName = generated.rest.components["schemas"]["RoleName"];

export interface TopBarProps {
  readonly env: BadgeEnvironment;
  /** `/me`'s name and role; `null` before `/me` answers (no name is guessed). */
  readonly user: { readonly name: string; readonly role: RoleName } | null;
  readonly connection: ReactNode;
  readonly searchHint: string; // "Ctrl+K"
  /** Opens the command palette; absent while no palette is registered (E10-S03). */
  readonly onSearch?: () => void;
  readonly onSignOut: () => void;
  readonly signingOut: boolean;
  readonly signOutFailed: boolean;
}

/** PROPOSED copy: no merged text names these placeholders' reasons. */
export const PICKER_REASON = "Not available in this build.";
export const SEARCH_REASON = "The command palette is not available in this build.";
export const SIGN_OUT_FAILED = "Couldn't reach the server. Try again."; // SCR-005's sign-out failure line

const ROW: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-2)",
  padding: "var(--space-2) var(--space-inset-sm)",
  borderBottom: "calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
};
const NOTE = { color: "var(--color-text-secondary)", fontSize: "var(--font-size-sm)" } as const;
const KBD: CSSProperties = {
  padding: "0 var(--space-1)",
  border: "calc(var(--border-hairline) * 1px) solid var(--color-border-strong)",
  borderRadius: "var(--radius-xs)",
  fontFamily: "var(--font-family-mono)",
};

const roleWord = (role: RoleName): string => role.charAt(0).toUpperCase() + role.slice(1);

/**
 * CMP-072 TopBar, first row (#304 S2; E10-D02 SCR-010, E10-D03 §2.1), props only. DOM order is the
 * focus order: wordmark, env badge, pickers, search trigger, connection chip, name and role, Sign out.
 * Stand-ins until their atoms land: T2 picker placeholders (CMP-105/219/220), a plain `<kbd>`
 * (CMP-022), name and role as text plus Sign out (CMP-061). Visible reason lines are `aria-hidden`:
 * each control carries its reason as its description. Deferred: CMP-073, CMP-211 (S7), CMP-210 (S4).
 */
export function TopBar(props: TopBarProps): JSX.Element {
  const { user, onSearch, signingOut } = props;
  const pickers = ["Account", "Symbol", "Interval"].map((label) => (
    <Button key={label} size="sm" iconRight="chevron-down" disabledReason={PICKER_REASON}>
      {label}
    </Button>
  ));
  return (
    <div style={ROW} data-cmp="CMP-072">
      <span style={{ fontWeight: "var(--font-weight-semibold)", fontSize: "var(--font-size-md)" }}>
        CandleViewer
      </span>
      <EnvBadge env={props.env} />
      {pickers}
      <span aria-hidden style={NOTE}>{`Pickers: ${PICKER_REASON.toLowerCase()}`}</span>
      <Button
        variant="ghost"
        size="sm"
        aria-keyshortcuts={props.searchHint.replace("Ctrl", "Control")}
        {...(onSearch === undefined ? { disabledReason: SEARCH_REASON } : { onClick: onSearch })}
        data-cmp="CMP-084"
      >
        Search commands <kbd style={KBD}>{props.searchHint}</kbd>
      </Button>
      <span aria-hidden style={NOTE}>
        {onSearch === undefined ? SEARCH_REASON : null}
      </span>
      {props.connection}
      <span style={{ marginLeft: "auto" }}>
        {user === null ? null : `${user.name} · ${roleWord(user.role)}`}
      </span>
      <Button variant="ghost" size="sm" loading={signingOut} onClick={props.onSignOut}>
        Sign out
      </Button>
      {props.signOutFailed ? <span style={NOTE}>{SIGN_OUT_FAILED}</span> : null}
    </div>
  );
}
