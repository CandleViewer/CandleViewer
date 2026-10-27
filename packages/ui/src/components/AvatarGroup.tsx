import type { JSX } from "react";
import { Avatar } from "./Avatar.js";

export interface AvatarGroupItem {
  /** The account's full label: the avatar's initials and one entry of the group's name. */
  label: string;
}

export interface AvatarGroupProps {
  items: readonly AvatarGroupItem[];
  /** The avatars drawn; the rest fold into a `+N` chip. Their names stay in the group's accessible name. */
  max: number;
}

/** "{n} accounts: {every label}", the hidden ones included. */
export function avatarGroupName(items: readonly AvatarGroupItem[]): string {
  const noun = items.length === 1 ? "account" : "accounts";
  return `${items.length} ${noun}: ${items.map((item) => item.label).join(", ")}`;
}

/**
 * CMP-025: an overlapping stack of md avatars, a static image summary. Each avatar sits in a fixed
 * `size.icon` slot, so it overlaps the next by the difference (no negative gap). The cut-out ring is the
 * `--cv-avatar-group-ring` custom property, `color.surface.canvas` by default: a host on another surface
 * sets it to that surface's token (E23). Renders nothing for no items.
 */
export function AvatarGroup({ items, max }: AvatarGroupProps): JSX.Element | null {
  if (items.length === 0) return null;
  // A whole, non-negative cap: NaN and negatives draw no avatar (all fold into +N); Infinity draws all.
  const shown = items.slice(0, Number.isNaN(max) ? 0 : Math.max(0, Math.floor(max)));
  const hidden = items.length - shown.length;
  return (
    <span
      className="cv-avatar-group"
      data-cmp="CMP-025"
      data-overflow={hidden > 0 ? "" : undefined}
      role="img"
      aria-label={avatarGroupName(items)}
    >
      {shown.map((item, index) => (
        <span key={index} className="cv-avatar-group__slot">
          <Avatar label={item.label} />
        </span>
      ))}
      {hidden > 0 ? (
        <span className="cv-avatar-group__more" aria-hidden="true">
          +{hidden}
        </span>
      ) : null}
    </span>
  );
}
