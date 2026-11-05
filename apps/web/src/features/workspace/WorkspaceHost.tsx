/**
 * SCR-020's host (E15-S03 #476 PR-1): one `getWorkspace`, the layout read through `fromLayout`
 * (#5411's trust boundary) and mounted in DockGrid. The frame paints first, with named headers and
 * skeletons; each pane fills in on its own (US-LAY-002; E15-D12 §8). The restore says "Loading
 * {name}, n panels." and, once every visible pane settles, RD:231's "Workspace ready: …". It opens
 * the last-used layout, else the default, else the first. A refusal or an unanswered read is its
 * own state (`Refusal`), never a stuck "Opening…". Saving is PR-2's (BQ-05).
 */
import { close, counterMinter, fromLayout, isDockError, leavesOf } from "@candleviewer/dock";
import type { DockNode, DockTree, PaneFields } from "@candleviewer/dock";
import { EmptyState } from "@candleviewer/ui";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type JSX } from "react";
import { useShellSelector } from "../../shell/useShellSelector";
import * as search from "../symbol-search/searchSession";
import {
  getWorkspace,
  type ApiFailure,
  type ApiResult,
  type WorkspaceDetail,
} from "./api/workspacesApi";
import { DockGrid, heirOf } from "./dock/DockGrid";
import { createDockStore, useDockTree, type DockStore } from "./dock/dockStore";
import { layoutSummary } from "./dock/layoutSummary";
import { createDefaultPaneRegistry, type PaneRegistry } from "./dock/paneRegistry";
import { mountCopy } from "./mount/copy";
import { MountContext, mountRegistry, roleGate, type PaneOutcome } from "./mount/mountRegistry";
import { regionName, spellInterval } from "./mount/paneName";
import { createSymbolStatus, type SymbolStatus } from "./mount/symbolStatus";
import { readLastUsed, sessionUserId, writeLastUsed } from "./current/resolveTarget";
import "./workspace.css";
import { opening, Refusal } from "./routes/states";

export interface HostDeps {
  readonly get: (id: string, signal: AbortSignal) => Promise<ApiResult<WorkspaceDetail>>;
  readonly registry: PaneRegistry;
  readonly symbols: () => SymbolStatus;
  readonly now: () => number;
  /** Analytics: closed sets and counts only, never a symbol or a name (`D02`:681). */
  readonly report: (detail: Readonly<Record<string, unknown>>) => void;
  readonly ownerOnlyKinds?: ReadonlySet<string>;
}

/** The app's analytics seam (`cv:analytics` on `window`), the name every screen reports on. */
const ANALYTICS_SEAM = "cv:analytics";

const defaultDeps = (): HostDeps => ({
  get: getWorkspace,
  registry: createDefaultPaneRegistry(),
  symbols: () => createSymbolStatus(),
  now: () => performance.now(),
  report: (detail) => window.dispatchEvent(new CustomEvent(ANALYTICS_SEAM, { detail })),
});

type OpenView = { name: string; store: DockStore; panes: ReadonlyMap<string, PaneFields> };

type Phase =
  | { readonly kind: "loading" | "no_layout" }
  | { readonly kind: "failed"; readonly failure: ApiFailure | null; readonly message: string }
  | { readonly kind: "open"; readonly view: OpenView };

/** The panes drawn when the restore starts: the maximised one, else lone leaves and active tabs. */
function visiblePanes(tree: DockTree): string[] {
  if (tree.maximised !== null) return [tree.maximised];
  const walk = (node: DockNode): string[] =>
    node.type === "leaf"
      ? [node.paneId]
      : node.type === "tabset"
        ? node.children.slice(node.active, node.active + 1).map((l) => l.paneId)
        : node.children.flatMap(walk);
  return tree.root === null ? [] : walk(tree.root);
}

function open(detail: WorkspaceDetail, workspaceId: string, registry: PaneRegistry): Phase {
  const userId = sessionUserId();
  const last = userId === null ? null : readLastUsed(userId);
  const remembered = last?.workspaceId === workspaceId ? last.layoutId : null;
  const { layouts } = detail;
  const layout =
    layouts.find((l) => l.id === remembered) ?? layouts.find((l) => l.is_default) ?? layouts[0];
  if (layout === undefined) return { kind: "no_layout" };
  const mint = counterMinter("ws-");
  try {
    const { minimums } = mountRegistry(registry, () => null);
    const { tree, panes } = fromLayout(layout, { mint, minimums });
    if (userId !== null) writeLastUsed(userId, { workspaceId, layoutId: layout.id });
    return {
      kind: "open",
      view: { name: detail.name, store: createDockStore({ tree, mint }), panes },
    };
  } catch (error) {
    if (!isDockError(error)) throw error;
    return { kind: "failed", failure: null, message: mountCopy.layoutRefused };
  }
}

export function WorkspaceHost(props: { workspaceId: string; deps?: HostDeps }): JSX.Element {
  const { workspaceId } = props;
  const deps = useMemo(() => props.deps ?? defaultDeps(), [props.deps]);
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setPhase({ kind: "loading" });
    const failed = (failure: ApiFailure): Phase => ({
      kind: "failed",
      failure,
      message: mountCopy.openFailed,
    });
    // Every answer, a rejection included, leaves `loading`; each refusal keeps its own state.
    const settle = (next: () => Phase): void => void (abort.signal.aborted || setPhase(next()));
    void deps
      .get(workspaceId, abort.signal)
      .then((a) =>
        settle(() => (a.ok ? open(a.value, workspaceId, deps.registry) : failed(a.failure))),
      )
      .catch(() => settle(() => failed({ kind: "network" })));
    return () => abort.abort();
  }, [workspaceId, attempt, deps]);

  if (phase.kind === "open") return <OpenWorkspace view={phase.view} deps={deps} />;
  if (phase.kind === "no_layout") return <EmptyState title={mountCopy.noLayout} />;
  if (phase.kind !== "failed") return opening;
  const retry = (): void => setAttempt((n) => n + 1);
  return <Refusal failure={phase.failure} message={phase.message} onRetry={retry} />;
}

