// Typed query functions over the generated client. Each unwraps openapi-fetch's
// { data, error, response } into the response value, throwing a readable Error
// on failure so the useAsync hook can surface it.
import { api } from "./client";
import type { CladeSummary, MetricConfig, TaxonLineage, TaxonRef } from "./types";

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

export const getSummary = async (taxid: number): Promise<CladeSummary> =>
  unwrap(await api.GET("/clade/{taxid}/summary", { params: { path: { taxid } } }));

export const getLineage = async (taxid: number): Promise<TaxonLineage> =>
  unwrap(await api.GET("/taxon/{taxid}", { params: { path: { taxid } } }));

export const searchTaxa = async (q: string, limit = 10): Promise<TaxonRef[]> =>
  unwrap(await api.GET("/search", { params: { query: { q, limit } } }));
