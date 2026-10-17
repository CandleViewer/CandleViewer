/**
 * Theme, density and reduced-motion runtime store (E05-T02, docs/plan/16-design-system-brief.md §4).
 *
 * Framework-free and ref-backed: React reads it through `useSyncExternalStore` (ThemeProvider), so a
 * switch re-renders only components that subscribe to the changed value. Everything else is a CSS
 * custom-property swap keyed on the root attributes written here (never a React-owned wrapper).
 */

export const THEMES = ["dark", "light", "high-contrast"] as const;
export const DENSITIES = ["compact", "comfortable"] as const;
export const TEXT_SCALES = [100, 112, 125, 150] as const;
export const MOTION_OVERRIDES = ["system", "on", "off"] as const;

export type ThemeName = (typeof THEMES)[number];
export type DensityName = (typeof DENSITIES)[number];
export type TextScale = (typeof TEXT_SCALES)[number];
/** In-app reduced-motion override: "system" follows the OS, "on"/"off" win over it. */
export type MotionOverride = (typeof MOTION_OVERRIDES)[number];
export type MotionName = "safe" | "reduce";

export const THEME_CHANGE_EVENT = "candleviewer:themechange";
export const THEME_STORAGE_KEY = "cv.theme.v1";
/** Artefact key of the engine colour uniforms (`build/engine/theme-uniforms.json`) named by the event. */
export const THEME_UNIFORMS_KEY = "theme-uniforms";

const DARK_QUERY = "(prefers-color-scheme: dark)";
const REDUCE_QUERY = "(prefers-reduced-motion: reduce)";

/** What the user chose (persisted). High contrast is an overlay so toggling it never loses the base theme. */
export interface ThemePreferences {
  readonly baseTheme: "dark" | "light";
  readonly matchSystem: boolean;
  readonly highContrast: boolean;
  readonly density: DensityName;
  readonly motionOverride: MotionOverride;
  readonly textScale: TextScale;
}

/** Preferences plus the resolved values written to the root attributes. */
export interface ThemeSnapshot extends ThemePreferences {
  readonly theme: ThemeName;
  readonly motion: MotionName;
}

/** `detail` of the `candleviewer:themechange` CustomEvent dispatched on `document`. */
export interface ThemeChangeDetail {
  readonly theme: ThemeName;
  readonly density: DensityName;
  readonly motion: MotionName;
  readonly themeUniforms: typeof THEME_UNIFORMS_KEY;
}

export type ThemeAnalyticsEvent =
  | { name: "appearance.theme_changed"; theme: ThemeName; matchSystem: boolean }
  | { name: "appearance.density_changed"; density: DensityName }
  | {
      name: "a11y.preference_changed";
      key: "reduced_motion" | "high_contrast" | "text_scale";
      value: string;
    };

export interface ThemeStoreOptions {
  /**
   * Element carrying the root attributes. Defaults to `document.documentElement`; without a DOM (SSR,
   * Node) the store is inert: state and subscriptions work, nothing is written or dispatched.
   */
  readonly root?: HTMLElement;
  /** Defaults to `window.localStorage` (persistence is skipped when it is unavailable). */
  readonly storage?: Pick<Storage, "getItem" | "setItem">;
  readonly matchMedia?: (query: string) => MediaQueryList;
  /** Injectable analytics sink; no-op by default so the package stays app-agnostic. */
  readonly onAnalytics?: (event: ThemeAnalyticsEvent) => void;
}

/** What `apply` does besides updating the state; the defaults are those of a user action. */
export interface ApplyOptions {
  /** `false` skips the storage write (state that came from elsewhere, e.g. the server). */
  readonly persist?: boolean;
  /** `true` skips the analytics callback (a change the user did not make). */
  readonly silent?: boolean;
}

export interface ThemeStore {
  getSnapshot(): ThemeSnapshot;
  /** Every call registers independently (the same function twice runs twice); each disposer removes only its own. */
  subscribe(listener: () => void): () => void;
  /**
   * Writes the root attributes and follows OS media changes until the returned disposer runs. It fires
   * the change event if the OS preference changed since the store was created.
   */
  connect(): () => void;
  /** Applies several preferences as ONE change (one write, one notification, one event); invalid values fall back to their defaults. */
  apply(patch: Partial<ThemePreferences>, options?: ApplyOptions): void;
  /** `high-contrast` turns the overlay on; `dark`/`light` pick that theme and leave match-system and HC. */
  setTheme(theme: ThemeName): void;
  /** Returns the new state of the high-contrast overlay. */
  toggleHighContrast(): boolean;
  setDensity(density: DensityName): void;
  setMotionOverride(override: MotionOverride): void;
  setTextScale(scale: TextScale): void;
}

