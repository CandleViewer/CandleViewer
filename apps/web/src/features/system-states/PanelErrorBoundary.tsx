/**
 * The CMP-091 panel-level boundary (E10-S04 #306, slice 6): a crashing panel is replaced by the
 * fallback while the rest of the workspace keeps running (`14` SCR-156). A class, because React has no
 * hook for error boundaries. Reload panel re-mounts the child under a new key; three crashes of one
 * `id` within two minutes stop it (`crashGuard.ts`).
 */
import { Component, Fragment, type ReactNode } from "react";
import { CrashFallback } from "./CrashFallback";
import { defaultCrashGuard, recordCrash, type CrashGuard, type CrashRecord } from "./crashGuard";

export interface PanelErrorBoundaryProps {
  /** Stable per panel: the crash log's component and the repeated-crash ring's key. */
  readonly id: string;
  readonly children: ReactNode;
  readonly guard?: CrashGuard | undefined;
  readonly onReloadApp?: (() => void) | undefined;
}

interface State {
  readonly failed: boolean;
  readonly crash: CrashRecord | null;
  readonly generation: number;
}

export class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, State> {
  override state: State = { failed: false, crash: null, generation: 0 };

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true };
  }

  override componentDidCatch(error: unknown): void {
    const { id, guard = defaultCrashGuard } = this.props;
    this.setState({ crash: recordCrash(error, "panel", id, guard) });
  }

  private readonly reload = (): void => {
    this.setState((s) => ({ failed: false, crash: null, generation: s.generation + 1 }));
  };

  override render(): ReactNode {
    const { failed, crash, generation } = this.state;
    return (
      <>
        {failed ? null : <Fragment key={generation}>{this.props.children}</Fragment>}
        {/* pre-rendered empty, so the fallback's arrival is announced (PROPOSED: polite) */}
        <div aria-live="polite">
          {crash === null ? null : (
            <CrashFallback
              scope="panel"
              crash={crash}
              onReload={this.reload}
              onReloadApp={this.props.onReloadApp}
            />
          )}
        </div>
      </>
    );
  }
}
