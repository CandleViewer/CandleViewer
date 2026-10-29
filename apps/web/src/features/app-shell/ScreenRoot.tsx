import { createContext, useContext, type CSSProperties, type JSX, type ReactNode } from "react";

const InShell = createContext(false);

/** Marks its subtree as rendered inside the shell's one `main` (E10-S01 S1). */
export function InShellProvider({ children }: { readonly children: ReactNode }): JSX.Element {
  return <InShell.Provider value={true}>{children}</InShell.Provider>;
}

/**
 * Root element of a screen that renders both inside the shell and outside it (stubs, error
 * states): a plain `div` inside the shell, whose `main` already holds it, and its own `main`
 * on public and error routes, so every page has exactly one `main`.
 */
export function ScreenRoot({
  children,
  style,
}: {
  readonly children: ReactNode;
  /** A page that is its own frame (R-902) paints its surface here; the shell paints its own. */
  readonly style?: CSSProperties;
}): JSX.Element {
  return useContext(InShell) ? (
    <div style={style}>{children}</div>
  ) : (
    <main style={style}>{children}</main>
  );
}