export const DEFAULT_PREFERENCES: ThemePreferences = {
  baseTheme: "dark",
  matchSystem: false,
  highContrast: false,
  density: "compact",
  motionOverride: "system",
  textScale: 100,
};

const pick = <T>(allowed: readonly T[], value: unknown, fallback: T): T =>
  allowed.includes(value as T) ? (value as T) : fallback;

/** Storage and analytics must never break a theme switch. */
function attempt<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

/** Untrusted values in (storage, `apply`), valid preferences out: any invalid leaf falls back to its default. */
function sanitize(input: unknown): ThemePreferences {
  const o = (typeof input === "object" && input !== null ? input : {}) as Record<string, unknown>;
  const d = DEFAULT_PREFERENCES;
  return {
    baseTheme: pick(["dark", "light"] as const, o["baseTheme"], d.baseTheme),
    matchSystem: o["matchSystem"] === true,
    highContrast: o["highContrast"] === true,
    density: pick(DENSITIES, o["density"], d.density),
    motionOverride: pick(MOTION_OVERRIDES, o["motionOverride"], d.motionOverride),
    textScale: pick(TEXT_SCALES, o["textScale"], d.textScale),
  };
}

/** Untrusted storage in, valid preferences out. */
export function parsePreferences(raw: string | null | undefined): ThemePreferences {
  return sanitize(attempt<unknown>(() => JSON.parse(raw ?? "null"), null));
}

interface Os {
  readonly dark: boolean;
  readonly reduceMotion: boolean;
}

function resolve(p: ThemePreferences, os: Os): ThemeSnapshot {
  const system = os.dark ? "dark" : "light";
  const theme = p.highContrast ? "high-contrast" : p.matchSystem ? system : p.baseTheme;
  const reduce = p.motionOverride === "system" ? os.reduceMotion : p.motionOverride === "on";
  return { ...p, theme, motion: reduce ? "reduce" : "safe" };
}

const sameSnapshot = (a: ThemeSnapshot, b: ThemeSnapshot): boolean =>
  (Object.keys(a) as (keyof ThemeSnapshot)[]).every((k) => a[k] === b[k]);

const detailOf = ({ theme, density, motion }: ThemeSnapshot): ThemeChangeDetail => ({
  theme,
  density,
  motion,
  themeUniforms: THEME_UNIFORMS_KEY,
});

const sameDetail = (a: ThemeChangeDetail, b: ThemeChangeDetail): boolean =>
  a.theme === b.theme && a.density === b.density && a.motion === b.motion;

/** Guarded like storage and `matchMedia`: there is no `document` in SSR or Node. */
const defaultRoot = (): HTMLElement | undefined =>
  typeof document === "undefined" ? undefined : document.documentElement;

