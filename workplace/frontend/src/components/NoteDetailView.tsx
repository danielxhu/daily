"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { noteText } from "@/components/NotePile";
import {
  ApiError,
  listKnowledgeNotes,
  localizeKnowledgeNote,
  updateKnowledgeNote,
} from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import type { KnowledgeNote } from "@/types/contract";

interface NoteDetailViewProps {
  boardId: string;
  noteId: string;
  // injectable so tests never hit the network
  notesFn?: typeof listKnowledgeNotes;
  saveFn?: typeof updateKnowledgeNote;
  localizeFn?: typeof localizeKnowledgeNote;
}

/** One saved note, open for editing: the title and the body, in the language being
 * read. A note written before the bilingual copies existed can be rendered into the
 * other language here — one explicit call, stored, after which it follows the
 * language switch. */
export function NoteDetailView({
  boardId,
  noteId,
  notesFn = listKnowledgeNotes,
  saveFn = updateKnowledgeNote,
  localizeFn = localizeKnowledgeNote,
}: NoteDetailViewProps) {
  const { locale } = useLocale();
  const t = useT();
  const lang: "zh" | "en" = locale === "en" ? "en" : "zh";
  const [note, setNote] = useState<KnowledgeNote | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<"save" | "localize" | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // the note list is the only read endpoint for a note, and it is small
  useEffect(() => {
    let alive = true;
    notesFn()
      .then((all) => {
        const found = all.find((n) => n.id === noteId) ?? null;
        if (!alive) return;
        if (found === null) {
          setError(t("note.errLoad"));
          return;
        }
        setNote(found);
      })
      .catch(() => alive && setError(t("note.errLoad")));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is render-fresh by design
  }, [notesFn, noteId]);

  // the editors follow the note and the language being read
  useEffect(() => {
    if (note === null) return;
    const shown = noteText(note, lang);
    setTitle(shown.title);
    setBody(shown.body);
  }, [note, lang]);

  const hasBoth =
    note !== null && Boolean(note.content_zh) && Boolean(note.content_en);

  const save = async () => {
    if (note === null) return;
    setBusy("save");
    setError(null);
    try {
      setNote(await saveFn(boardId, note.id, { title, content: body }, lang));
      setStatus(t("note.saved"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("note.errLoad"));
    } finally {
      setBusy(null);
    }
  };

  const localize = async () => {
    if (note === null) return;
    setBusy("localize");
    setError(null);
    try {
      setNote(await localizeFn(boardId, note.id, lang === "en" ? "zh" : "en"));
      setStatus(t("note.localized"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("note.errLoad"));
    } finally {
      setBusy(null);
    }
  };

  if (error !== null && note === null) {
    return (
      <p role="alert" className="text-sm text-bad-fg">
        {error}
      </p>
    );
  }
  if (note === null) return <p className="text-sm text-muted">{t("knowledge.loading")}</p>;

  const otherLanguage = t(lang === "en" ? "note.language.zh" : "note.language.en");

  return (
    <div className="space-y-5">
      <Link href="/knowledge" className="text-xs text-muted transition-colors hover:text-ink">
        {t("note.back")}
      </Link>

      <label className="block">
        <span className="text-xs text-faint">{t("note.title.label")}</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label={t("note.title.label")}
          className="input serif mt-1 text-[20px] tracking-[-0.014em]"
        />
      </label>

      <label className="block">
        <span className="text-xs text-faint">{t("note.body.label")}</span>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          aria-label={t("note.body.label")}
          rows={16}
          className="input mt-1 leading-relaxed"
        />
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={save} disabled={busy !== null} className="btn-primary">
          {busy === "save" ? t("note.saving") : t("note.save")}
        </button>
        {hasBoth ? (
          <span className="text-xs text-faint">{t("note.hasBoth")}</span>
        ) : (
          <button type="button" onClick={localize} disabled={busy !== null} className="btn-ghost text-xs">
            {busy === "localize"
              ? t("note.localizing")
              : t("note.localize", { language: otherLanguage })}
          </button>
        )}
      </div>

      {status && (
        <p role="status" className="text-xs text-ok-fg">
          {status}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-bad-fg">
          {error}
        </p>
      )}
      <p className="text-xs text-faint">{t("knowledge.notes.honesty")}</p>
    </div>
  );
}
