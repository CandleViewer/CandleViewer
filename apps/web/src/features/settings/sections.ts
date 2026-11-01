/** SCR-110 section list and the settings index the search reads (14-screens-catalogue.md §9). */

export interface SettingsSection {
  readonly id: string;
  readonly label: string;
  /** One line under the label (SCR-110 checklist: "all sections listed with a one-line description"). */
  readonly description: string;
  /** Where the section is built today; absent = not built yet, shown disabled with `reason`. */
  readonly path?: string;
  /** A section that shares a route with another is told apart by its hash. */
  readonly hash?: string;
}

/** T2 wording for a section whose screen has not shipped: disabled with a reason, never hidden. */
export const NOT_BUILT_REASON = "Not available yet: this section ships in a later release.";

/** The nine sections of SCR-110, in catalogue order. */
export const SECTIONS: readonly SettingsSection[] = [
  {
    id: "profile",
    label: "Profile",
    description: "Name, contact details and defaults.",
    path: "/settings/profile",
  },
  {
    id: "security",
    label: "Security",
    description: "Password, two-factor and active sessions.",
    path: "/settings/profile",
    hash: "#security",
  },
  {
    id: "appearance",
    label: "Appearance",
    description: "Theme, density and chart colours.",
    path: "/settings/appearance",
  },
  {
    id: "hotkeys",
    label: "Hotkeys",
    description: "Every command with its key binding.",
    path: "/settings/hotkeys",
  },
  {
    id: "trading-defaults",
    label: "Trading defaults",
    description: "Order type, size and confirmation defaults.",
  },
  {
    id: "notifications",
    label: "Notifications",
    description: "Channels and quiet hours per event.",
  },
  {
    id: "data-performance",
    label: "Data & performance",
    description: "Renderer, frame cap and cache.",
  },
  {
    id: "accessibility",
    label: "Accessibility",
    description: "Motion, contrast, focus and announcements.",
    path: "/settings/appearance",
    hash: "#accessibility",
  },
  {
    id: "help",
    label: "Help & about",
    description: "Version, cheatsheet and diagnostics.",
  },
];

export interface SettingEntry {
  readonly id: string;
  readonly sectionId: string;
  readonly label: string;
  readonly description: string;
  /** Who and what the setting applies to; said beside the control. */
  readonly scope: string;
}

const DEVICE = "Applies to this device only.";
const ACCOUNT = "Applies to your account on every device.";

/** Only settings that exist today; a section not built yet has no entries and is found by its name. */
export const SETTINGS: readonly SettingEntry[] = [
  {
    id: "chart-palette",
    sectionId: "appearance",
    label: "Chart palette",
    description: "Default or colour-blind safe colours for charts.",
    scope: DEVICE,
  },
  {
    id: "chart-convention",
    sectionId: "appearance",
    label: "Colour convention",
    description: "Which colour means buy and which means sell.",
    scope: DEVICE,
  },
  {
    id: "keybindings",
    sectionId: "hotkeys",
    label: "Key bindings",
    description: "Rebind, unbind or reset a command's keys.",
    scope: "Applies to your keymap profile.",
  },
  {
    id: "active-sessions",
    sectionId: "security",
    label: "Active sessions",
    description: "See where you are signed in and sign a device out.",
    scope: ACCOUNT,
  },
  {
    id: "reduced-motion",
    sectionId: "accessibility",
    label: "Reduced motion",
    description: "Follow the system, or always or never reduce animation.",
    scope: ACCOUNT,
  },
  {
    id: "increased-contrast",
    sectionId: "accessibility",
    label: "Increased contrast",
    description: "Follow the system, or always or never use high contrast.",
    scope: ACCOUNT,
  },
  {
    id: "canvas-animation",
    sectionId: "accessibility",
    label: "Disable canvas animation",
    description: "Stop chart animation, fades and flashes on update.",
    scope: ACCOUNT,
  },
  {
    id: "data-tables",
    sectionId: "accessibility",
    label: "Always show data tables",
    description: "Show the table alternative beside every chart.",
    scope: ACCOUNT,
  },
  {
    id: "focus-ring",
    sectionId: "accessibility",
    label: "Thicker focus ring",
    description: "Draw a heavier outline on the focused control.",
    scope: ACCOUNT,
  },
  {
    id: "announce-prices",
    sectionId: "accessibility",
    label: "Announce price updates",
    description: "Off, on significant change, or always.",
    scope: ACCOUNT,
  },
  {
    id: "verbosity",
    label: "Screen-reader verbosity",
    sectionId: "accessibility",
    description: "How much a screen reader says for streaming panels.",
    scope: ACCOUNT,
  },
  {
    id: "keyboard-only",
    sectionId: "accessibility",
    label: "Keyboard-only mode",
    description: "Reveal a form equivalent for every drag-only interaction.",
    scope: ACCOUNT,
  },
];

export interface SearchResult {
  readonly key: string;
  readonly section: SettingsSection;
  readonly setting: SettingEntry | null;
  /** "Settings > Accessibility > Reduced motion": the path said and shown for the match. */
  readonly path: string;
}

/** Pure search over section names and settings; an empty query has no results. */
export function searchSettings(query: string): readonly SearchResult[] {
  const q = query.trim().toLowerCase();
  if (q === "") return [];
  const out: SearchResult[] = [];
  for (const section of SECTIONS) {
    if (`${section.label} ${section.description}`.toLowerCase().includes(q)) {
      out.push({ key: section.id, section, setting: null, path: `Settings > ${section.label}` });
    }
    for (const setting of SETTINGS) {
      if (setting.sectionId !== section.id) continue;
      if (`${setting.label} ${setting.description}`.toLowerCase().includes(q)) {
        out.push({
          key: `${section.id}/${setting.id}`,
          section,
          setting,
          path: `Settings > ${section.label} > ${setting.label}`,
        });
      }
    }
  }
  return out;
}

/** The sentence the announcer says: the count, then up to five section paths. */
export function resultsSentence(results: readonly SearchResult[]): string {
  const n = results.length;
  const head = `${n} ${n === 1 ? "result" : "results"}`;
  if (n === 0) return `${head}.`;
  const shown = results.slice(0, 5).map((r) => r.path.replace("Settings > ", ""));
  const more = n > 5 ? `, and ${n - 5} more` : "";
  return `${head}: ${shown.join("; ")}${more}.`;
}
