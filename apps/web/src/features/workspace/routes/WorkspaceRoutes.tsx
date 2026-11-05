/**
 * The workspace routes' lazy chunk (E15-S03 #476): `/terminal/:layoutId` resolved and redirected to
 * `/w/:workspaceId` with no query (hand-off §10.1 rule 5: identity only), and `/w/:workspaceId`
 * restored by `WorkspaceHost`.
 */
import { EmptyState } from "@candleviewer/ui";
import { useEffect, useState, type JSX } from "react";
import { useNavigate, useParams } from "react-router";
import { mountCopy } from "../mount/copy";
import * as current from "../current/resolveTarget";
import { WorkspaceHost } from "../WorkspaceHost";
import { opening, Refusal } from "./states";

export function TerminalResolver(): JSX.Element {
  const { layoutId = "last" } = useParams();
  const navigate = useNavigate();
  const [answer, setAnswer] = useState<current.Resolution | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setAnswer(null);
    const userId = current.sessionUserId();
    const last = userId === null ? null : current.readLastUsed(userId);
    current
      .resolveTerminal(layoutId, last, undefined, abort.signal)
      .then((r) => {
        if (abort.signal.aborted) return;
        if (r.kind !== "open") return setAnswer(r);
        if (userId !== null && r.layoutId !== null) current.writeLastUsed(userId, r);
        void navigate(`/w/${r.workspaceId}`, { replace: true });
      })
      .catch(() => {
        // A rejected resolve is the network failure, never a stuck "Opening…" (not when left).
        if (!abort.signal.aborted) setAnswer({ kind: "failed", failure: { kind: "network" } });
      });
    return () => abort.abort();
  }, [layoutId, attempt, navigate]);
  if (answer?.kind === "empty") return <EmptyState title={mountCopy.noWorkspaces} />;
  if (answer?.kind !== "failed") return opening;
  const retry = (): void => setAttempt((n) => n + 1);
  return <Refusal failure={answer.failure} message={mountCopy.listFailed} onRetry={retry} />;
}

export function WorkspaceRoute(): JSX.Element {
  const { workspaceId = "" } = useParams();
  return <WorkspaceHost key={workspaceId} workspaceId={workspaceId} />;
}
