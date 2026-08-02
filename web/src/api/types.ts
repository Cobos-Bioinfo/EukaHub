// Friendly aliases for the generated component schemas, so app code imports
// `CladeSummary` instead of `components["schemas"]["CladeSummary"]`.
import type { components } from "./schema";

export type MetricConfig = components["schemas"]["MetricConfig"];
export type CladeSummary = components["schemas"]["CladeSummary"];
export type ResourceSummary = components["schemas"]["ResourceSummary"];
export type Breakdown = components["schemas"]["Breakdown"];
export type TaxonRef = components["schemas"]["TaxonRef"];
export type TaxonLineage = components["schemas"]["TaxonLineage"];
export type TaxonAbout = components["schemas"]["TaxonAbout"];
export type TaxonNode = components["schemas"]["TaxonNode"];
export type TaxonChildren = components["schemas"]["TaxonChildren"];

// Assembly-composition + quality dimension (data-model enrichment, Stage C/D).
export type AssemblyComposition = components["schemas"]["AssemblyComposition"];
export type QualityStatConfig = components["schemas"]["QualityStatConfig"];
export type QualityStatValue = components["schemas"]["QualityStatValue"];
export type AssemblyList = components["schemas"]["AssemblyList"];
export type AnnotationList = components["schemas"]["AnnotationList"];
export type AssemblyRecord = components["schemas"]["AssemblyRecord"];
export type AnnotationRecord = components["schemas"]["AnnotationRecord"];

// Breakdown (Q2) query-param enums — the closed sets the API validates against.
export type TargetRank = components["schemas"]["TargetRank"];
export type SortColumn = components["schemas"]["SortColumn"];
export type MetricFilter = components["schemas"]["MetricFilter"];
export type FilterLogic = components["schemas"]["FilterLogic"];

// Per-record drill-down sort enums (assemblies / annotations lists).
export type AssemblySort = components["schemas"]["AssemblySort"];
export type AnnotationSort = components["schemas"]["AnnotationSort"];
