/**
 * The CMP-091 panel-level boundary (E10-S04 #306, slice 6): a crashing panel is replaced by the
 * fallback while the rest of the workspace keeps running (`14` SCR-156). A class, because React has no
 * hook for error boundaries. Reload panel re-mounts the child under a new key; three crashes of one
 * `id` within two minutes stop it (`crashGuard.ts`).
 */
import { Component, Fragment, type ReactNode } from "react";
import { CrashFallback } from "./CrashFallback";
import { recordCrash, type CrashRecord } from "./crashGuard";

export interface PanelErrorBoundaryProps {
  /** Stable per panel: the crash log's component and the repeated-crash ring's key. */
  readonly id: string;
  readonly children: ReactNode;
  /** Reload app; `window.location.reload` by default (tests pass a spy). */
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
    this.setState({ crash: recordCrash(error, "panel", this.props.id) });
  }

  // The Reload panel button unmounts with the fallback, so focus drops to the body after a reload
  // (#267's CMP-091 / the panel host decides where it goes; nothing here moves it).
  private readonly reload = (): void => {
    this.setState((s) => ({ failed: false, crash: null, generation: s.generation + 1 }));
  };

  override render(): ReactNode {
    const { failed, crash, generation } = this.state;
    return (
      <>
        {failed ? null : <Fragment key={generation}>{this.props.children}</Fragment>}
        {/* CRASH_REGION: pre-rendered empty; the fallback is announced into it */}
        <div role="alert">
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