export function createThemeStore(options: ThemeStoreOptions = {}): ThemeStore {
  const root = options.root ?? defaultRoot();
  const storage = options.storage ?? attempt(() => window.localStorage, undefined);
  const mm =
    options.matchMedia ??
    (typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia.bind(window)
      : undefined);
  const entries = new Set<{ readonly run: () => void }>();
  const readOs = (): Os => ({
    dark: mm?.(DARK_QUERY).matches ?? true,
    reduceMotion: mm?.(REDUCE_QUERY).matches ?? false,
  });

  let os = readOs();
  let prefs = parsePreferences(attempt(() => storage?.getItem(THEME_STORAGE_KEY), null));
  let snapshot = resolve(prefs, os);
  let announced = detailOf(snapshot);
  let announcing = false;

  const writeRoot = (s: ThemeSnapshot): void => {
    if (root === undefined) return;
    const values = {
      theme: s.theme,
      density: s.density,
      motion: s.motion,
      "text-scale": s.textScale,
    };
    for (const [name, value] of Object.entries(values)) {
      if (root.getAttribute(`data-${name}`) !== String(value))
        root.setAttribute(`data-${name}`, String(value));
    }
  };
  const track = (p: ThemeSnapshot, n: ThemeSnapshot): void => {
    const emit = (event: ThemeAnalyticsEvent): void =>
      attempt(() => options.onAnalytics?.(event), undefined);
    const a11y = (key: "reduced_motion" | "high_contrast" | "text_scale", value: string): void =>
      emit({ name: "a11y.preference_changed", key, value });
    const { baseTheme, matchSystem, highContrast } = n;
    if (
      p.baseTheme !== baseTheme ||
      p.matchSystem !== matchSystem ||
      p.highContrast !== highContrast
    ) {
      emit({ name: "appearance.theme_changed", theme: n.theme, matchSystem });
    }
    if (p.density !== n.density) emit({ name: "appearance.density_changed", density: n.density });
    if (p.highContrast !== highContrast) a11y("high_contrast", highContrast ? "on" : "off");
    if (p.motionOverride !== n.motionOverride) a11y("reduced_motion", n.motionOverride);
    if (p.textScale !== n.textScale) a11y("text_scale", String(n.textScale));
  };

  /**
   * Dispatches the live state against the last announced one, so events stay oldest first with the
   * last one matching the final state even when a handler re-enters `apply` (the running loop picks
   * the nested change up once the current handlers are done).
   */
  const announce = (): void => {
    if (announcing) return;
    announcing = true;
    try {
      for (;;) {
        const next = detailOf(snapshot);
        if (sameDetail(announced, next)) break;
        announced = next;
        root?.ownerDocument.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: next }));
      }
    } finally {
      announcing = false;
    }
  };
  /** Walks a copy so subscribers may (un)subscribe; a throwing one is rethrown later and skips nobody. */
  const notify = (): void => {
    for (const entry of [...entries]) {
      try {
        entry.run();
      } catch (error) {
        queueMicrotask(() => {
          throw error;
        });
      }
    }
  };

  /** The single mutation path: write once, announce the engine event once, notify once. */
  const commit = (next: ThemePreferences, effects: { persist: boolean; track: boolean }): void => {
    const prev = snapshot;
    const resolved = resolve(next, os);
    if (sameSnapshot(prev, resolved)) return;
    prefs = next;
    snapshot = resolved;
    writeRoot(resolved);
    if (effects.persist) {
      attempt(() => storage?.setItem(THEME_STORAGE_KEY, JSON.stringify(next)), undefined);
    }
    if (effects.track) track(prev, resolved);
    announce();
    notify();
  };
  const syncOs = (): void => {
    os = readOs();
    commit(prefs, { persist: false, track: false });
  };
  const apply = (
    patch: Partial<ThemePreferences>,
    { persist = true, silent = false }: ApplyOptions = {},
  ): void => commit(sanitize({ ...prefs, ...patch }), { persist, track: !silent });

  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      const entry = { run: listener };
      entries.add(entry);
      return () => void entries.delete(entry);
    },
    connect: () => {
      const queries = mm ? [mm(DARK_QUERY), mm(REDUCE_QUERY)] : [];
      queries.forEach((q) => q.addEventListener("change", syncOs));
      syncOs();
      writeRoot(snapshot);
      return () => queries.forEach((q) => q.removeEventListener("change", syncOs));
    },
    apply,
    setTheme: (theme) =>
      apply(
        theme === "high-contrast"
          ? { highContrast: true }
          : { baseTheme: theme, matchSystem: false, highContrast: false },
      ),
    toggleHighContrast: () => {
      apply({ highContrast: !prefs.highContrast });
      return prefs.highContrast;
    },
    setDensity: (density) => apply({ density }),
    setMotionOverride: (motionOverride) => apply({ motionOverride }),
    setTextScale: (textScale) => apply({ textScale }),
  };
}

const shared = new WeakMap<HTMLElement, ThemeStore>();

/**
 * One store per root element: providers, stories and the app bootstrap that ask for the same root
 * get the same store, so they agree instead of clobbering each other's attributes and storage.
 * The first caller's `options` create it. Without a DOM nothing is shared (a fresh inert store per
 * call), so server rendering never leaks state between requests.
 */
export function sharedThemeStore(options: ThemeStoreOptions = {}): ThemeStore {
  const root = options.root ?? defaultRoot();
  if (root === undefined) return createThemeStore(options);
  let store = shared.get(root);
  if (store === undefined) {
    store = createThemeStore({ ...options, root });
    shared.set(root, store);
  }
  return store;
}
