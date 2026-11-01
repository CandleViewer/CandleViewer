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
  const section = useRef<HTMLElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => {
    // Esc cancels only while focus is inside the preview, so it never closes anything else.
    const root = section.current;
    if (root === null) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") cancel.current();
    };
    root.addEventListener("keydown", onKey);
    return () => root.removeEventListener("keydown", onKey);
  }, []);
  const changing = items.filter((i) => i.current !== i.defaultValue);
  return (
    <section ref={section} aria-labelledby="settings-reset-title">
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
