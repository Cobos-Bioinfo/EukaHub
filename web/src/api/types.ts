// Friendly aliases for the generated component schemas, so app code imports
// `CladeSummary` instead of `components["schemas"]["CladeSummary"]`.
import type { components } from "./schema";

export type MetricConfig = components["schemas"]["MetricConfig"];
export type CladeSummary = components["schemas"]["CladeSummary"];
export type ResourceSummary = components["schemas"]["ResourceSummary"];
export type Breakdown = components["schemas"]["Breakdown"];
export type TaxonRef = components["schemas"]["TaxonRef"];
export type TaxonLineage = components["schemas"]["TaxonLineage"];
