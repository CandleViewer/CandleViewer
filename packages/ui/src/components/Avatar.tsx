import type { JSX } from "react";

export type AvatarSize = "sm" | "md";

export interface AvatarProps {
  /** The account's full label; the initials derive from it, and it is the name when `standalone`. */
  label: string;
  /** sm = `size.icon`, one initial; md = `size.control.height`, two initials (E12). */
  size?: AvatarSize;
  /**
   * The avatar is the only content: `role="img"` named by the full label, never the initials. By default
   * it sits beside its visible name and is decorative (`aria-hidden`), as it is with a blank label.
   */
  standalone?: boolean;
}

/** The first letter of each of the first two words (one at sm), upper-cased. */
export function avatarInitials(label: string, size: AvatarSize = "md"): string {
  const words = label.trim().split(/\s+/).filter(Boolean);
  const letters = words.slice(0, size === "sm" ? 1 : 2).map((word) => Array.from(word)[0] ?? "");
  return letters.join("").toLocaleUpperCase();
}

/**
 * CMP-013: an initials circle, static and never focusable. The fill is the interim `color.neutral.subtle`
 * until an avatar palette is approved (E2), so the catalogue's per-account `color` waits with it.
 */
export function Avatar({ label, size = "md", standalone = false }: AvatarProps): JSX.Element {
  // A blank label cannot name an img, so the avatar falls back to decorative rather than an unnamed img.
  const named = standalone && label.trim() !== "";
  return (
    <span
      className="cv-avatar"
      data-cmp="CMP-013"
      data-size={size}
      role={named ? "img" : undefined}
      aria-label={named ? label : undefined}
      aria-hidden={named ? undefined : "true"}
    >
      {avatarInitials(label, size)}
    </span>
  );
}
