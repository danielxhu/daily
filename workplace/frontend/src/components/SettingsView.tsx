"use client";

import { useEffect, useState } from "react";

import { clearApiSlot, getApiSettings, saveApiSlot, type ApiSlotInput } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { WINDOW_DAY_OPTIONS, useWindowDays } from "@/lib/prefs";
import type { ApiSlotView } from "@/types/contract";

/** Model API credentials: two slots. "text" powers
 * summaries/Q&A and falls back to the built-in .env DeepSeek default; "vision"
 * is reserved for a hosted image-reading model (image notes read fine today via
 * the local on-device OCR, no key needed). Keys stay in the local database and
 * are echoed back as their last 4 characters only. */
interface SettingsViewProps {
  // injectable for tests (NFR-3), like the other views
  getFn?: typeof getApiSettings;
  saveFn?: typeof saveApiSlot;
  clearFn?: typeof clearApiSlot;
}

function LanguageSetting() {
  const { locale, setLocale } = useLocale();
  const t = useT();
  return (
    <section aria-label={t("lang.aria")} className="space-y-4">
      <div className="section-head">
        <h2 className="section-title">{t("settings.lang.title")}</h2>
        <span aria-hidden="true" className="section-rule" />
      </div>
      <div className="flex gap-2">
        {(
          [
            ["zh", "中文"],
            ["en", "English"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setLocale(value)}
            aria-pressed={locale === value}
            className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
              locale === value
                ? "border-accent bg-panel font-medium text-ink"
                : "border-line text-muted hover:bg-panel/60 hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}

/** How far back Today looks when listing what the sources published. */
function WindowSetting() {
  const { windowDays, setWindowDays } = useWindowDays();
  const t = useT();
  return (
    <section aria-label={t("settings.window.title")} className="space-y-4">
      <div className="section-head">
        <h2 className="section-title">{t("settings.window.title")}</h2>
        <span aria-hidden="true" className="section-rule" />
      </div>
      <p className="max-w-[60ch] text-sm text-muted">{t("settings.window.desc")}</p>
      <div className="flex gap-2">
        {WINDOW_DAY_OPTIONS.map((days) => (
          <button
            key={days}
            type="button"
            onClick={() => setWindowDays(days)}
            aria-pressed={windowDays === days}
            className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
              windowDays === days
                ? "border-accent bg-panel font-medium text-ink"
                : "border-line text-muted hover:bg-panel/60 hover:text-ink"
            }`}
          >
            {t("digest.window.option", { days })}
          </button>
        ))}
      </div>
    </section>
  );
}

export function SettingsView({
  getFn = getApiSettings,
  saveFn = saveApiSlot,
  clearFn = clearApiSlot,
}: SettingsViewProps = {}) {
  const t = useT();
  const [slots, setSlots] = useState<ApiSlotView[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // deliberately NOT a dep-tracked callback: `useT()` returns a fresh function
  // every render, so listing `t` (directly or via useCallback) re-arms the
  // mount effect each render — an infinite load loop (found as a vitest OOM)
  async function load() {
    try {
      setSlots((await getFn()).slots);
      setError(null);
    } catch {
      setError(t("settings.api.loadError"));
    }
  }

  useEffect(() => {
    let active = true;
    getFn()
      .then((s) => {
        if (active) {
          setSlots(s.slots);
          setError(null);
        }
      })
      .catch(() => active && setError(t("settings.api.loadError")));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is render-fresh by design
  }, [getFn]);

  // the language choice is client-side — never blocked by the API slots' load
  return (
    <div className="space-y-10">
      <LanguageSetting />
      <WindowSetting />
      {error ? (
        <p className="text-sm text-warn-fg">{error}</p>
      ) : !slots ? (
        <p className="text-sm text-muted">{t("settings.api.loading")}</p>
      ) : (
        <>
          {slots.map((slot) => (
            <SlotEditor
              key={slot.slot}
              view={slot}
              onChanged={load}
              saveFn={saveFn}
              clearFn={clearFn}
            />
          ))}
          <p className="max-w-[65ch] text-xs text-faint">{t("settings.api.privacy")}</p>
        </>
      )}
    </div>
  );
}

function SlotEditor({
  view,
  onChanged,
  saveFn,
  clearFn,
}: {
  view: ApiSlotView;
  onChanged: () => Promise<void>;
  saveFn: typeof saveApiSlot;
  clearFn: typeof clearApiSlot;
}) {
  const t = useT();
  const [draft, setDraft] = useState<ApiSlotInput>({ base_url: "", model: "", api_key: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canSave = Boolean(
    draft.base_url.trim() && draft.model.trim() && draft.api_key.trim() && !busy,
  );

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveFn(view.slot, {
        base_url: draft.base_url.trim(),
        model: draft.model.trim(),
        api_key: draft.api_key.trim(),
      });
      setDraft({ base_url: "", model: "", api_key: "" });
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("settings.api.saveError"));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setError(null);
    try {
      await clearFn(view.slot);
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("settings.api.saveError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby={`slot-${view.slot}`} className="space-y-4">
      <div className="section-head">
        <h2 id={`slot-${view.slot}`} className="section-title">
          {t(`settings.slot.${view.slot}.title`)}
        </h2>
        <span aria-hidden="true" className="section-rule" />
      </div>
      <p className="max-w-[65ch] text-sm text-muted">{t(`settings.slot.${view.slot}.desc`)}</p>

      <p className="text-sm text-ink">
        {view.source === "custom" ? (
          <>
            {t("settings.slot.current.custom")}{" "}
            <span className="mono text-xs text-muted">
              {view.base_url} · {view.model} · ····{view.key_last4}
            </span>
          </>
        ) : view.source === "env" ? (
          <>
            {t("settings.slot.current.env")}{" "}
            <span className="mono text-xs text-muted">{view.model}</span>
          </>
        ) : (
          t("settings.slot.current.empty")
        )}
      </p>

      <div className="grid max-w-xl gap-3">
        <label className="text-sm text-muted">
          {t("settings.field.baseUrl")}
          <input
            value={draft.base_url}
            onChange={(e) => setDraft((d) => ({ ...d, base_url: e.target.value }))}
            placeholder="https://api.example.com/v1"
            className="input mt-1"
          />
        </label>
        <label className="text-sm text-muted">
          {t("settings.field.model")}
          <input
            value={draft.model}
            onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value }))}
            placeholder={view.slot === "text" ? "deepseek-v4-flash" : "qwen3-vl-flash"}
            className="input mt-1"
          />
        </label>
        <label className="text-sm text-muted">
          {t("settings.field.apiKey")}
          <input
            type="password"
            value={draft.api_key}
            onChange={(e) => setDraft((d) => ({ ...d, api_key: e.target.value }))}
            autoComplete="off"
            className="input mt-1"
          />
        </label>
      </div>

      <div className="flex items-center gap-3">
        <button type="button" onClick={submit} disabled={!canSave} className="btn-primary disabled:opacity-50">
          {busy ? t("settings.saving") : t("settings.save")}
        </button>
        {view.source === "custom" && (
          <button type="button" onClick={clear} disabled={busy} className="btn-ghost">
            {t(`settings.slot.${view.slot}.clear`)}
          </button>
        )}
      </div>
      {error && <p className="text-sm text-warn-fg">{error}</p>}
    </section>
  );
}
