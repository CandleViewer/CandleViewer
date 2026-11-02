import type { JSX } from "react";
import { Button } from "./Button.js";
import { IconButton } from "./IconButton.js";
import { Menu, type MenuItem } from "./Menu.js";

export interface SplitButtonPrimary {
  /** The primary half's full label and accessible name: "Close", "Cancel" (E29-D05 N-04, N-06). */
  readonly label: string;
  /** Runs on a press; never while busy or gated (T2). */
  readonly onClick: () => void;
  /** The label while busy, kept visible beside a static ⟳: "Closing…", "Cancelling…" (E29-D02:341, :345). */
  readonly busyLabel?: string;
}

/**
 * The primary's gate, CMP-079's pair (E29-D04 §2.8.4 asks for it on the primary only): allowed, or denied with the
 * row's own reason sentence, never a role prop. The sentence is a key's, resolved by the host (`formatRbacReason`) or
 * a registered state string; a screen writes none of its own (`32-design-specs.md` G-T2.4). An allowed reason is
 * ignored, so a host may keep it computed.
 */
type SplitButtonGate =
  | { readonly allowed?: true; readonly reason?: string }
  | { readonly allowed: false; readonly reason: string };

interface SplitButtonBase {
  readonly primary: SplitButtonPrimary;
  /**
   * The ▾ half's CMP-041 items: the row's other actions, which the row menu repeats (E29-D02:153). The primary's gate
   * never reaches them: each keeps the `disabledReason` its host computes from its own operation (E09-D09 §2.3).
   */
  readonly items: readonly MenuItem[];
  /**
   * The ▾ half's accessible name, naming its row: "More close actions, BTCUSDT Long on Main" (E29-D05 N-05 and
   * N-07, PROPOSED). It also names the menu.
   */
  readonly menuLabel: string;
  /**
   * A request is in flight (E29-D02:341): the primary keeps its label, `busyLabel` when given, with `aria-busy` and a
   * static ⟳ leading it (Mo-12); a second press does nothing. Busy is not T2: no lock and no reason. A gate wins.
   */
  readonly busy?: boolean;
  /**
   * The T2 contract every atom takes, where CMP-079 RbacGate hands a role leg's reason. It gates the primary alone and
   * wins over `reason`, as E09-D09 §2.1 checks the role legs before a state. On SCR-063 a role leg is a scope's reason,
   * which renders once through the panel's notice (E29-D02 §10.4; CMP-079 `form="notice"`, E05's), not per row.
   */
  readonly disabledReason?: string;
  /** Both halves' CMP-001 / CMP-002 variant; default `secondary`. */
  readonly variant?: "primary" | "secondary" | "ghost";
  /** Emits `data-density` on both halves; absent = inherit. */
  readonly density?: "comfortable" | "compact";
  /** CMP-041's: a host that owns its surface's one polite region says each re-shown item reason (CMP-049, G12). */
  readonly announceReason?: (reason: string) => void;
}

export type SplitButtonProps = SplitButtonBase & SplitButtonGate;

const sentence = (text: string | undefined): string | undefined => {
  const trimmed = text?.trim();
  return trimmed === "" ? undefined : trimmed;
};

/**
 * CMP-057 SplitButton (`15` CMP-057; E29-D04 §2.8.4; E29-S01, built here and mounted by the ticket that wires the
 * row actions): two separately focusable controls, the primary CMP-001 and the ▾ CMP-002, which opens a CMP-041 menu.
 *
 * Gated (`allowed={false}` with a `reason`, or CMP-079's `disabledReason`): the primary alone is T2, in rendering 2b,
 * which E29-D02 §10.4 keeps for a reason that is the row's own (an order's or a position's state, a manager's freeze;
 * no inline room in a 24 px row): it keeps its role and full label, takes `aria-disabled="true"`, never `disabled`,
 * stays in the Tab order, is described by the reason node rendered at mount and echoed by CMP-016 on hover and focus,
 * and a press sends nothing and re-shows the reason once, politely. The ▾ stays a working menu button, and its items
 * keep the reasons their host computes (E09-D09 §2.3): an item the row's reason also covers repeats it as its second
 * line, so the reason is never hover-only, and one it does not cover stays enabled (Chart never takes T2, E29-D02
 * §8.1). A scope's reason (a Viewer, view-as, offline, the other environment, a read-only grant) is no row's own: it
 * renders once through its notice (E29-D02 §10.4). Busy: the primary keeps its label, `aria-busy`, no lock (D04 §4.2).
 */
export function SplitButton(props: SplitButtonProps): JSX.Element {
  const {
    primary,
    items,
    menuLabel,
    busy = false,
    variant = "secondary",
    density,
    announceReason,
  } = props;
  const gate =
    sentence(props.disabledReason) ??
    (props.allowed === false ? sentence(props.reason) : undefined);
  // Gated wins over busy, as on a CMP-041 item: the reason is what a user can act on.
  const working = busy && gate === undefined;
  const dense = density === undefined ? {} : { density };
  return (
    <span
      className="cv-split-button"
      data-cmp="CMP-057"
      data-gated={gate === undefined ? undefined : ""}
      data-busy={working ? "" : undefined}
    >
      <Button
        variant={variant}
        {...dense}
        {...(gate === undefined ? {} : { disabledReason: gate })}
        {...(working ? { loading: true, iconLeft: "refresh" as const } : {})}
        onClick={() => primary.onClick()}
      >
        {working ? (primary.busyLabel ?? primary.label) : primary.label}
      </Button>
      <Menu
        trigger={<IconButton icon="chevron-down" label={menuLabel} variant={variant} {...dense} />}
        items={items}
        {...(announceReason === undefined ? {} : { announceReason })}
      />
    </span>
  );
}
