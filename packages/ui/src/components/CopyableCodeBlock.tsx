import type { CSSProperties, JSX } from "react";
import { CopyButton } from "./CopyButton.js";
import { useFocusRing } from "./FocusRing.js";
import { cx } from "./internal/cx.js";

export interface CopyableCodeBlockProps {
  /** The text, shown exactly as given: never parsed, highlighted, reformatted or interpreted as markup. */
  readonly code: string;
  /** The text's format, e.g. `json` or `yaml`, as `data-language`; the block never parses it. */
  readonly language: string;
  /** Names the scroll region, e.g. "Raw record" (E42-D04 AD-2). */
  readonly label: string;
  /** The Copy button's name; default "Copy {label}". */
  readonly copyLabel?: string;
  /**
   * The region's largest block size, a CSS length the host sizes (no size token exists), e.g. "20rem"; past it
   * the region scrolls. Default none: it grows with the text.
   */
  readonly maxHeight?: string;
  /** The region's id, for a host's `aria-controls` (SCR-136's Show raw record). */
  readonly id?: string;
  /** Called after a successful copy, with no argument (CMP-033). */
  readonly onCopied?: () => void;
}

/**
 * CMP-068 CopyableCodeBlock: a read-only `<pre>` that is a focusable scroll region named by `label`
 * (`tabindex="0"`, `role="region"`; E42-D04 AD-2), followed by a CMP-033 CopyButton that copies `code` exactly.
 * Stand-in tokens (E42-D04 §15): `color.surface.sunken` for `color.surface.code`, `type.num.sm` for `font.mono`.
 * Only the region scrolls sideways (`16:128`); it speaks only through CMP-033's "Copied".
 */
export function CopyableCodeBlock({
  code,
  language,
  label,
  copyLabel,
  maxHeight,
  id,
  onCopied,
}: CopyableCodeBlockProps): JSX.Element {
  const ring = useFocusRing();
  const cap = maxHeight?.trim();
  const style =
    cap === undefined || cap === ""
      ? undefined
      : ({ "--cv-codeblock-max-height": cap } as CSSProperties);
  return (
    <div className="cv-codeblock" data-cmp="CMP-068" data-language={language} style={style}>
      {/* A focusable scroll region (WCAG 2.1.1): `role="region"` carries the name a bare pre may not. */}
      <pre
        id={id}
        className={cx(ring.className, "cv-codeblock__pre")}
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scroll region the keyboard must reach to scroll (WCAG 2.1.1; E42-D04 AD-2)
        tabIndex={0}
        role="region"
        aria-label={label}
      >
        <code className="cv-codeblock__code">{code}</code>
      </pre>
      <div className="cv-codeblock__actions">
        <CopyButton
          value={code}
          label={copyLabel ?? `Copy ${label}`}
          {...(onCopied === undefined ? {} : { onCopied })}
        />
      </div>
    </div>
  );
}
