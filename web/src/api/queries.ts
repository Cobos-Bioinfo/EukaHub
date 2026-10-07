// Typed query functions over the generated client. Each unwraps openapi-fetch's
// { data, error, response } into the response value, throwing a readable Error
// on failure so the useAsync hook can surface it.
import { API_BASE, api } from "./client";
import { EUKARYOTA_TAXID } from "../lib/taxonomy";
import type {
  AnnotationPage,
  AnnotationSort,
  AppConfig,
  AssemblyPage,
  AssemblySort,
  DatasetMeta,
  FilterLogic,
  MetricConfig,
  MetricFilter,
  QualityStatConfig,
  QualityStatValue,
  SortOrder,
  TargetRank,
  Taxon,
  TaxonPage,
  TaxonSort,
  TaxonStats,
  TaxonStatsPage,
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

/** A taxon with its lineage: the root first, the taxon itself last. */
export type TaxonWithLineage = Taxon & { lineage: Taxon[] };

// One taxon and its ancestors in one request: the ancestors end with the taxon.
export async function getTaxon(taxid: number): Promise<TaxonWithLineage> {
  const { results } = unwrap(
    await api.GET("/taxons/{taxid}/ancestors", { params: { path: { taxid } } }),
  );
  return { ...results[results.length - 1], lineage: results };
}

// The quality stats of the records on or below one taxon.
export const getTaxonStats = async (taxid: number): Promise<TaxonStats> =>
  unwrap(await api.GET("/taxons/{taxid}/stats", { params: { path: { taxid } } }));

// Taxa with their counts: a name search (q, or close spellings with fuzzy), a
// taxon's children (parent), the taxa of a rank under a taxon (within + rank) or
// chosen taxids. Pass a page's `next` as `cursor` for the page after it.
export interface TaxaParams {
  q?: string;
  fuzzy?: boolean;
  parent?: number;
  within?: number;
  rank?: TargetRank;
  taxids?: number[];
  filter?: MetricFilter[];
  logic?: FilterLogic;
  exclude_empty?: boolean;
  sort_by?: TaxonSort;
  sort_order?: SortOrder;
  limit?: number;
  cursor?: string;
}

export const getTaxa = async ({ taxids, ...params }: TaxaParams): Promise<TaxonPage> =>
  unwrap(
    await api.GET("/taxons", { params: { query: { ...params, taxids: taxids?.join(",") } } }),
  );

// The quality stats of the taxa getTaxa returns for the same params, page for
// page.
export const getTaxaStats = async ({ taxids, ...params }: TaxaParams): Promise<TaxonStatsPage> =>
  unwrap(
    await api.GET("/taxons/stats", {
      params: { query: { ...params, taxids: taxids?.join(",") } },
    }),
  );

const statsById = (page: TaxonStatsPage) => new Map(page.results.map((t) => [t.taxid, t.stats]));

// Direct children of a taxon, for lazy-expanding the tree, biggest first.
export const getChildren = (
  taxid: number,
  params: Pick<TaxaParams, "sort_by" | "limit" | "cursor"> = {},
): Promise<TaxonPage> => getTaxa({ parent: taxid, ...params });

/** A name-search result for the picker. */
export type SearchHit = Taxon & { has_data: boolean; similar: boolean };

// Names containing the query; when none does, close spellings (`similar`).
export async function searchTaxa(q: string, limit = 10): Promise<SearchHit[]> {
  let similar = false;
  let { results } = await getTaxa({ q, limit });
  if (results.length === 0 && q.length >= 4) {
    similar = true;
    ({ results } = await getTaxa({ q, fuzzy: true, limit }));
  }
  return results.map((t) => ({
    ...t,
    has_data: Object.values(t.resources).some((r) => r.total > 0),
    similar,
  }));
}

/** Landing-page "at a glance": Eukaryota's totals and the featured groups. */
export interface Overview {
  totals: {
    species: number;
    assemblies: number;
    annotations: number;
    rna_seq: number;
    long_read: number;
    reference_genomes: number;
  };
  featured: FeaturedClade[];
}

export interface FeaturedClade {
  taxid: number;
  name: string;
  species: number;
  assemblies: number;
  assembly_percent: number;
  annotation_percent: number;
}

// One request for Eukaryota and the deployment's featured groups (in config order).
export async function getOverview(): Promise<Overview> {
  const featured = (await getConfig()).groups.filter((g) => g.featured).map((g) => g.taxid);
  const taxids = [EUKARYOTA_TAXID, ...featured];
  const { results } = await getTaxa({ taxids, limit: taxids.length });
  const byId = new Map(results.map((t) => [t.taxid, t]));
  const root = byId.get(EUKARYOTA_TAXID);
  if (!root) throw new Error("Eukaryota is missing from the dataset");
  return {
    totals: {
      species: root.n_rows,
      assemblies: root.resources.ass.total,
      annotations: root.resources.ann.total,
      rna_seq: root.resources.rna.total,
      long_read: root.resources.lng.total,
      reference_genomes: root.composition.reference,
    },
    featured: featured.flatMap((taxid) => {
      const t = byId.get(taxid);
      return t
        ? [
            {
              taxid,
              name: t.name,
              species: t.n_rows,
              assemblies: t.resources.ass.total,
              assembly_percent: t.resources.ass.percent,
              annotation_percent: t.resources.ann.percent,
            },
          ]
        : [];
    }),
  };
}

/** One group in the compare view: its counts and quality stats. */
export type CompareGroup = Taxon & { quality: QualityStatValue[] };

// Several groups side by side, in the order given; unknown taxids are dropped.
export async function getCompare(taxids: number[]): Promise<{ groups: CompareGroup[] }> {
  if (taxids.length === 0) return { groups: [] };
  const params = { taxids, limit: taxids.length };
  const [{ results }, stats] = await Promise.all([getTaxa(params), getTaxaStats(params)]);
  const byId = new Map(results.map((t) => [t.taxid, t]));
  const quality = statsById(stats);
  return {
    groups: taxids.flatMap((id) => {
      const t = byId.get(id);
      return t ? [{ ...t, quality: quality.get(id) ?? [] }] : [];
    }),
  };
}

/** One group on the gaps leaderboard: its species still missing a resource. */
export interface GapItem {
  taxid: number;
  name: string;
  rank: string;
  n_rows: number;
  covered: number; // species with the resource
  percent: number; // covered / n_rows * 100
  gap: number; // n_rows - covered
  stats: QualityStatValue[];
}

// The biggest under-sequenced groups ("Where are the gaps?"): the taxa of `rank`
// under `root` with the most species missing `resource` data, largest first.
export interface GapsParams {
  root?: number;
  rank?: TargetRank;
  resource?: MetricFilter;
  limit?: number;
  include_quality?: boolean; // per-group quality stats; off for the landing teaser
}

export async function getGaps({
  root = EUKARYOTA_TAXID,
  rank = "order",
  resource = "ass",
  limit = 25,
  include_quality = true,
}: GapsParams = {}): Promise<{ root: Taxon; total_matches: number; items: GapItem[] }> {
  const params = { within: root, rank, sort_by: `gap_${resource}` as TaxonSort, limit };
  const [roots, page, stats] = await Promise.all([
    getTaxa({ taxids: [root], limit: 1 }),
    getTaxa(params),
    include_quality ? getTaxaStats(params) : null,
  ]);
  const quality = stats ? statsById(stats) : new Map<number, QualityStatValue[]>();
  const items = page.results
    .map((t) => {
      const r = t.resources[resource];
      return {
        taxid: t.taxid,
        name: t.name,
        rank: t.rank,
        n_rows: t.n_rows,
        covered: r.covered,
        percent: r.percent,
        gap: t.n_rows - r.covered,
        stats: quality.get(t.taxid) ?? [],
      };
    })
    .filter((it) => it.gap > 0);
  return { root: roots.results[0], total_matches: page.total, items };
}

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

// Record lists: assemblies or annotations on a taxon or below it, one page at a
// time. Pass a page's `next` as `cursor` for the page after it.
export interface RecordParams<Sort> {
  sort_by?: Sort;
  sort_order?: SortOrder;
  limit?: number;
  cursor?: string;
}

export const getAssemblies = async (
  within: number,
  params: RecordParams<AssemblySort> = {},
): Promise<AssemblyPage> =>
  unwrap(await api.GET("/assemblies", { params: { query: { within, ...params } } }));

export const getAnnotations = async (
  within: number,
  params: RecordParams<AnnotationSort> = {},
): Promise<AnnotationPage> =>
  unwrap(await api.GET("/annotations", { params: { query: { within, ...params } } }));

// The breakdown (Q2) controls. `rank` is required; the rest carry the API's own
// defaults when omitted.
export interface BreakdownParams {
  rank: TargetRank;
  sort?: TaxonSort;
  filter?: MetricFilter[];
  logic?: FilterLogic;
  exclude_empty?: boolean;
  limit?: number;
}

export interface Breakdown {
  total_matches: number; // taxa matching, before `limit`
  returned: number;
  items: Taxon[];
}

const breakdownQuery = (taxid: number, p: BreakdownParams): TaxaParams => ({
  within: taxid,
  rank: p.rank,
  sort_by: p.sort,
  filter: p.filter,
  logic: p.logic,
  exclude_empty: p.exclude_empty,
  limit: p.limit,
});

export async function getBreakdown(taxid: number, params: BreakdownParams): Promise<Breakdown> {
  const page = await getTaxa(breakdownQuery(taxid, params));
  return { total_matches: page.total, returned: page.results.length, items: page.results };
}

export interface BucketQuality {
  taxid: number;
  stats: QualityStatValue[];
}

// Per-tile quality stats (BUSCO / median genes / genome size / N50) for the taxa
// a breakdown with the same params returns: the data map's quality lenses,
// merged into the breakdown by taxid. Taxa without records are left out.
export async function getBreakdownQuality(
  taxid: number,
  params: BreakdownParams,
): Promise<BucketQuality[]> {
  const page = await getTaxaStats(breakdownQuery(taxid, params));
  return page.results
    .filter((t) => t.stats.some((s) => s.value !== null))
    .map((t) => ({ taxid: t.taxid, stats: t.stats }));
}

// Direct URL for the whole breakdown as TSV (a browser download, not a fetch):
// every taxon the list would page through. `filter` repeats per value, which is
// how FastAPI parses a list query param.
export function exportTsvUrl(taxid: number, params: BreakdownParams): string {
  const q = new URLSearchParams({ within: String(taxid), rank: params.rank });
  if (params.sort) q.set("sort_by", params.sort);
  for (const f of params.filter ?? []) q.append("filter", f);
  if (params.logic) q.set("logic", params.logic);
  if (params.exclude_empty !== undefined) q.set("exclude_empty", String(params.exclude_empty));
  return `${API_BASE}/taxons/report?${q.toString()}`;
}
