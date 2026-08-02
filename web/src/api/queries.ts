// Typed query functions over the generated client. Each unwraps openapi-fetch's
// { data, error, response } into the response value, throwing a readable Error
// on failure so the useAsync hook can surface it.
import { api } from "./client";
import type {
  AnnotationList,
  AnnotationSort,
  AssemblyList,
  AssemblySort,
  Breakdown,
  BucketQuality,
  CladeSummary,
  Compare,
  FilterLogic,
  MetricConfig,
  MetricFilter,
  Overview,
  QualityStatConfig,
  SortColumn,
  TargetRank,
  TaxonAbout,
  TaxonChildren,
  TaxonLineage,
  TaxonRef,
} from "./types";

function extractDetail(error: unknown): string | undefined {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e) => (e as { msg?: string }).msg)
        .filter(Boolean)
        .join("; ");
    }
  }
  return undefined;
}

function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || res.data === undefined) {
    throw new Error(extractDetail(res.error) ?? `Request failed (${res.response.status})`);
  }
  return res.data;
}

export const getMetricsConfig = async (): Promise<MetricConfig[]> =>
  unwrap(await api.GET("/metrics-config"));

// Landing-page "at a glance": global totals + a few featured groups, one request.
export const getOverview = async (): Promise<Overview> => unwrap(await api.GET("/overview"));

// Compare several groups side by side (2-6). Unknown taxids are dropped server-side.
export const getCompare = async (taxids: number[]): Promise<Compare> =>
  unwrap(await api.GET("/compare", { params: { query: { taxids: taxids.join(",") } } }));

export const getSummary = async (taxid: number): Promise<CladeSummary> =>
  unwrap(await api.GET("/clade/{taxid}/summary", { params: { path: { taxid } } }));

export const getLineage = async (taxid: number): Promise<TaxonLineage> =>
  unwrap(await api.GET("/taxon/{taxid}", { params: { path: { taxid } } }));

// Direct children of a taxon, for lazy-expanding the interactive tree. Sorted
// by species count by default; `offset` pages through a big node's children.
export interface ChildrenParams {
  sort?: SortColumn;
  limit?: number;
  offset?: number;
}

export const getChildren = async (
  taxid: number,
  params: ChildrenParams = {},
): Promise<TaxonChildren> =>
  unwrap(
    await api.GET("/taxon/{taxid}/children", {
      params: { path: { taxid }, query: params },
    }),
  );

// The decorative Wikipedia "About" summary. The endpoint returns a null body
// when the taxon has no usable article, so this resolves to null rather than
// throwing — the card is omitted, never load-bearing. (A real request failure
// still throws; the Dashboard ignores it and drops the card.)
export const getAbout = async (taxid: number): Promise<TaxonAbout | null> => {
  const { data, error, response } = await api.GET("/taxon/{taxid}/about", {
    params: { path: { taxid } },
  });
  if (error !== undefined) throw new Error(`Request failed (${response.status})`);
  return data ?? null;
};

export const searchTaxa = async (q: string, limit = 10): Promise<TaxonRef[]> =>
  unwrap(await api.GET("/search", { params: { query: { q, limit } } }));

// The annotation/assembly-quality stat chrome (BUSCO, genes, genome size, N50) —
// the analogue of getMetricsConfig for the enrichment dimension, fetched once.
export const getQualityConfig = async (): Promise<QualityStatConfig[]> =>
  unwrap(await api.GET("/quality-config"));

// Per-record drill-down: genome assemblies anywhere under a taxon, with live
// distribution stats (median genome size / contig N50). Paginated via
// limit/offset; sorted newest-first by default.
export interface AssemblyParams {
  sort?: AssemblySort;
  limit?: number;
  offset?: number;
}

export const getAssemblies = async (
  taxid: number,
  params: AssemblyParams = {},
): Promise<AssemblyList> =>
  unwrap(
    await api.GET("/taxon/{taxid}/assemblies", {
      params: { path: { taxid }, query: params },
    }),
  );

// Functional annotations under a taxon, with live annotation-quality stats
// (best BUSCO, median protein-coding gene count). Default sort surfaces the
// best-annotated genomes first.
export interface AnnotationParams {
  sort?: AnnotationSort;
  limit?: number;
  offset?: number;
}

export const getAnnotations = async (
  taxid: number,
  params: AnnotationParams = {},
): Promise<AnnotationList> =>
  unwrap(
    await api.GET("/taxon/{taxid}/annotations", {
      params: { path: { taxid }, query: params },
    }),
  );

// The breakdown (Q2) controls, matching the API's query params. `rank` is
// required; the rest carry the API's own defaults when omitted.
export interface BreakdownParams {
  rank: TargetRank;
  sort?: SortColumn;
  filter?: MetricFilter[];
  logic?: FilterLogic;
  exclude_empty?: boolean;
  limit?: number;
}

export const getBreakdown = async (
  taxid: number,
  params: BreakdownParams,
): Promise<Breakdown> =>
  unwrap(
    await api.GET("/clade/{taxid}/breakdown", {
      params: { path: { taxid }, query: params },
    }),
  );

// Per-bucket quality stats (BUSCO / median genes / genome size / N50) for a rank
// breakdown — the data map's quality lenses. Merged into the breakdown by taxid.
export const getBreakdownQuality = async (
  taxid: number,
  rank: TargetRank,
): Promise<BucketQuality[]> =>
  unwrap(
    await api.GET("/clade/{taxid}/breakdown/quality", {
      params: { path: { taxid }, query: { rank } },
    }),
  );

// Direct URL for the streamed full-breakdown TSV (a browser download, not a
// fetch). Mirrors the export endpoint's params; `filter` repeats per value,
// which is how FastAPI parses a list query param. Empties are included by
// default server-side, so `exclude_empty` is only sent when the caller sets it.
export function exportTsvUrl(taxid: number, params: BreakdownParams): string {
  const q = new URLSearchParams();
  q.set("rank", params.rank);
  if (params.sort) q.set("sort", params.sort);
  for (const f of params.filter ?? []) q.append("filter", f);
  if (params.logic) q.set("logic", params.logic);
  if (params.exclude_empty !== undefined) q.set("exclude_empty", String(params.exclude_empty));
  return `/api/clade/${taxid}/export.tsv?${q.toString()}`;
}
