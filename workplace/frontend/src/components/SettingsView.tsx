"use client";

import { useEffect, useState } from "react";

import { clearApiSlot, getApiSettings, saveApiSlot, type ApiSlotInput } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { ApiSlotView } from "@/types/contract";

/** Model API credentials (owner 2026-07-23): two slots. "text" powers
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

  if (error) return <p className="text-sm text-warn-fg">{error}</p>;
  if (!slots) return <p className="text-sm text-muted">{t("settings.api.loading")}</p>;

  return (
    <div className="space-y-10">
      {slots.map((slot) => (
        <SlotEditor key={slot.slot} view={slot} onChanged={load} saveFn={saveFn} clearFn={clearFn} />
      ))}
      <p className="max-w-[65ch] text-xs text-faint">{t("settings.api.privacy")}</p>
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
