// A curated pool of recognizable, data-rich eukaryotic groups. Used two ways on
// the landing page: as quick-jump "Try:" chips (a diverse subset) and as the
// source for the "Surprise me" random-clade button. Every taxid here was
// verified against the live DB to resolve to the named group with real data, so
// a new user always lands somewhere interesting (never an obscure, empty node).
export interface Clade {
  taxid: number;
  label: string;
}

export const FEATURED_CLADES: Clade[] = [
  { taxid: 9443, label: "Primates" },
  { taxid: 40674, label: "Mammals" },
  { taxid: 8782, label: "Birds" },
  { taxid: 9989, label: "Rodents" },
  { taxid: 9397, label: "Bats" },
  { taxid: 9721, label: "Whales & dolphins" },
  { taxid: 7898, label: "Ray-finned fishes" },
  { taxid: 7777, label: "Sharks & rays" },
  { taxid: 8292, label: "Amphibians" },
  { taxid: 8509, label: "Lizards & snakes" },
  { taxid: 50557, label: "Insects" },
  { taxid: 7041, label: "Beetles" },
  { taxid: 7088, label: "Butterflies & moths" },
  { taxid: 7399, label: "Bees, wasps & ants" },
  { taxid: 7147, label: "Flies" },
  { taxid: 4751, label: "Fungi" },
  { taxid: 5204, label: "Mushroom fungi" },
  { taxid: 4891, label: "Yeasts" },
  { taxid: 33090, label: "Green plants" },
  { taxid: 3398, label: "Flowering plants" },
  { taxid: 4479, label: "Grasses" },
  { taxid: 4747, label: "Orchids" },
  { taxid: 3803, label: "Legumes" },
  { taxid: 6231, label: "Nematodes" },
  { taxid: 6447, label: "Molluscs" },
  { taxid: 6854, label: "Arachnids" },
  { taxid: 6683, label: "Crabs & shrimp" },
  { taxid: 6073, label: "Corals & jellyfish" },
  { taxid: 7586, label: "Echinoderms" },
  { taxid: 5794, label: "Apicomplexans" },
  { taxid: 5878, label: "Ciliates" },
  { taxid: 2836, label: "Diatoms" },
];

// A diverse subset shown as quick-jump chips in the hero — instantly recognizable
// groups spread across the tree (vertebrates, insects, fungi, plants).
export const HERO_CHIPS: Clade[] = [
  FEATURED_CLADES[1], // Mammals
  FEATURED_CLADES[2], // Birds
  FEATURED_CLADES[6], // Ray-finned fishes
  FEATURED_CLADES[10], // Insects
  FEATURED_CLADES[12], // Butterflies & moths
  FEATURED_CLADES[15], // Fungi
  FEATURED_CLADES[18], // Green plants
  FEATURED_CLADES[19], // Flowering plants
];

/** A random featured taxid, never the one the user is already looking at. */
export function pickRandomCladeTaxid(exclude?: number): number {
  const pool = FEATURED_CLADES.filter((c) => c.taxid !== exclude);
  const list = pool.length > 0 ? pool : FEATURED_CLADES;
  return list[Math.floor(Math.random() * list.length)].taxid;
}
