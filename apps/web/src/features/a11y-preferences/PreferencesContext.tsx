import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { applyAppearance } from "../../shell/bootstrap/preferencesApply";
import { getShellState } from "../../shell/bootstrap/store";
import {
  increasedContrastThemeSettings,
  reducedMotionThemeSettings,
} from "../../shell/bootstrap/themeFromSettings";
import {
  DEFAULT_PREFERENCES,
  resolveFlags,
  resolveTriState,
  type A11yPreferences,
  type EngineFlags,
  type SystemMedia,
} from "./model";
import { loadPreferences, savePreferences } from "./prefsApi";

export interface PreferencesValue {
  readonly prefs: A11yPreferences;
  readonly media: SystemMedia;
  readonly flags: EngineFlags;
  readonly reducedMotion: boolean;
  readonly increasedContrast: boolean;
  readonly saveError: string | null;
  update: (patch: Partial<A11yPreferences>) => Promise<void>;
  retry: () => Promise<void>;
}

const Ctx = createContext<PreferencesValue | null>(null);

function readMedia(): SystemMedia {
  const m = typeof window !== "undefined" && window.matchMedia ? window.matchMedia : null;
  return {
    reducedMotion: m ? m("(prefers-reduced-motion: reduce)").matches : false,
    highContrast: m ? m("(prefers-contrast: more)").matches : false,
  };
}

export interface PreferencesProviderProps {
  readonly children: ReactNode;
  /** Receives plain-boolean flags on every change (the engine bridge); no scene rebuild. */
  readonly onEngineFlags?: (flags: EngineFlags) => void;
  readonly onChanged?: (key: string, value: unknown) => void;
}

export function PreferencesProvider(props: PreferencesProviderProps): JSX.Element {
  const { children, onEngineFlags, onChanged } = props;
  const [prefs, setPrefs] = useState<A11yPreferences>(DEFAULT_PREFERENCES);
  // True once `prefs` mirrors the server (the load or a save answered). Until then they are only the
  // defaults, which must not be fed to the theme runtime: they would reset a persisted local choice.
  const [settled, setSettled] = useState(false);
  const [media, setMedia] = useState<SystemMedia>(readMedia);
  const [saveError, setSaveError] = useState<string | null>(null);
  const pending = useRef<Partial<A11yPreferences> | null>(null);

  useEffect(() => {
    let live = true;
    loadPreferences().then(
      (p) => {
        if (live) {
          setPrefs(p);
          setSettled(true);
        }
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const qs = [
      window.matchMedia("(prefers-reduced-motion: reduce)"),
      window.matchMedia("(prefers-contrast: more)"),
    ];
    const on = (): void => setMedia(readMedia());
    qs.forEach((q) => q.addEventListener("change", on));
    return () => qs.forEach((q) => q.removeEventListener("change", on));
  }, []);

  const flags = useMemo(() => resolveFlags(prefs, media), [prefs, media]);
  const reducedMotion = resolveTriState(prefs.reduced_motion, media.reducedMotion);
  const increasedContrast = resolveTriState(prefs.increased_contrast, media.highContrast);

  useEffect(() => {
    onEngineFlags?.(flags);
  }, [flags, onEngineFlags]);

  // Reduced motion and increased contrast belong to the theme runtime, which owns the root attributes.
  // Each has a twin in the appearance the bootstrap loaded, so each is fed together with its twin, and
  // one at a time: a change of one must not re-send the other, which the user may have overridden in
  // this session (05-accessibility-standard.md §3.2), nor anything else (the theme, say).
  const motionPref = prefs.reduced_motion;
  const contrastPref = prefs.increased_contrast;
  useEffect(() => {
    if (!settled) return;
    applyAppearance(
      reducedMotionThemeSettings(motionPref, getShellState().preferences?.appearance),
    );
  }, [settled, motionPref]);
  useEffect(() => {
    if (!settled) return;
    applyAppearance(
      increasedContrastThemeSettings(contrastPref, getShellState().preferences?.appearance),
    );
  }, [settled, contrastPref]);

  useEffect(() => {
    const r = document.documentElement;
    r.dataset["focusRing"] = prefs.thick_focus_ring ? "thick" : "normal";
    r.dataset["keyboardOnly"] = String(prefs.keyboard_only);
  }, [prefs.thick_focus_ring, prefs.keyboard_only]);

  const update = useCallback(
    async (patch: Partial<A11yPreferences>): Promise<void> => {
      const before = prefs;
      pending.current = patch;
      setPrefs({ ...before, ...patch }); // applies immediately (next frame)
      try {
        setPrefs(await savePreferences(patch));
        setSettled(true);
        setSaveError(null);
        pending.current = null;
        for (const [k, v] of Object.entries(patch)) onChanged?.(k, v);
      } catch {
        setPrefs(before); // revert to the persisted value; never silently lie
        setSaveError("Could not save your accessibility preference.");
      }
    },
    [prefs, onChanged],
  );

  const retry = useCallback(async (): Promise<void> => {
    if (pending.current) await update(pending.current);
  }, [update]);

  const value: PreferencesValue = {
    prefs,
    media,
    flags,
    reducedMotion,
    increasedContrast,
    saveError,
    update,
    retry,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePreferences(): PreferencesValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("usePreferences requires PreferencesProvider");
  return v;
}
