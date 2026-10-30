import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage, get } from './api/client';

/** Fetches `url` (re-fetching when url/params change) and optionally polls. */
export function useApi(url, params, { interval = 0, enabled = true } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify(params || {});
  const alive = useRef(true);

  const load = useCallback(async (silent = false) => {
    if (!enabled || !url) return;
    if (!silent) setLoading(true);
    try {
      const result = await get(url, params);
      if (alive.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(errorMessage(e));
    } finally {
      if (alive.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, key, enabled]);

  useEffect(() => {
    alive.current = true;
    load();
    if (!interval) return () => { alive.current = false; };
    const id = setInterval(() => load(true), interval);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [load, interval]);

  return { data, error, loading, reload: load, setData };
}
