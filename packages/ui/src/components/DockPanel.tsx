import type { FocusEvent, JSX, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { cx } from "./internal/cx.js";

export interface DockPanelProps {
  /** The region name: kind, symbol and the spelled interval (E15-D03 D-5). */
  title: string;
  /** Drawn focused: the inset frame and the header bar, never a change of the content box. */
  focused?: boolean;
  state?: "loading" | "compact" | "error" | "maximised";
  /** The CMP-082 header row. */
  header?: ReactNode;
  children?: ReactNode;
  onFocus?: (event: FocusEvent<HTMLElement>) => void;
  className?: string;
}

/**
 * CMP-080: the panel every docked view mounts in, a `role="region"` named by `title`. Focus is
 * painted inside the box (the `border.panel.focus` frame), so focusing a panel never resizes the
 * WebGL canvas it holds; `aria-busy` while its body loads. A named `section` is the region.
 */
export function DockPanel({
  title,
  focused = false,
  state,
  header,
  children,
  onFocus,
  className,
}: DockPanelProps): JSX.Element {
  return (
    <section
      aria-label={title}
      aria-busy={state === "loading" ? true : undefined}
      className={cx("cv-dockpanel", className)}
      data-cmp="CMP-080"
      data-focused={focused ? "" : undefined}
      data-state={state}
      // A programmatic focus target only (the dock moves focus here when a pane closes, FM-11).
      tabIndex={-1}
      onFocus={onFocus}
    >
      {header}
      <div className="cv-dockpanel__body">{children}</div>
    </section>
  );
}

export interface PanelHeaderProps {
  /** The kind word ("Chart"): the handle is "Move {kind}". */
  kind: string;
  /** The visible heading; the region's name is the panel's. */
  title: string;
  /** `h2` in the dock, `h3` inside a tab group. */
  level?: 2 | 3;
  /** The panel's own actions, a `role="toolbar"`. */
  actions?: ReactNode;
  /** The handle: the only move origin (its keyboard path is E15-S02's move mode). */
  onMove?: () => void;
  onClose?: () => void;
  className?: string;
}

/** CMP-082: the one header row of a DockPanel: handle, heading, own actions and close. */
export function PanelHeader({
  kind,
  title,
  level = 2,
  actions,
  onMove,
  onClose,
  className,
}: PanelHeaderProps): JSX.Element {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div className={cx("cv-panelheader", className)} data-cmp="CMP-082">
      {onMove === undefined ? null : (
        <button
          type="button"
          className="cv-control cv-panelheader__button"
          aria-label={`Move ${kind}`}
          onClick={onMove}
        >
          <Icon name="drag-handle" />
        </button>
      )}
      <Heading className="cv-panelheader__title">{title}</Heading>
      {actions === undefined ? null : (
        <div role="toolbar" aria-label={`${kind} actions`} className="cv-panelheader__actions">
          {actions}
        </div>
      )}
      {onClose === undefined ? null : (
        <button
          type="button"
          className="cv-control cv-panelheader__button"
          aria-label={`Close ${kind}`}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      )}
    </div>
  );
}
