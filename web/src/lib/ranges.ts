// Colour ranges for a share (of species with data, or of assemblies at chromosome
// level): none, then five fixed steps of one sequential ramp, the same for every
// measure. Most shares sit under 25%, so fixed edges keep the low end readable
// where a 0-100% ramp washes it out. The colours are the --range-* tokens in
// index.css, one set per theme.

export const RANGE_LABELS = [
  "None",
  "Under 1%",
  "1 to 5%",
  "5 to 20%",
  "20 to 50%",
  "50% or more",
] as const;

/** The range of a share in percent: 0 for none (or no value), else 1 to 5. */
export function rangeOf(pct: number | null): number {
  if (pct === null || pct <= 0) return 0;
  if (pct < 1) return 1;
  if (pct < 5) return 2;
  if (pct < 20) return 3;
  if (pct < 50) return 4;
  return 5;
}

/** Fill and text colour for a range, from the theme's tokens. */
export function rangeStyle(range: number): { background: string; color: string } {
  return { background: `var(--range-${range})`, color: `var(--range-${range}-ink)` };
}
