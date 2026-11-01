import { useId, type JSX, type ReactNode } from "react";

export interface SettingRowProps {
  readonly label: string;
  readonly description: string;
  /** Who and what the setting applies to (SCR-110: never a bare toggle). */
  readonly scope: string;
  /** The one control; it is named by the label and described by the description and scope. */
  readonly children: (ids: { readonly labelId: string; readonly describedBy: string }) => ReactNode;
}

/** One setting: a persistent visible label, its description and its scope, read with the control. */
export function SettingRow({ label, description, scope, children }: SettingRowProps): JSX.Element {
  const id = useId();
  const labelId = `${id}-label`;
  const describedBy = `${id}-desc ${id}-scope`;
  return (
    <div role="group" aria-labelledby={labelId}>
      <p id={labelId} style={{ fontWeight: 600, margin: 0 }}>
        {label}
      </p>
      <p id={`${id}-desc`} style={{ margin: 0 }}>
        {description}
      </p>
      <p id={`${id}-scope`} style={{ margin: 0 }}>
        {scope}
      </p>
      {children({ labelId, describedBy })}
    </div>
  );
}
