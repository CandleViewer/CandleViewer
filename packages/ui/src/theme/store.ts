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
/** A change-event handler that keeps changing the theme is cut off after this many events and reported. */
const MAX_ANNOUNCED = 100;

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
  /**
   * `false` skips the storage write (state that came from elsewhere, e.g. the server). The next
   * persisting `apply` writes it, even when that call changes nothing, so a user confirming a
   * hydrated value is not reverted by a reload.
   */
  readonly persist?: boolean;
  /** `false` skips the analytics callback (a change the user did not make). */
  readonly track?: boolean;
}

export interface ThemeStore {
  getSnapshot(): ThemeSnapshot;
  /**
   * Every call registers independently (the same function twice runs twice); each disposer removes
   * only its own and is final: a listener removed by an earlier one in the same dispatch is not called.
   */
  subscribe(listener: () => void): () => void;
  /**
   * Writes the root attributes and follows OS media changes until the returned disposer runs. It fires
   * the change event if the OS preference changed since the store was created.
   */
  connect(): () => void;
  /**
   * Applies several preferences as ONE change (one write, one notification, one event). An invalid
   * value is ignored: that field keeps its current preference.
   */
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

/**
 * Untrusted values in, valid preferences out. An invalid leaf takes its value from `fallback`: the
 * defaults for stored preferences, the current preferences for `apply`, so a malformed patch never
 * drops a setting the user already made (an accessibility one, say).
 */
function sanitize(
  input: unknown,
  fallback: ThemePreferences = DEFAULT_PREFERENCES,
): ThemePreferences {
  const o = (typeof input === "object" && input !== null ? input : {}) as Record<string, unknown>;
  const d = fallback;
  const flag = (value: unknown, otherwise: boolean): boolean =>
    typeof value === "boolean" ? value : otherwise;
  return {
    baseTheme: pick(["dark", "light"] as const, o["baseTheme"], d.baseTheme),
    matchSystem: flag(o["matchSystem"], d.matchSystem),
    highContrast: flag(o["highContrast"], d.highContrast),
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
  let unpersisted = false; // a `persist: false` change that storage has not seen yet

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
  const report = (p: ThemeSnapshot, n: ThemeSnapshot): void => {
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
   * the nested change up once the current handlers are done, so nested changes coalesce). A handler
   * that never stops changing the theme is cut off after `MAX_ANNOUNCED` events and reported.
   */
  const announce = (): void => {
    if (announcing) return;
    announcing = true;
    try {
      for (let sent = 0; ; sent += 1) {
        const next = detailOf(snapshot);
        if (sameDetail(announced, next)) break;
        if (sent === MAX_ANNOUNCED) {
          queueMicrotask(() => {
            throw new Error(
              `${THEME_CHANGE_EVENT} handlers kept changing the theme (cut off after ${MAX_ANNOUNCED} events)`,
            );
          });
          break;
        }
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
      if (!entries.has(entry)) continue; // removed by an earlier subscriber: its disposer is final
      try {
        entry.run();
      } catch (error) {
        queueMicrotask(() => {
          throw error;
        });
      }
    }
  };

  /** Writes the preferences to storage; from then on storage and memory agree. */
  const save = (p: ThemePreferences): void => {
    attempt(() => storage?.setItem(THEME_STORAGE_KEY, JSON.stringify(p)), undefined);
    unpersisted = false;
  };

  /** The single mutation path: write once, announce the engine event once, notify once. */
  const commit = (next: ThemePreferences, effects: { persist: boolean; track: boolean }): void => {
    const prev = snapshot;
    const resolved = resolve(next, os);
    if (sameSnapshot(prev, resolved)) {
      // A user confirming a value that hydration already set must still reach storage, or a reload reverts it.
      if (effects.persist && unpersisted) save(next);
      return;
    }
    const changedPreferences = next !== prefs; // an OS-driven commit passes the current object
    prefs = next;
    snapshot = resolved;
    writeRoot(resolved);
    if (effects.persist) save(next);
    else if (changedPreferences) unpersisted = true;
    if (effects.track) report(prev, resolved);
    announce();
    notify();
  };
  const syncOs = (): void => {
    os = readOs();
    commit(prefs, { persist: false, track: false });
  };
  const apply = (
    patch: Partial<ThemePreferences>,
    { persist = true, track = true }: ApplyOptions = {},
  ): void => commit(sanitize({ ...prefs, ...patch }, prefs), { persist, track });

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

interface SharedEntry {
  readonly store: ThemeStore;
  readonly options: ThemeStoreOptions;
}

let shared = new WeakMap<HTMLElement, SharedEntry>();

/** Options a later caller passed that the existing store of the root does not honour (the first caller's win). */
const ignoredOptions = (first: ThemeStoreOptions, later: ThemeStoreOptions): string[] =>
  (["storage", "matchMedia", "onAnalytics"] as const).filter(
    (key) => later[key] !== undefined && later[key] !== first[key],
  );

/**
 * One store per root element: providers, stories and the app bootstrap that ask for the same root
 * get the same store, so they agree instead of clobbering each other's attributes and storage.
 * The first caller's `options` create it and stay in effect; a development build warns when a later
 * caller passes a different `storage`, `matchMedia` or `onAnalytics`. Without a DOM nothing is shared
 * (a fresh inert store per call), so server rendering never leaks state between requests.
 */
export function sharedThemeStore(options: ThemeStoreOptions = {}): ThemeStore {
  const root = options.root ?? defaultRoot();
  if (root === undefined) return createThemeStore(options);
  const known = shared.get(root);
  if (known !== undefined) {
    const ignored = ignoredOptions(known.options, options);
    if (ignored.length > 0 && import.meta.env?.DEV) {
      console.warn(
        `sharedThemeStore: this root already has a store, so the first caller's ${ignored.join(" and ")} stay in effect`,
      );
    }
    return known.store;
  }
  const store = createThemeStore({ ...options, root });
  shared.set(root, { store, options });
  return store;
}

/** Test-only: forgets every shared store (the stores themselves keep working) so tests do not leak state into each other. */
export function resetSharedThemeStores(): void {
  shared = new WeakMap();
}
