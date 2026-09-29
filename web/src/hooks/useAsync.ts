import { useCallback, useEffect, useState } from "react";

export interface AsyncState<T> {
  data?: T;
  error?: string;
  loading: boolean;
  /** Run the request again with the same inputs (e.g. after a 503/504). */
  reload: () => void;
}

type Result<T> = Omit<AsyncState<T>, "reload"> & { key?: string };
const LOADING: Result<never> = { loading: true };

/**
 * Run `fn` and track loading/data/error, re-running when `deps` change.
 * A result is only ever returned for the deps it was fetched with, so callers
 * never render (or fetch from) the previous inputs' data.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [attempt, setAttempt] = useState(0);
  const key = `${JSON.stringify(deps)}#${attempt}`;
  const [state, setState] = useState<Result<T>>(LOADING);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let active = true;
    setState({ loading: true, key });
    fn().then(
      (data) => active && setState({ data, loading: false, key }),
      (err: unknown) =>
        active &&
        setState({
          error: err instanceof Error ? err.message : String(err),
          loading: false,
          key,
        }),
    );
    return () => {
      active = false;
    };
    // `fn` is a fresh closure every render; `key` captures what it depends on.
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  return { ...(state.key === key ? state : LOADING), reload };
}
