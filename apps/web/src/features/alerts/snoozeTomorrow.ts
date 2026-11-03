/**
 * "Until tomorrow" (E40-D02 D-5): the next 00:00 in an IANA zone, as an epoch-ms instant. The zone
 * offset is read from `Intl` at the candidate instant, so a DST change inside the day is honoured.
 */
function zoneOffsetMs(utcMs: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(utcMs));
  const n = (type: string): number => Number(parts.find((part) => part.type === type)?.value);
  const asUtc = Date.UTC(n("year"), n("month") - 1, n("day"), n("hour"), n("minute"), n("second"));
  return asUtc - Math.floor(utcMs / 1000) * 1000;
}

export function nextLocalMidnightMs(nowMs: number, timeZone: string): number {
  const local = new Date(nowMs + zoneOffsetMs(nowMs, timeZone));
  const wallMidnight = Date.UTC(
    local.getUTCFullYear(),
    local.getUTCMonth(),
    local.getUTCDate() + 1,
  );
  // First guess with the offset now, then correct with the offset at the guess (DST day).
  const guess = wallMidnight - zoneOffsetMs(nowMs, timeZone);
  return wallMidnight - zoneOffsetMs(guess, timeZone);
}
