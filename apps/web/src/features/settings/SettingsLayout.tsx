import { useEffect, useId, useRef, useState, type JSX, type ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { Button, SearchBox } from "@candleviewer/ui";
import { announce, forget } from "../app-shell/announcer";
import { ResetPreview, type ResetItem } from "./ResetPreview";
import { currentSectionId, SettingsNav } from "./SettingsNav";
import { NOT_BUILT_REASON, SECTIONS } from "./sections";
import { useSettingsSearch } from "./useSettingsSearch";

export interface SettingsResetSource {
  /** What a reset of the current section would change; supplied by the section that owns the values. */
  readonly items: readonly ResetItem[];
  readonly onConfirm: () => void;
}

export interface SettingsLayoutProps {
  readonly children: ReactNode;
  /** Absent until the settings service can reset a section: the button then reads disabled with a reason. */
  readonly reset?: SettingsResetSource;
}

const RESET_REASON = "Not available yet: resetting needs the settings service.";

/** CMP-086 layout half: nav on the left, search above, the selected section on the right. */
export function SettingsLayout({ children, reset }: SettingsLayoutProps): JSX.Element {
  const { pathname, hash } = useLocation();
  const section = SECTIONS.find((s) => s.id === currentSectionId(pathname, hash));
  const { query, setQuery, results } = useSettingsSearch();
  const [previewing, setPreviewing] = useState(false);
  const resetButton = useRef<HTMLSpanElement>(null);
  const searching = query.trim() !== "";
  const searchId = useId();

  // A hash change (Security, Accessibility) moves focus to that section's heading; the first render is left alone.
  const previousHash = useRef(hash);
  useEffect(() => {
    if (previousHash.current === hash) return;
    previousHash.current = hash;
    const target = hash === "" ? null : document.getElementById(hash.slice(1));
    const heading = target?.querySelector<HTMLElement>("h1, h2") ?? null;
    if (heading === null) return;
    if (!heading.hasAttribute("tabindex")) {
      heading.setAttribute("tabindex", "-1");
      heading.addEventListener("blur", () => heading.removeAttribute("tabindex"), { once: true });
    }
    heading.focus();
  }, [hash]);

  function closePreview(): void {
    setPreviewing(false);
    resetButton.current?.querySelector("button")?.focus();
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-inset-lg, 16px)" }}>
      <div style={{ flex: "0 1 16rem", minWidth: 0 }}>
        <label htmlFor={searchId}>Search settings</label>
        <SearchBox
          id={searchId}
          label="Search settings"
          value={query}
          onChange={setQuery}
          onClear={() => setQuery("")}
        />
        <SettingsNav />
      </div>
      <div style={{ flex: "1 1 20rem", minWidth: 0 }}>
        {searching ? (
          <section aria-labelledby="settings-results-title">
            <h2 id="settings-results-title">Search results ({results.length})</h2>
            <ul>
              {results.map((r) => (
                <li key={r.key}>
                  <p>{r.path}</p>
                  <p>{r.setting?.description ?? r.section.description}</p>
                  {r.setting !== null && <p>Scope: {r.setting.scope}</p>}
                  {r.section.path === undefined ? (
                    <p>{NOT_BUILT_REASON}</p>
                  ) : (
                    <Link to={`${r.section.path}${r.section.hash ?? ""}`}>
                      {`Open ${r.section.label}`}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        {section !== undefined && !searching ? (
          <span ref={resetButton}>
            <Button
              {...(reset === undefined ? { disabledReason: RESET_REASON } : {})}
              onClick={() => {
                forget("settings:reset");
                setPreviewing(true);
              }}
            >
              {`Reset ${section.label}…`}
            </Button>
          </span>
        ) : null}
        {previewing && reset !== undefined && section !== undefined ? (
          <ResetPreview
            sectionLabel={section.label}
            items={reset.items}
            onCancel={closePreview}
            onConfirm={() => {
              const n = reset.items.filter((i) => i.current !== i.defaultValue).length;
              reset.onConfirm();
              announce(
                "polite",
                `${section.label} reset: ${n} ${n === 1 ? "setting" : "settings"} restored.`,
                "settings:reset",
              );
              closePreview();
            }}
          />
        ) : null}
        {searching ? null : children}
      </div>
    </div>
  );
}
