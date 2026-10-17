import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
  type JSX,
  type ReactNode,
} from "react";
import { mountLiveRegion } from "./a11y.js";
import {
  createThemeStore,
  type DensityName,
  type TextScale,
  type ThemeName,
  type ThemeSnapshot,
  type ThemeStore,
  type ThemeStoreOptions,
} from "./store.js";

const ThemeContext = createContext<ThemeStore | null>(null);
const useBrowserLayoutEffect = typeof document === "undefined" ? useEffect : useLayoutEffect;

export interface ThemeProviderProps {
  readonly children: ReactNode;
  /** A store shared with non-React code. Otherwise the provider creates one from `options`. */
  readonly store?: ThemeStore;
  readonly options?: ThemeStoreOptions;
}

/**
 * Connects a theme store to `document.documentElement`. It renders no DOM of its own and its context
 * value (the store) never changes, so a switch re-renders only components that read a value.
 * The store is fixed for the provider's lifetime (remount to change it).
 */
export function ThemeProvider({ children, store, options }: ThemeProviderProps): JSX.Element {
  const [active] = useState(() => store ?? createThemeStore(options));
  useBrowserLayoutEffect(() => {
    mountLiveRegion(); // pre-rendered, so the first Ctrl+Shift+H announcement is heard
    return active.connect();
  }, [active]);
  return <ThemeContext.Provider value={active}>{children}</ThemeContext.Provider>;
}

export function useThemeStore(): ThemeStore {
  const store = useContext(ThemeContext);
  if (store === null) throw new Error("useThemeStore requires <ThemeProvider>");
  return store;
}

function useSlice<T>(select: (snapshot: ThemeSnapshot) => T): T {
  const store = useThemeStore();
  const read = (): T => select(store.getSnapshot());
  return useSyncExternalStore(store.subscribe, read, read); // 3rd arg: also safe under renderToString
}

/** Every value, re-rendering on any change (settings screens). Prefer the narrow hooks below. */
export function useThemeSnapshot(): ThemeSnapshot {
  const store = useThemeStore();
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

/** The resolved theme (`data-theme`) and its setter; re-renders only when the theme changes. */
export function useTheme(): readonly [ThemeName, ThemeStore["setTheme"]] {
  return [useSlice((s) => s.theme), useThemeStore().setTheme];
}

export function useDensity(): readonly [DensityName, ThemeStore["setDensity"]] {
  return [useSlice((s) => s.density), useThemeStore().setDensity];
}

/** `true` while motion is reduced (OS preference or in-app override); the setter is the override. */
export function useReducedMotion(): readonly [boolean, ThemeStore["setMotionOverride"]] {
  return [useSlice((s) => s.motion === "reduce"), useThemeStore().setMotionOverride];
}

export function useTextScale(): readonly [TextScale, ThemeStore["setTextScale"]] {
  return [useSlice((s) => s.textScale), useThemeStore().setTextScale];
}
