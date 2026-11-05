/**
 * The mount's registry (E15-S03 #476): #5411's registry as a restored layout sees it. An unknown
 * kind (C-6.3) is a first-class error pane (D03:676); an owner-only kind is re-checked at mount and
 * never mounts for another role (SR-E15-15, LY-E03; presentation only); every other panel mounts
 * once its symbol resolves, a delisted one showing CP-21. Wrappers are made once per kind, so a
 * panel's component never changes and never remounts.
 */
import type { PaneFields } from "@candleviewer/dock";
import { ErrorState, Skeleton } from "@candleviewer/ui";
import { createContext, useContext, useEffect, useSyncExternalStore } from "react";
import type { ComponentType, JSX } from "react";
import type { PaneEntry, PaneProps, PaneRegistry } from "../dock/paneRegistry";
import { mountCopy } from "./copy";
import type { SymbolStatus } from "./symbolStatus";

/** How a pane settled at restore: loaded (or nothing to load), or its error state. */
export type PaneOutcome = "ready" | "delisted" | "unknown_kind";

export interface MountContextValue {
  readonly fields: (paneId: string) => PaneFields | undefined;
  readonly regionName: (paneId: string) => string;
  readonly symbols: SymbolStatus;
  readonly onSettled: (paneId: string, outcome: PaneOutcome) => void;
  /** Null when no symbol search can open in this window (SCR-102 needs an index). */
  readonly onRebind: ((paneId: string) => void) | null;
  readonly onClose: (paneId: string) => void;
}

export const MountContext = createContext<MountContextValue | null>(null);

function useMount(): MountContextValue {
  const ctx = useContext(MountContext);
  if (ctx === null) throw new Error("a mounted pane renders inside its workspace's MountContext");
  return ctx;
}

/** The dock's smallest drawn minimum (tape's, E15-D04 D04-D-5). */
const UNKNOWN_MINIMUMS = { minWidth: 232, minHeight: 120 } as const;

function UnknownKindPane({ paneId }: PaneProps): JSX.Element {
  const ctx = useMount();
  useEffect(() => ctx.onSettled(paneId, "unknown_kind"), [ctx, paneId]);
  const action = { label: mountCopy.closePanel, onClick: () => ctx.onClose(paneId) };
  return <ErrorState live="off" message={mountCopy.unknownKind} action={action} />;
}

const UNKNOWN_ENTRY: PaneEntry = {
  label: mountCopy.unknownLabel,
  component: UnknownKindPane,
  ...UNKNOWN_MINIMUMS,
};

function resolved(kind: string, Inner: ComponentType<PaneProps>): ComponentType<PaneProps> {
  function ResolvedPane(props: PaneProps): JSX.Element {
    const { paneId } = props;
    const ctx = useMount();
    const symbol = ctx.fields(paneId)?.symbol ?? null;
    const { symbols } = ctx;
    useEffect(() => {
      if (symbol !== null) symbols.check(symbol);
    }, [symbols, symbol]);
    const read = (): string => (symbol === null ? "none" : symbols.get(symbol));
    const state = useSyncExternalStore(symbols.subscribe, read);
    useEffect(() => {
      if (state !== "checking") ctx.onSettled(paneId, state === "delisted" ? "delisted" : "ready");
    }, [ctx, paneId, state]);
    if (state === "checking") {
      const name = mountCopy.paneLoading(ctx.regionName(paneId));
      return (
        <div role="group" aria-busy="true" aria-label={name}>
          <Skeleton shape={kind === "chart" ? "chart" : "row"} />
        </div>
      );
    }
    if (state !== "delisted" || symbol === null) return <Inner {...props} />;
    const { onRebind } = ctx;
    const close = { label: mountCopy.closePanel, onClick: () => ctx.onClose(paneId) };
    const rebind = onRebind && { label: mountCopy.changeSymbol, onClick: () => onRebind(paneId) };
    return (
      <ErrorState
        live="off"
        message={mountCopy.delisted(symbol)}
        {...(rebind === null ? {} : { retry: rebind })}
        action={close}
      />
    );
  }
  ResolvedPane.displayName = `Resolved(${kind})`;
  return ResolvedPane;
}

/** `gate(kind)`: the reason the session's role may not open the kind, or null. */
export function mountRegistry(
  base: PaneRegistry,
  gate: (kind: string) => string | null,
): PaneRegistry {
  const wrapped = new Map<string, PaneEntry>();
  return {
    register: (kind, entry) => {
      wrapped.delete(kind);
      base.register(kind, entry);
    },
    get(kind) {
      const entry = base.get(kind);
      if (entry === undefined) return UNKNOWN_ENTRY;
      const reason = gate(kind);
      if (reason !== null) return { ...entry, disabledReason: reason };
      const out = wrapped.get(kind) ?? { ...entry, component: resolved(kind, entry.component) };
      wrapped.set(kind, out);
      return out;
    },
    minimums: (kind) => base.minimums(kind) ?? UNKNOWN_MINIMUMS,
  };
}

/**
 * SR-E15-15: the kinds only the Owner may open. None in R1 (E15-D07 C-12), so the set is empty;
 * the restore test holds the rule with an illustrative one.
 */
export const OWNER_ONLY_KINDS: ReadonlySet<string> = new Set();

export const roleGate =
  (role: string | null, ownerOnly: ReadonlySet<string> = OWNER_ONLY_KINDS) =>
  (kind: string): string | null =>
    ownerOnly.has(kind) && role !== "owner" ? mountCopy.ownerOnly : null;
