import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
import { Icon } from "../icons/Icon.js";
import { useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { SectionContext, type SectionContextValue } from "./internal/sectionContext.js";
import { useControllable } from "./internal/useControllable.js";
import { useFocusRing } from "./FocusRing.js";
import { Heading } from "./Typography.js";

export interface FormSectionProps {
  /** The heading: the section's (group's) name, and the disclosure button's when collapsible. */
  readonly title: string;
  /** A caption under the heading; the group's description. */
  readonly description?: string | undefined;
  /** The heading's level inside the legend (D02F G14); default 3. */
  readonly headingLevel?: 2 | 3 | 4;
  /** The APG Disclosure pattern: a button inside the heading shows and hides the fields. */
  readonly collapsible?: boolean;
  /** Controlled expansion (collapsible only). */
  readonly open?: boolean;
  /** Uncontrolled initial expansion (collapsible only); default true. */
  readonly defaultOpen?: boolean;
  /** Called with the requested expansion: a toggle, or the section opening around an invalid field. */
  readonly onOpenChange?: (open: boolean) => void;
  /**
   * The problems inside, for the collapsed heading line ("2 problems"). Absent: the CMP-040 FormFields inside that
   * show an error.
   */
  readonly errorCount?: number;
  /** Plain disabled (`<fieldset disabled>`): unavailable to everyone in this state; the fields dim. */
  readonly disabled?: boolean;
  /**
   * The section is read-only for the session (E09-D09 §2.2 T2): one notice under the heading that every CMP-040
   * field inside points at; each field keeps the lock in its well and renders no reason of its own.
   */
  readonly disabledReason?: string | undefined;
  /** Emits `data-density`; absent = inherit. */
  readonly density?: "comfortable" | "compact";
  /** CMP-040 FormFields, `space.stack.md` apart. */
  readonly children: ReactNode;
}

const problems = (count: number): string => (count === 1 ? "1 problem" : `${count} problems`);

/**
 * CMP-065: a `fieldset` whose `legend` wraps a heading (D02F CMP-065, G14). Collapsible: a disclosure button inside
 * the heading; a collapsed section's fields leave the Tab order (`hidden`), its heading line counts the problems
 * inside, and a submit opens it around an invalid field so focus can reach the field. A native constraint failure
 * opens it before the browser moves focus; a host-validated FormField error opens it after the submit renders, and
 * focus moves to the first invalid control unless it is already on one.
 */
export function FormSection({
  title,
  description,
  headingLevel = 3,
  collapsible = false,
  open: openProp,
  defaultOpen = true,
  onOpenChange,
  errorCount,
  disabled,
  disabledReason,
  density,
  children,
}: FormSectionProps): JSX.Element {
  const headingId = useId();
  const descriptionId = useId();
  const bodyId = useId();
  const errorsId = useId();
  const reason = useDisabledReason(disabled, disabledReason);
  const ring = useFocusRing();
  const [held, setHeld] = useControllable(openProp, defaultOpen);
  const expanded = !collapsible || held;
  const rootRef = useRef<HTMLFieldSetElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const invalidKeys = useRef(new Map<string, boolean>());
  const [invalidCount, setInvalidCount] = useState(0);
  const [, setSubmits] = useState(0);
  const submitted = useRef(false);
  const focusPending = useRef(false);

  const setOpen = useCallback(
    (next: boolean): void => {
      setHeld(next);
      onOpenChange?.(next);
    },
    [setHeld, onOpenChange],
  );

  const reportInvalid = useCallback((key: string, invalid: boolean): void => {
    const map = invalidKeys.current;
    const before = map.size;
    if (invalid) map.set(key, true);
    else map.delete(key);
    // Only a change in the count costs a render; a field that stays invalid reports nothing new.
    if (map.size !== before) setInvalidCount(map.size);
  }, []);

  const context = useMemo<SectionContextValue>(
    () => ({ reason, reportInvalid }),
    [reason, reportInvalid],
  );

  // A submit arms the section; the render that follows (the host's validation) decides whether it opens.
  useEffect(() => {
    const form = rootRef.current?.form;
    if (!collapsible || form === null || form === undefined) return undefined;
    const onSubmit = (): void => {
      submitted.current = true;
      setSubmits((n) => n + 1);
    };
    form.addEventListener("submit", onSubmit, true);
    return () => form.removeEventListener("submit", onSubmit, true);
  }, [collapsible]);

  // Children's layout effects have reported into the map by now, so the count is this commit's. The arm lasts this
  // one commit (the submit's render, which carries the host's validation): a clean submit disarms, so a later blur or
  // server error never reopens the section or moves focus.
  useLayoutEffect(() => {
    if (!submitted.current) return;
    submitted.current = false;
    const count = errorCount ?? invalidKeys.current.size;
    if (count === 0 || expanded) return;
    focusPending.current = true;
    setOpen(true);
  });

  // Once the body shows, focus reaches the first invalid control unless the host already put it on one. A controlled
  // host that declines the submit's onOpenChange(true) leaves this pending until the user's own toggle clears it.
  useLayoutEffect(() => {
    if (!expanded || !focusPending.current) return;
    focusPending.current = false;
    const active = rootRef.current?.ownerDocument.activeElement;
    if (active?.closest('[aria-invalid="true"]')) return;
    bodyRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [expanded]);

  /** Native constraint validation: open at once, so the browser can focus the field it reports. */
  const onInvalidCapture = (): void => {
    if (expanded) return;
    flushSync(() => setOpen(true));
  };

  const count = errorCount ?? invalidCount;
  const showErrors = collapsible && !expanded && count > 0;
  const hasDescription = description !== undefined && description !== "";

  return (
    <fieldset
      ref={rootRef}
      className="cv-formsection"
      data-cmp="CMP-065"
      data-density={density}
      data-collapsed={expanded ? undefined : ""}
      disabled={reason.disabled}
      aria-labelledby={headingId}
      aria-describedby={hasDescription ? descriptionId : undefined}
      onInvalidCapture={onInvalidCapture}
    >
      <legend className="cv-formsection__legend">
        <Heading
          id={headingId}
          level={headingLevel}
          variant="heading-sm"
          className="cv-formsection__heading"
        >
          {collapsible ? (
            <button
              type="button"
              className={cx("cv-formsection__toggle", ring.className)}
              aria-expanded={expanded}
              aria-controls={bodyId}
              aria-describedby={showErrors ? errorsId : undefined}
              onClick={() => {
                // The user's own toggle settles a pending submit: a later error never reopens the section, and a
                // manual open never moves focus.
                submitted.current = false;
                focusPending.current = false;
                setOpen(!expanded);
              }}
            >
              <span className="cv-formsection__chevron">
                <Icon name={expanded ? "chevron-down" : "chevron-right"} />
              </span>
              <span>{title}</span>
            </button>
          ) : (
            title
          )}
        </Heading>
        {showErrors ? (
          <span id={errorsId} className="cv-formsection__errors">
            <span className="cv-formsection__glyph">
              <Icon name="danger" />
            </span>
            <span>{problems(count)}</span>
          </span>
        ) : null}
      </legend>
      {hasDescription ? (
        <p id={descriptionId} className="cv-formsection__description">
          {description}
        </p>
      ) : null}
      {reason.gated ? (
        <p id={reason.reasonId} className="cv-formsection__notice">
          {reason.reason}
        </p>
      ) : null}
      <div ref={bodyRef} id={bodyId} className="cv-formsection__body" hidden={!expanded}>
        <SectionContext.Provider value={context}>{children}</SectionContext.Provider>
      </div>
    </fieldset>
  );
}
