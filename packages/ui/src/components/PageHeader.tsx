import type { JSX, ReactNode } from "react";

export interface PageHeaderProps {
  /** The page's name: the route's one `h1`. Plain text; the header never puts a control in it. */
  readonly title: ReactNode;
  /** The `h1`'s id, so the host's skip link (CMP-085) can target it. */
  readonly headingId?: string | undefined;
  /**
   * The host's CMP-052 Breadcrumb, above the title. Omitted in the admin area: the CMP-087 band carries
   * the route (E42-D03 Appendix A).
   */
  readonly breadcrumb?: ReactNode;
  /** The page's actions, the primary first: next after the `h1` in DOM and Tab order, at the line's end. */
  readonly actions?: ReactNode;
  /** One plain line under the title, e.g. "All times UTC · as of 14:02:11" (`meta.asof`). Never live. */
  readonly meta?: ReactNode;
  /** A CMP-093 audited-read marker line under the meta, e.g. E42-D04's `audit.marker`. Never live. */
  readonly marker?: ReactNode;
}

const present = (node: ReactNode): boolean => node !== undefined && node !== null && node !== false;

/**
 * CMP-088 PageHeader: a full page's title row, for the admin sub-pages and the other area pages alike
 * (Journal, Rules, Alerts, Replay, Settings). It renders the route's single `h1`, then the actions, then
 * the `meta` and `marker` lines; the actions sit at the end of the title row and span the lines under it
 * (E42-D03 board 09). It has no role, no live region and no state of its own: the actions own their keys.
 */
export function PageHeader({
  title,
  headingId,
  breadcrumb,
  actions,
  meta,
  marker,
}: PageHeaderProps): JSX.Element {
  const hasMeta = present(meta);
  const hasMarker = present(marker);
  // The text lines beside the actions: the CSS spans the actions over exactly these rows.
  const lines = 1 + (hasMeta ? 1 : 0) + (hasMarker ? 1 : 0);
  return (
    <div className="cv-page-header" data-cmp="CMP-088" data-lines={lines}>
      {present(breadcrumb) ? <div className="cv-page-header__breadcrumb">{breadcrumb}</div> : null}
      <h1 id={headingId} className="cv-page-header__title">
        {title}
      </h1>
      {present(actions) ? <div className="cv-page-header__actions">{actions}</div> : null}
      {hasMeta ? <p className="cv-page-header__meta">{meta}</p> : null}
      {hasMarker ? <div className="cv-page-header__marker">{marker}</div> : null}
    </div>
  );
}
