// Theme-aware sequential colour ramp for magnitude/coverage encodings (dataviz
// skill: one hue, light→dark). Extracted from RadialTree so the breakdown map
// and the tree share one ramp. Coverage is heavily right-skewed (most clades sit
// at 0–10%, a few reach 100%), so we gamma-spread the low end before mapping.

export type RGB = [number, number, number];

const WHITE: RGB = [255, 255, 255];
const BLACK: RGB = [0, 0, 0];
const DARK_SURF: RGB = [23, 27, 33]; // matches --card (dark)

export const NO_DATA_LIGHT = "#d3d8df"; // pale slate, recessive on white
export const NO_DATA_DARK = "#333a44"; // dim slate, recessive on the dark surface

const hexRgb = (h: string): RGB => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];
export const rgbStr = (c: RGB): string => `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
const mix = (c: RGB, t: RGB, f: number): RGB =>
  [0, 1, 2].map((i) => Math.round(c[i] + (t[i] - c[i]) * f)) as RGB;

/** A hue's sequential ramp, anchored for the theme: light canvas runs
 *  faint→hue→dark (more ink = more), dark canvas runs dim→hue→bright. */
export function buildRamp(hex: string, dark: boolean): RGB[] {
  const c = hexRgb(hex);
  return dark
    ? [mix(c, DARK_SURF, 0.45), c, mix(c, WHITE, 0.5)]
    : [mix(c, WHITE, 0.85), c, mix(c, BLACK, 0.28)];
}

/** Map a 0–100 percentage to an RGB tuple along `ramp`, gamma-spreading the low
 *  end. Returns the ramp's faint end at exactly 0. */
export function rampRgb(pct: number, ramp: RGB[]): RGB {
  if (pct <= 0) return ramp[0];
  const t = Math.min(1, Math.pow(pct / 100, 0.35));
  const x = t * (ramp.length - 1);
  const i = Math.min(ramp.length - 2, Math.floor(x));
  return mix(ramp[i], ramp[i + 1], x - i);
}

/** Relative luminance (sRGB approximation) — for picking ink that reads on a fill. */
export function luminance([r, g, b]: RGB): number {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}
