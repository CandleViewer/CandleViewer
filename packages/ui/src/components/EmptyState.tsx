import type { JSX, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Button } from "./Button.js";
import { ErrorState } from "./ErrorState.js";
import { Link } from "./Link.js";
import { Heading, type HeadingLevel } from "./Typography.js";

export type EmptyStateVariant =
  "no-data" | "recording-not-started" | "backfill-in-progress" | "filtered-empty" | "error";

export interface EmptyStateCta {
  label: string;
  onClick: () => void;
}

export interface EmptyStateLink {
  label: string;
  href: string;
}

interface EmptyStateBase {
  /** A registered glyph replacing the variant's (decorative, `size="lg"`). */
  icon?: IconName;
  /** The fact, as a heading at `headingLevel`. Under `variant="error"` it is CMP-027's title. */
  title: string;
  /**
   * The sentence under it. The sentence form (E09-D09 §8): when the sole CTA is gated, omit `cta` and put the
   * host's reason here; no button renders. Under `variant="error"` it is CMP-027's message; without it the
   * title becomes the message and no heading renders, even when `headingLevel` is set.
   */
  description?: string;
  /** The one primary action, a CMP-001 `primary`; under `variant="error"` it is CMP-027's `retry`. */
  cta?: EmptyStateCta;
  /**
   * The heading's level; default 3, so it fits its panel's outline. `variant="error"` without a description
   * renders no heading, even when `headingLevel` is set.
   */
  headingLevel?: HeadingLevel;
}

/** The empty variants: one secondary link, and the host's progress under backfill. */
export interface EmptyStateEmptyProps extends EmptyStateBase {
  /** Default `no-data`. */
  variant?: Exclude<EmptyStateVariant, "error">;
  /** One secondary CMP-021 link after the CTA. */
  link?: EmptyStateLink;
  /** Backfill only: the host's CMP-023 ProgressBar, or CMP-038 when the total is unknown. */
  progress?: ReactNode;
}

/** `variant="error"` renders CMP-027's panel form, polite (E05-D02 H13): CMP-027 has no link and no progress. */
export interface EmptyStateErrorProps extends EmptyStateBase {
  variant: "error";
  link?: never;
  progress?: never;
}

export type EmptyStateProps = EmptyStateEmptyProps | EmptyStateErrorProps;

/** Each variant's decorative glyph. `filtered-empty` is the registry's `search`: nothing matched the query. */
const VARIANT_GLYPH: Readonly<Record<Exclude<EmptyStateVariant, "error">, IconName>> = {
  "no-data": "info",
  "recording-not-started": "pending",
  "backfill-in-progress": "pending",
  "filtered-empty": "search",
};

/**
 * CMP-026 EmptyState: a designed empty or zero-data block, static and centred in its region. It is no live
 * region: when a filter empties a table, the host's region says so once. `variant="error"` renders CMP-027's
 * panel with `live="polite"` (an in-panel load failure is met where the user looks, H13 / H14 / H37).
 */
export function EmptyState({
  variant = "no-data",
  icon,
  title,
  description,
  cta,
  link,
  headingLevel = 3,
  progress,
}: EmptyStateProps): JSX.Element {
  if (variant === "error") {
    return (
      <ErrorState
        form="panel"
        live="polite"
        headingLevel={headingLevel}
        {...(description === undefined ? { message: title } : { title, message: description })}
        {...(cta === undefined ? {} : { retry: cta })}
      />
    );
  }
  return (
    <div className="cv-empty-state" data-cmp="CMP-026" data-variant={variant}>
      <span className="cv-empty-state__glyph">
        <Icon name={icon ?? VARIANT_GLYPH[variant]} size="lg" />
      </span>
      <Heading level={headingLevel} variant="heading-sm" className="cv-empty-state__title">
        {title}
      </Heading>
      {description === undefined ? null : (
        <p className="cv-empty-state__description">{description}</p>
      )}
      {variant !== "backfill-in-progress" || progress === undefined ? null : (
        <div className="cv-empty-state__progress">{progress}</div>
      )}
      {cta === undefined && link === undefined ? null : (
        <div className="cv-empty-state__actions">
          {cta === undefined ? null : (
            <Button variant="primary" onClick={() => cta.onClick()}>
              {cta.label}
            </Button>
          )}
          {link === undefined ? null : <Link href={link.href}>{link.label}</Link>}
        </div>
      )}
    </div>
  );
}
