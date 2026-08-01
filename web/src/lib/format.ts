// Small presentation helpers shared across the dashboard.

/** Thousands-separated integer, e.g. 1647009 -> "1,647,009". */
export const fmt = (n: number): string => n.toLocaleString("en-US");

/** A coverage percentage: 2 decimals under 1%, else 1 (keeps tiny values visible). */
export const fmtPct = (p: number): string => p.toFixed(p < 1 ? 2 : 1);

/** Substitute the taxid into a metric's external URL template. */
export const externalUrl = (template: string, taxid: number): string =>
  template.replace("{taxid}", String(taxid));
