import { useEffect, useState, type JSX } from "react";
import { Icon } from "../icons/Icon.js";
import { Button } from "./Button.js";
import { PlainLink, type RenderLink } from "./internal/linkSlot.js";

export interface ForbiddenStateProps {
  /** D09 §5.1: `never-had` (nothing changed) or `withdrawn` (the session had it until just now). */
  variant?: "never-had" | "withdrawn";
  /** `permission`: the role lacks a capability; `account`: the account is not assigned (`rbac.account`). */
  scope?: "permission" | "account";
  /**
   * The D09 §3.2 `{verb}` phrase the role lacks, e.g. "see the journal", filling `rbac.permission`
   * ("Your role can't {verb}."). A capability, never data, a route or a screen name.
   */
  capability?: string;
  /** The account id the client's own route or request carried (never a label, never a server id). */
  accountId?: string;
  /** `Problem.instance` of a received 403 body; omitted, no Ref line (never an empty or synthetic id). */
  refId?: string;
  /** "Back to your workspace". */
  homeHref: string;
  /** The host's router link; a plain anchor by default. */
  renderLink?: RenderLink;
  /** Receives the details text; omitted, the text goes to the clipboard. */
  onCopyDetails?: (details: string) => void | Promise<void>;
}

/** PROPOSED: the permission sentence when the host knows no `{verb}` (a role-denied route). */
const NO_VERB = "see this";
const COPIED_MS = 2000;

/** D09 §10 `rbac.*`: the vocabulary sentence, with " any more" before its full stop when withdrawn. */
function reasonSentence(
  scope: "permission" | "account",
  capability: string,
  withdrawn: boolean,
): string {
  const base =
    scope === "account" ? "This account isn't assigned to you" : `Your role can't ${capability}`;
  return withdrawn ? `${base} any more` : `${base}.`;
}

/**
 * CMP-089 ForbiddenState (SCR-154): D09's T4 route landing and the step-3 never-had landing.
 * The `h1` is never "Access denied" (E05-D02 H18). Focus moves to the `h1` through the host's
 * route-focus mechanism; this component moves nothing on its own. `document.title` is the host's.
 */
export function ForbiddenState({
  variant = "never-had",
  scope = "permission",
  capability = NO_VERB,
  accountId,
  refId,
  homeHref,
  renderLink = PlainLink,
  onCopyDetails,
}: ForbiddenStateProps): JSX.Element {
  const withdrawn = variant === "withdrawn";
  const reason = reasonSentence(scope, capability, withdrawn);
  const body = withdrawn
    ? `${reason} — this changed just now. Anything you already sent was decided by the server: check Orders. Ask the owner if this is unexpected.`
    : `${reason} Ask the owner if you need it.`;
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), COPIED_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async (): Promise<void> => {
    // The capability sentence and the Ref when present, nothing else (D09 §5.1 `scr154.copy`).
    const details = [withdrawn ? `${reason}.` : reason, refId && `Ref ${refId}`]
      .filter(Boolean)
      .join("\n");
    try {
      await (onCopyDetails ?? ((text: string) => navigator.clipboard.writeText(text)))(details);
      setCopied(true);
    } catch {
      // A denied clipboard has no state yet (E05-D02 slice 2 E20: the failed state is a follow-up).
    }
  };

  return (
    <div className="cv-appstate" data-cmp="CMP-089" data-variant={variant} data-scope={scope}>
      <span className="cv-appstate__glyph">
        <Icon name="lock" size="lg" />
      </span>
      <h1 className="cv-appstate__heading" tabIndex={-1}>
        {withdrawn ? "Your access changed" : "You don't have access to this"}
      </h1>
      <p className="cv-appstate__body">{body}</p>
      {scope === "account" && accountId !== undefined ? (
        <p className="cv-appstate__echo">{accountId}</p>
      ) : null}
      <div className="cv-appstate__actions">
        {renderLink({
          href: homeHref,
          className: "cv-appstate__link",
          children: "Back to your workspace",
        })}
        <Button
          variant="secondary"
          {...(copied ? { iconLeft: "check" as const } : {})}
          onClick={() => void copy()}
        >
          Copy details
        </Button>
      </div>
      {refId === undefined ? null : <p className="cv-appstate__ref">Ref {refId}</p>}
      <span role="status" className="cv-visually-hidden">
        {copied ? "Copied" : ""}
      </span>
    </div>
  );
}
