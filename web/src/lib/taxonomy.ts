// Mirrors eukahub_core.taxonomy.

// The dataset covers Eukaryota; a TaxID outside it is rejected.
export const EUKARYOTA_TAXID = 2759;

// The NCBI root and "cellular organisms", stored above Eukaryota but never shown.
export const SPINE_TAXIDS: ReadonlySet<number> = new Set([1, 131567]);

// The rank the build gives to species-rank taxa without a formal species name
// that carry data. They are not counted as species.
export const INFORMAL_SPECIES_RANK = "informal species";