function OpenWorkspace({ view, deps }: { view: OpenView; deps: HostDeps }): JSX.Element {
  const tree = useDockTree(view.store);
  const environment = useShellSelector((s) => s.environment);
  const role = useShellSelector((s) => s.me?.role ?? null);
  const { ownerOnlyKinds } = deps;
  const registry = useMemo(
    () => mountRegistry(deps.registry, roleGate(role, ownerOnlyKinds)),
    [deps.registry, ownerOnlyKinds, role],
  );
  const hasIndex = search.useSymbolSearch((s) => s.index !== null);
  const symbols = useMemo(() => deps.symbols(), [deps]);
  useEffect(() => () => symbols.stop(), [symbols]);
  useEffect(() => () => search.setSymbolOpener(null), []);
  const [panes, setPanes] = useState(view.panes);
  const root = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState(() => mountCopy.loading(view.name, view.panes.size));

  const kindOf = (id: string): string =>
    [...leavesOf(tree.root), ...tree.minimised].find((l) => l.paneId === id)?.kind ?? "";
  const label = (id: string): string => registry.get(kindOf(id))?.label ?? "";
  const nameOf = (id: string): string =>
    regionName(kindOf(id), label(id), panes.get(id), environment);

  // The restore clock: the dock frame's first paint to every visible pane settled (D12 §8).
  const restore = useRef<{ start: number; expected: string[]; done: boolean } | null>(null);
  const settled = useRef(new Map<string, PaneOutcome>());
  const finish = (): void => {
    const r = restore.current;
    const expected = r?.expected.filter((id) => kindOf(id) !== "") ?? []; // a closed pane: none
    if (r === null || r.done || !expected.every((id) => settled.current.has(id))) return;
    r.done = true;
    const failed = expected.filter((id) => settled.current.get(id) !== "ready");
    for (const id of failed) {
      deps.report({ name: "workspace.pane_error", reason: settled.current.get(id) });
    }
    const [ms, paneCount] = [Math.round(deps.now() - r.start), expected.length];
    deps.report({ name: "workspace.restore_completed", ms, paneCount, failedPanes: failed.length });
    const names = failed.map((id) => [label(id), panes.get(id)?.symbol].filter(Boolean).join(", "));
    setMessage(mountCopy.ready(view.name, paneCount, names));
  };
  // Effects and pane callbacks read the latest render's closures.
  const latest = useRef({ finish, label, panes });
  latest.current = { finish, label, panes };
  useEffect(() => latest.current.finish(), [tree]);

  useLayoutEffect(() => {
    if (restore.current !== null) return; // one restore per mount
    const shown = visiblePanes(view.store.getTree());
    const kinds = new Map(leavesOf(view.store.getTree().root).map((l) => [l.paneId, l.kind]));
    // A role-gated pane never mounts, so there is nothing to wait for.
    const expected = shown.filter((id) => !registry.get(kinds.get(id) ?? "")?.disabledReason);
    restore.current = { start: deps.now(), expected, done: false };
    latest.current.finish();
  }, [view.store, registry, deps]);

  const rebind = (paneId: string): void => {
    const fields = latest.current.panes.get(paneId);
    const [symbol, interval] = [fields?.symbol ?? "", fields?.interval_code ?? ""];
    const pane = latest.current.label(paneId);
    const target = { pane, symbol, interval, intervalWords: spellInterval(interval), armed: false };
    search.setSymbolOpener({
      target,
      open: (symbol) => {
        search.setSymbolOpener(null);
        setPanes((was) => {
          const now = was.get(paneId);
          return now === undefined ? was : new Map(was).set(paneId, { ...now, symbol });
        });
      },
    });
    search.openSymbolSearch();
  };

  const ctx = {
    fields: (paneId: string) => panes.get(paneId),
    regionName: nameOf,
    symbols,
    onSettled: (paneId: string, outcome: PaneOutcome) => {
      settled.current.set(paneId, outcome);
      latest.current.finish();
    },
    onRebind: hasIndex ? rebind : null,
    onClose: (paneId: string) => {
      const summary = layoutSummary.closed(latest.current.label(paneId));
      const heir = heirOf(view.store.getTree().root, paneId); // FM-11, as DockGrid's own close
      view.store.apply("close", (t, c) => close(t, paneId, c), summary);
      const to = heir === null ? ".cv-dock-root" : `[data-pane-id="${heir}"] .cv-dockpanel`;
      root.current?.querySelector<HTMLElement>(to)?.focus();
    },
  };

  return (
    <div ref={root} className="cv-workspace">
      <h1 className="cv-visually-hidden">{view.name}</h1>
      <p className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {message}
      </p>
      {tree.root === null ? <EmptyState title={mountCopy.noPanels} /> : null}
      <MountContext.Provider value={ctx}>
        <DockGrid
          store={view.store}
          registry={registry}
          paneName={(leaf) => nameOf(leaf.paneId)}
          onAnnounce={setMessage}
        />
      </MountContext.Provider>
    </div>
  );
}
