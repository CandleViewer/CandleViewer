/**
 * The mount's words (E15-S03 #476 PR-1): each is the E15-D16 deck's string (v1.1 at `a83c1e0901`,
 * `docs/design/E15/E15-D16-copy.json`) by its key, or PROPOSED to its owner where the deck has
 * none. Names and symbols are user content, only ever interpolated into text nodes.
 */
import { formatRbacReason } from "@candleviewer/ui";

const panels = (n: number): string => `${n} ${n === 1 ? "panel" : "panels"}`;

export const mountCopy = {
  opening: "Opening your workspace…", // D15:321 SR-27, SCR-150's stage
  listFailed: "Couldn't load workspaces.", // D05:536 rail.error
  openFailed: "Couldn't open this workspace.", // PROPOSED (D12): getWorkspace failed, not 404
  layoutRefused: "This layout couldn't be opened.", // PROPOSED (D12): fromLayout refused it
  retry: "Try again", // D05:536; D08:736
  /** PROPOSED (D12): the heading CMP-026 requires over the 403 sentence. */
  forbiddenTitle: "Workspaces unavailable",
  /** A 403: E09-D09's T2 sentence form, `rbac.permission` with §3.2's verb for `workspaces:read`. */
  forbidden: formatRbacReason("rbac.permission", { verb: "see workspaces" }),
  /** PROPOSED (D12): a 429 and its wait, in symbol search's words (`symbol-search/copy.ts`). */
  rateLimited: (s: number | null): string =>
    `Too many requests — try again ${s === null ? "shortly" : `in ${String(s)} s`}.`,
  invalid: "This workspace can't be opened as saved.", // PROPOSED (D12): a 422, not retried
  noWorkspaces: "No workspaces yet — create one", // D05:535 (its action is CMP-073's, PR-3)
  noLayout: "No layout yet — start from a preset or blank canvas", // D03:653 (S01's gallery)
  noPanels: "This workspace has no panels", // D03:651
  loading: (name: string, n: number): string => `Loading ${name}, ${panels(n)}.`, // D03:650
  /** RD:231 CP-22; the failure clause's plural ("2 panels couldn't load: …") is PROPOSED. */
  ready: (name: string, total: number, failed: readonly string[]): string =>
    failed.length === 0
      ? `Workspace ready: ${name}, ${panels(total)}.`
      : `Workspace ready: ${total - failed.length} of ${panels(total)}. ` +
        `${panels(failed.length)} couldn't load: ${failed.join("; ")}.`,
  /** RD:230 CP-21 (= D03:674) and its two actions. */
  delisted: (symbol: string): string => `${symbol} is no longer listed. This panel can't load it.`,
  changeSymbol: "Change symbol…",
  closePanel: "Close panel",
  unknownKind: "This panel type isn't supported in this version.", // D03:676
  unknownLabel: "Panel", // PROPOSED: the kind word of a kind this version does not know
  /** PROPOSED (SR-E15-15): D07 K-13's "Only the owner can add this panel." with A-10's verb. */
  ownerOnly: "Only the owner can open this panel.",
  /** The ticket's a11y note: "Chart, BTCUSDT 1 minute, loading". */
  paneLoading: (region: string): string => `${region}, loading`,
} as const;
