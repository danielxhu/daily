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

/** Light or dark. Written to `data-theme` on the document root, where the token
 * layer picks it up. Defaults to the OS preference until the user chooses. */
const THEME_KEY = "daily.theme";
export type Theme = "light" | "dark";

function systemTheme(): Theme {
  // matchMedia is absent in SSR and in some test environments
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyStoredTheme(): Theme {
  const saved = typeof window !== "undefined" ? window.localStorage.getItem(THEME_KEY) : null;
  const theme: Theme = saved === "dark" || saved === "light" ? saved : systemTheme();
  document.documentElement.dataset.theme = theme;
  return theme;
}

export function useTheme(): { theme: Theme; setTheme: (t: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>("light");
  useEffect(() => {
    setThemeState(applyStoredTheme());
  }, []);
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    document.documentElement.dataset.theme = t;
    if (typeof window !== "undefined") window.localStorage.setItem(THEME_KEY, t);
  }, []);
  return { theme, setTheme };
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
