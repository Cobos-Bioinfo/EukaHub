"""Rank vocabulary shared by the pipeline and the API."""

SPECIES_RANK = "species"

# Rank the build gives to species-rank NCBI taxa without a formal species name
# ("sp.", "cf.", environmental samples, crosses between species) that carry data.
# They are kept and their data counts in every total, but they are not species.
INFORMAL_SPECIES_RANK = "informal species"

# A taxon of one of these ranks, or any taxon below one, is a single unit rather
# than a clade of species.
UNIT_RANKS: tuple[str, ...] = (SPECIES_RANK, INFORMAL_SPECIES_RANK)
