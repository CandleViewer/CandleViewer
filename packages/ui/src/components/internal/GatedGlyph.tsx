import type { JSX } from "react";

/**
 * The trailing lock of a disabled-with-reason control: decorative (the reason text is the description).
 * TODO(#271): a one-file seam; slice 2 replaces this inline glyph with the icon registry's `Icon`.
 */
export function GatedGlyph({ className }: { readonly className?: string }): JSX.Element {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      aria-hidden="true"
      focusable="false"
    >
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}
