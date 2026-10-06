// Friendly aliases for the generated component schemas, so app code imports
// `Taxon` instead of `components["schemas"]["Taxon"]`.
import type { components } from "./schema";

export type MetricConfig = components["schemas"]["MetricConfig"];
export type ResourceSummary = components["schemas"]["ResourceSummary"];
export type DatasetMeta = components["schemas"]["DatasetMeta"];
export type AppConfig = components["schemas"]["AppConfig"];
export type CladeGroup = components["schemas"]["CladeGroup"];
export type TaxonRef = components["schemas"]["TaxonRef"];
export type Taxon = components["schemas"]["Taxon"];
export type TaxonPage = components["schemas"]["TaxonPage"];
export type TaxonStats = components["schemas"]["TaxonStats"];
export type TaxonStatsPage = components["schemas"]["TaxonStatsPage"];
// The counts every taxon carries, alone or in a list.
export type CladeSummary = Omit<Taxon, "context" | "has_children">;
// A taxon in the interactive tree.
export type TaxonNode = Taxon;

// Assembly-composition + quality dimension (data-model enrichment, Stage C/D).
export type AssemblyComposition = components["schemas"]["AssemblyComposition"];
export type QualityStatConfig = components["schemas"]["QualityStatConfig"];
export type QualityStatValue = components["schemas"]["QualityStatValue"];
export type AssemblyPage = components["schemas"]["AssemblyPage"];
export type AnnotationPage = components["schemas"]["AnnotationPage"];
export type AssemblyRecord = components["schemas"]["AssemblyRecord"];
export type AnnotationRecord = components["schemas"]["AnnotationRecord"];

// Breakdown (Q2) query-param enums — the closed sets the API validates against.
export type TargetRank = components["schemas"]["TargetRank"];
export type MetricFilter = components["schemas"]["MetricFilter"];
export type TaxonSort = components["schemas"]["TaxonSort"];
export type FilterLogic = components["schemas"]["FilterLogic"];

// Per-record drill-down sort enums (assemblies / annotations lists).
export type AssemblySort = components["schemas"]["AssemblySort"];
export type AnnotationSort = components["schemas"]["AnnotationSort"];
export type SortOrder = components["schemas"]["SortOrder"];
