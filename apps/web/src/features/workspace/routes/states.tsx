/**
 * SCR-150's stage word while the workspace opens, said politely (SR-27), and a read's refusal: a
 * 404 is the uniform page; a 403 the T2 sentence alone (E09-D09 §2.2, no button); a 422 has no
 * Try again (the same read answers the same); a 429 shows Try again once its wait has passed.
 */
import { EmptyState, ErrorState } from "@candleviewer/ui";
import { useEffect, useState, type JSX } from "react";
import { NotFoundState } from "../../../routes/ErrorStates";
import type { ApiFailure } from "../api/workspacesApi";
import { mountCopy } from "../mount/copy";

/** The longest wait the button is held for, in seconds. */
export const MAX_WAIT_S = 3_600;

export const opening = (
  <p role="status" aria-live="polite">
    {mountCopy.opening}
  </p>
);

export function Refusal(props: {
  readonly failure: ApiFailure | null; // null: refused on the client (`fromLayout`)
  readonly message: string;
  readonly onRetry: () => void;
}): JSX.Element {
  const { failure } = props;
  // Bounded: a wait past 2^31 ms makes `setTimeout` fire at once.
  const wait =
    failure?.kind === "rate_limited" ? Math.min(failure.retryAfterS ?? 0, MAX_WAIT_S) : 0;
  const [held, setHeld] = useState(wait > 0);
  useEffect(() => {
    if (wait === 0) return;
    const timer = setTimeout(() => setHeld(false), wait * 1_000);
    return () => clearTimeout(timer);
  }, [wait]);
  if (failure?.kind === "not_found") return <NotFoundState />;
  if (failure?.kind === "forbidden") {
    // E09-D09 §8's sentence form: CMP-026 with `cta` omitted and the sentence as `description`.
    return <EmptyState title={mountCopy.forbiddenTitle} description={mountCopy.forbidden} />;
  }
  if (failure?.kind === "invalid") return <ErrorState live="polite" message={mountCopy.invalid} />;
  const message =
    failure?.kind === "rate_limited" ? mountCopy.rateLimited(failure.retryAfterS) : props.message;
  const retry = { label: mountCopy.retry, onClick: props.onRetry };
  return <ErrorState live="polite" message={message} {...(held ? {} : { retry })} />;
}
