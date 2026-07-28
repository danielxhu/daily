"use client";

import { useCallback, useEffect, useState } from "react";

/** How far back Today looks, in days. Set in Settings, persisted locally like the
 * language choice; 30 days is the default. */
const STORAGE_KEY = "daily.windowDays";
export const WINDOW_DAY_OPTIONS = [7, 30, 90] as const;
export const DEFAULT_WINDOW_DAYS = 30;

function read(): number {
  if (typeof window === "undefined") return DEFAULT_WINDOW_DAYS;
  const saved = Number(window.localStorage.getItem(STORAGE_KEY));
  return WINDOW_DAY_OPTIONS.includes(saved as (typeof WINDOW_DAY_OPTIONS)[number])
    ? saved
    : DEFAULT_WINDOW_DAYS;
}

export function useWindowDays(): { windowDays: number; setWindowDays: (days: number) => void } {
  // default first so SSR and the first client render agree, then adopt the stored
  // value on mount (reading localStorage during render would hydrate-mismatch)
  const [windowDays, setDays] = useState(DEFAULT_WINDOW_DAYS);
  useEffect(() => {
    setDays(read());
  }, []);
  const setWindowDays = useCallback((days: number) => {
    setDays(days);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, String(days));
    }
  }, []);
  return { windowDays, setWindowDays };
}
