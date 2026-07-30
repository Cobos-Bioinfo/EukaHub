import { useEffect, useState } from "react";

export interface AsyncState<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

/**
 * Run an async function and track loading/data/error, re-running when `deps`
 * change. Stale results are ignored (the cleanup flag guards against a slow
 * request resolving after the inputs moved on).
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ loading: true });

  useEffect(() => {
    let active = true;
    setState({ loading: true });
    fn().then(
      (data) => active && setState({ data, loading: false }),
      (err: unknown) =>
        active &&
        setState({
          error: err instanceof Error ? err.message : String(err),
          loading: false,
        }),
    );
    return () => {
      active = false;
    };
    // `fn` is intentionally excluded — `deps` is the caller's dependency list.
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  return state;
}
