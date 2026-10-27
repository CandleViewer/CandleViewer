// Every registered icon's component, keyed by registry name: INTERNAL, `Icon` (CMP-019) is the
// public way to draw one. Add a glyph to `registry.ts`, its module and a line here together.
import type { JSX } from "react";
import type { GlyphProps } from "../IconSvg.js";
import type { IconName } from "../registry.js";
import { ArrowDownIcon } from "./ArrowDownIcon.js";
import { ArrowUpIcon } from "./ArrowUpIcon.js";
import { CheckIcon } from "./CheckIcon.js";
import { ChevronDownIcon } from "./ChevronDownIcon.js";
import { ChevronRightIcon } from "./ChevronRightIcon.js";
import { CloseIcon } from "./CloseIcon.js";
import { DangerIcon } from "./DangerIcon.js";
import { InfoIcon } from "./InfoIcon.js";
import { LockIcon } from "./LockIcon.js";
import { MinusIcon } from "./MinusIcon.js";
import { PlusIcon } from "./PlusIcon.js";
import { UnlockIcon } from "./UnlockIcon.js";
import { WarningIcon } from "./WarningIcon.js";

export const ICON_COMPONENTS = {
  "arrow-down": ArrowDownIcon,
  "arrow-up": ArrowUpIcon,
  check: CheckIcon,
  "chevron-down": ChevronDownIcon,
  "chevron-right": ChevronRightIcon,
  close: CloseIcon,
  danger: DangerIcon,
  info: InfoIcon,
  lock: LockIcon,
  minus: MinusIcon,
  plus: PlusIcon,
  unlock: UnlockIcon,
  warning: WarningIcon,
} as const satisfies Readonly<Record<IconName, (props: GlyphProps) => JSX.Element>>;
