import { useRef, useState, type JSX, type ReactNode } from "react";
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

  function closePreview(): void {
    setPreviewing(false);
    resetButton.current?.querySelector("button")?.focus();
  }

  return (
    <div style={{ display: "flex", gap: "var(--space-inset-lg, 16px)" }}>
      <div>
        <label htmlFor="settings-search">Search settings</label>
        <SearchBox
          id="settings-search"
          label="Search settings"
          value={query}
          onChange={setQuery}
          onClear={() => setQuery("")}
        />
        <SettingsNav />
      </div>
      <div style={{ flex: 1 }}>
        {searching ? (
          <section aria-labelledby="settings-results-title">
            <h2 id="settings-results-title">Search results ({results.length})</h2>
            <ul>
              {results.map((r) => (
                <li key={r.key}>
                  <p>{r.path}</p>
                  <p>{r.setting?.description ?? r.section.description}</p>
                  {r.setting !== null && <p>{r.setting.scope}</p>}
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
                `${section.label} reset: ${n} settings restored.`,
                "settings:reset",
              );
              closePreview();
            }}
          />
        ) : null}
        {children}
      </div>
    </div>
  );
}
