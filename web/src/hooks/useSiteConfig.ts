import { useEffect, useMemo, useState } from "react";

import { getSiteConfig } from "../api/queries";
import type { SiteConfig } from "../api/types";

// Fetched once per page load and shared by every component that needs it.
let cached: SiteConfig | undefined;
let pending: Promise<SiteConfig> | undefined;

function loadSiteConfig(): Promise<SiteConfig> {
  pending ??= getSiteConfig().then(
    (config) => (cached = config),
    (err: unknown) => {
      pending = undefined; // the next component to mount retries
      throw err;
    },
  );
  return pending;
}

/** The deployment's links and curated groups, or undefined while loading or
 *  after a failed request. Callers render without it rather than waiting. */
export function useSiteConfig(): SiteConfig | undefined {
  const [config, setConfig] = useState(cached);
  useEffect(() => {
    if (config) return;
    let active = true;
    loadSiteConfig().then(
      (c) => active && setConfig(c),
      () => {},
    );
    return () => {
      active = false;
    };
  }, [config]);
  return config;
}

/** Looks up a curated group's friendly label (e.g. "Mammals" for Mammalia). */
export function useCladeLabel(): (taxid: number) => string | undefined {
  const config = useSiteConfig();
  return useMemo(() => {
    const labels = new Map(config?.groups.map((g) => [g.taxid, g.label]));
    return (taxid: number) => labels.get(taxid);
  }, [config]);
}
