"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { MESSAGES } from "@/lib/messages";

export type Locale = "en" | "zh";

const STORAGE_KEY = "daily.locale";

interface LocaleCtx {
  locale: Locale;
  setLocale: (l: Locale) => void;
}

const Ctx = createContext<LocaleCtx>({ locale: "en", setLocale: () => {} });

/** Client-side i18n. Default is English (so SSR + the test suite render English and
 * every existing assertion holds); on mount it upgrades to a saved choice, else the
 * browser language. Local-only — no external service, no network. */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    const saved = typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null;
    if (saved === "en" || saved === "zh") {
      setLocaleState(saved);
    } else if (typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("zh")) {
      setLocaleState("zh");
    }
  }, []);

  // keep the document language in sync so screen readers announce the right voice
  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

  function setLocale(l: Locale) {
    setLocaleState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // storage unavailable (private mode / tests) — the in-memory choice still applies
    }
  }

  return <Ctx.Provider value={{ locale, setLocale }}>{children}</Ctx.Provider>;
}

export function useLocale(): LocaleCtx {
  return useContext(Ctx);
}

/** BCP-47 tag for `toLocale*` date/number formatting, following the app locale
 * (never the OS default — a zh UI must not show "6/5/2026"). */
export function useIntlLocale(): string {
  const { locale } = useContext(Ctx);
  return locale === "zh" ? "zh-CN" : "en-US";
}

/** Returns a `t(key, params?)` translator. Missing keys fall back to the English
 * string, then to the key itself, so a not-yet-translated string degrades gracefully
 * (shows English) rather than breaking. `{param}` placeholders are interpolated. */
export function useT() {
  const { locale } = useContext(Ctx);
  return function t(key: string, params?: Record<string, string | number>): string {
    const raw = MESSAGES[locale][key] ?? MESSAGES.en[key] ?? key;
    if (!params) return raw;
    return raw.replace(/\{(\w+)\}/g, (_m, name) =>
      name in params ? String(params[name]) : `{${name}}`,
    );
  };
}
