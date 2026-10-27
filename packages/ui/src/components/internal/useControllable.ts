import { useState } from "react";

/** A boolean that is controlled when `controlled` is given, else held here from `initial`. */
export function useControllable(
  controlled: boolean | undefined,
  initial: boolean,
): readonly [boolean, (next: boolean) => void] {
  const [held, setHeld] = useState(initial);
  const value = controlled ?? held;
  return [
    value,
    (next) => {
      if (controlled === undefined) setHeld(next);
    },
  ];
}
