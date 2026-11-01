import { useEffect, useRef, type JSX } from "react";
import { Button } from "@candleviewer/ui";

export interface ResetItem {
  readonly id: string;
  readonly label: string;
  readonly current: string;
  readonly defaultValue: string;
}

export interface ResetPreviewProps {
  readonly sectionLabel: string;
  readonly items: readonly ResetItem[];
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
}

/**
 * Reset-preview flow shell: lists what would change, current to default, before anything does.
 * Nothing resets until the explicit confirm; Esc and Cancel leave every value as it was.
 */
export function ResetPreview({
  sectionLabel,
  items,
  onConfirm,
  onCancel,
}: ResetPreviewProps): JSX.Element {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  const changing = items.filter((i) => i.current !== i.defaultValue);
  return (
    <section aria-labelledby="settings-reset-title">
      <h2 id="settings-reset-title" ref={heading} tabIndex={-1}>
        Reset {sectionLabel} to defaults
      </h2>
      {changing.length === 0 ? (
        <p>Every setting here already has its default value. Nothing would change.</p>
      ) : (
        <>
          <p>
            {changing.length} {changing.length === 1 ? "setting" : "settings"} would change:
          </p>
          <ul>
            {changing.map((i) => (
              <li key={i.id}>
                {i.label}: {i.current} to {i.defaultValue}
              </li>
            ))}
          </ul>
        </>
      )}
      <Button
        variant="danger"
        {...(changing.length === 0 ? { disabledReason: "Nothing would change." } : {})}
        onClick={onConfirm}
      >
        {`Reset ${changing.length} ${changing.length === 1 ? "setting" : "settings"}`}
      </Button>
      <Button onClick={onCancel}>Cancel</Button>
    </section>
  );
}
