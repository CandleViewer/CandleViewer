import { useState, type JSX, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { Button } from "./Button.js";
import { ErrorState, type ErrorStateLive } from "./ErrorState.js";
import { Link } from "./Link.js";
import { Heading, type HeadingLevel } from "./Typography.js";

export type EmptyStateVariant =
  "no-data" | "recording-not-started" | "backfill-in-progress" | "filtered-empty" | "error";

export interface EmptyStateCta {
  label: string;
  onClick: () => void;
}

/** One action of the row (E08-D05 A-D05-5): a CMP-001 button. */
export interface EmptyStateAction extends EmptyStateCta {
  /** Default `primary` for the first action and `secondary` for the second (B03 draws a list region's both secondary). */
  variant?: "primary" | "secondary";
  /**
   * T2 as CMP-079 hands it (E09-D09 §2.2, rendering 2a): CMP-001's own T2 (focusable, `aria-disabled`, described by
   * its reason node, the CMP-019 `lock`), with this reason as a line under it; a press changes nothing and says it
   * again. A sole action that is gated is the sentence form instead (E09-D09 §8): no `actions`, the reason as the
   * `description`.
   */
  disabledReason?: string;
}

/** One action or two, in order. */
export type EmptyStateActions =
  readonly [EmptyStateAction] | readonly [EmptyStateAction, EmptyStateAction];

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
  /**
   * @deprecated Pass `actions: [cta]` (E08-D05 A-D05-5); ignored when `actions` is given. The one primary action, a
   * CMP-001 `primary`; under `variant="error"` it is CMP-027's `retry`.
   */
  cta?: EmptyStateCta;
  /** One or two actions after the words (E08-D05 A-D05-5: Clear search and Check again; Retry now and Refresh). */
  actions?: EmptyStateActions;
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
  /** One secondary CMP-021 link after the actions. */
  link?: EmptyStateLink;
  /** Backfill only: the host's CMP-023 ProgressBar, or CMP-038 when the total is unknown. */
  progress?: ReactNode;
  live?: never;
  reference?: never;
}

/** `variant="error"` renders CMP-027's panel form, polite (E05-D02 H13): CMP-027 has no link and no progress. */
export interface EmptyStateErrorProps extends EmptyStateBase {
  variant: "error";
  link?: never;
  progress?: never;
  /** Default `polite` (E05-D02 H13); `assertive` is `role="alert"`, once (E08-D05 A-D05-5, SCR-102's load failure). */
  live?: ErrorStateLive;
  /** A problem's `instance`: a selectable "Ref …" line after the actions, outside the live region (E08-D05 §6.2). */
  reference?: string;
}

export type EmptyStateProps = EmptyStateEmptyProps | EmptyStateErrorProps;

/** Each variant's decorative glyph. `filtered-empty` is the registry's `search`: nothing matched the query. */
const VARIANT_GLYPH: Readonly<Record<Exclude<EmptyStateVariant, "error">, IconName>> = {
  "no-data": "info",
  "recording-not-started": "pending",
  "backfill-in-progress": "pending",
  "filtered-empty": "search",
};

/** Whitespace is no reason, as CMP-001 reads it. */
const reasonOf = (action: EmptyStateAction): string | undefined =>
  action.disabledReason?.trim() || undefined;

/**
 * CMP-026 EmptyState: a designed empty or zero-data block, static and centred in its region. It is no live
 * region: when a filter empties a table, the host's region says so once (a press on a T2 action is said by its own
 * polite region, rendered while an action is gated). `variant="error"` renders CMP-027's panel, polite by default
 * (an in-panel load failure is met where the user looks, H13 / H14 / H37); with `actions` or `reference` that panel
 * holds the glyph and the words, and this block the actions and the Ref line.
 */
export function EmptyState({
  variant = "no-data",
  icon,
  title,
  description,
  cta,
  actions,
  link,
  headingLevel = 3,
  progress,
  live = "polite",
  reference,
}: EmptyStateProps): JSX.Element {
  // The count re-keys the node, so every press on a T2 action is said again.
  const [recall, setRecall] = useState({ text: "", n: 0 });
  const words = description === undefined ? { message: title } : { title, message: description };
  if (variant === "error" && actions === undefined && reference === undefined) {
    return (
      <ErrorState
        form="panel"
        live={live}
        headingLevel={headingLevel}
        {...words}
        {...(cta === undefined ? {} : { retry: cta })}
      />
    );
  }
  // The deprecated `cta` keeps its as-built look: CMP-027's secondary Retry on an error, else the primary CTA.
  const legacy: readonly EmptyStateAction[] =
    cta === undefined ? [] : [{ ...cta, variant: variant === "error" ? "secondary" : "primary" }];
  const list = actions ?? legacy;
  const more = variant === "error" ? undefined : link; // CMP-027 has no link
  const gated = list.some((action) => reasonOf(action) !== undefined);
  // A lifted gate forgets its words, so a gate that returns mounts its region empty.
  if (!gated && recall.n !== 0) setRecall({ text: "", n: 0 });
  const say = (text: string) => (): void => setRecall((prev) => ({ text, n: prev.n + 1 }));
  const row =
    list.length === 0 && more === undefined ? null : (
      <div className="cv-empty-state__actions" data-gated={gated ? "" : undefined}>
        {list.map((action, index) => {
          const reason = reasonOf(action);
          // One wrapper whatever the gate: a gate coming or going never re-parents the button (it keeps focus).
          return (
            <span key={action.label} className="cv-empty-state__action">
              <Button
                variant={action.variant ?? (index === 0 ? "primary" : "secondary")}
                {...(reason === undefined
                  ? {}
                  : { disabledReason: reason, onClickCapture: say(reason) })}
                onClick={() => action.onClick()}
              >
                {action.label}
              </Button>
              {reason === undefined ? null : (
                <span className="cv-empty-state__reason" aria-hidden="true">
                  {reason}
                </span>
              )}
            </span>
          );
        })}
        {more === undefined ? null : <Link href={more.href}>{more.label}</Link>}
      </div>
    );
  const said = gated ? (
    <span className="cv-visually-hidden" role="status">
      {recall.n === 0 ? null : <span key={recall.n}>{recall.text}</span>}
    </span>
  ) : null;
  if (variant === "error") {
    return (
      <div className="cv-empty-state" data-cmp="CMP-026" data-variant={variant}>
        <ErrorState form="panel" live={live} headingLevel={headingLevel} {...words} />
        {row}
        {reference === undefined ? null : <p className="cv-empty-state__ref">Ref {reference}</p>}
        {said}
      </div>
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
      {row}
      {said}
    </div>
  );
}
