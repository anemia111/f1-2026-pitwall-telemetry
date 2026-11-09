import { useEffect, useState } from 'react';

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const info = await res.json().catch(() => ({}));
    throw new Error(typeof info.detail === 'string' ? info.detail : `HTTP ${res.status}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const post = <T,>(path: string, body?: object) => request<T>(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: body ? JSON.stringify(body) : undefined,
});

export function useQuery<T>(path: string | null, refresh = 0): [T | null, string | null] {
  const [value, set] = useState<T | null>(null);
  const [error, fail] = useState<string | null>(null);
  useEffect(() => {
    set(null);
    fail(null);
  }, [path]);
  useEffect(() => {
    if (!path) return;
    const ctl = new AbortController();
    let timeout: number | undefined;
    async function fetchLatest() {
      try {
        const data = await request<T>(path!, { signal: ctl.signal });
        if (!ctl.signal.aborted) { set(data); fail(null); }
      } catch (e) {
        if (!ctl.signal.aborted) fail(String(e));
      } finally {
        if (refresh && !ctl.signal.aborted) timeout = window.setTimeout(fetchLatest, refresh);
      }
    }
    void fetchLatest();
    return () => { ctl.abort(); clearTimeout(timeout); };
  }, [path, refresh]);
  return [value, error];
}

export const n = (x: number | undefined | null, digits = 0) =>
  x == null || !Number.isFinite(x) ? 'N/A' : x.toFixed(digits);
export function lapTime(ms: number | undefined | null): string {
  if (!ms || ms <= 0) return 'N/A';
  const value = Math.round(ms);
  const min = Math.floor(value / 60000);
  return `${min}:${(Math.floor(value / 1000) % 60).toString().padStart(2, '0')}.${(value % 1000).toString().padStart(3, '0')}`;
}
export function seconds(ms: number | undefined | null, digits = 3): string {
  return n(ms == null ? ms : ms / 1000, digits);
}
export const clock = (s: number) => `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, '0')}`;
