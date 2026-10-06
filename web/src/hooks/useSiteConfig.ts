import { useEffect, useMemo, useState } from "react";

import { getConfig } from "../api/queries";
import type { AppConfig } from "../api/types";

let cached: AppConfig | undefined;

/** The deployment's links and curated groups, or undefined while loading or
 *  after a failed request. Callers render without it rather than waiting. */
export function useSiteConfig(): AppConfig | undefined {
  const [config, setConfig] = useState(cached);
  useEffect(() => {
    if (config) return;
    let active = true;
    getConfig().then(
      (c) => active && setConfig((cached = c)),
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
