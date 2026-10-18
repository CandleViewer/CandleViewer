/**
 * The app's one theme store (E05-T02 runtime, wired by #3139). The bootstrap, the preferences
 * feature and `<ThemeProvider>` all resolve to the same store of `document.documentElement`
 * (`sharedThemeStore`), so they agree instead of clobbering each other's root attributes.
 */
import {
  sharedThemeStore,
  type ApplyOptions,
  type ThemeAnalyticsEvent,
  type ThemeStore,
  type ThemeStoreOptions,
} from "@candleviewer/ui";

/**
 * DOM event on `window` that carries the runtime's analytics events (`appearance.theme_changed`,
 * `appearance.density_changed`, `a11y.preference_changed`; `detail` is the event). The app has no
 * analytics transport yet, so this is the seam one can subscribe to, like `cv:audit` in `keymap/audit.ts`.
 * Nothing leaves the page from here.
 */
export const THEME_ANALYTICS_EVENT = "cv:analytics";

function reportThemeAnalytics(event: ThemeAnalyticsEvent): void {
  window.dispatchEvent(
    new CustomEvent<ThemeAnalyticsEvent>(THEME_ANALYTICS_EVENT, { detail: event }),
  );
}

/**
 * The options of the app's store. The first caller creates the store and its options stay in effect, so
 * `<ThemeProvider>` passes this same object: whichever of the bootstrap and the provider runs first
 * wires the analytics, and the other is not warned about a mismatch.
 */
export const APP_THEME_OPTIONS: ThemeStoreOptions = { onAnalytics: reportThemeAnalytics };

/**
 * For values that come from the server: applying them neither writes local storage nor reports a
 * choice the user made. They are not kept out of storage for good: the runtime writes its whole
 * current state the next time the user changes any setting (so a user who confirms a hydrated value is
 * not reverted by a reload), and from then on the hydrated values are persisted local ones too.
 */
export const HYDRATE: ApplyOptions = { persist: false, track: false };

export function appThemeStore(): ThemeStore {
  return sharedThemeStore(APP_THEME_OPTIONS);
}
