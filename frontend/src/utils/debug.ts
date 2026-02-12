const DEBUG_UI = false;

/**
 * Conditional UI debug logger.
 */
export function debugLog(...args: unknown[]) {
  if (!DEBUG_UI) return;
  console.log('[dullypdf-ui]', ...args);
}
