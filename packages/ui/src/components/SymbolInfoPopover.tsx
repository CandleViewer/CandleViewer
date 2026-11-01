import { useId, type JSX, type ReactNode } from "react";
import { Button } from "./Button.js";
import { FreshnessMarker } from "./FreshnessMarker.js";
import { IconButton } from "./IconButton.js";
import { KeyValueRow } from "./KeyValueRow.js";
import { Popover, type PopoverPlacement } from "./Popover.js";

/** E08-D06 §9: default, stale (the band marker), not trading (the status heading), unavailable. */
export type SymbolInfoPopoverState = "default" | "stale" | "not-trading" | "unavailable";

/** The contract band's four rows, already formatted by the host's shared formatter (F3); absent reads "not available". */
export interface SymbolInfoContract {
  readonly tickSize?: string | undefined;
  readonly quantityStep?: string | undefined;
  readonly minimumOrderValue?: string | undefined;
  readonly maximumLeverage?: string | undefined;
}

/** The live band's rows, formatted by the host (F4, F6). */
export interface SymbolInfoLive {
  readonly last?: string | undefined;
  readonly fundingRate?: string | undefined;
}

export interface SymbolInfoPopoverProps {
  /** The symbol: the dialog's name and heading. */
  symbol: string;
  /** Default `default`; `stale` needs `staleAgeMs`, `not-trading` the host's `notTradingHeading`. */
  state?: SymbolInfoPopoverState;
  contract?: SymbolInfoContract;
  live?: SymbolInfoLive;
  /** `stale`: the age of the last live value, drawn by the band marker (CMP-239). */
  staleAgeMs?: number | undefined;
  /** `stale` past T2: the strong marker. */
  staleEscalated?: boolean | undefined;
  /** `not-trading`: the host's status heading, e.g. "BTCUSDT is not trading on Bybit." (D06 D-5). */
  notTradingHeading?: string | undefined;
  /** The recording state word, the host's ("Not recorded"); absent reads "not available". */
  recording?: string | undefined;
  /** "Open full details": opens SCR-103. The host closes this popover or not, as it chooses. */
  onOpenFullDetails: () => void;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  placement?: PopoverPlacement;
}

/** The absent-value name D06 §4 gives a row ("—", name "not available"). */
const NOT_AVAILABLE = "not available";

/** PROPOSED (not verbatim in D06 / D13): the trigger's name "Symbol info for {symbol}" (§9 names no label). */

function Band({
  label,
  marker,
  children,
}: {
  label: string;
  marker?: ReactNode;
  children: ReactNode;
}): JSX.Element {
  const id = useId();
  return (
    <section className="cv-symbol-info__band" aria-labelledby={id}>
      <div className="cv-symbol-info__band-head">
        <h3 id={id} className="cv-symbol-info__band-label">
          {label}
        </h3>
        {marker}
      </div>
      {children}
    </section>
  );
}

const row = (label: string, value: string | undefined): JSX.Element => (
  <KeyValueRow label={label} value={value} missingLabel={NOT_AVAILABLE} />
);

/**
 * CMP-125: a compact, non-modal quick reference with the three band labels (E08-D06 §9), over CMP-017. It opens
 * from an explicit info button (`aria-haspopup="dialog"`), never on hover alone; `Esc` closes it and returns focus
 * to the button. Contract and live rows are CMP-036 lists in the host's pre-formatted text; the stale marker sits
 * in the live band's head only, so the contract rules stay undimmed. "Open full details" is the one action.
 */
export function SymbolInfoPopover({
  symbol,
  state = "default",
  contract,
  live,
  staleAgeMs,
  staleEscalated,
  notTradingHeading,
  recording,
  onOpenFullDetails,
  open,
  defaultOpen,
  onOpenChange,
  placement,
}: SymbolInfoPopoverProps): JSX.Element {
  const control = {
    ...(open === undefined ? {} : { open }),
    ...(defaultOpen === undefined ? {} : { defaultOpen }),
    ...(onOpenChange === undefined ? {} : { onOpenChange }),
    ...(placement === undefined ? {} : { placement }),
  };
  const marker =
    state === "stale" ? (
      <FreshnessMarker
        presentation="compact"
        state="stale"
        {...(staleAgeMs === undefined ? {} : { lastUpdatedAgeMs: staleAgeMs })}
        {...(staleEscalated === undefined ? {} : { escalated: staleEscalated })}
      />
    ) : undefined;
  return (
    <Popover
      {...control}
      heading={symbol}
      anchor={<IconButton icon="info" label={`Symbol info for ${symbol}`} variant="ghost" />}
      footer={
        <Button variant="secondary" onClick={onOpenFullDetails}>
          Open full details
        </Button>
      }
    >
      <div className="cv-symbol-info" data-cmp="CMP-125" data-state={state}>
        {state === "unavailable" ? (
          <p className="cv-symbol-info__message">Contract rules not loaded</p>
        ) : (
          <>
            <Band label="Contract rules">
              <dl className="cv-symbol-info__rows">
                {row("Tick size", contract?.tickSize)}
                {row("Quantity step", contract?.quantityStep)}
                {row("Minimum order value", contract?.minimumOrderValue)}
                {row("Maximum leverage", contract?.maximumLeverage)}
              </dl>
            </Band>
            <Band label="Live market" marker={marker}>
              {state === "not-trading" ? (
                <p className="cv-symbol-info__message">{notTradingHeading}</p>
              ) : (
                <dl className="cv-symbol-info__rows">
                  {row("Last", live?.last)}
                  {row("Funding rate", live?.fundingRate)}
                </dl>
              )}
            </Band>
            <Band label="Recording in CandleViewer">
              <p
                className="cv-symbol-info__message"
                data-missing={recording === undefined ? "" : undefined}
              >
                {recording ?? NOT_AVAILABLE}
              </p>
            </Band>
          </>
        )}
      </div>
    </Popover>
  );
}
