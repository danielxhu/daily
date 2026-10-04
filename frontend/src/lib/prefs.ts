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

/** Follows `data-theme` however it changes, including from another component's
 * `setTheme` — the surfaces that paint with the theme (the light field) need the
 * live value, not the one read at mount. */
export function useAppliedTheme(): Theme {
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    const root = document.documentElement;
    const read = () => setTheme(root.dataset.theme === "dark" ? "dark" : "light");
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

/** How opaque the reading sheet is over the light field. Below 0.55 the body
 * text drops under 4.5:1 against the field's extremes, so that is the floor. */
const SHEET_KEY = "daily.sheetAlpha";
export const SHEET_ALPHA_OPTIONS = [1, 0.94, 0.84, 0.7] as const;
export const DEFAULT_SHEET_ALPHA = 0.94;
const MIN_SHEET_ALPHA = 0.55;

function clampSheetAlpha(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_SHEET_ALPHA;
  return Math.min(1, Math.max(MIN_SHEET_ALPHA, value));
}

export function applyStoredSheetAlpha(): number {
  const saved = typeof window !== "undefined" ? window.localStorage.getItem(SHEET_KEY) : null;
  const alpha = saved === null ? DEFAULT_SHEET_ALPHA : clampSheetAlpha(Number(saved));
  document.documentElement.style.setProperty("--sheet-a", String(alpha));
  return alpha;
}

export function useSheetAlpha(): { sheetAlpha: number; setSheetAlpha: (a: number) => void } {
  const [sheetAlpha, setState] = useState(DEFAULT_SHEET_ALPHA);
  useEffect(() => {
    setState(applyStoredSheetAlpha());
  }, []);
  const setSheetAlpha = useCallback((a: number) => {
    const alpha = clampSheetAlpha(a);
    setState(alpha);
    document.documentElement.style.setProperty("--sheet-a", String(alpha));
    if (typeof window !== "undefined") window.localStorage.setItem(SHEET_KEY, String(alpha));
  }, []);
  return { sheetAlpha, setSheetAlpha };
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
