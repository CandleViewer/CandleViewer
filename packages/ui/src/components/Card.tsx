import { useId, type JSX, type ReactNode } from "react";

interface CardBase {
  /** Header trailing slot: CMP-001 / CMP-002 actions, `space.inset.xs` apart. An icon-only one names the card. */
  readonly actions?: ReactNode;
  /** `panel` pads the body with `space.panel.padding`; `none` lets a child (a table) run edge to edge. */
  readonly padding?: "panel" | "none";
  /** `elevated` lifts by `elevation.card`; `flat` draws a 1px `border.default` hairline instead (E25-D05). */
  readonly surface?: "elevated" | "flat";
  /** The title's heading level; `0` renders it as plain text, for a card inside a listbox option (J11). */
  readonly headingLevel?: 2 | 3 | 4 | 0;
  readonly children?: ReactNode;
}

/** A plain card: a container with no role of its own; its title, when given, is a heading. */
interface PlainCard extends CardBase {
  readonly title?: ReactNode;
  readonly region?: false;
}

/** A landmark tile (J11): a `region` named by its heading, so it needs a title. */
interface RegionCard extends CardBase {
  readonly title: ReactNode;
  readonly region: true;
}

export type CardProps = PlainCard | RegionCard;

/**
 * CMP-050: a content surface, `color.surface.raised` on `radius.card`. Not interactive and no state of its own:
 * hover, focus, loading and empty are its content's. The header holds the title (wrapping before the actions move)
 * and the actions; DOM order is header, then body. `region` makes a dashboard tile a landmark named by its title.
 */
export function Card({
  title,
  actions,
  padding = "panel",
  surface = "elevated",
  headingLevel = 3,
  region = false,
  children,
}: CardProps): JSX.Element {
  const titleId = useId();
  const hasTitle = title !== undefined && title !== null && title !== false;
  const hasActions = actions !== undefined && actions !== null && actions !== false;
  const isRegion = region && hasTitle;
  const Root = isRegion ? "section" : "div";
  const Title = headingLevel === 0 ? "span" : (`h${headingLevel}` as const);
  return (
    <Root
      className="cv-card"
      data-cmp="CMP-050"
      data-surface={surface}
      data-padding={padding}
      aria-labelledby={isRegion ? titleId : undefined}
    >
      {hasTitle || hasActions ? (
        <div className="cv-card__header">
          {hasTitle ? (
            <Title id={titleId} className="cv-card__title">
              {title}
            </Title>
          ) : null}
          {hasActions ? <div className="cv-card__actions">{actions}</div> : null}
        </div>
      ) : null}
      <div className="cv-card__body">{children}</div>
    </Root>
  );
}
