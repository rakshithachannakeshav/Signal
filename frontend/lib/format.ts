/**
 * format.ts
 * Small formatting helpers shared across chat UI components.
 */

/**
 * Formats an ISO date string into a local HH:MM time string.
 *
 * Backend timestamps are naive UTC (no explicit timezone suffix). This
 * appends "Z" when one isn't already present before parsing — otherwise the
 * browser would interpret the timestamp as local time and show the wrong hour.
 */
export function formatMessageTime(dateStr: string): string {
  if (!dateStr) return '';
  const hasTimezone = dateStr.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr);
  const parsedDate = new Date(hasTimezone ? dateStr : dateStr + 'Z');
  return parsedDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
