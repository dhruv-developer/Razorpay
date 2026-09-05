"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Loader<T> = () => Promise<T>;

export type Resource<T> = {
  data: T | null;
  error: string;
  loading: boolean;
  /** True while refetching over data we already have - render it stale, don't flash a skeleton. */
  refreshing: boolean;
  reload: () => Promise<void>;
  setData: (value: T | null) => void;
};

/** Fetch once on mount, keep the previous render during refetch. */
export function useResource<T>(loader: Loader<T>, deps: unknown[] = []): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const hasData = useRef(false);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    if (hasData.current) setRefreshing(true);
    else setLoading(true);
    try {
      const next = await loaderRef.current();
      setData(next);
      hasData.current = true;
      setError("");
    } catch (err: any) {
      setError(err?.message || "Request failed");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refreshing, reload, setData };
}

/** Track an async button press so it can disable itself and surface errors. */
export function useAction() {
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const run = useCallback(async (key: string, fn: () => Promise<unknown>, successMessage?: string) => {
    setBusy(key);
    setError("");
    setMessage("");
    try {
      const result = await fn();
      if (successMessage) setMessage(successMessage);
      return result;
    } catch (err: any) {
      setError(err?.message || "Request failed");
      return null;
    } finally {
      setBusy("");
    }
  }, []);

  return { busy, error, message, run, setError, setMessage };
}
