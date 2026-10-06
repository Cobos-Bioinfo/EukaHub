// Typed query functions over the generated client. Each unwraps openapi-fetch's
// { data, error, response } into the response value, throwing a readable Error
// on failure so the useAsync hook can surface it.
import { api } from "./client";
import type {
  AnnotationList,
  AppConfig,
  AnnotationSort,
  AssemblyList,
  AssemblySort,
  Breakdown,
  BucketQuality,
  Compare,
  DatasetMeta,
  FilterLogic,
  Gaps,
  MetricConfig,
  MetricFilter,
  Overview,
  QualityStatConfig,
  SearchHit,
  SortColumn,
  TargetRank,
  Taxon,
  TaxonChildren,
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

/** A failed API request; ``status`` tells a missing taxon (404) from a busy server. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || res.data === undefined) {
    const status = res.response.status;
    throw new ApiError(extractDetail(res.error) ?? `Request failed (${status})`, status);
  }
  return res.data;
}

// Everything the app reads once (dataset stamp, measure and quality-stat chrome,
// deployment links and groups), fetched once per page load and shared.
let config: Promise<AppConfig> | undefined;

export function getConfig(): Promise<AppConfig> {
  config ??= api
    .GET("/config")
    .then(unwrap)
    .catch((err: unknown) => {
      config = undefined; // the next caller retries
      throw err;
    });
  return config;
}

export const getMetricsConfig = async (): Promise<MetricConfig[]> => (await getConfig()).metrics;

export const getQualityConfig = async (): Promise<QualityStatConfig[]> =>
  (await getConfig()).quality_stats;

// Dataset provenance for the app-wide "Data updated" footer stamp. built_at is
// null before the first build has stamped the DB.
export const getMeta = async (): Promise<DatasetMeta> => (await getConfig()).dataset;

// Landing-page "at a glance": global totals + a few featured groups, one request.
export const getOverview = async (): Promise<Overview> => unwrap(await api.GET("/overview"));

// Compare several groups side by side (2-6). Unknown taxids are dropped server-side.
export const getCompare = async (taxids: number[]): Promise<Compare> =>
  unwrap(await api.GET("/compare", { params: { query: { taxids: taxids.join(",") } } }));

// The biggest under-sequenced groups ("Where are the gaps?"): descendant clades
// of `root` at `rank`, ranked by species missing `resource` data (largest first).
// Every param carries the API default when omitted (Eukaryota / order / ass / 25).
export interface GapsParams {
  root?: number;
  rank?: TargetRank;
  resource?: MetricFilter;
  limit?: number;
  // Attach per-clade quality stats (BUSCO / genes / genome size / N50). Off for
  // lightweight callers (the landing teaser) that only show the gap bars.
  include_quality?: boolean;
}

export const getGaps = async (params: GapsParams = {}): Promise<Gaps> =>
  unwrap(await api.GET("/gaps", { params: { query: params } }));

// One taxon: its lineage (root first, the taxon last), counts and the quality
// stats of every record under it.
export const getTaxon = async (taxid: number): Promise<Taxon> =>
  unwrap(await api.GET("/taxons/{taxid}", { params: { path: { taxid } } }));

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

/** A Wikipedia summary for a taxon's "About" card. */
export interface TaxonAbout {
  title: string; // article title (may differ from the NCBI name via a redirect)
  description: string; // short one-line descriptor ("" when Wikipedia has none)
  extract: string; // first-paragraph plain-text summary
  thumbnail: string | null;
  url: string; // the article
}

const NO_ARTICLE = new Set(["", "Unknown", "Error"]);

// The decorative Wikipedia "About" summary, fetched by the browser from the
// deployment's Wikipedia endpoint (Wikipedia allows cross-origin requests and
// asks browsers to identify the tool with Api-User-Agent). Resolves to null when
// there is no usable article; a failed request throws, and the Dashboard drops
// the card either way.
export async function getAbout(name: string | undefined): Promise<TaxonAbout | null> {
  if (name === undefined || NO_ARTICLE.has(name)) return null;
  const { wikipedia_summary_url, source_code_url } = await getConfig();
  const url = wikipedia_summary_url.replace("{title}", encodeURIComponent(name));
  const response = await fetch(url, {
    headers: { "Api-User-Agent": `EukaHub (${source_code_url})` },
    signal: AbortSignal.timeout(6000),
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  const data = await response.json();
  if (data.type === "disambiguation" || !data.extract) return null;
  return {
    title: data.title || name,
    description: data.description || "",
    extract: data.extract,
    thumbnail: data.thumbnail?.source ?? null,
    url:
      data.content_urls?.desktop?.page ??
      `${new URL(url).origin}/wiki/${encodeURIComponent(name)}`,
  };
}

export const searchTaxa = async (q: string, limit = 10): Promise<SearchHit[]> =>
  unwrap(await api.GET("/search", { params: { query: { q, limit } } }));

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

// Per-bucket quality stats (BUSCO / median genes / genome size / N50) for the
// clades a breakdown with the same params returns — the data map's quality
// lenses. Merged into the breakdown by taxid.
export const getBreakdownQuality = async (
  taxid: number,
  params: BreakdownParams,
): Promise<BucketQuality[]> =>
  unwrap(
    await api.GET("/clade/{taxid}/breakdown/quality", {
      params: { path: { taxid }, query: params },
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
