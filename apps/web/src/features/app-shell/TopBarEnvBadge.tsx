import type { CSSProperties, JSX } from "react";
import { Icon } from "@candleviewer/ui";
import type { Environment } from "../../shell/bootstrap/store.js";

export type BadgeEnvironment = Environment | "unknown";

/**
 * Per value: word, name word, dot (a text stand-in for `icon/env-demo` / `env-live`; `null` = the
 * warning icon), border token, weight. E10-D02 ruling 2 / E10-D03 §1.2: word, weight, dot and a 2 px
 * env-token border, so word, glyph and weight carry it in greyscale. TESTNET and ENV UNKNOWN have no
 * merged treatment (PROPOSED); unknown is a dashed warning border, never a defaulted DEMO.
 */
type Look = readonly [string, string, string | null, string, string];
const LOOK: Record<BadgeEnvironment, Look> = {
  demo: ["DEMO", "Demo", "○", "env-demo", "medium"],
  live: ["LIVE", "Live", "●", "env-live", "bold"],
  testnet: ["TESTNET", "Testnet", "◇", "border-strong", "medium"],
  unknown: ["ENV UNKNOWN", "unknown", null, "status-warning-default", "bold"],
};

/**
 * Whether `unknown` renders its ENV UNKNOWN pill (#304 plan, S2) or nothing (E10-D03 §1.2 / §3.5: "no
 * badge is shown rather than a default one"). Pending the coordinator's ruling; either way it is
 * never a defaulted DEMO.
 */
export const SHOW_UNKNOWN_ENV = true;

/** The look for `env`, or `null` when nothing renders (only `unknown`, when not shown). */
export function badgeLook(env: BadgeEnvironment, showUnknown = SHOW_UNKNOWN_ENV): Look | null {
  return env === "unknown" && !showUnknown ? null : LOOK[env];
}

const PILL: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "var(--space-1)",
  height: "var(--size-icon-lg)",
  padding: "0 var(--space-2)",
  borderRadius: "var(--radius-pill)",
  background: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  fontSize: "var(--font-size-sm)",
  whiteSpace: "nowrap",
};

/** The accessible name, "Trading environment: Live" (E10-D03 §10.2). */
export const envBadgeName = (env: BadgeEnvironment): string =>
  `Trading environment: ${LOOK[env][1]}`;

/**
 * The TopBar's environment badge (#304 S2). Deviation: merged E10-D02 :67 and E10-D03 :78 / :344
 * place CMP-074 EnvBanner, `role="status"`, here; this renders CMP-075's read-only contract instead
 * (plan gap 6: no switch flow), `role="img"` with a static name, because a status region would be
 * read again beside the route-change announcement the shell makes (a double announcement). S4's
 * StatusBar badge is a separate component. It takes no prop, class or style that could hide it:
 * the environment is its only input, and every shown value renders a visible word.
 */
export function TopBarEnvBadge({ env }: { readonly env: BadgeEnvironment }): JSX.Element | null {
  const look = badgeLook(env);
  if (look === null) return null;
  const [word, , dot, border, weight] = look;
  return (
    <span
      role="img"
      aria-label={envBadgeName(env)}
      data-cmp="CMP-075"
      data-env={env}
      style={{
        ...PILL,
        border: `calc(var(--border-thick) * 1px) ${env === "unknown" ? "dashed" : "solid"} var(--color-${border})`,
        fontWeight: `var(--font-weight-${weight})`,
      }}
    >
      {dot === null ? (
        <Icon name="warning" size="sm" />
      ) : (
        <span style={{ color: `var(--color-${border})` }}>{dot}</span>
      )}
      <span>{word}</span>
    </span>
  );
}
