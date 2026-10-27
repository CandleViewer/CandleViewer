import { useId, type JSX } from "react";
import { PlainLink, type RenderLink } from "./internal/linkSlot.js";

export interface TryRoute {
  readonly label: string;
  readonly href: string;
}

export interface NotFoundStateProps {
  /** The attempted route, echoed as plain text (never a link). */
  path?: string;
  /** The session's permitted top-level routes (D09 §6); empty, no "Try:" line. */
  tryRoutes: readonly TryRoute[];
  /** `deleted`: the distinct copy for a deleted object (`14` SCR-155). */
  variant?: "unknown" | "deleted";
  /** The deleted object's noun, for `variant="deleted"`; default "workspace". */
  deletedObject?: string;
  /** The host's router link; a plain anchor by default. */
  renderLink?: RenderLink;
}

/**
 * CMP-090 NotFoundState (SCR-155): D09's T3 hard-404 and any unknown route, with identical copy for
 * both. No glyph: the CMP-019 `search` glyph is not in the icon registry yet. `document.title` is
 * the host's.
 */
export function NotFoundState({
  path,
  tryRoutes,
  variant = "unknown",
  deletedObject = "workspace",
  renderLink = PlainLink,
}: NotFoundStateProps): JSX.Element {
  const tryId = useId();
  let sentence: JSX.Element;
  if (variant === "deleted") {
    // PROPOSED: `14` SCR-155 names "this workspace was deleted"; the sentence form is ours.
    sentence = <>This {deletedObject} was deleted.</>;
  } else if (path === undefined) {
    // PROPOSED: the sentence without a route to echo.
    sentence = <>There&apos;s nothing here.</>;
  } else {
    sentence = (
      <>
        There&apos;s nothing at <span className="cv-appstate__route">{path}</span>.
      </>
    );
  }
  return (
    <div className="cv-appstate" data-cmp="CMP-090" data-variant={variant}>
      <h1 className="cv-appstate__heading" tabIndex={-1}>
        Page not found
      </h1>
      <p className="cv-appstate__body">{sentence}</p>
      {tryRoutes.length === 0 ? null : (
        <div className="cv-appstate__try">
          <span id={tryId} className="cv-appstate__body">
            Try:
          </span>
          <ul className="cv-appstate__list" aria-labelledby={tryId}>
            {tryRoutes.map((route, index) => (
              <li key={route.href}>
                {index === 0 ? null : (
                  <span className="cv-appstate__sep" aria-hidden="true">
                    ·
                  </span>
                )}
                {renderLink({
                  href: route.href,
                  className: "cv-appstate__link",
                  children: route.label,
                })}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
