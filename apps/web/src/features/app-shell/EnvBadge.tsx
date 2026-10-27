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
 * CMP-075 EnvBadgeLocal (#304 S2): read-only, `role="img"` with a static name so a re-render is
 * never re-announced (`15` CMP-075). It takes no prop, class or style that could hide it: the
 * environment is its only input, and every value renders a visible word.
 */
export function EnvBadge({ env }: { readonly env: BadgeEnvironment }): JSX.Element {
  const [word, , dot, border, weight] = LOOK[env];
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
