// Friendly aliases for the generated component schemas, so app code imports
// `CladeSummary` instead of `components["schemas"]["CladeSummary"]`.
import type { components } from "./schema";

export type MetricConfig = components["schemas"]["MetricConfig"];
export type CladeSummary = components["schemas"]["CladeSummary"];
export type Overview = components["schemas"]["Overview"];
export type OverviewTotals = components["schemas"]["OverviewTotals"];
export type FeaturedClade = components["schemas"]["FeaturedClade"];
export type Compare = components["schemas"]["Compare"];
export type CompareGroup = components["schemas"]["CompareGroup"];
export type ResourceSummary = components["schemas"]["ResourceSummary"];
export type Breakdown = components["schemas"]["Breakdown"];
export type DatasetMeta = components["schemas"]["DatasetMeta"];
export type Gaps = components["schemas"]["Gaps"];
export type GapItem = components["schemas"]["GapItem"];
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
export type BucketQuality = components["schemas"]["BucketQuality"];

// Breakdown (Q2) query-param enums — the closed sets the API validates against.
export type TargetRank = components["schemas"]["TargetRank"];
export type SortColumn = components["schemas"]["SortColumn"];
export type MetricFilter = components["schemas"]["MetricFilter"];
export type FilterLogic = components["schemas"]["FilterLogic"];

// Per-record drill-down sort enums (assemblies / annotations lists).
export type AssemblySort = components["schemas"]["AssemblySort"];
export type AnnotationSort = components["schemas"]["AnnotationSort"];
