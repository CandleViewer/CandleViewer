import { useEffect, useState, type JSX } from "react";
import { Button } from "./Button.js";
import { Spinner } from "./Spinner.js";

/** The slow path starts this long after the wait begins (CMP-038, `16-design-system-brief.md` §7). */
export const SLOW_AFTER_MS = 5_000;

/** The waits that may offer a Cancel: a load, an export or a replay (E05-D02 §6 H29). */
export type CancellableWait = "load" | "export" | "replay";

interface WaitBase {
  /** The waiting words, e.g. "Loading positions"; announced once when the wait begins. */
  label: string;
  /** Replaces `label` after 5 s, announced once, e.g. "Still loading… the server is slow to answer". */
  slowLabel?: string;
}

/** A load, an export or a replay: `onCancel` offers a ghost CMP-001 Cancel from the slow path on. */
interface CancellableProps extends WaitBase {
  kind: CancellableWait;
  onCancel?: () => void;
  /** Default "Cancel". */
  cancelLabel?: string;
}

/**
 * Any other wait (`wait`, the default: a save, a slow boot) or a `submit`, which never offers Cancel: a submit's
 * retries reuse its `orderLinkId` and the OMS reconciles it (C-2.10). An order submit's own slow path is its
 * button's (`submit.awaiting`, CMP-107), never this component's.
 */
interface NonCancellableProps extends WaitBase {
  kind?: "wait" | "submit";
  onCancel?: never;
  cancelLabel?: never;
}

export type InlineSpinnerTextProps = CancellableProps | NonCancellableProps;

const CANCELLABLE: ReadonlySet<string> = new Set<CancellableWait>(["load", "export", "replay"]);

/**
 * CMP-038 InlineSpinnerText: a nested CMP-014 `sm` plus the words, inside one polite `role="status"` mounted
 * empty and filled after mount; the label is announced once and the slow text once, with no time cap and no
 * elapsed counter. Completion is the host's: it unmounts this when the wait ends. Cancel sits outside the
 * region, after the text in the Tab order, and never takes focus.
 */
export function InlineSpinnerText(props: InlineSpinnerTextProps): JSX.Element {
  const { label, slowLabel, kind = "wait" } = props;
  const [mounted, setMounted] = useState(false);
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    setMounted(true);
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  // Enforced at run time as well as in the types, for JavaScript and spread callers.
  const cancel =
    props.onCancel !== undefined && CANCELLABLE.has(kind) && slow ? props.onCancel : undefined;
  const text = slow && slowLabel !== undefined ? slowLabel : label;
  return (
    <span
      className="cv-inline-spinner-text"
      data-cmp="CMP-038"
      data-kind={kind}
      data-phase={slow ? "slow" : "waiting"}
    >
      <span
        className="cv-inline-spinner-text__status"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <Spinner size="sm" />
        <span className="cv-inline-spinner-text__label">{mounted ? text : null}</span>
      </span>
      {cancel === undefined ? null : (
        <Button variant="ghost" size="sm" onClick={() => cancel()}>
          {props.cancelLabel ?? "Cancel"}
        </Button>
      )}
    </span>
  );
}
