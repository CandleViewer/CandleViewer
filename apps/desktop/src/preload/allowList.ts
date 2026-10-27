/**
 * Explicit IPC channel allow-list. Empty at E02-T04 (Do NOT: no business
 * logic here). E10-T02 adds exactly the three channels this ticket's
 * ShellPort surface needs (gpu info, opaque KEK handle, disabled update
 * check) — each is code-owned by the security engineer (trust boundary B4,
 * 20-architecture.md §2.2). `isChannelAllowed` rejects any channel not
 * present here so a caller can never widen the surface implicitly, and the
 * preload never accepts a caller-supplied channel name (SR-111): only these
 * literal, compile-time-constant strings are ever passed to `invoke`.
 */
export const ALLOWED_IPC_CHANNELS: readonly string[] = [
  "cv:gpu:info",
  "cv:keychain:getKekHandle",
  "cv:updates:check",
  // E10-S04: append one schema-checked crash entry to the local log; validated in preload and main.
  "cv:crashLog:append",
];

export function isChannelAllowed(
  channel: string,
  allowedChannels: readonly string[] = ALLOWED_IPC_CHANNELS,
): boolean {
  return allowedChannels.includes(channel);
}

/**
 * Builds the frozen record of invoke functions exposed as `window.cv`.
 * Throws if a requested channel is not on the allow-list — there is no
 * fallback path that silently permits an unlisted channel.
 */
export function buildAllowList(
  channels: readonly string[],
  invoke: (channel: string, ...args: unknown[]) => Promise<unknown>,
  allowedChannels: readonly string[] = ALLOWED_IPC_CHANNELS,
): Readonly<Record<string, (...args: unknown[]) => Promise<unknown>>> {
  for (const channel of channels) {
    if (!isChannelAllowed(channel, allowedChannels)) {
      throw new Error(`IPC channel "${channel}" is not on the allow-list`);
    }
  }
  return Object.freeze(
    Object.fromEntries(
      channels.map((channel) => [channel, (...args: unknown[]) => invoke(channel, ...args)]),
    ),
  );
}
