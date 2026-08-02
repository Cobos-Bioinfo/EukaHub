// Small presentation helpers shared across the dashboard.

/** Thousands-separated integer, e.g. 1647009 -> "1,647,009". */
export const fmt = (n: number): string => n.toLocaleString("en-US");

/** A coverage percentage: 2 decimals under 1%, else 1 (keeps tiny values visible). */
export const fmtPct = (p: number): string => p.toFixed(p < 1 ? 2 : 1);

/** Substitute the taxid into a metric's external URL template. */
export const externalUrl = (template: string, taxid: number): string =>
  template.replace("{taxid}", String(taxid));

/** A base-pair count as a human-readable size: 2841134231 -> "2.84 Gb",
 *  78812546 -> "78.8 Mb", 606714 -> "607 kb". Keeps ~3 significant figures. */
export function fmtBp(bp: number): string {
  const units: [number, string][] = [
    [1e9, "Gb"],
    [1e6, "Mb"],
    [1e3, "kb"],
  ];
  for (const [scale, unit] of units) {
    if (bp >= scale) {
      const v = bp / scale;
      const digits = v >= 100 ? 0 : v >= 10 ? 1 : 2;
      return `${v.toFixed(digits)} ${unit}`;
    }
  }
  return `${fmt(bp)} bp`;
}

/** Render a live quality stat by its declared format, or an em-space dash when
 *  the subtree carried no records with that field (value === null). */
export function fmtQuality(value: number | null | undefined, fmtKind: string): string {
  if (value === null || value === undefined) return "—";
  switch (fmtKind) {
    case "percent":
      return `${fmtPct(value)}%`;
    case "basepairs":
      return fmtBp(value);
    default: // "integer"
      return fmt(Math.round(value));
  }
}
