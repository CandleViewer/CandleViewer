/**
 * E10-Q04 render counter (BQ-Q04-06 B, AC3): the browser twin of `status-bar-isolation.test.tsx`
 * counts shell renders and outlet and status-bar commits in `window.__cvPerfProbe`. It exists only
 * in a build made with `CV_PERF_PROBE=1` (`__CV_PERF_PROBE__`, `vite.config.ts`): in every other
 * build each helper is its argument or a no-op and the counter is dropped as dead code
 * (`perfProbe.bundle.test.ts`; the bench also searches the production `dist/`). The probe build
 * also takes react-dom's profiling build, the only production one that calls `onRender`.
 */
import { Profiler, type ProfilerOnRenderCallback, type ReactNode } from "react";

declare const __CV_PERF_PROBE__: boolean;

function bump(id: string): void {
  const w = window as unknown as Record<string, Record<string, number> | undefined>;
  const counts = (w["__cvPerfProbe"] ??= {});
  counts[id] = (counts[id] ?? 0) + 1;
}

const onCommit: ProfilerOnRenderCallback = (id) => bump(id);

/** `node` inside a commit-counting Profiler in a probe build; `node` itself in any other. */
export function probeCommits(id: string, node: ReactNode): ReactNode {
  return __CV_PERF_PROBE__ ? (
    <Profiler id={id} onRender={onCommit}>
      {node}
    </Profiler>
  ) : (
    node
  );
}

/** Counts one render of the calling component in a probe build (StrictMode doubles it in dev). */
export function probeRender(id: string): void {
  if (__CV_PERF_PROBE__) bump(id);
}
